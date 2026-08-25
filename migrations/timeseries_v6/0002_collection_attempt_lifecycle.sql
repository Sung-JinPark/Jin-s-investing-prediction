BEGIN;

CREATE OR REPLACE FUNCTION timeseries_v6.enforce_attempt_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'collection_attempt rows are never deleted';
  END IF;
  IF OLD.terminal_status IS NOT NULL THEN
    RAISE EXCEPTION 'collection_attempt % is already terminal', OLD.attempt_id;
  END IF;
  IF NEW.attempt_id <> OLD.attempt_id
     OR NEW.source_id <> OLD.source_id
     OR NEW.scheduled_for <> OLD.scheduled_for
     OR NEW.retry_sequence <> OLD.retry_sequence
     OR NEW.started_at <> OLD.started_at
     OR NEW.request_fingerprint_sha256 <> OLD.request_fingerprint_sha256 THEN
    RAISE EXCEPTION 'collection_attempt immutable coordinates changed';
  END IF;
  IF NEW.terminal_status IS NULL OR NEW.completed_at IS NULL THEN
    RAISE EXCEPTION 'collection_attempt update must be a terminal transition';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS enforce_attempt_transition ON timeseries_v6.collection_attempt;
CREATE TRIGGER enforce_attempt_transition
BEFORE UPDATE OR DELETE ON timeseries_v6.collection_attempt
FOR EACH ROW EXECUTE FUNCTION timeseries_v6.enforce_attempt_transition();

CREATE OR REPLACE FUNCTION timeseries_v6.finish_collection_attempt(
  p_attempt_id text,
  p_terminal_status text,
  p_completed_at timestamptz,
  p_reason_code text
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  current_status text;
  linked_receipts bigint;
BEGIN
  SELECT terminal_status INTO current_status
  FROM timeseries_v6.collection_attempt
  WHERE attempt_id = p_attempt_id
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'unknown collection_attempt %', p_attempt_id;
  END IF;
  IF current_status IS NOT NULL THEN
    RAISE EXCEPTION 'collection_attempt % already terminal as %', p_attempt_id, current_status;
  END IF;
  IF p_terminal_status NOT IN (
    'success','not_modified','retryable_failure','permanent_failure',
    'blocked_secret','schema_quarantine','cancelled'
  ) THEN
    RAISE EXCEPTION 'invalid collection_attempt terminal status %', p_terminal_status;
  END IF;
  SELECT count(*) INTO linked_receipts
  FROM timeseries_v6.receipt WHERE attempt_id = p_attempt_id;
  IF p_terminal_status = 'success' AND linked_receipts = 0 THEN
    RAISE EXCEPTION 'successful collection_attempt % has no receipt', p_attempt_id;
  END IF;
  IF p_terminal_status = 'not_modified' AND linked_receipts <> 0 THEN
    RAISE EXCEPTION 'not_modified collection_attempt % unexpectedly has receipt', p_attempt_id;
  END IF;
  UPDATE timeseries_v6.collection_attempt
  SET completed_at = p_completed_at,
      terminal_status = p_terminal_status,
      terminal_reason_code = p_reason_code
  WHERE attempt_id = p_attempt_id;
END;
$$;

CREATE INDEX IF NOT EXISTS collection_attempt_open_idx
ON timeseries_v6.collection_attempt (started_at)
WHERE terminal_status IS NULL;

CREATE OR REPLACE VIEW timeseries_v6.collection_attempt_integrity AS
SELECT
  a.attempt_id,
  a.source_id,
  a.started_at,
  a.completed_at,
  a.terminal_status,
  count(r.receipt_id)::bigint AS receipt_count,
  CASE
    WHEN a.terminal_status IS NULL THEN false
    WHEN a.terminal_status = 'success' AND count(r.receipt_id) = 0 THEN false
    WHEN a.terminal_status = 'not_modified' AND count(r.receipt_id) <> 0 THEN false
    ELSE true
  END AS integrity_pass
FROM timeseries_v6.collection_attempt a
LEFT JOIN timeseries_v6.receipt r USING (attempt_id)
GROUP BY a.attempt_id, a.source_id, a.started_at, a.completed_at, a.terminal_status;

COMMIT;
