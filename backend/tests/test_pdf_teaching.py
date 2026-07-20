from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, ImportBatch, Institution, PdfExtractionTemplate
from app.schemas import PdfTemplateCreate
from app.services.operation_history import undo_operation
from app.services.pdf_teaching import (
    apply_pdf_templates,
    cache_pdf_content,
    delete_pdf_template,
    inspect_pdf_batch,
    inspect_pdf_content,
    record_template_confirmation,
    teach_pdf_template,
    templates_for_account,
)
from app.services.statement_pdf import extract_statement_pdf, statement_preview_row


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_anchor_relocation_fallback_validation_and_trust_ladder():
    original = _positioned_pdf([
        (72, 730, "Statement Date: 07/14/2026"),
        (72, 690, "Custom Balance"),
        (250, 690, "$1,234.56"),
    ])
    shifted = _positioned_pdf([
        (72, 730, "Statement Date: 08/14/2026"),
        (172, 650, "Custom Balance"),
        (350, 650, "$1,500.00"),
    ])

    with _session() as db:
        institution = Institution(name="Example Bank")
        account = Account(institution=institution, display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        batch = ImportBatch(
            account_id=account.id,
            filename="statement.pdf",
            file_hash="pdf-1",
            semantic_hash="pdf-1",
            status="pending",
            detected_preset="pdf_statement",
        )
        db.add(batch)
        db.flush()
        cache_pdf_content(batch.id, original)
        inspection = inspect_pdf_batch(db, batch.id, 1)
        value_word = next(word for word in inspection["words"] if word["text"] == "$1,234.56")

        taught, operation_id = teach_pdf_template(
            db,
            PdfTemplateCreate(
                staged_batch_id=batch.id,
                field="balance",
                page_number=1,
                region_x0=value_word["x0"] - 0.01,
                region_y0=value_word["y0"] - 0.01,
                region_x1=value_word["x1"] + 0.01,
                region_y1=value_word["y1"] + 0.01,
            ),
            "user:1",
        )
        template = db.get(PdfExtractionTemplate, taught["id"])
        assert operation_id
        assert template.anchor_text == "Balance"
        assert inspection["page_image"] is None
        assert batch.source_path is None

        shifted_row = statement_preview_row(extract_statement_pdf(shifted), account)
        shifted_row = apply_pdf_templates(shifted, [template], account, shifted_row)
        assert shifted_row["selected_balance_cents"] == 150_000
        assert shifted_row["statement_date"] == "2026-08-14"
        assert shifted_row["template_status"] == "anchored"
        assert not shifted_row["auto_commit_eligible"]

        record_template_confirmation(db, shifted_row)
        record_template_confirmation(db, shifted_row)
        assert template.confirmations == 2
        promoted = apply_pdf_templates(shifted, [template], account, statement_preview_row(extract_statement_pdf(shifted), account))
        assert promoted["auto_commit_eligible"]

        edited = {**promoted, "template_edited": True}
        record_template_confirmation(db, edited)
        assert template.confirmations == 0

        absolute = _positioned_pdf([
            (72, 730, "Statement Date: 09/14/2026"),
            (72, 690, "Amount Due"),
            (250, 690, "$1,700.00"),
        ])
        absolute_row = apply_pdf_templates(absolute, [template], account, statement_preview_row(extract_statement_pdf(absolute), account))
        assert absolute_row["selected_balance_cents"] == 170_000
        assert absolute_row["template_status"] == "absolute_fallback"

        invalid = _positioned_pdf([
            (72, 730, "Statement Date: 10/14/2026"),
            (172, 650, "Custom Balance"),
            (350, 650, "NOT-A-VALUE"),
        ])
        template.confirmations = 2
        invalid_row = apply_pdf_templates(invalid, [template], account, statement_preview_row(extract_statement_pdf(invalid), account))
        assert invalid_row["template_status"] == "validation_failed"
        assert template.confirmations == 0
        assert any("layout no longer validates" in warning for warning in invalid_row["warnings"])


def test_template_delete_is_journaled_and_undoable():
    content = _positioned_pdf([(72, 700, "Balance"), (250, 700, "$42.00")])
    with _session() as db:
        institution = Institution(name="Journal Bank")
        account = Account(institution=institution, display_name="Card", account_type="credit_card")
        db.add(account)
        db.flush()
        batch = ImportBatch(account_id=account.id, filename="card.pdf", file_hash="j1", semantic_hash="j1", status="pending", detected_preset="pdf_statement")
        db.add(batch)
        db.flush()
        cache_pdf_content(batch.id, content)
        word = next(word for word in inspect_pdf_content(content, 1)["words"] if word["text"] == "$42.00")
        taught, _ = teach_pdf_template(
            db,
            PdfTemplateCreate(
                staged_batch_id=batch.id,
                field="balance",
                page_number=1,
                region_x0=word["x0"] - 0.01,
                region_y0=word["y0"] - 0.01,
                region_x1=word["x1"] + 0.01,
                region_y1=word["y1"] + 0.01,
            ),
            "user:1",
        )
        delete_operation = delete_pdf_template(db, taught["id"], "user:1")
        db.flush()
        assert db.get(PdfExtractionTemplate, taught["id"]) is None

        undo_operation(db, operation_id=delete_operation, actor="user:1")
        db.flush()
        assert db.get(PdfExtractionTemplate, taught["id"]) is not None


def _positioned_pdf(items: list[tuple[int, int, str]]) -> bytes:
    commands = []
    for x, y, text in items:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"BT /F1 12 Tf {x} {y} Td ({escaped}) Tj ET")
    stream = "\n".join(commands).encode("latin-1")
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
