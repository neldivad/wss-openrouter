#!/usr/bin/env python3
"""Render charts from derived/observations/*.csv as SVG.

    python examples/visualize.py

  price-capability.svg   cost vs benchmark score. Marker colour = model
                         family, marker area = share of tokens, line = the
                         efficient frontier
  task-mix.svg           what people ask models to do, by share of tokens
  task-leaders.svg       who leads each workload, ranked by their grip on it
  task-contest.svg       workload size against how locked up it is — where
                         the open doors are

Reads the derived table, never the raw archive. Stdlib only, deterministic.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
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
# Scatter is an all-pairs form: only the first three categorical slots stay
# distinguishable under colour-vision deficiency, so at most three families
# are coloured and the rest are deliberately grey.
FAMILY_SLOTS = ("#2a78d6", "#eb6834", "#1baf7a")
FAMILY_OTHER = "#b8b7b0"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

MACRO_LABEL = {"code": "Code", "agent": "Agent", "data": "Data", "general": "General"}


def rows() -> list[dict]:
    out: list[dict] = []
    for partition in sorted((REPO / "derived" / "observations").glob("*.csv")):
        with partition.open(encoding="utf-8", newline="") as fh:
            out.extend(csv.DictReader(fh))
    return out


def latest_by_entity(all_rows, series: str) -> dict:
    """Most recently observed value of every metric, per entity, in one series."""
    seen: dict[tuple[str, str], tuple[str, str]] = {}
    for r in all_rows:
        if r["series_id"] != series:
            continue
        key = (r["entity_id"], r["metric"])
        if key not in seen or r["observed_at"] > seen[key][0]:
            seen[key] = (r["observed_at"], r["value"])
    out: dict[str, dict] = defaultdict(dict)
    for (entity, metric), (_, value) in seen.items():
        out[entity][metric] = value
    return out


def svg_text(x, y, text, *, size, fill, anchor="start", weight="normal", tabular=False) -> str:
    style = "font-variant-numeric: tabular-nums;" if tabular else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family=\'{FONT}\' font-size="{size}" '
        f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}" style="{style}">{escape(text)}</text>'
    )


def wrap(width, height, title, desc, body) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">\n'
        f"<title>{escape(title)}</title>\n<desc>{escape(desc)}</desc>\n"
        f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>\n' + "\n".join(body) + "\n</svg>\n"
    )


def hbar(x, y, w, h, colour, r=4) -> str:
    r = min(r, max(w / 2, 0.1), h / 2)
    return (
        f'<path d="M{x:.1f},{y:.1f} h{w - r:.1f} q{r},0 {r},{r} v{h - 2 * r:.1f} '
        f'q0,{r} -{r},{r} h-{w - r:.1f} z" fill="{colour}"/>'
    )


def short_model(model_id: str) -> str:
    """Drop the org prefix and the -YYYYMMDD stamp; the date is noise here."""
    return re.sub(r"-\d{8}$", "", model_id.split("/")[-1])


def pretty(tag: str) -> str:
    macro, _, rest = tag.partition(":")
    if not rest:
        macro, rest = "", tag
    words = rest.replace("_", " ")
    label = words[:1].upper() + words[1:]
    return f"{MACRO_LABEL.get(macro, macro.title())} · {label}" if macro else label


def cite(as_of: str) -> str:
    return f"Source: OpenRouter (openrouter.ai/rankings), as of {as_of}. Licensed under CC BY 4.0."


# ── task data ────────────────────────────────────────────────────────────────

def task_data(all_rows):
    """(task share, per-task model shares, as_of) from the classifications series."""
    cls = [r for r in all_rows if r["series_id"] == "openrouter.classifications.task"]
    if not cls:
        return {}, {}, ""
    as_of = max(r["observed_at"] for r in cls)
    share, per_task = {}, defaultdict(dict)
    for r in cls:
        if r["observed_at"] != as_of:
            continue
        e = r["entity_id"]
        if e.startswith("task:") and "/model:" in e and r["metric"] == "tag_token_share":
            tag, model = e[5:].split("/model:", 1)
            per_task[tag][model] = float(r["value"])
        elif e.startswith("task:") and "/" not in e and r["metric"] == "token_share":
            share[e[5:]] = float(r["value"])
    return share, per_task, as_of[:10]


def model_volume(all_rows) -> dict:
    """Approximate share of all tokens per model.

    Σ over tasks of (task's share of all tokens × model's share of that task).
    A lower bound: only models listed in a task's top-N contribute, so a model
    spread thinly across many tasks is undercounted.
    """
    share, per_task, _ = task_data(all_rows)
    volume: dict[str, float] = defaultdict(float)
    for tag, models in per_task.items():
        for model, within in models.items():
            volume[model] += share.get(tag, 0.0) * within
    return volume


# ── charts ───────────────────────────────────────────────────────────────────

def price_capability(out: Path, all_rows) -> str:
    catalog = latest_by_entity(all_rows, "openrouter.models.catalog")
    bench = latest_by_entity(all_rows, "openrouter.benchmarks.artificial-analysis")
    slug_to_id = {v["canonical_slug"]: e for e, v in catalog.items() if "canonical_slug" in v}
    volume = model_volume(all_rows)
    # volume is keyed by dated permaslug; catalogue ids are undated aliases
    vol_by_id = {slug_to_id[s]: v for s, v in volume.items() if s in slug_to_id}

    points = []
    for slug, b in bench.items():
        model_id = slug_to_id.get(slug)
        if not model_id or "intelligence_index" not in b:
            continue
        price = catalog[model_id].get("price_prompt_usd_per_mtok")
        if price is None or float(price) <= 0:
            continue
        points.append((model_id, float(price), float(b["intelligence_index"]), vol_by_id.get(model_id, 0.0)))
    if len(points) < 5:
        return "price-capability.svg skipped: too few joined models yet"

    frontier = []
    for p in sorted(points, key=lambda t: (t[1], -t[2])):
        if not frontier or p[2] > frontier[-1][2]:
            frontier.append(p)
    frontier_ids = {p[0] for p in frontier}

    # colour the three families carrying the most measured volume
    fam_volume: dict[str, float] = defaultdict(float)
    for model_id, _, _, vol in points:
        fam_volume[model_id.split("/")[0]] += vol
    top_families = [f for f, _ in sorted(fam_volume.items(), key=lambda kv: -kv[1])[:3]]
    colour_of = {f: FAMILY_SLOTS[i] for i, f in enumerate(top_families)}

    as_of = max(r["observed_at"] for r in all_rows if r["metric"] == "intelligence_index")[:10]
    width, height = 960.0, 560.0
    left, right, top, bottom = 62.0, 214.0, 108.0, 58.0
    lo, hi = min(p[1] for p in points), max(p[1] for p in points)
    smin, smax = min(p[2] for p in points), max(p[2] for p in points)
    vmax = max((p[3] for p in points), default=0) or 1

    x_of = lambda pr: left + (math.log10(pr) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * (width - left - right)  # noqa: E731
    y_of = lambda sc: (height - bottom) - (sc - smin) / max(1e-9, smax - smin) * (height - bottom - top)  # noqa: E731
    r_of = lambda vol: 4.0 + 11.0 * math.sqrt(vol / vmax)  # area ∝ volume  # noqa: E731

    body = [
        svg_text(24, 30, "What a point of intelligence costs", size=16, fill=INK, weight="600"),
        svg_text(24, 50, f"{len(points)} models priced and scored · snapshot {as_of}", size=12, fill=INK2),
        svg_text(24, 68, "vertical = Artificial Analysis intelligence index · line = efficient frontier · marker area = share of measured tokens", size=11, fill=MUTED),
    ]
    lx = 24.0
    for fam in top_families + ["other"]:
        col = colour_of.get(fam, FAMILY_OTHER)
        body.append(f'<circle cx="{lx + 5}" cy="88" r="5" fill="{col}"/>')
        body.append(svg_text(lx + 15, 92, fam, size=11, fill=INK2))
        lx += 15 + len(fam) * 6.6 + 18

    d = 10 ** math.floor(math.log10(lo))
    while d <= hi * 1.001:
        if d >= lo:
            gx = x_of(d)
            body.append(f'<line x1="{gx:.1f}" y1="{top - 8}" x2="{gx:.1f}" y2="{height - bottom}" stroke="{GRID}" stroke-width="1"/>')
            body.append(svg_text(gx, height - bottom + 18, f"${d:g}" if d >= 1 else f"${d:.2f}".rstrip("0").rstrip("."), size=10, fill=MUTED, anchor="middle", tabular=True))
        d *= 10
    for s in range(int(smin // 10 * 10), int(smax) + 10, 10):
        if smin <= s <= smax:
            gy = y_of(s)
            body.append(f'<line x1="{left}" y1="{gy:.1f}" x2="{width - right}" y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>')
            body.append(svg_text(left - 8, gy + 3.5, str(s), size=10, fill=MUTED, anchor="end", tabular=True))
    body.append(svg_text((left + width - right) / 2, height - 14, "input price, USD per million tokens (log scale)", size=10, fill=MUTED, anchor="middle"))
    body.append(f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="{BASELINE}" stroke-width="1"/>')

    fpts = " ".join(f"{x_of(p[1]):.1f},{y_of(p[2]):.1f}" for p in frontier)
    body.append(f'<polyline points="{fpts}" fill="none" stroke="{HUE}" stroke-width="2" stroke-linejoin="round" opacity="0.5"/>')

    # biggest markers first so small ones stay clickable on top
    for model_id, price, score, vol in sorted(points, key=lambda t: -t[3]):
        col = colour_of.get(model_id.split("/")[0], FAMILY_OTHER)
        body.append(
            f'<circle cx="{x_of(price):.1f}" cy="{y_of(score):.1f}" r="{r_of(vol):.1f}" '
            f'fill="{col}" fill-opacity="{0.9 if model_id in frontier_ids else 0.55}" '
            f'stroke="{SURFACE}" stroke-width="2"/>'
        )

    placed: list[float] = []
    for model_id, price, score, _ in sorted(frontier, key=lambda t: -t[2]):
        x, y = x_of(price), y_of(score)
        ly = y
        while any(abs(ly - p) < 13 for p in placed):
            ly += 13
        placed.append(ly)
        body.append(f'<line x1="{x + 8}" y1="{y:.1f}" x2="{x + 14}" y2="{ly - 3.5:.1f}" stroke="{BASELINE}" stroke-width="1"/>')
        body.append(svg_text(x + 17, ly + 3.5, f"{short_model(model_id)}  ${price:.3g}", size=10, fill=INK, weight="600"))

    body.append(svg_text(24, height - 4, cite(as_of) + " Scores: Artificial Analysis.", size=9, fill=MUTED))
    out.write_text(wrap(width, height, "What a point of intelligence costs",
                        "Scatter of model benchmark score against input price; colour is model family, marker area is token share, line is the efficient frontier.", body), encoding="utf-8")
    return f"{out.relative_to(REPO)} — {len(points)} models, {len(frontier)} on the frontier, {len(top_families)} families coloured"


def task_mix(out: Path, all_rows, top_n: int = 15) -> str:
    """Plain composition: no annotations, just what the tokens are spent on."""
    share, _, as_of = task_data(all_rows)
    if not share:
        return "task-mix.svg skipped: no classification observations yet"
    macros = {r["entity_id"][6:]: float(r["value"]) for r in all_rows
              if r["metric"] == "token_share" and r["entity_id"].startswith("macro:") and r["observed_at"][:10] == as_of}
    top = sorted(share.items(), key=lambda kv: -kv[1])[:top_n]

    width, left, right, top_pad = 880.0, 250.0, 100.0, 92.0
    bar_h, gap = 16.0, 8.0
    height = top_pad + len(top) * (bar_h + gap) + 36
    vmax, span = top[0][1], width - left - right
    body = [
        svg_text(24, 30, "What people actually ask models to do", size=16, fill=INK, weight="600"),
        svg_text(24, 50, f"share of all tokens on OpenRouter · trailing 7 days to {as_of}", size=12, fill=INK2),
        svg_text(24, 72, " · ".join(f"{MACRO_LABEL.get(k, k)} {v * 100:.0f}%" for k, v in sorted(macros.items(), key=lambda kv: -kv[1])), size=12, fill=INK2, weight="600"),
    ]
    body.append(f'<line x1="{left}" y1="{top_pad - 10}" x2="{left}" y2="{height - 32}" stroke="{BASELINE}" stroke-width="1"/>')
    t = 0.0
    while t <= vmax:
        gx = left + t / vmax * span
        body.append(f'<line x1="{gx:.1f}" y1="{top_pad - 10}" x2="{gx:.1f}" y2="{height - 32}" stroke="{GRID}" stroke-width="1"/>')
        body.append(svg_text(gx, height - 18, f"{t * 100:.0f}%", size=10, fill=MUTED, anchor="middle", tabular=True))
        t += 0.05
    for i, (tag, s) in enumerate(top):
        y = top_pad + i * (bar_h + gap)
        w = max(1.5, s / vmax * span)
        body.append(hbar(left, y, w, bar_h, HUE))
        body.append(svg_text(left - 10, y + bar_h - 4, pretty(tag)[:38], size=11, fill=INK2, anchor="end"))
        body.append(svg_text(left + w + 7, y + bar_h - 4, f"{s * 100:.1f}%", size=11, fill=INK, weight="600", tabular=True))
    body.append(svg_text(24, height - 4, cite(as_of), size=10, fill=MUTED))
    out.write_text(wrap(width, height, "What people actually ask models to do", "Ranked bar chart of OpenRouter token share by task.", body), encoding="utf-8")
    return f"{out.relative_to(REPO)} — {len(top)} of {len(share)} tasks"


def task_leaders(out: Path, all_rows, top_n: int = 15) -> str:
    """One row per workload: who leads it, and how much of it they hold."""
    share, per_task, as_of = task_data(all_rows)
    if not per_task:
        return "task-leaders.svg skipped: no classification observations yet"
    ranked = []
    for tag, s in sorted(share.items(), key=lambda kv: -kv[1])[:top_n]:
        if per_task.get(tag):
            model, within = max(per_task[tag].items(), key=lambda kv: kv[1])
            ranked.append((tag, s, model, within))

    width, left, right, top_pad = 940.0, 300.0, 150.0, 92.0
    bar_h, gap = 16.0, 8.0
    height = top_pad + len(ranked) * (bar_h + gap) + 36
    vmax = max(w for _, _, _, w in ranked)
    span = width - left - right
    body = [
        svg_text(24, 30, "Who leads each workload — and how firmly", size=16, fill=INK, weight="600"),
        svg_text(24, 50, f"bar = the leading model's share OF THAT WORKLOAD · trailing 7 days to {as_of}", size=12, fill=INK2),
        svg_text(24, 72, "a short bar means the workload is contested; a long one means it is spoken for", size=11, fill=MUTED),
    ]
    body.append(f'<line x1="{left}" y1="{top_pad - 10}" x2="{left}" y2="{height - 32}" stroke="{BASELINE}" stroke-width="1"/>')
    t = 0.0
    while t <= vmax:
        gx = left + t / vmax * span
        body.append(f'<line x1="{gx:.1f}" y1="{top_pad - 10}" x2="{gx:.1f}" y2="{height - 32}" stroke="{GRID}" stroke-width="1"/>')
        body.append(svg_text(gx, height - 18, f"{t * 100:.0f}%", size=10, fill=MUTED, anchor="middle", tabular=True))
        t += 0.05
    for i, (tag, s, model, within) in enumerate(ranked):
        y = top_pad + i * (bar_h + gap)
        w = max(1.5, within / vmax * span)
        body.append(hbar(left, y, w, bar_h, HUE))
        body.append(svg_text(left - 10, y + bar_h - 4, f"{pretty(tag)[:30]}  ({s * 100:.1f}% of tokens)", size=11, fill=INK2, anchor="end"))
        body.append(svg_text(left + w + 7, y + bar_h - 4, f"{within * 100:.0f}%  {short_model(model)[:26]}", size=10, fill=INK))
    body.append(svg_text(24, height - 4, cite(as_of), size=10, fill=MUTED))
    out.write_text(wrap(width, height, "Who leads each workload", "Bar chart of the leading model's share within each OpenRouter task.", body), encoding="utf-8")
    return f"{out.relative_to(REPO)} — {len(ranked)} workloads"


def task_contest(out: Path, all_rows) -> str:
    """Workload size against how locked up it is: the top-right is defended,
    the top-left is a big contested opening."""
    share, per_task, as_of = task_data(all_rows)
    pts = [(t, s, max(per_task[t].values())) for t, s in share.items() if per_task.get(t) and s > 0.005]
    if len(pts) < 4:
        return "task-contest.svg skipped: too few tasks yet"

    width, height = 900.0, 470.0
    left, right, top, bottom = 128.0, 40.0, 104.0, 58.0
    xmax = max(p[2] for p in pts) * 1.12
    ymax = max(p[1] for p in pts) * 1.12
    x_of = lambda v: left + v / xmax * (width - left - right)  # noqa: E731
    y_of = lambda v: (height - bottom) - v / ymax * (height - bottom - top)  # noqa: E731

    body = [
        svg_text(24, 30, "Where the open doors are", size=16, fill=INK, weight="600"),
        svg_text(24, 50, f"workload size against how much the leading model holds · trailing 7 days to {as_of}", size=12, fill=INK2),
        svg_text(24, 70, "up and to the LEFT = a big workload nobody owns", size=11, fill=MUTED),
    ]
    for frac in (0.05, 0.10, 0.15, 0.20, 0.25):
        if frac <= xmax:
            gx = x_of(frac)
            body.append(f'<line x1="{gx:.1f}" y1="{top - 8}" x2="{gx:.1f}" y2="{height - bottom}" stroke="{GRID}" stroke-width="1"/>')
            body.append(svg_text(gx, height - bottom + 18, f"{frac * 100:.0f}%", size=10, fill=MUTED, anchor="middle", tabular=True))
    for frac in (0.05, 0.10, 0.15, 0.20, 0.25):
        if frac <= ymax:
            gy = y_of(frac)
            body.append(f'<line x1="{left}" y1="{gy:.1f}" x2="{width - right}" y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>')
            body.append(svg_text(left - 8, gy + 3.5, f"{frac * 100:.0f}%", size=10, fill=MUTED, anchor="end", tabular=True))
    body.append(svg_text(left - 8, top - 12, "share of all tokens", size=10, fill=MUTED, anchor="end"))
    body.append(svg_text((left + width - right) / 2, height - 14, "leading model's share of that workload →  more locked up", size=10, fill=MUTED, anchor="middle"))
    body.append(f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="{BASELINE}" stroke-width="1"/>')

    placed: list[tuple[float, float]] = []
    for tag, size, lead in sorted(pts, key=lambda p: -p[1]):
        x, y = x_of(lead), y_of(size)
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{HUE}" fill-opacity="0.75" stroke="{SURFACE}" stroke-width="2"/>')
        # label only where it will not collide
        if not any(abs(x - px) < 90 and abs(y - py) < 13 for px, py in placed):
            body.append(svg_text(x + 9, y + 3.5, pretty(tag)[:26], size=10, fill=INK2))
            placed.append((x, y))
    body.append(svg_text(24, height - 4, cite(as_of), size=10, fill=MUTED))
    out.write_text(wrap(width, height, "Where the open doors are", "Scatter of workload size against the leading model's share of that workload.", body), encoding="utf-8")
    return f"{out.relative_to(REPO)} — {len(pts)} workloads"


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows = rows()
    if not all_rows:
        print("no observations yet — run capture + derive first")
        return 1
    print(price_capability(OUT_DIR / "price-capability.svg", all_rows))
    print(task_mix(OUT_DIR / "task-mix.svg", all_rows))
    print(task_leaders(OUT_DIR / "task-leaders.svg", all_rows))
    print(task_contest(OUT_DIR / "task-contest.svg", all_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
