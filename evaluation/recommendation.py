"""
recommendation.py — turn raw metrics into an explainable decision summary.

Produces the data the narrative report needs:
- usable vs failed/unavailable model split
- recommended (best overall), best-cheapest-usable, fastest-usable
- a decision matrix (verdict per model)
- run-health warnings (low sample size, failures, excluded sheets)
- concrete example cases (close / overscoring / underscoring)

Heuristic (simple + explainable):
- A model is "usable" if it produced >= MIN_VALID valid comparable outputs.
- Rank usable models by MAE ascending; tie-break by cost/app, then latency.
- best_overall  = rank 1 by that ordering.
- best_cheapest = usable model with the lowest cost/app.
- fastest       = usable model with the lowest avg latency.
- "Too inaccurate" verdict when MAE is much worse than the best usable model.
"""

from __future__ import annotations

# a model needs at least this many valid comparable outputs to be "usable"
MIN_VALID = 1
# if a run has fewer than this many valid rows for the best model, warn
LOW_CONFIDENCE_N = 10
# a usable model is flagged "too inaccurate" if its MAE exceeds
# best_mae + INACCURATE_MARGIN (absolute points)
INACCURATE_MARGIN = 3.0


def _rank_key(m: dict):
    mae = m.get("mae")
    cost = m.get("cost_per_app")
    lat = m.get("avg_latency_s")
    return (
        mae if mae is not None else 1e9,
        cost if cost is not None else 1e9,
        lat if lat is not None else 1e9,
    )


def build_recommendation(metrics: dict, resolved_models: list[dict],
                         dataset_report: dict) -> dict:
    per_model = metrics.get("per_model", {})

    # label lookup from resolved models
    label = {m["id"]: m.get("label", m["id"]) for m in resolved_models}
    availability = {m["id"]: m for m in resolved_models}

    usable, failed = [], []
    for mid, m in per_model.items():
        n = m.get("n") or 0
        if n >= MIN_VALID:
            usable.append(mid)
        else:
            # produced results rows but no valid comparable outputs
            reason = "no valid comparable outputs"
            fails = m.get("failures", [])
            if fails:
                # summarize the most common failure
                reason = _summarize_failures(fails)
            failed.append({"model_id": mid, "label": label.get(mid, mid),
                           "reason": reason, "kind": "invalid_output"})

    # models that never even ran (unavailable / not invoked)
    ran_ids = set(per_model.keys())
    for m in resolved_models:
        if not m.get("available"):
            failed.append({"model_id": m["id"], "label": m.get("label", m["id"]),
                           "reason": m.get("unavailable_reason") or "unavailable in account/region",
                           "kind": "unavailable"})
        elif m["id"] not in ran_ids:
            failed.append({"model_id": m["id"], "label": m.get("label", m["id"]),
                           "reason": "available but not evaluated in this run",
                           "kind": "not_run"})

    usable_sorted = sorted(usable, key=lambda mid: _rank_key(per_model[mid]))

    best_overall = usable_sorted[0] if usable_sorted else None
    best_cheapest = None
    fastest = None
    if usable_sorted:
        with_cost = [mid for mid in usable_sorted if per_model[mid].get("cost_per_app") is not None]
        if with_cost:
            best_cheapest = min(with_cost, key=lambda mid: per_model[mid]["cost_per_app"])
        with_lat = [mid for mid in usable_sorted if per_model[mid].get("avg_latency_s") is not None]
        if with_lat:
            fastest = min(with_lat, key=lambda mid: per_model[mid]["avg_latency_s"])

    best_mae = per_model[best_overall]["mae"] if best_overall and per_model[best_overall].get("mae") is not None else None

    # decision matrix
    matrix = []
    for mid in usable_sorted:
        m = per_model[mid]
        verdict = "Usable"
        if mid == best_overall:
            verdict = "Best overall"
        elif mid == best_cheapest:
            verdict = "Best low-cost option"
        if (best_mae is not None and m.get("mae") is not None
                and m["mae"] > best_mae + INACCURATE_MARGIN):
            verdict = "Too inaccurate"
        matrix.append({
            "model_id": mid, "label": label.get(mid, mid),
            "accuracy": _accuracy_word(m.get("mae"), best_mae),
            "mae": m.get("mae"), "cost_per_app": m.get("cost_per_app"),
            "avg_latency_s": m.get("avg_latency_s"), "valid_rate": m.get("valid_rate"),
            "reliability": _reliability_word(m.get("valid_rate")),
            "verdict": verdict,
        })
    for f in failed:
        matrix.append({
            "model_id": f["model_id"], "label": f["label"],
            "accuracy": "—", "mae": None, "cost_per_app": None,
            "avg_latency_s": None, "valid_rate": None, "reliability": "—",
            "verdict": "Failed in this run" if f["kind"] != "unavailable" else "Not currently usable",
            "reason": f["reason"],
        })

    # recommendation prose
    why = None
    if best_overall:
        m = per_model[best_overall]
        bits = [f"lowest MAE ({m.get('mae')}) among working models"]
        if best_overall == best_cheapest:
            bits.append("and also the cheapest usable model")
        elif m.get("cost_per_app") is not None:
            bits.append(f"at {_usd(m.get('cost_per_app'))}/application")
        if m.get("avg_latency_s") is not None:
            bits.append(f"{m.get('avg_latency_s')}s avg latency")
        why = ", ".join(bits)

    warnings = _run_warnings(metrics, dataset_report, best_overall, per_model)
    examples = _examples(per_model, best_overall)

    return {
        "recommended": _card(best_overall, per_model, label),
        "recommended_why": why,
        "cheapest": _card(best_cheapest, per_model, label),
        "fastest": _card(fastest, per_model, label),
        "usable_ids": usable_sorted,
        "failed": failed,
        "decision_matrix": matrix,
        "warnings": warnings,
        "examples": examples,
        "best_overall_id": best_overall,
    }


def _card(mid, per_model, label):
    if not mid:
        return None
    m = per_model[mid]
    return {
        "model_id": mid, "label": label.get(mid, mid),
        "mae": m.get("mae"), "cost_per_app": m.get("cost_per_app"),
        "avg_latency_s": m.get("avg_latency_s"), "valid_rate": m.get("valid_rate"),
        "n": m.get("n"), "within_1": m.get("within_1"),
    }


def _accuracy_word(mae, best_mae):
    if mae is None:
        return "—"
    if best_mae is None:
        return "—"
    if mae <= best_mae + 0.5:
        return "High"
    if mae <= best_mae + 2.0:
        return "Medium"
    return "Low"


def _reliability_word(valid_rate):
    if valid_rate is None:
        return "—"
    if valid_rate >= 0.95:
        return "High"
    if valid_rate >= 0.7:
        return "Medium"
    return "Low"


def _usd(v):
    return f"${v:.4f}" if isinstance(v, (int, float)) else "—"


def _summarize_failures(fails: list[dict]) -> str:
    kinds = {}
    for f in fails:
        msg = (f.get("failure") or "").lower()
        if "access denied" in msg or "resourcenotfound" in msg:
            k = "access denied / legacy model"
        elif "parse" in msg or "schema" in msg or "json" in msg:
            k = "invalid output (JSON/schema)"
        elif "keyerror" in msg or "text" in msg:
            k = "unexpected response format"
        elif "throttl" in msg:
            k = "throttled"
        else:
            k = "inference error"
        kinds[k] = kinds.get(k, 0) + 1
    top = max(kinds.items(), key=lambda kv: kv[1])
    return f"{top[0]} ({top[1]}/{len(fails)} calls)"


def _run_warnings(metrics, dataset_report, best_overall, per_model) -> list[str]:
    warns = []
    dr = dataset_report or {}
    sampled = dr.get("sampled", 0)
    if sampled and sampled < 20:
        warns.append(f"Small sample: only {sampled} applications were sampled across all groups.")
    if best_overall:
        n = per_model[best_overall].get("n") or 0
        if n < LOW_CONFIDENCE_N:
            warns.append(
                f"Low confidence: the recommended model produced only {n} valid comparable "
                f"result(s). Treat rankings as directional, not conclusive.")
    n_failed_sheets = sum(1 for s in dr.get("score_sheets", []) if not s.get("included"))
    if n_failed_sheets:
        warns.append(f"{n_failed_sheets} score sheet(s) were excluded (missing join key or columns).")
    # models with zero valid outputs
    zero = [mid for mid, m in per_model.items() if (m.get("n") or 0) == 0]
    if zero:
        warns.append(f"{len(zero)} model(s) produced no valid comparable outputs and were "
                     f"moved out of the ranking.")
    return warns


def _examples(per_model, best_overall) -> dict:
    """Pick close / overscoring / underscoring examples from the recommended model
    (or any usable model with rows)."""
    rows = []
    if best_overall and per_model.get(best_overall, {}).get("rows"):
        rows = per_model[best_overall]["rows"]
        src = best_overall
    else:
        src = None
        for mid, m in per_model.items():
            if m.get("rows"):
                rows = m["rows"]
                src = mid
                break
    if not rows:
        return {}

    close = min(rows, key=lambda r: abs(r["error"]))
    over = max(rows, key=lambda r: r["error"])   # model - human, most positive
    under = min(rows, key=lambda r: r["error"])  # most negative
    out = {"source_model": src, "close": close}
    if over["error"] > 0:
        out["overscoring"] = over
    if under["error"] < 0:
        out["underscoring"] = under
    return out
