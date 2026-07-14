"""
Scholarship type configurations.

Each config maps a filename pattern to:
- scholarship_type: human-readable label (passed to LLM for rubric selection)
- rubric_id: machine key for rubric lookup
- column_map: raw Excel column -> normalized field name (non-essay fields only)
- essay_fields: list of essay field definitions that drive qa_pairs construction
"""

SCHOLARSHIP_CONFIGS = {
    "SJSU General Scholarship": {
        "scholarship_type": "SJSU General Scholarship",
        "rubric_id": "sjsu-general",
        "column_map": {
            "AvailabilityId_t": "availability_id",
            "Student": "student_name",
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
    },
    "College of Engineering Dean_s Student Scholarship": {
        "scholarship_type": "College of Engineering Dean's Student Scholarship",
        "rubric_id": "coeng-deans",
        "column_map": {
            "AvailabilityId_t": "availability_id",
            "Student": "student_name",
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
            {
                "raw_column": "COENG_Leadership",
                "question_id": "department_specific",
                "question": "Describe your leadership experience and what demonstrates your potential for success as an engineering student.",
                "topic": "Leadership",
            },
        ],
    },
    "Lurie College of Education General Scholarship": {
        "scholarship_type": "Lurie College of Education General Scholarship",
        "rubric_id": "lurie-coed-general",
        "column_map": {
            "AvailabilityId_t": "availability_id",
            "Student": "student_name",
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
                "raw_column": "COED_Career Goals",
                "alt_columns": ["LCOE_Career Goals"],
                "question_id": "department_specific",
                "question": "Describe your career goals specific to the College of Education.",
                "topic": "Department Career Goals",
            },
        ],
    },
    "Physics Department Scholarship": {
        "scholarship_type": "Physics Department Scholarship",
        "rubric_id": "physics-dept",
        "column_map": {
            "AvailabilityId_t": "availability_id",
            "Student": "student_name",
            "PS_Cumulative GPA": "gpa",
            "FASO_General_Self-Reported GPA": "self_reported_gpa",
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
            {
                "raw_column": "COS_J. Williams_Challenges",
                "question_id": "department_specific",
                "question": "Describe a challenge you have faced in your academic or personal life and how you overcame it (J. Williams Scholarship).",
                "topic": "Challenges",
            },
        ],
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
    import re

    match = re.search(r"(\d{2}-\d{2})", filename)
    return match.group(1) if match else None
