"""tools/v15_vol_freeze_constants.py — V15-VOL 상수 동결 도구 (1회 실행, 재실행 거부).

계약: data/contracts/multivariate_timeseries_v15_vol.yaml (frozen_constants · produced_by).
설계창 2007-2014 만 읽어(read_market_observations 절단 + 이중 확인) R1 방향 층화 Platt·R2 평온 점프 꼬리·
R3 상태 기저율을 계산하고, 설계창 MDE·적격 도달 참조(채택 근거 아님)를 함께 기록한다.

  python tools/v15_vol_freeze_constants.py           # stdout 출력만 (쓰기 0)
  python tools/v15_vol_freeze_constants.py --write   # 상수 아티팩트 + 사전등록 참조 JSON 생성 — 이미 있으면 exit 2

결정론 수치모델(dualdb §8 예외) — base rate 참조이지 캘리브레이션 표본이 아니며 하이퍼파라미터 caveat 를 싣는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_fc.timeseries_v15_vol import contracts as C  # noqa: E402
from ai_fc.timeseries_v15_vol import design_fit as D  # noqa: E402


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _tool_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")


def freeze(root: Path, *, now: datetime) -> tuple[dict, dict]:
    knowledge_cutoff = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    body = D.build_constants(root, knowledge_cutoff=knowledge_cutoff)
    body["provenance"] = {"git_head": _git_head(), "tool": "tools/v15_vol_freeze_constants.py",
                          "tool_sha256": _tool_sha256(), "knowledge_cutoff": knowledge_cutoff,
                          "design_window_access": "repeated_reference_only (constants: freeze tool once)"}
    constants = {**body, "content_hash": C.canonical_hash(body)}
    mde_body = D.mde_reference(root, constants, knowledge_cutoff=knowledge_cutoff)
    mde_body["provenance"] = dict(body["provenance"])
    mde = {**mde_body, "content_hash": C.canonical_hash(mde_body)}
    return constants, mde


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="상수·MDE 참조 파일을 생성한다(이미 있으면 거부)")
    args = parser.parse_args(argv)
    constants_path = ROOT / C.CONSTANTS_RELATIVE
    mde_path = ROOT / C.PREREG_MDE_RELATIVE
    if args.write and (constants_path.exists() or mde_path.exists()):
        print("V15-VOL constants already frozen — single-use freeze; refusing to re-run.", file=sys.stderr)
        return 2
    constants, mde = freeze(ROOT, now=datetime.now(timezone.utc))
    if not args.write:
        print(json.dumps({"constants": constants, "mde_reference": mde}, ensure_ascii=False, indent=1))
        return 0
    _dump(constants_path, constants)
    _dump(mde_path, mde)
    print(json.dumps({"constants_path": C.CONSTANTS_RELATIVE.as_posix(),
                      "constants_sha256": C.sha256_file(constants_path),
                      "constants_content_hash": constants["content_hash"],
                      "mde_path": C.PREREG_MDE_RELATIVE.as_posix(),
                      "mde_sha256": C.sha256_file(mde_path)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
