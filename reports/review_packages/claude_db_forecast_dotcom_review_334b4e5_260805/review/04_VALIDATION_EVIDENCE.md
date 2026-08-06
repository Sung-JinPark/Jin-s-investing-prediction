# 검증 증거

## 1. 로컬 검증

| 검사 | 결과 |
|---|---|
| 전체 pytest | `380 passed in 123.74s` |
| 관련 회귀 묶음 | `52 passed` |
| `node --check dashboard.js` | 성공 |
| `inventory --check` | current |
| ledger audit | accumulating 22 · stalled 6 · inactive 0 · **violation 0** · planned 3 |
| 정적 Pages 빌드 | 성공 |
| `_site/data.json` | 298,623 bytes |
| forbidden public scan | 구형 완화 시나리오·구형 5년 제목·금지 가격표현 미검출 |

`sync --check`에서 과거 market benchmark 두 행이 canonical fraction 범위를 벗어나
quarantine되었다는 기존 경고가 있었으나 이번 두 기능의 입력이나 CI 실패는 아니다.

## 2. GitHub Actions

### 최종 verify

- run: https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/runs/30995504543
- HEAD: `334b4e54bbe11ced37404415f5e9326996376cb5`
- 결론: success
- 성공 단계:
  - unit tests
  - immutability drift check
  - generated inventory drift check
  - registered ledger integrity check
  - official provider approval guard
  - secret pattern scan
  - track record verifier

### Pages

- run: https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/runs/30995376880
- 기능 HEAD: `311b2ad7004688677dc240058f1d0756fdce0762`
- build: success
- deploy: success
- live: https://sung-jinpark.github.io/Jin-s-investing-prediction/

후속 `334b4e5`는 generated docs만 수정해 Pages path filter에 의해 재배포되지 않았으며,
라이브 제품 코드는 이미 `311b2ad`를 포함한다.

## 3. 라이브 스팟체크

`data.json`에서 확인한 값:

```text
snapshot_id = cross-asset:2026-08-03:r6
schema_version = 4
probability_space = reference_only
history.period = 2001-03 to 2006-03
forecast.default_scenario = btc_regime_center
```

## 4. CI 후속 수정 기록

첫 기능 push `311b2ad`의 verify는 `generated inventory drift check` 한 단계에서 실패했다.
원인은 새 correction 2행과 contract 2개, read-model enum을 반영한 생성 inventory/schema를
커밋하지 않았기 때문이다. `ai_fc inventory`로 두 생성물을 갱신해 `334b4e5`로 추가 push했고,
최종 verify는 전 단계 green이다. history rewrite나 force-push는 하지 않았다.

## 5. 패키지 자체 검증

- `patches/`에는 두 커밋의 `git format-patch` 원본이 있다.
- `files/`에는 `6a0ce0d..334b4e5`의 변경 파일 전체가 현재 HEAD 내용으로 들어 있다.
- `MANIFEST_SHA256.txt`에서 ZIP 내부 파일의 SHA-256을 대조할 수 있다.
- ZIP 생성 뒤 별도 hash를 최종 사용자에게 제공한다.

