"""
Service functions for Topic taxonomy management and idempotent seeding.

Docs:
- docs/03_DATABASE_DESIGN.md §3.2
- docs/07_AI_ML_DESIGN.md §2
- docs/01_REQUIREMENTS.md OD-06
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.topic import Topic

# The authoritative 8-topic taxonomy defined in docs/07_AI_ML_DESIGN.md §2
TAXONOMY_TOPICS: list[dict[str, str]] = [
    {
        "code": "OS_PROCESS",
        "name": "Process Management",
        "subject": "OS",
    },
    {
        "code": "OS_SCHEDULING",
        "name": "CPU Scheduling",
        "subject": "OS",
    },
    {
        "code": "OS_SYNC",
        "name": "Synchronization and Deadlocks",
        "subject": "OS",
    },
    {
        "code": "OS_MEMORY_FILES",
        "name": "Memory and File Systems",
        "subject": "OS",
    },
    {
        "code": "DB_NORMALIZATION",
        "name": "Relational Modeling and Normalization",
        "subject": "DBMS",
    },
    {
        "code": "DB_SQL_JOINS",
        "name": "SQL Queries and Joins",
        "subject": "DBMS",
    },
    {
        "code": "DB_TRANSACTIONS",
        "name": "Transactions and Concurrency",
        "subject": "DBMS",
    },
    {
        "code": "DB_INDEXING",
        "name": "Indexing and Query Optimization",
        "subject": "DBMS",
    },
]


def seed_taxonomy_topics(db: Session) -> list[Topic]:
    """
    Idempotently seeds the 8 authoritative topics into the topics table.

    Guarantees:
    - Never inserts duplicates on re-runs.
    - Preserves existing topic IDs, foreign keys, and relations intact.
    - Validates against table constraints (subject check: OS or DBMS).
    """
    stmt = select(Topic)
    existing_topics = db.scalars(stmt).all()
    existing_by_code = {t.code: t for t in existing_topics}

    result: list[Topic] = []
    has_changes = False

    for spec in TAXONOMY_TOPICS:
        code = spec["code"]
        if code in existing_by_code:
            result.append(existing_by_code[code])
        else:
            new_topic = Topic(
                code=code,
                name=spec["name"],
                subject=spec["subject"],
                is_active=True,
            )
            db.add(new_topic)
            result.append(new_topic)
            has_changes = True

    if has_changes:
        db.commit()
        for t in result:
            db.refresh(t)

    return result


def list_topics(db: Session, active_only: bool = True) -> list[Topic]:
    """List topics ordered by subject then code."""
    query = select(Topic)
    if active_only:
        query = query.filter(Topic.is_active.is_(True))
    query = query.order_by(Topic.subject, Topic.code)
    return list(db.scalars(query).all())


def get_topic_by_id(db: Session, topic_id: UUID) -> Topic | None:
    """Retrieve a topic by its primary key UUID."""
    return db.get(Topic, topic_id)


def get_topic_by_code(db: Session, code: str) -> Topic | None:
    """Retrieve a topic by its unique natural code."""
    stmt = select(Topic).filter(Topic.code == code)
    return db.scalars(stmt).first()
