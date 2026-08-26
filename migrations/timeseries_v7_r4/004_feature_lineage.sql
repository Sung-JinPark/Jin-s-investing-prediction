ALTER TABLE timeseries_v7_r4.feature_value_provenance
    ADD COLUMN IF NOT EXISTS source_revision_ids text[] NOT NULL
        DEFAULT ARRAY['legacy-qualified'],
    ADD COLUMN IF NOT EXISTS transformation_hash text NOT NULL
        DEFAULT 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    ADD COLUMN IF NOT EXISTS data_grade text NOT NULL DEFAULT 'legacy-qualified';

ALTER TABLE timeseries_v7_r4.feature_value_provenance
    DROP CONSTRAINT IF EXISTS feature_value_provenance_transformation_hash_check;
ALTER TABLE timeseries_v7_r4.feature_value_provenance
    ADD CONSTRAINT feature_value_provenance_transformation_hash_check
    CHECK (length(transformation_hash) = 64);
