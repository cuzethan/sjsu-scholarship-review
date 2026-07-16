"""
selfcheck.py — runnable check for the eval harness core logic (no Bedrock, no xlsx).

Exercises: schema.validate, compare.compute_metrics, report.render_report using
synthetic inference results + human scores. Fails loudly if the logic breaks.

    python selfcheck.py
"""

from __future__ import annotations

import sys

from schema import validate, SchemaError
from compare import compute_metrics
from report import render_report


def check_schema():
    good = {
        "criterion_scores": [
            {"criterion": "Academics", "score": 4, "reasoning": "strong",
             "evidence": [{"question_id": "career_goals", "quote": "I want to teach"}]},
        ],
        "total_score": 4, "confidence": 0.8,
    }
    validate(good)  # should not raise

    bad_cases = [
        {},  # missing criterion_scores
        {"criterion_scores": [], "total_score": 1, "confidence": 0.5},  # empty list
        {"criterion_scores": [{"criterion": "x", "score": "hi", "reasoning": "r"}],
         "total_score": 1, "confidence": 0.5},  # non-numeric score
        {"criterion_scores": [{"criterion": "x", "score": 1, "reasoning": "r"}],
         "total_score": 1, "confidence": 2.0},  # confidence out of range
    ]
    for bc in bad_cases:
        try:
            validate(bc)
        except SchemaError:
            continue
        raise AssertionError(f"schema should have rejected: {bc}")
    print("  schema: OK")


def _mk_result(model_id, ckey, stype, year, total, valid=True, conf=0.7,
               latency=1.0, out_tok=200, failure=None):
    parsed = None
    if valid:
        parsed = {
            "criterion_scores": [
                {"criterion": "C1", "score": total, "reasoning": "r", "evidence": []},
            ],
            "total_score": total, "confidence": conf,
        }
    return {
        "model_id": model_id, "effective_id": model_id, "substituted": False,
        "candidate_key": ckey, "rubric_id": "sjsu-general",
        "scholarship_type": stype, "year": year,
        "latency_s": latency, "input_tokens": 500, "output_tokens": out_tok,
        "raw": "{}", "parsed": parsed, "valid": valid, "failure": failure,
    }


def check_metrics_and_report():
    # Two models, 3 candidates. Human totals: 3,4,5. Keys: rubric|year|candidate
    human_lookup = {
        "sjsu-general|25-26|aaaaaaaaaaaa": {"human_total": 3.0, "criterion_avgs": {"C1": 3.0},
                                            "reviewer_totals": {"r1": 3, "r2": 3}},
        "sjsu-general|25-26|bbbbbbbbbbbb": {"human_total": 4.0, "criterion_avgs": {"C1": 4.0},
                                            "reviewer_totals": {"r1": 4, "r2": 4}},
        "sjsu-general|25-26|cccccccccccc": {"human_total": 5.0, "criterion_avgs": {"C1": 5.0},
                                            "reviewer_totals": {"r1": 4, "r2": 6}},
    }
    results = [
        # good_model: exactly matches humans (MAE 0, corr 1)
        _mk_result("good_model", "aaaaaaaaaaaa", "General", "25-26", 3.0),
        _mk_result("good_model", "bbbbbbbbbbbb", "General", "25-26", 4.0),
        _mk_result("good_model", "cccccccccccc", "General", "25-26", 5.0),
        # noisy_model: off by 1 each, plus one failure
        _mk_result("noisy_model", "aaaaaaaaaaaa", "General", "25-26", 4.0),
        _mk_result("noisy_model", "bbbbbbbbbbbb", "General", "25-26", 5.0),
        _mk_result("noisy_model", "cccccccccccc", "General", "25-26", None,
                   valid=False, failure="parse/schema: boom"),
    ]

    metrics = compute_metrics(results, human_lookup)
    gm = metrics["per_model"]["good_model"]
    nm = metrics["per_model"]["noisy_model"]

    assert gm["n"] == 3, gm
    assert gm["mae"] == 0.0, gm
    assert gm["pearson"] == 1.0, gm
    assert gm["within_1"] == 1.0, gm
    assert gm["valid_rate"] == 1.0, gm
    # good_model totals 3,4,5; reviewer ranges [3,3],[4,4],[4,6] -> in-range for cand a,b,c = 3/3
    assert gm["within_reviewer_range"] == 1.0, gm

    assert nm["n"] == 2, nm                     # 2 valid (third failed)
    assert nm["mae"] == 1.0, nm                 # off by 1
    assert nm["bias"] == 1.0, nm                # model higher than human
    assert round(nm["valid_rate"], 3) == 0.667, nm
    assert len(nm["failures"]) == 1, nm
    print("  metrics: OK")

    resolved = [
        {"id": "good_model", "label": "Good", "available": True,
         "effective_id": "good_model", "substituted": False, "unavailable_reason": None},
        {"id": "noisy_model", "label": "Noisy", "available": True,
         "effective_id": "noisy_model", "substituted": False, "unavailable_reason": None},
        {"id": "amazon.nova-micro-v1:0", "label": "Nova Micro", "available": False,
         "effective_id": None, "substituted": False,
         "unavailable_reason": "not available"},
    ]
    dataset_report = {
        "applications_parsed": 3, "application_files_skipped": [],
        "score_sheets": [{"file": "scores.xlsx", "included": True,
                          "candidate_col": "Candidate", "reviewer_cols": ["r1", "r2"],
                          "reason": ""}],
        "score_candidates_loaded": 3, "excluded_no_candidate_key": 0,
        "excluded_no_human_match": 0, "joined": 3, "sampled": 3,
        "by_group": {"General | 25-26": {"joined": 3, "sampled": 3}},
    }
    html_doc = render_report(metrics, dataset_report, resolved)
    for needle in ["Recommendation", "Decision matrix", "good_model", "noisy_model",
                   "Cost vs Accuracy", "What the metrics mean", "Data coverage",
                   "Example comparisons", "Technical appendix", "chart.js",
                   "Usable model leaderboard", "Failed / unavailable"]:
        assert needle.lower() in html_doc.lower(), f"report missing: {needle!r}"
    assert html_doc.strip().startswith("<!DOCTYPE html>")
    # UTF-8 safety: no raw mojibake, and charset declared
    assert 'charset="utf-8"' in html_doc
    for bad in ["\u00e2\u20ac\u201d", "\u00e2\u2020"]:  # â€" , â†
        assert bad not in html_doc, "mojibake detected in report"

    # recommendation logic
    from recommendation import build_recommendation
    reco = build_recommendation(metrics, resolved, dataset_report)
    assert reco["best_overall_id"] == "good_model", reco
    assert reco["recommended"]["label"] == "Good", reco
    ids_in_matrix = {d["model_id"] for d in reco["decision_matrix"]}
    assert "amazon.nova-micro-v1:0" in ids_in_matrix, "unavailable model missing from matrix"
    assert any(d["verdict"] == "Best overall" for d in reco["decision_matrix"]), reco
    assert reco["examples"].get("close"), "no close example"
    print(f"  report: OK ({len(html_doc)} bytes)")
    print("  recommendation: OK")


if __name__ == "__main__":
    check_schema()
    check_metrics_and_report()
    print("SELFCHECK PASSED")
    sys.exit(0)
