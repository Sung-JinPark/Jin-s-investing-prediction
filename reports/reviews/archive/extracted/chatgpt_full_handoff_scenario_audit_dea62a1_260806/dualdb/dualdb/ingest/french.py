"""Fama-French 팩터 월간 — Kenneth French Data Library (무등록·무키 CSV zip).

5팩터(Mkt-RF·SMB·HML·RMW·CMA·RF, 1963-07+)와 모멘텀(Mom, 1927+)을 월별로 병합해
factor_monthly에 적재한다. 값은 원본 그대로 **월간 수익률 퍼센트(%)** — 파생 z(밸류/
모멘텀/사이즈 기울기)는 별도 export 단계에서 산출한다.

정직성: 이 데이터는 사전학습·추론 전용 참조(base rate)다 — 학습·가중치 갱신 없음
(원칙 5·8-6, ML 게이트 비저촉). 프롬프트 주입 시 질문 매핑 확률로 쓰지 않는다(R-4).
French는 소프트웨어 산출을 학술 무상 재배포 — robots 준수·저빈도(주 1회) 접근.
"""

from __future__ import annotations

import io
import re
import sqlite3
import zipfile
from datetime import datetime

from .. import config, net

# French 결측 센티널 (-99.99, -999 등) → NULL
_MISSING = re.compile(r"^-9{2,}(\.9+)?$")
# French 원본 컬럼명 → factor_monthly 컬럼
_COLMAP = {"Mkt-RF": "mkt_rf", "SMB": "smb", "HML": "hml", "RMW": "rmw",
           "CMA": "cma", "RF": "rf", "Mom": "mom"}
_COLS = ("mkt_rf", "smb", "hml", "rmw", "cma", "mom", "rf")


def _f(s: str) -> float | None:
    s = s.strip()
    if not s or _MISSING.match(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_monthly(text: str) -> dict[str, dict[str, float | None]]:
    """월간 섹션 파싱 → {YYYYMM: {factor_col: value}}.

    헤더는 첫 셀이 비고 나머지가 팩터명인 행. 데이터는 6자리 연월 행. 4자리 연도
    행(연간 섹션) 또는 빈 줄을 만나면 월간 종료.
    """
    lines = text.splitlines()
    header: list[str] | None = None
    start = 0
    for i, ln in enumerate(lines):
        cells = [c.strip() for c in ln.split(",")]
        if cells and cells[0] == "" and any(re.search("[A-Za-z]", c) for c in cells[1:]):
            header = [_COLMAP.get(c, c.strip()) for c in cells[1:]]
            start = i + 1
            break
    if header is None:
        raise ValueError("French CSV 헤더 행을 찾지 못함")
    out: dict[str, dict[str, float | None]] = {}
    for ln in lines[start:]:
        if re.match(r"^\s*\d{6}\s*,", ln):
            cells = [c.strip() for c in ln.split(",")]
            ym = cells[0]
            vals = cells[1:]
            row = {header[k]: _f(vals[k]) for k in range(min(len(header), len(vals)))}
            out[ym] = {c: v for c, v in row.items() if c in _COLS}
        elif re.match(r"^\s*\d{4}\s*,", ln) or ln.strip() == "":
            break  # 연간 섹션 또는 공백 → 월간 종료
    return out


def _fetch_csv(zip_name: str) -> str:
    url = config.FRENCH["base"] + zip_name
    body = net.get_with_curl_fallback(url)
    net.save_raw("french", zip_name.replace(".zip", ""), body, "zip")
    z = zipfile.ZipFile(io.BytesIO(body))
    return z.read(z.namelist()[0]).decode("latin-1")


def ingest(conn: sqlite3.Connection, since: str | None = None) -> dict[str, int]:
    """5팩터 + 모멘텀 병합 → factor_monthly. since는 'YYYY-MM-01' 이상만 적재."""
    try:
        five = _parse_monthly(_fetch_csv(config.FRENCH["five_factor"]))
        mom = _parse_monthly(_fetch_csv(config.FRENCH["momentum"]))
    except Exception as exc:  # noqa: BLE001 — 소스 실패가 전체 ingest를 막지 않게
        return {"ERROR": f"{type(exc).__name__}: {exc}"[:200]}

    months = sorted(set(five) | set(mom))
    now = datetime.now().isoformat(timespec="seconds")
    rows = []
    for ym in months:
        d = f"{ym[:4]}-{ym[4:6]}-01"
        if since and d < since:
            continue
        rec = dict.fromkeys(_COLS)
        rec.update(five.get(ym, {}))
        rec.update({k: v for k, v in mom.get(ym, {}).items() if k == "mom"})
        rows.append((d, rec["mkt_rf"], rec["smb"], rec["hml"], rec["rmw"],
                     rec["cma"], rec["mom"], rec["rf"], "ken-french", now))
    conn.executemany(
        """INSERT OR REPLACE INTO factor_monthly
           (date, mkt_rf, smb, hml, rmw, cma, mom, rf, source, ingested_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit()
    return {"factor_monthly": len(rows),
            "five_factor_months": len(five), "momentum_months": len(mom)}
