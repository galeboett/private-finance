from sqlalchemy import Connection

from ..models import PdfExtractionTemplate


def upgrade(connection: Connection) -> None:
    PdfExtractionTemplate.__table__.create(bind=connection, checkfirst=True)
