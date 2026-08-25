BEGIN;

CREATE TABLE IF NOT EXISTS source_registry (
  source_id TEXT PRIMARY KEY, authority_class TEXT NOT NULL, provider TEXT NOT NULL,
  base_uri TEXT NOT NULL, license_id TEXT NOT NULL, redistribution TEXT NOT NULL,
  cadence TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS research_append_ledger (
  ledger_name TEXT NOT NULL, identity_value TEXT NOT NULL, payload JSONB NOT NULL,
  appended_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ledger_name, identity_value)
);
CREATE TABLE IF NOT EXISTS ingestion_run (
  run_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source_registry(source_id),
  mode TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ,
  status TEXT NOT NULL, checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS raw_object (
  sha256 CHAR(64) PRIMARY KEY, object_uri TEXT NOT NULL, size_bytes BIGINT NOT NULL,
  content_type TEXT NOT NULL, compression TEXT NOT NULL, object_version TEXT,
  encryption TEXT, license_id TEXT NOT NULL, redistribution TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_receipt (
  receipt_id TEXT PRIMARY KEY, run_id TEXT REFERENCES ingestion_run(run_id),
  source_id TEXT NOT NULL REFERENCES source_registry(source_id), raw_sha256 CHAR(64) NOT NULL REFERENCES raw_object(sha256),
  source_uri TEXT NOT NULL, request_fingerprint CHAR(64) NOT NULL, retrieved_at TIMESTAMPTZ NOT NULL,
  http_status INTEGER NOT NULL, etag TEXT, last_modified TEXT, schema_fingerprint CHAR(64)
);
CREATE TABLE IF NOT EXISTS receipt_parse_outcome (
  outcome_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL REFERENCES raw_receipt(receipt_id),
  outcome TEXT NOT NULL, parser_version TEXT NOT NULL, fact_count BIGINT NOT NULL DEFAULT 0,
  reason TEXT, created_at TIMESTAMPTZ NOT NULL,
  CHECK (outcome IN ('new_facts','revised_facts','unchanged_facts','no_fact_expected','rejected','quarantined','parse_failed','schema_drift'))
);
CREATE TABLE IF NOT EXISTS series_registry (
  series_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source_registry(source_id),
  unit TEXT NOT NULL, frequency TEXT NOT NULL, required_core BOOLEAN NOT NULL DEFAULT FALSE,
  data_grade TEXT NOT NULL, availability_policy TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observation_key (
  observation_key_id TEXT PRIMARY KEY, series_id TEXT NOT NULL REFERENCES series_registry(series_id),
  observation_time TIMESTAMPTZ NOT NULL, dimension_hash CHAR(64) NOT NULL,
  UNIQUE(series_id, observation_time, dimension_hash)
);
CREATE TABLE IF NOT EXISTS observation_version (
  observation_version_id TEXT PRIMARY KEY, observation_key_id TEXT NOT NULL REFERENCES observation_key(observation_key_id),
  revision_seq INTEGER NOT NULL, value DOUBLE PRECISION NOT NULL, unit TEXT NOT NULL,
  available_at TIMESTAMPTZ NOT NULL, vintage_start TIMESTAMPTZ, vintage_end TIMESTAMPTZ,
  data_grade TEXT NOT NULL, source_id TEXT NOT NULL, receipt_id TEXT NOT NULL REFERENCES raw_receipt(receipt_id),
  normalization_rule_version TEXT NOT NULL, parser_semantic_version TEXT NOT NULL,
  supersedes TEXT REFERENCES observation_version(observation_version_id), created_at TIMESTAMPTZ NOT NULL,
  UNIQUE(observation_key_id, revision_seq)
);
CREATE TABLE IF NOT EXISTS receipt_fact_link (
  receipt_id TEXT NOT NULL REFERENCES raw_receipt(receipt_id),
  observation_version_id TEXT REFERENCES observation_version(observation_version_id),
  relation TEXT NOT NULL, PRIMARY KEY(receipt_id, observation_version_id, relation)
);
CREATE TABLE IF NOT EXISTS market_session (
  session_id TEXT PRIMARY KEY, exchange TEXT NOT NULL, session_date DATE NOT NULL,
  open_at TIMESTAMPTZ NOT NULL, close_at TIMESTAMPTZ NOT NULL,
  calendar_hash CHAR(64) NOT NULL, UNIQUE(exchange, session_date)
);
CREATE TABLE IF NOT EXISTS forecast_origin (
  origin_id TEXT PRIMARY KEY, exchange TEXT NOT NULL, session_id TEXT NOT NULL REFERENCES market_session(session_id),
  origin_cutoff_at TIMESTAMPTZ NOT NULL, cutoff_policy_id TEXT NOT NULL,
  label_start_session_id TEXT NOT NULL REFERENCES market_session(session_id), created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS feature_snapshot (
  snapshot_id TEXT PRIMARY KEY, origin_id TEXT NOT NULL REFERENCES forecast_origin(origin_id),
  object_uri TEXT NOT NULL, content_hash CHAR(64) NOT NULL, row_count BIGINT NOT NULL,
  missing_required JSONB NOT NULL DEFAULT '[]'::jsonb, created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS label (
  label_id TEXT PRIMARY KEY, origin_id TEXT NOT NULL REFERENCES forecast_origin(origin_id),
  horizon_sessions INTEGER NOT NULL, maturity_session_id TEXT NOT NULL REFERENCES market_session(session_id),
  value DOUBLE PRECISION, matured_at TIMESTAMPTZ, status TEXT NOT NULL,
  UNIQUE(origin_id, horizon_sessions)
);
CREATE TABLE IF NOT EXISTS candidate_spec (
  candidate_id TEXT PRIMARY KEY, model_id TEXT NOT NULL, contract_hash CHAR(64) NOT NULL,
  spec JSONB NOT NULL, frozen_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS backtest_run (
  backtest_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidate_spec(candidate_id),
  dataset_snapshot_id TEXT NOT NULL, comparator_id TEXT NOT NULL,
  status TEXT NOT NULL, metrics JSONB NOT NULL, content_hash CHAR(64) NOT NULL,
  started_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS fold_score (
  backtest_id TEXT NOT NULL REFERENCES backtest_run(backtest_id), origin_id TEXT NOT NULL,
  horizon_sessions INTEGER NOT NULL, actual DOUBLE PRECISION NOT NULL,
  model_crps DOUBLE PRECISION NOT NULL, comparator_crps DOUBLE PRECISION NOT NULL,
  payload JSONB NOT NULL, PRIMARY KEY(backtest_id, origin_id, horizon_sessions)
);
CREATE TABLE IF NOT EXISTS promotion_decision (
  decision_id TEXT PRIMARY KEY, model_id TEXT NOT NULL, decision TEXT NOT NULL,
  research_gate_pass BOOLEAN NOT NULL, operational_gate_pass BOOLEAN NOT NULL,
  approved_by TEXT, approved_at TIMESTAMPTZ, evidence JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS task_queue (
  task_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, task_type TEXT NOT NULL, priority INTEGER NOT NULL,
  state TEXT NOT NULL, dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
  lease_owner TEXT, lease_token_hash CHAR(64), leased_at TIMESTAMPTZ,
  lease_expires_at TIMESTAMPTZ, heartbeat_at TIMESTAMPTZ, attempt_count INTEGER NOT NULL DEFAULT 0,
  checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb, last_error_class TEXT, blocker_signature TEXT,
  created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS task_attempt (
  attempt_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES task_queue(task_id),
  status TEXT NOT NULL, envelope JSONB NOT NULL, result JSONB,
  started_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS worker_heartbeat (
  worker_id TEXT PRIMARY KEY, capability TEXT NOT NULL, heartbeat_at TIMESTAMPTZ NOT NULL,
  state JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS audit_event (
  audit_id BIGSERIAL PRIMARY KEY, run_id TEXT, task_id TEXT, event_type TEXT NOT NULL,
  payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
