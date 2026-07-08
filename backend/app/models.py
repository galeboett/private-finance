from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AppUser(TimestampMixin, Base):
    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SessionToken(TimestampMixin, Base):
    __tablename__ = "session_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_users.id"), nullable=False)
    session_token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(128), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    user: Mapped["AppUser"] = relationship()


class Institution(TimestampMixin, Base):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    accounts: Mapped[list["Account"]] = relationship(back_populates="institution")


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"))
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    last_four: Mapped[str | None] = mapped_column(String(8))
    institution: Mapped["Institution | None"] = relationship(back_populates="accounts")
    presets: Mapped[list["ImportPreset"]] = relationship(back_populates="account")


class ImportPreset(TimestampMixin, Base):
    __tablename__ = "import_presets"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    preset_type: Mapped[str] = mapped_column(String(40), nullable=False)
    header_signature: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    account: Mapped["Account"] = relationship(back_populates="presets")


class ImportBatch(TimestampMixin, Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    preset_id: Mapped[int | None] = mapped_column(ForeignKey("import_presets.id"))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_duplicates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)


class StagingRow(TimestampMixin, Base):
    __tablename__ = "staging_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    row_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_json: Mapped[str] = mapped_column(Text, nullable=False)


class Category(TimestampMixin, Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))


class CategoryRule(TimestampMixin, Base):
    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    field_name: Mapped[str] = mapped_column(String(40), nullable=False)
    match_text: Mapped[str] = mapped_column(String(255), nullable=False)
    suggested_transaction_type: Mapped[str] = mapped_column(String(40), nullable=False)


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("account_id", "source_hash", name="uq_transactions_source_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    posted_date: Mapped[date | None] = mapped_column(Date)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_payee: Mapped[str | None] = mapped_column(String(255))
    transaction_type: Mapped[str] = mapped_column(String(40), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    review_status: Mapped[str] = mapped_column(String(40), default="needs_review", nullable=False)
    source_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(120))
    source_ordinal: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    running_balance_cents: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    linked_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    duplicate_of_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))


class TransactionSplit(TimestampMixin, Base):
    __tablename__ = "transaction_splits"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))


class TransferLink(TimestampMixin, Base):
    __tablename__ = "transfer_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    to_transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    match_confidence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class HoldingSnapshot(TimestampMixin, Base):
    __tablename__ = "holding_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(String(255))
    quantity_basis_points: Mapped[int | None] = mapped_column(Integer)
    price_cents: Mapped[int | None] = mapped_column(Integer)
    market_value_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_class: Mapped[str | None] = mapped_column(String(80))


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
