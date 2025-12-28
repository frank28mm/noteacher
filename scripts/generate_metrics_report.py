#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def generate_report(*, input_path: str, output_path: str) -> None:
    data = json.loads(Path(input_path).read_text(encoding="utf-8"))

    total_samples = data.get("total_samples", "N/A")
    success_rate = data.get("success_rate")
    latency = data.get("latency") or {}
    iterations = data.get("iterations") or {}

    def pct(v) -> str:
        if v is None:
            return "N/A"
        try:
            return f"{float(v) * 100:.1f}%"
        except Exception:
            return str(v)

    def ms(v) -> str:
        if v is None:
            return "N/A"
        try:
            return f"{float(v):.0f}ms"
        except Exception:
            return str(v)

    html = f"""\
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Agent Metrics Report</title>
    <style>
      body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 24px; }}
      h1 {{ margin: 0 0 8px 0; }}
      .meta {{ color: #666; margin: 0 0 20px 0; }}
      .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
      .card {{ border: 1px solid #eee; border-radius: 10px; padding: 14px; }}
      .k {{ color: #666; font-size: 12px; }}
      .v {{ font-size: 22px; font-weight: 600; margin-top: 4px; }}
      pre {{ background: #fafafa; border: 1px solid #eee; padding: 12px; border-radius: 10px; overflow: auto; }}
    </style>
  </head>
  <body>
    <h1>Agent Metrics Report</h1>
    <p class="meta">Generated from <code>{Path(input_path).as_posix()}</code></p>
    <div class="grid">
      <div class="card"><div class="k">Total Samples</div><div class="v">{total_samples}</div></div>
      <div class="card"><div class="k">Success Rate</div><div class="v">{pct(success_rate)}</div></div>
      <div class="card"><div class="k">Latency P50</div><div class="v">{ms(latency.get("p50_ms"))}</div></div>
      <div class="card"><div class="k">Latency P95</div><div class="v">{ms(latency.get("p95_ms"))}</div></div>
      <div class="card"><div class="k">Iterations Avg</div><div class="v">{iterations.get("avg", "N/A")}</div></div>
      <div class="card"><div class="k">Iterations Max</div><div class="v">{iterations.get("max", "N/A")}</div></div>
    </div>
    <h2>Raw Summary</h2>
    <pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre>
  </body>
</html>
"""
    Path(output_path).write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a minimal HTML report from metrics_summary.json")
    parser.add_argument("--input", required=True, help="Path to metrics_summary.json")
    parser.add_argument("--output", required=True, help="Output HTML path")
    args = parser.parse_args()

    generate_report(input_path=args.input, output_path=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
