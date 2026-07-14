from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.models import Account, Category, Institution, Transaction
from app.services.importers import commit_categorized_history, commit_reviewed_categorized_history, detect_preset_from_content, preview_import, review_categorized_history, suggest_account_for_import
from app.services.operation_history import undo_operation


def test_detect_card_reference_preset():
    content = b"Posted Date,Reference Number,Payee,Address,Amount\n05/01/2026,123,Store,Addr,-12.34\n"
    assert detect_preset_from_content(content.decode("utf-8")) == "card_reference"


def test_preview_checking_rows():
    content = (
        b"Description,,Summary Amt.,\n"
        b"Beginning balance as of 01/01/2026,,\"5,000.00\",\n"
        b",,,\n"
        b"Date,Description,Amount,Running Bal.\n"
        b"01/02/2026,Grocery Store,-50,\"4,950.00\"\n"
    )
    preview = preview_import(content, "checking_running_balance")
    assert len(preview.rows) == 1
    assert preview.rows[0]["raw_description"] == "Grocery Store"


def test_preview_brokerage_rows_keeps_account_identity():
    content = (
        b"Account Number,Account Name,Symbol,Description,Quantity,Last Price,Last Price Change,Current Value\n"
        b"Z12345678,Taxable Brokerage,VTI,Vanguard Total Stock,1,250.00,0.00,250.00\n"
    )
    preview = preview_import(content, "brokerage_positions")

    assert len(preview.rows) == 1
    assert preview.rows[0]["account_number"] == "Z12345678"
    assert preview.rows[0]["account_name"] == "Taxable Brokerage"
    assert preview.rows[0]["quantity"] == "1"
    assert preview.rows[0]["price"] == "250.00"


def test_suggest_account_for_brokerage_positions_matches_existing_last_four():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(display_name="Fidelity BrokerageLink", account_type="brokerage", last_four="5678")
        session.add(account)
        session.commit()
        content = (
            b"Account Number,Account Name,Symbol,Description,Quantity,Last Price,Last Price Change,Current Value\n"
            b"Z12345678,Taxable Brokerage,VTI,Vanguard Total Stock,1,250.00,0.00,250.00\n"
        )

        suggestion = suggest_account_for_import(session, "Portfolio_Positions_Jul-07-2026.csv", content)

        assert suggestion.preset_type == "brokerage_positions"
        assert suggestion.suggested_account_id == account.id
        assert suggestion.match_confidence >= 70
        assert suggestion.proposed_account["last_four"] == "5678"


def test_suggest_account_prepopulates_card_details_from_filename():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        content = b"Posted Date,Reference Number,Payee,Address,Amount\n05/01/2026,123,Store,Addr,-12.34\n"

        suggestion = suggest_account_for_import(session, "Chase5618_Activity20260707.CSV", content)

        assert suggestion.suggested_account_id is None
        assert suggestion.proposed_account["account_type"] == "credit_card"
        assert suggestion.proposed_account["institution_name"] == "Chase"
        assert suggestion.proposed_account["last_four"] == "5618"


def test_preview_brokerage_rows_allows_blank_description():
    content = (
        b"Account Number,Account Name,Symbol,Description,Quantity,Last Price,Last Price Change,Current Value\n"
        b"Z12345678,Taxable Brokerage,VMFXX,,1,1.00,0.00,1.00\n"
    )
    preview = preview_import(content, "brokerage_positions")

    assert len(preview.rows) == 1
    assert preview.rows[0]["description"] == ""


def test_preview_brokerage_link_aggregate_rows_are_ignored():
    content = (
        b"Account Number,Account Name,Symbol,Description,Quantity,Last Price,Last Price Change,Current Value\n"
        b"Z12345678,401k,,BROKERAGELINK,0,0,0,\"1,000.00\"\n"
        b"Z12345678,401k,VTI,Vanguard Total Stock,1,250.00,0.00,250.00\n"
    )
    preview = preview_import(content, "brokerage_positions")

    assert preview.rows[0]["row_kind"] == "ignore"
    assert preview.rows[1]["row_kind"] == "position"


def test_detect_venmo_statement_with_intro_rows():
    content = (
        b"Account Statement - (@hey-matt) ,,,,,,,,,,,,,,,,,,,,,\n"
        b"Account Activity,,,,,,,,,,,,,,,,,,,,,\n"
        b",ID,Datetime,Type,Status,Note,From,To,Amount (total),Amount (tip),Amount (tax),Amount (fee),Tax Rate,Tax Exempt,Funding Source,Destination,Beginning Balance,Ending Balance,Statement Period Venmo Fees,Terminal Location,Year to Date Venmo Fees,Disclaimer\n"
        b",4500240869271348286,2026-01-01T03:35:16,Charge,Complete,Yt premium monthly,Matt Matt,David Pham,+ $3.83,,0,,0,,,Venmo balance,,,,Venmo,,\n"
    )

    assert detect_preset_from_content(content.decode("utf-8")) == "venmo_activity"


def test_preview_venmo_statement_rows(monkeypatch):
    monkeypatch.setattr(settings, "venmo_self_name", "Matt Matt")
    content = (
        b"Account Statement - (@hey-matt) ,,,,,,,,,,,,,,,,,,,,,\n"
        b"Account Activity,,,,,,,,,,,,,,,,,,,,,\n"
        b",ID,Datetime,Type,Status,Note,From,To,Amount (total),Amount (tip),Amount (tax),Amount (fee),Tax Rate,Tax Exempt,Funding Source,Destination,Beginning Balance,Ending Balance,Statement Period Venmo Fees,Terminal Location,Year to Date Venmo Fees,Disclaimer\n"
        b",4500240869271348286,2026-01-01T03:35:16,Charge,Complete,Yt premium monthly,Matt Matt,David Pham,+ $3.83,,0,,0,,,Venmo balance,,,,Venmo,,\n"
    )

    preview = preview_import(content, "venmo_activity")

    assert len(preview.rows) == 1
    assert preview.rows[0]["transaction_date"] == "2026-01-01"
    assert preview.rows[0]["raw_description"] == "Yt premium monthly | David Pham paid Matt Matt"
    assert preview.rows[0]["amount"] == "+3.83"
    assert preview.rows[0]["source_reference"] == "4500240869271348286"


def test_preview_venmo_ignores_crypto_summary_rows(monkeypatch):
    monkeypatch.setattr(settings, "venmo_self_name", "Matt Matt")
    content = (
        b"Account Statement - (@hey-matt) ,,,,,,,,,,,,,,,,,,,,,\n"
        b"Account Activity,,,,,,,,,,,,,,,,,,,,,\n"
        b",ID,Datetime,Type,Status,Note,From,To,Amount (total),Amount (tip),Amount (tax),Amount (fee),Tax Rate,Tax Exempt,Funding Source,Destination,Beginning Balance,Ending Balance,Statement Period Venmo Fees,Terminal Location,Year to Date Venmo Fees,Disclaimer\n"
        b",4500240869271348286,2026-01-01T03:35:16,Charge,Complete,Yt premium monthly,Matt Matt,David Pham,+ $3.83,,0,,0,,,Venmo balance,,,,Venmo,,\n"
        b"Cryptocurrency summary,,,,,,,,,,,,,,,,,,,,,\n"
        b",Ethereum,,,,,,,,,,,,,,,,,,,,\n"
        b",Available,0.008271,,,,,,,,,,,,,,,,,,,\n"
        b"Cryptocurrency summary in USD (Estimated values as of Jul 03 2023 09:04 hours UTC),,,,,,,,,,,,,,,,,,,,,\n"
        b",Ethereum,,,,,,,,,,,,,,,,,,,,\n"
        b",Available,18.90546,,,,,,,,,,,,,,,,,,,\n"
    )

    preview = preview_import(content, "venmo_activity")

    assert len(preview.rows) == 1
    assert preview.rows[0]["raw_description"] == "Yt premium monthly | David Pham paid Matt Matt"


def test_preview_venmo_prefers_note_date_without_year(monkeypatch):
    monkeypatch.setattr(settings, "venmo_self_name", "Matt Matt")
    content = (
        b"Account Statement - (@hey-matt) ,,,,,,,,,,,,,,,,,,,,,\n"
        b"Account Activity,,,,,,,,,,,,,,,,,,,,,\n"
        b",ID,Datetime,Type,Status,Note,From,To,Amount (total),Amount (tip),Amount (tax),Amount (fee),Tax Rate,Tax Exempt,Funding Source,Destination,Beginning Balance,Ending Balance,Statement Period Venmo Fees,Terminal Location,Year to Date Venmo Fees,Disclaimer\n"
        b",4500240869271348286,2026-01-06T03:43:41,Charge,Complete,Marshalls 12/27,Matt Matt,Kate Thanan,+ $57.53,,0,,0,,,Venmo balance,,,,Venmo,,\n"
    )

    preview = preview_import(content, "venmo_activity")

    assert preview.rows[0]["transaction_date"] == "2025-12-27"
    assert preview.rows[0]["posted_date"] == "2026-01-06"


def test_preview_venmo_prefers_note_date_with_year(monkeypatch):
    monkeypatch.setattr(settings, "venmo_self_name", "Matt Matt")
    content = (
        b"Account Statement - (@hey-matt) ,,,,,,,,,,,,,,,,,,,,,\n"
        b"Account Activity,,,,,,,,,,,,,,,,,,,,,\n"
        b",ID,Datetime,Type,Status,Note,From,To,Amount (total),Amount (tip),Amount (tax),Amount (fee),Tax Rate,Tax Exempt,Funding Source,Destination,Beginning Balance,Ending Balance,Statement Period Venmo Fees,Terminal Location,Year to Date Venmo Fees,Disclaimer\n"
        b",4500240869271348286,2026-01-06T03:51:25,Payment,Complete,Jan 2025 rent 1/1/26,Kate Thanan,Matt Matt,- $1,600.00,,0,,0,,,Venmo balance,,,,Venmo,,\n"
    )

    preview = preview_import(content, "venmo_activity")

    assert preview.rows[0]["transaction_date"] == "2026-01-01"
    assert preview.rows[0]["raw_description"] == "Jan 2025 rent 1/1/26 | Matt Matt paid Kate Thanan"


def test_preview_venmo_maps_transaction_types():
    content = (
        b"Account Statement - (@hey-matt) ,,,,,,,,,,,,,,,,,,,,,\n"
        b"Account Activity,,,,,,,,,,,,,,,,,,,,,\n"
        b",ID,Datetime,Type,Status,Note,From,To,Amount (total),Amount (tip),Amount (tax),Amount (fee),Tax Rate,Tax Exempt,Funding Source,Destination,Beginning Balance,Ending Balance,Statement Period Venmo Fees,Terminal Location,Year to Date Venmo Fees,Disclaimer\n"
        b",4500240869271348286,2026-01-01T03:35:16,Charge,Complete,Dinner refund,Alex Kim,Matt Matt,+ $20.00,,0,,0,,,Venmo balance,,,,Venmo,,\n"
        b",4500240869271348287,2026-01-02T03:35:16,Payment,Complete,Dinner,Matt Matt,Alex Kim,- $20.00,,0,,0,,,Venmo balance,,,,Venmo,,\n"
        b",4500240869271348288,2026-01-03T03:35:16,Standard Transfer,Issued,Cash out,Matt Matt,BANK OF AMERICA,- $30.00,,0,,0,,,Venmo balance,BANK OF AMERICA,,,,Venmo,,\n"
    )

    preview = preview_import(content, "venmo_activity")

    assert [row["transaction_type"] for row in preview.rows] == ["refund", "expense", "transfer"]


def test_commit_categorized_history_creates_accounts_categories_and_confirmed_transactions():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        content = (
            b"Account,Posted Date,Payee,Amount,Expense Category\n"
            b"Chase Sapphire,08/01/2018,ANNUAL MEMBERSHIP FEE,150.00,Fees & Charges\n"
            b"Venmo,08/04/2018,Withdrew cash,-36.70,Income\n"
        )

        result = commit_categorized_history(session, "history.csv", content)
        session.commit()

        accounts = session.query(Account).order_by(Account.display_name).all()
        categories = session.query(Category).order_by(Category.label).all()
        transactions = session.query(Transaction).order_by(Transaction.raw_description).all()

        assert result["inserted"] == 2
        assert result["accounts_created"] == 2
        assert result["categories_created"] == 2
        assert [account.display_name for account in accounts] == ["Chase Sapphire", "Venmo"]
        assert [category.label for category in categories] == ["Fees & Charges", "Income"]
        assert all(transaction.review_status == "confirmed" for transaction in transactions)
        assert {transaction.transaction_type for transaction in transactions} == {"expense", "income"}
        chase = next(transaction for transaction in transactions if transaction.raw_description == "ANNUAL MEMBERSHIP FEE")
        venmo = next(transaction for transaction in transactions if transaction.raw_description == "Withdrew cash")
        assert chase.amount_cents == -15000
        assert venmo.amount_cents == 3670
        assert result["operation_id"]

        undo_operation(session, operation_id=result["operation_id"], actor="user:1")
        session.commit()
        assert all(transaction.deleted_at is not None for transaction in session.query(Transaction).all())


def test_commit_categorized_history_skips_duplicates_on_reupload():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        content = b"Account,Posted Date,Payee,Amount,Expense Category\nChase Sapphire,08/01/2018,ANNUAL MEMBERSHIP FEE,150.00,Fees & Charges\n"

        first = commit_categorized_history(session, "history.csv", content)
        session.commit()
        second = commit_categorized_history(session, "history.csv", content)
        session.commit()

        assert first["inserted"] == 1
        assert second["inserted"] == 0
        assert second["skipped"] == 1
        assert session.query(Transaction).count() == 1


def test_categorized_history_matches_existing_accounts_by_suffix_and_safe_alias():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        institution = Institution(name="Bank of America")
        suffix_account = Account(institution=institution, display_name="BoA Cash", account_type="credit_card", last_four="3056")
        alias_account = Account(institution=institution, display_name="BoA Cash USC", account_type="credit_card", last_four="0078")
        session.add_all([suffix_account, alias_account])
        session.commit()
        content = (
            b"Account,Posted Date,Payee,Amount,Expense Category\n"
            b"BoA Cash 3056,01/24/2026,Purchase one,10.00,Shopping\n"
            b"BoA Cash Rewards USC,01/26/2026,Purchase two,20.00,Shopping\n"
        )

        result = commit_categorized_history(session, "history.csv", content)
        session.commit()

        assert result["accounts_created"] == 0
        assert session.query(Account).count() == 2
        assert {transaction.account_id for transaction in session.query(Transaction).all()} == {suffix_account.id, alias_account.id}


def test_categorized_history_surfaces_rows_missing_dates_for_review():
    content = (
        b"Account,Posted Date,Payee,Amount,Expense Category\n"
        b"Chase Sapphire,08/01/2018,ANNUAL MEMBERSHIP FEE,150.00,Fees & Charges\n"
        b"Chase Sapphire,,Subtotal,,\n"
        b"Venmo,08/04/2018,Withdrew cash,-36.70,Income\n"
    )

    review = review_categorized_history("history.csv", content)

    assert review["needs_review"] is True
    assert review["rows"][1]["errors"] == ["Posted Date", "Amount"]


def test_commit_reviewed_categorized_history_imports_edited_rows():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        rows = [
            {"row_index": "2", "account": "Chase Sapphire", "posted_date": "08/01/2018", "payee": "ANNUAL MEMBERSHIP FEE", "amount": "150.00", "category": "Fees & Charges"},
            {"row_index": "3", "account": "Chase Sapphire", "posted_date": "08/02/2018", "payee": "Subtotal", "amount": "1.00", "category": "Fees & Charges"},
        ]

        result = commit_reviewed_categorized_history(session, "history.csv", rows)
        session.commit()

        assert result["inserted"] == 2
        assert session.query(Transaction).count() == 2


def test_detects_filename_aware_citi_formats():
    content = "Status,Date,Description,Debit,Credit\nCleared,06-01-2026,Purchase,10.00,\n"

    assert detect_preset_from_content(content, "CHK_4160_CURRENT_VIEW.csv") == "citi_checking"
    assert detect_preset_from_content(content, "Statement closed Jul 01, 2026.CSV") == "citi_card_activity"


def test_preview_citi_checking_normalizes_debits_and_credits():
    content = (
        b"Status,Date,Description,Debit,Credit\n"
        b"Cleared,05-05-2026,Debit Card Purchase,118.08,\n"
        b"Cleared,06-01-2026,ATM Fee Refund,,0.71\n"
    )

    preview = preview_import(content, "citi_checking")

    assert [row["amount"] for row in preview.rows] == ["-118.08", "0.71"]
    assert [row["transaction_date"] for row in preview.rows] == ["05-05-2026", "06-01-2026"]


def test_preview_citi_card_normalizes_purchases_and_credits():
    content = (
        b"Status,Date,Description,Debit,Credit\n"
        b"Cleared,06/17/2026,NEWEGG INC.,10.00,\n"
        b"Cleared,06/25/2026,AUTOPAY AUTO-PMT,,-17.70\n"
    )

    preview = preview_import(content, "citi_card_activity")

    assert [row["amount"] for row in preview.rows] == ["-10.00", "17.70"]


def test_preview_amex_normalizes_charge_credit_signs():
    content = (
        b"Date,Description,Amount\n"
        b"07/07/2026,INKD DAYGLOW,4.00\n"
        b"07/04/2026,AUTOPAY PAYMENT - THANK YOU,-1493.35\n"
    )

    preview = preview_import(content, "amex_activity")

    assert [row["amount"] for row in preview.rows] == ["-4.00", "1493.35"]


def test_preview_jpm_positions_uses_holding_fields_and_ignores_footer():
    content = (
        b"Asset Class,Asset Strategy,Asset Strategy Detail,Description,Ticker,CUSIP,Quantity,Price,Value,As of\n"
        b"Equity,US Large Cap,,VANGUARD S&P 500 ETF,VOO,922908363,320,693.86,\"222,035.2\",07/11/2026\n"
        b"FOOTNOTES,,,,,,,,,\n"
        b"P,This order is pending settlement.,,,,,,,,\n"
    )

    preview = preview_import(content, "jpm_brokerage_positions")

    assert len(preview.rows) == 1
    assert preview.rows[0]["symbol"] == "VOO"
    assert preview.rows[0]["market_value"] == "222,035.2"
    assert preview.rows[0]["snapshot_date"] == "07/11/2026"


def test_preview_compact_positions_skips_metadata_and_total():
    content = (
        b'"Positions for account Individual ...373 as of 03:44 AM ET, 2026/07/14"\n\n'
        b'"Symbol","Description","Qty (Quantity)","Price","Mkt Val (Market Value)","Asset Type",\n'
        b'"VOO","VANGUARD S&P 500 ETF","94.527","688.50","$65,081.84","ETFs & Closed End Funds",\n'
        b'"Cash & Cash Investments","--","--","--","$23.81","Cash and Money Market",\n'
        b'"Positions Total","","--","--","$65,105.65","",\n'
    )

    assert detect_preset_from_content(content.decode(), "Individual-Positions-2026-07-14.csv") == "brokerage_positions_compact"
    preview = preview_import(content, "brokerage_positions_compact")

    assert len(preview.rows) == 2
    assert preview.rows[0]["symbol"] == "VOO"
    assert preview.rows[0]["market_value"] == "$65,081.84"
    assert preview.rows[0]["account_name"] == "Individual ...373"
    assert preview.rows[1]["symbol"] is None
    assert preview.rows[1]["description"] == "Cash & Cash Investments"


def test_new_formats_propose_expected_accounts_without_treating_year_as_last_four():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        citi_checking = suggest_account_for_import(
            session,
            "CHK_4160_CURRENT_VIEW.csv",
            b"Status,Date,Description,Debit,Credit\nCleared,06-01-2026,Purchase,10.00,\n",
        )
        citi_card = suggest_account_for_import(
            session,
            "Statement closed Jul 01, 2026.CSV",
            b"Status,Date,Description,Debit,Credit\nCleared,06/17/2026,Purchase,10.00,\n",
        )
        amex = suggest_account_for_import(
            session,
            "activity (2).csv",
            b"Date,Description,Amount\n07/07/2026,Purchase,4.00\n",
        )

    assert citi_checking.proposed_account["institution_name"] == "Citi"
    assert citi_checking.proposed_account["account_type"] == "checking"
    assert citi_checking.proposed_account["last_four"] == "4160"
    assert citi_card.proposed_account["institution_name"] == "Citi"
    assert citi_card.proposed_account["account_type"] == "credit_card"
    assert citi_card.proposed_account["last_four"] is None
    assert amex.proposed_account["institution_name"] == "American Express"
    assert amex.proposed_account["account_type"] == "credit_card"


def test_jpm_positions_match_a_unique_existing_brokerage_by_name():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(display_name="JPM Investments", account_type="brokerage")
        session.add(account)
        session.commit()
        content = (
            b"Asset Class,Asset Strategy,Asset Strategy Detail,Description,Ticker,CUSIP,Quantity,Price,Value,As of\n"
            b"Equity,US Large Cap,,VANGUARD S&P 500 ETF,VOO,922908363,320,693.86,\"222,035.2\",07/11/2026\n"
        )

        suggestion = suggest_account_for_import(session, "positions.csv", content)

    assert suggestion.suggested_account_id == account.id
    assert suggestion.match_confidence == 75
    assert suggestion.proposed_account == {
        "institution_name": "Chase",
        "display_name": "Chase J.P. Morgan Brokerage",
        "account_type": "brokerage",
        "currency": "USD",
        "last_four": None,
    }
