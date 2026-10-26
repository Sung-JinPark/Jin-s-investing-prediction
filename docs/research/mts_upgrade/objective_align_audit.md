# 목적 정렬 감사 (OBJECTIVE_ALIGN, W4 — §8.3)

기계 판독본: `data/mts_research/derived/objective_align_audit.json` · **감사만, 재튜닝 없음**

## 정적 추적 (동결 코드 좌표)

| 파라미터 | 지평 | 판정 | 경로 |
|---|---|---|---|
| varx.lag / varx.alpha (1일 MSE 선택) | h21/h63 최종 분포 | **INDIRECT_VIA_LAMBDA** | residuals → select_distribution_parameters_v2 → λ 스위치 → FHS; PIT 이력 경유 재보정 |
| varx.lag / varx.alpha | h1/h5 · first_touch | **ACTIVE** | 엔진 경로 시뮬레이션이 VARX 적합을 직접 사용 |
| distribution.block_length | h21/h63 최종 분포 | **BYPASSED** | FHS 는 block_length 를 인자로 받지 않는다 (역사 중첩창 + EWMA 표준화) |
| distribution.ewma_lambda | h21/h63 최종 분포 | **ACTIVE** | FHS 표준화·재척도의 직접 인자 |

## 섭동 하니스 (합성 — V8 예산 비소모·계약 무변경)

- FHS 시그니처에 VARX fit 없음: h21/h63 모두 `varx_fit_in_fhs_signature=False`,
  같은 λ 에서 FHS 분포 차이 **0** (구조적).
- λ 스위치(0.94↔0.97)의 h21 분위 최대 차이 0.04123,
  h63 0.1542 — λ 는 ACTIVE.
- 두 제한 grid 적합의 λ 선택: {'lag1_smallA': 0.97, 'lag5_largeA': 0.94} → 판정
  **INDIRECT_VIA_LAMBDA**.

## 결론 (감사 가설 §2.4-1 승격)

'1일 MSE 선택 vs 장기 CRPS 목적 불일치' 가설은 **부분 확인**: h21/h63 최종 분포에서
VARX (lag,α) 는 λ 이진 스위치·PIT 이력 경유로만 작용(INDIRECT_VIA_LAMBDA),
block_length 는 BYPASSED, h1/h5·first_touch 는 ACTIVE. 선택 목적 재정렬 실험(ablation)은
영향 경로가 밝혀진 파라미터에 한해 W7 등록 후에만 의미가 있다 — 지금은 실행하지 않는다.
