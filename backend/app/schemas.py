from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

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
    parent_id: int | None = None


class CategoryUpdate(BaseModel):
    label: str
    parent_id: int | None = None


class ImportPresetCreate(BaseModel):
    account_id: int
    name: str
    preset_type: str
    header_signature: str
    config_json: str


class TransactionReviewUpdate(BaseModel):
    account_id: int | None = None
    category_id: int | None = None
    transaction_type: TransactionType | None = None
    review_status: ReviewStatus | None = None
    user_note: str | None = None


class ManualTransactionCreate(BaseModel):
    account_id: int
    transaction_date: date
    amount_cents: int
    category_id: int | None = None
    description: str = Field(min_length=1, max_length=500)
    labels: list[str] = Field(default_factory=list)


class OperationBulkUpdateRequest(BaseModel):
    entity_type: Literal["transaction"]
    ids: list[int] = Field(min_length=1)
    patch: TransactionReviewUpdate


class DuplicateResolutionRequest(BaseModel):
    action: Literal["remove_new", "keep_both", "replace_old"]


class RuleCreate(BaseModel):
    category_id: int | None = None
    field_name: str
    match_text: str
    suggested_transaction_type: TransactionType = TransactionType.EXPENSE
    priority: int = 100


class BulkRuleCreateRequest(BaseModel):
    rules: list[RuleCreate] = Field(min_length=1)


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


class RefundLinkCreate(BaseModel):
    expense_transaction_id: int
    refund_transaction_id: int
    match_confidence: int = Field(default=100, ge=0, le=100)
    confirmed: bool = True
    allow_over_refund: bool = False


class RefundConfirmRequest(BaseModel):
    allow_over_refund: bool = False


class HoldingMetadataUpdate(BaseModel):
    symbol: str
    user_description: str | None = None


class HoldingLotCreate(BaseModel):
    account_id: int
    symbol: str = Field(min_length=1, max_length=40)
    acquisition_date: date
    quantity_basis_points: int = Field(gt=0)
    cost_basis_cents: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=500)


class NetWorthSnapshotUpsert(BaseModel):
    account_id: int
    snapshot_date: date
    balance_cents: int


class StatementCheckpointCreate(BaseModel):
    statement_date: date
    statement_balance_cents: int


class DeleteConfirmRequest(BaseModel):
    confirm_text: str


class BulkDeleteRequest(BaseModel):
    ids: list[int]
    confirm_text: str


class BulkIdsRequest(BaseModel):
    ids: list[int] = Field(min_length=1)


class UndoOperationRequest(BaseModel):
    unconflicted_only: bool = False


class BulkTransactionField(StrEnum):
    INSTITUTION = "institution"
    ACCOUNT = "account"
    DESCRIPTION = "description"
    DETAILS = "details"
    TYPE = "type"
    CATEGORY = "category"
    DATE = "date"
    LABELS = "labels"


class BulkTransactionUpdateRequest(BaseModel):
    ids: list[int] = Field(min_length=1)
    field: BulkTransactionField
    value: str | int | None


class TransactionFilter(BaseModel):
    accounts: list[int] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    months: list[str] = Field(default_factory=list)
    years: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    date_basis: Literal["transaction", "reporting"] = "transaction"
    amount_min: int | None = None
    amount_max: int | None = None
    direction: Literal["inflow", "outflow"] | None = None
    transaction_types: list[TransactionType] = Field(default_factory=list)
    search: str | None = None
    view: Literal["live", "trash"] = "live"
    review_status: ReviewStatus | None = None
    has_refund: bool | None = None
