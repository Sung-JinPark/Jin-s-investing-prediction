"""Interval-aware, session-indexed five-role validation folds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from .pit_snapshot import LabelInterval
from .xnas_sessions import XnasSessionCalendar


ROLE_ORDER = ("train", "selection", "stacking", "calibration", "outer")


@dataclass(frozen=True, slots=True)
class RoleFold:
    labels_by_role: Mapping[str, tuple[LabelInterval, ...]]
    excluded_target_ids: Mapping[str, str]
    calendar_version: str
    purge_sessions: int
    embargo_sessions: int


def build_five_role_fold(
    *,
    labels: Iterable[LabelInterval],
    calendar: XnasSessionCalendar,
    role_origin_sessions: Mapping[str, Iterable[date | str]],
    purge_sessions: int,
    embargo_sessions: int,
) -> RoleFold:
    """Assign labels to five roles and remove earlier labels near later roles.

    Purge and embargo are measured on the supplied canonical session calendar.
    A label's complete closed interval participates in isolation; its origin is
    used only to select the candidate role.
    """
    if set(role_origin_sessions) != set(ROLE_ORDER):
        raise ValueError(f"role_origin_sessions must contain exactly {ROLE_ORDER}")
    if isinstance(purge_sessions, bool) or not isinstance(purge_sessions, int) or purge_sessions < 0:
        raise ValueError("purge_sessions must be a non-negative integer")
    if isinstance(embargo_sessions, bool) or not isinstance(embargo_sessions, int) or embargo_sessions < 0:
        raise ValueError("embargo_sessions must be a non-negative integer")

    positions = {session.session_date: index for index, session in enumerate(calendar.sessions)}
    origins: dict[str, set[date]] = {}
    owner: dict[date, str] = {}
    for role in ROLE_ORDER:
        origins[role] = {_date(value) for value in role_origin_sessions[role]}
        for session_date in origins[role]:
            if session_date not in positions:
                raise ValueError(f"role origin is not a canonical session: {session_date}")
            previous = owner.setdefault(session_date, role)
            if previous != role:
                raise ValueError(f"origin session belongs to multiple roles: {session_date}")

    candidates = {role: [] for role in ROLE_ORDER}
    seen_ids: set[str] = set()
    excluded: dict[str, str] = {}
    for label in labels:
        if not label.target_id or label.target_id in seen_ids:
            raise ValueError("target_id must be present and unique")
        seen_ids.add(label.target_id)
        for endpoint in (label.label_start_session, label.label_end_session):
            if endpoint not in positions:
                raise ValueError(f"label endpoint is not a canonical session: {endpoint}")
        if positions[label.label_start_session] > positions[label.label_end_session]:
            raise ValueError("label_start_session must not follow label_end_session")
        role = owner.get(label.origin_session)
        if role is None:
            excluded[label.target_id] = "origin_outside_roles"
        else:
            candidates[role].append(label)

    gap = purge_sessions + embargo_sessions
    kept: dict[str, tuple[LabelInterval, ...]] = {}
    # Later roles are evaluation-like and authoritative. Purge an earlier label
    # whenever its interval reaches, or is within the configured session gap of,
    # any later role's label interval.
    for role_index in range(len(ROLE_ORDER) - 1, -1, -1):
        role = ROLE_ORDER[role_index]
        accepted: list[LabelInterval] = []
        # Compare with all later candidates, including a candidate subsequently
        # purged from its own role. Otherwise an overlap chain could disappear.
        later = [(later_role, item) for later_role in ROLE_ORDER[role_index + 1:]
                 for item in candidates[later_role]]
        for label in candidates[role]:
            conflict = next((later_role for later_role, other in later
                             if _interval_distance(label, other, positions) <= gap), None)
            if conflict is None:
                accepted.append(label)
            else:
                excluded[label.target_id] = f"purge_or_embargo_overlap:{conflict}"
        kept[role] = tuple(sorted(accepted, key=lambda item: (
            item.origin_session, item.label_start_session, item.label_end_session, item.target_id)))

    fold = RoleFold(
        labels_by_role={role: kept[role] for role in ROLE_ORDER},
        excluded_target_ids=excluded,
        calendar_version=calendar.version,
        purge_sessions=purge_sessions,
        embargo_sessions=embargo_sessions,
    )
    validate_interval_disjointness(fold)
    return fold


def validate_interval_disjointness(fold: RoleFold) -> None:
    """Reject any closed label interval shared by distinct roles."""
    if tuple(fold.labels_by_role) != ROLE_ORDER:
        raise ValueError(f"labels_by_role must be ordered as {ROLE_ORDER}")
    for left_index, left_role in enumerate(ROLE_ORDER):
        for right_role in ROLE_ORDER[left_index + 1:]:
            for left in fold.labels_by_role[left_role]:
                for right in fold.labels_by_role[right_role]:
                    if (left.label_start_session <= right.label_end_session
                            and right.label_start_session <= left.label_end_session):
                        raise ValueError(
                            "label interval overlap between "
                            f"{left_role}:{left.target_id} and {right_role}:{right.target_id}"
                        )


def _interval_distance(
    left: LabelInterval, right: LabelInterval, positions: Mapping[date, int]
) -> int:
    left_start, left_end = positions[left.label_start_session], positions[left.label_end_session]
    right_start, right_end = positions[right.label_start_session], positions[right.label_end_session]
    if left_end < right_start:
        return right_start - left_end - 1
    if right_end < left_start:
        return left_start - right_end - 1
    return 0


def _date(value: date | str) -> date:
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"invalid role origin session: {value}") from exc
    raise ValueError("role origin sessions must be dates or ISO dates")
