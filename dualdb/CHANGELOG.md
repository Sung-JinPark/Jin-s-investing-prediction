# dualdb CHANGELOG — 스펙 대비 변경 사유 기록 (스펙 §0 규칙 2)

## 2026-07-15 초기 구축 시 스펙 이탈 사항

1. **저장소 위치**: 독립 저장소 대신 `C:\workspace\ai-investing\dualdb\` 하위 디렉토리로 구축.
   사유: ai-fc와 같은 git 저장소에서 export 연동(`data/base_rates/`)이 단순해지고
   불변성 감사(git)가 일원화됨. 스펙의 `../ai-fc/` 상대경로는 `../data/base_rates/`로 대체.
2. **Makefile → Python CLI**: Windows 환경에 make 부재 — `python -m dualdb <rebuild|ingest|derive|report|test>`
   로 대체. 명령 의미는 스펙 §2 Makefile 타깃과 1:1.
3. **yfinance → 표준 라이브러리 Yahoo chart API**: 신규 의존성 회피 + ai-fc quant/feed.py에서
   검증된 패턴 재사용(레이트리밋·재시도 동일). 데이터 원천은 동일(Yahoo v8 chart).
4. **^IXIC 이중 소스의 PK 충돌 해소**: price_daily PK(series,date)라 FRED·Stooq 동시 저장 불가 —
   **Stooq를 price_daily의 정본**(OHLCV 보유)으로, FRED NASDAQCOM은 macro_daily에 저장하고
   교차검증 리포트에서 대조. (스펙 §4 "이중 소스 교차검증" 의도 유지)
5. **Ritter 자동 파싱 폴백**: xls 자동 탐지·파싱 실패 시 Tier-3 큐레이션 시드
   (`seeds/ritter_curated.csv`, 출처 URL 명기)로 적재하고 source에 'ritter-curated(tier3)' 표기.
   센티널(1999 적자 IPO > 70%)은 어느 경로든 실데이터 기준으로 검증.
6. **지수 백본 Stooq → Yahoo** (2026-07-15 실측): stooq.com이 JS 브라우저 검증 벽을 반환해
   프로그램 수집 불가. ^IXIC(1971~)·^GSPC·^NDX·^SOX·^VIX 일간을 Yahoo v8
   (period1/period2 명시 — range=max는 interval 강등 버그)로 수집. FRED NASDAQCOM
   교차검증은 유지. 상폐종목(yhoo.us·viav.us·aol.us) 복원은 불가 — entity에 data_gap 기록.
7. **FRED 네트워크 차단** (2026-07-15, 3회 재시도 실패 — RemoteDisconnected/Timeout,
   본 세션 quant 실행에서도 동일): FRED 모듈은 유지 — 도달 가능해지면 주간 ingest가
   자동 충전. 임시 대응: VIX 센티널은 Yahoo ^VIX(동일 지수) 인정, NASDAQCOM 교차검증은
   skip으로 보류(통과 위장 금지). FRED 전용 계열(FEDFUNDS·M2SL·CPI·UNRATE·PAYEMS·
   DGS10·HY스프레드)은 **결측 유지** — Q7·Q8·Q9는 FRED 충전 전까지 산출 불가로 표기.
   금리 문맥은 Yahoo ^TNX(10y 수익률×10)로 보조.
8. **P2 Pearson 게이트 정정** (2026-07-15, §0 규칙 5에 따른 사용자 보고 사항):
   스펙의 "Pearson 0.9269"는 모(母)리포트와 불일치하는 오기 — v4.1 원문
   (`nasdaq(AI) overlay quant refit_260710_v4.1.md` L10)은 **0.899** (v3 0.917).
   검증: 독립 2경로(quant Yahoo 1mo봉 0.9073 / dualdb 일간→월말 0.9067, M+0~42 부분월 포함)
   일치 + 완결월 창(M+0~41) 0.8989 = v4.1 0.899 정확 재현. 게이트를 0.899±0.012
   (M+0~41 고정창)로 수정. 데이터는 이상 없음.
9. **^IXIC 2026-07-14 센티널 일시 실패**: Yahoo가 7/14 일봉을 일시 철회
   (같은 날 오전엔 26,107.01 반환 — 뉴스와 일치하는 검증된 값). 센티널 값은 유지,
   차기 ingest에서 자동 충전 예상. P1은 10/11 통과 + 1 보류로 보고.
10. **P3 부분 (2026-07-15)**: FINRA 마진부채 Tier-2 수집 성공 — 단 페이지 노출 범위가
    최근 13개월뿐이라 닷컴측(1997~2003) 동시점 비교(Q13)는 data_gap. AAII는 수동
    다운로드 대기(사용자가 `data/raw/manual/`에 투입 시 파서 추가 예정).
11. **P4 (2026-07-15)**: 모델 4종(knn_analog·dtw_daily·lppl_walkforward·twins) 구축
    — 병렬 에이전트 빌드 + 2렌즈 적대 검증 + 이슈 10건 시정. 핵심 정직 결론:
    (a) LPPL 워크포워드 실측 — 닷컴에서 정점 1개월 전에야 수렴, 경계히트 17/21로
    편향 보정 무의미 → 조기경보 도구 강등 (DECISIONS.md 8-7);
    (b) 위상 추정 방법 간 불일치 — 캘린더 M+42 / 월간 최적상관 M+37 / 일간 DTW
    M+43.5 → 단일 위상 단정 금지, 삼중 병기;
    (c) 트윈 12종은 생존 승자 표본 — 붕괴 base rate의 낙관적 하한.
    스펙 §8의 수치 모델 예외는 CLAUDE.md 원칙 5에 명문화 (DECISIONS.md 8-6).
