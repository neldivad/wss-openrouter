"""Parser for schema or-classifications.v1 — OpenRouter's task mix.

Shape verified against the live endpoint on 2026-09-01.

What people ask models to *do*, as a share of traffic. OpenRouter samples
this and publishes shares only, so there are no absolute volumes — which is
fine, because composition is the question.

`as_of` is the window's upper bound and is the fact's own date, so it becomes
`observed_at` rather than letting capture time stand in.

entity_id is namespaced, and the model-within-task figures use a composite
`task:<tag>/model:<id>` entity: the cross-product belongs in the entity, not
in an exploding set of metric names.
"""

import json

from wss import derive

PARSER_VERSION = "1"

# (payload key, metric name) — shares are fractions of 1, kept verbatim.
SHARES = (
    ("usage_share", "usage_share"),
    ("token_share", "token_share"),
    ("category_usage_share", "category_usage_share"),
    ("category_token_share", "category_token_share"),
)


def parse(body: bytes, ctx: derive.ParseContext):
    data = json.loads(body)["data"]
    observed_at = f"{data['as_of']}T00:00:00Z"

    for macro in data.get("macro_categories", []):
        for key in ("usage_share", "token_share"):
            if macro.get(key) is not None:
                yield derive.Observation(
                    entity_id=f"macro:{macro['key']}",
                    metric=key,
                    value=macro[key],
                    unit="share",
                    observed_at=observed_at,
                )

    for cls in data.get("classifications", []):
        tag = cls["tag"]
        for key, metric in SHARES:
            if cls.get(key) is not None:
                yield derive.Observation(
                    entity_id=f"task:{tag}",
                    metric=metric,
                    value=cls[key],
                    unit="share",
                    observed_at=observed_at,
                )
        for model in cls.get("models", []):
            for key in ("tag_usage_share", "tag_token_share"):
                if model.get(key) is not None:
                    yield derive.Observation(
                        entity_id=f"task:{tag}/model:{model['id']}",
                        metric=key,
                        value=model[key],
                        unit="share",
                        observed_at=observed_at,
                    )


derive.register("or-classifications.v1", parse, PARSER_VERSION)
