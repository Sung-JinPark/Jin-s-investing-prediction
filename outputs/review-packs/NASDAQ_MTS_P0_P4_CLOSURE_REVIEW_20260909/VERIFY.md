# 검증 명령 — 검토관용 3단계

이 팩은 **팩만으로 닫히도록** 만들었다. 아래 세 단계는 저장소 없이 실행된다.

## 1. 팩 무결성 (전수)

```bash
cd NASDAQ_MTS_P0_P4_CLOSURE_REVIEW_20260909
sha256sum -c MANIFEST.sha256
```

zip 자체의 해시는 동봉된 `.sha256` 파일과 대조한다.

```bash
sha256sum NASDAQ_MTS_P0_P4_CLOSURE_REVIEW_20260909.zip
cat NASDAQ_MTS_P0_P4_CLOSURE_REVIEW_20260909.zip.sha256
```

## 2. 원장 ↔ 산출물 해시 사슬

```bash
sha256sum E_artifacts/vol/ladder_rung4_macro.json
python -c "import json;print([r['results_sha256'] for r in map(json.loads,open('E_artifacts/ledgers/vol_experiments.jsonl',encoding='utf-8')) if r['experiment_label']=='V13VOL_rung4_macro'])"
```

두 값이 같아야 한다. `champion_coefficients.json` 도 같은 방식으로 홀드아웃 원장의
`coefficients_sha256`·계약 `frozen_coefficients.sha256` 와 대조된다.

## 3. 판정 산술 재계산

```bash
python - <<'PY'
import json, math
h = json.load(open('E_artifacts/runs/holdout_V13VOL_champion_aec80c65038b.json', encoding='utf-8'))
k = sum(1 for c in h['cells'].values() if c['verdict'] == 'pass')
n = len(h['cells'])
p = sum(math.comb(n, i) * .05**i * .95**(n-i) for i in range(k, n+1))
print(f'k={k} n={n} family P={p:.10f}')
print('원장값       =', h['family_p_binomial'])
PY
```

`k=3 n=9 family P=0.0083610395` 가 나와야 하고 원장값과 일치해야 한다.

**단, 이 검정은 셀 독립을 가정한다.** 측정된 종속 아래에서는 같은 결과의 P 가 0.0415 다 —
`E_artifacts/diagnostics/family_null_under_dependence.json` 및 검토 질문 Q13 참조.
