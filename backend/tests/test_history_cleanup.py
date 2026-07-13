from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, Category, ExpenseAllocation, ImportBatch, Institution, Transaction, TransactionSplit
from app.services.history_cleanup import apply_categorized_history_sign_cleanup, preview_categorized_history_sign_cleanup
from app.services.operation_history import undo_operation


def test_history_cleanup_previews_applies_and_undoes_dependent_sign_changes():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        institution = Institution(name="Venmo")
        account = Account(institution=institution, display_name="Venmo", account_type="credit_card")
        category = Category(key="dining", label="Dining")
        db.add_all([account, category])
        db.flush()
        batch = ImportBatch(account_id=account.id, filename="history.csv", file_hash="history", status="committed")
        direct_batch = ImportBatch(account_id=account.id, filename="venmo.csv", file_hash="direct", status="committed", sign_convention="preset")
        db.add_all([batch, direct_batch])
        db.flush()
        charge = Transaction(account_id=account.id, import_batch_id=batch.id, transaction_date=date(2025, 1, 1), amount_cents=10000, raw_description="Dinner", transaction_type="expense", category_id=category.id, review_status="confirmed", source_hash="charge", source_reference="categorized-history-row-2")
        refund = Transaction(account_id=account.id, import_batch_id=batch.id, transaction_date=date(2025, 1, 2), amount_cents=-2500, raw_description="Dinner refund", transaction_type="expense", category_id=category.id, review_status="confirmed", source_hash="refund", source_reference="categorized-history-row-3")
        deleted_charge = Transaction(account_id=account.id, import_batch_id=batch.id, transaction_date=date(2025, 1, 3), amount_cents=500, raw_description="Deleted snack", transaction_type="expense", category_id=category.id, review_status="confirmed", source_hash="deleted", source_reference="categorized-history-row-4", deleted_at=datetime(2025, 2, 1))
        direct_overlap = Transaction(account_id=account.id, import_batch_id=direct_batch.id, transaction_date=date(2025, 1, 2), amount_cents=-1200, raw_description="Direct overlap", transaction_type="expense", category_id=category.id, review_status="confirmed", source_hash="direct-overlap", source_reference="bank-reference-1")
        direct_duplicate = Transaction(account_id=account.id, import_batch_id=direct_batch.id, transaction_date=date(2025, 1, 2), amount_cents=-1200, raw_description="Direct overlap", transaction_type="expense", category_id=category.id, review_status="confirmed", source_hash="older-hash-for-same-row", source_reference="bank-reference-1")
        deleted_direct_duplicate = Transaction(account_id=account.id, import_batch_id=direct_batch.id, transaction_date=date(2025, 1, 2), amount_cents=-1200, raw_description="Direct overlap", transaction_type="expense", category_id=category.id, review_status="confirmed", source_hash="deleted-hash-for-same-row", source_reference="bank-reference-1", deleted_at=datetime(2025, 2, 1))
        direct_after = Transaction(account_id=account.id, import_batch_id=direct_batch.id, transaction_date=date(2025, 2, 1), amount_cents=-1500, raw_description="Direct after", transaction_type="expense", category_id=category.id, review_status="confirmed", source_hash="direct-after")
        db.add_all([charge, refund, deleted_charge, direct_overlap, direct_duplicate, deleted_direct_duplicate, direct_after])
        db.flush()
        split = TransactionSplit(transaction_id=charge.id, category_id=category.id, amount_cents=10000)
        allocation = ExpenseAllocation(transaction_id=charge.id, category_id=category.id, allocation_date=date(2025, 1, 1), amount_cents=10000)
        db.add_all([split, allocation])
        db.commit()

        preview = preview_categorized_history_sign_cleanup(db)
        assert preview["candidate_transactions"] == 3
        assert preview["charges_to_normalize"] == 2
        assert preview["refunds_to_normalize"] == 1
        assert preview["accounts"][0]["next_account_type"] == "cash"
        assert preview["accounts"][0]["history_through"] == "2025-01-03"
        assert preview["accounts"][0]["direct_rows_after_history"] == 1
        assert preview["accounts"][0]["direct_rows_on_or_before_history"] == 3
        assert preview["source_boundary_warnings"][0]["direct_rows_on_or_before_history"] == 3
        assert preview["possible_direct_import_duplicates"][0]["possible_duplicate_rows"] == 1

        result = apply_categorized_history_sign_cleanup(db, actor="user:1", confirm_text="NORMALIZE")
        db.commit()
        assert result["updated"] == 3
        assert charge.amount_cents == -10000
        assert charge.transaction_type == "expense"
        assert refund.amount_cents == 2500
        assert refund.transaction_type == "refund"
        assert deleted_charge.amount_cents == -500
        assert direct_overlap.amount_cents == -1200
        assert direct_after.amount_cents == -1500
        assert split.amount_cents == -10000
        assert allocation.amount_cents == -10000
        assert account.account_type == "cash"
        assert batch.sign_convention == "normalized_charges_negative"
        assert preview_categorized_history_sign_cleanup(db)["candidate_transactions"] == 0

        undo_operation(db, operation_id=result["operation_id"], actor="user:1")
        db.commit()
        assert charge.amount_cents == 10000
        assert refund.amount_cents == -2500
        assert deleted_charge.amount_cents == 500
        assert split.amount_cents == 10000
        assert allocation.amount_cents == 10000
        assert account.account_type == "credit_card"
        assert batch.sign_convention is None


def test_history_cleanup_ignores_newly_normalized_and_non_card_history():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        checking = Account(display_name="Checking", account_type="checking")
        card = Account(display_name="Card", account_type="credit_card")
        db.add_all([checking, card])
        db.flush()
        normalized_batch = ImportBatch(account_id=card.id, filename="new.csv", file_hash="new", status="committed", sign_convention="charges_positive")
        legacy_checking_batch = ImportBatch(account_id=checking.id, filename="old.csv", file_hash="old", status="committed")
        db.add_all([normalized_batch, legacy_checking_batch])
        db.flush()
        db.add_all([
            Transaction(account_id=card.id, import_batch_id=normalized_batch.id, transaction_date=date(2025, 1, 1), amount_cents=-1000, raw_description="New charge", transaction_type="expense", review_status="confirmed", source_hash="new", source_reference="categorized-history-row-2"),
            Transaction(account_id=checking.id, import_batch_id=legacy_checking_batch.id, transaction_date=date(2025, 1, 1), amount_cents=-1000, raw_description="Withdrawal", transaction_type="expense", review_status="confirmed", source_hash="old", source_reference="categorized-history-row-2"),
        ])
        db.commit()

        assert preview_categorized_history_sign_cleanup(db)["candidate_transactions"] == 0


def test_history_cleanup_flags_alias_accounts_with_matching_history():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = Account(display_name="BoA Cash", account_type="credit_card", last_four="3056")
        alias = Account(display_name="BoA Cash 3056", account_type="credit_card", last_four="3056")
        db.add_all([first, alias])
        db.flush()
        first_batch = ImportBatch(account_id=first.id, filename="history.xlsx", file_hash="first", status="committed")
        alias_batch = ImportBatch(account_id=alias.id, filename="history-copy.xlsx", file_hash="alias", status="committed")
        db.add_all([first_batch, alias_batch])
        db.flush()
        for index in range(5):
            transaction_date = date(2025, 1, index + 1)
            for account, batch, suffix in ((first, first_batch, "first"), (alias, alias_batch, "alias")):
                db.add(Transaction(
                    account_id=account.id,
                    import_batch_id=batch.id,
                    transaction_date=transaction_date,
                    amount_cents=1000 + index,
                    raw_description=f"Purchase {index}",
                    transaction_type="expense",
                    review_status="confirmed",
                    source_hash=f"{suffix}-{index}",
                    source_reference=f"categorized-history-row-{index + 2}",
                ))
        db.commit()

        preview = preview_categorized_history_sign_cleanup(db)
        assert preview["candidate_transactions"] == 10
        assert len(preview["possible_duplicate_account_pairs"]) == 1
        pair = preview["possible_duplicate_account_pairs"][0]
        assert pair["matching_transactions"] == 5
        assert pair["overlap_percent"] == 100
