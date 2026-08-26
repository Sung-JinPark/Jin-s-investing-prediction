CREATE SCHEMA IF NOT EXISTS timeseries_v7_r4;

CREATE TABLE IF NOT EXISTS timeseries_v7_r4.runs (
    run_id text PRIMARY KEY,
    state text NOT NULL,
    config_hash text NOT NULL,
    backlog_hash text NOT NULL,
    review_pack_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    terminal_reason jsonb
);

CREATE TABLE IF NOT EXISTS timeseries_v7_r4.cycles (
    run_id text NOT NULL REFERENCES timeseries_v7_r4.runs(run_id),
    cycle_id text NOT NULL,
    ordinal integer NOT NULL,
    state text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, cycle_id)
);

CREATE TABLE IF NOT EXISTS timeseries_v7_r4.tasks (
    run_id text NOT NULL REFERENCES timeseries_v7_r4.runs(run_id),
    task_key text NOT NULL,
    title text NOT NULL,
    priority integer NOT NULL,
    worker_capability text NOT NULL,
    payload jsonb NOT NULL,
    state text NOT NULL DEFAULT 'PENDING',
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_owner text,
    lease_token text,
    lease_expires_at timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    blocker_signature text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, task_key)
);

CREATE TABLE IF NOT EXISTS timeseries_v7_r4.task_dependencies (
    run_id text NOT NULL,
    task_key text NOT NULL,
    dependency_key text NOT NULL,
    PRIMARY KEY (run_id, task_key, dependency_key),
    FOREIGN KEY (run_id, task_key) REFERENCES timeseries_v7_r4.tasks(run_id, task_key),
    FOREIGN KEY (run_id, dependency_key) REFERENCES timeseries_v7_r4.tasks(run_id, task_key)
);

CREATE TABLE IF NOT EXISTS timeseries_v7_r4.attempts (
    run_id text NOT NULL,
    task_key text NOT NULL,
    attempt_id text NOT NULL,
    lease_token text NOT NULL,
    worker_id text NOT NULL,
    state text NOT NULL,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    result jsonb,
    result_hash text,
    PRIMARY KEY (run_id, attempt_id),
    FOREIGN KEY (run_id, task_key) REFERENCES timeseries_v7_r4.tasks(run_id, task_key)
);

CREATE TABLE IF NOT EXISTS timeseries_v7_r4.events (
    event_id bigserial PRIMARY KEY,
    run_id text NOT NULL REFERENCES timeseries_v7_r4.runs(run_id),
    event_type text NOT NULL,
    task_key text,
    payload jsonb NOT NULL,
    payload_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS timeseries_v7_r4.artifact_receipts (
    run_id text NOT NULL REFERENCES timeseries_v7_r4.runs(run_id),
    receipt_id text NOT NULL,
    task_key text,
    artifact_path text NOT NULL,
    sha256 text NOT NULL,
    bytes bigint NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, receipt_id)
);

CREATE TABLE IF NOT EXISTS timeseries_v7_r4.backlog_catalog (
    catalog_id text NOT NULL,
    task_key text NOT NULL,
    payload jsonb NOT NULL,
    payload_hash text NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (catalog_id, task_key)
);

CREATE INDEX IF NOT EXISTS r4_tasks_claim_idx
ON timeseries_v7_r4.tasks(run_id, state, available_at, priority, created_at);

CREATE TABLE IF NOT EXISTS timeseries_v7_r4.fred_revisions (
    series_id text NOT NULL,
    observation_date date NOT NULL,
    realtime_start date NOT NULL,
    realtime_end date NOT NULL,
    available_at date NOT NULL,
    value text NOT NULL,
    raw_sha256 text NOT NULL CHECK (length(raw_sha256) = 64),
    retrieved_at timestamptz NOT NULL,
    PRIMARY KEY (series_id, observation_date, realtime_start, realtime_end),
    CHECK (available_at = realtime_start)
);

CREATE TABLE IF NOT EXISTS timeseries_v7_r4.fred_cursors (
    series_id text PRIMARY KEY,
    realtime_start date NOT NULL,
    committed_at timestamptz NOT NULL DEFAULT now()
);
