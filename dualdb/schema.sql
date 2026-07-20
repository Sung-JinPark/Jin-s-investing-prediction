-- 닷컴↔AI 이중시대 정량 비교 DB — 스펙 v1.0 §3 DDL 그대로.
PRAGMA journal_mode=WAL;

-- ── 차원 ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS era (
  era_id TEXT PRIMARY KEY,              -- 'dotcom' | 'ai'
  anchor_month TEXT NOT NULL,           -- '1996-01' | '2023-01'
  peak_date TEXT, bottom_date TEXT,     -- 닷컴: 2000-03-10 / 2002-10-09. AI: NULL(미확정)
  note TEXT);

CREATE TABLE IF NOT EXISTS role (
  role_code TEXT PRIMARY KEY,
  name_kr TEXT, layer INTEGER,          -- 1장비→2인프라→3플랫폼→4앱→5B2B
  description TEXT);

CREATE TABLE IF NOT EXISTS entity (
  entity_id INTEGER PRIMARY KEY,
  era_id TEXT REFERENCES era(era_id), ticker TEXT, name TEXT,
  role_code TEXT REFERENCES role(role_code),
  status TEXT CHECK(status IN ('alive','dead','acquired','renamed')),
  data_ticker TEXT,
  listing_date TEXT, delisting_date TEXT,
  is_twin INTEGER DEFAULT 0,
  survivorship_note TEXT, source_note TEXT);

CREATE TABLE IF NOT EXISTS alignment (
  method TEXT,                          -- 'calendar_m' | 'event' | 'dtw'
  cycle_index REAL,
  event_name TEXT DEFAULT '',
  dotcom_date TEXT, ai_date TEXT,
  PRIMARY KEY(method, cycle_index, event_name));

-- ── 원천(raw 계층 — 추정치·보간치 저장 금지) ─────────
CREATE TABLE IF NOT EXISTS price_daily (
  series TEXT, date TEXT,
  open REAL, high REAL, low REAL, close REAL, adj_close REAL, volume REAL,
  source TEXT NOT NULL, ingested_at TEXT NOT NULL,
  PRIMARY KEY(series, date));

CREATE TABLE IF NOT EXISTS macro_daily (
  series_id TEXT, date TEXT, value REAL, source TEXT, ingested_at TEXT,
  PRIMARY KEY(series_id, date));

CREATE TABLE IF NOT EXISTS macro_monthly (
  series_id TEXT, date TEXT, value REAL, source TEXT, ingested_at TEXT,
  PRIMARY KEY(series_id, date));

CREATE TABLE IF NOT EXISTS ipo_annual (
  year INTEGER PRIMARY KEY, ipo_count INTEGER, tech_count INTEGER,
  mean_first_day_ret REAL, pct_negative_eps REAL,
  proceeds_bil REAL, source TEXT, ingested_at TEXT);

CREATE TABLE IF NOT EXISTS sentiment_weekly (
  date TEXT PRIMARY KEY, bull REAL, neutral REAL, bear REAL,
  source TEXT, ingested_at TEXT);

CREATE TABLE IF NOT EXISTS margin_debt_monthly (
  date TEXT PRIMARY KEY, debit_bil REAL, credit_bil REAL, source TEXT, ingested_at TEXT);

CREATE TABLE IF NOT EXISTS valuation_monthly (
  scope TEXT, date TEXT,
  pe_ttm REAL, pe_fwd REAL, ps REAL, cape REAL,
  tier INTEGER NOT NULL, source TEXT, ingested_at TEXT,
  PRIMARY KEY(scope, date));

CREATE TABLE IF NOT EXISTS fundamentals_annual (
  entity_id INTEGER REFERENCES entity(entity_id), fiscal_year INTEGER,
  revenue_mil REAL, gross_margin REAL, capex_mil REAL, eps REAL,
  tier INTEGER, source TEXT, ingested_at TEXT,
  PRIMARY KEY(entity_id, fiscal_year));

CREATE TABLE IF NOT EXISTS capex_buildout_annual (
  era_id TEXT, year INTEGER, capex_bil REAL, gdp_pct REAL,
  tier INTEGER, source TEXT, note TEXT, PRIMARY KEY(era_id, year));

CREATE TABLE IF NOT EXISTS event (
  event_id INTEGER PRIMARY KEY, era_id TEXT, date TEXT,
  type TEXT,
  title TEXT, magnitude REAL,
  cycle_month REAL, source_url TEXT, note TEXT);

CREATE TABLE IF NOT EXISTS dotcom_casualty (
  name TEXT PRIMARY KEY, role_code TEXT, peak_mcap_bil REAL, peak_date TEXT,
  outcome TEXT,
  months_after_index_peak REAL, source TEXT);

-- ── 파생(derived 계층 — 전량 재계산 가능) ──────────
CREATE TABLE IF NOT EXISTS derived_daily (
  series TEXT, date TEXT, era_id TEXT, cycle_day INTEGER,
  ret_1d REAL, vol_20d REAL, vol_60d REAL,
  ath_to_date REAL, drawdown REAL,
  dist_200dma REAL, rsi_14 REAL, norm_m0 REAL,
  PRIMARY KEY(series, date));

CREATE TABLE IF NOT EXISTS correction_episode (
  series TEXT, era_id TEXT, peak_date TEXT, trough_date TEXT, recover_date TEXT,
  depth REAL, dur_days INTEGER, recover_days INTEGER, cycle_month_at_peak REAL,
  PRIMARY KEY(series, peak_date));

CREATE TABLE IF NOT EXISTS cycle_compare (
  method TEXT, cycle_index REAL, metric TEXT,
  dotcom_value REAL, ai_value REAL, ratio REAL, zgap REAL,
  computed_at TEXT, PRIMARY KEY(method, cycle_index, metric));

CREATE TABLE IF NOT EXISTS model_run (
  run_id INTEGER PRIMARY KEY, model TEXT, asof TEXT,
  params_json TEXT, output_json TEXT, created_at TEXT);

CREATE INDEX IF NOT EXISTS idx_price_date ON price_daily(date);
CREATE INDEX IF NOT EXISTS idx_event_era ON event(era_id, date);
