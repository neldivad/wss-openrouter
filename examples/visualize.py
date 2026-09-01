#!/usr/bin/env python3
"""Render charts from derived/observations/*.csv as SVG.

    python examples/visualize.py

  usage-share.svg   each leading model's share of weekly tokens across the
                    rolling window — where inference demand actually goes,
                    and how quickly it moves between model versions

Reads the derived table, never the raw archive. Stdlib only, deterministic.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "examples" / "charts"
SERIES_ID = "openrouter.usage.tools"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
# Validated categorical slots, fixed order, assigned alphabetically so a
# re-render never repaints a surviving series.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

DATED_SUFFIX = re.compile(r"-(\d{4})(\d{2})(\d{2})$")


def short(model_id: str) -> str:
    """`deepseek/deepseek-v4-flash-20260423` → `deepseek-v4-flash (Apr 23)`."""
    name = model_id.split("/")[-1]
    m = DATED_SUFFIX.search(name)
    if not m:
        return name
    stamp = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return f"{name[: m.start()]} ({stamp:%b %-d})"


def svg_text(x, y, text, *, size, fill, anchor="start", weight="normal", tabular=False) -> str:
    style = "font-variant-numeric: tabular-nums;" if tabular else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family=\'{FONT}\' font-size="{size}" '
        f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}" style="{style}">{escape(text)}</text>'
    )


def usage_share(out: Path, top_n: int = 4) -> str:
    rows = []
    for partition in sorted((REPO / "derived" / "observations").glob("*.csv")):
        with partition.open(encoding="utf-8", newline="") as fh:
            rows.extend(r for r in csv.DictReader(fh) if r["series_id"] == SERIES_ID)
    if not rows:
        return "usage-share.svg skipped: no observations yet"

    # Latest statement of each (week, model): a later capture may revise a week.
    latest: dict[tuple[str, str], dict] = {}
    for r in rows:
        if r["metric"] != "tokens_weekly":
            continue
        key = (r["observed_at"][:10], r["entity_id"])
        if key not in latest or r["captured_at"] > latest[key]["captured_at"]:
            latest[key] = r
    totals: dict[str, int] = {}
    for r in rows:
        if r["metric"] == "tokens_weekly_total":
            totals[r["observed_at"][:10]] = int(r["value"])

    by_week: dict[str, dict[str, int]] = defaultdict(dict)
    volume: dict[str, int] = defaultdict(int)
    for (week, model), r in latest.items():
        if model == "Others":  # OpenRouter's own tail bucket, not a model
            continue
        by_week[week][model] = int(r["value"])
        volume[model] += int(r["value"])

    weeks = sorted(by_week)
    keep = sorted(sorted(volume, key=lambda m: -volume[m])[:top_n])
    others_share = 100 - sum(by_week[weeks[-1]].get(m, 0) for m in by_week[weeks[-1]]) / totals[weeks[-1]] * 100

    width, height = 940.0, 470.0
    left, right, top, bottom = 58.0, 210.0, 96.0, 46.0
    ymax = max(
        (by_week[w].get(m, 0) / totals[w] * 100 for w in weeks for m in keep), default=1
    ) * 1.15

    def x_of(week: str) -> float:
        i = weeks.index(week)
        return left + (i / max(1, len(weeks) - 1)) * (width - left - right)

    def y_of(pct: float) -> float:
        return (height - bottom) - (pct / ymax) * (height - bottom - top)

    body = [
        svg_text(24, 30, "Where inference demand actually goes", size=16, fill=INK, weight="600"),
        svg_text(
            24, 50,
            f"share of weekly tokens on OpenRouter · top {top_n} of the ranked models · "
            f"a further {others_share:.0f}% sits outside the top 10",
            size=12, fill=INK2,
        ),
    ]

    lx = 24.0
    for i, model in enumerate(keep):
        label = short(model)
        body.append(f'<circle cx="{lx + 4}" cy="68" r="4" fill="{SERIES[i]}"/>')
        body.append(svg_text(lx + 12, 72, label, size=11, fill=INK2))
        lx += 12 + len(label) * 6.4 + 18

    tick = 0.0
    while tick <= ymax:
        gy = y_of(tick)
        body.append(f'<line x1="{left}" y1="{gy:.1f}" x2="{width - right}" y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>')
        body.append(svg_text(left - 8, gy + 3.5, f"{tick:.0f}%", size=11, fill=MUTED, anchor="end", tabular=True))
        tick += 5
    for w in weeks[::3]:
        body.append(svg_text(x_of(w), height - bottom + 18, w[5:], size=10, fill=MUTED, anchor="middle", tabular=True))
    body.append(f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="{BASELINE}" stroke-width="1"/>')

    ends = []
    for i, model in enumerate(keep):
        # A model missing from a week's top 10 is *unknown*, not zero — the
        # endpoint only itemises ten. Break the line rather than draw a floor.
        segments: list[list[tuple[float, float]]] = [[]]
        for w in weeks:
            if model in by_week[w]:
                segments[-1].append((x_of(w), y_of(by_week[w][model] / totals[w] * 100)))
            elif segments[-1]:
                segments.append([])
        segments = [s for s in segments if s]
        for seg in segments:
            if len(seg) > 1:
                body.append(
                    f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in seg)}" fill="none" '
                    f'stroke="{SERIES[i]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
                )
            else:
                x, y = seg[0]
                body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{SERIES[i]}"/>')
        ex, ey = segments[-1][-1]
        body.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="5" fill="{SERIES[i]}" stroke="{SURFACE}" stroke-width="2"/>')
        last_week = next(w for w in reversed(weeks) if model in by_week[w])
        pct = by_week[last_week][model] / totals[last_week] * 100
        gone = "" if last_week == weeks[-1] else "  (dropped out)"
        ends.append((ey, f"{short(model)}  {pct:.1f}%{gone}", ex))

    placed: list[float] = []
    for ey, label, ex in sorted(ends):
        y = ey
        for p in placed:
            if abs(y - p) < 14:
                y = p + 14
        placed.append(y)
        if abs(y - ey) > 7:
            body.append(f'<line x1="{ex + 7}" y1="{ey:.1f}" x2="{ex + 10}" y2="{y - 3.5:.1f}" stroke="{BASELINE}" stroke-width="1"/>')
        body.append(svg_text(ex + 12, y + 3.5, label, size=11, fill=INK, weight="600"))

    body.append(svg_text(24, height - 8, "source: wss-openrouter · openrouter.usage.tools · CC-BY-4.0", size=10, fill=MUTED))

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Where inference demand actually goes">\n'
        f"<title>Where inference demand actually goes</title>\n"
        f"<desc>Line chart of each leading model's share of weekly tokens served on OpenRouter.</desc>\n"
        f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>\n' + "\n".join(body) + "\n</svg>\n"
    )
    out.write_text(svg, encoding="utf-8")
    return f"{out.relative_to(REPO)} — {len(keep)} series over {len(weeks)} weeks"


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(usage_share(OUT_DIR / "usage-share.svg"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
