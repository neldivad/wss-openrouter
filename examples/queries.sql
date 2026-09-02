-- Decision analytics over the long-format observation table.
--   observations(series_id, entity_id, observed_at, captured_at, metric,
--                value, unit, source_id, raw_ref, parser_version)
-- Run with: python examples/load_observations.py
-- Or in DuckDB, straight off GitHub with no credentials:
--   SELECT * FROM read_csv_auto('https://raw.githubusercontent.com/neldivad/wss-openrouter/main/derived/observations/*.csv')

-- EVERY query starts by deduplicating. Several sources restate the same
-- observed_at on each capture -- the task mix describes a trailing 7-day
-- window, so three captures produce three rows for the same week. That is
-- deliberate (it is how a revision becomes visible) but it means a naive
-- filter returns duplicates. `latest` keeps the most recent statement of
-- each fact, which is what almost every question wants.

-- Cost versus capability: what a point of intelligence costs, per model.
-- Which model to default to, and which "premium" model buys you nothing.
WITH latest AS (
  SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (
      PARTITION BY series_id, entity_id, metric, observed_at
      ORDER BY captured_at DESC) AS rn
    FROM observations
  ) WHERE rn = 1
),
newest AS (SELECT MAX(observed_at) AS t FROM latest WHERE metric = 'intelligence_index'),
score AS (
  SELECT entity_id AS slug, CAST(value AS REAL) AS index_score
  FROM latest, newest WHERE metric = 'intelligence_index' AND observed_at = newest.t
),
slug AS (SELECT entity_id AS model_id, value AS slug FROM latest WHERE metric = 'canonical_slug'),
price AS (SELECT entity_id AS model_id, CAST(value AS REAL) AS usd FROM latest WHERE metric = 'price_prompt_usd_per_mtok')
SELECT slug.model_id, score.index_score, price.usd AS usd_per_mtok,
       ROUND(score.index_score / NULLIF(price.usd, 0), 1) AS points_per_dollar
FROM score
JOIN slug ON slug.slug = score.slug
JOIN price ON price.model_id = slug.model_id
WHERE price.usd > 0
ORDER BY points_per_dollar DESC;

-- Who owns each workload, and how firmly. A leader holding 25% is a defended
-- position; one holding 7% is contested and worth entering.
WITH latest AS (
  SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (
      PARTITION BY series_id, entity_id, metric, observed_at
      ORDER BY captured_at DESC) AS rn
    FROM observations
  ) WHERE rn = 1
),
newest AS (SELECT MAX(observed_at) AS t FROM latest WHERE metric = 'token_share'),
task AS (
  SELECT substr(entity_id, 6) AS tag, CAST(value AS REAL) AS token_share
  FROM latest, newest
  WHERE metric = 'token_share' AND observed_at = newest.t
    AND entity_id LIKE 'task:%' AND entity_id NOT LIKE '%/model:%'
),
leader AS (
  SELECT substr(entity_id, 6, instr(entity_id, '/model:') - 6) AS tag,
         substr(entity_id, instr(entity_id, '/model:') + 7)    AS model,
         CAST(value AS REAL) AS within_task,
         ROW_NUMBER() OVER (
           PARTITION BY substr(entity_id, 6, instr(entity_id, '/model:') - 6)
           ORDER BY CAST(value AS REAL) DESC) AS rn
  FROM latest, newest
  WHERE metric = 'tag_token_share' AND observed_at = newest.t
)
SELECT task.tag,
       ROUND(task.token_share * 100, 1)   AS pct_of_all_tokens,
       leader.model                       AS leading_model,
       ROUND(leader.within_task * 100, 1) AS leader_pct_of_task
FROM task JOIN leader ON leader.tag = task.tag AND leader.rn = 1
ORDER BY task.token_share DESC;

-- Demand composition: what people use models for, independent of which wins.
WITH latest AS (
  SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (
      PARTITION BY series_id, entity_id, metric, observed_at
      ORDER BY captured_at DESC) AS rn
    FROM observations
  ) WHERE rn = 1
)
SELECT substr(entity_id, 7) AS macro_category,
       ROUND(CAST(value AS REAL) * 100, 1) AS pct_of_tokens
FROM latest
WHERE metric = 'token_share' AND entity_id LIKE 'macro:%'
  AND observed_at = (SELECT MAX(observed_at) FROM latest WHERE metric = 'token_share')
ORDER BY pct_of_tokens DESC;

-- What one agent session actually costs, by session length. A cheap
-- per-token model that needs fifty turns can cost more than an expensive one
-- that finishes in two.
WITH latest AS (
  SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (
      PARTITION BY series_id, entity_id, metric, observed_at
      ORDER BY captured_at DESC) AS rn
    FROM observations
  ) WHERE rn = 1
)
SELECT substr(entity_id, 5, instr(entity_id, '/turns:') - 5) AS app,
       substr(entity_id, instr(entity_id, '/turns:') + 7,
              instr(entity_id, '/model:') - instr(entity_id, '/turns:') - 7) AS turn_range,
       substr(entity_id, instr(entity_id, '/model:') + 7) AS model,
       ROUND(CAST(value AS REAL), 4) AS median_usd
FROM latest
WHERE metric = 'median_session_cost'
ORDER BY app, median_usd DESC;

-- ONCE SEVERAL WEEKS EXIST -- the questions only history can answer.

-- Is a workload growing or shrinking? (needs >= 2 distinct observed_at)
WITH latest AS (
  SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (
      PARTITION BY series_id, entity_id, metric, observed_at
      ORDER BY captured_at DESC) AS rn
    FROM observations
  ) WHERE rn = 1
)
SELECT substr(entity_id, 6) AS tag,
       MIN(observed_at) AS first_seen,
       MAX(observed_at) AS last_seen,
       ROUND((MAX(CAST(value AS REAL)) - MIN(CAST(value AS REAL))) * 100, 2) AS share_swing_pts
FROM latest
WHERE metric = 'token_share' AND entity_id LIKE 'task:%' AND entity_id NOT LIKE '%/model:%'
GROUP BY tag
HAVING COUNT(DISTINCT observed_at) > 1
ORDER BY ABS(MAX(CAST(value AS REAL)) - MIN(CAST(value AS REAL))) DESC;

-- Quiet price cuts: a model whose price fell between two captures.
WITH latest AS (
  SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (
      PARTITION BY series_id, entity_id, metric, observed_at
      ORDER BY captured_at DESC) AS rn
    FROM observations
  ) WHERE rn = 1
),
p AS (SELECT entity_id, observed_at, CAST(value AS REAL) AS usd FROM latest WHERE metric = 'price_prompt_usd_per_mtok')
SELECT a.entity_id, a.observed_at AS from_date, a.usd AS from_price,
       b.observed_at AS to_date, b.usd AS to_price,
       ROUND((b.usd - a.usd) * 100.0 / NULLIF(a.usd, 0), 1) AS pct_change
FROM p a JOIN p b ON b.entity_id = a.entity_id AND b.observed_at > a.observed_at
WHERE a.usd <> b.usd
ORDER BY pct_change ASC;
