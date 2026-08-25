BEGIN;

CREATE SCHEMA IF NOT EXISTS timeseries_v6;

CREATE OR REPLACE FUNCTION timeseries_v6.reject_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'timeseries_v6 append-only table % rejects %', TG_TABLE_NAME, TG_OP;
END;
$$;

CREATE TABLE IF NOT EXISTS timeseries_v6.source_registry (
  source_id text PRIMARY KEY,
  provider text NOT NULL,
  authority_class text NOT NULL CHECK (authority_class IN ('official','licensed','academic','research_reference')),
  adapter_status text NOT NULL CHECK (adapter_status IN ('implemented','blocked_no_history','forward_capture','licensed_unavailable','retired')),
  data_grade text NOT NULL CHECK (data_grade IN ('native_pit','reconstructed_official_archive','captured_forward','licensed_reference_only','quarantined')),
  availability_policy_version text NOT NULL,
  source_uri_template text NOT NULL CHECK (source_uri_template !~* '(api_?key|token|secret|password)='),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS timeseries_v6.collection_attempt (
  attempt_id text PRIMARY KEY,
  source_id text NOT NULL REFERENCES timeseries_v6.source_registry(source_id),
  scheduled_for timestamptz NOT NULL,
  retry_sequence integer NOT NULL DEFAULT 0 CHECK (retry_sequence >= 0),
  started_at timestamptz NOT NULL,
  completed_at timestamptz,
  terminal_status text CHECK (terminal_status IN ('success','not_modified','retryable_failure','permanent_failure','blocked_secret','schema_quarantine','cancelled')),
  terminal_reason_code text,
  request_fingerprint_sha256 char(64) NOT NULL CHECK (request_fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
  UNIQUE (source_id, scheduled_for, retry_sequence),
  CHECK ((completed_at IS NULL AND terminal_status IS NULL) OR (completed_at IS NOT NULL AND terminal_status IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS timeseries_v6.raw_object (
  object_sha256 char(64) PRIMARY KEY CHECK (object_sha256 ~ '^[0-9a-f]{64}$'),
  stored_sha256 char(64) NOT NULL CHECK (stored_sha256 ~ '^[0-9a-f]{64}$'),
  decompressed_bytes bigint NOT NULL CHECK (decompressed_bytes >= 0),
  stored_bytes bigint NOT NULL CHECK (stored_bytes >= 0),
  object_uri text NOT NULL UNIQUE CHECK (object_uri !~* '(api_?key|token|secret|password)='),
  compression text NOT NULL CHECK (compression IN ('none','gzip','zstd')),
  encryption_status text NOT NULL CHECK (encryption_status IN ('provider_managed','customer_managed','local_ci_unencrypted')),
  license_class text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS timeseries_v6.receipt (
  receipt_id text PRIMARY KEY,
  source_id text NOT NULL REFERENCES timeseries_v6.source_registry(source_id),
  attempt_id text NOT NULL REFERENCES timeseries_v6.collection_attempt(attempt_id),
  object_sha256 char(64) NOT NULL REFERENCES timeseries_v6.raw_object(object_sha256),
  fetched_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL,
  http_status integer NOT NULL CHECK (http_status BETWEEN 100 AND 599),
  media_type text NOT NULL,
  schema_fingerprint_sha256 char(64) NOT NULL CHECK (schema_fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
  parser_version text NOT NULL,
  UNIQUE (attempt_id, object_sha256)
);

CREATE TABLE IF NOT EXISTS timeseries_v6.receipt_terminal_outcome (
  receipt_id text PRIMARY KEY REFERENCES timeseries_v6.receipt(receipt_id),
  outcome_status text NOT NULL CHECK (outcome_status IN ('parsed','empty_valid','schema_quarantine','parser_failure','license_blocked')),
  observation_count integer NOT NULL CHECK (observation_count >= 0),
  reason_code text,
  recorded_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS timeseries_v6.observation_key (
  observation_key_id text PRIMARY KEY,
  source_id text NOT NULL REFERENCES timeseries_v6.source_registry(source_id),
  series_id text NOT NULL,
  observation_time timestamptz NOT NULL,
  unit text NOT NULL,
  semantic_type text NOT NULL,
  UNIQUE (source_id, series_id, observation_time, unit, semantic_type)
);

CREATE TABLE IF NOT EXISTS timeseries_v6.observation_version (
  observation_version_id text PRIMARY KEY,
  observation_key_id text NOT NULL REFERENCES timeseries_v6.observation_key(observation_key_id),
  revision_seq integer NOT NULL CHECK (revision_seq >= 0),
  value_numeric double precision,
  value_text text,
  available_at timestamptz NOT NULL,
  vintage_start date,
  vintage_end date,
  raw_object_sha256 char(64) NOT NULL REFERENCES timeseries_v6.raw_object(object_sha256),
  supersedes_observation_version_id text REFERENCES timeseries_v6.observation_version(observation_version_id),
  status text NOT NULL CHECK (status IN ('active','superseded','quarantined')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (observation_key_id, revision_seq),
  CHECK ((value_numeric IS NOT NULL)::integer + (value_text IS NOT NULL)::integer = 1),
  CHECK ((revision_seq = 0 AND supersedes_observation_version_id IS NULL) OR (revision_seq > 0 AND supersedes_observation_version_id IS NOT NULL)),
  CHECK (vintage_end IS NULL OR vintage_start IS NULL OR vintage_end >= vintage_start)
);

CREATE TABLE IF NOT EXISTS timeseries_v6.receipt_fact_link (
  receipt_id text NOT NULL REFERENCES timeseries_v6.receipt(receipt_id),
  observation_version_id text NOT NULL REFERENCES timeseries_v6.observation_version(observation_version_id),
  relation text NOT NULL CHECK (relation IN ('parsed_from','revision_evidence','cross_check')),
  PRIMARY KEY (receipt_id, observation_version_id, relation)
);

CREATE TABLE IF NOT EXISTS timeseries_v6.dataset_snapshot (
  dataset_snapshot_id text PRIMARY KEY,
  contract_hash char(64) NOT NULL CHECK (contract_hash ~ '^[0-9a-f]{64}$'),
  partition_manifest_sha256 char(64) NOT NULL CHECK (partition_manifest_sha256 ~ '^[0-9a-f]{64}$'),
  knowledge_cutoff timestamptz NOT NULL,
  source_count integer NOT NULL CHECK (source_count >= 0),
  observation_version_count bigint NOT NULL CHECK (observation_version_count >= 0),
  object_manifest_uri text NOT NULL,
  created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS timeseries_v6.task_queue (
  task_id text PRIMARY KEY,
  task_type text NOT NULL,
  required_capability text NOT NULL,
  state text NOT NULL CHECK (state IN ('pending','leased','running','validating','succeeded','retry','blocked','hold','failed','cancelled')),
  priority integer NOT NULL CHECK (priority BETWEEN 0 AND 1000),
  dependency_task_ids text[] NOT NULL DEFAULT '{}',
  task_payload_sha256 char(64) NOT NULL CHECK (task_payload_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS timeseries_v6.score (
  score_id text PRIMARY KEY,
  backtest_run_id text NOT NULL,
  origin_id text NOT NULL,
  horizon_sessions integer NOT NULL CHECK (horizon_sessions IN (1,5,21,63)),
  candidate_id text NOT NULL,
  metric_name text NOT NULL,
  metric_value double precision NOT NULL CHECK (metric_value NOT IN ('NaN'::double precision, 'Infinity'::double precision, '-Infinity'::double precision)),
  comparator_metric_value double precision CHECK (comparator_metric_value IS NULL OR comparator_metric_value NOT IN ('NaN'::double precision, 'Infinity'::double precision, '-Infinity'::double precision)),
  sample_role text NOT NULL CHECK (sample_role IN ('research','inner_selection','inner_stacking','inner_calibration','outer_test','qualification','prospective')),
  recorded_at timestamptz NOT NULL,
  UNIQUE (backtest_run_id, origin_id, horizon_sessions, candidate_id, metric_name, sample_role)
);

CREATE TABLE IF NOT EXISTS timeseries_v6.gate_decision (
  gate_decision_id text PRIMARY KEY,
  backtest_run_id text NOT NULL,
  gate_type text NOT NULL CHECK (gate_type IN ('integrity','research','operational','qualification','prospective')),
  gate_pass boolean NOT NULL,
  reason_code text NOT NULL,
  score_snapshot_sha256 char(64) NOT NULL CHECK (score_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
  contract_hash char(64) NOT NULL CHECK (contract_hash ~ '^[0-9a-f]{64}$'),
  decided_at timestamptz NOT NULL,
  UNIQUE (backtest_run_id, gate_type, score_snapshot_sha256, contract_hash)
);

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'source_registry','raw_object','receipt','receipt_terminal_outcome',
    'observation_key','observation_version','receipt_fact_link',
    'dataset_snapshot','score','gate_decision'
  ]
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS reject_mutation ON timeseries_v6.%I', table_name);
    EXECUTE format(
      'CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON timeseries_v6.%I '
      'FOR EACH ROW EXECUTE FUNCTION timeseries_v6.reject_mutation()',
      table_name
    );
  END LOOP;
END;
$$;

COMMIT;
