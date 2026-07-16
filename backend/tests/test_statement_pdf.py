import json
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, ImportBatch, Institution, NetWorthSnapshot, StatementCheckpoint, StatementPdfPattern, StagingRow
from app.services.statement_pdf import commit_pdf_statement, extract_statement_pdf, extract_statement_text, statement_preview_row, update_statement_preview
from app.services.operation_history import undo_operation


BOA_TEXT = """BANK OF AMERICA
Advantage Banking 1234
for May 19, 2026 to June 17, 2026
Beginning balance on May 19, 2026 $12,142.74
Ending balance on June 17, 2026 $8,904.58
"""

CITI_TEXT = """Citibank
Statement Date: 07/14/2026
New Balance $2,804.19
"""


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_boa_statement_pattern_extracts_ending_balance_and_period_date():
    preview = extract_statement_text(BOA_TEXT)

    assert preview.institution == "Bank of America"
    assert preview.statement_date == "2026-06-17"
    assert preview.date_label == "Ending balance date"
    assert preview.candidates[0].label == "Ending Balance"
    assert preview.candidates[0].balance_cents == 890_458
    assert preview.selected_index == 0
    assert preview.confidence == "high"


def test_citi_statement_pattern_extracts_new_balance():
    preview = extract_statement_text(CITI_TEXT)

    assert preview.institution == "Citi"
    assert preview.statement_date == "2026-07-14"
    assert preview.candidates[0].balance_cents == 280_419


def test_local_pdf_text_extraction_uses_the_same_preview_registry():
    preview = extract_statement_pdf(_simple_text_pdf(["Citibank", "Statement Date: 07/14/2026", "New Balance $2,804.19"]), "citi.pdf")

    assert preview.institution == "Citi"
    assert preview.statement_date == "2026-07-14"
    assert preview.candidates[0].balance_cents == 280_419


def test_multiple_balance_candidates_are_low_confidence_and_never_guessed():
    preview = extract_statement_text(
        "Bank of America\nStatement date 06/30/2026\nEnding balance $1,000.00\nTotal balance $1,250.00"
    )

    assert len(preview.candidates) == 2
    assert preview.selected_index is None
    assert preview.confidence == "low"
    assert any("Several labeled balances" in warning for warning in preview.warnings)


def test_credit_card_statement_preview_normalizes_amount_owed_as_liability():
    account = Account(display_name="Citi Card", account_type="credit_card")
    row = statement_preview_row(extract_statement_text(CITI_TEXT), account)

    assert row["selected_balance_cents"] == -280_419
    assert row["candidates"][0]["balance_cents"] == -280_419


def test_pdf_preview_edit_and_confirm_write_anchor_and_saved_pattern_in_one_operation():
    with _session() as session:
        institution = Institution(name="Bank of America")
        account = Account(institution=institution, display_name="BoA Checking", account_type="checking", last_four="1234")
        session.add(account)
        session.flush()
        batch = ImportBatch(
            account_id=account.id,
            filename="boa-1234.pdf",
            file_hash="pdf",
            semantic_hash="pdf",
            status="pending",
            detected_preset="pdf_statement",
            sign_convention="preset",
        )
        session.add(batch)
        session.flush()
        preview_row = statement_preview_row(extract_statement_text(BOA_TEXT), account)
        session.add(
            StagingRow(
                import_batch_id=batch.id,
                account_id=account.id,
                row_index=1,
                row_kind="statement_balance",
                raw_json=json.dumps(preview_row),
                normalized_json=json.dumps(preview_row),
            )
        )
        session.commit()

        update_statement_preview(
            session,
            batch,
            statement_date=date(2026, 6, 30),
            balance_cents=0,
            candidate_index=0,
        )
        result = commit_pdf_statement(session, batch, account, actor="user:1")
        session.commit()

        checkpoint = session.query(StatementCheckpoint).one()
        snapshot = session.query(NetWorthSnapshot).one()
        pattern = session.query(StatementPdfPattern).one()
        assert checkpoint.statement_balance_cents == 890_458
        assert checkpoint.source == "manual"
        assert snapshot.balance_cents == 890_458
        assert pattern.balance_label == "Ending Balance"
        assert result["operation_id"]
        assert batch.status == "committed"
        assert session.query(StagingRow).count() == 0

        undo_operation(session, operation_id=result["operation_id"], actor="user:1")
        session.commit()
        assert session.query(StatementCheckpoint).count() == 0
        assert session.query(NetWorthSnapshot).count() == 0
        assert session.query(StatementPdfPattern).count() == 0


def _simple_text_pdf(lines: list[str]) -> bytes:
    escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
    commands = "BT /F1 12 Tf 72 720 Td 16 TL " + " T* ".join(f"({line}) Tj" for line in escaped) + " ET"
    stream = commands.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode())
        payload.extend(body)
        payload.extend(b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(payload)
