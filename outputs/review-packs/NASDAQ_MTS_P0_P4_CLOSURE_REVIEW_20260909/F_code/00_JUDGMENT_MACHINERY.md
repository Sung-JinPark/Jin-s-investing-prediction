# 판정 기계 (Judgment Machinery) — V13-VOL 트랙이 통과·실패를 결정하는 방식

> 작성 2026-09-09 (KST). 대상: 이 팩만 보는 외부 검토관(통계 전문가 / 프론티어 LLM).
> 이 문서의 모든 수치·인용은 팩 안 파일에서 직접 읽어 확인한 것이다. 확인하지 못한 것은 `[미확인]` 으로 표기했다.
>
> **경로 규약.** `F_code/...` 는 이 팩 안 사본이고, 저장소 원본 경로는 각 절에 병기한다.
> `F_code/timeseries_v13/*.py` ← `src/ai_fc/timeseries_v13/*.py`,
> `F_code/timeseries_v13_vol_display.py` ← `src/ai_fc/timeseries_v13_vol_display.py`,
> `F_code/tools/*.py` ← `tools/*.py`, `F_code/tests/*.py` ← `src/tests/*.py`.
> 인용한 줄 번호는 팩 사본 기준이며 원본과 같다.

---

## 0. 이 트랙이 판정하는 대상

9개 셀(cell)의 **이벤트 확률**이다. 표적은 계약
`A_contracts/multivariate_timeseries_v13_vol.yaml` 이 고정한다.

| 표적 | 정의 | 셀 |
|---|---|---|
| `vix_touch` | 원점 이후 h 영업일 안에 VIX 종가 ≥ K 를 한 번이라도 터치 | K ∈ {25, 30} × h ∈ {5, 21, 63} = 6셀 |
| `rv_exceedance` | 원점 이후 h 영업일 안에 RV21(연율) > θ = 0.1694 를 한 번이라도 초과 | h ∈ {5, 21, 63} = 3셀 |

셀 순서는 `F_code/timeseries_v13/contracts.py:27` 의 `CELL_ORDER` 로 고정
(`vix25_h5, vix25_h21, vix25_h63, vix30_h5, vix30_h21, vix30_h63, rv_h5, rv_h21, rv_h63`).
창은 설계창 2007-01-01~2014-12-31(분할 2011-01-01), 홀드아웃 2015-01-01~2018-12-31,
봉인 2019-01-01~latest (`contracts.py:24,31`, 계약 `stopping_points`).

champion 은 **9셀 전부 `persistence_pb`** — 절편 + 당일 수준 1피처의 로짓이다
(계약 `gates.champion.cells`, `E_artifacts/vol/champion_coefficients.json`).
`finalist_id = V13VOL_champion_aec80c65038b`.

라벨 생성기는 `F_code/timeseries_v13/features.py:96-109` 이며,
원점 i 의 라벨은 **엄격 전방창** `[i+1, i+h]` 만 본다(당일 미포함). 창이 패널 끝을 넘으면 `NaN`
(= label-incomplete origin, 채점 제외).

---

## 1. 판정 기계 목록

정본 구현은 전부 `F_code/timeseries_v13/scoring.py` (부트스트랩·귀무·분해·가드)와
`F_code/timeseries_v13/features.py` (수치층·대역)에 있다. `scoring.py` 의 헤더 주석이 밝히듯,
이 파일은 새 규칙을 만든 것이 아니라 rung-1 러너 `F_code/tools/v13_vol_run.py` 가 실제로 쓴 규칙을
라이브러리로 승격한 것이고, 그 동치성은 패리티 테스트로 고정되어 있다(§6).

계약이 못 박은 좌표는 하나뿐이며 모든 기계가 이것을 공유한다
(`contracts.py:34-36`, 계약 `gate.uncertainty`):

```
BLOCK_LENGTH = 13            # ℓ — 정지 블록 평균 길이
BOOTSTRAP_REPLICATES = 2000  # B
BOOTSTRAP_SEED = 20260907
CI_INTERVAL = (5, 95)        # CI90 백분위
MDE_Z = 1.645                # MDE = 1.645 · bootstrap_se
Z80 = 1.2815515655446004     # Φ⁻¹(0.90) — 80% 양측 대역
```

### 1.1 정지 블록 부트스트랩 — `block_boot_ci`

**파일** `F_code/timeseries_v13/scoring.py:27-52`.
**참조 구현** `F_code/tools/v13_vol_run.py:80-89` (`block_boot_ci`).

입력은 쌍대 손실차 벡터 `d`(길이 n, 양수 = 후보 우세). 한 복제(replicate) b 는:

```
반복 { s ~ Uniform{0, …, n−1};  L ~ Geometric(p = 1/ℓ),  ℓ = 13
       인덱스 (s + 0…L−1) mod n 을 이어붙임 }   총길이 ≥ n 이 될 때까지
θ*_b = mean( d[ 이어붙인 인덱스[:n] ] )
```

즉 시작점 균등·블록 길이 기하분포·순환(circular) 재표집 — Politis–Romano stationary bootstrap 이다
(평균 블록 길이 = ℓ = 13). B = 2000 회 반복 뒤:

```
CI90 = [ percentile(θ*, 5),  percentile(θ*, 95) ]     # 백분위 구간 (bias-corrected 아님)
se   = std(θ*, ddof = 1)
MDE  = 1.645 · se
mean = mean(d)                                        # 표본 평균 — 부트스트랩 평균이 아니다
```

주의할 점 두 가지. ① 보고되는 점추정 `mean` 은 원표본 평균이고 CI 는 부트스트랩 분포의 백분위이므로,
둘은 서로 중심이 다를 수 있다(BCa·studentized 보정 없음). ② `n == 0` 이면 NaN 을 담은 dict 를
돌려주고 판정 다리로 넘어가지 않는다.

### 1.2 쌍대 Brier 신뢰구간 — `paired_brier_ci`

**파일** `scoring.py:55-72`.

```
BS_base = (p_baseline − y)²
BS_cand = (p_candidate − y)²
d       = BS_base − BS_cand                     # 양수 = 후보 우세
(CI90, se, MDE) ← block_boot_ci(d)

lower_gt_zero = CI90_low  >  0     # 엄격 우월  → 홀드아웃 G1 형
upper_ge_zero = CI90_high ≥  0     # 유의 열위 아님(비열화) → 홀드아웃 G2 형
```

계약 `gate.primary` 원문("각 rung(≠기후)이 기후 대비 쌍대 Brier 손실차 CI90 하한 > 0 (엄격부등호)")과
`stopping_points.holdout.gate.G1/G2` 가 이 두 술어에 1:1 대응한다. 부호 규약을 뒤집었을 때
비열화가 통과하면 안 된다는 것이 회귀 테스트로 못 박혀 있다
(`F_code/tests/test_timeseries_v13_scoring.py:42`).

파생 지표 `brier_skill_score` (`scoring.py:75-80`): `BSS = 1 − BS_model / max(BS_clim, 1e-9)`,
여기서 `BS_clim` 은 **고정 기저율 상수**에 대한 Brier 다. 보고용이며 판정 다리가 아니다.

### 1.3 건전 귀무 — y-block 순열

**파일** `scoring.py:84-102` (`y_block_permutations`, `y_block_null_pass_rate`).

```
starts = 0, ℓ, 2ℓ, …            # ℓ = 13, 인덱스 0에 고정된 분할
draw:  블록 순서를 무작위 순열 → 이어붙임 → [:n]
       (블록 길이 합 = n 이므로 라벨 다중집합은 정확히 보존된다)
pass_rate = #{ decide(y_perm) == True } / draws
```

**임계 0.10** (계약 `gate.negative_control.threshold`: "통과율 <= 0.10. 초과 시 그 rung 의 채택 무효.").

무엇을 보존하고 무엇을 파괴하는가가 핵심이다.
보존: 라벨 다중집합(따라서 창 기저율), 블록 내부 자기상관.
파괴: 예측 p 와 라벨 y 의 **정렬(pairing)**. 즉 p→y 관계가 없는 세계에서 같은 판정 절차가
얼마나 자주 "통과"를 내는지를 잰다.

홀드아웃에서의 결정 함수는 `F_code/timeseries_v13/holdout.py:196-200` 에 있다:

```python
def _decide(perm, _p=p, _base=clim_fixed[name]) -> bool:
    d = ((_base - perm) ** 2) - ((_p - perm) ** 2)
    return bool(S.block_boot_ci(d, b=300)["ci90"][0] > 0)

null_rate = S.y_block_null_pass_rate(yv, _decide, draws=NULL_DRAWS, seed=C.BOOTSTRAP_SEED)
```

즉 **모형은 고정**(재적합 없음)이고 라벨만 순열한다. `NULL_DRAWS = 200` (`holdout.py:34`).
설계창 사다리에서는 라벨 순열 뒤 **양방향 재적합·재채택**까지 돌리므로 계산이 무거워
경량 경로(`_boot_lower_fast`, `_adopt_fast`)를 쓴다 — §8 (b)(c)에 그 차이를 적었다.

### 1.4 Murphy 신뢰도 분해 — `murphy_reliability`

**파일** `scoring.py:106-129`. 승계 원본 `F_code/tools/v13_vol_rung2.py:36-49` (`reliability`).

p 를 [1e-6, 1−1e-6] 로 클립하고 [0,1] 을 등간격 10구간으로 나눈 뒤:

```
ȳ   = mean(y)
unc = ȳ(1 − ȳ)
rel = Σ_k (n_k/n)(p̄_k − ō_k)²          # 낮을수록 보정 좋음
res = Σ_k (n_k/n)(ō_k − ȳ)²            # 높을수록 분해능 좋음
brier_check = unc − res + rel           ≈ Brier
```

빈 구간은 건너뛴다. 마지막 구간만 p = 1 을 포함한다(`scoring.py:120`).
계약은 이것을 **보고 의무**로만 규정한다 — `gate.reliability`: "…보고 의무(판정 다리 아님)",
`stopping_points.holdout.gate.G3_reliability_report`: "…판정 다리 아님". 홀드아웃 판정에서
G3 는 PASS/FAIL 을 만들지 않는다(`holdout.py:204`: `passed = g1_ok and g2_ok and g4_ok`).

### 1.5 다중비교 — `family_p_binomial`

**파일** `scoring.py:133-135`.

```
P(K ≥ k_obs) = Σ_{k=k_obs}^{n} C(n,k) · p^k · (1−p)^{n−k},   p = 0.05
```

계약 `gate.multiplicity`: "family P(k>=k_obs) <= 0.05 병기".
코드 주석 자체가 한계를 명시한다 — "셀 독립 가정의 참고값. 셀 종속 caveat 를 항상 병기한다."
9셀은 같은 VIX·RV 패널과 겹치는 지평을 공유하므로 독립이 아니다(§8 (i)).

실제 적용값: 홀드아웃 `P(k ≥ 3 | n = 9, p = 0.05) = 0.008361039546874999`
(`E_artifacts/runs/holdout_V13VOL_champion_aec80c65038b.json`, 계약 `publication.holdout_family_p: 0.008361`).
rung-4 는 `P(k ≥ 0 | n = 27) = 0.9999999999999989`
(`E_artifacts/vol/ladder_rung4_macro.json`).

### 1.6 국면(에피소드) 런 계산 — `episode_runs` / `degeneracy_report` / `episode_spans`

**파일** `scoring.py:139-194`.

이 트랙에서 가장 독창적인 판정 장치다. 라벨이 h영업일 전방창으로 만들어져 **이웃 원점이 강하게
겹치므로 사건 '일수'는 유효 자유도를 과대평가한다.** 그래서 클래스별 **독립 국면(연속 run) 수**를
함께 잰다.

```
episode_runs(y):  유한 라벨만 훑으며 값이 바뀔 때마다 해당 클래스의 run 을 +1.
                  NaN 은 건너뛰되 구간을 끊지 않는다.

degeneracy_report(y, min_events, min_episodes):
    counts_ok   = min(events, non_events)              ≥ min_events      (기본 20)
    episodes_ok = min(event_runs, non_event_runs)      ≥ min_episodes    (기본 5)
    verdict = ok                          if counts_ok ∧ episodes_ok
            = episode_thin                if counts_ok ∧ ¬episodes_ok
            = untestable_by_construction  if ¬counts_ok
```

`episode_spans(dates, y, value)` 는 해당 클래스의 연속 구간 목록을 돌려주어 판정서가 국면을
날짜로 명시할 수 있게 한다.

**임계값의 출처를 계약이 스스로 공시한다** (계약 `degeneracy_guard.provenance`):
"임계 min_episodes=5 는 설계창을 실측한 뒤 정한 값이다 — 숨기지 않고 공시한다." 그래서 사용처를
세 곳으로 제한한다: (a) 이미 실행된 rung 판정과 게이트 산술은 **소급 변경하지 않는다**,
(b) 홀드아웃 창에서 채점 불가 셀 제외, (c) 표시·배선 자격 제한. 즉 게이트를 **느슨하게 하는
방향으로는 쓰이지 않는다**. 이 문장의 존재 자체가 계약 테스트로 강제된다
(`F_code/tests/test_timeseries_v13_vol_contract.py:251`: `assert "소급" in guard["provenance"] and "느슨" in guard["provenance"]`).

설계창 실측(`E_artifacts/vol/guard_mde_design.json`, content_hash `e8cf914b4ea11cfa…`, n = 2014):

- **사건 수 가드(≥20) 실패: 0셀** — 최소가 27이라 구속력이 없었다.
- **국면 가드(≥5) 실패: 6셀** — `vix25_h21, vix25_h63, vix30_h5, vix30_h21, vix30_h63, rv_h63`.
- 가장 극단: `vix30_h21` 후반창 사건 109일 = **1국면**(2011-07-06~2011-12-07),
  `vix30_h63` 후반창 151일 = **1국면**(2011-05-05~2011-12-07)
  (`B_verdicts/V13_GUARD_MDE_20260909.md` §2).

그리고 이 가드가 예측력이 있었다는 것이 홀드아웃에서 확인됐다 —
국면이 3인 세 셀의 G4 귀무 통과율이 1.000 / 0.965 / 0.485, 국면 4인 셀이 0.805,
국면 5~8인 셀들이 0.000~0.125 로 **거의 단조 대응**한다
(`B_verdicts/V13_HOLDOUT_VERDICT_20260909.md` §2, 원자료 `E_artifacts/runs/holdout_*.json`).

### 1.7 델타법 80% 대역 — `delta_method_se` + `block_bootstrap_cov`

**파일** `features.py:151-158` (델타법), `features.py:161-178` (계수 공분산),
소비처 `F_code/timeseries_v13/pipeline.py:53-60`.

```
z        = [1, (x − μ)/σ]                     # 동결 μ, σ 좌표
η        = zᵀ β
p        = σ(η) = 1/(1 + e^{−η})              # [1e-6, 1−1e-6] 클립
Var(η)   = zᵀ Cov(β) z
se_p     = p(1 − p) · sqrt(max(Var(η), 0))    # 델타법
band80   = [ max(0, p − Z80·se_p),  min(1, p + Z80·se_p) ],  Z80 = Φ⁻¹(0.90)
```

`Cov(β)` 는 **재적합 부트스트랩**으로 얻는다(`block_bootstrap_cov`): §1.1 과 **같은** 재표집 규칙
(정지 블록 ℓ=13, 순환, B=2000, seed 20260907)으로 (X, y) 를 재표집하고 매 복제마다 로짓을 재적합해
β_b 를 모은 뒤 `np.cov(β.T, ddof=1)` 을 취한다. 재적합은 `tol=1e-9` 조기 정지를 쓴다.

**이 대역의 의미는 계수 불확실성이지 보정(calibration) 구간이 아니다.** 계약
`live_display.band80.meaning: coefficient_uncertainty_not_calibration`,
동결 artifact `band80.meaning` 동일, 포인터 footnote 도 그 문장을 싣는다
(`pipeline.py:88`, `E_artifacts/vol/vol_latest.json`). h63 셀에 isotonic 파생층이 있으면
p 와 대역 양끝을 모두 PAV 사상에 통과시킨 뒤 순서를 다시 맞춘다(`pipeline.py:57-60`) —
현재 champion 은 세 h63 셀 모두 `raw` 로 fallback 되어 이 경로가 비활성이다
(`E_artifacts/vol/ladder_pb_baseline.json` `iso_h63_derived_layer` = {vix25_h63: raw, vix30_h63: raw, rv_h63: raw}).

**적합기 자체** (`features.py:122-144`): 절편 + z-score(ddof=0, σ<1e-9 → 1.0) 설계행렬,
Newton 200회 고정(`tol=None` 이면 수렴 검사 없이 정확히 200회), ridge `l2 = 1e-3`,
확률 클립 [1e-6, 1−1e-6]. 하이퍼파라미터는 동결 artifact 의 `hyperparameters` 블록에 그대로
기록되어 있다(`iters: 200, l2: 0.001, zscore_ddof: 0, sd_floor_rule: "sd<1e-9 -> 1.0", optimizer: newton`).

### 1.8 부속 — PAV isotonic (h63 파생층)

`features.py:182-199` (`pav`, `pav_apply`), 교차적합 원본 `F_code/tools/v13_vol_rung3_pb.py:114-161`.
설계창을 시간순 k=5 연속 블록으로 나눠 OOF 확률을 만들고(경계 embargo = h 원점 양측),
그 위에 가중 PAV 를 적합한다. **fallback 이 사전등록되어 있다** — 어느 방향이든
(BS_raw − BS_iso) CI90 상단 < 0 (iso 유의 열위)이면 그 셀은 raw 유지(계약
`reliability.cross_fit_isotonic_h63.fallback_rule_preregistered`). 실제로 세 셀 모두 fallback 발동.

---

## 2. "건전한 귀무" 란 무엇이며, 왜 p-순열을 금지했는가

### 2.1 정의

건전한 귀무(sound null)는 **검정하려는 관계만 파괴하고 나머지 구조는 보존하는** 대조군이다.
여기서 검정 대상은 "예측 p 가 라벨 y 를 안다"이므로, 건전한 귀무는

- **y 를 블록 순열**하고 (라벨 다중집합·블록 내부 자기상관 보존, p→y 정렬만 파괴)
- p 는 원래 날짜에 그대로 둔 채
- **같은 판정 절차를 다시 돌려** 통과율을 잰다.

통과율이 0.10 을 넘으면, 그 절차의 "통과"는 p→y 관계가 아니라 다른 무언가로 설명된다.

### 2.2 금지 규정

계약이 두 곳에서 못 박는다.

```yaml
# A_contracts/multivariate_timeseries_v13_vol.yaml:65-68
  negative_control:
    # T-A 교훈: p-순열 귀무는 누수. 사건 라벨(y) 블록순열 = 건전 귀무를 쓴다.
    null: y-block-permutation (ℓ=13) — 이벤트 라벨을 블록 순열해 스킬 통과율 측정
    threshold: 통과율 <= 0.10. 초과 시 그 rung 의 채택 무효.

# 같은 파일 :131  (prohibitions 블록)
  p_permutation_null_as_negative_control: true   # T-A 에서 누수 확인 — 사용 금지
```

코드에도 같은 문장이 박혀 있다 — `scoring.py:86`:
`"""사건 라벨의 블록 순열 — p-순열은 누수라 계약이 금지(T-A 교훈)."""`

### 2.3 p-순열이 실제로 통과시킨 사례 (T-A)

이것이 금지의 실증 근거다. 다른 트랙(V12 계열 first_touch 재보정 맵, "T1 맵")의 검정 기계를
수리하려고, 세 가지 블록 보존 귀무를 사전등록해(`docs/design/v13_next_design_prereg_260907.md` §1,
결과 전 커밋 `cda1176b`) 각각 1000 복제로 돌렸다.

**도구** `F_code/tools/v13_ta_null_repair.py` · **원자료** `E_artifacts/prereg/ta_null_repair.json`
· **판정서** `B_verdicts/V13_TA_NULL_REPAIR_VERDICT_20260907.md`.

| 귀무 (ℓ=13, 복제 1000) | 무엇을 섞는가 | T1 pooled 통과율 | 판정 |
|---|---|---|---|
| **N-p-block** | **p 를 블록 순열, y 고정** | **0.201** | **초과 — 누수** |
| N-y-block | y 를 블록 순열, p 고정 | 0.000 | 통과 |
| N-blk-pair | (p, y) 쌍을 함께 블록 순열 | 0.000 | 통과 |

셀별로 보면 누수는 h21 에 집중된다: N-p-block 의 `t1_pass_rate_by_cell` = {h21: 0.361, h63: 0.041}.
같은 파일이 기록한 이전 세대 i.i.d. p-순열(N1)의 기준값은 `n1_baseline_t5_pooled = 0.254`.
즉 **p-순열 귀무는 진짜 p→y 관계를 완전히 파괴한 데이터에서도 T1 맵을 20~25% 채택시켰다.**

기전은 판정서 §"무엇을 뜻하는가" 가 설명한다 — 상단 수축(shrinkage)이 확률을 기저율 쪽으로 당기면,
**창의 기저율만 맞아도** 고정 상수 대비 Brier 가 줄어든다. p 의 분포 구조만으로 얻는 자명한 이득이다.
반대로 관계를 섞는 두 귀무(y 순열·쌍 순열)에서는 0.000 — 진짜 개입은 유효하게 검정된다.
결론은 사전등록 기준(셋 다 ≤ 0.10) 미충족 → **NOT_REPAIRED**, 그 트랙 종결.

### 2.4 같은 기전의 변동성 판 — 홀드아웃 `vix30_h5`

T-A 의 교훈이 V13-VOL 에서도 그대로 재현됐고, 이번에는 **건전 귀무가 그것을 잡았다**.

`E_artifacts/runs/holdout_V13VOL_champion_aec80c65038b.json` 의 `vix30_h5`:

| 항목 | 값 |
|---|---|
| 원점 | 1001 |
| 사건/비사건 | 25 / 976 (기저율 0.025) |
| 국면(event runs) | 3 |
| BSS(기후 대비) | **+0.615** |
| G1 CI90 | **[+0.0259, +0.0326]** — 0 을 한참 넘는다 |
| **G4 y-block 귀무 통과율** | **1.000** |
| 판정 | **fail (G4)** |

라벨을 블록 순열해도 같은 판정이 **200/200 재현된다.** 그 "스킬"은 VIX 수준과 사건의 연관이 아니라
사건이 25/1001 로 극히 드물다는 사실에서 나온다 — 매끄러운 확률이면 무엇이든 고정 기후상수(0.407)보다
Brier 가 작다. **만약 이 트랙이 p-순열을 귀무로 썼다면 이 셀은 통과했을 것이다.**

홀드아웃 6개 실패 셀 중 **4셀이 기후 대비로는 통과했는데 G4 에서 무너졌다**
(`vix25_h5` 0.125 · `rv_h63` 0.805 · `vix30_h21` 0.965 · `vix30_h5` 1.000).
건전 귀무가 없었으면 9셀 중 7셀이 통과로 보고됐을 것이다.

---

## 3. 홀드아웃 verb 의 가드 순서 — 승인 → 예산 → **데이터 읽기 전 거부**

**파일** `F_code/timeseries_v13/holdout.py` ← `src/ai_fc/timeseries_v13/holdout.py`.
**CLI** `timeseries-v13-vol-holdout --approval-receipt <id>` (`src/ai_fc/cli.py:502-518`).

### 3.1 순서를 코드로

`score_holdout` 본문(`holdout.py:114-149`)의 실행 순서다. 주석은 원문 그대로다.

```python
def score_holdout(root, *, approval_receipt_id, knowledge_cutoff=None):
    contract  = C.load_contract_v13(root)                       # 114-118  계약 로드 (시장데이터 아님)
    protocol  = contract.get("development_protocol") or {}
    champion  = (contract.get("gates") or {}).get("champion") or {}
    finalist_id = str(champion.get("finalist_id") or "")
    if not finalist_id or not champion.get("cells"):            # 120-121
        raise TimeSeriesV13HoldoutError("champion is not fixed — nothing to score")

    _require_named_verb(contract)                               # 123  ① 계약 개정 확인
    receipt = _require_approval(root, approval_receipt_id, finalist_id)   # 124  ② 승인 원문
    _require_budget(root, protocol, finalist_id)                # 125  ③ 예산·중복 소모

    frozen_cfg = contract.get("frozen_coefficients") or {}      # 127-131 ④ 동결 계수 3중 핀
    frozen = C.load_frozen_coefficients(
        root, expected_sha256=frozen_cfg.get("sha256"),
        expected_content_hash=frozen_cfg.get("content_hash"),
        expected_finalist_id=frozen_cfg.get("finalist_id"))
    ...
    # 패널은 홀드아웃 끝에서 절단한다 — 봉인창 바이트 미열람.
    cutoff = knowledge_cutoff or datetime.now(timezone.utc).isoformat(timespec="seconds")
    panel = F.build_panel(read_market_observations(root, knowledge_cutoff=cutoff),   # 141  ★ 최초 데이터 읽기
                          start=HISTORY_START, end=holdout_end)
```

**`read_market_observations` 호출은 141행이 유일하며, 네 개의 거부 지점 전부보다 뒤에 있다.**

각 거부 지점의 판정 조건:

| # | 함수 | 줄 | 거부 조건 |
|---|---|---|---|
| ① | `_require_named_verb` | 55-61 | `development_protocol.holdout_execution_path != "named_verb_guarded"` — 계약 개정이 선행돼야 한다 |
| ② | `_require_approval` | 63-86 | 영수증 id 공란 / 원장에 없음 / `decision_id != "V13-D3"` / 승인 원문 공란 / 원문에 `"V13-D3"` 또는 정확한 `finalist_id` 문자열이 없음 / `approval_scope.holdout_single_scoring is not True` / `semantic_reference.finalist_id` 불일치 |
| ③ | `_require_budget` | 89-98 | 같은 finalist 가 이미 원장에 있음 / distinct finalist 수 ≥ `holdout_maximum_finalists`(=3) / finalist 가 `holdout_finalists_preregistered` 접두에 없음 |
| ④ | `load_frozen_coefficients` | `contracts.py:94-121` | 계약에 핀이 없음 / 파일 sha256 불일치 / `content_hash` 불일치(기록값·재계산값 둘 다 대조) / `finalist_id` 불일치 / model identity 불일치 / 셀 집합이 `CELL_ORDER` 밖 |

패널은 `end=holdout_end`(= 2018-12-31)로 절단되고 원장 행은 `sealed_bytes_read: False` 를 단언한다
(`holdout.py:227`, 실제 기록 `E_artifacts/runs/holdout_*.json` `"sealed_bytes_read": false`,
`"panel_truncated_at": "2018-12-31"`).

퇴화·국면 가드는 **실행 시점에** 홀드아웃 창에 적용한다(`holdout.py:164`). 모듈 헤더가 이유를 밝힌다 —
"사전 점검은 미열람 위반"(`holdout.py:12`).

결과 무관 append 는 `holdout.py:242` 한 줄이다: `append_unique(root, C.HOLDOUT_LEDGER_RELATIVE, row, key="finalist_id")   # 결과 무관 append`.

### 3.2 이 파일에 적합 함수가 없다는 사실

`_predict` 는 예측만 한다 — `holdout.py:105-111`:

```python
def _predict(cell, X):
    """동결 계수로만 예측한다 — 이 모듈에 적합 함수는 없다."""
    p = F.logit_predict(np.asarray(cell["beta"], float), np.asarray(cell["mu"], float),
                        np.asarray(cell["sd"], float), X)
    if cell.get("iso_map"):
        p = F.pav_apply(cell["iso_map"], p)
    return np.asarray(p, float)
```

이 파일이 `features` 에서 쓰는 것은 `build_panel · fill_rv_nan · ewma · labels_vix · labels_rv ·
feature_matrix · logit_predict · pav_apply` 뿐이다. **`logit_fit` 도 `block_bootstrap_cov` 도 등장하지 않는다.**

그리고 그 사실이 소스 문자열 수준의 테스트로 고정되어 있다
(`F_code/tests/test_timeseries_v13_holdout.py:191-198`):

```python
def test_holdout_module_has_no_refit_path_and_no_sealed_verb() -> None:
    source = (ROOT / "src/ai_fc/timeseries_v13/holdout.py").read_text(encoding="utf-8")
    assert "logit_fit" not in source, "홀드아웃 모듈에 적합 함수가 있으면 안 된다 (holdout_refit 금지)"
    assert "block_bootstrap_cov" not in source, "계수 재추정 경로 금지"
    assert "sealed_backtest" not in source and "2019-01-01" not in source, "봉인창 진입점 부재"
    workflows = list((ROOT / ".github/workflows").glob("*.yml"))
    assert not [w for w in workflows if "timeseries-v13-vol-holdout" in w.read_text(encoding="utf-8")], \
        "홀드아웃 verb 는 어떤 워크플로에서도 호출되지 않는다 (무인 자동화 밖)"
```

계약 `prohibitions.holdout_refit: true` 와 짝을 이룬다.

### 3.3 "데이터 읽기 전 거부"의 기계적 증명

테스트 픽스처가 `read_market_observations` 를 호출 계수기로 바꿔 놓고, 각 거부 케이스마다
**`assert not _archive`** — 즉 관측을 한 번도 읽지 않았음을 단언한다
(`test_timeseries_v13_holdout.py:112-166`). 계약 미개정(129행), 승인 부재/미존재 영수증(138행),
잘못된 결정·문구·범위·finalist 5종(154행), 중복 소모·예산 소진(166행) 전부.
승인 부재 케이스는 원장 파일 자체가 생성되지 않았음도 확인한다(139행).

실제 소모 시에도 같은 검증을 했다는 기록이 판정서에 있다
(`B_verdicts/V13_HOLDOUT_VERDICT_20260909.md` §5): "실행 전 드라이런 3종(승인 없음·가짜 영수증·다른 결정
영수증)이 **데이터를 읽기 전에** 거부됨을 확인했고 그때 원장은 생성되지 않았다."

### 3.4 실제 소모 1회 — 기록

| 항목 | 값 | 출처 |
|---|---|---|
| 승인 원문 | `V13-D3 홀드아웃 1회 소모 승인 finalist=V13VOL_champion_aec80c65038b` | `E_artifacts/ledgers/approvals.jsonl` (`v13-approval:V13-D3:2026-09-09:r1`) |
| 창 | 2015-01-01 ~ 2018-12-31 | 원장 행 `window` |
| 결과 | `partial` — 9셀 중 3셀 통과 (`vix25_h21, rv_h5, rv_h21`) | 원장 `status`, `pass_cells` |
| family P | 0.008361039546874999 | 원장 `family_p_binomial` |
| 계수 sha256 | `1a857850…` | 원장 `coefficients_sha256`, 계약 `frozen_coefficients.sha256` |
| 소모 슬롯 | 1/3 (원장 1행, `holdout_scorings.jsonl`) | `E_artifacts/ledgers/holdout_scorings.jsonl` |

---

## 4. 알려진 버그와 수정 — band80 부트스트랩 좌표 불일치

### 4.1 무엇이 틀렸나

`block_bootstrap_cov` 는 원래 **재표집마다 그 표본의 (μ_b, σ_b) 로 다시 표준화한** β_b 를 모아
공분산을 취했다. 그런데 `delta_method_se` 는 `z = [1, (x − μ)/σ]` 를 **동결 μ/σ 좌표**에서 만든다.
서로 다른 좌표계의 β_b 를 섞으면 표준화 인자의 표본 변동이 Cov(β) 에 얹혀 **대역이 과대**해진다.

### 4.2 수정 — 고정 표준화

`features.py` 두 곳이다.

```python
# features.py:122-131  — logit_fit 에 standardize 인자 신설
def logit_fit(X, y, *, iters=200, l2=1e-3, tol=None,
              standardize: tuple[np.ndarray, np.ndarray] | None = None):
    """...
    standardize=(mu, sd) 를 주면 그 좌표로 고정 표준화한다 — 부트스트랩 Cov(β) 는 반드시 동결 μ/σ 좌표에서
    계산해야 delta_method_se 와 같은 좌표계가 된다 (재표집마다 재표준화하면 β_b 가 서로 다른 좌표계에 놓인다).
    """
    mu, sd = standardize if standardize is not None else standardize_params(X)

# features.py:161-178  — 전체 표본 (μ,σ) 를 한 번 구해 모든 재적합에 넘긴다
def block_bootstrap_cov(X, y, *, seed, block=BLOCK_LENGTH, b=BOOTSTRAP_REPLICATES):
    """...
    모든 재표집 적합은 전체 표본의 (μ, σ) 로 고정 표준화한다 — 동결 계수·delta_method_se 와 같은 좌표계.
    """
    rng = np.random.default_rng(seed); n = len(y)
    fixed = standardize_params(X)                  # ← 한 번만
    ...
        beta, _, _ = logit_fit(X[take], y[take], tol=1e-9, standardize=fixed)   # ← 고정 좌표
    return np.cov(np.asarray(betas).T, ddof=1)
```

즉 **`standardize` 인자의 존재 자체가 이 수정의 흔적**이다. 인자가 없던 시절에는
`logit_fit` 이 항상 자기 표본으로 표준화했다.

### 4.3 영향 — 확률은 그대로, 대역만 좁아짐

`D_governance/DECISIONS.md` ("**정정 2 — band80 부트스트랩 좌표 불일치 (같은 검토, numerics 렌즈)**",
2026-09-08 푸시 전 적대적 검토):

- 재동결: sha256 `51815bde…` → **`1a857850…`**
- 반창 대사(reconciliation) `2e-15` 동일 — 즉 **적합 자체는 바뀌지 않았다**
  (동결 artifact `reconciliation.max_abs_bss_diff = 1.9984014443252818e-15`, `pass: true`)
- 확률 p **무변경**, **대역만 좁아짐**. 예시: `vix25_h63` [18%, 38%] → **[21%, 36%]**
- 재동결은 라이브 원장에 **새 행**으로 남고 이전 artifact 바이트는 git 이력에 보존

원장에 그 흔적이 그대로 있다 (`E_artifacts/ledgers/vol_live.jsonl`, run_id 목록):

```
v13vol-2026-09-04              ← 수정 전 (run_id 에 계수 sha 접미가 없던 판)
v13vol-2026-09-04-1a857850     ← 수정 후 재발행 (같은 as_of, 새 계수)
v13vol-2026-09-08-1a857850
```

`pipeline.py:150-151` 이 그 규칙을 명시한다 —
"run_id 는 (as_of, 계수 sha 앞 8자) — 같은 관측·같은 계수의 재실행은 한 행(멱등), 재동결은 새 행(이력 보존)."

### 4.4 같은 계열의 선행 정정 — "손실차 se 를 P 의 se 로 쓰지 말 것"

계약 `live_display.band80` 에 주석으로 박혀 있다(`A_contracts/…v13_vol.yaml:309`):

```yaml
  band80:
    method: delta_method_block_bootstrap_cov   # 정정: 사다리 json 의 se 는 손실차 se — P 의 se 가 아니므로 사용 금지
```

사다리 json 의 `se`/`mde` 는 **쌍대 손실차 d 의 표준오차**이지 확률 P 의 표준오차가 아니다.
이것을 대역에 쓰는 것은 범주 오류이며, 계약이 그 오용을 명시적으로 차단한다.

### 4.5 회귀 방지

`F_code/tests/test_timeseries_v13_vol.py:89-105` 가 좌표계를 직접 검사한다:

```python
def test_block_bootstrap_cov_is_symmetric_psd_and_in_frozen_coordinates() -> None:
    ...
    # 좌표계 검사: 재표집 적합이 전체 표본 (μ,σ) 로 고정 표준화되어야 동결 β·delta_method_se 와 같은 좌표다.
    # 피처를 10배 늘려도(σ 10배) 고정 표준화 β 의 공분산은 스케일 불변이어야 한다.
    cov_scaled = F.block_bootstrap_cov(X * 10.0, y, seed=1, b=40)
    assert np.allclose(cov, cov_scaled, rtol=1e-6, atol=1e-9)
    # 고정 표준화 인자가 실제로 쓰인다: standardize 를 주면 반환 μ/σ 가 그대로다
    mu, sd = F.standardize_params(X)
    beta_fixed, mu_out, sd_out = F.logit_fit(X[:100], y[:100], standardize=(mu, sd))
    assert np.array_equal(mu_out, mu) and np.array_equal(sd_out, sd)
    beta_own, mu_own, _ = F.logit_fit(X[:100], y[:100])
    assert not np.array_equal(mu_own, mu) and not np.allclose(beta_fixed, beta_own)
```

스케일 불변성 + 고정 인자 실제 사용 + 대조군(자기 표준화는 다른 β) 세 가지를 동시에 고정한다.

---

## 5. 표시 페일클로즈 — 숫자가 보이려면 무엇이 전부 성립해야 하는가

숫자는 두 시점에 각각 평가된다: **발행 시점**(라이브 CLI, `pipeline.py`)과
**빌드 시점**(표시 모듈, `timeseries_v13_vol_display.py`). 둘 다 통과해야 화면에 뜬다.
**마지막 값 캐시는 없다** (`timeseries_v13_vol_display.py:211`: "마지막 값 캐시 없음").

### 5.1 발행 시점 — `publish_latest_timeseries_v13_vol` (`pipeline.py:97-162`)

`reasons` 리스트가 하나라도 채워지면 `status = "hold"` 이고, hold 포인터에는 `cells`·`inputs` 가
아예 실리지 않으며 원장에도 쓰지 않는다.

| # | 조건 | 실패 시 reason | 줄 |
|---|---|---|---|
| 1 | **계약 무장** `gates.armed is True` | `gates_not_armed (V13-D4 pending)` | 107-108 |
| 2 | **계수 3중 핀** `load_frozen_coefficients` 성공 | `coefficients_not_pinned: …` | 110-115 |
| 3 | **설계 게이트 증거** 모든 셀 `gate_evidence.design_pass is True` **∧** `reconciliation.pass is True` | `design_gate_evidence_incomplete` | 116-120 |
| 4 | **거래일 신선도** `missing_sessions ≤ max_missing_sessions`(계약 기본 1) | `stale: missing_sessions=… > …` | 122-127 |

②의 "3중 핀"은 `contracts.py:94-121` 에서 **파일 sha256 · content_hash(기록값과 재계산값 둘 다) ·
finalist_id** 를 대조하는 것이다. 하나라도 어긋나면 raise.

④의 신선도는 달력 계약 기반이다 (`F_code/timeseries_v13/freshness.py`):

```
missing_sessions = #{ NYSE 거래일 d : as_of < d ≤ last_completed_session(now) }
last_completed_session(now) = 16:15 ET 이전이면 전일   (completed_market_cutoff)
fresh ⇔ missing_sessions ≤ max_missing_sessions
```

주말·연휴·장중을 정직하게 처리한다 — 테스트가 금/월, 목/월, 수/월, 노동절 다음 화요일,
토요일 01:30Z, 평일 장중 케이스를 전부 고정한다(`test_timeseries_v13_pipeline.py:165-183`).

### 5.2 빌드 시점 — `load_projection` → `build_projection` (`timeseries_v13_vol_display.py`)

먼저 `validate_latest` (45-92행)가 포인터 자체를 페일클로즈로 검증한다:

- `model_id` · `model_version` · `probability_space` · `probability_unit` 일치
- **`content_hash` 재계산 일치** (변조 탐지)
- `status ∈ {live, hold}`
- **`publication.customer_numbers_visible` 가 네 게이트의 AND 와 정확히 같아야 하고, `status == "live"` 와도 같아야 한다**
  (67, 69행: `"V13 visibility must equal all four gate decisions"`).
  네 게이트 = `GATE_KEYS = ("design_gate_pass", "armed", "coefficients_pinned", "freshness_pass")`
- `reference_opinion_only is True`
- `ISOLATION_KEYS`(공식 예측·시나리오 v5.2·V8 결합) 셋과 `trading_signal` 이 전부 `False`
- **hold 면 `cells`·`inputs` 가 있으면 안 된다**
- live 면 셀마다 `0 ≤ lo ≤ p ≤ hi ≤ 1`, `reliability ∈ {good, weak}`, `episode_sample ∈ {ok, thin, None}`,
  `model ∈ {ewma_logit, persistence_pb}`

그다음 `build_projection` (120-207행)이 순서대로 강등한다:

| 순서 | 조건 | 결과 상태 | reason |
|---|---|---|---|
| 0 | 포인터 파일 없음 | `absent` | `no committed pointer` |
| 0' | 포인터 JSON 파손 / 최상위가 dict 아님 / validate 실패 | `hold` | `pointer invalid: …` |
| 1 | 포인터가 `live` 아님 | `hold` | 포인터의 reasons 승계 |
| 2 | **빌드 시점 계약이 무장 해제** | `hold` | `contract_disarmed_at_build (gates.armed is not true)` |
| 3 | **`publication.holdout_status == "fail"`** | `hold` | `holdout_failed — 배선·표시 불가 (계약 wiring_eligibility)` |
| 4 | **계수 핀 3자 불일치**(계약 핀 == 포인터 기록 == **디스크 실제 sha256**) | `hold` | `coefficients_pin: …` |
| 5 | **빌드 시점 신선도 재평가** 실패(달력 계약 부재도 포함) | `hold` | `stale_at_build: …` |
| 6 | `display_tier == "t0_internal"` 인데 live | `internal` (숫자 제거) | `display_tier t0_internal — numbers stripped` |

계약 한 줄(`gates.armed` 또는 `publication.display_tier`)로 즉시 강등할 수 있다는 것이 설계 의도이며,
표시 tier 는 `("t0_internal", "t2_hidden_panel", "t3_live_card")` 셋뿐이고 계약 파일이 없으면
t0 로 페일클로즈한다(`contracts.py:72-79`). **자본 결정(T4) tier 는 값 자체가 존재하지 않는다.**

### 5.3 홀드아웃 실패 셀은 어떻게 제거되는가

**포인터에는 9셀이 전부 실린다** — 실측 확인: `E_artifacts/vol/vol_latest.json` 의 `cells` 는 9개
(`rv_h21, rv_h5, rv_h63, vix25_h21, vix25_h5, vix25_h63, vix30_h21, vix30_h5, vix30_h63`).
**제거는 표시 투영 단계에서 일어난다** (`timeseries_v13_vol_display.py:193-206`):

```python
if live:
    projection["inputs"] = dict(latest.get("inputs") or {})
    # 홀드아웃 부분 실패(partial) 셀은 숫자 대신 표시 불가 — PASS 셀만 싣는다 (계약 wiring_eligibility).
    projection["cells"] = {name: dict(latest["cells"][name]) for name in CELL_ORDER
                           if name in latest["cells"] and name not in holdout_fail_cells}
    if holdout_fail_cells:
        projection["holdout_fail_cells"] = [c for c in CELL_ORDER if c in holdout_fail_cells]
        projection["holdout_pass_cells"]  = [c for c in CELL_ORDER
                                             if c in (publication.get("holdout_pass_cells") or [])]
    if not projection["cells"]:
        projection.pop("cells"); projection.pop("inputs")
        projection["status"] = "hold"; projection["numbers_visible"] = False
        projection["display_state"] = "validation_pending"
        projection["gate"]["reasons"] = reasons + ["holdout_failed_all_cells"]
```

`holdout_fail_cells` 의 정본은 계약 `publication.holdout_fail_cells` 이며 현재 6셀
(`vix25_h5, vix25_h63, vix30_h5, vix30_h21, vix30_h63, rv_h63`). 즉 **화면에는 3셀만 남는다.**
전 셀이 실패하면 카드 전체가 hold 로 떨어진다.

**검토관이 유의할 비대칭**: 원 payload(`data.json` 의 `timeseries_v13_vol` 키 및 커밋 포인터)는
9셀을 계속 담는다. 화면 표시와 payload 는 같지 않다. 계약도 이를 공시한다
(V13-D4 `disclosure`: "T2 는 UI 수준 숨김이지 payload 비공개가 아니다").

### 5.4 숫자만 내리는 것으로는 부족하다 — 문장도 따라간다

`G_session_20260909/fixes.diff` 커밋 `6670ea7e` 가 그 결함을 고쳤다. 홀드아웃 실패로
`vix25_h63` 숫자를 내린 뒤에도 카드가 "등록 질문 vix-25-90d 의 base rate 공급원입니다"라고 계속
말하고 있었고, "읽는 법" 예시가 숨긴 셀을 인용해 화면에 `기준율 —` 이 찍혔다. 수정 후:

- 대응 셀이 `holdout_fail_cells` 에 있으면 역할 문구가 "**base rate를 공급하지 않습니다 · 이 질문에
  대입하지 않습니다**"로 바뀐다
- "읽는 법"은 **실제로 실린 셀**을 인용하고, 그 셀의 사건·지평에 맞춰 설명도 함께 바뀐다
- 커밋 `52d44563`: 모바일(≤620px)은 지평 한 칸만 보이므로 기본 지평을 "숫자가 있는 가장 긴 지평"
  (63 → 21 → 5)으로 바꿨다. 그 전에는 375px 화면에서 기본 탭 63 의 세 칸이 전부 `—` 였다

두 수정 모두 소스 문자열이 아니라 **node 로 렌더 결과를 실행해** 검사한다
(`F_code/tests/test_timeseries_v13_vol_role_honesty.py`, 7건).

### 5.5 라이브 배선(wiring) 자격은 더 좁다

홀드아웃 PASS 3셀 중 `vix25_h21` 은 **설계창 국면 가드 미달**(후반창 4국면)이라 배선 불가.
계약 `degeneracy_guard.consequences.wiring` — "episode_thin 셀은 홀드아웃 PASS 여도 V13-D6 배선 불가".
따라서 `publication.wiring_eligible_cells: [rv_h5, rv_h21]` (2셀).
그리고 등록 질문 43문항 중 9셀로 채점 가능한 것은 `vix-25-90d` 하나인데 대응 셀 `vix25_h63` 은
홀드아웃 실패 — 그래서 **V13-D6 배선은 열리지 않았다**
(`B_verdicts/V13_HOLDOUT_VERDICT_20260909.md` §4, 계약 `decisions_pending.V13-D6`).

---

## 6. 테스트가 무엇을 고정하는가

팩에 포함된 테스트는 12개 파일이다(`F_code/tests/`). 회귀 방지용으로 붙은 것을 **굵게** 표시한다.

### 6.1 `test_timeseries_v13_scoring.py` — 판정 기계 (9건)

- `block_boot_ci` 가 rung-1 참조 구현(`tools/v13_vol_run.block_boot_ci`)과 **평균·CI90·se·MDE 가 수치까지 일치**
- 쌍대 CI 의 부호와 양측 판정 — **유의 열위가 비열화(upper ≥ 0)를 통과하면 안 된다**
- y-block 순열이 **라벨 다중집합을 보존**하고 최소 한 번은 순서를 바꾼다
- Murphy 분해가 Brier 를 재구성(`abs=0.02`)하고 잘 보정된 표본의 rel < 0.05
- family P 경계값: `P(0|9)=1`, `P(9|9)=0.05⁹`, `0 < P(3|9) < 0.01`
- **`episode_runs` 는 일수가 아니라 국면을 센다** — 주석이 근거를 명시:
  "사건 100일이 한 덩어리면 국면은 1개다 — 이것이 설계창 vix30 계열의 실제 모양이었다".
  NaN 은 구간을 끊지 않는다
- **`degeneracy_report` 가 사건 수 통과 / 국면 실패를 분리**: 사건 100·비사건 100 이지만 국면 2 →
  `counts_ok=True, episodes_ok=False, verdict="episode_thin"`. 사건 3개 → `untestable_by_construction`
- `episode_spans` 의 구간 경계

### 6.2 `test_timeseries_v13_vol.py` — 수치 패리티·좌표계

- numpy 패키지 ↔ pandas 설계 러너 **완전 패리티**: 패널 날짜·VIX·NDX, rv21 의 NaN 위치가 정확히 21개,
  값 `atol=1e-10`, EWMA `rtol=0` 완전 일치, 9셀 라벨 `array_equal(equal_nan=True)`
- `logit_fit` 이 `tools._logit_fit` 과 `atol=1e-12` 일치, 조기 정지판이 같은 고정점에 수렴
- **EWMA 는 전체 이력에 연속 실행해야 한다** — 재시작(시드 x[200])이 연속 실행과 다름을 단언
- **rv NaN 채움은 동결 중앙값(0.1694207105468098)이지 재계산 중앙값이 아니다**
- 델타 대역이 [0,1] 안
- **`block_bootstrap_cov` 대칭·PSD·고정 좌표(스케일 불변)** ← §4.5 의 회귀 핀
- PAV 단조·클립, 피처 shape/이름, `cell_specs` 가 계약 `targets` 와 일치
- 동결 계수 3중 핀이 실제 저장소에서 성립 + finalist 를 바꾸면 raise

### 6.3 `test_timeseries_v13_holdout.py` — 비가역 자원 규율 (7건)

- 계약 개정 전 거부 / 승인 영수증 부재·미존재 거부 / 잘못된 결정·문구·범위·finalist 5종 거부 —
  **모두 `assert not _archive`(관측 미열람) 동반**
- finalist 당 1회 + 예산(3) 소진 거부
- 창 한정 채점 + **결과 무관 정확히 한 행 append** + 행 해시 검증 + 2회차 거부 + `verify_holdout ok`
- **소스 수준 금지 검사**: `logit_fit`·`block_bootstrap_cov`·`sealed_backtest`·`2019-01-01` 부재,
  **어떤 워크플로도 홀드아웃 verb 를 부르지 않음**
- **실제 저장소 원장 대사**: 창·`sealed_bytes_read`·승인 원문·finalist 일치,
  계약 `holdout_status`/`fail_cells`/`pass_cells` = 원장 마지막 행,
  **`wiring_eligible_cells == pass_cells − episode_thin_cells`**

### 6.4 `test_timeseries_v13_pipeline.py` — 발행 페일클로즈 (6건)

- 미무장 → hold 포인터에 숫자 없음, **원장에 쓰지 않음**
- live 포인터 9셀 + `0 ≤ lo ≤ p ≤ hi ≤ 1` + 신선도 fresh, **같은 as_of·계수 재실행은 멱등**
- **재동결은 충돌이 아니라 새 행** ← §4.3 의 회귀 핀
- verify 가 원장/포인터 셀 불일치와 해시 파손과 계수 핀 파손을 잡는다
- 낡은 아카이브 → hold, 신선도 헬퍼가 주말·연휴·장중을 처리

### 6.5 `test_timeseries_v13_vol_display.py` — 표시 페일클로즈 (13건)

포인터 부재(absent) / 해시 변조 / **가시성이 게이트를 앞지를 수 없음** / hold 는 셀을 숨겨야 함 /
대역 역순·모형 불법·격리 위반 raise / 디스크 계수 변조 / 빌드 시점 stale(주말 허용 포함) /
달력 계약 부재 / **빌드 시점 disarm** / **홀드아웃 fail → hold, partial → 셀 제거(9→7), 전 셀 실패 → hold** /
비-dict 포인터가 예외 대신 hold / t0 숫자 제거 / t3 굵은 caveat 플래그 / end-to-end live

### 6.6 `test_timeseries_v13_resolve.py` — 라이브 전진 채점 (6건)

기후는 **계약 고정값**에서만 / 미성숙 원점은 pending 이고 **원장 파일조차 만들지 않음** /
성숙 원점 9셀 1회 채점·라벨 실현·해시·멱등 / **성숙은 달력이 아니라 아카이브 거래일 인덱스로 판정**
(h5 만 성숙 → 3건) / 변조 탐지(해시·라벨 0/1) / 원장 등록 + verb 존재 + `live_forward_gate.execution_path`

### 6.7 `test_v13_vol_rung4_macro.py` — 지연 정렬 누수 (5건)

- `_align` 은 **과거로만** 전방 채움(첫 관측 이전은 NaN)
- 지연은 **엄격히 뒤로만** 민다
- **미래 급등이 지연 이전 칸에 새지 않는다** — 지연 10세션 뒤부터만 보인다
- 계약이 결과 전에 블록·PIT 등급·지연을 등록했고 PIT 증거 없는 계열은 보수 지연 필수
- 결과 artifact sha256 == 원장 행 `results_sha256`, **예산 회계(`evaluations_spent`) == 원장 행 수**

### 6.8 `test_timeseries_v13_vol_contract.py` — 계약 불변식 (15건)

- **사전등록 게이트 원문이 바이트 단위로 고정**: `gate.primary`·`bidirectional_transfer` 문자열,
  `uncertainty` dict(`{stationary_block, 13, 2000, 20260907, [5,95]}`), 귀무 임계 문장,
  표적 K/h/θ, split, 홀드아웃 창, 설계창
- 예산 대사 / 홀드아웃 프로토콜 finalist 한계 / 자명 기준선 규칙·신설 금지 3건 무장
- champion 상태가 rung-3 원장 행과 대사 / 표시 tier 가 무장·caveat 를 앞지를 수 없음
- 승인 영수증이 미래 시각이 아님 + 계약이 superseded 행을 가리키지 않음
- **가드가 실측 artifact 와 일치**하고 `provenance` 에 "소급"·"느슨"이 들어 있어야 함(사후 완화 방지)
- **`live_forward_gate` 가 어떤 원점도 성숙하기 전에 등록**됐고 채점 verb 가 스스로 강등하지 않음
- 원장 5종이 `ledger_registry.yaml` 에 등록

### 6.9 표시·운영 회귀

- `test_timeseries_v13_vol_panel.py` (5건): 패널 기본 숨김, X1 이름충돌 6항, 레일 tier 게이트,
  **`min-width:0` 로 63열이 화면 밖으로 밀리던 결함** 방지, CSS 배지·caveat 상시 노출
- `test_timeseries_v13_vol_role_honesty.py` (7건): §5.4 — **화면에 없는 셀을 문장이 가리키지 않는다**
- `test_investing_refresh_workflow.py`: **예약·연쇄 트리거로 도는 데이터 라이터는 전부 실패 감시 목록에
  있어야 한다** — `timeseries-v5-refresh` 가 2026-08-25 부터 12일, `timeseries-v13-vol-live` 가 사흘
  아무 신호 없이 실패한 사건의 회귀 방지
- `test_roadmap_status.py` (3건): 파생 상태 도구가 **읽은 체크아웃을 숫자보다 먼저 인쇄**하고
  아무것도 쓰지 않는다 — 낡은 워크트리 탓에 "라이브 원점 1"(실제 2)이 보고된 사건의 회귀 방지

---

## 7. 재현 — 각 판정 수치를 어느 명령이 만드는가

저장소 루트에서 실행한다(팩의 `F_code/tools/*` → `tools/*`, `F_code/timeseries_v13/*` →
`src/ai_fc/timeseries_v13/*`, `F_code/tests/*` → `src/tests/*`).

### 7.1 사다리(설계창) — 판정 원자료

| 산출 | 명령 | 결과 파일(팩 사본) |
|---|---|---|
| rung-1 EWMA vs 기후 + y-block 귀무 | `PYTHONUTF8=1 python tools/v13_vol_run.py` | `E_artifacts/vol/ladder_ewma_logit.json` |
| rung-2 HAR vs 기후 / vs EWMA 증분 + Murphy | `PYTHONUTF8=1 python tools/v13_vol_rung2.py` | `E_artifacts/vol/ladder_har_logit.json` |
| rung-3 PB 기준선·champion 확정·h63 isotonic | `PYTHONUTF8=1 python tools/v13_vol_rung3_pb.py` | `E_artifacts/vol/ladder_pb_baseline.json` |
| rung-4 매크로 블록 27검정 | `PYTHONUTF8=1 python tools/v13_vol_rung4_macro.py` | `E_artifacts/vol/ladder_rung4_macro.json` |
| P0 퇴화·국면 가드 + 셀별 MDE | `PYTHONUTF8=1 python tools/v13_guard_mde.py` | `E_artifacts/vol/guard_mde_design.json` |
| T-A 귀무 수리(3종 × 1000복제) | `PYTHONUTF8=1 python tools/v13_ta_null_repair.py --count 1000` | `E_artifacts/prereg/ta_null_repair.json` |

**주의 — 평가 예산 단회성.** rung-3·rung-4 러너는 원장에 같은 `experiment_label` 행이 이미 있으면
**재실행을 거부하고 exit 2** 를 낸다(`v13_vol_rung3_pb.py:202-205`, `v13_vol_rung4_macro.py:93-97`).
따라서 현 저장소 상태에서 그 두 산출물은 "재생성"되지 않는다 — 검토관은 JSON artifact 를 기록으로,
러너 소스를 감사 대상으로 다뤄야 한다. rung-1·rung-2·guard·TA 는 단회성 가드가 없어 재실행 가능하며,
전부 `seed = 20260907` 결정론이라 같은 수가 나와야 한다.

### 7.2 동결·라이브·홀드아웃

| 산출 | 명령 |
|---|---|
| champion 계수 동결(+ G0 대사 ≤1e-6, 계약 핀 자동 기입) | `PYTHONUTF8=1 python tools/v13_vol_freeze_coefficients.py` |
| 라이브 포인터 발행(fail-closed, 재적합 없음) | `cd src && python -m ai_fc timeseries-v13-vol-latest` |
| 라이브 전진 채점(성숙 원점만) | `cd src && python -m ai_fc timeseries-v13-vol-resolve` |
| 포인터·원장·핀·아카이브 재계산 대사 검증 | `cd src && python -m ai_fc timeseries-v13-vol-verify` |
| **홀드아웃(비가역, 1회)** | `cd src && python -m ai_fc timeseries-v13-vol-holdout --approval-receipt v13-approval:V13-D3:2026-09-09:r1` |
| 로드맵 상태(읽기 전용) | `PYTHONUTF8=1 python tools/roadmap_status.py` |

홀드아웃 명령은 **지금 실행하면 `already consumed` 로 거부된다**(`_require_budget`, `holdout.py:91-92`).
그것이 정상 동작이며, 검토관이 확인할 것은 "거부된다"는 사실 자체다.
`--approval-receipt` 를 생략하거나 가짜 id 를 주면 **데이터를 읽기 전에** 거부된다(§3.3).

### 7.3 테스트

```
cd src && python -m pytest \
  tests/test_timeseries_v13_scoring.py \
  tests/test_timeseries_v13_vol.py \
  tests/test_timeseries_v13_holdout.py \
  tests/test_timeseries_v13_pipeline.py \
  tests/test_timeseries_v13_resolve.py \
  tests/test_timeseries_v13_vol_display.py \
  tests/test_timeseries_v13_vol_contract.py \
  tests/test_timeseries_v13_vol_panel.py \
  tests/test_timeseries_v13_vol_role_honesty.py \
  tests/test_v13_vol_rung4_macro.py \
  tests/test_roadmap_status.py -q
```

(`test_timeseries_v13_vol_role_honesty.py` 는 `node` 가 필요하며 없으면 skip.
pytest 는 `src/` 에서 실행해야 한다.)

### 7.4 저장소 없이 — 팩만으로 검산할 수 있는 것

홀드아웃 판정의 **산술 자체**는 원장 JSON 만으로 재현된다. 셀별 G1/G2/G4 와 최종 상태·family P 가
서로 모순 없는지 확인하는 최소 스크립트:

```python
import json, math
d = json.load(open("E_artifacts/runs/holdout_V13VOL_champion_aec80c65038b.json", encoding="utf-8"))
scored = {k: v for k, v in d["cells"].items() if v["verdict"] != "untestable_by_construction"}
for name, c in scored.items():
    g1 = c["G1_vs_climatology"]["ci90"][0] > 0
    g2 = c["G2_not_inferior_to_pb"]["upper_ge_zero"]
    g4 = c["G4_negative_control_pass_rate"] <= 0.10
    assert (g1 and g2 and g4) == c["verdict"].startswith("pass"), name
    assert c["G1_pass"] == g1 and c["G2_pass"] == g2 and c["G4_pass"] == g4, name
k, n = len(d["pass_cells"]), len(scored)
fam = sum(math.comb(n, i) * 0.05**i * 0.95**(n - i) for i in range(k, n + 1))
print(k, n, fam, d["family_p_binomial"])     # 3 9 0.008361039546874999 (일치)
```

`E_artifacts/vol/guard_mde_design.json` 과 계약 `degeneracy_guard.design_window_result` 의 대조,
`ladder_rung4_macro.json` 의 `tests_run/k_obs_adopted/family_p_binomial` 과 원장 행 대조도
같은 방식으로 팩 안에서 닫힌다. 다만 **부트스트랩 CI 와 귀무 통과율의 재계산에는 시장 패널이
필요하므로 팩만으로는 불가능하다** — 그 부분은 저장소 접근이 있어야 한다.

---

## 8. 검토관이 알아야 할 열린 문제 — 정직 목록

이 절의 항목은 결함 주장이 아니라 **판정 기계를 평가할 때 보이지 않으면 안 되는 사실**이다.

**(a) 판정서와 원장의 신뢰도 수치 불일치.**
`B_verdicts/V13_HOLDOUT_VERDICT_20260909.md` §1 각주는 "통과 셀의 rel은 0.004~0.010으로 양호하고,
실패한 vix30_h63은 0.042로 가장 나쁘다"고 적었다. 원장 실측은 다르다 —
통과 셀 rel = `vix25_h21` 0.00396 · `rv_h5` 0.00992 · **`rv_h21` 0.03249**,
실패 셀 중 최악은 **`rv_h63` 0.09863**(vix30_h63 은 0.04176)이다
(`E_artifacts/runs/holdout_*.json` 의 `cells.*.reliability.reliability`).
G3 는 판정 다리가 아니므로 PASS/FAIL 은 영향받지 않지만, **원장이 정본이고 판정서 문장이 부정확하다.**

**(b) G4 내부 부트스트랩이 계약의 B=2000 이 아니다.**
`holdout.py:198` 은 `S.block_boot_ci(d, b=300)` — 순열 1회당 300 복제다(200 순열 × 300 = 60,000 재표집).
계약 `stopping_points.holdout.gate.G4` 는 내부 B 를 명시하지 않으므로 계약 위반은 아니지만,
G1 의 CI(B=2000)와 G4 의 CI(B=300)는 같은 정밀도가 아니다.
더 중요한 것은 `_decide` 가 `seed` 를 넘기지 않아 **200번의 순열 전부가 동일한 부트스트랩 인덱스
시퀀스**(seed 20260907)를 쓴다는 점이다. 공통난수(common random numbers) 설계로 볼 수 있으나,
통과율은 하나의 부트스트랩 실현에 조건부다.

**(c) 설계창 사다리의 귀무는 다른 부트스트랩을 쓴다.**
rung-1/3/4 의 귀무는 `_boot_lower_fast`(`tools/v13_vol_run.py:114-123`) — **고정 길이 13 블록**(기하분포가
아님), b = 400, CI90 하한만 반환하는 벡터화 근사다. 순열 수도 120(`neg_control`, `neg_control_increment`)이다.
코드는 이를 "경량 근사"로 명시하지만 계약 `gate.uncertainty`(정지 블록·B=2000)와는 다른 절차다.
본 판정(CI)은 계약대로 정지 블록·B=2000 을 쓴다 — 차이는 귀무 통과율 추정치에만 있다.

**(d) 설계창 귀무에 합성 라벨이 섞인다.**
`v13_vol_run.main:188` 과 `v13_vol_rung3_pb.main:242` 는 귀무에 `np.where(m, y, 0.0)` 를 넘긴다.
즉 라벨이 없는 원점(패널 끝 h 개)에 **인공 0** 이 들어간 뒤 블록 순열되어 평가 구간으로 이동할 수 있다.
h63 셀이면 2014 중 63개(약 3.1%)다. 홀드아웃 G4 에는 이 문제가 없다 — `yv = y[mask]` 만 순열한다
(`holdout.py:174, 200`).

**(e) 부트스트랩 블록 분할이 인덱스 0 에 고정.**
`y_block_permutations` 의 `starts = np.arange(0, n, block)` 는 매 draw 마다 같은 분할을 쓴다
(무작위 오프셋 없음). 블록 경계에 걸친 상관은 모든 draw 에서 동일하게 파괴된다.

**(f) 시드 하나를 전 셀·전 rung 이 공유한다.**
`BOOTSTRAP_SEED = 20260907` 하나로 9셀·4 rung 을 모두 돌린다. 재현성에는 유리하나 셀 간
부트스트랩 오차가 독립이 아니며, 이는 (i) 의 family P 독립 가정과 겹쳐 작용한다.

**(g) family P 의 독립 가정.**
9셀은 같은 VIX/RV 패널을 공유하고 h5 ⊂ h21 ⊂ h63 방향으로 사건이 포함관계에 가깝다(K25 vs K30 도
포섭 관계). `scoring.py:134` 주석이 "셀 독립 가정의 참고값" 이라 스스로 밝히고 계약도 "병기"로만
요구한다. **P = 0.0084 를 엄밀한 다중비교 통제로 읽으면 안 된다.**

**(h) 원장과 계약의 `wiring_eligible_cells` 가 다르다(의도된 것).**
원장 행은 3셀(`rv_h5, rv_h21, vix25_h21`), 계약은 2셀. 원장은 **홀드아웃 창 기준**으로 국면 가드를
계산했고(그 창에서 `vix25_h21` 국면 6), 계약은 **두 창 모두** 통과를 요구한다. append-only 원장은
고치지 않고 판정서 §3 이 그 차이를 설명한다 — 검토관은 계약·판정서를 정본으로 읽어야 한다.

**(i) rung-4 사전등록 커밋 해시가 두 가지로 인용된다.**
판정서는 `7a868424`, 산출물·원장은 `0ce8569b`. 계약 284행이 이유를 적었다 —
"병렬 세션의 브랜치 전환으로 원커밋 7a868424 를 clean 브랜치에 cherry-pick — 내용 동일".
**내용 동일성 자체는 이 팩 안에서 검증할 수 없다** `[미확인]`.

**(j) 적합기의 사소한 편향 두 가지.**
`logit_fit` 의 ridge `l2 = 1e-3` 은 **절편에도 적용**된다(`features.py:139`: `l2 * np.eye(…)`),
표준화 좌표에서 p 를 0.5 쪽으로 미세하게 당긴다. 또 `tol=None` 경로는 수렴 검사 없이 정확히
200회를 돌아 발산 가드가 없다. 둘 다 동결 artifact 의 `hyperparameters` 에 그대로 공시되어 있다.

**(k) 설계창의 구조적 한계(계약이 스스로 나열).**
`known_limits`: 설계창이 GFC(2008-09)를 포함해 early 반창이 위기이며 전이 검정이 "위기↔평온" 성격이 된다,
`θ_rv = 0.1694` 는 설계창 중앙값이라 in-sample 기준(사전등록으로 고정했으나 창 의존),
홀드아웃·봉인 미열람. `B_verdicts/V13_GUARD_MDE_20260909.md` §5 는 국면 가드를 통과한 셋
(`vix25_h5`·`rv_h5`·`rv_h21`)이 **공교롭게 전부 단기 지평**이며 이는 구조적 성질(지평이 길수록 라벨이
겹치고 국면이 줄어든다)이라고 밝힌다.

**(l) 이 트랙의 위치.**
CLAUDE.md 의 하드 게이트상 P3(해소 50문항 & Brier < 0.18) 통과 전이므로 모든 출력은 "참고 의견"이며,
`publication.reference_opinion_only: true` · `trading_signal: false` · 세 격리 키가 코드 수준에서 강제된다
(§5.2). 라이브 전진 표본은 셀당 성숙 원점 **0/60**(해상 원장 0행, `01_STATE/roadmap_status.txt`)이다.

---

## 부록 A — 홀드아웃 9셀 원자료 (팩 내 원장에서 그대로 옮김)

출처: `E_artifacts/runs/holdout_V13VOL_champion_aec80c65038b.json`.
`G2` 는 champion 이 PB 자신이라 9셀 전부 항등 통과(`{"identity": true, "upper_ge_zero": true}`).

| 셀 | 원점 | 사건/비사건 | 국면(최소) | BSS(기후) | G1 CI90 | G4 귀무 | Murphy rel | 판정 |
|---|---:|---|---:|---:|---|---:|---:|---|
| `rv_h5` | 1001 | 285/716 | 7 | +0.8279 | [+0.2051, +0.2495] | 0.000 | 0.00992 | **pass** |
| `rv_h21` | 985 | 354/631 | 5 | +0.5997 | [+0.1490, +0.2422] | 0.015 | 0.03249 | **pass** |
| `vix25_h21` | 985 | 169/816 | 6 | +0.4464 | [+0.0551, +0.1237] | 0.080 | 0.00396 | **pass** |
| `vix25_h5` | 1001 | 74/927 | 8 | +0.6395 | [+0.0683, +0.0880] | 0.125 | 0.00462 | fail (G4) |
| `rv_h63` | 943 | 492/451 | 4 | +0.2752 | [+0.0651, +0.1419] | 0.805 | 0.09863 | fail (G4) |
| `vix30_h21` | 985 | 57/928 | 3 | +0.3733 | [+0.0164, +0.0499] | 0.965 | 0.00741 | fail (G4) |
| `vix30_h5` | 1001 | 25/976 | 3 | +0.6147 | [+0.0259, +0.0326] | **1.000** | 0.00270 | fail (G4) |
| `vix25_h63` | 943 | 353/590 | 5 | +0.1452 | [−0.0390, +0.1182] | 0.000 | 0.03178 | fail (G1) |
| `vix30_h63` | 943 | 141/802 | 3 | +0.1619 | [−0.0239, +0.0813] | 0.485 | 0.04176 | fail (G1·G4) |

`untestable_by_construction` 셀: 없음. `episode_thin_pass_cells`: 없음(홀드아웃 창 기준).
`status: partial`, `family_p_binomial: 0.008361039546874999`.

## 부록 B — 사다리 4단의 결론 한 줄씩

| rung | 후보 | 기준선 | 결과 | 출처 |
|---|---|---|---|---|
| 1 | `ewma_logit` | 기후 | 9/9 채택(양방향 CI90 하한>0), y-block 귀무 0.000~0.0167 | `ladder_ewma_logit.json` |
| 2 | `har_logistic` (Corsi 1/5/22) | EWMA 증분 | **증분 0/9** — "스킬은 변동성 지속성 지배(richer 무익)" | `ladder_har_logit.json` |
| 3 | `ewma_logit` | `persistence_pb`(당일 수준 단독) | **EWMA 가 PB 를 이긴 셀 0/9** → G2 (b) 발동, champion = PB 전 9셀. PB 의 기후 대비 귀무 0.000~0.0333. h63 isotonic 은 fallback(raw) | `ladder_pb_baseline.json` |
| 4 | PB + 매크로 블록(F1 기간스프레드·F2 달러·F3 EBP) | PB | **채택 0/27**, family P = 1.0000. 귀무는 한 건도 실행되지 않음(CI 단계에서 전부 탈락) | `ladder_rung4_macro.json` |

세 번의 서로 다른 확장이 전부 "당일 수준 하나"를 이기지 못했다는 것이 이 트랙의 결론이다
(`B_verdicts/V13_VOL_RUNG4_MACRO_VERDICT_20260909.md` §3). 개발 예산 4/8 소모, 새 창 개방 0,
홀드아웃 슬롯 1/3 소모, 봉인 1/1 미사용.
