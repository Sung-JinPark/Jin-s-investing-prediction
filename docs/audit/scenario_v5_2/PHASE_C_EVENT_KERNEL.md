# Phase C — Labor vector and event kernel

Gate: **PASS WITH LIMITATION**

The labor vector uses payroll surprise, combined revision, temporary layoffs, unemployment, participation, employment/population, earnings, and hours. Missing fields are rejected rather than filled with zero. Growth-risk score is `0.738149`. Policy-relief is a separate latent factor, `0.557133`.

Only one eligible event is available for a direct historical event-return map. Under the n<30 rule, the hard event kernel is `REFERENCE_ONLY_INSUFFICIENT_N`; it contributes no direct price jump. The August 7 Nasdaq return is already in the 26,605.36 anchor. Future event jump = 0, event-return coefficient = 0, equality-with-zero-event-reaction gate = `True`.
