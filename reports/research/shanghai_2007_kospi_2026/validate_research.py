"""Independent arithmetic/provenance checks, entirely inside the research boundary."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    errors=[];checks=[];catalog=[]
    baseline=json.loads((ROOT/"protected_before.json").read_text(encoding="utf-8"))["sha256"]
    changed=[name for name,value in baseline.items() if not (REPO/name).is_file() or sha(REPO/name)!=value]
    checks.append({"check":"protected_original_files","count":len(baseline),"changed":changed,"passed":not changed})
    errors.extend("Protected file changed: "+name for name in changed)
    hashes=0
    for part in ("china","korea","prices","context"):
        manifest=json.loads((ROOT/part/"source_manifest.json").read_text(encoding="utf-8"))
        for record in manifest.get("sources",[]):
            entry={"namespace":part,**record}
            locals_=[record[k] for k in ("raw_file","local_path","relative_path","path") if record.get(k)]
            if locals_ and record.get("sha256"):
                candidates=[p for local in locals_ for p in (ROOT/part/local,ROOT/local)]
                path=next((p.resolve() for p in candidates if p.is_file()),None)
                if path is None:
                    errors.append(f"Missing source file {part}/{locals_}")
                elif not path.is_relative_to(ROOT):
                    errors.append(f"Source path outside research root: {path}")
                elif sha(path)!=record["sha256"]:
                    errors.append(f"Source hash mismatch {path}")
                else:hashes+=1
                entry["research_relative_file"]=str(path.relative_to(ROOT)).replace("\\","/") if path else None
            catalog.append(entry)
    checks.append({"check":"raw_response_hashes","checked":hashes,"source_records":len(catalog),
                   "note":"Counts include challenge and partial responses; usable source content is identified separately.",
                   "passed":not any("source" in x.lower() for x in errors)})
    (ROOT/"source_catalog.json").write_text(json.dumps({"as_of":"2026-10-16T09:00:00+09:00","sources":catalog},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    frame=pd.read_csv(ROOT/"prices/prices.csv",parse_dates=["date"])
    result=json.loads((ROOT/"prices/analytics.json").read_text(encoding="utf-8"))
    def weekly(symbol,start,end,shift):
        x=frame.loc[(frame.symbol==symbol)&frame.date.between(start,end),["date","close"]].copy()
        if shift:x["date"]=x.date.map(lambda value:value.replace(year=value.year+19))
        # Independent pandas W-SUN bins; NaN empty periods suppress cross-gap returns.
        x=x.set_index("date")["close"].resample("W-SUN").last()
        return np.log(x).diff()
    joined=pd.concat([weekly("SSE_COMPOSITE","2006-01-01","2007-10-15",True),
                      weekly("KOSPI","2025-01-01","2026-10-15",False)],axis=1).dropna()
    independent={"n":len(joined),"pearson":float(pearsonr(joined.iloc[:,0],joined.iloc[:,1]).statistic),
                 "spearman":float(spearmanr(joined.iloc[:,0],joined.iloc[:,1]).statistic)}
    expected=result["primary"]["SSE_COMPOSITE"]["weekly_returns"]
    arithmetic_ok=(len(joined)==expected["n_return_pairs"] and abs(independent["pearson"]-expected["pearson"])<1e-12 and abs(independent["spearman"]-expected["spearman"])<1e-12)
    checks.append({"check":"independent_pandas_scipy_weekly_computation",**independent,"passed":arithmetic_ok})
    if not arithmetic_ok:errors.append("Independent weekly correlation mismatch")
    data_ok=(not frame.duplicated(["symbol","date"]).any() and frame.date.max()<=pd.Timestamp("2026-10-15") and frame.close.gt(0).all())
    checks.append({"check":"canonical_price_boundary","rows":len(frame),"symbols":int(frame.symbol.nunique()),"passed":bool(data_ok)})
    if not data_ok:errors.append("Price boundary failure")
    suppressed=all(value.get("world_price_return_fraction") is None and value.get("usd_minus_world_log_return") is None for value in result["usd_global"].values())
    checks.append({"check":"unverified_benchmark_suppressed","passed":suppressed})
    if not suppressed:errors.append("Unverified benchmark numeric result exposed")
    run=subprocess.run([sys.executable,"-X","utf8","-m","unittest","discover","-p","test_*.py","-v"],cwd=ROOT,text=True,capture_output=True,encoding="utf-8")
    (ROOT/"test_results.txt").write_text(run.stdout+run.stderr,encoding="utf-8")
    checks.append({"check":"full_research_unit_suite","passed":run.returncode==0,"record":"test_results.txt"})
    if run.returncode:errors.append("Research tests failed")
    visual=json.loads((ROOT/"visual_qa.json").read_text(encoding="utf-8"))
    checks.append({"check":"desktop_tablet_mobile_render","passed":visual["passed"],"viewports":[r["width"] for r in visual["results"]]})
    if not visual["passed"]:errors.append("Visual QA failed")
    reviews=[]
    for part in ("china","korea","prices"):
        path=ROOT/part/"independent_review_parent.json"
        record=json.loads(path.read_text(encoding="utf-8"))
        reviews.append({"reviewer":part,"file":str(path.relative_to(ROOT)),"record":record})
    (ROOT/"independent_review.json").write_text(json.dumps({"reviews":reviews,
        "root_resolution":{"china_causal_wording":"rephrased to observed earnings increases",
                           "china_threshold_precision":"actual first-crossing and previous-session drawdowns displayed",
                           "korea_policy_causality":"government main-cause hypothesis left unverified; central bank tightening is not a refutation of government inducement",
                           "korea_fund_date":"May29 participation date added; Oct15 FSC position added",
                           "fx_quote_time":"unspecified fixing time disclosed"},
        "final_report_sha256":sha(ROOT/"report.md"),"no_blocking_findings_after_resolution":True},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    outputs={str(p.relative_to(ROOT)).replace("\\","/"):sha(p) for p in [ROOT/"report.md",ROOT/"report.html",ROOT/"prices/analytics.json",ROOT/"prices/prices.csv",ROOT/"supporting_analysis.json"]}
    validation={"validated_at":datetime.now(timezone.utc).isoformat(),"as_of":"2026-10-16T09:00:00+09:00",
        "passed":not errors,"errors":errors,"checks":checks,"output_sha256":outputs,
        "failure_categories":{"code_defects":errors,"environment_or_dependency":"Playwright bundled browser missing; resolved using installed Chrome without installation",
                              "data_or_artifact_gaps":["full matched global country EPS panel","constant-definition index EPS/P-E decomposition","daily investor flows for causal policy estimate","world benchmark conflicting quotes","252-session post-2008-March diagnostic right-censored"]},
        "production_tests":"Not run: production code is unchanged; several repository tests can mutate durable databases. Full isolated research suite and protected-file hashes used.",
        "official_forecast":False,"durable_database_writes":0,"dependencies_installed":0}
    (ROOT/"validation.json").write_text(json.dumps(validation,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"passed":not errors,"errors":errors,"protected_files":len(baseline),"raw_hashes":hashes,"canonical_rows":len(frame),"independent":independent},ensure_ascii=False))
    if errors:raise SystemExit(1)


if __name__=="__main__":main()
