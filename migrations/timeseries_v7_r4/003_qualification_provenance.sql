CREATE TABLE IF NOT EXISTS timeseries_v7_r4.feature_value_provenance (
    snapshot_hash text NOT NULL REFERENCES timeseries_v7_r4.pit_snapshots(snapshot_hash),
    origin_session date NOT NULL,
    feature_id text NOT NULL,
    max_available_at timestamptz NOT NULL,
    origin_cutoff_at timestamptz NOT NULL,
    PRIMARY KEY (snapshot_hash, origin_session, feature_id),
    CHECK (max_available_at <= origin_cutoff_at)
);

DROP TRIGGER IF EXISTS feature_value_provenance_immutable
ON timeseries_v7_r4.feature_value_provenance;
CREATE TRIGGER feature_value_provenance_immutable
BEFORE UPDATE OR DELETE ON timeseries_v7_r4.feature_value_provenance
FOR EACH ROW EXECUTE FUNCTION timeseries_v7_r4.reject_immutable_snapshot_change();
