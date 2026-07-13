from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, Category, CategoryRule, HoldingSnapshot, NetWorthSnapshot, Transaction
from app.services.importers import (
    _extract_snapshot_date,
    _history_transaction_type,
    commit_import,
    decode_text,
)


CARD_CSV = (
    b"Posted Date,Reference Number,Payee,Address,Amount\n"
    b"05/01/2026,111,Grocery Store,Addr,-42.10\n"
    b"05/02/2026,222,Coffee Shop,Addr,-5.25\n"
)

BROKERAGE_CSV = (
    b"Account Number,Account Name,Symbol,Description,Quantity,Last Price,Last Price Change,Current Value\n"
    b"Z12345678,Taxable Brokerage,VTI,Vanguard Total Stock,2,250.00,0.00,500.00\n"
    b"Z12345678,Taxable Brokerage,BND,Vanguard Total Bond,1,72.00,0.00,72.00\n"
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_commit_import_skips_duplicates_on_reupload():
    """Regression for BUG-01: re-committing an overlapping file must skip, not crash."""
    with _session() as session:
        account = Account(display_name="Card", account_type="credit_card")
        session.add(account)
        session.commit()

        first = commit_import(session, account, None, "card.csv", CARD_CSV)
        session.commit()
        second = commit_import(session, account, None, "card.csv", CARD_CSV)
        session.commit()

        assert first["inserted"] == 2 and first["skipped"] == 0
        assert second["inserted"] == 0 and second["skipped"] == 2
        assert session.query(Transaction).count() == 2


def test_commit_import_reimport_replaces_holdings_snapshot():
    """Regression for BUG-02: re-importing a positions file must not double net worth."""
    with _session() as session:
        account = Account(display_name="Taxable Brokerage", account_type="brokerage", last_four="5678")
        session.add(account)
        session.commit()

        commit_import(session, account, None, "Portfolio_Positions_Jul-04-2026.csv", BROKERAGE_CSV)
        session.commit()
        commit_import(session, account, None, "Portfolio_Positions_Jul-04-2026.csv", BROKERAGE_CSV)
        session.commit()

        holdings = session.query(HoldingSnapshot).all()
        assert len(holdings) == 2
        assert sum(row.market_value_cents for row in holdings) == 57200
        snapshots = session.query(NetWorthSnapshot).all()
        assert len(snapshots) == 1
        assert snapshots[0].balance_cents == 57200


def test_commit_import_records_running_balance_snapshot():
    with _session() as session:
        account = Account(display_name="Checking", account_type="checking")
        session.add(account)
        session.commit()
        content = b"Date,Description,Amount,Running Bal.\n07/01/2026,Deposit,100.00,1000.00\n"

        commit_import(session, account, None, "checking.csv", content)
        session.commit()

        snapshot = session.query(NetWorthSnapshot).one()
        assert snapshot.snapshot_date == date(2026, 7, 1)
        assert snapshot.balance_cents == 100000
        assert snapshot.source == "import"


def test_commit_import_uses_filename_snapshot_date():
    """Regression for BUG-03: the snapshot date must come from the filename, not today."""
    with _session() as session:
        account = Account(display_name="Taxable Brokerage", account_type="brokerage")
        session.add(account)
        session.commit()

        commit_import(session, account, None, "Portfolio_Positions_Jul-04-2026.csv", BROKERAGE_CSV)
        session.commit()

        assert {row.snapshot_date for row in session.query(HoldingSnapshot).all()} == {date(2026, 7, 4)}


def test_commit_import_explicit_snapshot_date_overrides_filename():
    with _session() as session:
        account = Account(display_name="Taxable Brokerage", account_type="brokerage")
        session.add(account)
        session.commit()

        commit_import(session, account, None, "positions.csv", BROKERAGE_CSV, snapshot_date=date(2026, 3, 31))
        session.commit()

        assert {row.snapshot_date for row in session.query(HoldingSnapshot).all()} == {date(2026, 3, 31)}


def test_commit_import_undated_filename_warns_and_uses_today():
    with _session() as session:
        account = Account(display_name="Taxable Brokerage", account_type="brokerage")
        session.add(account)
        session.commit()

        result = commit_import(session, account, None, "positions.csv", BROKERAGE_CSV)
        session.commit()

        assert any("Could not find a date" in warning for warning in result["warnings"])
        assert {row.snapshot_date for row in session.query(HoldingSnapshot).all()} == {date.today()}


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Portfolio_Positions_Jul-04-2026.csv", date(2026, 7, 4)),
        ("positions-2026-07-04.csv", date(2026, 7, 4)),
        ("positions_20260704.csv", date(2026, 7, 4)),
        ("positions 07-04-2026.csv", date(2026, 7, 4)),
        ("positions.csv", None),
        ("statement-4500.csv", None),
    ],
)
def test_extract_snapshot_date(filename, expected):
    assert _extract_snapshot_date(filename) == expected


def test_commit_import_applies_rule_category_and_type_as_suggestion():
    """Import-time rule matches carry the rule's transaction type and stay reviewable."""
    with _session() as session:
        account = Account(display_name="Checkings", account_type="checking")
        category = Category(key="work", label="Work")
        session.add_all([account, category])
        session.flush()
        session.add(
            CategoryRule(
                category_id=category.id,
                field_name="raw_description",
                match_text="coffee",
                suggested_transaction_type="refund",
                priority=10,
            )
        )
        session.commit()

        content = (
            b"Description,,Summary Amt.,\n"
            b"Date,Description,Amount,Running Bal.\n"
            b'01/02/2026,Coffee Shop,-5.25,"4,950.00"\n'
        )
        commit_import(session, account, None, "checking.csv", content)
        session.commit()

        row = session.query(Transaction).one()
        assert row.category_id == category.id
        assert row.transaction_type == "refund"
        assert row.review_status == "suggested"


def test_commit_import_links_possible_duplicates():
    """Same date+amount with a different description flags and links the original row."""
    with _session() as session:
        account = Account(display_name="Card", account_type="credit_card")
        session.add(account)
        session.commit()

        first_file = b"Posted Date,Reference Number,Payee,Address,Amount\n05/01/2026,111,Grocery Store,Addr,-42.10\n"
        second_file = b"Posted Date,Reference Number,Payee,Address,Amount\n05/01/2026,999,GROCERY STORE #42,Addr,-42.10\n"
        commit_import(session, account, None, "a.csv", first_file)
        session.commit()
        commit_import(session, account, None, "b.csv", second_file)
        session.commit()

        original = session.query(Transaction).filter_by(raw_description="Grocery Store").one()
        flagged = session.query(Transaction).filter_by(raw_description="GROCERY STORE #42").one()
        assert flagged.review_status == "possible_duplicate"
        assert flagged.duplicate_of_transaction_id == original.id


def test_decode_text_rejects_non_utf8():
    with pytest.raises(ValueError):
        decode_text(b"\xff\xfe\x00 binary")


@pytest.mark.parametrize(
    ("label", "amount_cents", "account_type", "inverted_history_sign", "expected"),
    [
        ("Income", 250000, "checking", False, "income"),
        ("", 250000, "checking", False, "income"),
        ("", 100000, "savings", False, "income"),
        ("", -4200, "checking", False, "expense"),
        ("Refund", 4200, "credit_card", False, "refund"),
        ("", 4200, "credit_card", False, "refund"),
        ("", -4200, "credit_card", True, "expense"),
        ("", 4200, "credit_card", True, "refund"),
        ("Credit Card Payment", -50000, "checking", False, "transfer"),
        ("Transfer", 50000, "savings", False, "transfer"),
        ("Groceries", -4200, "checking", False, "expense"),
    ],
)
def test_history_transaction_type_matrix(label, amount_cents, account_type, inverted_history_sign, expected):
    """Regression for BUG-05: deposits into cash accounts must not be typed as expenses."""
    account = Account(display_name="Test", account_type=account_type)
    assert _history_transaction_type(label, amount_cents, account, inverted_history_sign) == expected


def test_commit_jpm_positions_uses_as_of_date_and_ignores_footnotes():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(display_name="J.P. Morgan Brokerage", account_type="brokerage")
        session.add(account)
        session.commit()
        content = (
            b"Asset Class,Asset Strategy,Asset Strategy Detail,Description,Ticker,CUSIP,Quantity,Price,Value,As of\n"
            b"Equity,US Large Cap,,VANGUARD S&P 500 ETF,VOO,922908363,320,693.86,\"222,035.2\",07/11/2026\n"
            b"Cash & Money Market Funds,Money Market Funds,,CHASE DEPOSIT SWEEP,QACDS,,1228.9,1,1228.9,07/11/2026\n"
            b"FOOTNOTES,,,,,,,,,\n"
        )

        result = commit_import(session, account, None, "positions.csv", content)
        session.commit()

        holdings = session.query(HoldingSnapshot).order_by(HoldingSnapshot.symbol).all()

    assert result["inserted"] == 2
    assert result["warnings"] == []
    assert [holding.symbol for holding in holdings] == ["QACDS", "VOO"]
    assert {holding.snapshot_date for holding in holdings} == {date(2026, 7, 11)}
    assert sum(holding.market_value_cents for holding in holdings) == 22326410
