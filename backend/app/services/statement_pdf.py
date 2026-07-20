from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime

import pdfplumber
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import Account, ImportBatch, NetWorthSnapshot, StatementCheckpoint, StatementPdfPattern, StagingRow
from ..money import parse_decimal_to_cents
from .mutation_log import MutationChange, full_values, journal_mutation
from .account_identifiers import matching_accounts_for_last_four, replacement_card_candidate
from .pdf_teaching import forget_pdf_content, record_template_confirmation


@dataclass(frozen=True)
class BalanceCandidate:
    label: str
    balance_cents: int
    context: str


@dataclass(frozen=True)
class StatementPdfPreview:
    institution: str | None
    statement_date: str | None
    date_label: str | None
    candidates: list[BalanceCandidate]
    selected_index: int | None
    confidence: str
    warnings: list[str]


BALANCE_PATTERN = re.compile(
    r"(?im)^\s*(new\s+balance|ending\s+balance|closing\s+balance|statement\s+balance|total\s+balance|account\s+balance)"
    r"(?:\s+on\s+[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})?\s*:?[ \t]*\$?[ \t]*(\(?-?[\d,]+\.\d{2}\)?)\s*$"
)
DATE_PATTERNS = (
    ("Ending balance date", re.compile(r"(?i)ending\s+balance\s+on\s+([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})")),
    ("Statement date", re.compile(r"(?i)statement\s+date\s*:?[ \t]*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})")),
    ("Closing date", re.compile(r"(?i)closing\s+date\s*:?[ \t]*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})")),
    ("Statement period end", re.compile(r"(?i)(?:through|to)\s+([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})")),
)


def extract_statement_pdf(content: bytes, filename: str = "statement.pdf", preferred_label: str | None = None) -> StatementPdfPreview:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as error:  # pdfplumber raises several parser-specific exception types
        raise ValueError(f"Could not read {filename} as a PDF statement") from error
    if not text.strip():
        raise ValueError("The PDF has no extractable text. Use manual statement balance entry for scanned-image statements.")
    return extract_statement_text(text, preferred_label=preferred_label)


def extract_statement_text(text: str, preferred_label: str | None = None) -> StatementPdfPreview:
    institution = _detect_institution(text)
    statement_date, date_label = _extract_date(text)
    candidates: list[BalanceCandidate] = []
    seen: set[tuple[str, int]] = set()
    for match in BALANCE_PATTERN.finditer(text):
        label = " ".join(match.group(1).title().split())
        cents = _currency_cents(match.group(2))
        key = (label.casefold(), cents)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(BalanceCandidate(label=label, balance_cents=cents, context=match.group(0).strip()))

    selected_index: int | None = None
    if preferred_label:
        selected_index = next((index for index, candidate in enumerate(candidates) if candidate.label.casefold() == preferred_label.casefold()), None)
    if selected_index is None and len(candidates) == 1 and statement_date:
        selected_index = 0
    confidence = "high" if selected_index is not None else "low"
    warnings: list[str] = []
    if statement_date is None:
        warnings.append("Could not identify the statement date. Enter it before confirming the anchor.")
    if not candidates:
        warnings.append("Could not identify a labeled ending balance. Enter the balance before confirming the anchor.")
    elif len(candidates) > 1 and selected_index is None:
        warnings.append("Several labeled balances were found. Choose the statement's ending balance before confirming.")
    return StatementPdfPreview(
        institution=institution,
        statement_date=statement_date.isoformat() if statement_date else None,
        date_label=date_label,
        candidates=candidates,
        selected_index=selected_index,
        confidence=confidence,
        warnings=warnings,
    )


def statement_preview_row(preview: StatementPdfPreview, account: Account) -> dict:
    candidates = [asdict(candidate) for candidate in preview.candidates]
    if account.account_type == "credit_card":
        for candidate in candidates:
            candidate["balance_cents"] = -abs(int(candidate["balance_cents"]))
    selected = candidates[preview.selected_index] if preview.selected_index is not None else None
    return {
        "row_index": 1,
        "row_kind": "statement_balance",
        "institution": preview.institution,
        "statement_date": preview.statement_date,
        "date_label": preview.date_label,
        "candidates": candidates,
        "selected_index": preview.selected_index,
        "selected_balance_cents": selected["balance_cents"] if selected else None,
        "selected_balance_label": selected["label"] if selected else None,
        "confidence": preview.confidence,
        "warnings": preview.warnings,
    }


def suggest_pdf_account(db: Session, filename: str, preview: StatementPdfPreview) -> tuple[Account | None, int, str, dict, int | None]:
    accounts = db.scalars(select(Account).where(Account.status == "active", Account.account_type != "external")).all()
    digits = "".join(character for character in filename if character.isdigit())
    last_four = digits[-4:] if len(digits) >= 4 else None
    proposed = {
        "institution_name": preview.institution,
        "display_name": f"{preview.institution or 'Statement'} Account",
        "account_type": "checking",
        "currency": "USD",
        "last_four": last_four,
    }
    suffix_matches = matching_accounts_for_last_four(db, accounts, last_four)
    if len(suffix_matches) == 1:
        return suffix_matches[0], 95, "Matched the account's current or previous last four digits in the PDF filename.", proposed, None
    institution = (preview.institution or "").casefold()
    institution_matches = [
        account for account in accounts
        if account.institution and institution and (
            institution in account.institution.name.casefold() or account.institution.name.casefold() in institution
        )
    ]
    replacement_candidate = replacement_card_candidate(db, accounts, proposed)
    if replacement_candidate:
        return None, 70, "This PDF may use a replacement card number. Confirm before combining its history.", proposed, replacement_candidate.id
    if len(institution_matches) == 1:
        return institution_matches[0], 80, "Matched the only active account for the detected PDF institution.", proposed, None
    return None, 0, "Choose the account for this statement PDF; include its last four digits in future filenames for automatic matching.", proposed, None


def semantic_pdf_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def saved_pdf_pattern(db: Session, account: Account) -> StatementPdfPattern | None:
    if not account.institution_id:
        return None
    return db.scalar(select(StatementPdfPattern).where(StatementPdfPattern.institution_id == account.institution_id))


def update_statement_preview(db: Session, batch: ImportBatch, *, statement_date: date, balance_cents: int, candidate_index: int | None = None) -> dict:
    if batch.status != "pending" or batch.detected_preset != "pdf_statement":
        raise ValueError("Only pending PDF statement previews can be edited")
    row = db.scalar(select(StagingRow).where(StagingRow.import_batch_id == batch.id, StagingRow.row_kind == "statement_balance"))
    if not row:
        raise ValueError("This PDF statement preview is missing")
    normalized = json.loads(row.normalized_json)
    candidates = normalized.get("candidates") or []
    selected_label = None
    if candidate_index is not None:
        if candidate_index < 0 or candidate_index >= len(candidates):
            raise ValueError("Choose one of the extracted balance candidates")
        balance_cents = int(candidates[candidate_index]["balance_cents"])
        selected_label = candidates[candidate_index].get("label")
    if normalized.get("template_extracted"):
        normalized["template_edited"] = bool(
            statement_date.isoformat() != normalized.get("template_original_statement_date")
            or balance_cents != normalized.get("template_original_balance_cents")
            or candidate_index is not None
        )
    normalized.update(
        {
            "statement_date": statement_date.isoformat(),
            "selected_index": candidate_index,
            "selected_balance_cents": balance_cents,
            "selected_balance_label": selected_label,
            "confidence": "user_confirmed",
        }
    )
    row.normalized_json = json.dumps(normalized)
    return normalized


def commit_pdf_statement(db: Session, batch: ImportBatch, account: Account, *, actor: str) -> dict:
    row = db.scalar(select(StagingRow).where(StagingRow.import_batch_id == batch.id, StagingRow.row_kind == "statement_balance"))
    if not row:
        raise ValueError("This PDF statement preview is missing")
    normalized = json.loads(row.normalized_json)
    if not normalized.get("statement_date") or normalized.get("selected_balance_cents") is None:
        raise ValueError("Choose the statement date and ending balance before confirming this PDF")
    statement_date = date.fromisoformat(normalized["statement_date"])
    balance_cents = int(normalized["selected_balance_cents"])
    changes: list[MutationChange] = []

    checkpoint = db.scalar(
        select(StatementCheckpoint).where(
            StatementCheckpoint.account_id == account.id,
            StatementCheckpoint.statement_date == statement_date,
        )
    )
    before_checkpoint = full_values(checkpoint) if checkpoint else None
    if checkpoint is None:
        checkpoint = StatementCheckpoint(
            account_id=account.id,
            statement_date=statement_date,
            statement_balance_cents=balance_cents,
            source="manual",
        )
        db.add(checkpoint)
        db.flush()
    else:
        checkpoint.statement_balance_cents = balance_cents
        checkpoint.source = "manual"
        db.flush()
    changes.append(MutationChange(checkpoint.id, before_checkpoint, full_values(checkpoint), entity_type="statement_checkpoint"))

    snapshot = db.scalar(
        select(NetWorthSnapshot).where(NetWorthSnapshot.account_id == account.id, NetWorthSnapshot.snapshot_date == statement_date)
    )
    before_snapshot = full_values(snapshot) if snapshot else None
    if snapshot is None:
        snapshot = NetWorthSnapshot(account_id=account.id, snapshot_date=statement_date, balance_cents=balance_cents, source="manual")
        db.add(snapshot)
        db.flush()
    else:
        snapshot.balance_cents = balance_cents
        snapshot.source = "manual"
        db.flush()
    changes.append(MutationChange(snapshot.id, before_snapshot, full_values(snapshot), entity_type="net_worth_snapshot"))
    changes.extend(record_template_confirmation(db, normalized))

    label = normalized.get("selected_balance_label")
    if account.institution_id and label:
        pattern = db.scalar(select(StatementPdfPattern).where(StatementPdfPattern.institution_id == account.institution_id))
        before_pattern = full_values(pattern) if pattern else None
        if pattern is None:
            pattern = StatementPdfPattern(
                institution_id=account.institution_id,
                balance_label=label,
                date_label=normalized.get("date_label"),
            )
            db.add(pattern)
            db.flush()
        else:
            pattern.balance_label = label
            pattern.date_label = normalized.get("date_label")
            db.flush()
        changes.append(MutationChange(pattern.id, before_pattern, full_values(pattern), entity_type="statement_pdf_pattern"))

    batch.status = "committed"
    batch.imported_rows = 1
    batch.skipped_duplicates = 0
    batch.warnings_json = json.dumps(normalized.get("warnings") or [])
    db.execute(delete(StagingRow).where(StagingRow.import_batch_id == batch.id))
    forget_pdf_content(batch.id)
    operation_id = journal_mutation(
        db,
        kind="import",
        entity_type="statement_checkpoint",
        actor=actor,
        description=f'Anchored {account.display_name} from PDF statement "{batch.filename}"',
        changes=changes,
    )
    record_audit_event(
        db,
        "statement_pdf_confirm",
        actor,
        "import_batch",
        str(batch.id),
        {"filename": batch.filename, "account_id": account.id, "statement_date": statement_date.isoformat(), "operation_id": operation_id},
    )
    return {"batch_id": batch.id, "inserted": 1, "skipped": 0, "warnings": normalized.get("warnings") or [], "operation_id": operation_id}


def _detect_institution(text: str) -> str | None:
    folded = text.casefold()
    for marker, institution in (
        ("bank of america", "Bank of America"),
        ("citibank", "Citi"),
        ("citi", "Citi"),
        ("american express", "American Express"),
        ("jpmorgan chase", "Chase"),
        ("chase", "Chase"),
        ("fidelity", "Fidelity"),
    ):
        if marker in folded:
            return institution
    return None


def _extract_date(text: str) -> tuple[date | None, str | None]:
    for label, pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        parsed = _parse_date(match.group(1))
        if parsed:
            return parsed, label
    return None, None


def _parse_date(value: str) -> date | None:
    for pattern in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            continue
    return None


def _currency_cents(value: str) -> int:
    cleaned = value.strip()
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cents = parse_decimal_to_cents(cleaned.strip("()").replace(",", "")) or 0
    return -abs(cents) if negative else cents
