"""Parser for schema or-rankings.v1 — OpenRouter's weekly usage rankings.

Each response carries a rolling 13-week window, so one capture restates
thirteen weeks at once. That makes `observed_at` (the week being described)
genuinely different from `captured_at` (when we fetched it), and it means a
later capture can *revise* an earlier week — which the archive will show,
because both statements are kept.

Weeks are labelled by their start date; observations are stamped at the start
of that week, midnight UTC.
"""

import json

from wss import derive

PARSER_VERSION = "1"


def parse(body: bytes, ctx: derive.ParseContext):
    points = json.loads(body)["data"]
    for point in points:
        observed_at = f"{point['x']}T00:00:00Z"
        weekly = point["ys"]
        for model_id, tokens in sorted(weekly.items()):
            # "Others" is OpenRouter's own bucket for everything outside the
            # top 10; kept verbatim, because its share measures concentration.
            yield derive.Observation(
                entity_id=model_id,
                metric="tokens_weekly",
                value=int(tokens),
                unit="tokens/week",
                observed_at=observed_at,
            )
        yield derive.Observation(
            entity_id="openrouter",
            metric="tokens_weekly_total",
            value=int(sum(weekly.values())),
            unit="tokens/week",
            observed_at=observed_at,
        )


derive.register("or-rankings.v1", parse, PARSER_VERSION)
