from app.services.importers import detect_preset_from_content, preview_import


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


def test_preview_venmo_statement_rows():
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


def test_preview_venmo_ignores_crypto_summary_rows():
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


def test_preview_venmo_prefers_note_date_without_year():
    content = (
        b"Account Statement - (@hey-matt) ,,,,,,,,,,,,,,,,,,,,,\n"
        b"Account Activity,,,,,,,,,,,,,,,,,,,,,\n"
        b",ID,Datetime,Type,Status,Note,From,To,Amount (total),Amount (tip),Amount (tax),Amount (fee),Tax Rate,Tax Exempt,Funding Source,Destination,Beginning Balance,Ending Balance,Statement Period Venmo Fees,Terminal Location,Year to Date Venmo Fees,Disclaimer\n"
        b",4500240869271348286,2026-01-06T03:43:41,Charge,Complete,Marshalls 12/27,Matt Matt,Kate Thanan,+ $57.53,,0,,0,,,Venmo balance,,,,Venmo,,\n"
    )

    preview = preview_import(content, "venmo_activity")

    assert preview.rows[0]["transaction_date"] == "2025-12-27"
    assert preview.rows[0]["posted_date"] == "2026-01-06"


def test_preview_venmo_prefers_note_date_with_year():
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
