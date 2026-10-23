"""
Deterministic seeding service for examos_lab benchmark datasets (M3-DB-1).

Features:
- Deterministic data generation using a pseudorandom number generator with recorded seed.
- Paired insertion into both `lab_students_no_index` and `lab_students_indexed`
  with identical data, order, and row counts.
- Paired insertion into both `lab_enrollments_no_index` and `lab_enrollments_indexed`.
- Idempotent: clears prior lab records and reseeds cleanly without affecting application data.
"""

from __future__ import annotations

import random
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.services.benchmark_catalog import DATASET_SIZES

DEPARTMENTS = [
    "Computer Science",
    "Information Technology",
    "Electrical Engineering",
    "Mechanical Engineering",
    "Civil Engineering",
]

COURSE_CODES = [
    "CS101", "CS201", "CS301", "CS401",
    "IT101", "IT201", "IT301",
    "EE101", "EE201", "ME101", "CE101",
]

FIRST_NAMES = [
    "Aarav", "Aditi", "Amit", "Ananya", "Dev", "Diya", "Hardik", "Isha",
    "Kavya", "Manish", "Neha", "Pooja", "Rahul", "Riya", "Rohan", "Sanjay",
    "Shreya", "Sneha", "Tanvi", "Varun", "Vikas", "Yash",
]

LAST_NAMES = [
    "Agarwal", "Bansal", "Chopra", "Gupta", "Kapil", "Kumar", "Mehta", "Mishra",
    "Patel", "Reddy", "Sharma", "Singh", "Verma", "Yadav",
]


def seed_lab_dataset(
    db: Session,
    size: str = "small",
    seed: int = 42,
) -> dict[str, Any]:
    """
    Seed paired datasets in schema `examos_lab` deterministically.
    Returns summary statistics including row counts and checksums.
    """
    if size not in DATASET_SIZES:
        raise ValueError(f"Invalid dataset size '{size}'. Allowed: {list(DATASET_SIZES.keys())}")

    config = DATASET_SIZES[size]
    student_count = config["student_count"]
    enrollments_per_student = config["enrollments_per_student"]

    # 1. Clean existing lab tables (DELETE requires DELETE privilege; TRUNCATE requires table ownership)
    db.execute(text("DELETE FROM examos_lab.lab_enrollments_no_index"))
    db.execute(text("DELETE FROM examos_lab.lab_enrollments_indexed"))
    db.execute(text("DELETE FROM examos_lab.lab_students_no_index"))
    db.execute(text("DELETE FROM examos_lab.lab_students_indexed"))

    # 2. Deterministic generator
    rng = random.Random(seed)

    students_data: list[dict[str, Any]] = []
    enrollments_data: list[dict[str, Any]] = []

    enrollment_id_counter = 1

    for s_id in range(1, student_count + 1):
        fn = rng.choice(FIRST_NAMES)
        ln = rng.choice(LAST_NAMES)
        full_name = f"{fn} {ln}"
        dept = rng.choice(DEPARTMENTS)
        gpa = round(Decimal(rng.uniform(2.0, 4.0)), 2)
        year = rng.randint(2020, 2024)
        stu_num = f"STU-{s_id:05d}"

        students_data.append({
            "id": s_id,
            "student_number": stu_num,
            "full_name": full_name,
            "department": dept,
            "gpa": gpa,
            "enrolled_year": year,
        })

        # Generate courses for this student
        chosen_courses = rng.sample(COURSE_CODES, min(enrollments_per_student, len(COURSE_CODES)))
        for c_code in chosen_courses:
            grade_pt = round(Decimal(rng.uniform(2.0, 4.0)), 2)
            sem = f"{year + rng.randint(0, 3)}-{rng.choice(['Fall', 'Spring'])}"
            enrollments_data.append({
                "id": enrollment_id_counter,
                "student_id": s_id,
                "course_code": c_code,
                "semester": sem,
                "grade_point": grade_pt,
            })
            enrollment_id_counter += 1

    # 3. Batch insert into paired student tables
    stmt_students_no_idx = text(
        "INSERT INTO examos_lab.lab_students_no_index "
        "(id, student_number, full_name, department, gpa, enrolled_year) "
        "VALUES (:id, :student_number, :full_name, :department, :gpa, :enrolled_year)"
    )
    stmt_students_idx = text(
        "INSERT INTO examos_lab.lab_students_indexed "
        "(id, student_number, full_name, department, gpa, enrolled_year) "
        "VALUES (:id, :student_number, :full_name, :department, :gpa, :enrolled_year)"
    )

    db.execute(stmt_students_no_idx, students_data)
    db.execute(stmt_students_idx, students_data)

    # 4. Batch insert into paired enrollment tables
    stmt_enrollments_no_idx = text(
        "INSERT INTO examos_lab.lab_enrollments_no_index "
        "(id, student_id, course_code, semester, grade_point) "
        "VALUES (:id, :student_id, :course_code, :semester, :grade_point)"
    )
    stmt_enrollments_idx = text(
        "INSERT INTO examos_lab.lab_enrollments_indexed "
        "(id, student_id, course_code, semester, grade_point) "
        "VALUES (:id, :student_id, :course_code, :semester, :grade_point)"
    )

    db.execute(stmt_enrollments_no_idx, enrollments_data)
    db.execute(stmt_enrollments_idx, enrollments_data)

    db.commit()

    # 5. Explicitly refresh PostgreSQL statistics on all 4 lab tables
    try:
        db.execute(text("ANALYZE examos_lab.lab_students_no_index"))
        db.execute(text("ANALYZE examos_lab.lab_students_indexed"))
        db.execute(text("ANALYZE examos_lab.lab_enrollments_no_index"))
        db.execute(text("ANALYZE examos_lab.lab_enrollments_indexed"))
        db.commit()
    except Exception as e:
        raise RuntimeError(f"Failed to refresh PostgreSQL statistics on examos_lab tables: {e}") from e

    return {
        "dataset_size": size,
        "seed": seed,
        "student_count": len(students_data),
        "enrollment_count": len(enrollments_data),
        "students_no_index_rows": len(students_data),
        "students_indexed_rows": len(students_data),
        "enrollments_no_index_rows": len(enrollments_data),
        "enrollments_indexed_rows": len(enrollments_data),
        "analyzed": True,
    }


def get_lab_dataset_status(db: Session) -> dict[str, int]:
    """Check current row counts of all 4 lab tables."""
    res_s_no = db.execute(text("SELECT count(*) FROM examos_lab.lab_students_no_index")).scalar() or 0
    res_s_idx = db.execute(text("SELECT count(*) FROM examos_lab.lab_students_indexed")).scalar() or 0
    res_e_no = db.execute(text("SELECT count(*) FROM examos_lab.lab_enrollments_no_index")).scalar() or 0
    res_e_idx = db.execute(text("SELECT count(*) FROM examos_lab.lab_enrollments_indexed")).scalar() or 0

    return {
        "students_no_index": res_s_no,
        "students_indexed": res_s_idx,
        "enrollments_no_index": res_e_no,
        "enrollments_indexed": res_e_idx,
    }


def inspect_active_lab_dataset(db: Session) -> dict[str, Any]:
    """Inspect actual row counts and classify the active dataset scale.

    Returns:
        {
            "detected_scale": "small" | "medium" | "large" | "inconsistent" | "empty",
            "is_consistent": bool,
            "counts": {
                "students_no_index": int,
                "students_indexed": int,
                "enrollments_no_index": int,
                "enrollments_indexed": int,
            },
            "description": str,
        }
    """
    counts = get_lab_dataset_status(db)
    s_no = counts["students_no_index"]
    s_idx = counts["students_indexed"]
    e_no = counts["enrollments_no_index"]
    e_idx = counts["enrollments_indexed"]

    if s_no == 0 and s_idx == 0 and e_no == 0 and e_idx == 0:
        return {
            "detected_scale": "empty",
            "is_consistent": True,
            "counts": counts,
            "description": "Lab tables are empty. Please seed an initial dataset.",
        }

    # Paired parity check
    if s_no != s_idx or e_no != e_idx:
        return {
            "detected_scale": "inconsistent",
            "is_consistent": False,
            "counts": counts,
            "description": (
                f"Paired tables have mismatched row counts (students: {s_no} vs {s_idx}, "
                f"enrollments: {e_no} vs {e_idx}). Reseeding is required."
            ),
        }

    # Match against documented standard sizes
    matched_scale: str | None = None
    for scale_key, spec in DATASET_SIZES.items():
        expected_students = spec["student_count"]
        expected_enrollments = expected_students * spec["enrollments_per_student"]
        if s_no == expected_students and e_no == expected_enrollments:
            matched_scale = scale_key
            break

    if matched_scale:
        return {
            "detected_scale": matched_scale,
            "is_consistent": True,
            "counts": counts,
            "description": f"Active dataset verified as '{matched_scale}' ({s_no} students, {e_no} enrollments).",
        }

    return {
        "detected_scale": "unknown",
        "is_consistent": False,
        "counts": counts,
        "description": f"Row counts ({s_no} students, {e_no} enrollments) do not match any standard catalog scale.",
    }
