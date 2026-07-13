from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import Account, ExpenseAllocation, ImportBatch, Transaction, TransactionSplit
from .mutation_log import MutationChange, changed_values, journal_mutation


LEGACY_HISTORY_REFERENCE = "categorized-history-row-%"
NORMALIZED_HISTORY_CONVENTION = "normalized_charges_negative"


def preview_categorized_history_sign_cleanup(db: Session) -> dict:
    candidates = _cleanup_candidates(db)
    account_rows: dict[int, dict] = {}
    charges = 0
    refunds = 0
    income_sign_fixes = 0
    gross_cents = 0
    for transaction, account, _batch in candidates:
        row = account_rows.setdefault(
            account.id,
            {
                "account_id": account.id,
                "account": account.display_name,
                "last_four": account.last_four,
                "current_account_type": account.account_type,
                "next_account_type": "cash" if _is_venmo(account) else account.account_type,
                "transactions": 0,
                "gross_cents": 0,
                "history_rows": 0,
                "history_from": None,
                "history_through": None,
                "direct_rows": 0,
                "direct_from": None,
                "direct_through": None,
                "direct_rows_after_history": 0,
                "direct_rows_on_or_before_history": 0,
                "possible_direct_duplicate_rows": 0,
            },
        )
        next_amount, next_type = _normalized_history_values(transaction)
        if next_amount == transaction.amount_cents and next_type == transaction.transaction_type:
            continue
        row["transactions"] += 1
        row["gross_cents"] += abs(transaction.amount_cents)
        gross_cents += abs(transaction.amount_cents)
        if transaction.transaction_type == "income":
            income_sign_fixes += 1
        elif transaction.amount_cents < 0:
            refunds += 1
        else:
            charges += 1
    history_rows: list[tuple[Transaction, Account]] = []
    if account_rows:
        history_rows = db.execute(
            select(Transaction, Account)
            .join(Account, Account.id == Transaction.account_id)
            .where(
                Transaction.account_id.in_(account_rows),
                Transaction.source_reference.like(LEGACY_HISTORY_REFERENCE),
            )
        ).all()
        for transaction, _account in history_rows:
            row = account_rows[transaction.account_id]
            transaction_date = transaction.transaction_date.isoformat()
            row["history_rows"] += 1
            row["history_from"] = min(row["history_from"] or transaction_date, transaction_date)
            row["history_through"] = max(row["history_through"] or transaction_date, transaction_date)

        direct_rows = db.scalars(
            select(Transaction)
            .outerjoin(ImportBatch, ImportBatch.id == Transaction.import_batch_id)
            .where(
                Transaction.account_id.in_(account_rows),
                or_(Transaction.source_reference.is_(None), ~Transaction.source_reference.like(LEGACY_HISTORY_REFERENCE)),
                or_(ImportBatch.id.is_not(None), Transaction.source_reference.is_not(None)),
            )
        ).all()
        direct_references: dict[int, Counter[str]] = defaultdict(Counter)
        for transaction in direct_rows:
            row = account_rows[transaction.account_id]
            transaction_date = transaction.transaction_date.isoformat()
            row["direct_rows"] += 1
            row["direct_from"] = min(row["direct_from"] or transaction_date, transaction_date)
            row["direct_through"] = max(row["direct_through"] or transaction_date, transaction_date)
            if transaction_date > row["history_through"]:
                row["direct_rows_after_history"] += 1
            else:
                row["direct_rows_on_or_before_history"] += 1
            if transaction.source_reference:
                direct_references[transaction.account_id][transaction.source_reference] += 1
        for account_id, references in direct_references.items():
            account_rows[account_id]["possible_direct_duplicate_rows"] = sum(count - 1 for count in references.values() if count > 1)
    duplicate_pairs = _possible_duplicate_account_pairs(history_rows)
    boundary_warnings = [
        {
            "account_id": row["account_id"],
            "account": row["account"],
            "last_four": row["last_four"],
            "direct_rows_on_or_before_history": row["direct_rows_on_or_before_history"],
        }
        for row in account_rows.values()
        if row["direct_rows_on_or_before_history"] > 0
    ]
    return {
        "candidate_transactions": sum(row["transactions"] for row in account_rows.values()),
        "charges_to_normalize": charges,
        "refunds_to_normalize": refunds,
        "income_sign_fixes": income_sign_fixes,
        "gross_cents": gross_cents,
        "accounts": sorted(account_rows.values(), key=lambda row: (row["account"].casefold(), row["last_four"] or "")),
        "possible_duplicate_account_pairs": duplicate_pairs,
        "possible_direct_import_duplicates": [
            {
                "account_id": row["account_id"],
                "account": row["account"],
                "last_four": row["last_four"],
                "possible_duplicate_rows": row["possible_direct_duplicate_rows"],
            }
            for row in account_rows.values()
            if row["possible_direct_duplicate_rows"] > 0
        ],
        "source_boundary_warnings": boundary_warnings,
        "confirmation_text": "NORMALIZE",
    }


def apply_categorized_history_sign_cleanup(db: Session, *, actor: str, confirm_text: str) -> dict:
    if confirm_text.strip().upper() != "NORMALIZE":
        raise ValueError('Type "NORMALIZE" to apply the categorized-history cleanup')
    preview = preview_categorized_history_sign_cleanup(db)
    if preview["candidate_transactions"] == 0:
        return {**preview, "operation_id": None, "updated": 0}

    changes: list[MutationChange] = []
    changed_batches: dict[int, ImportBatch] = {}
    splits_by_transaction: dict[int, list[TransactionSplit]] = defaultdict(list)
    allocations_by_transaction: dict[int, list[ExpenseAllocation]] = defaultdict(list)
    candidates = _cleanup_candidates(db)
    candidate_ids = [transaction.id for transaction, _account, _batch in candidates]
    if candidate_ids:
        for split in db.scalars(select(TransactionSplit).where(TransactionSplit.transaction_id.in_(candidate_ids))).all():
            splits_by_transaction[split.transaction_id].append(split)
        for allocation in db.scalars(select(ExpenseAllocation).where(ExpenseAllocation.transaction_id.in_(candidate_ids))).all():
            allocations_by_transaction[allocation.transaction_id].append(allocation)

    changed_accounts: dict[int, Account] = {}
    updated = 0
    for transaction, account, batch in candidates:
        next_amount, next_type = _normalized_history_values(transaction)
        if next_amount == transaction.amount_cents and next_type == transaction.transaction_type:
            continue
        before = changed_values(transaction, ["amount_cents", "transaction_type"])
        sign_reversed = next_amount == -transaction.amount_cents
        transaction.amount_cents = next_amount
        transaction.transaction_type = next_type
        changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["amount_cents", "transaction_type"]), entity_type="transaction"))
        if sign_reversed:
            for split in splits_by_transaction.get(transaction.id, []):
                split_before = changed_values(split, ["amount_cents"])
                split.amount_cents = -split.amount_cents
                changes.append(MutationChange(split.id, split_before, changed_values(split, ["amount_cents"]), entity_type="transaction_split"))
            for allocation in allocations_by_transaction.get(transaction.id, []):
                allocation_before = changed_values(allocation, ["amount_cents"])
                allocation.amount_cents = -allocation.amount_cents
                changes.append(MutationChange(allocation.id, allocation_before, changed_values(allocation, ["amount_cents"]), entity_type="expense_allocation"))
        changed_batches[batch.id] = batch
        if _is_venmo(account):
            changed_accounts[account.id] = account
        updated += 1

    for batch in changed_batches.values():
        before = changed_values(batch, ["sign_convention"])
        batch.sign_convention = NORMALIZED_HISTORY_CONVENTION
        changes.append(MutationChange(batch.id, before, changed_values(batch, ["sign_convention"]), entity_type="import_batch"))
    for account in changed_accounts.values():
        if account.account_type == "cash":
            continue
        before = changed_values(account, ["account_type"])
        account.account_type = "cash"
        changes.append(MutationChange(account.id, before, changed_values(account, ["account_type"]), entity_type="account"))

    operation_id = journal_mutation(
        db,
        kind="normalize_history_signs",
        entity_type="mixed",
        actor=actor,
        description=f"Normalized signs for {updated} categorized-history transactions",
        changes=changes,
    )
    record_audit_event(
        db,
        "categorized_history_sign_cleanup",
        actor,
        "operation",
        operation_id,
        {"updated": updated, "accounts": len(preview["accounts"]), "charges": preview["charges_to_normalize"], "refunds": preview["refunds_to_normalize"]},
    )
    return {**preview, "operation_id": operation_id, "updated": updated}


def _cleanup_candidates(db: Session) -> list[tuple[Transaction, Account, ImportBatch]]:
    rows = db.execute(
        select(Transaction, Account, ImportBatch)
        .join(Account, Account.id == Transaction.account_id)
        .join(ImportBatch, ImportBatch.id == Transaction.import_batch_id)
        .where(
            Transaction.source_reference.like(LEGACY_HISTORY_REFERENCE),
            ImportBatch.sign_convention.is_(None),
        )
        .order_by(Transaction.id)
    ).all()
    return [(transaction, account, batch) for transaction, account, batch in rows if _is_history_spend_account(account)]


def _possible_duplicate_account_pairs(history_rows: list[tuple[Transaction, Account]]) -> list[dict]:
    fingerprints: dict[int, set[tuple]] = defaultdict(set)
    accounts: dict[int, Account] = {}
    for transaction, account in history_rows:
        accounts[account.id] = account
        fingerprints[account.id].add((transaction.transaction_date, transaction.amount_cents, transaction.raw_description, transaction.category_id))
    results = []
    account_ids = sorted(fingerprints)
    for index, left_id in enumerate(account_ids):
        for right_id in account_ids[index + 1 :]:
            smaller_count = min(len(fingerprints[left_id]), len(fingerprints[right_id]))
            if smaller_count < 5:
                continue
            overlap = len(fingerprints[left_id] & fingerprints[right_id])
            overlap_ratio = overlap / smaller_count
            if overlap_ratio < 0.8:
                continue
            left = accounts[left_id]
            right = accounts[right_id]
            results.append({
                "left_account_id": left.id,
                "left_account": left.display_name,
                "left_last_four": left.last_four,
                "right_account_id": right.id,
                "right_account": right.display_name,
                "right_last_four": right.last_four,
                "matching_transactions": overlap,
                "overlap_percent": round(overlap_ratio * 100),
            })
    return sorted(results, key=lambda row: (-row["matching_transactions"], row["left_account"].casefold()))


def _normalized_history_values(transaction: Transaction) -> tuple[int, str]:
    if transaction.amount_cents == 0:
        return 0, transaction.transaction_type
    if transaction.transaction_type == "income":
        return abs(transaction.amount_cents), "income"
    if transaction.transaction_type in {"transfer", "credit_card_payment", "investment_flow", "adjustment"}:
        return transaction.amount_cents, transaction.transaction_type
    if transaction.amount_cents < 0:
        return abs(transaction.amount_cents), "refund"
    return -abs(transaction.amount_cents), "expense"


def _is_history_spend_account(account: Account) -> bool:
    return account.account_type == "credit_card" or _is_venmo(account)


def _is_venmo(account: Account) -> bool:
    institution = account.institution.name.casefold() if account.institution else ""
    return account.display_name.strip().casefold() == "venmo" or institution == "venmo"
