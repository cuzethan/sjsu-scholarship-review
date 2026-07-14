# Parser — Task Plan

Build a deterministic pandas-based parser that reads `.xlsx` scholarship application files,
normalizes each row into structured JSON, and writes records to DynamoDB.

---

## Status

- [x] Inspect all `.xlsx` files and compare structure (`inspect_xlsx.py`)
- [ ] Define scholarship type mappings
- [ ] Build parser core (`parser.py`)
- [ ] Write output JSON locally for testing
- [ ] Write to DynamoDB (`dynamo_writer.py`)
- [ ] Lambda handler wrapper (`handler.py`)

---

## Scholarship Files

| Scholarship | Years | Rows |
|---|---|---|
| SJSU General | 25-26, 26-27 | 1903, 4887 |
| College of Engineering | 25-26, 26-27 | 194, 132 |
| Lurie College of Education | 25-26, 26-27 | 281, 222 |
| Physics Department | 25-26, 26-27 | 9, 15 |

---

## Column Structure (per scholarship)

All files share a common base of 2–3 FASO essay questions plus optional profile fields.

### Common columns (most files)
| Raw Column | Normalized Field |
|---|---|
| `Student` | `student_name` |
| `FASO_General_Career Goals` | `essays.career_goals` |
| `FASO_General_Challenge or Mistake` | `essays.challenge_or_mistake` |
| `PS_Cumulative GPA` | `gpa` |
| `PS_Academic Program` | `academic_program` |
| `PS_Major(s)` | `major` |
| `PS_Academic Level` | `academic_level` |
| `FASO_General_Extracurricular Activities` | `essays.extracurricular_activities` |
| `FASO_General_Self-Reported GPA` | `self_reported_gpa` |

### Department-specific columns
| Scholarship | Raw Column | Normalized Field | Topic Label |
|---|---|---|---|
| College of Engineering | `COENG_Leadership` | `essays.department_specific` | `"Leadership"` |
| Lurie (25-26) | `COED_Career Goals` | `essays.department_specific` | `"Department Career Goals"` |
| Lurie (26-27) | `LCOE_Career Goals` | `essays.department_specific` | `"Department Career Goals"` |
| Physics | `COS_J. Williams_Challenges` | `essays.department_specific` | `"Challenges"` |
| SJSU General | *(none)* | `null` | `null` |

---

## Target JSON Schema (per application)

```json
{
  "application_id": "<uuid>",
  "availability_id": "12345",
  "scholarship_type": "College of Engineering Dean's Student Scholarship",
  "rubric_id": "coeng-deans-scholarship",
  "year": "26-27",
  "student_name": "Jane Doe",
  "gpa": 3.8,
  "self_reported_gpa": null,
  "academic_program": "Engineering",
  "academic_level": "Junior",
  "major": "Computer Engineering",
  "essays": {
    "career_goals": "I want to...",
    "challenge_or_mistake": "A time I failed...",
    "department_specific": "My leadership experience...",
    "department_essay_topic": "Leadership",
    "extracurricular_activities": null
  }
}
```

> `scholarship_type` is the human-readable label passed to the LLM so it knows which rubric to load.
> `rubric_id` is the machine key used to look up the rubric file.

---

## Scholarship Type → Rubric Mapping

| Scholarship Type | rubric_id |
|---|---|
| `SJSU General Scholarship` | `sjsu-general` |
| `College of Engineering Dean's Student Scholarship` | `coeng-deans` |
| `Lurie College of Education General Scholarship` | `lurie-coed-general` |
| `Physics Department Scholarship` | `physics-dept` |

---

## Parser Logic (step by step)

1. **Identify scholarship type** from the filename (e.g. `"College of Engineering"` in the filename → `coeng-deans`)
2. **Extract year** from the filename (`25-26` or `26-27`)
3. **Read the sheet** with pandas (`read_excel`)
4. **For each row**, map raw columns → normalized fields using the mapping table above
5. **Generate a UUID** as `application_id`
6. **Set `scholarship_type`** and `rubric_id` based on step 1
7. **Handle missing columns gracefully** — set field to `null` if the column isn't present
8. **Output**: list of normalized application dicts

---

## Questions / Decisions Needed

- [ ] Should `student_name` stay as a full string or be split into first/last?
      *(Note: current data is already redacted/anonymized per FERPA — names may be synthetic)*
- [ ] Physics 26-27 is missing `AvailabilityId_t` — is that okay or do we need to flag those rows?
- [ ] Should GPA be stored as a float or string? (raw values may have formatting issues)
- [ ] Do we deduplicate across years if the same student appears in both 25-26 and 26-27?
- [ ] Should the parser skip rows where all essay fields are null/empty?
- [ ] Should we add a `confidence_flag` at parse time (e.g. flag rows with missing essays)?

---

## Project Context (from Challenge Overview)

Key constraints that affect the parser design:

- **PII/FERPA**: Data is anonymized/synthetic. Parser should NOT assume real student names.
  No PII should leak into logs or error messages.
- **Scale**: 8,000+ applications/year, each needing ≥2 reviews. Parser must handle large files.
- **Shadow mode**: AI scoring runs in parallel to human review — parser output feeds AI scoring
  but does NOT replace human decisions.
- **Multi-scholarship**: Different departments have different rubrics and different essay questions.
  Parser must tag each record with the correct `scholarship_type` so the LLM picks the right rubric.
- **Calibration**: Historical human scores exist. Parser should preserve `availability_id` where
  present so records can be joined with historical human scores for agreement analysis.
- **Extension**: System should transfer to other CSU campuses. Parser design should be generic
  enough to support new scholarship types via config, not code changes.

---

## Files in This Folder

| File | Purpose |
|---|---|
| `inspect_xlsx.py` | One-off script to inspect column headers across all xlsx files |
| `parser.py` | *(to build)* Core parser — xlsx → list of application dicts |
| `dynamo_writer.py` | *(to build)* Writes parsed applications to DynamoDB |
| `handler.py` | *(to build)* Lambda entry point — reads from S3, calls parser, writes to DynamoDB |
| `task.md` | This file |
