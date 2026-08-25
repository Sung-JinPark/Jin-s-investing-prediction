"""Terminal dependency propagation for V7 tasks."""

from __future__ import annotations

from collections.abc import Iterable


SUCCESS_STATES = {"succeeded"}
WAIT_STATES = {"wait_data"}
HOLD_STATES = {"hold", "blocked", "failed", "cancelled", "skipped_dependency"}


def downstream_terminal_state(dependency_states: Iterable[str]) -> str | None:
    states = set(dependency_states)
    if not states or states <= SUCCESS_STATES:
        return None
    if states & {"cancelled"}:
        return "cancelled"
    if states & WAIT_STATES and not states & HOLD_STATES:
        return "wait_data"
    if states & HOLD_STATES:
        return "skipped_dependency"
    return None


PROPAGATE_SQL = """
WITH dependency_state AS (
  SELECT child.run_id,child.cycle_id,child.generation_id,child.task_key,
         array_agg(parent.state) AS states
  FROM timeseries_v7.task_dependency dep
  JOIN timeseries_v7.task child ON
    (child.run_id,child.cycle_id,child.generation_id,child.task_key)=
    (dep.run_id,dep.cycle_id,dep.generation_id,dep.task_key)
  JOIN timeseries_v7.task parent ON
    (parent.run_id,parent.cycle_id,parent.generation_id,parent.task_key)=
    (dep.run_id,dep.cycle_id,dep.dependency_generation_id,dep.dependency_task_key)
  WHERE child.state IN ('pending','ready','retry_wait')
  GROUP BY child.run_id,child.cycle_id,child.generation_id,child.task_key
), terminal AS (
  SELECT *, CASE
    WHEN 'cancelled'=ANY(states) THEN 'cancelled'
    WHEN states && ARRAY['hold','blocked','failed','skipped_dependency']::text[] THEN 'skipped_dependency'
    WHEN 'wait_data'=ANY(states) THEN 'wait_data'
  END AS next_state
  FROM dependency_state
)
UPDATE timeseries_v7.task task SET state=terminal.next_state,updated_at=clock_timestamp()
FROM terminal
WHERE (task.run_id,task.cycle_id,task.generation_id,task.task_key)=
      (terminal.run_id,terminal.cycle_id,terminal.generation_id,terminal.task_key)
  AND terminal.next_state IS NOT NULL
RETURNING task.run_id,task.cycle_id,task.generation_id,task.task_key,task.state
"""
