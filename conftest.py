"""루트 pytest 진입용 경로 설정 (v2 구조 개편 — pyproject testpaths 지원).

`cd src && python -m pytest`·`cd dualdb && python -m pytest` 기존 경로와 병존.
uv editable 설치 후에는 불필요해지나 무해 (sys.path 중복 삽입은 no-op에 가깝다).
"""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent
for _p in (_ROOT / "src", _ROOT / "dualdb"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _windows_long_paths_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except OSError:
        return False


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Windows MAX_PATH(260자) 회피 — 장경로 미허용 PC 에서만 basetemp 를 짧게 잡는다.

    기본 basetemp(`%TEMP%/pytest-of-<user>/pytest-N/<테스트명>`)는 91자 안팎이고,
    trendlines 스냅샷 경로(`.../exports/<64hex 스냅샷>/detail.json`)가 그 아래 ~150자를 더해
    260자를 넘긴다 → 쓰기 실패가 `critical: unavailable` 로 삼켜져 테스트가 깨진다.
    저장소의 기존 관례인 `.tmp-pytest/`(gitignore·security-check 제외 대상)로 옮기면 22자가 준다.
    Linux CI·`--basetemp` 명시·LongPathsEnabled=1 환경에는 아무 영향 없음.
    주의: 명시 basetemp 는 매 실행 시작 시 비워지므로 같은 체크아웃에서 pytest 를 동시에 두 번 돌리지 말 것.
    """
    if sys.platform != "win32" or config.option.basetemp or _windows_long_paths_enabled():
        return
    config.option.basetemp = str(_ROOT / ".tmp-pytest")
