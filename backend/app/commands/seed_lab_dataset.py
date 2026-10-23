"""
Operator CLI command to seed the isolated examos_lab benchmark dataset.

Usage:
  python -m app.commands.seed_lab_dataset --size medium --seed 42
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.lab_data_service import seed_lab_dataset


def run_seed_lab_dataset(
    size: str = "medium",
    seed: int = 42,
    db_url: str | None = None,
) -> int:
    target_url = db_url or settings.DATABASE_URL
    if not target_url:
        print("Error: DATABASE_URL is not configured.", file=sys.stderr)
        return 1

    engine = create_engine(str(target_url), pool_pre_ping=True)
    try:
        SessionMaker = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        with SessionMaker() as session:
            stats = seed_lab_dataset(session, size=size, seed=seed)
            print("Successfully seeded examos_lab benchmark datasets:")
            print(f"  - Size: {stats['dataset_size']} (Seed: {stats['seed']})")
            print(f"  - Students: {stats['student_count']} rows in both lab_students_no_index & lab_students_indexed")
            print(f"  - Enrollments: {stats['enrollment_count']} rows in both lab_enrollments_no_index & lab_enrollments_indexed")
            print("  - PostgreSQL statistics successfully refreshed via ANALYZE.")
        return 0
    finally:
        engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed ExamOS Database Performance Lab dataset.",
    )
    parser.add_argument(
        "--size",
        dest="size",
        default="medium",
        choices=["small", "medium", "large"],
        help="Dataset size scale (default: medium).",
    )
    parser.add_argument(
        "--seed",
        dest="seed",
        type=int,
        default=42,
        help="Random seed for deterministic generation (default: 42).",
    )
    parser.add_argument(
        "--db-url",
        dest="db_url",
        default=None,
        help="Optional database connection URL override.",
    )
    args = parser.parse_args(argv)
    return run_seed_lab_dataset(size=args.size, seed=args.seed, db_url=args.db_url)


if __name__ == "__main__":
    sys.exit(main())
