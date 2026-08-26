CREATE TABLE IF NOT EXISTS timeseries_v7_r4_generations (
    generation_id text PRIMARY KEY CHECK (generation_id ~ '^[0-9a-f]{64}$'),
    contract_sha256 text NOT NULL CHECK (contract_sha256 ~ '^[0-9a-f]{64}$'),
    data_sha256 text NOT NULL CHECK (data_sha256 ~ '^[0-9a-f]{64}$'),
    code_sha256 text NOT NULL CHECK (code_sha256 ~ '^[0-9a-f]{64}$'),
    runtime_sha256 text NOT NULL CHECK (runtime_sha256 ~ '^[0-9a-f]{64}$'),
    hypothesis_sha256 text NOT NULL CHECK (hypothesis_sha256 ~ '^[0-9a-f]{64}$'),
    as_of timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (contract_sha256, data_sha256, code_sha256, runtime_sha256, hypothesis_sha256)
);

CREATE TABLE IF NOT EXISTS timeseries_v7_r4_generation_exposures (
    exposure_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    generation_id text NOT NULL REFERENCES timeseries_v7_r4_generations(generation_id),
    evidence_id text NOT NULL,
    evidence_role text NOT NULL CHECK (evidence_role IN ('tuning', 'qualification', 'prospective')),
    available_at timestamptz NOT NULL,
    exposed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE UNIQUE INDEX IF NOT EXISTS timeseries_v7_r4_one_qualification_per_generation
ON timeseries_v7_r4_generation_exposures (generation_id)
WHERE evidence_role = 'qualification';

CREATE OR REPLACE FUNCTION timeseries_v7_r4_guard_generation_exposure()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE frozen_as_of timestamptz;
BEGIN
    SELECT as_of INTO STRICT frozen_as_of
      FROM timeseries_v7_r4_generations
     WHERE generation_id = NEW.generation_id
     FOR KEY SHARE;
    IF NEW.evidence_role = 'tuning' AND NEW.available_at > frozen_as_of THEN
        RAISE EXCEPTION 'tuning evidence available_at exceeds generation as_of';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS timeseries_v7_r4_generation_exposure_guard
ON timeseries_v7_r4_generation_exposures;
CREATE TRIGGER timeseries_v7_r4_generation_exposure_guard
BEFORE INSERT ON timeseries_v7_r4_generation_exposures
FOR EACH ROW EXECUTE FUNCTION timeseries_v7_r4_guard_generation_exposure();
