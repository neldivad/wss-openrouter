#!/usr/bin/env python3
"""Render charts from derived/observations/*.csv as SVG.

    python examples/visualize.py

  task-mix.svg          what people ask models to DO, by share of tokens,
                        with the leading model for each workload
  price-capability.svg  cost against benchmark score, with the efficient
                        frontier — what a point of intelligence costs

Reads the derived table, never the raw archive. Stdlib only, deterministic.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
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
HUE_SOFT = "#9ec5f4"
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


def task_leaders() -> dict:
    """Leading model per task, from the task:<tag>/model:<id> rows."""
    per_task = defaultdict(dict)
    for r in _rows():
        e = r["entity_id"]
        if r["metric"] == "tag_token_share" and e.startswith("task:") and "/model:" in e:
            tag, model = e[5:].split("/model:", 1)
            per_task[tag][model] = float(r["value"])
    return {t: max(m.items(), key=lambda kv: kv[1]) for t, m in per_task.items() if m}


def task_mix(out: Path, top_n: int = 15) -> str:
    tasks, as_of = load("token_share", "task:")
    macros, _ = load("token_share", "macro:")
    leaders = task_leaders()
    if not tasks:
        return "task-mix.svg skipped: no classification observations yet"

    top = tasks[:top_n]
    width, left, right, top_pad = 980.0, 250.0, 300.0, 90.0
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
        svg_text(width - right + 96, 70, "leading model · its share of that task", size=10, fill=MUTED, weight="600"),
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
        lead = leaders.get(tag)
        if lead:
            model, lead_share = lead
            body.append(svg_text(
                width - right + 96, y + bar_h - 4,
                f"{model.split('/')[-1][:30]}  {lead_share * 100:.0f}%",
                size=10, fill=MUTED,
            ))

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


def _rows():
    out = []
    for partition in sorted((REPO / "derived" / "observations").glob("*.csv")):
        with partition.open(encoding="utf-8", newline="") as fh:
            out.extend(csv.DictReader(fh))
    return out


def price_capability(out: Path) -> str:
    """Cost against capability, with the efficient frontier drawn.

    Joins two sources on canonical_slug — the catalogue's `id` is an undated
    alias while the benchmarks key on the dated permaslug.
    """
    rows = _rows()
    by = defaultdict(dict)
    for r in rows:
        by[(r["series_id"], r["entity_id"])][r["metric"]] = r["value"]
    catalog = {e: v for (s, e), v in by.items() if s == "openrouter.models.catalog"}
    bench = {e: v for (s, e), v in by.items() if s == "openrouter.benchmarks.artificial-analysis"}
    slug_to_id = {v["canonical_slug"]: e for e, v in catalog.items() if "canonical_slug" in v}

    points = []
    for slug, b in bench.items():
        model_id = slug_to_id.get(slug)
        if not model_id or "intelligence_index" not in b:
            continue
        price = catalog[model_id].get("price_prompt_usd_per_mtok")
        if price is None or float(price) <= 0:
            continue
        points.append((model_id, float(price), float(b["intelligence_index"])))
    if len(points) < 5:
        return "price-capability.svg skipped: too few joined models yet"

    # Frontier: cheapest-first, keep each model that beats every cheaper one.
    frontier = []
    for model_id, price, score in sorted(points, key=lambda t: (t[1], -t[2])):
        if not frontier or score > frontier[-1][2]:
            frontier.append((model_id, price, score))
    frontier_ids = {m for m, _, _ in frontier}

    as_of = max(r["observed_at"] for r in rows if r["metric"] == "intelligence_index")[:10]
    width, height = 940.0, 520.0
    left, right, top, bottom = 62.0, 210.0, 86.0, 56.0
    lo = min(p for _, p, _ in points)
    hi = max(p for _, p, _ in points)
    smin = min(s for _, _, s in points)
    smax = max(s for _, _, s in points)

    def x_of(price):  # log scale: prices span two orders of magnitude
        f = (math.log10(price) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
        return left + f * (width - left - right)

    def y_of(score):
        f = (score - smin) / max(1e-9, smax - smin)
        return (height - bottom) - f * (height - bottom - top)

    body = [
        svg_text(24, 30, "What a point of intelligence costs", size=16, fill=INK, weight="600"),
        svg_text(
            24, 50,
            f"{len(points)} models priced and scored · snapshot {as_of} · "
            "highlighted: the efficient frontier, where nothing is both cheaper and smarter",
            size=12, fill=INK2,
        ),
    ]
    # decade gridlines on price, plain ticks on score
    d = 10 ** math.floor(math.log10(lo))
    while d <= hi * 1.001:
        if d >= lo:
            gx = x_of(d)
            body.append(f'<line x1="{gx:.1f}" y1="{top - 8}" x2="{gx:.1f}" y2="{height - bottom}" stroke="{GRID}" stroke-width="1"/>')
            label = f"${d:g}" if d >= 1 else f"${d:.2f}".rstrip("0").rstrip(".")
            body.append(svg_text(gx, height - bottom + 18, label, size=10, fill=MUTED, anchor="middle", tabular=True))
        d *= 10
    for s in range(int(smin // 10 * 10), int(smax) + 10, 10):
        if smin <= s <= smax:
            gy = y_of(s)
            body.append(f'<line x1="{left}" y1="{gy:.1f}" x2="{width - right}" y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>')
            body.append(svg_text(left - 8, gy + 3.5, str(s), size=10, fill=MUTED, anchor="end", tabular=True))
    body.append(svg_text(left - 8, top - 22, "index", size=10, fill=MUTED, anchor="end"))
    body.append(svg_text((left + width - right) / 2, height - 12, "input price, USD per million tokens (log scale)", size=10, fill=MUTED, anchor="middle"))
    body.append(f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="{BASELINE}" stroke-width="1"/>')

    # frontier line first, so markers sit on top of it
    fpts = " ".join(f"{x_of(p):.1f},{y_of(s):.1f}" for _, p, s in frontier)
    body.append(f'<polyline points="{fpts}" fill="none" stroke="{HUE}" stroke-width="2" stroke-linejoin="round"/>')

    for model_id, price, score in points:
        on = model_id in frontier_ids
        body.append(
            f'<circle cx="{x_of(price):.1f}" cy="{y_of(score):.1f}" r="{5 if on else 4}" '
            f'fill="{HUE if on else HUE_SOFT}" stroke="{SURFACE}" stroke-width="2"/>'
        )

    placed: list[float] = []
    for model_id, price, score in sorted(frontier, key=lambda t: -t[2]):
        x, y = x_of(price), y_of(score)
        label_y = y
        while any(abs(label_y - p) < 13 for p in placed):
            label_y += 13
        placed.append(label_y)
        name = model_id.split("/")[-1]
        body.append(f'<line x1="{x + 7}" y1="{y:.1f}" x2="{x + 13}" y2="{label_y - 3.5:.1f}" stroke="{BASELINE}" stroke-width="1"/>')
        body.append(svg_text(x + 16, label_y + 3.5, f"{name}  ${price:.3g}", size=10, fill=INK, weight="600"))

    body.append(svg_text(24, height - 4, f"Source: OpenRouter (openrouter.ai/rankings), as of {as_of}. Licensed under CC BY 4.0. Scores: Artificial Analysis.", size=9, fill=MUTED))
    out.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="What a point of intelligence costs">\n'
        f"<title>What a point of intelligence costs</title>\n"
        f"<desc>Scatter plot of model benchmark score against input price, with the efficient frontier highlighted.</desc>\n"
        f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>\n' + "\n".join(body) + "\n</svg>\n",
        encoding="utf-8",
    )
    return f"{out.relative_to(REPO)} — {len(points)} models, {len(frontier)} on the frontier"


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(task_mix(OUT_DIR / "task-mix.svg"))
    print(price_capability(OUT_DIR / "price-capability.svg"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
