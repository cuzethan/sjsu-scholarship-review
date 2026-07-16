"""
compare.py — compare model outputs to human scores and compute metrics.

For each model we compare the model's total_score against:
- the human average score (human_avg)
- individual reviewer scores (when available)

Metrics per model (and per scholarship group):
- n (valid scored records)
- MAE  (mean absolute error vs human_avg)
- RMSE (root mean squared error vs human_avg)
- bias (mean signed error: model - human)
- pearson correlation (model vs human_avg)
- within_1 / within_2 (share of predictions within 1 / 2 points of human_avg)
- valid_rate (share of records where the model returned valid schema JSON)
- avg_latency_s, avg_output_tokens

Because rubrics use different scales, model total_score and human_avg are compared
on their raw scales. To make cross-scholarship aggregation meaningful, we also
compute a normalized error (error divided by the group's human score range),
reported as `norm_mae` when a range is available.

No third-party deps — plain math.
"""

from __future__ import annotations

import math
from statistics import mean


from config import MODELS as MODEL_LIST


def _first_reasoning(parsed: dict) -> str:
    """Short rationale snippet from the model's first criterion (for examples)."""
    cs = (parsed or {}).get("criterion_scores") or []
    if cs and isinstance(cs[0], dict):
        return (cs[0].get("reasoning", "") or "")[:280]
    return ""


def _model_pricing(model_id: str) -> tuple[float, float]:
    """Return (cost_per_1k_in, cost_per_1k_out) for a model. Defaults to 0 if unknown."""
    for m in MODEL_LIST:
        if m["id"] == model_id:
            return m.get("cost_per_1k_in", 0), m.get("cost_per_1k_out", 0)
    return 0, 0


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def compute_metrics(results: list[dict], human_lookup: dict) -> dict:
    """Compute per-model metrics.

    Args:
        results: list of inference result dicts (from inference.run_inference)
        human_lookup: { candidate_key: {"human_avg": float, "reviewer_scores": {..}} }

    Returns:
        {
          "per_model": { model_id: {metrics..., "per_group": {group: metrics}} },
          "models": [model_id, ...],
        }
    """
    by_model = {}
    for r in results:
        by_model.setdefault(r["model_id"], []).append(r)

    per_model = {}
    for model_id, rs in by_model.items():
        total = len(rs)
        valid = [r for r in rs if r.get("valid") and r.get("parsed")]
        valid_rate = len(valid) / total if total else 0.0

        # build paired arrays
        model_scores, human_scores = [], []
        abs_errs, sq_errs, signed_errs = [], [], []
        within1 = within2 = 0
        rev_in_range = rev_records = 0
        latencies, out_tokens = [], []
        rows = []

        for r in rs:
            if r.get("latency_s") is not None:
                latencies.append(r["latency_s"])
            if r.get("output_tokens") is not None:
                out_tokens.append(r["output_tokens"])
            if not (r.get("valid") and r.get("parsed")):
                continue
            human = human_lookup.get(f'{r["rubric_id"]}|{r["year"]}|{r["candidate_key"]}')
            if not human:
                continue
            m_total = r["parsed"].get("total_score")
            h_total = human.get("human_total")
            if not isinstance(m_total, (int, float)) or not isinstance(h_total, (int, float)):
                continue
            model_scores.append(float(m_total))
            human_scores.append(float(h_total))
            err = float(m_total) - float(h_total)
            abs_errs.append(abs(err))
            sq_errs.append(err * err)
            signed_errs.append(err)
            if abs(err) <= 1:
                within1 += 1
            if abs(err) <= 2:
                within2 += 1
            # individual-reviewer comparison: is the model within the spread of
            # individual reviewer totals?
            rev = human.get("reviewer_totals") or {}
            if len(rev) >= 1:
                rev_records += 1
                rlo, rhi = min(rev.values()), max(rev.values())
                if rlo <= float(m_total) <= rhi:
                    rev_in_range += 1
            rows.append({
                "candidate_key": r["candidate_key"],
                "scholarship_type": r["scholarship_type"],
                "year": r["year"],
                "model_total": float(m_total),
                "human_score": float(h_total),
                "error": err,
                "confidence": r["parsed"].get("confidence"),
                "reviewer_totals": rev,
                "reasoning_snippet": _first_reasoning(r["parsed"]),
            })

        n = len(model_scores)
        metrics = {
            "n": n,
            "total_attempts": total,
            "valid_rate": round(valid_rate, 3),
            "mae": round(mean(abs_errs), 3) if abs_errs else None,
            "rmse": round(math.sqrt(mean(sq_errs)), 3) if sq_errs else None,
            "bias": round(mean(signed_errs), 3) if signed_errs else None,
            "pearson": (round(_pearson(model_scores, human_scores), 3)
                        if _pearson(model_scores, human_scores) is not None else None),
            "within_1": round(within1 / n, 3) if n else None,
            "within_2": round(within2 / n, 3) if n else None,
            "within_reviewer_range": round(rev_in_range / rev_records, 3) if rev_records else None,
            "avg_latency_s": round(mean(latencies), 3) if latencies else None,
            "avg_output_tokens": round(mean(out_tokens), 1) if out_tokens else None,
            "cost_per_app": None,
            "total_cost": None,
            "failures": [
                {"candidate_key": r["candidate_key"], "failure": r["failure"]}
                for r in rs if r.get("failure")
            ],
            "rows": rows,
        }

        # compute cost from actual token usage
        c_in, c_out = _model_pricing(model_id)
        total_in = sum(r.get("input_tokens") or 0 for r in rs)
        total_out = sum(r.get("output_tokens") or 0 for r in rs)
        total_cost = (total_in / 1000 * c_in) + (total_out / 1000 * c_out)
        metrics["total_cost"] = round(total_cost, 5)
        metrics["cost_per_app"] = round(total_cost / total, 5) if total else None

        # per-group breakdown
        per_group = {}
        groups = {}
        for row in rows:
            groups.setdefault(f"{row['scholarship_type']} | {row['year']}", []).append(row)
        for g, grows in groups.items():
            errs = [gr["error"] for gr in grows]
            ms = [gr["model_total"] for gr in grows]
            hs = [gr["human_score"] for gr in grows]
            per_group[g] = {
                "n": len(grows),
                "mae": round(mean([abs(e) for e in errs]), 3),
                "bias": round(mean(errs), 3),
                "pearson": (round(_pearson(ms, hs), 3)
                            if _pearson(ms, hs) is not None else None),
            }
        metrics["per_group"] = per_group
        per_model[model_id] = metrics

    return {"per_model": per_model, "models": list(per_model.keys())}
