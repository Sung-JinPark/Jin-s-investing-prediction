BEGIN;

CREATE OR REPLACE VIEW timeseries_v6.receipt_lineage_integrity AS
SELECT
  r.receipt_id,
  r.object_sha256,
  count(o.receipt_id)::integer AS terminal_outcome_count,
  max(o.observation_count) AS declared_observation_count,
  count(l.observation_version_id) FILTER (WHERE l.relation = 'parsed_from')::integer AS parsed_fact_count,
  CASE
    WHEN count(o.receipt_id) <> 1 THEN false
    WHEN max(o.outcome_status) = 'parsed'
         AND max(o.observation_count) <> count(l.observation_version_id) FILTER (WHERE l.relation = 'parsed_from') THEN false
    ELSE true
  END AS integrity_pass
FROM timeseries_v6.receipt r
LEFT JOIN timeseries_v6.receipt_terminal_outcome o USING (receipt_id)
LEFT JOIN timeseries_v6.receipt_fact_link l USING (receipt_id)
GROUP BY r.receipt_id, r.object_sha256;

CREATE OR REPLACE VIEW timeseries_v6.observation_revision_integrity AS
SELECT
  child.observation_version_id,
  child.observation_key_id,
  child.revision_seq,
  child.supersedes_observation_version_id,
  parent.observation_key_id AS parent_key_id,
  parent.revision_seq AS parent_revision_seq,
  count(sibling.observation_version_id)::integer AS child_count,
  CASE
    WHEN child.revision_seq = 0 AND child.supersedes_observation_version_id IS NOT NULL THEN false
    WHEN child.revision_seq > 0 AND child.supersedes_observation_version_id IS NULL THEN false
    WHEN child.revision_seq > 0 AND parent.observation_version_id IS NULL THEN false
    WHEN child.revision_seq > 0 AND parent.observation_key_id <> child.observation_key_id THEN false
    WHEN child.revision_seq > 0 AND parent.revision_seq <> child.revision_seq - 1 THEN false
    WHEN count(sibling.observation_version_id) > 1 THEN false
    ELSE true
  END AS integrity_pass
FROM timeseries_v6.observation_version child
LEFT JOIN timeseries_v6.observation_version parent
  ON child.supersedes_observation_version_id = parent.observation_version_id
LEFT JOIN timeseries_v6.observation_version sibling
  ON sibling.supersedes_observation_version_id = child.observation_version_id
GROUP BY child.observation_version_id, child.observation_key_id, child.revision_seq,
         child.supersedes_observation_version_id, parent.observation_version_id,
         parent.observation_key_id, parent.revision_seq;

CREATE OR REPLACE VIEW timeseries_v6.orphan_observation_version AS
SELECT version.observation_version_id
FROM timeseries_v6.observation_version version
LEFT JOIN timeseries_v6.receipt_fact_link link USING (observation_version_id)
WHERE link.observation_version_id IS NULL;

COMMIT;
