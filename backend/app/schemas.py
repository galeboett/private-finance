from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class SetupRequest(BaseModel):
    password: str = Field(min_length=12)


class LoginRequest(BaseModel):
    password: str


class AccountCreate(BaseModel):
    institution_name: str | None = None
    display_name: str
    account_type: str
    currency: str = "USD"
    last_four: str | None = None


class ImportPresetCreate(BaseModel):
    account_id: int
    name: str
    preset_type: str
    header_signature: str
    config_json: str


class TransactionReviewUpdate(BaseModel):
    category_id: int | None = None
    transaction_type: str | None = None
    review_status: str | None = None


class RuleCreate(BaseModel):
    category_id: int
    field_name: str
    match_text: str
    suggested_transaction_type: str = "expense"
    priority: int = 100


class SplitCreate(BaseModel):
    category_id: int
    amount_cents: int
    note: str | None = None


class SplitSetRequest(BaseModel):
    splits: list[SplitCreate]


class TransferLinkCreate(BaseModel):
    from_transaction_id: int
    to_transaction_id: int
    match_confidence: int = 0
    confirmed: bool = False


class TransactionFilter(BaseModel):
    account_id: int | None = None
    review_status: str | None = None
    category_id: int | None = None
    transaction_type: str | None = None
    start_date: date | None = None
    end_date: date | None = None

