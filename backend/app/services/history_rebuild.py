from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import (
    Account,
    DuplicatePairDecision,
    ExpenseAllocation,
    HoldingLot,
    ImportBatch,
    PaymentVerificationDismissal,
    RefundLink,
    StagingRow,
    Transaction,
    TransactionSplit,
    TransferLink,
)


HISTORICAL_WORKBOOK_FILENAME = "transaction history for private finance.xlsx"
PURGE_CONFIRMATION = "PURGE HISTORY"


def preview_history_import_purge(db: Session, *, filename: str = HISTORICAL_WORKBOOK_FILENAME) -> dict[str, Any]:
    batches, transactions = _history_lineage(db, filename)
    batch_ids = [batch.id for batch in batches]
    transaction_ids = [transaction.id for transaction in transactions]
    transaction_id_set = set(transaction_ids)

    account_ids = {transaction.account_id for transaction in transactions}
    accounts = {
        account.id: account
        for account in db.scalars(select(Account).where(Account.id.in_(account_ids))).all()
    } if account_ids else {}
    by_account: dict[int, dict[str, Any]] = defaultdict(lambda: {
        "transactions": 0,
        "live_transactions": 0,
        "trashed_transactions": 0,
        "signed_total_cents": 0,
        "first_date": None,
        "last_date": None,
    })
    for transaction in transactions:
        summary = by_account[transaction.account_id]
        summary["transactions"] += 1
        if transaction.deleted_at is None:
            summary["live_transactions"] += 1
            summary["signed_total_cents"] += transaction.amount_cents
        else:
            summary["trashed_transactions"] += 1
        summary["first_date"] = min(summary["first_date"], transaction.transaction_date) if summary["first_date"] else transaction.transaction_date
        summary["last_date"] = max(summary["last_date"], transaction.transaction_date) if summary["last_date"] else transaction.transaction_date

    account_summaries = []
    for account_id, summary in by_account.items():
        account = accounts.get(account_id)
        account_summaries.append({
            "account_id": account_id,
            "account": account.display_name if account else "Unknown account",
            "account_type": account.account_type if account else None,
            **summary,
            "first_date": summary["first_date"].isoformat() if summary["first_date"] else None,
            "last_date": summary["last_date"].isoformat() if summary["last_date"] else None,
        })

    dependencies = {
        "staging_rows": _count(db, StagingRow, StagingRow.import_batch_id.in_(batch_ids)),
        "splits": _count(db, TransactionSplit, TransactionSplit.transaction_id.in_(transaction_ids)),
        "allocations": _count(db, ExpenseAllocation, ExpenseAllocation.transaction_id.in_(transaction_ids)),
        "transfer_links": _count(db, TransferLink, or_(TransferLink.from_transaction_id.in_(transaction_ids), TransferLink.to_transaction_id.in_(transaction_ids))),
        "refund_links": _count(db, RefundLink, or_(RefundLink.expense_transaction_id.in_(transaction_ids), RefundLink.refund_transaction_id.in_(transaction_ids))),
        "payment_dismissals": _count(db, PaymentVerificationDismissal, PaymentVerificationDismissal.transaction_id.in_(transaction_ids)),
        "duplicate_decisions": _count(db, DuplicatePairDecision, or_(DuplicatePairDecision.transaction_a_id.in_(transaction_ids), DuplicatePairDecision.transaction_b_id.in_(transaction_ids))),
        "holding_lots": _count(db, HoldingLot, HoldingLot.import_batch_id.in_(batch_ids)),
        "outside_linked_references": _count(db, Transaction, Transaction.id.not_in(transaction_id_set), Transaction.linked_transaction_id.in_(transaction_ids)),
        "outside_duplicate_references": _count(db, Transaction, Transaction.id.not_in(transaction_id_set), Transaction.duplicate_of_transaction_id.in_(transaction_ids)),
    }

    digest = hashlib.sha256(filename.casefold().encode("utf-8"))
    for batch in batches:
        digest.update(f"|b:{batch.id}:{batch.file_hash}:{batch.status}".encode("utf-8"))
    for transaction in transactions:
        digest.update(f"|t:{transaction.id}:{transaction.account_id}:{transaction.source_hash}:{transaction.deleted_at}".encode("utf-8"))
    for key, value in sorted(dependencies.items()):
        digest.update(f"|d:{key}:{value}".encode("utf-8"))

    live_transactions = [transaction for transaction in transactions if transaction.deleted_at is None]
    return {
        "filename": filename,
        "preview_token": digest.hexdigest(),
        "batches": len(batches),
        "transactions": len(transactions),
        "live_transactions": len(live_transactions),
        "trashed_transactions": len(transactions) - len(live_transactions),
        "signed_total_cents": sum(transaction.amount_cents for transaction in live_transactions),
        "first_date": min((transaction.transaction_date for transaction in transactions), default=None).isoformat() if transactions else None,
        "last_date": max((transaction.transaction_date for transaction in transactions), default=None).isoformat() if transactions else None,
        "accounts": sorted(account_summaries, key=lambda row: (-row["transactions"], row["account"])),
        "dependencies": dependencies,
        "preserves": ["accounts", "institutions", "categories", "rules", "net_worth_snapshots", "statement_checkpoints", "other_import_batches", "other_transactions"],
    }


def purge_history_import_lineage(
    db: Session,
    *,
    preview_token: str,
    confirm_text: str,
    actor: str,
    filename: str = HISTORICAL_WORKBOOK_FILENAME,
) -> dict[str, Any]:
    if confirm_text.strip().upper() != PURGE_CONFIRMATION:
        raise ValueError(f'Type "{PURGE_CONFIRMATION}" to remove the historical workbook lineage')
    preview = preview_history_import_purge(db, filename=filename)
    if preview_token != preview["preview_token"]:
        raise ValueError("The historical import lineage changed after preview. Review the refreshed counts before purging.")
    batches, transactions = _history_lineage(db, filename)
    if not batches:
        return {**preview, "purged": False}

    batch_ids = [batch.id for batch in batches]
    transaction_ids = [transaction.id for transaction in transactions]
    transaction_id_set = set(transaction_ids)

    db.execute(
        update(Transaction)
        .where(Transaction.id.not_in(transaction_id_set), Transaction.linked_transaction_id.in_(transaction_ids))
        .values(linked_transaction_id=None)
    )
    outside_duplicates = db.scalars(
        select(Transaction).where(Transaction.id.not_in(transaction_id_set), Transaction.duplicate_of_transaction_id.in_(transaction_ids))
    ).all()
    for transaction in outside_duplicates:
        transaction.duplicate_of_transaction_id = None
        if transaction.review_status == "possible_duplicate":
            transaction.review_status = "needs_review"

    db.execute(delete(TransactionSplit).where(TransactionSplit.transaction_id.in_(transaction_ids)))
    db.execute(delete(ExpenseAllocation).where(ExpenseAllocation.transaction_id.in_(transaction_ids)))
    db.execute(delete(TransferLink).where(or_(TransferLink.from_transaction_id.in_(transaction_ids), TransferLink.to_transaction_id.in_(transaction_ids))))
    db.execute(delete(RefundLink).where(or_(RefundLink.expense_transaction_id.in_(transaction_ids), RefundLink.refund_transaction_id.in_(transaction_ids))))
    db.execute(delete(PaymentVerificationDismissal).where(PaymentVerificationDismissal.transaction_id.in_(transaction_ids)))
    db.execute(delete(DuplicatePairDecision).where(or_(DuplicatePairDecision.transaction_a_id.in_(transaction_ids), DuplicatePairDecision.transaction_b_id.in_(transaction_ids))))
    db.execute(delete(HoldingLot).where(HoldingLot.import_batch_id.in_(batch_ids)))
    db.execute(delete(StagingRow).where(StagingRow.import_batch_id.in_(batch_ids)))
    db.execute(delete(Transaction).where(Transaction.id.in_(transaction_ids)))
    db.execute(delete(ImportBatch).where(ImportBatch.id.in_(batch_ids)))
    record_audit_event(db, "categorized_history_lineage_purge", actor, "import_batch", filename, {
        "filename": filename,
        "batches": preview["batches"],
        "transactions": preview["transactions"],
        "dependencies": preview["dependencies"],
        "preview_token": preview_token,
    })
    db.flush()
    return {**preview, "purged": True}


def _history_lineage(db: Session, filename: str) -> tuple[list[ImportBatch], list[Transaction]]:
    batches = db.scalars(
        select(ImportBatch)
        .where(func.lower(ImportBatch.filename) == filename.casefold())
        .order_by(ImportBatch.id)
    ).all()
    if not batches:
        return [], []
    batch_ids = [batch.id for batch in batches]
    transactions = db.scalars(
        select(Transaction)
        .where(Transaction.import_batch_id.in_(batch_ids))
        .order_by(Transaction.id)
    ).all()
    return list(batches), list(transactions)


def _count(db: Session, model: type, *conditions: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)
