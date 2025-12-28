#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


JsonObject = Dict[str, Any]
JsonArray = List[Any]


def _load_json(path: Path) -> Union[JsonObject, JsonArray]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data


def _get(d: Dict[str, Any], key: str) -> Optional[float]:
    cur: Any = d
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur.get(part)
    try:
        if cur is None:
            return None
        return float(cur)
    except Exception:
        return None


@dataclass
class Entry:
    label: str
    path: str
    data: Dict[str, Any]


def _pct(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%"


def _ms(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    return f"{v:.0f}ms"


def _num(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    try:
        if abs(v - round(v)) < 1e-9:
            return str(int(round(v)))
    except Exception:
        pass
    return f"{v:.3f}"


def _derive_uncertain_rate(summary: Dict[str, Any]) -> Optional[float]:
    v = summary.get("verdicts")
    if not isinstance(v, dict):
        return None
    try:
        correct = float(v.get("correct_total") or 0)
        incorrect = float(v.get("incorrect_total") or 0)
        uncertain = float(v.get("uncertain_total") or 0)
        total = correct + incorrect + uncertain
        if total <= 0:
            return None
        return uncertain / total
    except Exception:
        return None


def _collect_top_from_metrics(metrics_items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Accepts metrics.json list items from either:
      - scripts/collect_replay_metrics.py (offline)
      - homework_agent/scripts/collect_metrics.py (live)
    and returns best-effort top lists for reporting.
    """
    failed = [m for m in metrics_items if str(m.get("status") or "").lower() not in {"ok", "done"}]
    top_failed = failed[:10]

    def _float(v: Any) -> float:
        try:
            return float(v)
        except Exception:
            return 0.0

    top_slow = sorted(metrics_items, key=lambda m: _float(m.get("duration_ms")), reverse=True)[:10]
    top_iter = sorted(metrics_items, key=lambda m: _float(m.get("iterations")), reverse=True)[:10]
    top_tokens = sorted(metrics_items, key=lambda m: _float(m.get("tokens_total")), reverse=True)[:10]

    return {
        "top_failed": top_failed,
        "top_slow": top_slow,
        "top_iter": top_iter,
        "top_tokens": top_tokens,
    }


def _render_kv_table(items: List[Dict[str, Any]], *, columns: List[Tuple[str, str]]) -> str:
    if not items:
        return "<p class=\"meta\">n/a</p>"
    rows = []
    for it in items:
        tds = []
        for key, label in columns:
            val = it.get(key)
            if val is None:
                tds.append("<td>n/a</td>")
            else:
                safe = json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else str(val)
                if len(safe) > 200:
                    safe = safe[:200] + "…"
                tds.append(f"<td><code>{safe}</code></td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    head = "".join(f"<th>{label}</th>" for _, label in columns)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _render_html(entries: List[Entry]) -> str:
    rows: List[str] = []
    for e in entries:
        sr = _get(e.data, "success_rate")
        p95 = _get(e.data, "latency.p95_ms")
        it = _get(e.data, "iterations.avg")
        total = _get(e.data, "total_samples")
        mode = str(e.data.get("metrics_mode") or "")
        unc = _derive_uncertain_rate(e.data)
        tokens_total = _get(e.data, "tokens.total")
        needs_review_rate = _get(e.data, "needs_review_rate")

        it_cell = f"{it:.2f}" if it is not None else "n/a"
        rows.append(
            "<tr>"
            f"<td><code>{e.label}</code></td>"
            f"<td><code>{mode or 'n/a'}</code></td>"
            f"<td>{int(total) if total is not None else 'n/a'}</td>"
            f"<td>{_pct(sr)}</td>"
            f"<td>{_pct(unc)}</td>"
            f"<td>{_ms(p95)}</td>"
            f"<td>{it_cell}</td>"
            f"<td>{_num(tokens_total)}</td>"
            f"<td>{_pct(needs_review_rate)}</td>"
            "</tr>"
        )

    def _trend(key: str) -> Tuple[Optional[float], Optional[float]]:
        if not entries:
            return None, None
        first = _get(entries[0].data, key)
        last = _get(entries[-1].data, key)
        return first, last

    sr0, sr1 = _trend("success_rate")
    p950, p951 = _trend("latency.p95_ms")
    it0, it1 = _trend("iterations.avg")
    tok0, tok1 = _trend("tokens.total")

    def _delta(a: Optional[float], b: Optional[float], *, kind: str) -> str:
        if a is None or b is None:
            return "n/a"
        if kind == "pct":
            return f"{(b - a) * 100:+.1f}%"
        if kind == "ms":
            return f"{(b - a):+.0f}ms"
        return f"{(b - a):+.3f}"

    return f"""\
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Agent Weekly Report</title>
    <style>
      body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 24px; }}
      h1 {{ margin: 0 0 8px 0; }}
      .meta {{ color: #666; margin: 0 0 20px 0; }}
      .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-bottom: 16px; }}
      .card {{ border: 1px solid #eee; border-radius: 10px; padding: 14px; }}
      .k {{ color: #666; font-size: 12px; }}
      .v {{ font-size: 18px; font-weight: 600; margin-top: 4px; }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{ padding: 10px; border-bottom: 1px solid #eee; text-align: left; vertical-align: top; }}
      th {{ color: #666; font-weight: 600; font-size: 12px; }}
      code {{ background: #fafafa; border: 1px solid #eee; padding: 1px 6px; border-radius: 6px; }}
    </style>
  </head>
  <body>
    <h1>Agent Weekly Report</h1>
    <p class="meta">Inputs: {len(entries)} summary file(s)</p>
    <div class="cards">
      <div class="card"><div class="k">Success Rate Δ (first→last)</div><div class="v">{_delta(sr0, sr1, kind="pct")}</div></div>
      <div class="card"><div class="k">Latency P95 Δ (first→last)</div><div class="v">{_delta(p950, p951, kind="ms")}</div></div>
      <div class="card"><div class="k">Iterations Avg Δ (first→last)</div><div class="v">{_delta(it0, it1, kind="num")}</div></div>
      <div class="card"><div class="k">Tokens Total Δ (first→last)</div><div class="v">{_delta(tok0, tok1, kind="num")}</div></div>
    </div>
    <table>
      <thead>
        <tr>
          <th>Label</th>
          <th>Mode</th>
          <th>Total</th>
          <th>Success Rate</th>
          <th>Uncertain Rate</th>
          <th>Latency P95</th>
          <th>Iterations Avg</th>
          <th>Tokens Total</th>
          <th>Needs Review Rate</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an HTML weekly report from multiple metrics_summary.json files.")
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="Input paths or globs (e.g. qa_metrics/*_summary.json).",
    )
    parser.add_argument(
        "--metrics",
        nargs="*",
        default=[],
        help="Optional metrics.json paths/globs for top lists (offline or live).",
    )
    parser.add_argument("--output", required=True, help="Output HTML path.")
    args = parser.parse_args()

    paths: List[Path] = []
    for it in args.inputs:
        expanded = [Path(p) for p in glob.glob(it)]
        if expanded:
            paths.extend(expanded)
        else:
            paths.append(Path(it))

    entries: List[Entry] = []
    for p in sorted(set(paths)):
        data_any = _load_json(p)
        if not isinstance(data_any, dict):
            raise ValueError(f"Expected JSON object summary: {p}")
        data = data_any
        label = p.stem
        entries.append(Entry(label=label, path=p.as_posix(), data=data))

    if not entries:
        print("[FAIL] no inputs")
        return 2

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = _render_html(entries)

    # Optional: add top lists section if metrics are provided.
    metric_paths: List[Path] = []
    for it in args.metrics:
        expanded = [Path(p) for p in glob.glob(it)]
        metric_paths.extend(expanded or [Path(it)])
    metric_items: List[Dict[str, Any]] = []
    for mp in sorted({p for p in metric_paths if p.exists()}):
        data_any = _load_json(mp)
        if isinstance(data_any, list):
            for x in data_any:
                if isinstance(x, dict):
                    metric_items.append(x)
    if metric_items:
        tops = _collect_top_from_metrics(metric_items)
        extra = (
            "<hr/>"
            "<h2>Top Lists (from metrics.json)</h2>"
            "<h3>Top Failed</h3>"
            + _render_kv_table(tops["top_failed"], columns=[("sample_id", "sample_id/file"), ("status", "status"), ("error", "error")])
            + "<h3>Top Slow (duration_ms)</h3>"
            + _render_kv_table(tops["top_slow"], columns=[("file", "file"), ("sample_id", "sample_id"), ("duration_ms", "duration_ms"), ("status", "status")])
            + "<h3>Top Iterations</h3>"
            + _render_kv_table(tops["top_iter"], columns=[("file", "file"), ("sample_id", "sample_id"), ("iterations", "iterations"), ("status", "status")])
            + "<h3>Top Tokens</h3>"
            + _render_kv_table(tops["top_tokens"], columns=[("file", "file"), ("sample_id", "sample_id"), ("tokens_total", "tokens_total"), ("status", "status")])
        )
        html = html.replace("</body>", extra + "</body>")

    out.write_text(html, encoding="utf-8")
    print(f"[OK] report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
