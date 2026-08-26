CREATE TABLE IF NOT EXISTS timeseries_v7_r4.wake_evidence (
    run_id text NOT NULL REFERENCES timeseries_v7_r4.runs(run_id),
    evidence_kind text NOT NULL,
    evidence_hash text NOT NULL CHECK (length(evidence_hash) = 64),
    available_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, evidence_kind, evidence_hash),
    CHECK (available_at <= observed_at),
    CHECK (evidence_kind IN ('COLLECTION_RECEIPT', 'MATURE_LABEL'))
);
