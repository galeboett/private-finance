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

