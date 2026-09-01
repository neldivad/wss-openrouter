"""Parser for schema or-benchmarks.v1 — benchmark scores via OpenRouter.

Shapes verified against the live endpoint on 2026-09-01 for both
`artificial-analysis` (composite indices) and `design-arena` (tournament
ELO). One parser serves both sources by branching on each item's own
`source` field, the same way one parser serves every Hugging Face listing.

`meta.as_of` is the scores' own timestamp and becomes `observed_at`.

Prices are deliberately *not* emitted here even though the payload carries
them: openrouter.models.catalog is the one price source, and two sources
publishing the same metric under different methodologies would be a trap.
"""

import json

from wss import derive

PARSER_VERSION = "1"

# metrics per benchmark source: (payload key, metric name, unit)
BY_SOURCE = {
    "artificial-analysis": (
        ("intelligence_index", "intelligence_index", "index"),
        ("coding_index", "coding_index", "index"),
        ("agentic_index", "agentic_index", "index"),
    ),
    "design-arena": (
        ("elo", "elo", "rating"),
        ("win_rate", "win_rate", "percent"),
        ("avg_generation_time_ms", "avg_generation_time", "ms"),
    ),
    "openrouter": (
        ("primary_score", "primary_score", "score"),
        ("accuracy", "accuracy", "fraction"),
        ("total_tasks", "total_tasks", "count"),
        ("avg_cost_per_task", "avg_cost_per_task", "USD"),
        ("avg_latency_per_task_ms", "avg_latency_per_task", "ms"),
    ),
}


def parse(body: bytes, ctx: derive.ParseContext):
    payload = json.loads(body)
    observed_at = payload.get("meta", {}).get("as_of")

    for item in payload.get("data", []):
        source = item.get("source")
        metrics = BY_SOURCE.get(source)
        if not metrics:  # a new benchmark source: bump PARSER_VERSION to add it
            continue
        entity_id = item["model_permaslug"]
        # design-arena scores are per (arena, category); keep them apart.
        if source == "design-arena" and item.get("category"):
            entity_id = f"{entity_id}/arena:{item.get('arena', 'models')}/{item['category']}"
        elif source == "openrouter" and item.get("benchmark_type"):
            entity_id = f"{entity_id}/bench:{item['benchmark_type']}"

        for key, metric, unit in metrics:
            if item.get(key) is not None:
                yield derive.Observation(
                    entity_id=entity_id,
                    metric=metric,
                    value=item[key],
                    unit=unit,
                    observed_at=observed_at,
                )


derive.register("or-benchmarks.v1", parse, PARSER_VERSION)
