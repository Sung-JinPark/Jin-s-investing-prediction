"""Frozen historical research qualification; prospective scores are forbidden."""

from __future__ import annotations


def evaluate(metrics:dict[str,float],historical_stress_pass:bool,*,prospective_scores=None)->dict[str,object]:
    if prospective_scores is not None:raise ValueError('qualification must not consume prospective scores')
    checks={
      'long_skill':metrics['long_horizon_mean_crps_skill']>=.02,
      'h21_nonnegative':metrics['h21_skill']>=0,
      'h63_nonnegative':metrics['h63_skill']>=0,
      'ci':metrics['paired_ci_upper']<=0,
      'coverage80':.76<=metrics['coverage80']<=.84,
      'coverage50':.45<=metrics['coverage50']<=.55,
      'direction':metrics['balanced_direction_accuracy']>=.52,
      'brier':metrics['brier']<metrics['base_rate_brier'],
      'extreme':metrics['extreme_q4_coverage']>=.60,
      'catastrophic':metrics['catastrophic_underperformance']<=.10,
      'historical_stress':historical_stress_pass,
    }
    return {'checks':checks,'pass':all(checks.values()),'prospective_scores_consumed':False}
