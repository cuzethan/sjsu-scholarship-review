# Parser — Memory / Change Log

## 2026-07-14: Config-Driven qa_pairs Refactor

### What Changed

The parser output was refactored from a hardcoded `essays` object to a config-driven `qa_pairs` array.

**Before:**
```python
# parser.py had hardcoded essay routing:
elif normalized_field == "essay_career_goals":
    record["essays"]["career_goals"] = value
elif normalized_field == "essay_challenge_or_mistake":
    record["essays"]["challenge_or_mistake"] = value
# ...etc
```

**After:**
```python
# parser.py has ZERO essay knowledge. It just loops:
for essay_def in config["essay_fields"]:
    # try column, build qa_pair from config metadata
```

---

### Why

1. The LLM scoring step needs `{question, answer}` pairs — not a fixed object with field names it has to interpret.
2. Different scholarships have different questions. Hardcoding means parser changes every time a scholarship is added.
3. Config-driven means adding a new scholarship or question is just a new entry in `scholarship_config.py`.

---

### Files Modified

| File | What Changed |
|---|---|
| `scholarship_config.py` | Split into `column_map` (non-essay structured fields only) + `essay_fields` (list of essay definitions). Each essay field has `raw_column`, `question_id`, `question`, and optional `topic`/`alt_columns`. |
| `parser.py` | Removed all `essay_`/`ESSAY_FIELD_PREFIX` logic. `normalize_row()` now iterates `config["essay_fields"]` to build `qa_pairs`. No question text or IDs exist in parser.py. |

---

### Config Shape (scholarship_config.py)

```python
{
    "scholarship_type": "College of Engineering Dean's Student Scholarship",
    "rubric_id": "coeng-deans",
    "column_map": {
        # Non-essay fields ONLY
        "AvailabilityId_t": "availability_id",
        "Student": "student_name",
        "PS_Cumulative GPA": "gpa",
    },
    "essay_fields": [
        {
            "raw_column": "FASO_General_Career Goals",   # Excel column name
            "question_id": "career_goals",               # stable ID for downstream scoring
            "question": "What are your career goals?",   # full question text sent to LLM
        },
        {
            "raw_column": "COENG_Leadership",
            "question_id": "department_specific",
            "question": "Describe your leadership experience...",
            "topic": "Leadership",                       # optional — included in output when present
        },
    ],
}
```

---

### Output Shape (per application)

```json
{
  "application_id": "uuid",
  "scholarship_type": "College of Engineering Dean's Student Scholarship",
  "rubric_id": "coeng-deans",
  "year": "25-26",
  "student_name": "anonymized-uuid",
  "availability_id": "Engineering Dean's Student Scholarship",
  "gpa": 3.7,
  "self_reported_gpa": null,
  "academic_program": null,
  "academic_level": null,
  "major": null,
  "qa_pairs": [
    {
      "question_id": "career_goals",
      "question": "What are your career goals?",
      "answer": "..."
    },
    {
      "question_id": "challenge_or_mistake",
      "question": "Describe a challenge or mistake and what you learned from it.",
      "answer": "..."
    },
    {
      "question_id": "department_specific",
      "question": "Describe your leadership experience...",
      "answer": "...",
      "topic": "Leadership"
    }
  ],
  "source": {
    "file_name": "College of Engineering Dean_s Student Scholarship 25-26 ad hoc report.xlsx",
    "sheet_name": "ScholarshipManagerData (26)",
    "row_number": 2
  }
}
```

---

### How It Works (step by step)

1. `parser.py` reads an xlsx from S3
2. Identifies the scholarship type from the filename → gets the config
3. For each row:
   - Iterates `config["column_map"]` → fills structured fields (`student_name`, `gpa`, etc.)
   - Iterates `config["essay_fields"]` → for each essay definition:
     - Tries `raw_column` first, then any `alt_columns` (handles naming inconsistencies)
     - If a non-empty answer is found, builds a qa_pair `{question_id, question, answer, ?topic}`
     - Appends to `record["qa_pairs"]`
   - Skips the entire record if `student_name` is null
4. Outputs grouped JSON files by rubric_id + year

---

### Edge Cases Handled

| Case | How |
|---|---|
| Lurie 25-26 uses `COED_Career Goals`, 26-27 uses `LCOE_Career Goals` | `alt_columns` in essay_fields — parser tries primary then alternates |
| Physics 26-27 missing `FASO_General_Challenge or Mistake` column | Essay just doesn't appear in qa_pairs (skipped gracefully) |
| Physics 26-27 missing `AvailabilityId_t` | `availability_id` stays null |
| Empty/null essay answers | Skipped — not included in qa_pairs |
| GPA of 0.0 in first Engineering row | Stored as-is (may be a data quality issue to flag later) |

---

### How to Add a New Scholarship

1. Open `scholarship_config.py`
2. Add a new key to `SCHOLARSHIP_CONFIGS` matching the filename pattern
3. Define `column_map` for non-essay structured fields
4. Define `essay_fields` with one entry per essay question
5. Run `python parser.py --sample 2` to verify

No changes to `parser.py` needed.
