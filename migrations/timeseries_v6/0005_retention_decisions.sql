BEGIN;

CREATE TABLE IF NOT EXISTS timeseries_v6.retention_decision (
  retention_decision_id text PRIMARY KEY,
  decision_type text NOT NULL CHECK (decision_type IN ('quota_hold','legal_delete_authorized','legal_delete_rejected')),
  object_sha256 char(64) REFERENCES timeseries_v6.raw_object(object_sha256),
  approval_receipt_sha256 char(64) CHECK (approval_receipt_sha256 IS NULL OR approval_receipt_sha256 ~ '^[0-9a-f]{64}$'),
  reason_code text NOT NULL,
  decided_at timestamptz NOT NULL,
  CHECK ((decision_type = 'legal_delete_authorized' AND object_sha256 IS NOT NULL AND approval_receipt_sha256 IS NOT NULL)
      OR decision_type <> 'legal_delete_authorized')
);

DROP TRIGGER IF EXISTS reject_mutation ON timeseries_v6.retention_decision;
CREATE TRIGGER reject_mutation
BEFORE UPDATE OR DELETE ON timeseries_v6.retention_decision
FOR EACH ROW EXECUTE FUNCTION timeseries_v6.reject_mutation();

COMMIT;
