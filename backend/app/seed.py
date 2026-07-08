from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category


FIXED_CATEGORIES = [
    ("groceries", "Groceries"),
    ("rent", "Rent"),
    ("household", "Household"),
    ("restaurants", "Restaurants"),
    ("auto_transport", "Auto & Transport"),
    ("travel", "Travel"),
    ("entertainment", "Entertainment"),
    ("gift", "Gift"),
    ("moving", "Moving"),
    ("shopping", "Shopping"),
    ("utilities", "Utilities"),
    ("health_fitness", "Health & Fitness"),
    ("work", "Work"),
]


def seed_categories(db: Session) -> None:
    existing = {row[0] for row in db.execute(select(Category.key)).all()}
    for key, label in FIXED_CATEGORIES:
        if key not in existing:
            db.add(Category(key=key, label=label))

