"""Parser for schema or-sessions.v1 — median cost of one agent session.

Shape verified against the live endpoint on 2026-09-02.

The economics list prices cannot tell you: what a *session* costs, split by
how long the session runs. A cheap per-token model that needs fifty turns can
cost more than an expensive one that finishes in two.

entity_id is composite — `app:<slug>/turns:<range>/model:<permaslug>` — because
the fact is a three-way cell, not a property of any one of them. Splitting on
`/` recovers the dimensions; `model_permaslug` also joins to the benchmark
sources and, via canonical_slug, to catalogue prices.
"""

import json

from wss import derive

PARSER_VERSION = "1"


def parse(body: bytes, ctx: derive.ParseContext):
    payload = json.loads(body)
    meta = payload.get("meta", {})
    observed_at = meta.get("as_of")
    # window_end_date is the last day the 30-day window covers; prefer it as
    # the fact's own date when present, since as_of is merely fetch-adjacent.
    if meta.get("window_end_date"):
        observed_at = f"{meta['window_end_date']}T00:00:00Z"

    for row in payload.get("data", []):
        entity_id = (
            f"app:{row['app_slug']}"
            f"/turns:{row['turn_range']}"
            f"/model:{row['model_permaslug']}"
        )
        cost = row.get("median_session_cost_usd")
        if cost is not None:
            yield derive.Observation(
                entity_id=entity_id,
                metric="median_session_cost",
                value=cost,
                unit="USD/session",
                observed_at=observed_at,
            )


derive.register("or-sessions.v1", parse, PARSER_VERSION)
