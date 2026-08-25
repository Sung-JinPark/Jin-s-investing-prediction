"""Immutable post-freeze prospective forecast records."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ProspectiveForecast:
    prediction_id:str;issued_at:datetime;origin_cutoff_at:datetime;model_hash:str;dataset_hash:str;samples_hash:str;generation_frozen_at:datetime
    def __post_init__(self):
        if self.issued_at<self.generation_frozen_at:raise ValueError('forecast predates generation freeze')
        if self.origin_cutoff_at>self.issued_at:raise ValueError('cutoff after issuance')


class AppendOnlyForecastLedger:
    def __init__(self):self._rows={}
    def append(self,row:ProspectiveForecast):
        if row.prediction_id in self._rows:raise ValueError('immutable prediction already exists')
        self._rows[row.prediction_id]=row
    def get(self,prediction_id):return self._rows[prediction_id]
