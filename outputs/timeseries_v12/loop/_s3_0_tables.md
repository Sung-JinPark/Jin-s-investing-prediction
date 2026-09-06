# S3-0 사전등록 요약 (자동 렌더 — 수기 전사 없음)

원본: `data/timeseries_v12/prereg/hypotheses.json` · sha256 `a2c1a9e72a1265dc68bf3e9d4660ce6c4095dc0e943f46d1cb3c61fb7a3bf4df`
등록 시각(epoch): 1788659863 — 2026-09-06 (일) — 태스크 envelope 의 now_epoch
결과 열람 여부: **results_seen = False**

## 표 A — 가설

| ID | 이름 | 채택대상 | 설계도 원문 식 | 자유도 | 설계도 원문 기대 |
|---|---|---|---|---|---|
| T1 | 상단 수축 | O | `p′=p−λ(p−b)·1{p>τ}, τ=학습창 80분위, b=학습창 터치율` | 1 | h21 유망·h63 역방향 위험 (§0 실측) |
| T2 | 양방향 최소 λ | O | `λ=min(λ_전→후, λ_후→전) 고정 후 재검정` | 1 | h63 역방향 실패 완화 |
| T3 | 반사원리 앵커 | O | `p′=(1−w)p + w·p_reflect, p_reflect=2Φ(−ln(S/K)/(σ√T)) (σ=EWMA λ=.97)` | 1 | 기계적 기준선이 과신 교정 |
| T4 | 지평 간 정합 | O | `p_h21′ ≤ p_h63′ 단조 제약 위반 시 교정(터치는 지평 단조)` | 0 | 구조 제약 — 무비용 |
| T5 | 음성 대조 (순열 섞은 p 로 T1 재검정) | — (음성대조) | `순열 섞은 p로 T1 재검정` | 0 | 통과 시 검정 자체 결함 |

설계도 §2 표의 식·기대는 `tools/v12_prereg_check.py` C2 가 바이트 부분문자열로 대사한다.

## 표 B — 검정 프로토콜 (전부 결과 보기 전 고정)

| 항목 | 사전 고정값 |
|---|---|
| 표적 y | first_touch_actual — 지평 내 지수 경로 최소값 ≤ 0.90 × S0 (원점 대비 −10% first-passage). run 의 scores[].first_touch_actual 을 1.0/0.0 으로. |
| 예측 p | V8 first_touch_probability — run 의 scores[].first_touch_probability. 어떤 재보정도 거치지 않은 원값. |
| 지평 | [21, 63] (h1·h5 제외 — S2-1·S2-2 규약 승계 — h1/h5 는 터치 기저율이 판정 불가 수준. 결과를 본 뒤의 배제가 아니라 S2 에서 이미 고정된 범위.) |
| 원점 | 417개 · 2007-01-05~2014-12-24 |
| 분할 | 2010-12-31 — 전반 209 / 후반 208 |
| 방향 | 전→후(early→late) · 후→전(late→early) |
| 적합 | 학습창 Brier 최소화 (평가창 정보 일절 미사용). |
| 격자 | [0.0, 1.0] step 0.01 → 101점 · 동점 시 가장 작은 값 (변화 없음 쪽 = 보수적) |
| 검정통계량 | Δ = mean_i[ (p_i − y_i)² − (p′_i − y_i)² ] (평가창). 양수 = 개선. 쌍대(paired) 손실차 d_i = (p_i−y_i)² − (p′_i−y_i)² 의 표본평균과 동일. |
| CI | stationary block bootstrap (감싸기) ℓ=13 B=2000 seed=20260902 · percentile [5, 95] = CI90 |
| 1차 채택 | 가설 H, 지평 h 의 셀이 채택되려면 early_to_late 와 late_to_early 두 방향 **모두** Δ 의 CI90 하한 > 0. |
| 2차 기준 | p′ vs p_reflect 쌍대 Δ_ref = mean[(p_reflect−y)² − (p′−y)²] 의 CI90 하한이 두 방향 모두 > 0. |
| 귀무 | 각 창 안에서 p 를 무작위 치환(y 고정, 창별 독립). 설계도 §2 의 '순열 섞은 p' 문자 그대로. · 1000회 |
| 다중검정 | family 8셀 · k 의 경험분포와 P(k ≥ k_obs) 를 공표한다. · 주장 문턱 family 수준의 증거 주장은 P(k ≥ k_obs) ≤ 0.05 일 때만. 초과 시 개별 셀이 채택돼도 'family 수준에서는 다중검정으로 설명 가능' 을 판정문에 병기. |
| 홀드아웃 | 2015+ 봉인창은 S3 의 어떤 셀에서도 계산하지 않는다. |

## 표 C — 보고 의무 (셀마다 전부 채워야 마감)

산출 경로 `data/timeseries_v12/diagnostics/transfer_results.json (S3-1)` · 필드 23개

```
  hypothesis_id, horizon, direction, n_eval
  touches_eval, fitted_parameter, tau, b
  brier_p, brier_p_prime, delta, ci90_lower
  ci90_upper, bootstrap_se, mde_1645se, mde_share_of_brier
  top5_abs_share, sign_after_top5pct_drop, concentration_fragile, delta_vs_reflection
  ci90_lower_vs_reflection, A1_pass, A2_pass
```

- 8 셀 × 2 방향 = 16 결과를 전부 기록한다. 미달·퇴화·빈 상단집합도 사유와 함께 기록하며 생략하지 않는다.
- 모든 셀에 MDE = 1.645 × bootstrap_se 를 병기한다. \|Δ\| < MDE 인 셀은 부호와 무관하게 '결정적 증거 없음' 으로 라벨하고, 개선 주장에 인용할 수 없다.
- 모든 셀에 (a) 상위 5% \|d_i\| 가 \|d\| 총합에서 차지하는 비중, (b) 그 상위 5% 를 제거한 뒤의 Δ 부호를 보고한다. 부호가 뒤집히는 셀은 '집중도 취약' 라벨을 달고, 라벨이 달린 셀은 채택되더라도 그 사실을 판정문에 병기해야 한다.

## 표 D — 금지 조항

| 조항 | 내용 |
|---|---|
| 사후 가설 | T6 이후는 없다. 결과를 본 뒤 가설을 추가·삭제·재정의하지 않는다. 실패한 가설도 원장에 남긴다. |
| 손잡이 교체 1 | 그리드 지지집합·해상도(0.01) 변경 금지 |
| 손잡이 교체 2 | τ 분위(80) 변경 금지 |
| 손잡이 교체 3 | 분할 경계·블록길이 ℓ=13·복제수 B=2000·seed 20260902 변경 금지 |
| 손잡이 교체 4 | p_reflect 변형 교체 금지 (T3.p_reflect_spec.forbidden_substitution) |
| 손잡이 교체 5 | T4 교정 방식 교체 금지 (PAV 고정) |
| K-split-contrast | S2-3 이 낸 분할창 대비(후반창 두 지평 CI90 하한>0)는 사전등록 검정도 다중검정 보정도 아니다. 'V8 이 기준선을 이긴다' 의 근거로 인용 금지, 가설 승격 금지. 풀표본 판정(두 지평 모두 0 포함)이 정본. |
| K-gate-arith | S3 통과가 S4 게이트 통과를 뜻하지 않음을 지금 못박는다. S2-3 이 재산출한 문턱 — 필요 BSS h21 +14.28%(BGK +21.12%)·h63 +10.18%(BGK +15.08%), 완전보정 상한 h21 +19.84%·h63 +16.39%. S4-2 에서 문턱을 낮추는 기준선 선택(원식·λ=0.99)은 사후 완화이며 근거 명문화 없이 금지. |
| 봉인 | forecasts/·calibration/·data/timeseries_v8·data/timeseries_v2·questions/·src/ 무수정. 봉인 해시 e3ff2fdb… 와 원장 해시 b9c492be… 를 태스크 전후로 대사. |
| 홀드아웃 | 2015+ 창 계산 금지. |

## 표 E — 결과를 보기 전에 정한 해석

| 경우 | 사전 확정 귀결 |
|---|---|
| adopted_ge_1 | 채택 셀 ≥ 1 → S4-1 은 V12 계약 draft 를 작성하고 채택 셀을 후보로 승계한다. 단 S4 게이트 통과는 별도 판정이며 K-gate-arith 가 적용된다. |
| adopted_0 | 채택 0 → 설계도 §1 각주대로 S4 를 'V12 부정 결과 계약 — 이벤트 확률 재보정도 전이 불가' 로 대체 작성한다. 이후 유일한 경로가 '다른 데이터'(사용자 결정 V12-D4)임을 명시. |
| T5_fail | T5 통과율 > 10% → 채택 전부 무효 + 부정 결과 계약. 이 경로가 adopted_0 보다 우선한다. |
| what_adoption_does_not_mean | 채택은 '표적의 과신 구조를 파생층 맵이 교정하고 그 교정이 창을 넘어 전이된다' 는 뜻이다. 'V8 이 기준선을 이긴다' 는 뜻이 아니며(S2-3 R1 미달·S2-2 결론 유지), 실전 자금 결정 근거가 아니다(CLAUDE.md P3 게이트). |

