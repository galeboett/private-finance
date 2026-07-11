from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class TransactionType(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"
    CREDIT_CARD_PAYMENT = "credit_card_payment"
    REFUND = "refund"
    INVESTMENT_FLOW = "investment_flow"
    ADJUSTMENT = "adjustment"


class ReviewStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    SUGGESTED = "suggested"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    CONFIRMED = "confirmed"


class AccountType(StrEnum):
    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    CASH = "cash"
    OTHER = "other"
    LOAN = "loan"
    BROKERAGE = "brokerage"
    RETIREMENT = "retirement"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class SetupRequest(BaseModel):
    password: str = Field(min_length=12)


class LoginRequest(BaseModel):
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)


class RuleUpdate(BaseModel):
    category_id: int | None = None
    match_text: str | None = None
    suggested_transaction_type: TransactionType | None = None
    priority: int | None = None


class AccountCreate(BaseModel):
    institution_name: str | None = None
    display_name: str
    account_type: AccountType
    currency: str = "USD"
    last_four: str | None = None


class AccountUpdate(BaseModel):
    institution_name: str | None = None
    display_name: str | None = None
    account_type: AccountType | None = None
    currency: str | None = None
    last_four: str | None = None
    status: AccountStatus | None = None


class CategoryCreate(BaseModel):
    label: str


class CategoryUpdate(BaseModel):
    label: str


class ImportPresetCreate(BaseModel):
    account_id: int
    name: str
    preset_type: str
    header_signature: str
    config_json: str


class TransactionReviewUpdate(BaseModel):
    category_id: int | None = None
    transaction_type: TransactionType | None = None
    review_status: ReviewStatus | None = None
    user_note: str | None = None


class RuleCreate(BaseModel):
    category_id: int
    field_name: str
    match_text: str
    suggested_transaction_type: TransactionType = TransactionType.EXPENSE
    priority: int = 100


class RuleApplyRequest(BaseModel):
    scope: str = "unreviewed"


class SplitCreate(BaseModel):
    category_id: int
    amount_cents: int
    note: str | None = None


class SplitSetRequest(BaseModel):
    splits: list[SplitCreate]


class MonthlyAllocationRequest(BaseModel):
    category_id: int
    months: int = Field(ge=2, le=120)
    allocation_start: date


class TransferLinkCreate(BaseModel):
    from_transaction_id: int
    to_transaction_id: int
    match_confidence: int = 0
    confirmed: bool = False


class HoldingMetadataUpdate(BaseModel):
    symbol: str
    user_description: str | None = None


class DeleteConfirmRequest(BaseModel):
    confirm_text: str


class BulkDeleteRequest(BaseModel):
    ids: list[int]
    confirm_text: str


class BulkTransactionField(StrEnum):
    INSTITUTION = "institution"
    ACCOUNT = "account"
    DESCRIPTION = "description"
    DETAILS = "details"
    TYPE = "type"
    CATEGORY = "category"


class BulkTransactionUpdateRequest(BaseModel):
    ids: list[int] = Field(min_length=1)
    field: BulkTransactionField
    value: str | int | None


class TransactionFilter(BaseModel):
    account_id: int | None = None
    review_status: ReviewStatus | None = None
    category_id: int | None = None
    transaction_type: TransactionType | None = None
    start_date: date | None = None
    end_date: date | None = None
