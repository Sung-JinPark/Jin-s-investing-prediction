#!/usr/bin/env python3
"""Deterministic V7 review pack that distinguishes historical/prospective evidence."""

from __future__ import annotations
import argparse,hashlib,json,zipfile
from pathlib import Path,PurePosixPath

REPO=Path(__file__).resolve().parents[1]
ROOTS=(
 'src/ai_fc/timeseries_v7','src/tests/timeseries_v7','docs/timeseries_v7',
 'outputs/timeseries_v7/task_results','migrations/timeseries_v7','locks/timeseries_v7',
 'containers/timeseries_v7','data/timeseries_v7/ralph','data/contracts/multivariate_timeseries_v7.yaml',
 'data/timeseries_v7/manifests/protected_v6_baseline.json','data/timeseries_v7/manifests/runtime_receipt.json',
 'outputs/timeseries_v7/audit/v6_gate_reproduction.json','outputs/timeseries_v7/status.json',
 'outputs/timeseries_v7/secret_scan.json','outputs/timeseries_v7/ARTIFACTS.json',
 'outputs/timeseries_v7/replay/NASDAQ_V7_BOOTSTRAP_REPLAY_PACK_20260825.zip',
 'tools/ralph_v7.py','tools/build_v7_replay_pack.py','tools/finalize_v7_wait_data.py',
)


def collect_files():
 files={}
 for relative in ROOTS:
  root=REPO/relative
  candidates=[root] if root.is_file() else root.rglob('*') if root.is_dir() else []
  for path in candidates:
   if not path.is_file() or '__pycache__' in path.parts or path.suffix in {'.pyc','.tmp'}:continue
   if any(part.startswith('clean_room_') for part in path.parts):continue
   files[path.relative_to(REPO).as_posix()]=path.read_bytes()
 return files


def build(output:Path,status:dict)->dict:
    files=collect_files();files['STATUS.json']=(json.dumps(status,sort_keys=True,indent=2)+'\n').encode()
    files['README_REVIEW.md']=(
      '# NASDAQ V7 detailed review pack\n\n'
      'This is an engineering/research audit pack, not a model PASS or customer forecast.\n\n'
      '- Historical qualification: not run because no frozen V7 PIT snapshot exists.\n'
      '- Prospective qualification: not started; 126 post-freeze origins cannot exist on bootstrap day.\n'
      '- Customer numbers/screenshots: intentionally absent because numbers_visible=false and no UI was changed.\n'
      '- V1-V6 and customer numerical surfaces: protected hash unchanged.\n'
      '- Automatic promotion, publication and trading: disabled.\n'
    ).encode()
    rows=[{'path':path,'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body)} for path,body in sorted(files.items())]
    manifest={'schema_version':1,'pack_type':'v7_wait_data_detailed_review','historical_evidence_claim':status.get('historical_status','not_run'),'prospective_evidence_claim':status.get('prospective_status','not_started'),'screenshots_included':False,'screenshots_absence_reason':'numbers_hidden_and_no_customer_ui_change','automatic_promotion':False,'automatic_publication':False,'automatic_trading':False,'file_count':len(rows),'files':rows}
    files['MANIFEST.json']=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode();output.parent.mkdir(parents=True,exist_ok=True);tmp=output.with_suffix('.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
      for name,body in sorted(files.items()):
        if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:raise ValueError(name)
        info=zipfile.ZipInfo(name,(2026,8,25,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,body)
    tmp.replace(output);return {**manifest,'zip_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'zip_bytes':output.stat().st_size}


def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--status',type=Path,required=True);a=p.parse_args();print(json.dumps(build(a.output,json.loads(a.status.read_text(encoding='utf-8'))),indent=2))


if __name__=='__main__':main()
