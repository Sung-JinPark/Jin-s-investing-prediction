BEGIN;

CREATE TABLE IF NOT EXISTS timeseries_v6.dataset_snapshot_partition (
  dataset_snapshot_id text NOT NULL REFERENCES timeseries_v6.dataset_snapshot(dataset_snapshot_id),
  partition_path text NOT NULL CHECK (partition_path !~ '(^/|(^|/)\.\.(/|$)|\\\\)'),
  partition_sha256 char(64) NOT NULL CHECK (partition_sha256 ~ '^[0-9a-f]{64}$'),
  schema_sha256 char(64) NOT NULL CHECK (schema_sha256 ~ '^[0-9a-f]{64}$'),
  byte_count bigint NOT NULL CHECK (byte_count > 0),
  row_count bigint NOT NULL CHECK (row_count >= 0),
  source_count integer NOT NULL CHECK (source_count >= 0),
  min_available_at timestamptz,
  max_available_at timestamptz,
  PRIMARY KEY (dataset_snapshot_id, partition_path),
  CHECK (max_available_at IS NULL OR min_available_at IS NULL OR max_available_at >= min_available_at)
);

DROP TRIGGER IF EXISTS reject_mutation ON timeseries_v6.dataset_snapshot_partition;
CREATE TRIGGER reject_mutation
BEFORE UPDATE OR DELETE ON timeseries_v6.dataset_snapshot_partition
FOR EACH ROW EXECUTE FUNCTION timeseries_v6.reject_mutation();

COMMIT;
