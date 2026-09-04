#!/usr/bin/env python
"""V12 루프 파이썬 실행 래퍼 — 안정된 허용 토큰 1개로 임의 v12 분석 스크립트를 실행한다.

Claude Code Bash 권한은 토큰 정확 매칭이라 임의 이름의 `python tools/v12_<name>.py`를
--allowedTools로 좁게 허용할 수 없다. 그래서 루프의 Opus 세션은 파이썬 재분석을
반드시 다음 형태로만 실행한다:

    .venv/Scripts/python.exe tools/v12_run.py tools/v12_<name>.py [args...]

허용 규칙은 `Bash(.venv/Scripts/python.exe tools/v12_run.py:*)` / `Bash(python tools/v12_run.py:*)`
단 두 개면 된다. 이 래퍼가 대상 경로를 tools/v12_*.py로 **강제 검증**하므로, 허용 토큰이
넓어져도 실행 가능한 것은 v12 분석 스크립트뿐이다 (임의 python·-c·-m ai_fc 백테스트 verb 차단).
"""

from __future__ import annotations

import re
import runpy
import sys
from pathlib import Path

_ALLOWED = re.compile(r"^tools/v12_[A-Za-z0-9_]+\.py$")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: v12_run.py tools/v12_<name>.py [args...]", file=sys.stderr)
        return 2
    raw = sys.argv[1].replace("\\", "/")
    if raw == "tools/v12_run.py" or not _ALLOWED.match(raw) or ".." in raw:
        print(f"refused: target must match tools/v12_*.py and not be the wrapper: {raw}",
              file=sys.stderr)
        return 3
    target = Path(raw)
    if not target.is_file():
        print(f"refused: target not found: {raw}", file=sys.stderr)
        return 4
    # 대상 스크립트를 현재(venv) 인터프리터에서 실행. argv를 대상 기준으로 재설정.
    sys.argv = [str(target), *sys.argv[2:]]
    runpy.run_path(str(target), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
