BEGIN;
CREATE SCHEMA IF NOT EXISTS timeseries_v7;

CREATE FUNCTION timeseries_v7.reject_immutable_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'immutable V7 evidence table % does not allow %', TG_TABLE_NAME, TG_OP
    USING ERRCODE = '55000';
END;
$$;

CREATE TABLE timeseries_v7.research_run (
  run_id text PRIMARY KEY, model_id text NOT NULL, contract_hash char(64) NOT NULL,
  protected_predecessor_hash char(64) NOT NULL,
  state text NOT NULL CHECK (state IN ('running','wait_data','hold','failed','completed','cancelled')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE timeseries_v7.data_cycle (
  run_id text NOT NULL REFERENCES timeseries_v7.research_run(run_id), cycle_id text NOT NULL,
  knowledge_cutoff timestamptz NOT NULL, trigger_reason text NOT NULL, input_snapshot_hash char(64),
  state text NOT NULL CHECK (state IN ('collecting','materializing','ready','wait_data','hold','failed','completed')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY (run_id, cycle_id)
);
CREATE TABLE timeseries_v7.research_generation (
  run_id text NOT NULL, cycle_id text NOT NULL, generation_id text NOT NULL,
  parent_generation_id text, hypothesis_id text NOT NULL, contract_hash char(64) NOT NULL,
  code_hash char(64) NOT NULL, runtime_hash char(64) NOT NULL, dataset_snapshot_hash char(64) NOT NULL,
  state text NOT NULL CHECK (state IN ('planned','training','qualifying','qualified','failed','hold','frozen','prospective','review_ready')),
  opened_at timestamptz NOT NULL DEFAULT clock_timestamp(), frozen_at timestamptz,
  PRIMARY KEY (run_id, cycle_id, generation_id),
  FOREIGN KEY (run_id, cycle_id) REFERENCES timeseries_v7.data_cycle(run_id, cycle_id)
);
CREATE TABLE timeseries_v7.source_registry (
  source_id text PRIMARY KEY, provider text NOT NULL,
  data_grade text NOT NULL CHECK (data_grade IN ('native_pit','reconstructed_official_archive','captured_forward','licensed_reference_only','quarantined')),
  availability_policy_version text NOT NULL, collector_version text NOT NULL,
  lifecycle_state text NOT NULL CHECK (lifecycle_state IN ('declared','implemented','fixture_verified','forward_capture_active','history_available','model_eligible','retired')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE timeseries_v7.collection_attempt (
  attempt_id text PRIMARY KEY, run_id text NOT NULL, cycle_id text NOT NULL,
  source_id text NOT NULL REFERENCES timeseries_v7.source_registry(source_id),
  idempotency_key char(64) NOT NULL UNIQUE, scheduled_for timestamptz NOT NULL,
  started_at timestamptz, completed_at timestamptz,
  state text NOT NULL CHECK (state IN ('scheduled','running','success','not_modified','retryable_failure','permanent_failure','schema_quarantine','cancelled')),
  request_hash char(64) NOT NULL, response_object_sha256 char(64),
  FOREIGN KEY (run_id, cycle_id) REFERENCES timeseries_v7.data_cycle(run_id, cycle_id)
);
CREATE TABLE timeseries_v7.raw_object (
  object_sha256 char(64) PRIMARY KEY, physical_sha256 char(64) NOT NULL,
  object_uri text NOT NULL UNIQUE, media_type text NOT NULL, compression text NOT NULL,
  byte_count bigint NOT NULL CHECK (byte_count >= 0), license_class text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE timeseries_v7.receipt (
  receipt_id text PRIMARY KEY, attempt_id text NOT NULL REFERENCES timeseries_v7.collection_attempt(attempt_id),
  source_id text NOT NULL REFERENCES timeseries_v7.source_registry(source_id),
  object_sha256 char(64) NOT NULL REFERENCES timeseries_v7.raw_object(object_sha256),
  fetched_at timestamptz NOT NULL, schema_fingerprint char(64) NOT NULL, parser_version text NOT NULL,
  UNIQUE (attempt_id, object_sha256)
);
CREATE TABLE timeseries_v7.receipt_terminal_outcome (
  receipt_id text PRIMARY KEY REFERENCES timeseries_v7.receipt(receipt_id),
  outcome text NOT NULL CHECK (outcome IN ('parsed_new','parsed_revision','unchanged','empty_valid','quarantined','parser_failure','license_blocked')),
  observation_count integer NOT NULL CHECK (observation_count >= 0), reason_code text,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE timeseries_v7.observation_key (
  observation_key_id text PRIMARY KEY, source_id text NOT NULL REFERENCES timeseries_v7.source_registry(source_id),
  series_id text NOT NULL, entity_id text NOT NULL DEFAULT '', observation_time timestamptz NOT NULL,
  unit text NOT NULL, semantic_type text NOT NULL,
  UNIQUE (source_id, series_id, entity_id, observation_time, unit, semantic_type)
);
CREATE TABLE timeseries_v7.observation_revision (
  observation_revision_id text PRIMARY KEY,
  observation_key_id text NOT NULL REFERENCES timeseries_v7.observation_key(observation_key_id),
  revision_seq integer NOT NULL CHECK (revision_seq >= 0), value_numeric double precision, value_text text,
  available_at timestamptz NOT NULL, ingested_at timestamptz NOT NULL, valid_from timestamptz NOT NULL,
  valid_to timestamptz, raw_object_sha256 char(64) NOT NULL REFERENCES timeseries_v7.raw_object(object_sha256),
  parser_version text NOT NULL, normalization_version text NOT NULL, data_grade text NOT NULL,
  supersedes_revision_id text REFERENCES timeseries_v7.observation_revision(observation_revision_id),
  UNIQUE (observation_key_id, revision_seq),
  CHECK ((value_numeric IS NOT NULL)::int + (value_text IS NOT NULL)::int = 1),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE TABLE timeseries_v7.receipt_fact_link (
  receipt_id text NOT NULL REFERENCES timeseries_v7.receipt(receipt_id),
  observation_revision_id text NOT NULL REFERENCES timeseries_v7.observation_revision(observation_revision_id),
  relation text NOT NULL CHECK (relation IN ('parsed_from','revision_evidence','cross_check')),
  PRIMARY KEY (receipt_id, observation_revision_id, relation)
);
CREATE TABLE timeseries_v7.dataset_snapshot (
  dataset_snapshot_id text PRIMARY KEY, run_id text NOT NULL, cycle_id text NOT NULL,
  knowledge_cutoff timestamptz NOT NULL, contract_hash char(64) NOT NULL,
  logical_manifest_hash char(64) NOT NULL, physical_manifest_hash char(64) NOT NULL,
  object_manifest_uri text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY (run_id, cycle_id) REFERENCES timeseries_v7.data_cycle(run_id, cycle_id)
);
CREATE TABLE timeseries_v7.feature_definition (
  feature_id text PRIMARY KEY, definition_hash char(64) NOT NULL UNIQUE,
  transformation text NOT NULL, missingness_policy text NOT NULL, data_grade_floor text NOT NULL,
  active boolean NOT NULL
);
CREATE TABLE timeseries_v7.feature_value_lineage (
  dataset_snapshot_id text NOT NULL REFERENCES timeseries_v7.dataset_snapshot(dataset_snapshot_id),
  origin_id text NOT NULL, feature_id text NOT NULL REFERENCES timeseries_v7.feature_definition(feature_id),
  value_numeric double precision, missing_flag boolean NOT NULL, stale_flag boolean NOT NULL,
  age_seconds bigint, max_available_at timestamptz, origin_cutoff_at timestamptz NOT NULL,
  source_revision_ids text[] NOT NULL, feature_definition_hash char(64) NOT NULL, eligible boolean NOT NULL,
  PRIMARY KEY (dataset_snapshot_id, origin_id, feature_id),
  CHECK (NOT eligible OR max_available_at IS NULL OR max_available_at <= origin_cutoff_at)
);
CREATE TABLE timeseries_v7.label_interval (
  dataset_snapshot_id text NOT NULL REFERENCES timeseries_v7.dataset_snapshot(dataset_snapshot_id),
  origin_id text NOT NULL, horizon_sessions integer NOT NULL CHECK (horizon_sessions IN (1,5,21,63)),
  origin_session date NOT NULL, label_start_session date NOT NULL, label_end_session date NOT NULL,
  mature_at timestamptz NOT NULL, value double precision,
  PRIMARY KEY (dataset_snapshot_id, origin_id, horizon_sessions),
  CHECK (origin_session < label_start_session AND label_start_session <= label_end_session)
);
CREATE TABLE timeseries_v7.task (
  run_id text NOT NULL, cycle_id text NOT NULL, generation_id text NOT NULL DEFAULT '',
  task_key text NOT NULL, task_type text NOT NULL, required_capability text NOT NULL,
  state text NOT NULL CHECK (state IN ('pending','ready','leased','running','validating','retry_wait','succeeded','skipped_dependency','blocked','hold','failed','cancelled','wait_data')),
  priority integer NOT NULL DEFAULT 100, payload_hash char(64) NOT NULL,
  input_snapshot_hash char(64) NOT NULL, idempotency_key char(64) NOT NULL UNIQUE,
  attempt_count integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0), lease_owner text,
  fencing_token bigint NOT NULL DEFAULT 0, lease_expires_at timestamptz, heartbeat_at timestamptz,
  next_attempt_at timestamptz, cancellation_requested_at timestamptz,
  checkpoint_uri text, checkpoint_hash char(64), result_artifact_uri text, result_artifact_hash char(64),
  blocker_fingerprint char(64),
  blocker_repetitions integer NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (run_id, cycle_id, generation_id, task_key)
);
CREATE TABLE timeseries_v7.task_dependency (
  run_id text NOT NULL, cycle_id text NOT NULL, generation_id text NOT NULL DEFAULT '',
  task_key text NOT NULL, dependency_generation_id text NOT NULL DEFAULT '', dependency_task_key text NOT NULL,
  PRIMARY KEY (run_id, cycle_id, generation_id, task_key, dependency_generation_id, dependency_task_key),
  FOREIGN KEY (run_id, cycle_id, generation_id, task_key)
    REFERENCES timeseries_v7.task(run_id, cycle_id, generation_id, task_key)
);
CREATE INDEX task_lease_idx ON timeseries_v7.task
  (state, required_capability, priority DESC, created_at)
  WHERE state IN ('pending','ready','retry_wait','leased','running');
CREATE TABLE timeseries_v7.task_event (
  event_id bigserial PRIMARY KEY, run_id text NOT NULL, cycle_id text NOT NULL,
  generation_id text NOT NULL DEFAULT '', task_key text NOT NULL, fencing_token bigint NOT NULL,
  event_type text NOT NULL, payload_json jsonb NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE timeseries_v7.experiment (
  experiment_id text PRIMARY KEY, run_id text NOT NULL, cycle_id text NOT NULL, generation_id text NOT NULL,
  candidate_id text NOT NULL, horizon_sessions integer NOT NULL CHECK (horizon_sessions IN (1,5,21,63)),
  fold_role text NOT NULL, candidate_spec_hash char(64) NOT NULL, feature_schema_hash char(64) NOT NULL,
  dataset_snapshot_hash char(64) NOT NULL, code_hash char(64) NOT NULL, runtime_hash char(64) NOT NULL,
  status text NOT NULL, result_uri text, result_hash char(64),
  UNIQUE (run_id, cycle_id, generation_id, candidate_id, horizon_sessions, fold_role,
    candidate_spec_hash, feature_schema_hash, dataset_snapshot_hash, code_hash, runtime_hash)
);
CREATE TABLE timeseries_v7.prediction (
  prediction_id text PRIMARY KEY, run_id text NOT NULL, cycle_id text NOT NULL, generation_id text NOT NULL,
  origin_id text NOT NULL, horizon_sessions integer NOT NULL CHECK (horizon_sessions IN (1,5,21,63)),
  role text NOT NULL CHECK (role IN ('historical_outer','qualification','prospective')),
  issued_at timestamptz NOT NULL, origin_cutoff_at timestamptz NOT NULL, sample_object_uri text NOT NULL,
  logical_samples_hash char(64) NOT NULL, physical_artifact_hash char(64) NOT NULL,
  model_bundle_hash char(64) NOT NULL,
  UNIQUE (run_id, cycle_id, generation_id, origin_id, horizon_sessions, role)
);
CREATE TABLE timeseries_v7.score (
  score_id text PRIMARY KEY, prediction_id text NOT NULL REFERENCES timeseries_v7.prediction(prediction_id),
  metric_name text NOT NULL, metric_value double precision NOT NULL,
  comparator_metric_value double precision, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (prediction_id, metric_name)
);
CREATE TABLE timeseries_v7.gate_definition (
  gate_definition_id text PRIMARY KEY, contract_hash char(64) NOT NULL, gate_type text NOT NULL,
  definition_hash char(64) NOT NULL UNIQUE, feasibility_receipt_hash char(64) NOT NULL,
  frozen_at timestamptz NOT NULL
);
CREATE TABLE timeseries_v7.gate_evaluation (
  gate_evaluation_id text PRIMARY KEY,
  gate_definition_id text NOT NULL REFERENCES timeseries_v7.gate_definition(gate_definition_id),
  run_id text NOT NULL, cycle_id text NOT NULL, generation_id text NOT NULL,
  score_snapshot_hash char(64) NOT NULL, gate_pass boolean NOT NULL,
  decision text NOT NULL CHECK (decision IN ('pass','fail','hold_insufficient_sample','wait_data','not_applicable')),
  reasons text[] NOT NULL, evaluated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (gate_definition_id, run_id, cycle_id, generation_id, score_snapshot_hash)
);
CREATE TABLE timeseries_v7.budget_ledger (
  budget_event_id bigserial PRIMARY KEY, run_id text NOT NULL, cycle_id text NOT NULL,
  generation_id text NOT NULL DEFAULT '', task_key text NOT NULL,
  resource_type text NOT NULL CHECK (resource_type IN ('wall_clock_seconds','cpu_seconds','gpu_seconds','api_calls','api_cost_usd','storage_bytes','experiment_count')),
  amount numeric NOT NULL CHECK (amount >= 0), recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE timeseries_v7.promotion_proposal (
  proposal_id text PRIMARY KEY, run_id text NOT NULL, cycle_id text NOT NULL, generation_id text NOT NULL,
  gate_bundle_hash char(64) NOT NULL,
  status text NOT NULL CHECK (status IN ('proposed','approved','rejected','expired')),
  owner_signature text, created_at timestamptz NOT NULL DEFAULT clock_timestamp(), decided_at timestamptz
);

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'raw_object','receipt','receipt_terminal_outcome','observation_revision','receipt_fact_link',
    'dataset_snapshot','feature_value_lineage','label_interval','task_event','prediction','score',
    'gate_definition','gate_evaluation','budget_ledger'
  ] LOOP
    EXECUTE format(
      'CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON timeseries_v7.%I '
      'FOR EACH ROW EXECUTE FUNCTION timeseries_v7.reject_immutable_mutation()', table_name
    );
  END LOOP;
END;
$$;
COMMIT;
