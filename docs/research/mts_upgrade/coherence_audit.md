# 정합성 감사 (W4 — §9.1)

기계 판독본: `data/mts_research/derived/coherence_audit.json`

## V8 — 단일 분포 artifact 파생 (T28~T32 실측)

- 전 shadow 행: quantile_grid 단조 + `p_up == mean(grid>0)` 동일 artifact 재현 **PASS**
  (19행 해소 전부 재계산 일치, baseline_identity.json).
- latest pointer: 현재 fail-closed hold 상태(숫자 없음) — 투영 검사는 해당 시 적용.
- 격자 라벨 관찰: V8 quantile_grid 는 중점 레벨 (i+0.5)/200 — pointer 투영 grid[int(q*200)] 의 p10 은 정확히는 0.1025-분위 수준이다. 수학적 모순이 아니라 라벨 정밀도 관찰이며, 동결 좌표이므로 수정 대상이 아니다 (공시만).
- **grid-종속 라벨 발견**: bundle grid 가 국채 휴장 주식 거래일을 제외해 h세션 누적수익 라벨이 해당 일 수익을 누락한다 (2026-10-12 실측 2행) — grid-종속 표적. 동결 코드: 수정이 아니라 공시·후속 계약 설계의 입력.

## V13 — 확률 표면 단조성 (33행 전측정, 보고만)

- 지평 단조성 위반 **0** / 임계 단조성(p30≤p25) 위반 **0** — 현행 라이브 표면 정합.
- 사후 '정합화 공개' 경로 없음(§9.6) · V14 조건부 표면과 결합하지 않음(T27).

## Gate E2 입력

coherence_pass = **True** (정합성 개선 축 — 예측력 주장 아님, §3.3)

## 정정 노트 (2026-11-11 append — 위 본문은 수정하지 않음)

- 위 "grid-종속 라벨 발견 … (2026-10-12 실측 2행)" 은 작성 시점 기준이다. 2026-11-11 재측정에서 영향 해소 행은 **6행**
  (09-11·09-18·09-25·10-02 h21, 10-09 h1·h5)이고, 미해소 19쌍 중 18쌍이 10-12 또는 11-11 에 노출돼 있다.
  근거: `src/ai_fc/mts_research/v8_xnas_labels.py`(진단 원장 `data/mts_research/ledgers/v8_xnas_label_diagnostics.jsonl`).
- 일일 정합성 감시기 C1~C12 와 임계 사전고정: `coherence_monitor_prereg_20261111.md`.
