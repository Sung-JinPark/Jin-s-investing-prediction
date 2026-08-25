"""Maturity-gated prospective score selection."""

from __future__ import annotations
from datetime import datetime


def matured_only(rows:list[dict],cutoff:datetime)->list[dict]:
    return [row for row in rows if row['mature_at']<=cutoff and row.get('actual') is not None]


def assert_not_training_input(role:str)->None:
    if role in {'research_train','candidate_selection','stacking','calibration'}:raise ValueError('prospective score cannot enter model selection')
