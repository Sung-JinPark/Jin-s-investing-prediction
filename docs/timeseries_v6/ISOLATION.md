# V6 isolation boundary

`shadow.nasdaq_pit_hierarchical_distribution_v6` is developed in a new
namespace. V1–V5 time-series artifacts, Scenario artifacts, forecast ledgers,
and official ledgers are read-only predecessors.

Every V6 task follows two independent checks:

1. Hash all protected files before and after the task. Any added, removed, or
   changed protected byte fails the task.
2. Validate the paths changed by that task against the closed V6 allowlist.
   Pre-existing user changes are inventoried but are never reset or claimed as
   V6 work.

The frozen baseline is
`data/timeseries_v6/manifests/protected_v5_baseline.json`. It contains 5,107
files and has content hash
`f5a58e3ea684a73bd3afe3850463efa728e102b1e7f202616a305d2fb88719b2`.
The value matches the independent V5 adversarial audit baseline.

This isolation step does not approve V5, V6, or publication. V5 remains a
shadow HOLD and V6 may write only research artifacts under its own namespace.
