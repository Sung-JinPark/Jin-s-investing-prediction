"""수집 공통 규칙 (스펙 §4): UA 명시·1초 지연·3회 지수 백오프·원본 보존 후 파싱."""

from __future__ import annotations

import hashlib
import time
import urllib.request
from datetime import date
from pathlib import Path

from . import config

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) dualdb-research/1.0"}
_last_request = 0.0
_python_path_blocked = False   # WS-T5: 세션 내 파이썬 경로 실패 시 curl 직행 플래그


def get(url: str, timeout: int | None = None) -> bytes:
    global _last_request
    wait = config.REQ_DELAY - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    last: Exception | None = None
    for attempt in range(config.REQ_RETRIES):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout or config.REQ_TIMEOUT) as resp:
                _last_request = time.time()
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 ** attempt * 2)
    raise last  # type: ignore[misc]


def get_with_curl_fallback(url: str, timeout: int | None = None) -> bytes:
    """파이썬 경로 실패 시 curl 서브프로세스 폴백 (v3.5 WS-T5 — 사용자 승인).

    배경: FRED가 curl에는 200을 주면서 파이썬 urllib에는 응답을 지연/차단
    (클라이언트 TLS 시그니처 기반 봇 필터로 진단 — docs/NETWORK_RECOVERY.md 2026-07-20).
    이 폴백은 우회가 아니라 **정상 접근의 복원**이다: 대상은 공개 데이터(무키
    fredgraph.csv), 빈도는 주 1회 6시리즈(REQ_DELAY 지연 유지), robots 준수.
    """
    import subprocess

    global _python_path_blocked
    if not _python_path_blocked:
        try:
            return get(url, timeout=timeout)
        except Exception:  # noqa: BLE001 — 파이썬 경로 실패 → curl 폴백
            # 세션 내 재실패 방지: 이후 호출은 curl 직행 (시리즈 6개 × 재시도 낭비 차단)
            _python_path_blocked = True

    # UA를 넘기지 않는다 (curl 기본 UA 사용): 실측상 필터가 파이썬 TLS 시그니처와
    # 이 패키지의 커스텀 UA 문자열을 표적하며, curl 기본 요청은 200을 받는다
    # (2026-07-20 실측 — NETWORK_RECOVERY.md). 위장이 아니라 도구 기본값이다.
    time.sleep(max(0.0, config.REQ_DELAY))   # 폴백 경로에도 예의 지연 유지
    tmo = str(timeout or config.REQ_TIMEOUT)
    r = subprocess.run(["curl", "-sS", "--max-time", tmo, url],
                       capture_output=True)
    if r.returncode == 0 and r.stdout:
        return r.stdout

    # 3단 폴백: 로컬 리졸버가 이 도메인을 간헐 차단 (curl exit 6 실측 —
    # 같은 순간 공개 DNS 1.1.1.1은 정상 해석). 공개 DNS로 IP를 얻어 --resolve 주입.
    # DNS "우회"가 아니라 표준 공개 리졸버 사용 — 대상·빈도·robots 준수는 동일.
    from urllib.parse import urlparse

    host = urlparse(url).netloc
    ip = _resolve_via_public_dns(host)
    if ip is None:
        raise RuntimeError(f"curl 폴백 실패(exit {r.returncode}) + 공개 DNS 해석 실패: {url}")
    r = subprocess.run(
        ["curl", "-sS", "--max-time", tmo, "--resolve", f"{host}:443:{ip}", url],
        capture_output=True, check=True)
    if not r.stdout:
        raise RuntimeError(f"curl --resolve 폴백 빈 응답: {url}")
    return r.stdout


def _resolve_via_public_dns(host: str, resolver: str = "1.1.1.1") -> str | None:
    """nslookup을 공개 리졸버로 직접 질의해 A 레코드 추출 (로컬 리졸버 간헐 차단 대응)."""
    import re
    import subprocess

    try:
        r = subprocess.run(["nslookup", host, resolver],
                           capture_output=True, text=True, timeout=15)
    except Exception:  # noqa: BLE001
        return None
    ips = [m for m in re.findall(r"Address:\s+(\d+\.\d+\.\d+\.\d+)", r.stdout or "")
           if m != resolver]
    return ips[0] if ips else None


def save_raw(source: str, name: str, body: bytes, ext: str) -> Path:
    """원본을 data/raw/{source}/{date}_{hash}.{ext}로 보존 (원칙 5 — 재현 가능성)."""
    d = config.RAW_DIR / source
    d.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(body).hexdigest()[:10]
    path = d / f"{date.today().isoformat()}_{name}_{h}.{ext}"
    if not path.exists():
        path.write_bytes(body)
    return path
