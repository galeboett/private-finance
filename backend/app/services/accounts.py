from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import Account, AccountIdentifier, DuplicatePairDecision, HoldingLot, HoldingSnapshot, ImportBatch, ImportPreset, ImportSignProfile, Institution, PaymentVerificationDismissal, RefundLink, RefundPairDecision, RefundReviewResolution, StatementCheckpoint, StagingRow, Transaction, TransactionSplit, TransferLink
from .dedupe import canonical_source_hash, find_merge_match, is_categorized_history_reference
from .mutation_log import MutationChange, changed_values, full_values, journal_mutation


UNASSIGNED_ACCOUNT_MARKER = "SYSTEM"


@dataclass(frozen=True)
class AccountCharacterization:
    institution_name: str | None
    account_type: str
    display_name: str | None = None


def infer_account_characterization(display_name: str, current_type: str = "checking") -> AccountCharacterization:
    cleaned = " ".join(display_name.split())
    lowered = cleaned.lower()

    if current_type in {"brokerage", "retirement"}:
        return AccountCharacterization(None, current_type, cleaned)
    if lowered == "checkings" or lowered == "checking":
        return AccountCharacterization(None, "checking", "Checkings")
    if lowered == "venmo":
        return AccountCharacterization("Venmo", "cash", "Venmo")

    if lowered.startswith("boa ") or "bank of america" in lowered or lowered.startswith("custom cash"):
        return AccountCharacterization("Bank of America", "credit_card", cleaned)
    if "amex" in lowered or "american express" in lowered:
        return AccountCharacterization("American Express", "credit_card", cleaned)
    if any(token in lowered for token in ("chase", "sapphire", "freedom", "bonvoy", "jpm", "ihg", "ritz")) or re_contains_word(lowered, "ink"):
        return AccountCharacterization("Chase", "credit_card", cleaned)
    if lowered.startswith("citi "):
        return AccountCharacterization("Citi", "credit_card", cleaned)
    if lowered.startswith("discover"):
        return AccountCharacterization("Discover", "credit_card", cleaned)
    if lowered.startswith("target"):
        return AccountCharacterization("Target", "credit_card", cleaned)

    if current_type in {"brokerage", "retirement", "credit_card", "cash"}:
        return AccountCharacterization(None, current_type, cleaned)
    return AccountCharacterization(None, current_type, cleaned)


def infer_last_four(display_name: str) -> str | None:
    """Return a likely card/account suffix embedded in an imported account label.

    Imported labels often put the suffix before a parenthetical note (for example,
    ``BoA Cash 3970 (premium rewards)``).  Calendar years are deliberately
    ignored so names such as ``Chase Freedom (2025, prev csp)`` are not tagged
    with a made-up account suffix.
    """
    matches = re.findall(r"(?<!\d)(\d{4})(?!\d)", display_name)
    for value in reversed(matches):
        if not 1900 <= int(value) <= 2100:
            return value
    return None


def re_contains_word(value: str, word: str) -> bool:
    return any(part == word for part in value.replace("-", " ").replace("_", " ").split())


def upsert_institution_by_name(db: Session, name: str | None) -> Institution | None:
    if not name:
        return None
    institution = db.scalar(select(Institution).where(Institution.name == name))
    if not institution:
        institution = Institution(name=name)
        db.add(institution)
        db.flush()
    return institution


def merge_account_into(db: Session, source: Account, target: Account, actor: str = "local-user") -> tuple[int, list[MutationChange]]:
    if source.id == target.id:
        return 0, []

    moved_transactions = 0
    changes: list[MutationChange] = [MutationChange(source.id, full_values(source), None, entity_type="account")]
    source_transactions = db.scalars(select(Transaction).where(Transaction.account_id == source.id)).all()
    matched_target_ids: set[int] = set()
    for transaction in source_transactions:
        duplicate, reference_conflict = find_merge_match(
            db,
            target_account_id=target.id,
            source=transaction,
            excluded_target_ids=matched_target_ids,
        )
        if duplicate:
            matched_target_ids.add(duplicate.id)
            changes.append(MutationChange(transaction.id, full_values(transaction), None, entity_type="transaction"))
            changes.extend(MutationChange(split.id, full_values(split), None, entity_type="transaction_split") for split in db.scalars(select(TransactionSplit).where(TransactionSplit.transaction_id == transaction.id)).all())
            changes.extend(MutationChange(link.id, full_values(link), None, entity_type="transfer_link") for link in db.scalars(select(TransferLink).where((TransferLink.from_transaction_id == transaction.id) | (TransferLink.to_transaction_id == transaction.id))).all())
            changes.extend(MutationChange(link.id, full_values(link), None, entity_type="refund_link") for link in db.scalars(select(RefundLink).where((RefundLink.expense_transaction_id == transaction.id) | (RefundLink.refund_transaction_id == transaction.id))).all())
            _delete_transaction_row_for_merge(db, transaction)
            continue
        changed_fields = ["account_id", "source_hash", "review_status", "duplicate_of_transaction_id"]
        before = changed_values(transaction, changed_fields)
        transaction.account_id = target.id
        if (transaction.import_batch_id is not None or transaction.source_reference is not None) and not is_categorized_history_reference(transaction.source_reference):
            transaction.source_hash = canonical_source_hash(
                transaction.transaction_date,
                transaction.amount_cents,
                transaction.raw_description,
                transaction.source_reference,
                transaction.source_ordinal,
            )
        if reference_conflict:
            transaction.review_status = "possible_duplicate"
            transaction.duplicate_of_transaction_id = reference_conflict.id
        changes.append(MutationChange(transaction.id, before, changed_values(transaction, changed_fields), entity_type="transaction"))
        moved_transactions += 1

    related_groups = [
        ("staging_row", db.scalars(select(StagingRow).where(StagingRow.account_id == source.id)).all()),
        ("holding_snapshot", db.scalars(select(HoldingSnapshot).where(HoldingSnapshot.account_id == source.id)).all()),
        ("holding_lot", db.scalars(select(HoldingLot).where(HoldingLot.account_id == source.id)).all()),
        ("import_batch", db.scalars(select(ImportBatch).where(ImportBatch.account_id == source.id)).all()),
        ("import_preset", db.scalars(select(ImportPreset).where(ImportPreset.account_id == source.id)).all()),
    ]
    for entity_type, rows in related_groups:
        changes.extend(MutationChange(row.id, changed_values(row, ["account_id"]), {"id": row.id, "account_id": target.id}, entity_type=entity_type) for row in rows)
    db.execute(update(StagingRow).where(StagingRow.account_id == source.id).values(account_id=target.id))
    db.execute(update(HoldingSnapshot).where(HoldingSnapshot.account_id == source.id).values(account_id=target.id))
    db.execute(update(HoldingLot).where(HoldingLot.account_id == source.id).values(account_id=target.id))
    db.execute(update(ImportBatch).where(ImportBatch.account_id == source.id).values(account_id=target.id))
    db.execute(update(ImportPreset).where(ImportPreset.account_id == source.id).values(account_id=target.id))
    target_identifiers = db.scalars(select(AccountIdentifier).where(AccountIdentifier.account_id == target.id)).all()
    target_identifier_keys = {(row.identifier_type, row.identifier_value) for row in target_identifiers}
    target_has_current = any(row.is_current for row in target_identifiers)
    for identifier in db.scalars(select(AccountIdentifier).where(AccountIdentifier.account_id == source.id)).all():
        if (identifier.identifier_type, identifier.identifier_value) in target_identifier_keys:
            db.delete(identifier)
        else:
            identifier.account_id = target.id
            if target_has_current:
                identifier.is_current = False
    source_profiles = db.scalars(select(ImportSignProfile).where(ImportSignProfile.account_id == source.id)).all()
    target_profiles = db.scalars(select(ImportSignProfile).where(ImportSignProfile.account_id == target.id)).all()
    target_by_preset = {profile.preset_type: profile for profile in target_profiles}
    for profile in source_profiles:
        if profile.preset_type in target_by_preset:
            changes.append(MutationChange(profile.id, full_values(profile), None, entity_type="import_sign_profile"))
            db.delete(profile)
        else:
            before = changed_values(profile, ["account_id"])
            profile.account_id = target.id
            changes.append(MutationChange(profile.id, before, changed_values(profile, ["account_id"]), entity_type="import_sign_profile"))
    target_checkpoint_dates = set(db.scalars(select(StatementCheckpoint.statement_date).where(StatementCheckpoint.account_id == target.id)).all())
    source_checkpoints = db.scalars(select(StatementCheckpoint).where(StatementCheckpoint.account_id == source.id)).all()
    for checkpoint in source_checkpoints:
        if checkpoint.statement_date in target_checkpoint_dates:
            changes.append(MutationChange(checkpoint.id, full_values(checkpoint), None, entity_type="statement_checkpoint"))
            db.delete(checkpoint)
        else:
            before = changed_values(checkpoint, ["account_id"])
            checkpoint.account_id = target.id
            changes.append(MutationChange(checkpoint.id, before, changed_values(checkpoint, ["account_id"]), entity_type="statement_checkpoint"))
    record_audit_event(
        db,
        "account_merge",
        actor,
        "account",
        str(target.id),
        {"source_account_id": source.id, "source_display_name": source.display_name, "target_display_name": target.display_name, "moved_transactions": moved_transactions},
    )
    db.delete(source)
    return moved_transactions, changes


def cleanup_imported_accounts(db: Session, actor: str = "local-user") -> dict:
    accounts = db.scalars(select(Account).where(Account.status == "active").order_by(Account.display_name.asc(), Account.id.asc())).all()
    updated = 0
    merged = 0
    moved_transactions = 0
    seen_by_normalized_name: dict[str, Account] = {}
    journal_changes: list[MutationChange] = []

    for account in list(accounts):
        if account not in db:
            continue
        normalized = account.display_name.strip().casefold()
        existing = seen_by_normalized_name.get(normalized)
        if existing:
            moved, changes = merge_account_into(db, account, existing, actor)
            moved_transactions += moved
            journal_changes.extend(changes)
            merged += 1
            continue
        seen_by_normalized_name[normalized] = account

        characterization = infer_account_characterization(account.display_name, account.account_type)
        institution = upsert_institution_by_name(db, characterization.institution_name) if characterization.institution_name else account.institution
        next_display_name = characterization.display_name or account.display_name
        next_last_four = account.last_four or infer_last_four(next_display_name)
        if account.display_name != next_display_name or account.account_type != characterization.account_type or account.institution_id != (institution.id if institution else None) or account.last_four != next_last_four:
            before = changed_values(account, ["display_name", "account_type", "institution_id", "last_four"])
            account.display_name = next_display_name
            account.account_type = characterization.account_type
            account.institution_id = institution.id if institution else None
            account.last_four = next_last_four
            journal_changes.append(MutationChange(account.id, before, changed_values(account, ["display_name", "account_type", "institution_id", "last_four"]), entity_type="account"))
            updated += 1
            record_audit_event(
                db,
                "account_recharacterize",
                actor,
                "account",
                str(account.id),
                {"display_name": account.display_name, "account_type": account.account_type, "institution_name": characterization.institution_name, "last_four": account.last_four},
            )

    operation_id = journal_mutation(db, kind="cleanup", entity_type="mixed", actor=actor, description="Cleaned imported account labels", changes=journal_changes) if journal_changes else None
    db.commit()
    return {"updated": updated, "merged": merged, "moved_transactions": moved_transactions, "operation_id": operation_id}


def _delete_transaction_row_for_merge(db: Session, transaction: Transaction) -> None:
    db.execute(update(Transaction).where(Transaction.linked_transaction_id == transaction.id).values(linked_transaction_id=None))
    db.execute(update(Transaction).where(Transaction.duplicate_of_transaction_id == transaction.id).values(duplicate_of_transaction_id=None))
    db.execute(delete(TransactionSplit).where(TransactionSplit.transaction_id == transaction.id))
    db.execute(delete(TransferLink).where((TransferLink.from_transaction_id == transaction.id) | (TransferLink.to_transaction_id == transaction.id)))
    db.execute(delete(RefundLink).where((RefundLink.expense_transaction_id == transaction.id) | (RefundLink.refund_transaction_id == transaction.id)))
    db.execute(delete(RefundPairDecision).where((RefundPairDecision.expense_transaction_id == transaction.id) | (RefundPairDecision.refund_transaction_id == transaction.id)))
    db.execute(delete(RefundReviewResolution).where(RefundReviewResolution.refund_transaction_id == transaction.id))
    db.execute(delete(PaymentVerificationDismissal).where(PaymentVerificationDismissal.transaction_id == transaction.id))
    db.execute(delete(DuplicatePairDecision).where((DuplicatePairDecision.transaction_a_id == transaction.id) | (DuplicatePairDecision.transaction_b_id == transaction.id)))
    db.delete(transaction)
