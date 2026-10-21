"""
Operator CLI command to seed the 8 authoritative topics taxonomy.

Usage:
  python -m app.commands.seed_topics
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.topic_service import seed_taxonomy_topics


def run_seed_topics(db_url: str | None = None) -> int:
    target_url = db_url or settings.DATABASE_URL
    if not target_url:
        print("Error: DATABASE_URL is not configured.", file=sys.stderr)
        return 1

    engine = create_engine(str(target_url), pool_pre_ping=True)
    try:
        SessionMaker = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        with SessionMaker() as session:
            topics = seed_taxonomy_topics(session)
            print(f"Successfully verified/seeded {len(topics)} taxonomy topics:")
            for t in topics:
                print(f"  - [{t.subject}] {t.code}: {t.name} (id={t.id})")
        return 0
    finally:
        engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed ExamOS topic taxonomy.",
    )
    parser.add_argument(
        "--db-url",
        dest="db_url",
        default=None,
        help="Optional database connection URL override.",
    )
    args = parser.parse_args(argv)
    return run_seed_topics(db_url=args.db_url)


if __name__ == "__main__":
    sys.exit(main())
