-- ai-fc SQLite 파생 인덱스. 언제든 파일에서 재구축 가능 (sync --rebuild).
-- schema_version: 1

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '1');

CREATE TABLE IF NOT EXISTS questions (
    question_id     TEXT PRIMARY KEY,
    title           TEXT,
    question        TEXT,
    deadline_kind   TEXT CHECK (deadline_kind IN ('fixed', 'rolling', 'tbd')),
    deadline        TEXT,           -- ISO date, fixed일 때
    rolling_days    INTEGER,
    resolution      TEXT,
    resolution_source TEXT,
    domain          TEXT,           -- enum 아님 (market-daily 등 신설 가능)
    cadence_raw     TEXT,
    schedule_json   TEXT,           -- 정규화 스케줄, '[]' = manual
    action_link     TEXT,
    status          TEXT,
    created         TEXT,
    notes           TEXT,
    required_snapshots_json TEXT,
    src_hash        TEXT            -- 질문 블록 해시 (판정기준 변경 감지)
);

CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id     TEXT PRIMARY KEY,   -- 파일명 stem
    question_id     TEXT NOT NULL,
    round           INTEGER NOT NULL,
    forecast_ts     TEXT,               -- ISO datetime (KST naive)
    probability     INTEGER NOT NULL,
    ci80_lo         INTEGER,
    ci80_hi         INTEGER,
    window_end      TEXT,               -- rolling 인스턴스 키
    snapshots_json  TEXT,
    market_implied  REAL,
    edge            REAL,
    model           TEXT,
    prompt_version  TEXT,
    phase           TEXT,
    method          TEXT,
    sources_count   INTEGER,
    path            TEXT NOT NULL,
    file_sha256     TEXT NOT NULL,
    ingested_at     TEXT,
    research_status TEXT,           -- ok|ok_low_primary|degraded|failed (구파일 NULL=ok)
    shadow_extremized INTEGER,      -- WS8: 섀도 가상 Brier용 (표시 전용 열의 DB 적재)
    ml_divergence_pp REAL,          -- WS6: 기록 시점 |rN − ML앙상블| (%p)
    divergence_class TEXT,          -- WS6: ≥15%p 시 분류 (enum 4종)
    pipeline_tier   TEXT,           -- v3 WS-B: standard|lite (티어별 Brier 분해용)
    UNIQUE (question_id, round)
);
CREATE INDEX IF NOT EXISTS idx_forecasts_qid_window ON forecasts (question_id, window_end);

CREATE TABLE IF NOT EXISTS resolutions (
    forecast_id     TEXT NOT NULL,
    resolved_date   TEXT NOT NULL,
    question_id     TEXT,
    forecast_date   TEXT,
    probability     INTEGER,
    outcome         INTEGER,
    brier           REAL,
    domain          TEXT,
    notes           TEXT,
    ledger_line     INTEGER,
    PRIMARY KEY (forecast_id, resolved_date)
);

CREATE TABLE IF NOT EXISTS ledger_lines (
    line_no         INTEGER PRIMARY KEY,  -- 1-based, 헤더 제외
    line_hash       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_meta (
    file            TEXT PRIMARY KEY,     -- 루트 상대 경로
    sha256          TEXT NOT NULL,
    mtime           REAL,
    ingested_at     TEXT
);

-- AUDIT-260715 8-2(c): 소급 리서치 상태 판정 — 예측 파일은 불변이므로 메타로만.
-- 원천: calibration/research_status_overrides.csv (git 추적, 사유 필수)
CREATE TABLE IF NOT EXISTS research_status_override (
    forecast_id     TEXT PRIMARY KEY,
    status          TEXT NOT NULL,      -- degraded | failed
    reason          TEXT,
    created_at      TEXT NOT NULL       -- 시점 불변식: created_at < 해소일 (E4)
);

-- overrides.csv 행 해시 (원장급 규율 — RE-AUDIT U-2: 축소·변조 = E5)
CREATE TABLE IF NOT EXISTS override_lines (
    line_no         INTEGER PRIMARY KEY,
    line_hash       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT,
    question_id     TEXT,
    stage           TEXT,               -- research | reasoning
    model           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL
);

-- ── ML/시장 확률 이력 (원본: data/ml_history/*.jsonl — 재구축 가능) ──

CREATE TABLE IF NOT EXISTS ml_forecasts (
    run_ts          TEXT NOT NULL,
    question_id     TEXT NOT NULL,
    model           TEXT NOT NULL,      -- bolt | c2 | t5 | gbm | ensemble
    kind            TEXT NOT NULL,      -- terminal | path_touch
    prob            REAL NOT NULL,
    threshold       REAL,
    horizon_weeks   INTEGER,
    detail_json     TEXT,
    PRIMARY KEY (run_ts, question_id, model, kind)
);

CREATE TABLE IF NOT EXISTS ml_sentiment (
    run_ts          TEXT NOT NULL,
    feed            TEXT NOT NULL,
    n_headlines     INTEGER,
    score           REAL,
    PRIMARY KEY (run_ts, feed)
);

CREATE TABLE IF NOT EXISTS market_implied (
    run_ts          TEXT NOT NULL,
    question_id     TEXT NOT NULL,
    source          TEXT NOT NULL,      -- kalshi | polymarket | options_bl
    prob            REAL NOT NULL,
    detail_json     TEXT,
    PRIMARY KEY (run_ts, question_id, source)
);

-- ── 벤치마크 3자 원장 (WS2 — 원본: calibration/benchmark_ledger.csv) ──
-- edge 증명의 전제 배관: LLM vs ML앙상블 vs 시장내재의 Brier를 나란히 채점.
-- 기록·표시 전용 — 게이트 산정식(v_gate_status)과 무관 (참고 의견, P3 게이트 전).

CREATE TABLE IF NOT EXISTS benchmark_scores (
    forecast_id     TEXT NOT NULL,
    resolved_date   TEXT NOT NULL,
    question_id     TEXT,
    llm_prob        REAL,
    llm_brier       REAL,
    ml_prob         REAL,               -- NULL = 예측 시점 이전 ML 참조 부재 (정직)
    ml_brier        REAL,
    market_prob     REAL,               -- NULL = 기록된 시장내재 부재
    market_brier    REAL,
    ml_asof         TEXT,               -- 사용한 ML run_ts (룩어헤드 차단 증빙)
    market_asof     TEXT,               -- frontmatter 기록 시점 (예측일)
    notes           TEXT,
    line_no         INTEGER,
    PRIMARY KEY (forecast_id, resolved_date)
);

CREATE TABLE IF NOT EXISTS benchmark_lines (
    line_no         INTEGER PRIMARY KEY,
    line_hash       TEXT NOT NULL
);

-- 쌍대 비교: 비교 대상이 존재하는 해소만 집계 (불공정 비교 차단)
DROP VIEW IF EXISTS v_benchmark_pairwise;
CREATE VIEW v_benchmark_pairwise AS
SELECT 'llm_vs_ml' AS pair, COUNT(*) AS n,
       AVG(llm_brier) AS llm_brier, AVG(ml_brier) AS other_brier
FROM benchmark_scores WHERE ml_brier IS NOT NULL
UNION ALL
SELECT 'llm_vs_market', COUNT(*), AVG(llm_brier), AVG(market_brier)
FROM benchmark_scores WHERE market_brier IS NOT NULL
UNION ALL
SELECT 'all_three', COUNT(*), AVG(llm_brier),
       (AVG(ml_brier) + AVG(market_brier)) / 2
FROM benchmark_scores WHERE ml_brier IS NOT NULL AND market_brier IS NOT NULL;

-- ── 뷰 ─────────────────────────────────────────────────────────

DROP VIEW IF EXISTS v_brier;
CREATE VIEW v_brier AS
SELECT '(전체)' AS domain, COUNT(*) AS n, AVG(brier) AS brier FROM resolutions
UNION ALL
SELECT domain, COUNT(*) AS n, AVG(brier) AS brier FROM resolutions GROUP BY domain;

-- AUDIT-260715 8-2(c) 활성 (사용자 위임 결정 2026-07-15):
-- 원장은 전량 채점(투명·append-only 유지). 대표 Brier·게이트는 primary
-- (research_status='failed' 제외 — frontmatter 또는 메타 오버라이드) 기준.
-- primary가 더 보수적: 표본 n이 작아져 게이트 통과가 늦어진다.
DROP VIEW IF EXISTS v_brier_all;
CREATE VIEW v_brier_all AS SELECT * FROM v_brier;

DROP VIEW IF EXISTS v_brier_primary;
CREATE VIEW v_brier_primary AS
SELECT '(전체)' AS domain, COUNT(*) AS n, AVG(r.brier) AS brier
FROM resolutions r
LEFT JOIN forecasts f ON f.forecast_id = r.forecast_id
LEFT JOIN research_status_override o ON o.forecast_id = r.forecast_id
WHERE COALESCE(o.status, f.research_status, 'ok') != 'failed'
UNION ALL
SELECT r.domain, COUNT(*) AS n, AVG(r.brier) AS brier
FROM resolutions r
LEFT JOIN forecasts f ON f.forecast_id = r.forecast_id
LEFT JOIN research_status_override o ON o.forecast_id = r.forecast_id
WHERE COALESCE(o.status, f.research_status, 'ok') != 'failed' GROUP BY r.domain;

-- 도메인 차단: primary/all 양쪽 평가 — 하나라도 걸리면 차단 (RE-AUDIT U-2:
-- failed 밀집 도메인이 primary 단독 평가에서 무능을 은폐하는 채널 차단)
DROP VIEW IF EXISTS v_domain_skill;
CREATE VIEW v_domain_skill AS
SELECT a.domain, a.n AS n, a.brier AS brier,
       p.n AS n_primary, p.brier AS brier_primary,
       ((a.brier > 0.22 AND a.n >= 10)
        OR (COALESCE(p.brier, 0) > 0.22 AND COALESCE(p.n, 0) >= 10)) AS blocked
FROM (SELECT domain, COUNT(*) n, AVG(brier) brier
      FROM resolutions GROUP BY domain) a
LEFT JOIN (SELECT r.domain, COUNT(*) n, AVG(r.brier) brier
           FROM resolutions r
           LEFT JOIN forecasts f ON f.forecast_id = r.forecast_id
           LEFT JOIN research_status_override o ON o.forecast_id = r.forecast_id
           WHERE COALESCE(o.status, f.research_status, 'ok') != 'failed'
           GROUP BY r.domain) p ON p.domain = a.domain;

DROP VIEW IF EXISTS v_calibration_curve;
CREATE VIEW v_calibration_curve AS
SELECT MIN(probability / 10, 9) AS decile,
       COUNT(*) AS n,
       AVG(probability) / 100.0 AS avg_forecast,
       AVG(outcome) AS avg_outcome
FROM resolutions GROUP BY decile;

-- 게이트 판정은 primary 기준 (8-2(c) — failed 예측 제외라 표본이 작아져 더 보수적).
-- 전량 기준은 v_gate_status_all로 참조 가능.
DROP VIEW IF EXISTS v_gate_status;
CREATE VIEW v_gate_status AS
SELECT COUNT(*) AS n_resolved,
       AVG(r.brier) AS brier,
       (COUNT(*) >= 30 AND AVG(r.brier) < 0.20) AS gate_p2,
       (COUNT(*) >= 50 AND AVG(r.brier) < 0.18) AS gate_p3
FROM resolutions r
LEFT JOIN forecasts f ON f.forecast_id = r.forecast_id
LEFT JOIN research_status_override o ON o.forecast_id = r.forecast_id
WHERE COALESCE(o.status, f.research_status, 'ok') != 'failed';

DROP VIEW IF EXISTS v_gate_status_all;
CREATE VIEW v_gate_status_all AS
SELECT COUNT(*) AS n_resolved,
       AVG(brier) AS brier,
       (COUNT(*) >= 30 AND AVG(brier) < 0.20) AS gate_p2,
       (COUNT(*) >= 50 AND AVG(brier) < 0.18) AS gate_p3
FROM resolutions;

DROP VIEW IF EXISTS v_latest_forecast;
CREATE VIEW v_latest_forecast AS
SELECT question_id,
       MAX(round) AS last_round,
       MAX(forecast_ts) AS last_ts,
       MAX(window_end) AS last_window_end
FROM forecasts GROUP BY question_id;
