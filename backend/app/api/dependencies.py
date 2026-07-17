from datetime import date
from typing import Literal

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import SessionToken
from ..schemas import ReviewStatus, TransactionFilter, TransactionType
from ..security import get_session_from_request
from ..services.transaction_filters import parse_csv_ints, parse_csv_values


def current_session(request: Request, db: Session = Depends(get_db)) -> SessionToken:
    return get_session_from_request(db, request)


def transaction_filter_dependency(
    accounts: str | None = None,
    categories: str | None = None,
    tags: str | None = None,
    months: str | None = None,
    years: str | None = None,
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    date_basis: Literal["transaction", "reporting"] = Query(default="transaction", alias="dateBasis"),
    amount_min: int | None = Query(default=None, alias="amountMin", ge=0),
    amount_max: int | None = Query(default=None, alias="amountMax", ge=0),
    direction: Literal["inflow", "outflow"] | None = None,
    types: str | None = None,
    search: str | None = None,
    view: Literal["live", "trash"] = "live",
    review_status: ReviewStatus | None = None,
    has_refund: bool | None = Query(default=None, alias="hasRefund"),
) -> TransactionFilter:
    try:
        transaction_types = [TransactionType(value) for value in parse_csv_values(types)]
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f'Unknown transaction type "{error.args[0]}"') from error
    return TransactionFilter(
        accounts=parse_csv_ints(accounts), categories=parse_csv_values(categories), tags=parse_csv_values(tags),
        months=parse_csv_values(months), years=parse_csv_values(years), date_from=date_from, date_to=date_to,
        date_basis=date_basis, amount_min=amount_min, amount_max=amount_max, direction=direction,
        transaction_types=transaction_types, search=search, view=view, review_status=review_status, has_refund=has_refund,
    )
