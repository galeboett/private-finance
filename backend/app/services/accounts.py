from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import Account, HoldingSnapshot, ImportBatch, ImportPreset, Institution, StagingRow, Transaction, TransactionSplit, TransferLink


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


def merge_account_into(db: Session, source: Account, target: Account, actor: str = "local-user") -> int:
    if source.id == target.id:
        return 0

    moved_transactions = 0
    source_transactions = db.scalars(select(Transaction).where(Transaction.account_id == source.id)).all()
    for transaction in source_transactions:
        duplicate = db.scalar(select(Transaction).where(Transaction.account_id == target.id, Transaction.source_hash == transaction.source_hash))
        if duplicate:
            _delete_transaction_row_for_merge(db, transaction)
            continue
        transaction.account_id = target.id
        moved_transactions += 1

    db.execute(update(StagingRow).where(StagingRow.account_id == source.id).values(account_id=target.id))
    db.execute(update(HoldingSnapshot).where(HoldingSnapshot.account_id == source.id).values(account_id=target.id))
    db.execute(update(ImportBatch).where(ImportBatch.account_id == source.id).values(account_id=target.id))
    db.execute(update(ImportPreset).where(ImportPreset.account_id == source.id).values(account_id=target.id))
    record_audit_event(
        db,
        "account_merge",
        actor,
        "account",
        str(target.id),
        {"source_account_id": source.id, "source_display_name": source.display_name, "target_display_name": target.display_name, "moved_transactions": moved_transactions},
    )
    db.delete(source)
    return moved_transactions


def cleanup_imported_accounts(db: Session, actor: str = "local-user") -> dict:
    accounts = db.scalars(select(Account).where(Account.status == "active").order_by(Account.display_name.asc(), Account.id.asc())).all()
    updated = 0
    merged = 0
    moved_transactions = 0
    seen_by_normalized_name: dict[str, Account] = {}

    for account in list(accounts):
        if account not in db:
            continue
        normalized = account.display_name.strip().casefold()
        existing = seen_by_normalized_name.get(normalized)
        if existing:
            moved_transactions += merge_account_into(db, account, existing, actor)
            merged += 1
            continue
        seen_by_normalized_name[normalized] = account

        characterization = infer_account_characterization(account.display_name, account.account_type)
        institution = upsert_institution_by_name(db, characterization.institution_name) if characterization.institution_name else account.institution
        next_display_name = characterization.display_name or account.display_name
        if account.display_name != next_display_name or account.account_type != characterization.account_type or account.institution_id != (institution.id if institution else None):
            account.display_name = next_display_name
            account.account_type = characterization.account_type
            account.institution_id = institution.id if institution else None
            updated += 1
            record_audit_event(
                db,
                "account_recharacterize",
                actor,
                "account",
                str(account.id),
                {"display_name": account.display_name, "account_type": account.account_type, "institution_name": characterization.institution_name},
            )

    db.commit()
    return {"updated": updated, "merged": merged, "moved_transactions": moved_transactions}


def _delete_transaction_row_for_merge(db: Session, transaction: Transaction) -> None:
    db.execute(update(Transaction).where(Transaction.linked_transaction_id == transaction.id).values(linked_transaction_id=None))
    db.execute(update(Transaction).where(Transaction.duplicate_of_transaction_id == transaction.id).values(duplicate_of_transaction_id=None))
    db.execute(delete(TransactionSplit).where(TransactionSplit.transaction_id == transaction.id))
    db.execute(delete(TransferLink).where((TransferLink.from_transaction_id == transaction.id) | (TransferLink.to_transaction_id == transaction.id)))
    db.delete(transaction)
