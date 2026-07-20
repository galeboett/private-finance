from __future__ import annotations

import io
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import pdfplumber
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Account, ImportBatch, PdfExtractionTemplate
from ..money import parse_decimal_to_cents
from ..schemas import PdfTemplateCreate
from .mutation_log import MutationChange, full_values, journal_mutation


CURRENCY_VALUE_PATTERN = r"^\s*\$?\s*\(?-?[\d,]+\.\d{2}\)?\s*$"
DATE_VALUE_PATTERN = r"^\s*(?:[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})\s*$"
LAST4_VALUE_PATTERN = r"^\s*\d{4}\s*$"
_PDF_CONTENT_CACHE: dict[int, bytes] = {}


def cache_pdf_content(batch_id: int, content: bytes) -> None:
    _PDF_CONTENT_CACHE[batch_id] = content


def forget_pdf_content(batch_id: int) -> None:
    _PDF_CONTENT_CACHE.pop(batch_id, None)


def pdf_content_for_batch(batch: ImportBatch) -> bytes:
    cached = _PDF_CONTENT_CACHE.get(batch.id)
    if cached is not None:
        return cached
    if batch.source_path:
        source = Path(batch.source_path).expanduser().resolve()
        if source.is_file() and source.suffix.casefold() == ".pdf":
            return source.read_bytes()
    raise ValueError("The PDF is no longer available for teaching. Stage it again and reopen the teacher.")


def inspect_pdf_batch(db: Session, batch_id: int, page_number: int) -> dict:
    batch = db.get(ImportBatch, batch_id)
    if not batch or batch.detected_preset != "pdf_statement":
        raise ValueError("Choose a staged PDF statement")
    return inspect_pdf_content(pdf_content_for_batch(batch), page_number)


def inspect_pdf_content(content: bytes, page_number: int) -> dict:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                raise ValueError(f"Choose a page from 1 to {len(pdf.pages)}")
            page = pdf.pages[page_number - 1]
            width = float(page.width)
            height = float(page.height)
            words = [
                {
                    "text": str(word["text"]),
                    "x0": float(word["x0"]) / width,
                    "y0": float(word["top"]) / height,
                    "x1": float(word["x1"]) / width,
                    "y1": float(word["bottom"]) / height,
                }
                for word in page.extract_words()
                if str(word.get("text") or "").strip()
            ]
            return {
                "page_count": len(pdf.pages),
                "page": page_number,
                "width": width,
                "height": height,
                "page_image": None,
                "render_mode": "word_boxes",
                "words": words,
            }
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("Could not inspect this PDF statement") from error


def teach_pdf_template(db: Session, payload: PdfTemplateCreate, actor: str) -> tuple[dict, str]:
    batch = db.get(ImportBatch, payload.staged_batch_id)
    if not batch or batch.detected_preset != "pdf_statement":
        raise ValueError("Choose a staged PDF statement")
    account = db.get(Account, batch.account_id)
    if not account or not account.institution:
        raise ValueError("The staged statement needs an institution before teaching")
    inspection = inspect_pdf_content(pdf_content_for_batch(batch), payload.page_number)
    region = _ordered_region(payload.region_x0, payload.region_y0, payload.region_x1, payload.region_y1)
    selected = _words_in_region(inspection["words"], region)
    captured_text = _joined_words(selected)
    if not captured_text:
        raise ValueError("Draw a box around the value to capture")
    value_pattern = payload.value_pattern or _default_value_pattern(payload.field)
    try:
        valid = re.fullmatch(value_pattern, captured_text, flags=re.IGNORECASE) is not None
    except re.error as error:
        raise ValueError("The value validation pattern is invalid") from error
    if not valid:
        raise ValueError(f'The selected text "{captured_text}" does not match the {payload.field.replace("_", " ")} format')

    anchor = _select_anchor(inspection["words"], selected, region, payload.anchor_text)
    target_center = _region_center(region)
    anchor_center = _word_center(anchor) if anchor else None
    account_id = account.id
    template = db.scalar(
        select(PdfExtractionTemplate).where(
            PdfExtractionTemplate.institution == account.institution.name,
            PdfExtractionTemplate.account_id == account_id,
            PdfExtractionTemplate.field == payload.field,
        )
    )
    before = full_values(template) if template else None
    if template is None:
        template = PdfExtractionTemplate(
            institution=account.institution.name,
            account_id=account_id,
            field=payload.field,
            page_number=payload.page_number,
            region_x0=region[0],
            region_y0=region[1],
            region_x1=region[2],
            region_y1=region[3],
            value_pattern=value_pattern,
        )
        db.add(template)
        db.flush()
    template.page_number = payload.page_number
    template.anchor_text = anchor["text"] if anchor else None
    template.anchor_dx = target_center[0] - anchor_center[0] if anchor_center else None
    template.anchor_dy = target_center[1] - anchor_center[1] if anchor_center else None
    template.region_x0, template.region_y0, template.region_x1, template.region_y1 = region
    template.value_pattern = value_pattern
    template.confirmations = 0
    db.flush()
    operation_id = journal_mutation(
        db,
        kind="update" if before else "create",
        entity_type="pdf_extraction_template",
        actor=actor,
        description=f'Taught PDF {payload.field.replace("_", " ")} extraction for {account.display_name}',
        changes=[MutationChange(template.id, before, full_values(template))],
    )
    return {**template_payload(template), "captured_text": captured_text}, operation_id


def list_pdf_templates(db: Session) -> list[dict]:
    return [template_payload(template) for template in db.scalars(select(PdfExtractionTemplate).order_by(PdfExtractionTemplate.institution, PdfExtractionTemplate.account_id, PdfExtractionTemplate.field)).all()]


def delete_pdf_template(db: Session, template_id: int, actor: str) -> str:
    template = db.get(PdfExtractionTemplate, template_id)
    if not template:
        raise ValueError("PDF extraction template not found")
    operation_id = journal_mutation(
        db,
        kind="delete",
        entity_type="pdf_extraction_template",
        actor=actor,
        description=f"Deleted PDF {template.field.replace('_', ' ')} template for {template.institution}",
        changes=[MutationChange(template.id, full_values(template), None)],
    )
    db.delete(template)
    return operation_id


def templates_for_account(db: Session, account: Account) -> list[PdfExtractionTemplate]:
    if not account.institution:
        return []
    rows = db.scalars(
        select(PdfExtractionTemplate).where(
            PdfExtractionTemplate.institution == account.institution.name,
            or_(PdfExtractionTemplate.account_id.is_(None), PdfExtractionTemplate.account_id == account.id),
        )
    ).all()
    by_field: dict[str, PdfExtractionTemplate] = {}
    for row in rows:
        if row.field not in by_field or row.account_id == account.id:
            by_field[row.field] = row
    return list(by_field.values())


def apply_pdf_templates(content: bytes, templates: list[PdfExtractionTemplate], account: Account, row: dict) -> dict:
    applied_ids: list[int] = []
    statuses: list[str] = []
    original_balance = row.get("selected_balance_cents")
    original_date = row.get("statement_date")
    for template in templates:
        try:
            inspection = _inspection_for_template(content, template)
            captured, status = _capture_template_value(inspection["words"], template)
        except ValueError:
            template.confirmations = 0
            statuses.append("page_missing")
            continue
        if not captured or re.fullmatch(template.value_pattern, captured, flags=re.IGNORECASE) is None:
            template.confirmations = 0
            statuses.append("validation_failed")
            continue
        if template.field == "balance":
            cents = _currency_cents(captured)
            row["selected_balance_cents"] = -abs(cents) if account.account_type == "credit_card" else cents
            row["selected_balance_label"] = template.anchor_text or "Taught region"
            row["selected_index"] = None
        elif template.field == "statement_date":
            parsed = _parse_date(captured)
            if parsed is None:
                template.confirmations = 0
                statuses.append("validation_failed")
                continue
            row["statement_date"] = parsed
        elif template.field == "account_last4":
            row["account_last4"] = captured.strip()
        applied_ids.append(template.id)
        statuses.append(status)

    if applied_ids:
        row["template_extracted"] = True
        row["template_ids"] = applied_ids
        row["template_original_balance_cents"] = row.get("selected_balance_cents")
        row["template_original_statement_date"] = row.get("statement_date")
        row["template_edited"] = False
        row["template_status"] = "anchored" if "anchored" in statuses else "absolute_fallback"
        confirmations = [template.confirmations for template in templates if template.id in applied_ids]
        row["template_confirmations"] = min(confirmations) if confirmations else 0
        row["auto_commit_eligible"] = bool(
            row.get("selected_balance_cents") is not None
            and row.get("statement_date")
            and confirmations
            and min(confirmations) >= 2
        )
        row["confidence"] = "high"
    elif templates:
        row.setdefault("warnings", []).append("The saved PDF layout no longer validates. Review this statement and re-teach the extractor.")
        row["template_status"] = "validation_failed"
        row["auto_commit_eligible"] = False
    else:
        row["template_extracted"] = False
        row["auto_commit_eligible"] = False
    if original_balance is not None and row.get("selected_balance_cents") is None:
        row["selected_balance_cents"] = original_balance
    if original_date and not row.get("statement_date"):
        row["statement_date"] = original_date
    return row


def record_template_confirmation(db: Session, normalized: dict) -> list[MutationChange]:
    template_ids = [int(value) for value in normalized.get("template_ids") or []]
    if not template_ids:
        return []
    templates = db.scalars(select(PdfExtractionTemplate).where(PdfExtractionTemplate.id.in_(template_ids))).all()
    changes: list[MutationChange] = []
    edited = bool(normalized.get("template_edited"))
    for template in templates:
        before = full_values(template)
        template.confirmations = 0 if edited else template.confirmations + 1
        changes.append(MutationChange(template.id, before, full_values(template), entity_type="pdf_extraction_template"))
    return changes


def template_payload(template: PdfExtractionTemplate) -> dict:
    return {
        "id": template.id,
        "institution": template.institution,
        "account_id": template.account_id,
        "field": template.field,
        "page_number": template.page_number,
        "anchor_text": template.anchor_text,
        "anchor_dx": template.anchor_dx,
        "anchor_dy": template.anchor_dy,
        "region_x0": template.region_x0,
        "region_y0": template.region_y0,
        "region_x1": template.region_x1,
        "region_y1": template.region_y1,
        "value_pattern": template.value_pattern,
        "confirmations": template.confirmations,
    }


def _inspection_for_template(content: bytes, template: PdfExtractionTemplate) -> dict:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        page_number = template.page_number if template.page_number > 0 else len(pdf.pages) + template.page_number + 1
    return inspect_pdf_content(content, page_number)


def _capture_template_value(words: list[dict], template: PdfExtractionTemplate) -> tuple[str, str]:
    region = (template.region_x0, template.region_y0, template.region_x1, template.region_y1)
    if template.anchor_text and template.anchor_dx is not None and template.anchor_dy is not None:
        anchor = max(
            words,
            key=lambda word: SequenceMatcher(None, _fold(word["text"]), _fold(template.anchor_text or "")).ratio(),
            default=None,
        )
        if anchor and SequenceMatcher(None, _fold(anchor["text"]), _fold(template.anchor_text)).ratio() >= 0.9:
            anchor_center = _word_center(anchor)
            width = template.region_x1 - template.region_x0
            height = template.region_y1 - template.region_y0
            target_x = anchor_center[0] + template.anchor_dx
            target_y = anchor_center[1] + template.anchor_dy
            projected = (target_x - width / 2, target_y - height / 2, target_x + width / 2, target_y + height / 2)
            captured = _joined_words(_words_in_region(words, projected))
            if captured:
                return captured, "anchored"
    return _joined_words(_words_in_region(words, region)), "absolute_fallback"


def _default_value_pattern(field: str) -> str:
    return {"balance": CURRENCY_VALUE_PATTERN, "statement_date": DATE_VALUE_PATTERN, "account_last4": LAST4_VALUE_PATTERN}[field]


def _ordered_region(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))
    if right - left < 0.001 or bottom - top < 0.001:
        raise ValueError("Draw a larger box around the value")
    return left, top, right, bottom


def _words_in_region(words: list[dict], region: tuple[float, float, float, float]) -> list[dict]:
    x0, y0, x1, y1 = region
    return [
        word for word in words
        if (word["x0"] + word["x1"]) / 2 >= x0
        and (word["x0"] + word["x1"]) / 2 <= x1
        and (word["y0"] + word["y1"]) / 2 >= y0
        and (word["y0"] + word["y1"]) / 2 <= y1
    ]


def _joined_words(words: list[dict]) -> str:
    return " ".join(word["text"] for word in sorted(words, key=lambda item: (round(item["y0"], 3), item["x0"])))


def _select_anchor(words: list[dict], selected: list[dict], region: tuple[float, float, float, float], override: str | None) -> dict | None:
    selected_ids = {id(word) for word in selected}
    candidates = [word for word in words if id(word) not in selected_ids and re.search(r"[A-Za-z]{3}", word["text"])]
    if override:
        match = max(candidates, key=lambda word: SequenceMatcher(None, _fold(word["text"]), _fold(override)).ratio(), default=None)
        if match and SequenceMatcher(None, _fold(match["text"]), _fold(override)).ratio() >= 0.8:
            return match
        raise ValueError("The chosen anchor text was not found on this page")
    target = _region_center(region)
    same_line_left = [
        word for word in candidates
        if _word_center(word)[0] <= target[0]
        and abs(_word_center(word)[1] - target[1]) <= max(0.02, region[3] - region[1])
    ]
    if same_line_left:
        return max(same_line_left, key=lambda word: _word_center(word)[0])
    left_or_above = [word for word in candidates if _word_center(word)[0] <= target[0] or _word_center(word)[1] <= target[1]]
    return min(left_or_above or candidates, key=lambda word: (_word_center(word)[0] - target[0]) ** 2 + (_word_center(word)[1] - target[1]) ** 2, default=None)


def _region_center(region: tuple[float, float, float, float]) -> tuple[float, float]:
    return (region[0] + region[2]) / 2, (region[1] + region[3]) / 2


def _word_center(word: dict) -> tuple[float, float]:
    return (word["x0"] + word["x1"]) / 2, (word["y0"] + word["y1"]) / 2


def _fold(value: str) -> str:
    return " ".join(value.casefold().split())


def _currency_cents(value: str) -> int:
    cleaned = value.strip()
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cents = parse_decimal_to_cents(cleaned.strip("()").replace("$", "").replace(",", "").strip()) or 0
    return -abs(cents) if negative else cents


def _parse_date(value: str) -> str | None:
    for pattern in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            continue
    return None
