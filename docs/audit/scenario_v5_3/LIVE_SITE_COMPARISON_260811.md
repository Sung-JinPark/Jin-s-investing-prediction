# Live site comparison — 2026-08-11 09:10 KST

Read-only targets:

- `https://sung-jinpark.github.io/Jin-s-investing-prediction/`
- `https://sung-jinpark.github.io/Jin-s-investing-prediction/data.json`

Both returned HTTP 200.

## Public state observed before deployment

| Check | Live value | Local remediated value |
|---|---|---|
| champion method | `gbm-daily-252d-v2-lookup` | same |
| champion as-of | `2026-08-07` | same |
| V5.2 status | `degraded` | `degraded`, research-only |
| `#future` renderer | eligible V5.2 is returned before champion | champion is rendered first |
| explicit research route | absent | `#future/research` |
| V5.2 governance payload | absent | four promotion gates exposed |
| top-level band calibration | absent | 3/60 exposed |
| method change rows | 4 | 6 append-only rows |

Observed live source excerpt semantics:

```text
if candidate52 is ok/degraded and display-eligible:
    renderScenarioV52(candidate52)
    return
```

This confirms P0-B on the public build: the degraded V5.2 candidate occupies the default future route. The local remediation is not yet deployed because this task did not authorize commit, push, PR, merge, or deployment.

Content receipts:

- live `index.html` SHA-256: `5e5276cd513059719c700984ff867d1f7938b713259be62b6f4c4ae46fe86f73`
- live `data.json` SHA-256: `fc75cd97aa1c0d8ec51dd01e3115437d3da02dda933f977276b3cf120bd0ec5c`
