"""
dataset_builder.py — build the joined evaluation dataset.

Steps:
1. Parse application xlsx (reuse repo parser) from input/applications.
2. Load human score sheets from input/scores (Candidate join key).
3. Join on candidate_key = last-12-hex(student_uuid) == Candidate.
   - Only keep valid 1:1 joins.
   - Record every excluded record/file and why.
4. Randomly sample up to SAMPLE_PER_SCHOLARSHIP per (scholarship_type, year).
5. Emit eval records carrying metadata for reporting.

The LLM never sees human scores — those are kept in a separate field of the eval
record and only used later by the comparison step.
"""

from __future__ import annotations

import random

from config import SAMPLE_PER_SCHOLARSHIP, RANDOM_SEED
from human_scores import candidate_key_from_uuid, load_all_scores
from local_parser import parse_all_applications


def build_dataset(applications_dir, scores_dir):
    """Return (eval_records, report).

    eval_record = {
      scholarship_type, year, rubric_id, student_uuid, candidate_key,
      application_key, qa_pairs, gpa, self_reported_gpa, major,
      academic_level, academic_program,
      human: { human_avg, reviewer_scores, source_file }   # NEVER sent to LLM
    }
    """
    report = {
        "applications_parsed": 0,
        "application_files_skipped": [],
        "score_sheets": [],
        "score_candidates_loaded": 0,
        "excluded_no_candidate_key": 0,
        "excluded_no_human_match": 0,
        "joined": 0,
        "sampled": 0,
        "by_group": {},
    }

    apps, skipped = parse_all_applications(applications_dir)
    report["applications_parsed"] = len(apps)
    report["application_files_skipped"] = skipped

    candidate_index, sheet_reports = load_all_scores(scores_dir)
    report["score_sheets"] = sheet_reports
    report["score_candidates_loaded"] = len(candidate_index)

    # --- Join (scoped by rubric_id + year + candidate_key) ---
    # Phase 1: evaluation is narrowed to SJSU General only.
    from config import EVAL_SCOPE_RUBRIC_IDS
    joined = []
    for app in apps:
        if app.get("rubric_id") not in EVAL_SCOPE_RUBRIC_IDS:
            continue
        ckey = candidate_key_from_uuid(app.get("student_uuid"))
        if ckey is None:
            report["excluded_no_candidate_key"] += 1
            continue
        human = candidate_index.get((app.get("rubric_id"), app.get("year"), ckey))
        if human is None:
            report["excluded_no_human_match"] += 1
            continue
        joined.append({
            "scholarship_type": app.get("scholarship_type"),
            "year": app.get("year"),
            "rubric_id": app.get("rubric_id"),
            "student_uuid": app.get("student_uuid"),
            "candidate_key": ckey,
            "application_key": app.get("application_id"),
            "qa_pairs": app.get("qa_pairs", []),
            "gpa": app.get("gpa"),
            "self_reported_gpa": app.get("self_reported_gpa"),
            "major": app.get("major"),
            "academic_level": app.get("academic_level"),
            "academic_program": app.get("academic_program"),
            "human": {
                "human_total": human["human_total"],
                "criterion_avgs": human.get("criterion_avgs", {}),
                "reviewer_totals": human.get("reviewer_totals", {}),
                "source_file": human["source_file"],
            },
        })
    report["joined"] = len(joined)

    # --- Sample per (scholarship_type, year) ---
    rng = random.Random(RANDOM_SEED)
    groups = {}
    for rec in joined:
        groups.setdefault((rec["scholarship_type"], rec["year"]), []).append(rec)

    sampled = []
    for (stype, year), recs in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        rng.shuffle(recs)
        take = recs[:SAMPLE_PER_SCHOLARSHIP]
        sampled.extend(take)
        report["by_group"][f"{stype} | {year}"] = {
            "joined": len(recs),
            "sampled": len(take),
        }

    report["sampled"] = len(sampled)
    return sampled, report
