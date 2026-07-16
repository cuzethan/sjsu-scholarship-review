"""
run_eval.py — orchestrate the full evaluation.

Pipeline:
  1. Build joined dataset from local xlsx (applications + score sheets).
  2. Resolve model availability (mark unavailable, apply alternates).
  3. Run inference (deterministic) across available models x sampled records.
  4. Compute metrics vs human scores.
  5. Write HTML report + JSON artifacts to output/.

Usage:
  python run_eval.py                         # full run
  python run_eval.py --dry-run               # build dataset + resolve models, NO inference
  python run_eval.py --limit 3               # cap records per run (cost control)
  python run_eval.py --models anthropic.claude-sonnet-4-20250514-v1:0
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import (APPLICATIONS_DIR, MODELS, OUTPUT_DIR, SCORES_DIR)


def main():
    ap = argparse.ArgumentParser(description="Bedrock model evaluation harness")
    ap.add_argument("--dry-run", action="store_true",
                    help="Build dataset + resolve models, skip inference")
    ap.add_argument("--limit", type=int, help="Cap total sampled records (cost control)")
    ap.add_argument("--models", nargs="*", help="Subset of model ids to run (default: all in config)")
    args = ap.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Imported here so --help works without boto3/pandas installed
    from dataset_builder import build_dataset
    from inference import resolve_models, run_inference
    from compare import compute_metrics
    from report import render_report

    print("1) Building dataset from local xlsx …")
    records, dataset_report = build_dataset(APPLICATIONS_DIR, SCORES_DIR)
    print(f"   parsed={dataset_report['applications_parsed']} "
          f"candidates={dataset_report['score_candidates_loaded']} "
          f"joined={dataset_report['joined']} sampled={dataset_report['sampled']}")

    if args.limit:
        records = records[:args.limit]
        print(f"   limited to {len(records)} records")

    # human lookup for comparison (kept separate from LLM input), keyed by
    # rubric_id|year|candidate_key to avoid cross-scholarship collisions
    human_lookup = {
        f'{r["rubric_id"]}|{r["year"]}|{r["candidate_key"]}': r["human"]
        for r in records
    }

    model_list = MODELS
    if args.models:
        model_list = [m for m in MODELS if m["id"] in set(args.models)]

    print("2) Resolving model availability …")
    resolved = resolve_models(model_list)
    for m in resolved:
        tag = "OK" if m["available"] else "unavailable"
        if m.get("substituted"):
            tag = f"OK (alt {m['effective_id']})"
        print(f"   [{tag}] {m['id']}")

    (OUTPUT_DIR / "dataset_report.json").write_text(
        json.dumps(dataset_report, indent=2, default=str), encoding="utf-8")

    results = []
    if args.dry_run:
        print("3) --dry-run: skipping inference")
        metrics = {"per_model": {}, "models": []}
    else:
        print("3) Running inference …")
        results = run_inference(resolved, records)
        print(f"   {len(results)} inference results")
        (OUTPUT_DIR / "inference_results.json").write_text(
            json.dumps(results, indent=2, default=str), encoding="utf-8")
        print("4) Computing metrics …")
        metrics = compute_metrics(results, human_lookup)
        (OUTPUT_DIR / "metrics.json").write_text(
            json.dumps(metrics, indent=2, default=str), encoding="utf-8")

    print("5) Writing HTML report …")
    html_doc = render_report(metrics, dataset_report, resolved)
    report_path = OUTPUT_DIR / "report.html"
    report_path.write_text(html_doc, encoding="utf-8")
    print(f"\nDone. Report: {report_path}")


if __name__ == "__main__":
    main()
