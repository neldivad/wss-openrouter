#!/usr/bin/env python3
"""Render charts from derived/observations/*.csv as SVG.

    python examples/visualize.py

  task-mix.svg   what people ask models to DO, by share of tokens — the
                 composition of demand rather than a model popularity chart

Reads the derived table, never the raw archive. Stdlib only, deterministic.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "examples" / "charts"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
HUE = "#2a78d6"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

MACRO_LABEL = {"code": "Code", "agent": "Agent", "data": "Data", "general": "General"}


def load(metric: str, prefix: str, exclude_composite: bool = True):
    rows = []
    for partition in sorted((REPO / "derived" / "observations").glob("*.csv")):
        with partition.open(encoding="utf-8", newline="") as fh:
            rows.extend(
                r for r in csv.DictReader(fh)
                if r["metric"] == metric and r["entity_id"].startswith(prefix)
            )
    if not rows:
        return [], ""
    latest = max(r["observed_at"] for r in rows)
    out = []
    for r in rows:
        if r["observed_at"] != latest:
            continue
        name = r["entity_id"][len(prefix):]
        if exclude_composite and "/" in name:
            continue
        out.append((name, float(r["value"])))
    return sorted(out, key=lambda kv: (-kv[1], kv[0])), latest[:10]


def svg_text(x, y, text, *, size, fill, anchor="start", weight="normal", tabular=False) -> str:
    style = "font-variant-numeric: tabular-nums;" if tabular else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family=\'{FONT}\' font-size="{size}" '
        f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}" style="{style}">{escape(text)}</text>'
    )


def pretty(tag: str) -> str:
    macro, _, rest = tag.partition(":")
    if not rest:
        macro, rest = "", tag
    words = rest.replace("_", " ")
    label = words[:1].upper() + words[1:]
    return f"{MACRO_LABEL.get(macro, macro.title())} · {label}" if macro else label


def task_mix(out: Path, top_n: int = 15) -> str:
    tasks, as_of = load("token_share", "task:")
    macros, _ = load("token_share", "macro:")
    if not tasks:
        return "task-mix.svg skipped: no classification observations yet"

    top = tasks[:top_n]
    width, left, right, top_pad = 900.0, 268.0, 96.0, 90.0
    bar_h, gap = 16.0, 8.0
    height = top_pad + len(top) * (bar_h + gap) + 36
    vmax = top[0][1]
    span = width - left - right

    macro_line = " · ".join(f"{MACRO_LABEL.get(k, k)} {v * 100:.0f}%" for k, v in macros)
    body = [
        svg_text(24, 30, "What people actually ask models to do", size=16, fill=INK, weight="600"),
        svg_text(
            24, 50,
            f"share of tokens on OpenRouter by task · trailing 7 days to {as_of}",
            size=12, fill=INK2,
        ),
        svg_text(24, 70, macro_line, size=12, fill=INK2, weight="600"),
    ]
    body.append(f'<line x1="{left}" y1="{top_pad - 10}" x2="{left}" y2="{height - 32}" stroke="{BASELINE}" stroke-width="1"/>')
    tick = 0.0
    while tick <= vmax:
        gx = left + tick / vmax * span
        body.append(f'<line x1="{gx:.1f}" y1="{top_pad - 10}" x2="{gx:.1f}" y2="{height - 32}" stroke="{GRID}" stroke-width="1"/>')
        body.append(svg_text(gx, height - 18, f"{tick * 100:.0f}%", size=10, fill=MUTED, anchor="middle", tabular=True))
        tick += 0.05

    for i, (tag, share) in enumerate(top):
        y = top_pad + i * (bar_h + gap)
        w = max(1.5, share / vmax * span)
        r = min(4, w / 2, bar_h / 2)
        body.append(
            f'<path d="M{left:.1f},{y:.1f} h{w - r:.1f} q{r},0 {r},{r} v{bar_h - 2 * r:.1f} '
            f'q0,{r} -{r},{r} h-{w - r:.1f} z" fill="{HUE}"/>'
        )
        label = pretty(tag)
        body.append(svg_text(left - 10, y + bar_h - 4, label[:38], size=11, fill=INK2, anchor="end"))
        body.append(svg_text(left + w + 7, y + bar_h - 4, f"{share * 100:.1f}%", size=11, fill=INK, weight="600", tabular=True))

    body.append(
        svg_text(24, height - 4, f"Source: OpenRouter (openrouter.ai/rankings), as of {as_of}. Licensed under CC BY 4.0.", size=10, fill=MUTED)
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="What people actually ask models to do">\n'
        f"<title>What people actually ask models to do</title>\n"
        f"<desc>Ranked bar chart of OpenRouter token share by task classification.</desc>\n"
        f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>\n' + "\n".join(body) + "\n</svg>\n"
    )
    out.write_text(svg, encoding="utf-8")
    return f"{out.relative_to(REPO)} — {len(top)} of {len(tasks)} tasks"


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(task_mix(OUT_DIR / "task-mix.svg"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
