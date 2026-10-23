"""
Predefined benchmark catalog for ExamOS Database Performance Lab (M3-DB-1).

Docs:
- docs/04_API_CONTRACT.md §7 Database Performance Lab
- docs/01_REQUIREMENTS.md FR-DBLAB-001 to FR-DBLAB-015
- docs/03_DATABASE_DESIGN.md §§3.10, 5, 7

Educational objectives:
Demonstrates real PostgreSQL query plans and execution timings on controlled lab datasets
in examos_lab. Shows how index access compares with sequential scan for:
1. Selective point lookup (unique index scan vs seq scan).
2. Inner JOIN (indexed nested loop vs hash join / seq scan).
3. Grouped aggregation (index-assisted grouping / index scan vs hash aggregate / seq scan).
Also explains why indexes might not benefit small tables or queries with low selectivity.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BenchmarkScenario:
    scenario_id: str
    title: str
    description: str
    learning_objective: str
    relevant_tables: list[str]
    allowed_dataset_sizes: list[str]
    query_no_index: str
    query_indexed: str
    default_parameters: dict[str, Any]
    index_explanation: str
    caveat_notes: str


BENCHMARK_SCENARIOS: dict[str, BenchmarkScenario] = {
    "selective_lookup": BenchmarkScenario(
        scenario_id="selective_lookup",
        title="Selective Point Lookup (Single Row)",
        description="Lookup a specific student record by unique student number.",
        learning_objective=(
            "Demonstrates the contrast between an Index Scan (or Index Only Scan) on a B-tree "
            "index versus a full Sequential Scan (heap scan) when filtering for a single record."
        ),
        relevant_tables=["examos_lab.lab_students_no_index", "examos_lab.lab_students_indexed"],
        allowed_dataset_sizes=["small", "medium", "large"],
        query_no_index=(
            "SELECT id, student_number, full_name, department, gpa, enrolled_year "
            "FROM examos_lab.lab_students_no_index "
            "WHERE student_number = :student_number"
        ),
        query_indexed=(
            "SELECT id, student_number, full_name, department, gpa, enrolled_year "
            "FROM examos_lab.lab_students_indexed "
            "WHERE student_number = :student_number"
        ),
        default_parameters={"student_number": "STU-00042"},
        index_explanation=(
            "A B-tree index on student_number allows PostgreSQL to traverse the tree in O(log N) "
            "and fetch the exact page containing the tuple. Without the index, PostgreSQL must "
            "perform a Sequential Scan reading every table block from disk or buffer cache."
        ),
        caveat_notes=(
            "On very small datasets (e.g. fewer than 100 rows fitting in a single disk page), "
            "PostgreSQL's cost planner may choose a sequential scan over an index scan because "
            "reading the single block is faster than reading both index and heap blocks."
        ),
    ),
    "join_students_enrollments": BenchmarkScenario(
        scenario_id="join_students_enrollments",
        title="Equi-JOIN (Students and Course Enrollments)",
        description="Inner JOIN students with their course enrollments filtered by department.",
        learning_objective=(
            "Demonstrates how foreign-key indexes on joining keys (student_id) enable "
            "Index-assisted Nested Loop joins instead of Hash Join or Merge Join with Sequential Scans."
        ),
        relevant_tables=[
            "examos_lab.lab_students_no_index",
            "examos_lab.lab_enrollments_no_index",
            "examos_lab.lab_students_indexed",
            "examos_lab.lab_enrollments_indexed",
        ],
        allowed_dataset_sizes=["small", "medium", "large"],
        query_no_index=(
            "SELECT s.student_number, s.full_name, s.department, e.course_code, e.grade_point "
            "FROM examos_lab.lab_students_no_index s "
            "JOIN examos_lab.lab_enrollments_no_index e ON s.id = e.student_id "
            "WHERE s.department = :department"
        ),
        query_indexed=(
            "SELECT s.student_number, s.full_name, s.department, e.course_code, e.grade_point "
            "FROM examos_lab.lab_students_indexed s "
            "JOIN examos_lab.lab_enrollments_indexed e ON s.id = e.student_id "
            "WHERE s.department = :department"
        ),
        default_parameters={"department": "Computer Science"},
        index_explanation=(
            "With indexes on department and student_id, the planner can locate matching students "
            "via index and look up each student's enrollments using the enrollment student_id index. "
            "Without indexes, both tables must be scanned sequentially and hashed in memory."
        ),
        caveat_notes=(
            "If the department filter matches a large fraction of the table (low selectivity), "
            "a Hash Join with sequential scan is often more efficient than repeated random index lookups."
        ),
    ),
    "aggregation_department_gpa": BenchmarkScenario(
        scenario_id="aggregation_department_gpa",
        title="Grouped Aggregation (Average GPA by Department)",
        description="Compute aggregate statistics (count, average GPA, min, max) grouped by department.",
        learning_objective=(
            "Demonstrates HashAggregate vs GroupAggregate execution strategies and the effect "
            "of pre-sorted or indexed keys on grouping and aggregation efficiency."
        ),
        relevant_tables=["examos_lab.lab_students_no_index", "examos_lab.lab_students_indexed"],
        allowed_dataset_sizes=["small", "medium", "large"],
        query_no_index=(
            "SELECT department, COUNT(*) AS student_count, "
            "ROUND(AVG(gpa), 2) AS avg_gpa, MIN(gpa) AS min_gpa, MAX(gpa) AS max_gpa "
            "FROM examos_lab.lab_students_no_index "
            "GROUP BY department "
            "ORDER BY department"
        ),
        query_indexed=(
            "SELECT department, COUNT(*) AS student_count, "
            "ROUND(AVG(gpa), 2) AS avg_gpa, MIN(gpa) AS min_gpa, MAX(gpa) AS max_gpa "
            "FROM examos_lab.lab_students_indexed "
            "GROUP BY department "
            "ORDER BY department"
        ),
        default_parameters={},
        index_explanation=(
            "With an index on department, PostgreSQL can evaluate the grouping using GroupAggregate "
            "via an Index Scan in ordered fashion. Without an index, PostgreSQL gathers all tuples "
            "into a hash table using HashAggregate followed by Sort."
        ),
        caveat_notes=(
            "Because aggregation must read every row to compute count and average, the speedup "
            "from an index is limited compared to highly selective point lookups. Furthermore, "
            "modern CPUs evaluate in-memory HashAggregate extremely quickly on small-to-medium tables."
        ),
    ),
}

# Standard dataset scale definitions
DATASET_SIZES = {
    "small": {
        "label": "Small (100 students, ~400 enrollments)",
        "student_count": 100,
        "enrollments_per_student": 4,
    },
    "medium": {
        "label": "Medium (1,000 students, ~4,000 enrollments)",
        "student_count": 1000,
        "enrollments_per_student": 4,
    },
    "large": {
        "label": "Large (10,000 students, ~40,000 enrollments)",
        "student_count": 10000,
        "enrollments_per_student": 4,
    },
}
