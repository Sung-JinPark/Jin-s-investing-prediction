from pathlib import Path
import yaml
from ai_fc.timeseries_v7.contract_runtime_audit import REQUIRED_FOLD_ROLES,audit_runtime_contract


CONTRACT=yaml.safe_load((Path(__file__).resolve().parents[3]/'data/contracts/multivariate_timeseries_v7.yaml').read_text(encoding='utf-8'))


def runtime():
 experts={k:{'algorithm':v['algorithm']} for k,v in CONTRACT['candidates'].items()};experts['E2']['objective']='ridge_on_mad';experts['E7']['full_trajectory_required']=False
 return {'experts':experts,'fold_roles':sorted(REQUIRED_FOLD_ROLES),'stacking':{'weights':'learned_nonnegative'},'path_forecast':{'implemented':False,'sample_count':0}}


def test_fake_student_t_endpoint_only_and_missing_path_are_p0_mismatches():
 codes={x['code'] for x in audit_runtime_contract(CONTRACT,runtime())['findings']}
 assert {'e2_objective_mismatch','e7_missing_full_trajectory','path_implementation_missing'}<=codes
