-- Decision analytics over the long-format observation table.
--   observations(series_id, entity_id, observed_at, captured_at, metric,
--                value, unit, source_id, raw_ref, parser_version)
-- Loaded by examples/load_observations.py, or read directly with DuckDB:
--   SELECT * FROM read_csv_auto('derived/observations/*.csv')
--
-- The cross-source join key is `canonical_slug`: the catalogue's `id` is an
-- undated alias (anthropic/claude-opus-5) while the benchmark endpoints key
-- on the dated permaslug (anthropic/claude-opus-5-20260723). Joining on
-- canonical_slug matches 96 of 100 benchmarked models; joining on id
-- matches 14.

-- Cost versus capability: what a point of intelligence costs, per model.
-- The decision this informs: which model to default to for a workload, and
-- which "premium" model is not buying you anything.
WITH latest AS (
  SELECT MAX(observed_at) AS t FROM observations WHERE metric = 'intelligence_index'
),
score AS (
  SELECT entity_id AS slug, CAST(value AS REAL) AS index_score
  FROM observations, latest
  WHERE metric = 'intelligence_index' AND observed_at = latest.t
),
slug AS (
  SELECT entity_id AS model_id, value AS slug
  FROM observations WHERE metric = 'canonical_slug'
),
price AS (
  SELECT entity_id AS model_id, CAST(value AS REAL) AS usd_per_mtok
  FROM observations WHERE metric = 'price_prompt_usd_per_mtok'
)
SELECT slug.model_id,
       score.index_score,
       price.usd_per_mtok,
       ROUND(score.index_score / NULLIF(price.usd_per_mtok, 0), 1) AS points_per_dollar
FROM score
JOIN slug  ON slug.slug = score.slug
JOIN price ON price.model_id = slug.model_id
WHERE price.usd_per_mtok > 0
ORDER BY points_per_dollar DESC;

-- Who owns each workload: the leading model per task, and how concentrated
-- that task is. A task where the leader holds 25% is a defended position; a
-- task where the leader holds 7% is contested and worth entering.
WITH latest AS (
  SELECT MAX(observed_at) AS t FROM observations WHERE metric = 'token_share'
),
task AS (
  SELECT substr(entity_id, 6) AS tag, CAST(value AS REAL) AS token_share
  FROM observations, latest
  WHERE metric = 'token_share' AND observed_at = latest.t
    AND entity_id LIKE 'task:%' AND entity_id NOT LIKE '%/model:%'
),
leader AS (
  SELECT substr(entity_id, 6, instr(entity_id, '/model:') - 6) AS tag,
         substr(entity_id, instr(entity_id, '/model:') + 7)    AS model,
         CAST(value AS REAL) AS within_task_share,
         ROW_NUMBER() OVER (
           PARTITION BY substr(entity_id, 6, instr(entity_id, '/model:') - 6)
           ORDER BY CAST(value AS REAL) DESC
         ) AS rn
  FROM observations, latest
  WHERE metric = 'tag_token_share' AND observed_at = latest.t
)
SELECT task.tag,
       ROUND(task.token_share * 100, 1)        AS pct_of_all_tokens,
       leader.model                            AS leading_model,
       ROUND(leader.within_task_share * 100, 1) AS leader_pct_of_task
FROM task
JOIN leader ON leader.tag = task.tag AND leader.rn = 1
ORDER BY task.token_share DESC;

-- Demand composition by macro category — the shape of what people actually
-- use models for, independent of which model wins.
SELECT substr(entity_id, 7) AS macro_category,
       ROUND(CAST(value AS REAL) * 100, 1) AS pct_of_tokens
FROM observations
WHERE metric = 'token_share' AND entity_id LIKE 'macro:%'
  AND observed_at = (SELECT MAX(observed_at) FROM observations WHERE metric = 'token_share')
ORDER BY pct_of_tokens DESC;

-- ONCE SEVERAL WEEKS EXIST — the questions only history can answer.

-- Is a workload growing or shrinking? (needs >= 2 capture weeks)
SELECT substr(entity_id, 6) AS tag,
       MIN(observed_at) AS first_seen,
       MAX(observed_at) AS last_seen,
       ROUND((MAX(CAST(value AS REAL)) - MIN(CAST(value AS REAL))) * 100, 2) AS share_swing_pts
FROM observations
WHERE metric = 'token_share' AND entity_id LIKE 'task:%' AND entity_id NOT LIKE '%/model:%'
GROUP BY tag
HAVING COUNT(DISTINCT observed_at) > 1
ORDER BY ABS(MAX(CAST(value AS REAL)) - MIN(CAST(value AS REAL))) DESC;

-- Price cuts: a model whose price fell between two captures.
WITH p AS (
  SELECT entity_id, observed_at, CAST(value AS REAL) AS usd
  FROM observations WHERE metric = 'price_prompt_usd_per_mtok'
)
SELECT a.entity_id,
       a.observed_at AS from_date, a.usd AS from_price,
       b.observed_at AS to_date,   b.usd AS to_price,
       ROUND((b.usd - a.usd) * 100.0 / NULLIF(a.usd, 0), 1) AS pct_change
FROM p a
JOIN p b ON b.entity_id = a.entity_id AND b.observed_at > a.observed_at
WHERE a.usd <> b.usd
ORDER BY pct_change ASC;
