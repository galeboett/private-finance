from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import Account, Category, DuplicatePairDecision, ExpenseAllocation, ImportBatch, RefundLink, Transaction, TransactionSplit
from .dedupe import is_categorized_history_reference, normalize_transaction_description
from .duplicate_scan import classify_duplicate_pair, normalized_pair
from .mutation_log import MutationChange, changed_values, full_values, journal_mutation


COMPARED_FIELDS = ("account", "reference", "date", "amount", "description", "category", "notes", "labels", "import_source")
BANK_FIELDS = ("transaction_date", "posted_date", "amount_cents", "currency", "raw_description", "normalized_payee", "source_reference", "running_balance_cents")
NEW_IMPORT_FIELDS = (*BANK_FIELDS, "import_batch_id", "source_ordinal")
AUTHORITATIVE_HISTORY_FIELDS = (*NEW_IMPORT_FIELDS, "category_id", "transaction_type", "review_status")


def pending_duplicate_pairs(db: Session, *, limit: int | None = None, offset: int = 0, tier_filter: str | None = None, account_id: int | None = None) -> list[dict[str, Any]]:
    candidate_query = (
        select(Transaction).where(
            Transaction.deleted_at.is_(None),
            Transaction.status == "active",
            Transaction.review_status == "possible_duplicate",
            Transaction.duplicate_of_transaction_id.is_not(None),
        ).order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
    )
    if account_id is not None:
        candidate_query = candidate_query.where(Transaction.account_id == account_id)
    paged_in_query = limit is not None and tier_filter is None
    if paged_in_query:
        candidate_query = candidate_query.offset(offset).limit(limit)
    candidates = db.scalars(candidate_query).all()
    if not candidates:
        return []
    original_ids = {candidate.duplicate_of_transaction_id for candidate in candidates if candidate.duplicate_of_transaction_id is not None}
    originals = {
        transaction.id: transaction
        for transaction in db.scalars(
            select(Transaction).where(
                Transaction.id.in_(original_ids),
                Transaction.deleted_at.is_(None),
                Transaction.status == "active",
            )
        ).all()
    }
    account_ids = {candidate.account_id for candidate in candidates} | {row.account_id for row in originals.values()}
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.id.in_(account_ids))).all()}
    category_ids = {row.category_id for row in [*candidates, *originals.values()] if row.category_id is not None}
    categories = {category.id: category for category in db.scalars(select(Category).where(Category.id.in_(category_ids))).all()} if category_ids else {}
    batch_ids = {row.import_batch_id for row in [*candidates, *originals.values()] if row.import_batch_id is not None}
    batches = {batch.id: batch for batch in db.scalars(select(ImportBatch).where(ImportBatch.id.in_(batch_ids))).all()} if batch_ids else {}
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        original = originals.get(candidate.duplicate_of_transaction_id)
        if original is None:
            continue
        candidate_payload = _transaction_payload(candidate, accounts, categories, batches)
        original_payload = _transaction_payload(original, accounts, categories, batches)
        diff_fields = [field for field in COMPARED_FIELDS if candidate_payload[field] != original_payload[field]]
        tier, similarity = classify_duplicate_pair(candidate, original)
        exact_match = not diff_fields or tier in {"exact", "cross_source"}
        safe_reimport = _is_safe_reimport(candidate, original, tier=tier)
        results.append({"candidate": candidate_payload, "original": original_payload, "diff_fields": diff_fields, "exact_match": exact_match, "safe_reimport": safe_reimport, "tier": tier, "similarity": round(similarity, 3)})
    if tier_filter:
        results = [pair for pair in results if pair["tier"] == tier_filter]
    if paged_in_query:
        return results
    return results[offset:offset + limit] if limit is not None else results[offset:]


def duplicate_queue_summary(db: Session, *, account_id: int | None = None) -> dict[str, Any]:
    pairs = pending_duplicate_pairs(db, account_id=account_id)
    counts = {name: 0 for name in ("cross_source", "exact", "probable", "mirrored", "import")}
    for pair in pairs:
        counts[pair["tier"]] += 1
    return {
        "total": len(pairs),
        "counts": counts,
        "safe_reimports": sum(1 for pair in pairs if pair["safe_reimport"]),
        "historical_refunds": len(_historical_refund_pairs(db)),
    }


def preview_historical_refund_links(db: Session) -> dict[str, Any]:
    pairs = _historical_refund_pairs(db)
    account_ids = {positive.account_id for _, positive, _ in pairs}
    accounts = {row.id: row for row in db.scalars(select(Account).where(Account.id.in_(account_ids))).all()} if account_ids else {}
    category_ids = {positive.category_id for _, positive, _ in pairs if positive.category_id is not None}
    categories = {row.id: row for row in db.scalars(select(Category).where(Category.id.in_(category_ids))).all()} if category_ids else {}
    batch_ids = {positive.import_batch_id for _, positive, _ in pairs if positive.import_batch_id is not None}
    batches = {row.id: row for row in db.scalars(select(ImportBatch).where(ImportBatch.id.in_(batch_ids))).all()} if batch_ids else {}

    account_counts = Counter(positive.account_id for _, positive, _ in pairs)
    category_counts = Counter(categories[positive.category_id].label if positive.category_id in categories else "Uncategorized" for _, positive, _ in pairs)
    source_counts = Counter(batches[positive.import_batch_id].filename if positive.import_batch_id in batches else "Unknown import" for _, positive, _ in pairs)
    token_material = [
        f"{candidate.id}:{positive.id}:{negative.id}:{positive.amount_cents}:{positive.category_id}:{positive.import_batch_id}:{positive.review_status}:{positive.duplicate_of_transaction_id}"
        for candidate, positive, negative in pairs
    ]
    dates = [positive.transaction_date for _, positive, _ in pairs]
    return {
        "selection_token": hashlib.sha256("|".join(token_material).encode("utf-8")).hexdigest(),
        "pair_count": len(pairs),
        "refund_total_cents": sum(positive.amount_cents for _, positive, _ in pairs),
        "net_change_cents": 0,
        "date_from": min(dates).isoformat() if dates else None,
        "date_to": max(dates).isoformat() if dates else None,
        "accounts": [
            {"account_id": account_id, "account": accounts[account_id].display_name if account_id in accounts else "Unknown account", "pairs": count}
            for account_id, count in account_counts.most_common()
        ],
        "categories": [{"category": label, "pairs": count} for label, count in category_counts.most_common()],
        "sources": [{"source": label, "pairs": count} for label, count in source_counts.most_common()],
        "criteria": ["same account, date, and normalized description", "equal opposite amounts", "expense plus refund", "matching category", "same categorized-history import batch"],
    }


def link_historical_refund_pairs(db: Session, *, preview_token: str, actor: str) -> dict[str, Any]:
    preview = preview_historical_refund_links(db)
    if preview_token != preview["selection_token"]:
        raise ValueError("The historical refund queue changed after preview. Review the refreshed totals before confirming.")
    pairs = _historical_refund_pairs(db)
    if not pairs:
        return {"ok": True, "linked": 0, "operation_id": None}

    changes: list[MutationChange] = []
    refund_ids: list[int] = []
    expense_ids: list[int] = []
    for candidate, positive, negative in pairs:
        link = RefundLink(
            expense_transaction_id=negative.id,
            refund_transaction_id=positive.id,
            match_confidence=100,
            confirmed=True,
        )
        db.add(link)
        db.flush()
        changes.append(MutationChange(link.id, None, full_values(link), entity_type="refund_link"))

        positive_fields = ["transaction_type", "review_status", "category_id", "duplicate_of_transaction_id"]
        positive_before = changed_values(positive, positive_fields)
        positive.transaction_type = "refund"
        positive.review_status = "confirmed"
        positive.category_id = negative.category_id
        positive.duplicate_of_transaction_id = None
        changes.append(MutationChange(positive.id, positive_before, changed_values(positive, positive_fields), entity_type="transaction"))
        if candidate.id != positive.id:
            candidate_fields = ["review_status", "duplicate_of_transaction_id"]
            candidate_before = changed_values(candidate, candidate_fields)
            candidate.review_status = "needs_review"
            candidate.duplicate_of_transaction_id = None
            changes.append(MutationChange(candidate.id, candidate_before, changed_values(candidate, candidate_fields), entity_type="transaction"))
        refund_ids.append(positive.id)
        expense_ids.append(negative.id)

    operation_id = journal_mutation(
        db,
        kind="link_refunds",
        entity_type="mixed",
        actor=actor,
        description=f"Linked {len(pairs)} intentional historical refund pairs",
        changes=changes,
    )
    record_audit_event(db, "historical_refunds_bulk_link", actor, "refund_link", f"bulk:{len(pairs)}", {
        "expense_transaction_ids": expense_ids,
        "refund_transaction_ids": refund_ids,
        "refund_total_cents": preview["refund_total_cents"],
        "operation_id": operation_id,
    })
    return {"ok": True, "linked": len(pairs), "refund_total_cents": preview["refund_total_cents"], "operation_id": operation_id}


def preview_duplicate_selection(
    db: Session,
    *,
    transaction_ids: list[int],
    action: str,
    authoritative_batch_id: int | None = None,
) -> dict[str, Any]:
    selected = _selected_duplicate_pairs(db, transaction_ids)
    if action not in {"keep_both", "remove_new", "prefer_authoritative_history"}:
        raise ValueError("Choose keep_both, remove_new, or prefer_authoritative_history")
    account_ids = {candidate.account_id for candidate, _, _ in selected}
    accounts = {row.id: row for row in db.scalars(select(Account).where(Account.id.in_(account_ids))).all()} if account_ids else {}
    batch_ids = {row.import_batch_id for candidate, original, _ in selected for row in (candidate, original) if row.import_batch_id is not None}
    batches = {row.id: row for row in db.scalars(select(ImportBatch).where(ImportBatch.id.in_(batch_ids))).all()} if batch_ids else {}
    authoritative_batch = batches.get(authoritative_batch_id) if authoritative_batch_id is not None else None
    if action == "prefer_authoritative_history":
        if authoritative_batch is None:
            raise ValueError("Choose the imported batch that should be treated as authoritative.")
        ineligible = [
            candidate.id
            for candidate, original, _ in selected
            if (original.import_batch_id is not None and original.import_batch_id in batches)
            or candidate.import_batch_id != authoritative_batch.id
        ]
        if ineligible:
            raise ValueError(
                f'Prefer authoritative history requires Manual entry on the established side and "{authoritative_batch.filename}" on the imported side for every selected pair.'
            )
    elif authoritative_batch_id is not None:
        raise ValueError("An authoritative batch is only valid with prefer_authoritative_history.")
    account_counts = Counter(candidate.account_id for candidate, _, _ in selected)
    tier_counts = Counter(tier for _, _, tier in selected)
    source_counts = Counter(_source_label(candidate, batches) for candidate, _, _ in selected)
    original_ids = [original.id for _, original, _ in selected]
    splits = db.scalars(select(TransactionSplit).where(TransactionSplit.transaction_id.in_(original_ids))).all()
    allocations = db.scalars(select(ExpenseAllocation).where(ExpenseAllocation.transaction_id.in_(original_ids))).all()
    annotation_summary = {
        "notes": sum(1 for _, original, _ in selected if original.user_note),
        "labels": sum(1 for _, original, _ in selected if original.labels),
        "splits": len(splits),
        "allocations": len(allocations),
    }
    token_material = [
        action,
        f"authoritative_batch_id:{authoritative_batch_id}",
        "splits:" + ",".join(f"{row.id}:{row.transaction_id}:{row.category_id}:{row.amount_cents}:{row.note}" for row in splits),
        "allocations:" + ",".join(f"{row.id}:{row.transaction_id}:{row.category_id}:{row.allocation_date}:{row.amount_cents}" for row in allocations),
    ]
    for candidate, original, tier in selected:
        candidate_state = ":".join(f"{field}={getattr(candidate, field)!r}" for field in AUTHORITATIVE_HISTORY_FIELDS)
        original_state = ":".join(f"{field}={getattr(original, field)!r}" for field in AUTHORITATIVE_HISTORY_FIELDS)
        token_material.append(
            f"{candidate.id}:{original.id}:{tier}:{candidate_state}:{candidate.user_note!r}:{candidate.labels!r}:{candidate.duplicate_of_transaction_id}:{candidate.deleted_at}:"
            f"{original_state}:{original.user_note!r}:{original.labels!r}:{original.deleted_at}:{_source_label(candidate, batches)}:{_source_label(original, batches)}"
        )
    dates = [candidate.transaction_date for candidate, _, _ in selected]
    retires_rows = action in {"remove_new", "prefer_authoritative_history"}
    return {
        "action": action,
        "selection_token": hashlib.sha256("|".join(token_material).encode("utf-8")).hexdigest(),
        "pair_count": len(selected),
        "tiers": dict(tier_counts),
        "rows_soft_deleted": len(selected) if retires_rows else 0,
        "decisions_saved": len(selected) if action == "keep_both" else 0,
        "balance_change_cents": -sum(candidate.amount_cents for candidate, _, _ in selected) if retires_rows else 0,
        "category_changes": sum(1 for candidate, original, _ in selected if candidate.category_id != original.category_id) if action == "prefer_authoritative_history" else 0,
        "type_changes": sum(1 for candidate, original, _ in selected if candidate.transaction_type != original.transaction_type) if action == "prefer_authoritative_history" else 0,
        "authoritative_batch_id": authoritative_batch.id if authoritative_batch else None,
        "authoritative_source": authoritative_batch.filename if authoritative_batch else None,
        "annotations_preserved": annotation_summary,
        "uses_existing_record_identity": action == "prefer_authoritative_history",
        "date_from": min(dates).isoformat() if dates else None,
        "date_to": max(dates).isoformat() if dates else None,
        "accounts": [
            {"account_id": account_id, "account": accounts[account_id].display_name if account_id in accounts else "Unknown account", "pairs": count}
            for account_id, count in account_counts.most_common()
        ],
        "sources": [{"source": source, "pairs": count} for source, count in source_counts.most_common()],
        "transaction_ids": [candidate.id for candidate, _, _ in selected],
    }


def resolve_duplicate_selection(
    db: Session,
    *,
    transaction_ids: list[int],
    action: str,
    preview_token: str,
    actor: str,
    authoritative_batch_id: int | None = None,
) -> dict[str, Any]:
    preview = preview_duplicate_selection(
        db,
        transaction_ids=transaction_ids,
        action=action,
        authoritative_batch_id=authoritative_batch_id,
    )
    if preview_token != preview["selection_token"]:
        raise ValueError("The selected duplicate pairs changed after preview. Review them again before confirming.")
    selected = _selected_duplicate_pairs(db, transaction_ids)
    deleted_at = datetime.now(UTC).replace(tzinfo=None)
    changes: list[MutationChange] = []
    for candidate, original, _ in selected:
        if action == "remove_new":
            before = changed_values(candidate, ["deleted_at"])
            candidate.deleted_at = deleted_at
            changes.append(MutationChange(candidate.id, before, changed_values(candidate, ["deleted_at"]), entity_type="transaction"))
            continue
        if action == "prefer_authoritative_history":
            original_before = changed_values(original, AUTHORITATIVE_HISTORY_FIELDS)
            for field in NEW_IMPORT_FIELDS:
                setattr(original, field, getattr(candidate, field))
            original.category_id = candidate.category_id
            original.transaction_type = candidate.transaction_type
            original.review_status = "confirmed"
            changes.append(MutationChange(original.id, original_before, changed_values(original, AUTHORITATIVE_HISTORY_FIELDS), entity_type="transaction"))
            candidate_before = changed_values(candidate, ["deleted_at"])
            candidate.deleted_at = deleted_at
            changes.append(MutationChange(candidate.id, candidate_before, changed_values(candidate, ["deleted_at"]), entity_type="transaction"))
            continue

        fields = ["duplicate_of_transaction_id", "review_status"]
        before = changed_values(candidate, fields)
        candidate.duplicate_of_transaction_id = None
        candidate.review_status = "needs_review"
        changes.append(MutationChange(candidate.id, before, changed_values(candidate, fields), entity_type="transaction"))
        transaction_a_id, transaction_b_id = normalized_pair(candidate.id, original.id)
        decision = db.scalar(select(DuplicatePairDecision).where(DuplicatePairDecision.transaction_a_id == transaction_a_id, DuplicatePairDecision.transaction_b_id == transaction_b_id))
        if decision is None:
            decision = DuplicatePairDecision(transaction_a_id=transaction_a_id, transaction_b_id=transaction_b_id, decision="keep_both")
            db.add(decision)
            db.flush()
            changes.append(MutationChange(decision.id, None, full_values(decision), entity_type="duplicate_pair_decision"))

    entity_types = {change.entity_type for change in changes}
    description = (
        f"Kept both transactions in {len(selected)} reviewed pairs"
        if action == "keep_both"
        else f'Preferred authoritative history from "{preview["authoritative_source"]}" for {len(selected)} duplicate pairs'
        if action == "prefer_authoritative_history"
        else f"Removed the new copy from {len(selected)} exact duplicate pairs"
    )
    operation_id = journal_mutation(
        db,
        kind="resolve_duplicates",
        entity_type="mixed" if len(entity_types) > 1 else "transaction",
        actor=actor,
        description=description,
        changes=changes,
    )
    record_audit_event(db, "duplicates_resolve_selection", actor, "transactions", f"bulk:{len(selected)}", {
        "transaction_ids": preview["transaction_ids"],
        "action": action,
        "authoritative_batch_id": authoritative_batch_id,
        "operation_id": operation_id,
    })
    affected_card_account = bool(db.scalar(select(Account.id).where(Account.id.in_({candidate.account_id for candidate, _, _ in selected}), Account.account_type == "credit_card").limit(1)))
    return {"ok": True, "resolved": len(selected), "action": action, "operation_id": operation_id, "affected_card_account": affected_card_account}


def preview_safe_duplicate_resolution(db: Session, *, strategy: str) -> dict[str, Any]:
    if strategy not in {"keep_existing", "use_new_import"}:
        raise ValueError("Choose keep_existing or use_new_import")
    groups = _safe_reimport_groups(db)
    candidates = [candidate for _, group_candidates in groups for candidate in group_candidates]
    selected_rows = [
        original if strategy == "keep_existing" else max(group_candidates, key=lambda row: row.id)
        for original, group_candidates in groups
    ]
    all_rows = [row for original, group_candidates in groups for row in (original, *group_candidates)]
    batch_ids = {row.import_batch_id for row in all_rows if row.import_batch_id is not None}
    batches = {batch.id: batch for batch in db.scalars(select(ImportBatch).where(ImportBatch.id.in_(batch_ids))).all()} if batch_ids else {}
    account_ids = {original.account_id for original, _ in groups}
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.id.in_(account_ids))).all()} if account_ids else {}

    account_summary: dict[int, dict[str, Any]] = {}
    for original, group_candidates in groups:
        account = accounts.get(original.account_id)
        entry = account_summary.setdefault(original.account_id, {
            "account_id": original.account_id,
            "account": account.display_name if account else "Unknown account",
            "institution": account.institution.name if account and account.institution else None,
            "pairs": 0,
            "transactions_retained": 0,
            "balance_change_cents": 0,
        })
        entry["pairs"] += len(group_candidates)
        entry["transactions_retained"] += 1
        entry["balance_change_cents"] -= sum(row.amount_cents for row in group_candidates)

    original_ids = [original.id for original, _ in groups]
    annotation_summary = {
        "categorized": sum(1 for original, _ in groups if original.category_id is not None),
        "notes": sum(1 for original, _ in groups if original.user_note),
        "labels": sum(1 for original, _ in groups if original.labels),
        "splits": 0,
        "allocations": 0,
    }
    if original_ids:
        annotation_summary["splits"] = len(db.scalars(select(TransactionSplit).where(TransactionSplit.transaction_id.in_(original_ids))).all())
        annotation_summary["allocations"] = len(db.scalars(select(ExpenseAllocation).where(ExpenseAllocation.transaction_id.in_(original_ids))).all())

    selected_sources = Counter(_source_label(row, batches) for row in selected_rows)
    retired_sources = Counter(_source_label(row, batches) for row in candidates)
    dates = [row.transaction_date for row in candidates]
    token_material = [strategy]
    for original, group_candidates in groups:
        token_material.append(
            f"{original.id}:{original.amount_cents}:{original.import_batch_id}:"
            + ",".join(f"{row.id}:{row.amount_cents}:{row.import_batch_id}" for row in group_candidates)
        )
    selection_token = hashlib.sha256("|".join(token_material).encode("utf-8")).hexdigest()
    return {
        "strategy": strategy,
        "selection_token": selection_token,
        "pair_count": len(candidates),
        "transactions_retained": len(groups),
        "rows_soft_deleted": len(candidates),
        "accounts": sorted(account_summary.values(), key=lambda row: (-row["pairs"], row["account"])),
        "account_count": len(account_summary),
        "balance_change_cents": -sum(row.amount_cents for row in candidates),
        "date_from": min(dates).isoformat() if dates else None,
        "date_to": max(dates).isoformat() if dates else None,
        "selected_sources": [{"source": source, "count": count} for source, count in selected_sources.most_common()],
        "retired_sources": [{"source": source, "count": count} for source, count in retired_sources.most_common()],
        "annotations_preserved": annotation_summary,
        "uses_existing_record_identity": True,
    }


def resolve_safe_duplicate_reimports(db: Session, *, strategy: str, preview_token: str, actor: str) -> dict[str, Any]:
    preview = preview_safe_duplicate_resolution(db, strategy=strategy)
    if preview_token != preview["selection_token"]:
        raise ValueError("The duplicate queue changed after this preview. Review the refreshed totals before confirming.")
    groups = _safe_reimport_groups(db)
    if not groups:
        return {"ok": True, "resolved": 0, "updated": 0, "operation_id": None, "affected_card_account": False}

    deleted_at = datetime.now(UTC).replace(tzinfo=None)
    changes: list[MutationChange] = []
    if strategy == "use_new_import":
        for original, group_candidates in groups:
            newest = max(group_candidates, key=lambda row: row.id)
            before = changed_values(original, NEW_IMPORT_FIELDS)
            for field in NEW_IMPORT_FIELDS:
                setattr(original, field, getattr(newest, field))
            changes.append(MutationChange(original.id, before, changed_values(original, NEW_IMPORT_FIELDS)))
    for _, group_candidates in groups:
        for candidate in group_candidates:
            before = changed_values(candidate, ["deleted_at"])
            candidate.deleted_at = deleted_at
            changes.append(MutationChange(candidate.id, before, changed_values(candidate, ["deleted_at"])))

    resolved = sum(len(group_candidates) for _, group_candidates in groups)
    description = (
        f"Kept {len(groups)} existing ledger transactions and removed {resolved} safe reimports"
        if strategy == "keep_existing"
        else f"Replaced {len(groups)} existing transactions with newer import data and removed {resolved} safe reimports"
    )
    operation_id = journal_mutation(db, kind="resolve_duplicates", entity_type="transaction", actor=actor, description=description, changes=changes)
    candidate_ids = [candidate.id for _, group_candidates in groups for candidate in group_candidates]
    record_audit_event(db, "duplicates_resolve_safe", actor, "transactions", f"bulk:{resolved}", {
        "transaction_ids": candidate_ids,
        "strategy": strategy,
        "survivor_ids": [original.id for original, _ in groups],
        "operation_id": operation_id,
    })
    account_ids = {original.account_id for original, _ in groups}
    affected_card_account = bool(db.scalar(select(Account.id).where(Account.id.in_(account_ids), Account.account_type == "credit_card").limit(1)))
    return {"ok": True, "resolved": resolved, "updated": len(groups) if strategy == "use_new_import" else 0, "operation_id": operation_id, "affected_card_account": affected_card_account}


def resolve_duplicate(db: Session, *, transaction_id: int, action: str, actor: str) -> dict[str, Any]:
    candidate, original = _duplicate_pair(db, transaction_id)
    changes: list[MutationChange] = []
    if action == "remove_new":
        before = changed_values(candidate, ["deleted_at"])
        candidate.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        changes.append(MutationChange(candidate.id, before, changed_values(candidate, ["deleted_at"])))
        description = f'Removed duplicate "{candidate.raw_description}"'
    elif action == "keep_both":
        fields = ["duplicate_of_transaction_id", "review_status"]
        before = changed_values(candidate, fields)
        candidate.duplicate_of_transaction_id = None
        candidate.review_status = "needs_review"
        changes.append(MutationChange(candidate.id, before, changed_values(candidate, fields)))
        transaction_a_id, transaction_b_id = normalized_pair(candidate.id, original.id)
        decision = db.scalar(select(DuplicatePairDecision).where(DuplicatePairDecision.transaction_a_id == transaction_a_id, DuplicatePairDecision.transaction_b_id == transaction_b_id))
        if not decision:
            decision = DuplicatePairDecision(transaction_a_id=transaction_a_id, transaction_b_id=transaction_b_id, decision="keep_both")
            db.add(decision)
            db.flush()
            changes.append(MutationChange(decision.id, None, full_values(decision), entity_type="duplicate_pair_decision"))
        description = f'Kept both copies of "{candidate.raw_description}"'
    elif action == "replace_old":
        original_before = changed_values(original, BANK_FIELDS)
        for field in BANK_FIELDS:
            setattr(original, field, getattr(candidate, field))
        changes.append(MutationChange(original.id, original_before, changed_values(original, BANK_FIELDS)))
        candidate_before = changed_values(candidate, ["deleted_at"])
        candidate.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        changes.append(MutationChange(candidate.id, candidate_before, changed_values(candidate, ["deleted_at"])))
        description = f'Replaced bank fields on "{original.raw_description}" with the newer import'
    elif action == "remove_sign_artifact":
        tier, _ = classify_duplicate_pair(candidate, original)
        if tier != "mirrored":
            raise ValueError("Remove sign artifact is only available for mirrored-sign pairs")
        positive = candidate if candidate.amount_cents > 0 else original
        survivor = original if positive is candidate else candidate
        before = changed_values(positive, ["deleted_at"])
        positive.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        changes.append(MutationChange(positive.id, before, changed_values(positive, ["deleted_at"])))
        if survivor is candidate:
            survivor_before = changed_values(survivor, ["duplicate_of_transaction_id", "review_status"])
            survivor.duplicate_of_transaction_id = None
            survivor.review_status = "needs_review"
            changes.append(MutationChange(survivor.id, survivor_before, changed_values(survivor, ["duplicate_of_transaction_id", "review_status"])))
        description = f'Removed mirrored sign artifact "{positive.raw_description}"'
    else:
        raise ValueError("Choose remove_new, keep_both, replace_old, or remove_sign_artifact")
    change_entity_types = {change.entity_type or "transaction" for change in changes}
    entity_type = "mixed" if len(change_entity_types) > 1 else "transaction"
    if entity_type == "mixed":
        changes = [
            MutationChange(change.entity_id, change.before, change.after, entity_type=change.entity_type or "transaction")
            for change in changes
        ]
    operation_id = journal_mutation(db, kind="resolve_duplicate", entity_type=entity_type, actor=actor, description=description, changes=changes)
    record_audit_event(db, "duplicate_resolve", actor, "transaction", str(candidate.id), {"action": action, "original_transaction_id": original.id, "operation_id": operation_id})
    account = db.get(Account, candidate.account_id)
    return {"ok": True, "action": action, "transaction_id": candidate.id, "original_transaction_id": original.id, "operation_id": operation_id, "affected_card_account": bool(account and account.account_type == "credit_card")}


def resolve_all_exact_duplicates(db: Session, *, actor: str) -> dict[str, Any]:
    exact_pairs = [pair for pair in pending_duplicate_pairs(db) if pair["safe_reimport"]]
    exact_ids = [pair["candidate"]["id"] for pair in exact_pairs]
    if not exact_ids:
        return {"ok": True, "resolved": 0, "operation_id": None}
    deleted_at = datetime.now(UTC).replace(tzinfo=None)
    changes: list[MutationChange] = []
    for transaction_id in exact_ids:
        candidate, _ = _duplicate_pair(db, transaction_id)
        before = changed_values(candidate, ["deleted_at"])
        candidate.deleted_at = deleted_at
        changes.append(MutationChange(candidate.id, before, changed_values(candidate, ["deleted_at"])))
    operation_id = journal_mutation(
        db,
        kind="resolve_duplicates",
        entity_type="transaction",
        actor=actor,
        description=f"Removed {len(changes)} safe duplicate reimports",
        changes=changes,
    )
    record_audit_event(db, "duplicates_resolve_exact", actor, "transactions", f"bulk:{len(changes)}", {"transaction_ids": exact_ids, "selection": "safe_reimports", "operation_id": operation_id})
    affected_account_ids = {pair["candidate"]["account_id"] for pair in exact_pairs}
    affected_card_account = bool(db.scalar(select(Account.id).where(Account.id.in_(affected_account_ids), Account.account_type == "credit_card").limit(1)))
    return {"ok": True, "resolved": len(changes), "operation_id": operation_id, "affected_card_account": affected_card_account}


def _duplicate_pair(db: Session, transaction_id: int) -> tuple[Transaction, Transaction]:
    candidate = db.get(Transaction, transaction_id)
    if not candidate or candidate.deleted_at is not None or candidate.status != "active":
        raise LookupError("Duplicate candidate not found")
    if candidate.review_status != "possible_duplicate" or candidate.duplicate_of_transaction_id is None:
        raise ValueError("This transaction is not waiting for duplicate review")
    original = db.get(Transaction, candidate.duplicate_of_transaction_id)
    if not original or original.deleted_at is not None or original.status != "active":
        raise ValueError("The matched original transaction is no longer available")
    return candidate, original


def _safe_reimport_groups(db: Session) -> list[tuple[Transaction, list[Transaction]]]:
    candidates = db.scalars(
        select(Transaction).where(
            Transaction.deleted_at.is_(None),
            Transaction.status == "active",
            Transaction.review_status == "possible_duplicate",
            Transaction.duplicate_of_transaction_id.is_not(None),
        ).order_by(Transaction.id)
    ).all()
    original_ids = {candidate.duplicate_of_transaction_id for candidate in candidates if candidate.duplicate_of_transaction_id is not None}
    originals = {
        original.id: original
        for original in db.scalars(select(Transaction).where(Transaction.id.in_(original_ids), Transaction.deleted_at.is_(None), Transaction.status == "active")).all()
    } if original_ids else {}
    grouped: dict[int, tuple[Transaction, list[Transaction]]] = {}
    for candidate in candidates:
        original = originals.get(candidate.duplicate_of_transaction_id)
        if original is None or not _is_safe_reimport(candidate, original):
            continue
        if original.id not in grouped:
            grouped[original.id] = (original, [])
        grouped[original.id][1].append(candidate)
    return [
        (original, sorted(candidates, key=lambda row: row.id))
        for original, candidates in sorted(grouped.values(), key=lambda group: group[0].id)
    ]


def _selected_duplicate_pairs(db: Session, transaction_ids: list[int]) -> list[tuple[Transaction, Transaction, str]]:
    unique_ids = list(dict.fromkeys(transaction_ids))
    if not unique_ids:
        raise ValueError("Select at least one duplicate pair")
    if len(unique_ids) != len(transaction_ids):
        raise ValueError("The duplicate selection contains repeated rows")
    selected: list[tuple[Transaction, Transaction, str]] = []
    for transaction_id in unique_ids:
        candidate, original = _duplicate_pair(db, transaction_id)
        tier, _ = classify_duplicate_pair(candidate, original)
        if tier not in {"exact", "cross_source", "probable"}:
            raise ValueError("Bulk selection is limited to exact, cross-source, and probable duplicate pairs")
        selected.append((candidate, original, tier))
    return selected


def _historical_refund_pairs(db: Session) -> list[tuple[Transaction, Transaction, Transaction]]:
    candidates = db.scalars(
        select(Transaction).where(
            Transaction.deleted_at.is_(None),
            Transaction.status == "active",
            Transaction.review_status == "possible_duplicate",
            Transaction.duplicate_of_transaction_id.is_not(None),
        ).order_by(Transaction.id)
    ).all()
    original_ids = {candidate.duplicate_of_transaction_id for candidate in candidates if candidate.duplicate_of_transaction_id is not None}
    originals = {
        row.id: row
        for row in db.scalars(select(Transaction).where(Transaction.id.in_(original_ids), Transaction.deleted_at.is_(None), Transaction.status == "active")).all()
    } if original_ids else {}
    already_linked_refund_ids = set(db.scalars(select(RefundLink.refund_transaction_id)).all())
    pairs: list[tuple[Transaction, Transaction, Transaction]] = []
    for candidate in candidates:
        original = originals.get(candidate.duplicate_of_transaction_id)
        if original is None or classify_duplicate_pair(candidate, original)[0] != "mirrored":
            continue
        positive = candidate if candidate.amount_cents > 0 else original
        negative = original if positive is candidate else candidate
        if (
            positive.id in already_linked_refund_ids
            or positive.transaction_type != "refund"
            or negative.transaction_type != "expense"
            or positive.account_id != negative.account_id
            or positive.transaction_date != negative.transaction_date
            or positive.amount_cents != -negative.amount_cents
            or normalize_transaction_description(positive.raw_description) != normalize_transaction_description(negative.raw_description)
            or positive.category_id is None
            or positive.category_id != negative.category_id
            or positive.import_batch_id is None
            or positive.import_batch_id != negative.import_batch_id
            or not is_categorized_history_reference(positive.source_reference)
            or not is_categorized_history_reference(negative.source_reference)
        ):
            continue
        pairs.append((candidate, positive, negative))
    return pairs


def _source_label(transaction: Transaction, batches: dict[int, ImportBatch]) -> str:
    if transaction.import_batch_id is None:
        return "Manual entry"
    batch = batches.get(transaction.import_batch_id)
    return batch.filename if batch else "Unknown import"


def _is_safe_reimport(candidate: Transaction, original: Transaction, *, tier: str | None = None) -> bool:
    pair_tier = tier or classify_duplicate_pair(candidate, original)[0]
    return pair_tier == "cross_source" or bool(
        candidate.source_reference
        and candidate.source_reference == original.source_reference
        and candidate.account_id == original.account_id
        and candidate.transaction_date == original.transaction_date
        and candidate.amount_cents == original.amount_cents
        and candidate.raw_description == original.raw_description
    )


def _transaction_payload(
    transaction: Transaction,
    accounts: dict[int, Account],
    categories: dict[int, Category],
    batches: dict[int, ImportBatch],
) -> dict[str, Any]:
    account = accounts.get(transaction.account_id)
    category = categories.get(transaction.category_id) if transaction.category_id is not None else None
    batch = batches.get(transaction.import_batch_id) if transaction.import_batch_id is not None else None
    account_label = account.display_name if account else "Unknown account"
    institution = account.institution.name if account and account.institution else None
    return {
        "id": transaction.id,
        "import_batch_id": transaction.import_batch_id,
        "account_id": transaction.account_id,
        "account": account_label,
        "institution": institution,
        "account_last_four": account.last_four if account else None,
        "reference": transaction.source_reference,
        "date": transaction.transaction_date.isoformat(),
        "posted_date": transaction.posted_date.isoformat() if transaction.posted_date else None,
        "amount": transaction.amount_cents,
        "amount_cents": transaction.amount_cents,
        "description": transaction.raw_description,
        "category_id": transaction.category_id,
        "category": category.label if category else None,
        "notes": transaction.user_note,
        "labels": transaction.labels,
        "import_source": batch.filename if batch else "Manual entry",
    }
