"""
report.py — narrative decision dashboard for the model evaluation.

Single self-contained HTML artifact. Uses Chart.js (via CDN) for readable,
interactive charts (cost-vs-accuracy, latency-vs-accuracy, within-1, valid rate,
per-scholarship MAE). All text uses ASCII/HTML entities so UTF-8 renders cleanly.

Page flow:
  1. Header / run metadata
  2. Run-health warnings
  3. Executive recommendation (cards + why)
  4. Decision matrix (verdict per model)
  5. Key charts
  6. Usable model leaderboard
  7. Failed / unavailable models
  8. Metric glossary (plain English)
  9. Data coverage & exclusions
 10. Example comparisons
 11. Detailed model breakdowns (collapsible)
 12. Technical appendix (collapsible)

Assumption: "per-criterion MAE" is not reliably computable because model criterion
names and human score-sheet column names don't align 1:1; we show per-scholarship
MAE instead (well-supported by the metrics) and label it as such.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from recommendation import build_recommendation

CHARTJS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"


def _esc(x) -> str:
    return html.escape(str(x)) if x is not None else "n/a"


def _usd(v) -> str:
    return f"${v:.4f}" if isinstance(v, (int, float)) else "n/a"


def _num(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else "n/a"


# ---------- sections ----------

def _health(reco: dict) -> str:
    warns = reco.get("warnings", [])
    if not warns:
        return ('<div class="banner ok">Run health: no major caveats detected for this run.</div>')
    items = "".join(f"<li>{_esc(w)}</li>" for w in warns)
    return (f'<div class="banner warn"><b>Run health &mdash; read before trusting the numbers</b>'
            f'<ul>{items}</ul></div>')


def _reco_cards(reco: dict) -> str:
    def card(title, c, extra=""):
        if not c:
            return (f'<div class="card"><div class="card-t">{title}</div>'
                    f'<div class="card-v">None</div><div class="muted">no usable model</div></div>')
        sub = []
        if c.get("mae") is not None:
            sub.append(f"MAE {_num(c['mae'])}")
        if c.get("cost_per_app") is not None:
            sub.append(f"{_usd(c['cost_per_app'])}/app")
        if c.get("avg_latency_s") is not None:
            sub.append(f"{_num(c['avg_latency_s'])}s")
        return (f'<div class="card"><div class="card-t">{title}</div>'
                f'<div class="card-v">{_esc(c["label"])}</div>'
                f'<div class="muted">{" &middot; ".join(sub)}{extra}</div></div>')

    rec = reco.get("recommended")
    why = reco.get("recommended_why")
    why_html = (f'<div class="why"><b>Why:</b> {_esc(why)}</div>' if why else "")
    return (
        '<div class="cards">'
        + card("Recommended model", rec)
        + card("Best low-cost usable", reco.get("cheapest"))
        + card("Fastest usable", reco.get("fastest"))
        + "</div>" + why_html
    )


def _decision_matrix(reco: dict) -> str:
    rows = []
    for d in reco.get("decision_matrix", []):
        vclass = {
            "Best overall": "v-best", "Best low-cost option": "v-cheap",
            "Too inaccurate": "v-bad", "Failed in this run": "v-fail",
            "Not currently usable": "v-fail",
        }.get(d["verdict"], "")
        reason = d.get("reason")
        note = f'<div class="muted">{_esc(reason)}</div>' if reason else ""
        rows.append(
            f"<tr><td><b>{_esc(d['label'])}</b><div class='mono muted'>{_esc(d['model_id'])}</div></td>"
            f"<td>{_esc(d['accuracy'])}</td>"
            f"<td>{_usd(d['cost_per_app']) if d['cost_per_app'] is not None else 'n/a'}</td>"
            f"<td>{_num(d['avg_latency_s']) if d['avg_latency_s'] is not None else 'n/a'}</td>"
            f"<td>{_esc(d['reliability'])}</td>"
            f"<td class='{vclass}'>{_esc(d['verdict'])}{note}</td></tr>"
        )
    return (
        '<table class="matrix"><thead><tr><th>Model</th><th>Accuracy</th><th>Cost</th>'
        '<th>Speed</th><th>Reliability</th><th>Verdict</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def _leaderboard(per_model: dict, usable_ids: list[str], labels: dict) -> str:
    cols = [("mae", "MAE"), ("rmse", "RMSE"), ("bias", "Bias"), ("pearson", "Corr"),
            ("within_1", "Within &plusmn;1"), ("within_2", "Within &plusmn;2"),
            ("within_reviewer_range", "In reviewer range"), ("valid_rate", "Valid rate"),
            ("avg_latency_s", "Latency (s)"), ("avg_output_tokens", "Out tok"),
            ("cost_per_app", "$/app"), ("total_cost", "Total $"), ("n", "n")]
    head = "".join(f"<th>{h}</th>" for _, h in cols)
    body = []
    for rank, mid in enumerate(usable_ids, 1):
        m = per_model[mid]
        cells = [f"<td>{rank}</td>",
                 f"<td><b>{_esc(labels.get(mid, mid))}</b></td>"]
        for key, _ in cols:
            v = m.get(key)
            if key in ("cost_per_app", "total_cost"):
                cells.append(f"<td>{_usd(v) if v is not None else 'n/a'}</td>")
            else:
                cells.append(f"<td>{_esc(v)}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    if not body:
        return "<p><em>No usable models in this run.</em></p>"
    return (f'<table><thead><tr><th>#</th><th>Model</th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def _failed(reco: dict) -> str:
    failed = reco.get("failed", [])
    if not failed:
        return "<p><em>No failed or unavailable models.</em></p>"
    rows = "".join(
        f"<tr><td><b>{_esc(f['label'])}</b><div class='mono muted'>{_esc(f['model_id'])}</div></td>"
        f"<td>{_esc(f['kind'])}</td><td>{_esc(f['reason'])}</td></tr>"
        for f in failed
    )
    return ('<table><thead><tr><th>Model</th><th>Type</th><th>Reason</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


GLOSSARY = [
    ("MAE", "Average gap between the model's total score and the human total score (lower is better)."),
    ("RMSE", "Like MAE but punishes big misses more heavily (lower is better)."),
    ("Bias", "Whether the model tends to score higher (+) or lower (-) than humans overall."),
    ("Correlation", "How well the model's ranking of applicants tracks the humans' ranking (1.0 = perfect)."),
    ("Within &plusmn;1 / &plusmn;2", "Share of applications where the model's total was within 1 (or 2) points of the human total."),
    ("In reviewer range", "Share of applications where the model's score fell between the lowest and highest individual human reviewer."),
    ("Valid output rate", "Share of calls where the model returned correctly-formatted JSON that matched the required schema."),
    ("$/app", "Estimated Bedrock cost to score one application with this model."),
]


def _glossary() -> str:
    items = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in GLOSSARY)
    return f'<dl class="glossary">{items}</dl>'


def _coverage(dr: dict) -> str:
    def li(label, val):
        return f"<li><span class='big'>{_esc(val)}</span> {label}</li>"
    counts = (
        '<ul class="counts">'
        + li("applications parsed", dr.get("applications_parsed"))
        + li("human score candidates loaded", dr.get("score_candidates_loaded"))
        + li("joined (valid 1:1)", dr.get("joined"))
        + li("sampled for evaluation", dr.get("sampled"))
        + "</ul>"
    )
    # score sheets
    sheets = dr.get("score_sheets", [])
    srows = "".join(
        f"<tr><td>{_esc(s['file'])}</td>"
        f"<td>{'included' if s.get('included') else 'EXCLUDED'}</td>"
        f"<td class='mono'>{_esc(s.get('candidate_col'))}</td>"
        f"<td>{_esc(len(s.get('criterion_cols', [])))}</td>"
        f"<td>{_esc(s.get('reason'))}</td></tr>"
        for s in sheets
    )
    sheet_tbl = (
        "<h3>Score sheets</h3><table><thead><tr><th>File</th><th>Status</th>"
        "<th>Candidate col</th><th># criteria</th><th>Reason (if excluded)</th>"
        f"</tr></thead><tbody>{srows}</tbody></table>" if sheets else ""
    )
    bg = dr.get("by_group", {})
    grows = "".join(f"<tr><td>{_esc(g)}</td><td>{_esc(v['joined'])}</td>"
                    f"<td>{_esc(v['sampled'])}</td></tr>" for g, v in sorted(bg.items()))
    group_tbl = (
        "<h3>Included scholarship / year groups</h3><table><thead><tr><th>Group</th>"
        "<th>Joined</th><th>Sampled</th></tr></thead>"
        f"<tbody>{grows}</tbody></table>" if bg else ""
    )
    return counts + sheet_tbl + group_tbl


def _examples(reco: dict) -> str:
    ex = reco.get("examples", {})
    if not ex:
        return "<p><em>No example cases available.</em></p>"
    src = ex.get("source_model")
    blocks = [f'<p class="muted">Examples from model: <span class="mono">{_esc(src)}</span></p>']

    def block(title, r, kind):
        if not r:
            return ""
        rev = r.get("reviewer_totals") or {}
        rev_str = ", ".join(f"{_esc(k)}: {_esc(v)}" for k, v in rev.items()) or "n/a"
        snip = r.get("reasoning_snippet") or ""
        snip_html = f'<div class="snip">&ldquo;{_esc(snip)}&rdquo;</div>' if snip else ""
        return (
            f'<div class="ex ex-{kind}"><div class="ex-t">{title}</div>'
            f"<div><b>{_esc(r['scholarship_type'])}</b> ({_esc(r['year'])}) &middot; "
            f"<span class='mono'>{_esc(r['candidate_key'])}</span></div>"
            f"<div>Human total: <b>{_num(r['human_score'])}</b> &middot; "
            f"Model total: <b>{_num(r['model_total'])}</b> &middot; "
            f"Error: <b>{_num(r['error'])}</b></div>"
            f"<div class='muted'>Individual reviewers: {rev_str}</div>{snip_html}</div>"
        )
    blocks.append(block("Close agreement", ex.get("close"), "close"))
    blocks.append(block("Model overscored vs humans", ex.get("overscoring"), "over"))
    blocks.append(block("Model underscored vs humans", ex.get("underscoring"), "under"))
    return '<div class="examples">' + "".join(blocks) + "</div>"


def _model_details(per_model: dict, usable_ids: list[str], labels: dict) -> str:
    parts = []
    for mid in usable_ids:
        m = per_model[mid]
        pg = m.get("per_group", {})
        pg_rows = "".join(
            f"<tr><td>{_esc(g)}</td><td>{_esc(v['n'])}</td><td>{_esc(v['mae'])}</td>"
            f"<td>{_esc(v['bias'])}</td><td>{_esc(v['pearson'])}</td></tr>"
            for g, v in sorted(pg.items())
        )
        pg_tbl = (
            "<table><thead><tr><th>Scholarship | Year</th><th>n</th><th>MAE</th><th>Bias</th>"
            f"<th>Corr</th></tr></thead><tbody>{pg_rows}</tbody></table>" if pg else ""
        )
        fails = m.get("failures", [])
        fail_html = ""
        if fails:
            items = "".join(f"<li class='mono'>{_esc(f['candidate_key'])}: {_esc(f['failure'])}</li>"
                            for f in fails[:20])
            more = f"<li>... and {len(fails)-20} more</li>" if len(fails) > 20 else ""
            fail_html = f"<details><summary>Failures ({len(fails)})</summary><ul>{items}{more}</ul></details>"
        parts.append(
            f'<details class="mcard"><summary><b>{_esc(labels.get(mid, mid))}</b> '
            f'&mdash; MAE {_esc(m.get("mae"))}, valid {_esc(m.get("valid_rate"))}, '
            f'{_usd(m.get("cost_per_app")) if m.get("cost_per_app") is not None else "n/a"}/app</summary>'
            f'{pg_tbl}{fail_html}</details>'
        )
    return "".join(parts) if parts else "<p><em>No usable models.</em></p>"


# ---------- charts (Chart.js) ----------

def _charts_payload(per_model: dict, usable_ids: list[str], labels: dict) -> dict:
    models = []
    for mid in usable_ids:
        m = per_model[mid]
        models.append({
            "label": labels.get(mid, mid),
            "mae": m.get("mae"), "cost": m.get("cost_per_app"),
            "latency": m.get("avg_latency_s"), "within1": m.get("within_1"),
            "valid": m.get("valid_rate"),
        })
    # per-scholarship MAE (grouped): groups x models
    groups = sorted({g for mid in usable_ids for g in per_model[mid].get("per_group", {})})
    per_group = {"groups": groups, "series": []}
    for mid in usable_ids:
        pg = per_model[mid].get("per_group", {})
        per_group["series"].append({
            "label": labels.get(mid, mid),
            "data": [pg.get(g, {}).get("mae") for g in groups],
        })
    return {"models": models, "per_group": per_group}


def _charts_html() -> str:
    return """
<div class="charts-grid">
  <div class="chartbox"><h3>Cost vs Accuracy <span class="muted">(bottom-left = best)</span></h3>
    <canvas id="costAcc"></canvas></div>
  <div class="chartbox"><h3>Latency vs Accuracy <span class="muted">(bottom-left = best)</span></h3>
    <canvas id="latAcc"></canvas></div>
  <div class="chartbox"><h3>Within &plusmn;1 agreement by model</h3><canvas id="within1"></canvas></div>
  <div class="chartbox"><h3>Valid output rate by model</h3><canvas id="validRate"></canvas></div>
  <div class="chartbox wide"><h3>MAE by scholarship (grouped)</h3><canvas id="perGroup"></canvas></div>
</div>
"""


def _charts_script(payload: dict) -> str:
    data = json.dumps(payload)
    return """
<script>
const P = __DATA__;
const palette = ['#2e7d32','#5b8def','#e6883c','#8e5bd8','#d84b6b','#38a3a5','#b58900','#666'];
function scatter(id, xKey, yKey, xLabel, yLabel) {
  const pts = P.models.filter(m => m[xKey]!=null && m[yKey]!=null)
    .map((m,i)=>({x:m[xKey], y:m[yKey], label:m.label, _c:palette[i%palette.length]}));
  new Chart(document.getElementById(id), {
    type:'scatter',
    data:{datasets:[{data:pts, pointRadius:7, pointHoverRadius:9,
      backgroundColor:pts.map(p=>p._c)}]},
    options:{plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>`${c.raw.label}: (${xLabel} ${c.raw.x}, ${yLabel} ${c.raw.y})`}}},
      scales:{x:{title:{display:true,text:xLabel}},y:{title:{display:true,text:yLabel}}}}
  });
}
function bar(id, key, label) {
  const ms = P.models.filter(m=>m[key]!=null);
  new Chart(document.getElementById(id), {
    type:'bar',
    data:{labels:ms.map(m=>m.label),
      datasets:[{label:label, data:ms.map(m=>m[key]),
        backgroundColor:ms.map((m,i)=>palette[i%palette.length])}]},
    options:{plugins:{legend:{display:false}},
      scales:{y:{beginAtZero:true, max: key==='within1'||key==='valid' ? 1 : undefined}}}
  });
}
if (P.models.length) {
  scatter('costAcc','cost','mae','$/app','MAE');
  scatter('latAcc','latency','mae','latency(s)','MAE');
  bar('within1','within1','Within +/-1');
  bar('validRate','valid','Valid rate');
  const g = P.per_group;
  new Chart(document.getElementById('perGroup'), {
    type:'bar',
    data:{labels:g.groups, datasets:g.series.map((s,i)=>({label:s.label, data:s.data,
      backgroundColor:palette[i%palette.length]}))},
    options:{scales:{y:{beginAtZero:true, title:{display:true,text:'MAE'}}}}
  });
}
</script>
""".replace("__DATA__", data)


# ---------- assembly ----------

def render_report(metrics: dict, dataset_report: dict, resolved_models: list[dict]) -> str:
    per_model = metrics.get("per_model", {})
    labels = {m["id"]: m.get("label", m["id"]) for m in resolved_models}
    reco = build_recommendation(metrics, resolved_models, dataset_report)
    usable_ids = reco.get("usable_ids", [])
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    has_charts = bool(usable_ids)
    charts_block = (_charts_html() if has_charts
                    else "<p><em>No usable models to chart.</em></p>")
    payload = _charts_payload(per_model, usable_ids, labels)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Model Evaluation &mdash; Scholarship Scoring</title>
<script src="{CHARTJS_CDN}"></script>
<style>
  :root {{ --line:#e3e6ee; }}
  body {{ font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
    margin:0; color:#1f2430; background:#f7f8fb; line-height:1.5; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:2rem 1.5rem 4rem; }}
  h1 {{ margin:0 0 .2rem; font-size:1.7rem; }}
  h2 {{ margin:2.2rem 0 .6rem; font-size:1.25rem; border-bottom:2px solid var(--line); padding-bottom:.3rem; }}
  h3 {{ font-size:1rem; margin:.8rem 0 .4rem; }}
  .muted {{ color:#7a8194; font-size:.85em; font-weight:400; }}
  table {{ border-collapse:collapse; width:100%; margin:.5rem 0 1rem; font-size:13px; background:#fff; }}
  th,td {{ border:1px solid var(--line); padding:6px 10px; text-align:left; vertical-align:top; }}
  th {{ background:#eef1f8; }}
  .mono {{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:11px; }}
  .banner {{ padding:.9rem 1.1rem; border-radius:8px; margin:1rem 0; }}
  .banner.ok {{ background:#e8f5e9; border:1px solid #a5d6a7; }}
  .banner.warn {{ background:#fff4e5; border:1px solid #ffcc80; }}
  .banner ul {{ margin:.4rem 0 0 1.1rem; }}
  .cards {{ display:flex; flex-wrap:wrap; gap:1rem; margin:1rem 0; }}
  .card {{ flex:1 1 240px; background:#fff; border:1px solid var(--line); border-radius:10px; padding:1rem 1.2rem; }}
  .card-t {{ font-size:.8rem; text-transform:uppercase; letter-spacing:.04em; color:#7a8194; }}
  .card-v {{ font-size:1.35rem; font-weight:700; margin:.2rem 0; }}
  .why {{ background:#eef4ff; border:1px solid #cfe0ff; border-radius:8px; padding:.7rem 1rem; margin:.4rem 0 0; }}
  .matrix td:last-child {{ font-weight:600; }}
  .v-best {{ color:#1b7f2e; }} .v-cheap {{ color:#1256b8; }}
  .v-bad {{ color:#b26a00; }} .v-fail {{ color:#b0304a; }}
  .charts-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; }}
  .chartbox {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:1rem; }}
  .chartbox.wide {{ grid-column:1 / -1; }}
  canvas {{ max-height:280px; }}
  .counts {{ list-style:none; display:flex; flex-wrap:wrap; gap:1.5rem; padding:0; }}
  .counts .big {{ font-size:1.5rem; font-weight:700; display:block; }}
  .glossary {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:1rem 1.2rem; }}
  .glossary dt {{ font-weight:700; margin-top:.5rem; }} .glossary dd {{ margin:0 0 .3rem; color:#3a4256; }}
  .examples {{ display:flex; flex-wrap:wrap; gap:1rem; }}
  .ex {{ flex:1 1 300px; background:#fff; border:1px solid var(--line); border-left:5px solid #999;
    border-radius:8px; padding:.8rem 1rem; font-size:13px; }}
  .ex-close {{ border-left-color:#2e7d32; }} .ex-over {{ border-left-color:#b26a00; }}
  .ex-under {{ border-left-color:#1256b8; }}
  .ex-t {{ font-weight:700; margin-bottom:.3rem; }}
  .snip {{ margin-top:.4rem; font-style:italic; color:#55607a; }}
  details.mcard {{ background:#fff; border:1px solid var(--line); border-radius:8px;
    padding:.6rem 1rem; margin:.5rem 0; }}
  summary {{ cursor:pointer; }}
</style></head><body><div class="wrap">

<h1>Bedrock Model Evaluation &mdash; Scholarship Scoring</h1>
<div class="muted">Generated {ts} &middot; deterministic inference (temperature=0, top_p=1)
&middot; the model never sees human scores during scoring</div>

{_health(reco)}

<h2>1. Recommendation</h2>
{_reco_cards(reco)}

<h2>2. Decision matrix</h2>
<p class="muted">Verdicts combine accuracy, cost, speed and reliability. Failed/unavailable
models are listed but not ranked on performance.</p>
{_decision_matrix(reco)}

<h2>3. Key charts</h2>
{charts_block}

<h2>4. Usable model leaderboard</h2>
<p class="muted">Only models that produced valid, comparable outputs. Ranked by MAE
vs the human total score (lower is better).</p>
{_leaderboard(per_model, usable_ids, labels)}

<h2>5. Failed / unavailable models</h2>
<p class="muted">Operational issues, not performance results.</p>
{_failed(reco)}

<h2>6. What the metrics mean</h2>
{_glossary()}

<h2>7. Data coverage &amp; exclusions</h2>
{_coverage(dataset_report)}

<h2>8. Example comparisons</h2>
{_examples(reco)}

<h2>9. Detailed model breakdowns</h2>
<p class="muted">Per-scholarship metrics and failure lists. Click to expand.</p>
{_model_details(per_model, usable_ids, labels)}

<details><summary><h2 style="display:inline">10. Technical appendix</h2></summary>
<p class="muted">Raw model availability resolution.</p>
{_appendix(resolved_models)}
</details>

</div>
{_charts_script(payload) if has_charts else ""}
</body></html>"""


def _appendix(resolved_models: list[dict]) -> str:
    rows = []
    for m in resolved_models:
        status = "available" if m.get("available") else "UNAVAILABLE"
        if m.get("substituted"):
            status = f"substituted -> {_esc(m.get('effective_id'))}"
        rows.append(
            f"<tr><td class='mono'>{_esc(m['id'])}</td><td>{_esc(m.get('label'))}</td>"
            f"<td>{status}</td><td>{_esc(m.get('unavailable_reason'))}</td></tr>"
        )
    return ("<table><thead><tr><th>Requested model</th><th>Label</th><th>Status</th>"
            f"<th>Note</th></tr></thead><tbody>{''.join(rows)}</tbody></table>")
