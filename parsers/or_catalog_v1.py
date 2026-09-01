"""Parser for schema or-catalog.v1 — the OpenRouter model catalogue.

Prices arrive as per-token decimal strings. They are converted to USD per
million tokens (the unit humans quote) using Decimal, never float, so the
CSV is exact and a rebuild is byte-identical.

`hugging_face_id` is emitted as its own observation so the join to
wss-hugging-face lives in the data rather than in someone's notebook.
"""

import json
from decimal import Decimal

from wss import derive

PARSER_VERSION = "1"

PER_MILLION = Decimal(1_000_000)

# (pricing key, metric name) — the dimensions that are comparable across
# models. Modality-specific keys (audio, web_search) are left out; add them
# here and bump PARSER_VERSION if they become interesting.
PRICES = (
    ("prompt", "price_prompt_usd_per_mtok"),
    ("completion", "price_completion_usd_per_mtok"),
    ("input_cache_read", "price_cache_read_usd_per_mtok"),
)


def _per_mtok(raw: str) -> str | None:
    """Exact decimal conversion; None when the field is absent or unpriced."""
    try:
        value = Decimal(str(raw)) * PER_MILLION
    except Exception:
        return None
    # normalize() drops trailing zeros; 'f' avoids scientific notation.
    return format(value.normalize(), "f")


def parse(body: bytes, ctx: derive.ParseContext):
    for model in json.loads(body)["data"]:
        entity_id = model["id"]
        pricing = model.get("pricing") or {}
        for key, metric in PRICES:
            if key in pricing:
                value = _per_mtok(pricing[key])
                if value is not None:
                    yield derive.Observation(
                        entity_id=entity_id, metric=metric, value=value, unit="USD/Mtok"
                    )
        if model.get("context_length"):
            yield derive.Observation(
                entity_id=entity_id,
                metric="context_length",
                value=int(model["context_length"]),
                unit="tokens",
            )
        # The join key to wss-hugging-face, carried as data.
        if model.get("hugging_face_id"):
            yield derive.Observation(
                entity_id=entity_id,
                metric="hugging_face_id",
                value=model["hugging_face_id"],
                unit="ref",
            )


derive.register("or-catalog.v1", parse, PARSER_VERSION)
