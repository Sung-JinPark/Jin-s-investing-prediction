CREATE TABLE IF NOT EXISTS timeseries_v7_r4.pit_snapshots (
    snapshot_hash text PRIMARY KEY CHECK (length(snapshot_hash) = 64),
    as_of timestamptz NOT NULL,
    calendar_version text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS timeseries_v7_r4.label_intervals (
    snapshot_hash text NOT NULL REFERENCES timeseries_v7_r4.pit_snapshots(snapshot_hash),
    target_id text NOT NULL,
    origin_session date NOT NULL,
    label_start_session date NOT NULL,
    label_end_session date NOT NULL,
    mature_at timestamptz NOT NULL,
    horizon_sessions integer NOT NULL CHECK (horizon_sessions > 0),
    target_value jsonb NOT NULL,
    PRIMARY KEY (snapshot_hash, target_id),
    CHECK (origin_session < label_start_session),
    CHECK (label_start_session <= label_end_session)
);

CREATE OR REPLACE FUNCTION timeseries_v7_r4.reject_immutable_snapshot_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'PIT snapshots and label intervals are immutable';
END;
$$;

DROP TRIGGER IF EXISTS pit_snapshots_immutable ON timeseries_v7_r4.pit_snapshots;
CREATE TRIGGER pit_snapshots_immutable
BEFORE UPDATE OR DELETE ON timeseries_v7_r4.pit_snapshots
FOR EACH ROW EXECUTE FUNCTION timeseries_v7_r4.reject_immutable_snapshot_change();

DROP TRIGGER IF EXISTS label_intervals_immutable ON timeseries_v7_r4.label_intervals;
CREATE TRIGGER label_intervals_immutable
BEFORE UPDATE OR DELETE ON timeseries_v7_r4.label_intervals
FOR EACH ROW EXECUTE FUNCTION timeseries_v7_r4.reject_immutable_snapshot_change();
