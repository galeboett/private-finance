from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.main import UNASSIGNED_ACCOUNT_MARKER, _delete_account_tree
from app.models import Account, Category, HoldingSnapshot, ImportBatch, Transaction, TransactionSplit
from app.services.accounts import cleanup_imported_accounts, infer_account_characterization, infer_last_four, merge_account_into
from app.services.operation_history import undo_operation
from app.services.importers import _find_or_create_history_account


def test_infer_credit_card_institution_from_account_name():
    boa = infer_account_characterization("BoA Cash 3056")
    chase = infer_account_characterization("Bonvoy Chase")
    citi = infer_account_characterization("Citi Premier")

    assert boa.institution_name == "Bank of America"
    assert boa.account_type == "credit_card"
    assert chase.institution_name == "Chase"
    assert chase.account_type == "credit_card"
    assert citi.institution_name == "Citi"
    assert citi.account_type == "credit_card"


def test_infer_preserves_brokeragelink_as_brokerage():
    brokerage = infer_account_characterization("Brokeragelink", current_type="brokerage")

    assert brokerage.account_type == "brokerage"
    assert brokerage.institution_name is None


def test_infer_last_four_from_account_name_ignores_years():
    assert infer_last_four("BoA Cash 3970 (premium rewards)") == "3970"
    assert infer_last_four("Chase Freedom (2025, prev csp)") is None


def test_categorized_history_account_creation_uses_inferred_metadata():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account, created = _find_or_create_history_account(session, "Discover")

        assert created is True
        assert account.account_type == "credit_card"
        assert account.institution.name == "Discover"


def test_cleanup_imported_accounts_merges_case_duplicates_and_recharacterizes_cards():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        checkings = Account(display_name="Checkings", account_type="checking")
        duplicate_checkings = Account(display_name="checkings", account_type="checking")
        boa = Account(display_name="BoA Cash 3056", account_type="checking")
        session.add_all([checkings, duplicate_checkings, boa])
        session.flush()
        session.add(
            Transaction(
                account_id=duplicate_checkings.id,
                transaction_date=date(2026, 1, 1),
                amount_cents=100,
                raw_description="Opening",
                transaction_type="income",
                review_status="confirmed",
                source_hash="source-1",
            )
        )
        session.commit()
        duplicate_id = duplicate_checkings.id

        result = cleanup_imported_accounts(session)
        accounts = session.scalars(select(Account).order_by(Account.display_name)).all()
        cleaned_checkings = session.scalar(select(Account).where(Account.display_name == "Checkings"))
        moved_transaction = session.scalar(select(Transaction).where(Transaction.source_hash == "source-1"))
        cleaned_boa = session.scalar(select(Account).where(Account.display_name == "BoA Cash 3056"))

        assert result["merged"] == 1
        assert [account.display_name for account in accounts] == ["BoA Cash 3056", "Checkings"]
        assert moved_transaction.account_id == cleaned_checkings.id
        assert cleaned_boa.account_type == "credit_card"
        assert cleaned_boa.institution.name == "Bank of America"
        assert cleaned_boa.last_four == "3056"
        assert result["operation_id"]

        undo_operation(session, operation_id=result["operation_id"], actor="user:1")
        session.commit()
        restored_duplicate = session.get(Account, duplicate_id)
        session.refresh(moved_transaction)
        session.refresh(cleaned_boa)
        assert restored_duplicate.display_name == "checkings"
        assert moved_transaction.account_id == restored_duplicate.id
        assert cleaned_boa.account_type == "checking"


def test_account_deletion_preserves_transactions_for_account_review():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(display_name="Old Card", account_type="credit_card")
        category = Category(key="shopping", label="Shopping")
        session.add_all([account, category])
        session.flush()
        batch = ImportBatch(account_id=account.id, filename="old.csv", file_hash="file", status="committed")
        session.add(batch)
        session.flush()
        transaction = Transaction(account_id=account.id, import_batch_id=batch.id, transaction_date=date(2026, 7, 1), amount_cents=-5000, raw_description="Purchase", transaction_type="expense", category_id=category.id, review_status="confirmed", source_hash="preserved")
        session.add(transaction)
        session.flush()
        split = TransactionSplit(transaction_id=transaction.id, category_id=category.id, amount_cents=-5000)
        holding = HoldingSnapshot(account_id=account.id, snapshot_date=date(2026, 7, 1), symbol="TEST", market_value_cents=10000)
        session.add_all([split, holding])
        session.commit()
        account_id = account.id
        transaction_id = transaction.id
        split_id = split.id
        batch_id = batch.id
        holding_id = holding.id

        _delete_account_tree(session, account)
        session.commit()

        preserved = session.get(Transaction, transaction_id)
        review_account = session.get(Account, preserved.account_id)
        assert session.get(Account, account_id) is None
        assert preserved is not None
        assert preserved.review_status == "needs_review"
        assert preserved.import_batch_id is None
        assert preserved.category_id == category.id
        assert session.get(TransactionSplit, split_id) is not None
        assert review_account.last_four == UNASSIGNED_ACCOUNT_MARKER
        assert review_account.display_name == "Needs account (Old Card)"
        assert session.get(ImportBatch, batch_id) is None
        assert session.get(HoldingSnapshot, holding_id) is None


def test_account_merge_deduplicates_reliable_reference_even_when_legacy_hashes_differ():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        target = Account(display_name="BoA Cash", account_type="credit_card", last_four="3056")
        source = Account(display_name="BoA Cash 3056", account_type="credit_card", last_four="3056")
        session.add_all([target, source])
        session.flush()
        target_batch = ImportBatch(account_id=target.id, filename="first.csv", file_hash="first", status="committed", detected_preset="card_reference")
        source_batch = ImportBatch(account_id=source.id, filename="second.csv", file_hash="second", status="committed", detected_preset="card_reference")
        session.add_all([target_batch, source_batch])
        session.flush()
        shared = {
            "transaction_date": date(2026, 5, 8),
            "amount_cents": -1481,
            "raw_description": "Amazon",
            "transaction_type": "expense",
            "review_status": "confirmed",
            "source_reference": "24692166128402310148405",
        }
        session.add_all([
            Transaction(account_id=target.id, import_batch_id=target_batch.id, source_hash="legacy-target-hash", **shared),
            Transaction(account_id=source.id, import_batch_id=source_batch.id, source_hash="legacy-source-hash", **shared),
        ])
        session.commit()

        moved, _changes = merge_account_into(session, source, target)
        session.commit()

        assert moved == 0
        rows = session.query(Transaction).all()
        assert len(rows) == 1
        assert rows[0].account_id == target.id


def test_account_merge_does_not_rewrite_categorized_history_fingerprint():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        target = Account(display_name="Card", account_type="credit_card")
        source = Account(display_name="card", account_type="credit_card")
        session.add_all([target, source])
        session.flush()
        batch = ImportBatch(account_id=source.id, filename="history.xlsx", file_hash="history", status="committed")
        session.add(batch)
        session.flush()
        transaction = Transaction(
            account_id=source.id,
            import_batch_id=batch.id,
            transaction_date=date(2026, 1, 1),
            amount_cents=1000,
            raw_description="History purchase",
            transaction_type="expense",
            review_status="confirmed",
            source_hash="categorized-history-fingerprint",
            source_reference="categorized-history-row-2",
        )
        session.add(transaction)
        session.commit()

        merge_account_into(session, source, target)
        session.commit()

        assert transaction.account_id == target.id
        assert transaction.source_hash == "categorized-history-fingerprint"
