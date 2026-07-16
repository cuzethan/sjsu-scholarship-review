"""
scholarship_config.py — Phase 1 scope: SJSU General Scholarship ONLY.

Phase 1 actively supports a single scholarship (SJSU General) across both the
25-26 and 26-27 datasets, using ONE shared rubric + ONE shared prompt. The
active path has no `rubric_id` and no multi-rubric branching.

Specialized/department scholarships are kept as clearly-marked UNSUPPORTED stubs
so the architecture stays extensible, but they are NOT part of phase 1 and are
never scored. `identify_scholarship()` only returns the supported config.

Schema produced by the parser (see handler.normalize_row):
    application_key   = student UUID (sole PK, no sort key)
    availability_id   (raw scholarship label from the sheet)
    year              (extracted from filename; phase 1 = "26-27" only)
    scholarship_scope = "sjsu_general"
    student_name(None in this data), gpa, academic_program,
    academic_level, major, qa_pairs, source, status
"""

import re

# The single supported phase-1 scope.
SCHOLARSHIP_SCOPE = "sjsu_general"

# ---- Active (supported) config: SJSU General ----
SJSU_GENERAL_CONFIG = {
    "scope": SCHOLARSHIP_SCOPE,
    "scholarship_type": "SJSU General Scholarship",
    "supported": True,
    # filename substrings that identify an SJSU General application workbook
    "filename_markers": ["SJSU General Scholarship", "SJSU General Scholarships"],
    "column_map": {
        "AvailabilityId_t": "availability_id",
        "Student": "student_uuid",
        "PS_Academic Program": "academic_program",
        "PS_Major(s)": "major",
        "PS_Academic Level": "academic_level",
        "PS_Cumulative GPA": "gpa",
    },
    "essay_fields": [
        {
            "raw_column": "FASO_General_Career Goals",
            "question_id": "career_goals",
            "question": "What are your career goals?",
        },
        {
            "raw_column": "FASO_General_Challenge or Mistake",
            "question_id": "challenge_or_mistake",
            "question": "Describe a challenge or mistake and what you learned from it.",
        },
        {
            "raw_column": "FASO_General_Extracurricular Activities",
            "question_id": "extracurricular_activities",
            "question": "Describe your extracurricular activities.",
        },
    ],
}

# ---- UNSUPPORTED stubs (extensibility placeholders, NOT scored in phase 1) ----
# These exist only to document the intended extension path. The parser and scorer
# ignore them. Do NOT claim support for these in phase 1.
UNSUPPORTED_SCHOLARSHIPS = {
    "coeng-deans": {
        "scope": "coeng_deans",
        "scholarship_type": "College of Engineering Dean's Student Scholarship",
        "supported": False,
        "note": "Phase 2+ — department-specific rubric not implemented.",
    },
    "lurie-coed-general": {
        "scope": "lurie_coed_general",
        "scholarship_type": "Lurie College of Education General Scholarship",
        "supported": False,
        "note": "Phase 2+ — department-specific rubric not implemented.",
    },
    "physics-dept": {
        "scope": "physics_dept",
        "scholarship_type": "Physics Department Scholarship",
        "supported": False,
        "note": "Phase 2+ — department-specific rubric not implemented.",
    },
}

NUMERIC_FIELDS = {"gpa", "self_reported_gpa"}
_YEAR_RE = re.compile(r"(\d{2}-\d{2})")


def identify_scholarship(filename: str):
    """Return the SUPPORTED config for a workbook filename, else None.

    Phase 1: only SJSU General is recognized. Specialized workbooks return None
    (skipped, logged as unsupported).
    """
    for marker in SJSU_GENERAL_CONFIG["filename_markers"]:
        if marker in filename:
            return SJSU_GENERAL_CONFIG
    return None


def extract_year(filename: str) -> str | None:
    """Extract academic year from filename (e.g. '25-26' or '26-27')."""
    m = _YEAR_RE.search(filename)
    return m.group(1) if m else None


def build_application_key(student_uuid: str) -> str:
    """PK = student UUID as-is (sole primary key, no sort key)."""
    return student_uuid
