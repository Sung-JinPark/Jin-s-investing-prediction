# 네트워크 복구 체크리스트 — FRED·Stooq 차단 대응 (v3 WS-D, 2026-07-20)

> 배경: KNOWN_LIMITS 11 — Yahoo 단일 소스 의존 심화. FRED(fred.stlouisfed.org)·Stooq가
> 이 네트워크에서 지속 차단(TimeoutError), Yahoo 7/14 일봉 일시 철회 실사례.
> 목적: 차단 원인 격리 절차의 표준화 + 복구 시 자동 재가동 확인.

## 점검 절차 (순서대로 — 각 단계 결과를 기록)

1. **DNS 해석**: `Resolve-DnsName fred.stlouisfed.org` / `stooq.com` — 실패 시 DNS 이슈(공유기/ISP DNS 변경 시도: 1.1.1.1, 8.8.8.8)
2. **TCP 도달**: `Test-NetConnection fred.stlouisfed.org -Port 443` — DNS OK인데 TCP 실패면 방화벽/ISP 차단
3. **HTTP 응답**: `curl.exe -sI --max-time 15 https://fred.stlouisfed.org/graph/fredgraph.csv?id=M2SL` — TCP OK인데 타임아웃/403이면 서버측 지역·봇 차단 (User-Agent 변경 시도는 dualdb net.py가 이미 수행)
4. **프록시/VPN 변수**: `$env:HTTPS_PROXY` 존재 여부 · VPN 활성 시 끄고 1~3 재시도
5. **대조군**: 같은 시각 `curl.exe -sI https://query1.finance.yahoo.com` (정상 소스) — 전체 네트워크 문제 vs 특정 호스트 문제 격리

## 복구 확인 (차단 해제 시)

- `cd dualdb && python -m dualdb ingest` — fred 항목이 ERROR가 아닌 행 수를 반환하면 복구
- 자동 재가동 확인 3종: ① `python -m pytest tests/test_sentinels.py` — `test_dual_source_cross_check`가 **skip → pass 전환** (FRED NASDAQCOM 교차검증 자동 재가동) ② `python -m dualdb report` — Q7·Q8·Q9 매크로 섹션 충전 ③ shiller_cape·finra 히스토리 수집 재개
- 별도 코드 수정 불필요 — fail-soft 설계가 데이터 도달 시 자동 충전 (KNOWN_LIMITS 28)

## 점검 이력

| 일자 | 단계별 결과 | 판정 |
|---|---|---|
| 2026-07-20 | ① DNS: FRED 해석됨(IP 무표기 CNAME)·Stooq 159.69.202.225 ② TCP 443: FRED **True** ③ HTTP(curl): FRED **200 OK** ④ 프록시 없음 ⑤ 대조군 Yahoo 429(일시 rate limit) · **단 Python urllib 경로는 >120s 행업** | **부분 복구** — 서버가 curl은 허용, **파이썬 클라이언트 시그니처(TLS/UA)를 표적 차단**하는 정황. 원인은 네트워크가 아니라 봇 필터. 대응 후보: 수집 경로를 curl 서브프로세스/requests+UA로 변경 (기존 소스의 수집 방법 개선 — 새 소스 아님, v3 §4 비저촉). **8월 WS-F 슬롯 제안 — 사용자 승인 대기** |
| 2026-07-20 (2차 — v3.5 WS-T5 구현 중 정밀 격리) | 시간대별 재실측: 파이썬 = 연결 후 **읽기 단계 차단**(RemoteDisconnected/read timeout) · curl = **DNS 해석 자체가 간헐 실패**(exit 6 — 같은 순간 Windows Resolve-DnsName·공개 DNS 1.1.1.1은 정상 해석) · **공개 DNS로 얻은 IP + curl --resolve = 200 OK 안정** | **확정 진단 2층**: ⓐ 로컬 리졸버가 이 도메인을 **간헐 DNS 차단**(플래핑 — "때때로 되던" 이력의 원인) ⓑ 서버측이 파이썬 스타일 요청을 읽기 단계에서 지연 차단. **구현된 해법 (net.py 3단 폴백)**: python → curl 기본 → nslookup@1.1.1.1 + `--resolve`. 공개 리졸버 사용은 표준 구성이지 우회가 아님 |

> 주기: 주간 리프레시에서 FRED ERROR 지속 시 월 1회 수동 점검. ISP/네트워크 환경 변경 시 즉시.
