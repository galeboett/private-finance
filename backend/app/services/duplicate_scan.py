from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import AuditEvent, DuplicatePairDecision, RefundLink, Transaction, TransferLink
from .dedupe import is_categorized_history_reference, normalize_transaction_description
from .mutation_log import MutationChange, changed_values, journal_mutation
from .transaction_queries import live_transaction_select


MAX_SCAN_PAIRS = 500
TIER_PRIORITY = {"cross_source": 0, "mirrored": 1, "exact": 2, "probable": 3}


@dataclass(frozen=True)
class LedgerDuplicateCandidate:
    candidate: Transaction
    original: Transaction
    tier: str
    similarity: float


def scan_ledger_duplicates(db: Session, *, actor: str) -> dict:
    migrated = migrate_keep_both_decisions(db)
    rows = db.scalars(live_transaction_select()).all()
    reviewed_groups = _keep_both_group_roots(db)
    already_flagged = {row.id for row in rows if row.review_status == "possible_duplicate"}
    already_flagged.update(row.duplicate_of_transaction_id for row in rows if row.review_status == "possible_duplicate" and row.duplicate_of_transaction_id is not None)
    changes: list[MutationChange] = []
    cleared_reviewed = 0
    for row in rows:
        if (
            row.review_status == "possible_duplicate"
            and row.duplicate_of_transaction_id is not None
            and _same_reviewed_group(row.id, row.duplicate_of_transaction_id, reviewed_groups)
        ):
            before = changed_values(row, ["duplicate_of_transaction_id", "review_status"])
            row.duplicate_of_transaction_id = None
            row.review_status = "needs_review"
            changes.append(MutationChange(row.id, before, changed_values(row, ["duplicate_of_transaction_id", "review_status"]), entity_type="transaction"))
            cleared_reviewed += 1
    linked_ids = _confirmed_linked_ids(db)
    excluded_ids = already_flagged | linked_ids
    eligible = [row for row in rows if row.id not in excluded_ids]

    proposals: dict[tuple[int, int], LedgerDuplicateCandidate] = {}
    same_amount_groups: dict[tuple[int, object, int], list[Transaction]] = defaultdict(list)
    mirrored_groups: dict[tuple[int, object, int, str], list[Transaction]] = defaultdict(list)
    for row in eligible:
        same_amount_groups[(row.account_id, row.transaction_date, row.amount_cents)].append(row)
        mirrored_groups[(row.account_id, row.transaction_date, abs(row.amount_cents), normalize_transaction_description(row.raw_description))].append(row)

    for group in same_amount_groups.values():
        for left, right in combinations(sorted(group, key=lambda row: row.id), 2):
            tier, similarity = classify_duplicate_pair(left, right)
            if tier not in {"cross_source", "exact", "probable"}:
                continue
            if tier == "cross_source":
                original, candidate = (left, right) if is_categorized_history_reference(left.source_reference) else (right, left)
            else:
                original, candidate = (left, right) if left.id < right.id else (right, left)
            _add_proposal(proposals, reviewed_groups, LedgerDuplicateCandidate(candidate, original, tier, similarity))

    for group in mirrored_groups.values():
        positives = [row for row in group if row.amount_cents > 0 and row.transaction_type == "refund"]
        negatives = [row for row in group if row.amount_cents < 0]
        for positive in positives:
            for negative in negatives:
                _add_proposal(proposals, reviewed_groups, LedgerDuplicateCandidate(positive, negative, "mirrored", 1.0))

    selected: list[LedgerDuplicateCandidate] = []
    used_ids: set[int] = set()
    ordered = sorted(proposals.values(), key=lambda item: (TIER_PRIORITY[item.tier], item.candidate.transaction_date, min(item.candidate.id, item.original.id)))
    for proposal in ordered:
        if proposal.candidate.id in used_ids or proposal.original.id in used_ids:
            continue
        selected.append(proposal)
        used_ids.update((proposal.candidate.id, proposal.original.id))
        if len(selected) >= MAX_SCAN_PAIRS:
            break

    counts = {tier: 0 for tier in TIER_PRIORITY}
    for proposal in selected:
        before = changed_values(proposal.candidate, ["duplicate_of_transaction_id", "review_status"])
        proposal.candidate.duplicate_of_transaction_id = proposal.original.id
        proposal.candidate.review_status = "possible_duplicate"
        changes.append(MutationChange(proposal.candidate.id, before, changed_values(proposal.candidate, ["duplicate_of_transaction_id", "review_status"]), entity_type="transaction"))
        counts[proposal.tier] += 1

    operation_id = journal_mutation(
        db,
        kind="scan",
        entity_type="transaction",
        actor=actor,
        description=(
            f"Flagged {len(selected)} ledger duplicate pairs and cleared {cleared_reviewed} previously reviewed pairs"
            if cleared_reviewed
            else f"Flagged {len(selected)} ledger duplicate pairs"
        ),
        changes=changes,
    ) if changes else None
    record_audit_event(db, "duplicate_ledger_scan", actor, "transactions", f"scan:{len(selected)}", {"counts": counts, "migrated_keep_both": migrated, "cleared_reviewed": cleared_reviewed, "limited": len(selected) == MAX_SCAN_PAIRS, "operation_id": operation_id})
    return {"flagged": len(selected), "counts": counts, "migrated_keep_both": migrated, "cleared_reviewed": cleared_reviewed, "limit": MAX_SCAN_PAIRS, "limited": len(selected) == MAX_SCAN_PAIRS, "operation_id": operation_id}


def classify_duplicate_pair(left: Transaction, right: Transaction) -> tuple[str, float]:
    if left.account_id != right.account_id or left.transaction_date != right.transaction_date:
        return "import", 0.0
    left_description = normalize_transaction_description(left.raw_description)
    right_description = normalize_transaction_description(right.raw_description)
    if left.amount_cents == -right.amount_cents and left_description == right_description and ({left.transaction_type, right.transaction_type} & {"refund"}):
        return "mirrored", 1.0
    if left.amount_cents != right.amount_cents:
        return "import", 0.0
    if left_description == right_description:
        history_left = is_categorized_history_reference(left.source_reference)
        history_right = is_categorized_history_reference(right.source_reference)
        other_reference = right.source_reference if history_left else left.source_reference
        if history_left != history_right and bool(other_reference):
            return "cross_source", 1.0
        return "exact", 1.0
    similarity = SequenceMatcher(None, left_description, right_description).ratio()
    return ("probable", similarity) if similarity >= 0.85 else ("import", similarity)


def migrate_keep_both_decisions(db: Session) -> int:
    existing = {
        (decision.transaction_a_id, decision.transaction_b_id)
        for decision in db.scalars(select(DuplicatePairDecision)).all()
    }
    migrated = 0
    events = db.scalars(select(AuditEvent).where(AuditEvent.event_type == "duplicate_resolve").order_by(AuditEvent.id)).all()
    for event in events:
        try:
            details = json.loads(event.details_json)
            candidate_id = int(event.entity_id)
            original_id = int(details.get("original_transaction_id"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if details.get("action") != "keep_both":
            continue
        pair = normalized_pair(candidate_id, original_id)
        if pair in existing or not db.get(Transaction, pair[0]) or not db.get(Transaction, pair[1]):
            continue
        db.add(DuplicatePairDecision(transaction_a_id=pair[0], transaction_b_id=pair[1], decision="keep_both"))
        existing.add(pair)
        migrated += 1
    if migrated:
        db.flush()
    return migrated


def normalized_pair(left_id: int, right_id: int) -> tuple[int, int]:
    return (left_id, right_id) if left_id < right_id else (right_id, left_id)


def _add_proposal(proposals: dict[tuple[int, int], LedgerDuplicateCandidate], reviewed_groups: dict[int, int], proposal: LedgerDuplicateCandidate) -> None:
    pair = normalized_pair(proposal.candidate.id, proposal.original.id)
    if _same_reviewed_group(pair[0], pair[1], reviewed_groups):
        return
    current = proposals.get(pair)
    if current is None or TIER_PRIORITY[proposal.tier] < TIER_PRIORITY[current.tier]:
        proposals[pair] = proposal


def _keep_both_group_roots(db: Session) -> dict[int, int]:
    parent: dict[int, int] = {}

    def find(transaction_id: int) -> int:
        parent.setdefault(transaction_id, transaction_id)
        while parent[transaction_id] != transaction_id:
            parent[transaction_id] = parent[parent[transaction_id]]
            transaction_id = parent[transaction_id]
        return transaction_id

    def union(left_id: int, right_id: int) -> None:
        left_root = find(left_id)
        right_root = find(right_id)
        if left_root != right_root:
            parent[right_root] = left_root

    decisions = db.scalars(select(DuplicatePairDecision).where(DuplicatePairDecision.decision == "keep_both")).all()
    for decision in decisions:
        union(decision.transaction_a_id, decision.transaction_b_id)
    return {transaction_id: find(transaction_id) for transaction_id in parent}


def _same_reviewed_group(left_id: int, right_id: int, reviewed_groups: dict[int, int]) -> bool:
    return left_id in reviewed_groups and right_id in reviewed_groups and reviewed_groups[left_id] == reviewed_groups[right_id]


def _confirmed_linked_ids(db: Session) -> set[int]:
    ids: set[int] = set()
    for link in db.scalars(select(TransferLink).where(TransferLink.confirmed.is_(True))).all():
        ids.update((link.from_transaction_id, link.to_transaction_id))
    for link in db.scalars(select(RefundLink).where(RefundLink.confirmed.is_(True))).all():
        ids.update((link.expense_transaction_id, link.refund_transaction_id))
    return ids
