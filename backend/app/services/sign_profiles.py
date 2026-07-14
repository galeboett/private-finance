from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Account, ImportSignProfile
from ..money import parse_decimal_to_cents
from .importers import PreviewResult, apply_import_sign_convention
from .mutation_log import MutationChange, full_values, journal_mutation


PROFILE_CONVENTIONS = {"canonical_as_detected": "preset", "reverse_detected": "reverse"}
DECIDED_BY_VALUES = {"user", "auto_detected"}
PAYMENT_WORDS = ("PAYMENT", "AUTOPAY", "TRANSFER", "THANK YOU")
PAYROLL_WORDS = ("PAYROLL", "DIRECT DEP", "DIRECT DEPOSIT", "SALARY", "PAYCHECK")


@dataclass(frozen=True)
class SignResolution:
    preview: PreviewResult
    sign_convention: str
    profile: ImportSignProfile | None
    heuristic: dict[str, Any]
    requires_confirmation: bool


def get_sign_profile(db: Session, account_id: int, preset_type: str) -> ImportSignProfile | None:
    profiles = db.scalars(
        select(ImportSignProfile).where(
            ImportSignProfile.account_id == account_id,
            or_(ImportSignProfile.preset_type == preset_type, ImportSignProfile.preset_type.is_(None)),
        )
    ).all()
    if not profiles:
        return None
    return sorted(profiles, key=lambda profile: (profile.decided_by != "user", profile.preset_type != preset_type, profile.id))[0]


def resolve_sign_preview(
    db: Session,
    *,
    account: Account,
    preset_type: str,
    preview: PreviewResult,
    requested: str = "auto",
) -> SignResolution:
    if requested not in {"auto", "preset", "reverse"}:
        raise ValueError("Choose automatic, detected amount signs, or reversed signs")
    profile = get_sign_profile(db, account.id, preset_type)
    selected = requested
    if requested == "auto":
        selected = PROFILE_CONVENTIONS.get(profile.sign_convention, "preset") if profile else "preset"
    heuristic = analyze_sign_distribution(preview, account)
    recommendation = heuristic.get("recommended_sign_convention")
    requires_confirmation = bool(recommendation and recommendation != selected and (profile is not None or requested == "auto"))
    return SignResolution(
        preview=apply_import_sign_convention(preview, selected),
        sign_convention=selected,
        profile=profile,
        heuristic=heuristic,
        requires_confirmation=requires_confirmation,
    )


def analyze_sign_distribution(preview: PreviewResult, account: Account) -> dict[str, Any]:
    rows = [row for row in preview.rows if row.get("row_kind") == "transaction" and row.get("amount") not in {None, ""}]
    candidates: list[tuple[dict, int]] = []
    rule = None
    if account.account_type == "credit_card":
        rule = "credit_card_non_payment"
        for row in rows:
            description = str(row.get("raw_description") or "").upper()
            if any(word in description for word in PAYMENT_WORDS):
                continue
            candidates.append((row, parse_decimal_to_cents(row.get("amount")) or 0))
    elif account.account_type in {"checking", "savings"}:
        rule = "payroll_deposit"
        for row in rows:
            description = str(row.get("raw_description") or "").upper()
            if any(word in description for word in PAYROLL_WORDS):
                candidates.append((row, parse_decimal_to_cents(row.get("amount")) or 0))
    if not candidates:
        return {"status": "insufficient_data", "rule": rule, "sample_size": 0, "recommended_sign_convention": None, "examples": []}
    negative = sum(1 for _, amount in candidates if amount < 0)
    positive = sum(1 for _, amount in candidates if amount > 0)
    nonzero = negative + positive
    if nonzero == 0:
        return {"status": "insufficient_data", "rule": rule, "sample_size": len(candidates), "recommended_sign_convention": None, "examples": []}
    expected_count = negative if account.account_type == "credit_card" else positive
    opposite_count = positive if account.account_type == "credit_card" else negative
    expected_ratio = expected_count / nonzero
    opposite_ratio = opposite_count / nonzero
    recommendation = "preset" if expected_ratio >= 0.85 else "reverse" if opposite_ratio >= 0.85 else None
    return {
        "status": "consistent" if recommendation == "preset" else "contradicts_detected" if recommendation == "reverse" else "mixed",
        "rule": rule,
        "sample_size": nonzero,
        "expected_ratio": round(expected_ratio, 4),
        "recommended_sign_convention": recommendation,
        "examples": [
            {
                "transaction_date": row.get("transaction_date"),
                "description": row.get("raw_description"),
                "amount": row.get("amount"),
            }
            for row, _ in candidates[:2]
        ],
    }


def save_sign_profile(
    db: Session,
    *,
    account: Account,
    preset_type: str | None,
    sign_convention: str,
    actor: str,
    sample_note: str | None = None,
    decided_by: str = "user",
) -> tuple[ImportSignProfile, str]:
    if sign_convention not in PROFILE_CONVENTIONS:
        raise ValueError("Unknown sign convention")
    if decided_by not in DECIDED_BY_VALUES:
        raise ValueError("Unknown sign-profile decision source")
    profile = db.scalar(
        select(ImportSignProfile).where(
            ImportSignProfile.account_id == account.id,
            ImportSignProfile.preset_type == preset_type if preset_type is not None else ImportSignProfile.preset_type.is_(None),
        )
    )
    before = full_values(profile) if profile else None
    if profile is None:
        profile = ImportSignProfile(account_id=account.id, preset_type=preset_type, sign_convention=sign_convention, decided_by=decided_by, sample_note=sample_note)
        db.add(profile)
        db.flush()
    else:
        profile.sign_convention = sign_convention
        profile.decided_by = decided_by
        profile.sample_note = sample_note
        db.flush()
    after = full_values(profile)
    operation_id = journal_mutation(
        db,
        kind="update" if before else "create",
        entity_type="import_sign_profile",
        actor=actor,
        description=f"Saved sign convention for {account.display_name}",
        changes=[MutationChange(profile.id, before, after)],
    )
    return profile, operation_id


def profile_payload(profile: ImportSignProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "account_id": profile.account_id,
        "preset_type": profile.preset_type,
        "sign_convention": profile.sign_convention,
        "decided_by": profile.decided_by,
        "sample_note": profile.sample_note,
        "updated_at": profile.updated_at.isoformat(),
    }


def resolution_payload(resolution: SignResolution) -> dict[str, Any]:
    return {
        "applied_sign_convention": resolution.sign_convention,
        "using_saved_profile": resolution.profile is not None,
        "profile": profile_payload(resolution.profile) if resolution.profile else None,
        "heuristic": resolution.heuristic,
        "requires_confirmation": resolution.requires_confirmation,
    }
