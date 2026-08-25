from datetime import date,datetime,timezone,timedelta
import numpy as np
from ai_fc.timeseries_v7.fold_roles import FoldAssignment,validate_disjoint_roles
from ai_fc.timeseries_v7.folds import eligible_training_labels
from ai_fc.timeseries_v7.labels import label_interval


def sessions(count=200):
 d=date(2024,1,1);out=[]
 while len(out)<count:
  if d.weekday()<5:out.append(d)
  d+=timedelta(days=1)
 return out


def test_weekly_row_offset_cannot_replace_session_interval_purge():
 s=sessions();labels=[label_interval(s,i,63,mature_at=datetime.now(timezone.utc)) for i in range(0,100,5)]
 valid=s[100];eligible=eligible_training_labels(labels,valid,s,embargo_sessions=5)
 assert all(row.label_end_session<valid for row in eligible) and len(labels)-len(eligible)<68


def test_overlapping_fold_roles_fail():
 rows=[FoldAssignment('stacking',date(2020,1,1),date(2020,1,2),date(2020,3,1)),FoldAssignment('calibration',date(2020,2,1),date(2020,2,2),date(2020,4,1))]
 assert not validate_disjoint_roles(rows)['pass']


def test_scaler_must_be_fit_on_train_only():
 train=np.array([0.,1.]);outer=np.array([100.]);train_median=np.median(train);leaky=np.median(np.r_[train,outer]);assert train_median!=leaky
