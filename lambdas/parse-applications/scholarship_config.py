"""
Scholarship type configurations.

Each config maps a filename pattern to:
- scholarship_type: human-readable label
- rubric_id: machine key for rubric lookup
- column_map: raw Excel column name -> normalized field name
- department_essay_topic: label for the department-specific essay question
"""

import re

SCHOLARSHIP_CONFIGS = {
    "SJSU General Scholarship": {
        "scholarship_type": "SJSU General Scholarship",
        "rubric_id": "sjsu-general",
        "department_essay_topic": None,
        "column_map": {
            "AvailabilityId_t": "availability_id",
            "Student": "student_name",
            "FASO_General_Challenge or Mistake": "essay_challenge_or_mistake",
            "FASO_General_Career Goals": "essay_career_goals",
            "PS_Academic Program": "academic_program",
            "FASO_General_Extracurricular Activities": "essay_extracurricular_activities",
            "PS_Major(s)": "major",
            "PS_Academic Level": "academic_level",
            "PS_Cumulative GPA": "gpa",
        },
    },
    "College of Engineering Dean_s Student Scholarship": {
        "scholarship_type": "College of Engineering Dean's Student Scholarship",
        "rubric_id": "coeng-deans",
        "department_essay_topic": "Leadership",
        "column_map": {
            "AvailabilityId_t": "availability_id",
            "Student": "student_name",
            "COENG_Leadership": "essay_department_specific",
            "PS_Cumulative GPA": "gpa",
            "FASO_General_Challenge or Mistake": "essay_challenge_or_mistake",
            "FASO_General_Career Goals": "essay_career_goals",
            "FASO_General_Extracurricular Activities": "essay_extracurricular_activities",
        },
    },
    "Lurie College of Education General Scholarship": {
        "scholarship_type": "Lurie College of Education General Scholarship",
        "rubric_id": "lurie-coed-general",
        "department_essay_topic": "Department Career Goals",
        "column_map": {
            "AvailabilityId_t": "availability_id",
            "Student": "student_name",
            "COED_Career Goals": "essay_department_specific",
            "LCOE_Career Goals": "essay_department_specific",
            "FASO_General_Challenge or Mistake": "essay_challenge_or_mistake",
            "FASO_General_Career Goals": "essay_career_goals",
        },
    },
    "Physics Department Scholarship": {
        "scholarship_type": "Physics Department Scholarship",
        "rubric_id": "physics-dept",
        "department_essay_topic": "Challenges",
        "column_map": {
            "AvailabilityId_t": "availability_id",
            "Student": "student_name",
            "COS_J. Williams_Challenges": "essay_department_specific",
            "PS_Cumulative GPA": "gpa",
            "FASO_General_Challenge or Mistake": "essay_challenge_or_mistake",
            "FASO_General_Career Goals": "essay_career_goals",
            "FASO_General_Extracurricular Activities": "essay_extracurricular_activities",
            "FASO_General_Self-Reported GPA": "self_reported_gpa",
        },
    },
}


def identify_scholarship(filename: str) -> dict | None:
    """Match a filename to a scholarship config. Returns config dict or None."""
    for key, config in SCHOLARSHIP_CONFIGS.items():
        if key in filename:
            return config
    return None


def extract_year(filename: str) -> str | None:
    """Extract academic year from filename (e.g. '25-26' or '26-27')."""
    match = re.search(r"(\d{2}-\d{2})", filename)
    return match.group(1) if match else None
