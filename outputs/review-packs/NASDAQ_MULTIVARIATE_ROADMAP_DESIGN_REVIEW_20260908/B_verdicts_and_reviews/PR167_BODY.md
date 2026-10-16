## V13-VOL: 외부 검토 다음설계(V13-D2′·C-1 PB 기준선) + 변동성 이벤트 기준율 카드 T2→T3 라이브

외부 검토 `CAMPAIGN_REVIEW_NEXT_DESIGN_260908.md`(§C-1·C-2·D-1~D-4) 채택과 표시 설계서(`docs/design/v13_vol_live_card_display_design_260908.md`) 구현. 계획 승인(2026-09-08) 순서: 사전등록 → C-1 → 동결 → T2 → T3.

### 1. V13-D2′ 사전등록 개정 (결과 전 커밋 afec214e)
- 자명 기준선 `baselines.persistence_pb` + G2 champion 규칙(우월-아니면-단순-아니면-HOLD), cross-fit isotonic(h63) + fallback, 홀드아웃 게이트 G1~G4·finalist 3/1·결과 무관 append, prohibitions 3건, `evaluations_spent` 0→2 정정, 표시 계층(거래일 신선도·델타법 band80·전용 read-model 키) 사전등록. 원문 `gate:` 무수정.
- 원장 등록 6종(`ledger_registry`), 승인 원장 `data/timeseries_v13/ledgers/approvals.jsonl` 신설, DECISIONS V13-D2′·GOV-1(main 잠금 우회 금지 + 사후 기록)·V12b-park, `V12B_PARKED_20260908.md`, method_changes r25.

### 2. C-1 rung-3 결과 (예산 3/8, 새 창 0, 홀드아웃 미열람)
- **EWMA 는 PB(당일 수준 단독 로짓) 대비 양방향 우세 0/9**(h63 두 셀 한 방향 유의 열위). PB 는 기후 대비 9/9 양방향 CI90>0·건전 y-block 귀무 ≤0.033 → **champion = persistence_pb 전 9셀**, finalist `V13VOL_champion_aec80c65038b`. h63 isotonic fallback(raw). 판정 `docs/review/V13_VOL_RUNG3_PB_VERDICT_20260908.md`, method_changes r26(champion_changed).

### 3. 계수 동결 + 표시 계층 + T3 라이브 (V13-D4·D5)
- `champion_coefficients.json`(sha256 `51815bde…`, 반창 대사 max|Δ| 2e-15, immutable/frozen 등록), 비봉인 패키지 `src/ai_fc/timeseries_v13/`, 표시 모듈 `timeseries_v13_vol_display.py`(항상 dict, 네 게이트·계수 핀 3자 일치·NYSE 거래일 신선도 빌드 시점 재평가, 마지막 값 캐시 없음), 읽기모델 전용 키 `timeseries_v13_vol` + 가드, 24KB 예산(실측 4KB), 계보 `volatility_base_rate_v13`.
- 라이브: `timeseries-v13-vol-latest/verify`, 포인터 `vol_latest.json`(live 2026-09-04), 원장 `vol_live.jsonl`, 워크플로 `timeseries-v13-vol-live.yml`(화~토 03:40 UTC; pages·verify 트리거 등록).
- 대시보드 5번째 탭 '변동성 기준율' + 레일 항목(T3), X1 이름충돌 6항(명칭 기준율·출처 배지 상시·영업일≈달력일·caveat lead 상시(**홀드아웃 미검증** 굵게)·vix-25-90d 역할 관계 + 괴리 표시만·결합 0), h63 '▲ 보정 약함', 모바일 지평 탭. 스크린샷 검수 1400/620/375(탭 활성 상태).

### 불변식
봉인 V8/V2 0바이트 · forecasts/·calibration/ 무수정 · 홀드아웃(2015-18)·봉인(2019+) 미열람 · 게이트 산술 무변경 · 매매 신호 아님(참고 의견) · LLM 예측과 산술 결합 없음 · 리프스펙 FF 푸시 없음(GOV-1).

### 남은 사용자 결정
V13-D3 홀드아웃 1슬롯 소모(승인 원문 형식 `V13-D3 홀드아웃 1회 소모 승인 finalist=V13VOL_champion_aec80c65038b`) · V13-D6 배선(PASS 셀 한정) · V12-D4 CBOE 발송 · FR-1 FirstRate.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
