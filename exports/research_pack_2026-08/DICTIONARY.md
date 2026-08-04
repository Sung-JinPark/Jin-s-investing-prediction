# Research pack data dictionary

Each registered ledger is exported to its own Zstandard-compressed Parquet table. The original normalized row is retained as `payload_json`; `source_file` and `source_sha256` identify the immutable input. `probability_space` prevents physical-event, risk-neutral and scenario-conditional probabilities from being silently mixed. `derived_from` is a JSON array of source paths. Dates without a time remain civil dates; timestamps are converted to UTC ISO-8601. Missing planned ledgers are intentionally absent.
