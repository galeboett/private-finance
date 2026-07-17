from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import SessionToken
from ..schemas import TransactionFilter
from ..services.aggregation import aggregate_by_account, aggregate_by_category, aggregate_summary, aggregate_timeseries
from .dependencies import current_session, transaction_filter_dependency

router = APIRouter(prefix="/api/aggregate", tags=["aggregation"])


@router.get("/by-category")
def get_aggregate_by_category(filters: TransactionFilter = Depends(transaction_filter_dependency), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return aggregate_by_category(db, filters)


@router.get("/by-account")
def get_aggregate_by_account(filters: TransactionFilter = Depends(transaction_filter_dependency), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return aggregate_by_account(db, filters)


@router.get("/timeseries")
def get_aggregate_timeseries(bucket: Literal["day", "week", "month"] = "month", filters: TransactionFilter = Depends(transaction_filter_dependency), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return aggregate_timeseries(db, filters, bucket)


@router.get("/summary")
def get_aggregate_summary(filters: TransactionFilter = Depends(transaction_filter_dependency), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return aggregate_summary(db, filters)
