# 구조경로 감사 증거집 — EVIDENCE-260806

기준: `main@dea62a1` · `nasdaq-scenario:2026-08-03:r8`

성격: 검토자가 빠르게 반증할 수 있도록 만든 1차 증거 지도. 이 문서의 판정도 코드·데이터 재현보다 우선하지 않는다.

---

## 1. 첨부 화면에서 관찰되는 현상

패키지 파일: `evidence/codex-clipboard-5812eae9-25a6-4488-a38f-504b3b983cf2.png`

- 세 굵은 선이 2026-08-03에 25,914에서 함께 시작한다.
- 8월 말까지 동반 하락한다.
- S1은 9월 말 반등한 뒤 10월 말 다시 저점을 만든다.
- S2/S3도 같은 시점에 같은 방향으로 꺾인다.
- 세 경로의 상대 간격은 다르지만 turning point가 거의 동일하다.
- 회색 점선 참조선은 굵은 선과 별도 모양이며 2026년 말 약 26~27k에 보인다.
- 배경 위험창은 2026-08-31~11-24, 중심은 2026-10으로 직렬화돼 있다.

---

## 2. 증거 파일 지도

| 주장 | 정본 파일 | 핵심 위치 |
|---|---|---|
| GBM 경로 생성·분류 | `src/ai_fc/scenario.py` | representative 생성, S1/S2/S3 mask |
| 구형 참조선 상수 | `src/ai_fc/scenario.py` | `_ANALOG_VALUES`, 약 112행 |
| 참조선 보간 | `src/ai_fc/scenario.py` | `np.interp`, 약 619행 |
| 참조선 clip | `src/ai_fc/scenario.py` | payload `analog.clip`, 약 705행 |
| 역사 raw median | `src/ai_fc/scenario_structure.py` | `_analog_shape`, 약 234행 |
| 공통 구조식 | `src/ai_fc/scenario_structure.py` | `_structural_paths`, 약 249행 |
| S1 보정 | `src/ai_fc/scenario_structure.py` | `_calibration_strength`, 약 312행 |
| 선택 민감도 | `src/ai_fc/scenario_structure.py` | `_selection_sensitivity`, 약 347행 |
| v3 직렬화 | `src/ai_fc/scenario_structure.py` | `build_structural_forecast`, 약 432행 |
| 선택 계약 | `data/contracts/scenario_structural_forecast.yaml` | innovation_cycle·calibration |
| 최신 context | `data/ml_history/2026.jsonl` | 마지막 `kind=context` 행 |
| overlay anchor | `dualdb/config.yaml` | anchors·overlay_months |
| overlay 생성 | `dualdb/dualdb/export/context_bridge.py` | `_overlay`, 약 276행 |
| k-NN | `dualdb/dualdb/models/knn_analog.py` | `run`, pool z-score, neighbors |
| 화면 경로 선택 | `src/ai_fc/dashboard_parts/dashboard.js` | `flowDisplayPath`, 약 1737행 |
| 화면 차트 | `src/ai_fc/dashboard_parts/dashboard.js` | `drawFlow`, 약 1850행 이후 |
| immutable 최신 | `data/scenarios/archive/2026-08-03_CORR-260806-019.json` | 전체 |
| 직전 revision | `data/scenarios/archive/2026-08-03_CORR-260806-018.json` | 전체 |

---

## 3. 현재 스냅샷 사실값

```json
{
  "snapshot_id": "nasdaq-scenario:2026-08-03:r8",
  "asof": "2026-08-03",
  "anchor": 25914,
  "probabilities": {"S1": 83, "S2": 2, "S3": 15},
  "selected_eras": ["biotech2015", "dotcom", "japan1989"],
  "context_asof": "2026-07-29",
  "current_phase": 42,
  "target_depth_pct": 12.19,
  "common_strength": 1.735781,
  "common_strength_scope": "S1/S2/S3 and all display years"
}
```

---

## 4. 하락 곡선 재현 체크포인트

| date | phase | raw median | residual | factor | S1 baseline | S1 | S2 | S3 | legacy analog |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08-03 | 42.00 | 1.0000 | 1.0000 | 1.0000 | 25,914.0 | 25,914 | 25,914 | 25,914 | 25,914 |
| 2026-08-31 | 42.92 | 0.9727 | 0.9587 | 0.9293 | 26,428.2 | 24,561 | 24,187 | 23,755 | 25,176 |
| 2026-09-29 | 43.87 | 0.9962 | 0.9677 | 0.9446 | 26,952.7 | 25,459 | 24,690 | 23,815 | 23,832 |
| 2026-10-27 | 44.79 | 0.9377 | 0.8977 | 0.8292 | 27,487.5 | 22,793 | 21,769 | 20,622 | 24,690 |
| 2026-11-24 | 45.71 | 1.0139 | 0.9566 | 0.9259 | 28,032.9 | 25,957 | 24,413 | 22,713 | 26,396 |
| 2026-12-31 | 46.93 | 1.0793 | 1.0000 | 1.0000 | 28,730.0 | 28,730 | 26,508 | 24,113 | 26,412 |

산식 검산:

```text
2026-10-27 S1 = round(27487.5 × 0.8977^1.735781)
                  ≈ round(27487.5 × 0.8292)
                  = 22,793
```

즉, 10월 저점은 이벤트 캘린더가 만든 것이 아니다. 선택 역사 위상의 중앙값, 연도 detrend, -12.19% target calibration이 만든다.

---

## 5. 선택 시대별 위상 비율

각 값은 `overlay_e[phase] / overlay_e[42]`이다.

| phase | biotech2015 | dotcom | japan1989 | median |
|---|---:|---:|---:|---:|
| 42.00 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 42.92 | 0.9727 | 0.8167 | 0.9822 | 0.9727 |
| 43.87 | 0.9961 | 0.8913 | 0.9979 | 0.9961 |
| 44.79 | 0.9106 | 0.9376 | 1.0021 | 0.9376 |
| 45.71 | 0.9297 | 1.0137 | 1.0432 | 1.0137 |
| 46.67 | 0.9270 | 1.1282 | 1.0738 | 1.0738 |
| 47.19 | 0.9253 | 1.2028 | 1.0904 | 1.0904 |

관찰:

- 8월 말 median은 biotech2015가 결정한다.
- 10월 말 median은 dotcom이 결정한다.
- japan1989는 같은 구간에서 상대적으로 강하지만 median 집계에서는 상단 값이므로 직접 채택되지 않는다.
- “닷컴 하나가 전체 하락을 결정했다”는 설명은 불완전하다.

---

## 6. 세 경로 공통 모형 증거

`_structural_paths()`는 각 표시 연도와 시나리오에 대해 다음을 한다.

1. `source = scenario.paths[key].values`
2. 해당 연도의 `start_value`와 `end_value`만 추출
3. 두 값을 잇는 기하 baseline 생성
4. 공통 `raw`에서 만든 공통 residual 사용
5. 공통 strength를 거듭제곱

```text
display_s(t) / geometric_endpoint_baseline_s(t)
    = residual(t)^strength
```

오른쪽 항은 S1/S2/S3에 동일하다. 따라서 반올림 오차를 제외하면 세 경로의 정규화 구조 factor는 완전히 같다.

직렬화된 scenario-specific strength:

| key | strength | achieved depth | applied |
|---|---:|---:|---|
| S1 | 1.735781 | 12.2% | yes |
| S2 | 1.320724 | 12.1% | no |
| S3 | 0.819160 | 12.2% | no |

이 값들도 같은 raw shape의 진폭만 달리한다. scenario별 timing이나 복수 경로를 생성하지 않는다.

---

## 7. 2027 체크포인트

| date | phase | residual | factor | S1 | S2 | S3 | legacy analog raw |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2027-01-08 | 47.19 | 1.0000 | 1.0000 | 28,863 | 26,740 | 24,170 | 25,821 |
| 2027-02-08 | 48.21 | 1.0208 | 1.0363 | 30,371 | 28,099 | 25,390 | 26,568 |
| 2027-04-07 | 50.11 | 1.0221 | 1.0387 | 31,384 | 28,958 | 26,147 | 28,514 |
| 2027-06-03 | 51.99 | 1.0233 | 1.0407 | 32,420 | 29,833 | 26,919 | 32,559 |
| 2027-07-02 | 52.94 | 0.9678 | 0.9447 | 29,881 | 27,460 | 24,769 | 34,447 |
| 2027-08-04 | 54.02 | 1.0000 | 1.0000 | 32,239 | 29,577 | 26,667 | 37,956 |

2027은 완전 단조 증가가 아니며 6~7월 조정이 있다. 다만 세 시나리오가 동일한 시점에 거의 동일한 상대 낙폭을 보이므로 사용자에게는 하나의 공통 파형으로 인식된다.

---

## 8. 참조선 증거

### 8.1 정적 배열

`scenario.py::_ANALOG_VALUES`는 26개 고정 숫자다. 현재 context의 selected-era 배열을 읽는 코드가 아니다.

### 8.2 보간

```python
analog = np.interp(
    np.linspace(0, len(_ANALOG_RATIOS) - 1, len(week_dates)),
    np.arange(len(_ANALOG_RATIOS)), _ANALOG_RATIOS
) * anchor
```

26개 ratio를 52개 표시 주차 전체에 균등하게 늘린다. 원래 26개 값의 시간 단위와 현재 52개 주차의 시간 의미가 코드 계약으로 명확히 남아 있지 않다.

### 8.3 clip

```text
clip = round(anchor × 1.25) = 32,392
raw final = 37,956
```

UI는 `min(raw, clip)`을 그리므로 2027 후반 상승이 32,392에서 평평해질 수 있다.

### 8.4 라벨

UI는 이 값을 `혁신사이클 대표 참조선 · 확률 아님`으로 표시한다. lineage와 라벨의 일치 여부가 검토 대상이다.

---

## 9. anchor·위상 계보

`dualdb/config.yaml`:

| era | model_anchor | overlay_start |
|---|---|---|
| ai | 2023-01 | 2023-01 |
| dotcom | 1996-01 | 1995-01 |
| japan1989 | 1985-01 | 1985-01 |
| biotech2015 | 2013-01 | 2013-01 |

`context_bridge._overlay()`는 `overlay_start`를 기준으로 값을 100에 재기준한다. `scenario_structure._analog_shape()`는 AI 배열 길이로 `current_phase=42`를 만든 뒤 모든 선택 시대 배열의 같은 index를 읽는다.

따라서 dotcom만 모델 anchor보다 12개월 앞선 좌표를 사용한다. 이것이 의도된 build-up 비교인지, 구조경로에 잘못 재사용된 것인지 계약 해석이 필요하다.

---

## 10. k-NN lineage 관찰

최신 context 행:

```text
run_ts=2026-07-30T16:38:37
analog.asof=2026-07-29
selected_eras=[biotech2015,dotcom,japan1989]
```

현재 `dualdb/db/dualdb.sqlite`에서 조회된 최신 `model_run(model='knn_analog')`은 다음이었다.

```text
run_id=5
asof=2026-07-17
created_at=2026-07-19T23:03:59
standardize=dotcom-only z
```

패키지의 정본은 파일 context지만, 현재 재구축 SQLite 원장만으로 2026-07-29 multi-era 선택을 직접 되살릴 수 있는지는 불명확하다. 이는 곧바로 데이터 오류를 뜻하지 않으며, model_run lineage 보존 여부를 `BLOCKED` 후보로 검토해야 한다.

---

## 11. 캘리브레이션 불변성

r8 V-1은 era 교체 시 다음을 공개한다.

- native MDD 범위: -14.5%~-2.9%
- calibrated MDD 범위: -12.2%~-12.1%
- 시대 선택은 위험창 중심월을 이동
- 화면 깊이는 -12.19% target에 재수렴

즉, 시대 선택 민감도 표의 native 차이는 화면 깊이 민감도가 아니다. 현재 화면 깊이는 base rate target이 고정한다.

---

## 12. 회귀·무결성 증거

| 검사 | 결과 |
|---|---|
| 전체 pytest | 383 passed |
| snapshot 재현 | 83/2/15 동일 |
| quantile 비교 | 1,764셀 mismatch 0 |
| r7 archive SHA | V-1 전후 동일 |
| data.json | 311,360 bytes |
| ledger audit | violation 0 |
| GitHub verify/pages | green at `dea62a1` |

이 검사는 현재 구현의 결정성과 불변성을 증명하지만, 경제적 정합성이나 시나리오별 동학의 타당성을 증명하지는 않는다.

---

## 13. 검토자가 먼저 반증할 가설

| ID | 가설 | 현재 1차 관찰 |
|---|---|---|
| H1 | 2026 하락은 이벤트 전망이다 | 반증 가능성이 높음. 구조 위상+보정 결과 |
| H2 | 세 시나리오는 서로 다른 역사 모형이다 | 반증됨. 공통 residual과 strength |
| H3 | 회색선은 최신 selected-era 대표선이다 | 반증됨. 정적 `_ANALOG_VALUES` |
| H4 | 닷컴이 굵은 경로의 main이다 | 반증됨. 선택 3시대 중앙 중 하나 |
| H5 | 2027은 완전 단조다 | 반증됨. 6~7월 -7.8~-8.0% 조정 존재 |
| H6 | 2027 시나리오 timing은 서로 다르다 | 반증 가능성이 높음. 공통 factor |
| H7 | k-NN neighbor date가 미래 shape 출발점이다 | 반증 가능성이 높음. era label만 사용 |
| H8 | current DB에서 context selection을 완전 재현할 수 있다 | 확인 필요·BLOCKED 후보 |

---

## 14. 이 증거집이 답하지 않는 것

- 미래 실제 시장 방향
- 2026년 10월 조정의 실제 사건확률
- dotcom-only가 multi-era보다 우월한지 여부
- 최선의 시나리오별 경로 생성 방법
- 사용자 견해의 정답 여부

위 항목은 OOS 연구와 추가 사전등록 없이는 판정할 수 없다.
