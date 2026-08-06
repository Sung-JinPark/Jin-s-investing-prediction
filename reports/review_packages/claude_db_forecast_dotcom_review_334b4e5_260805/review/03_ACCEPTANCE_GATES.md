# 독립 수용 게이트

## G0. 범위·재현성

| ID | 게이트 | 기대값 |
|---|---|---|
| G0-1 | commit range | `6a0ce0d..334b4e5` |
| G0-2 | 기능/생성물 커밋 분리 | `311b2ad`, `334b4e5` |
| G0-3 | 전체 테스트 | `380 passed` |
| G0-4 | inventory check | drift 없음 |
| G0-5 | ledger audit | `violation=0` |
| G0-6 | 정적 JS 문법 | `node --check` 성공 |

## G1. NASDAQ 구조 경로

| ID | 게이트 | 판정 조건 |
|---|---|---|
| G1-1 | additive | quantile table·fan·S1/S2/S3 prob를 변경하지 않음 |
| G1-2 | 결정성 | 같은 snapshot과 DB에서 같은 structural path |
| G1-3 | endpoint | 각 연도 segment 시작·끝이 기존 경로와 일치 |
| G1-4 | DB lineage | selected eras·correction median·source files 직렬화 |
| G1-5 | 2026 진폭 | S1 MDD가 약 -12.2%이며 target 12.19%와 정합 |
| G1-6 | 2027 범위 | 2027-08-04까지만 표시 |
| G1-7 | timing 언어 | 월 단위 위험창, 특정 저점일 주장 없음 |
| G1-8 | probability separation | physical-event `used_numerically=false` |
| G1-9 | AI regime gate | coverage<0.6이면 수치 입력 금지 |
| G1-10 | legacy | schema v2 archive도 validator 통과 |

## G2. 닷컴 교차자산

| ID | 게이트 | 판정 조건 |
|---|---|---|
| G2-1 | window | 2001-03..2006-03, 61개월 |
| G2-2 | anchor disclosure | 2000-03 정점과 2001-03 비교 시작 분리 |
| G2-3 | observed equality | 네 case의 NASDAQ/O 두 경로가 history와 정확히 동일 |
| G2-4 | BTC data gap | pre-2009 `not_available`, synthetic asset=Bitcoin only |
| G2-5 | formula | 월별 로그수익 복리 산식으로 snapshot에서 재현 가능 |
| G2-6 | cases | low/center/high/full 네 beta 규칙이 audit 필드와 일치 |
| G2-7 | band semantics | sensitivity envelope, probability/CI 아님 |
| G2-8 | O protection | current O sensitivity `used_numerically=false` |
| G2-9 | probability | schema v4 `reference_only`, weight `not_applicable` |
| G2-10 | append-only | r5 보존, r6은 `CORR-260805-015` 새 archive |

## G3. UI·접근성·공개 산출물

| ID | 게이트 | 판정 조건 |
|---|---|---|
| G3-1 | old narrative removal | 공개 HTML/data에 `AI 조정 후 완화·순환` 없음 |
| G3-2 | BTC style | 점선·반사실 라벨·data-gap banner |
| G3-3 | O visibility | O 가격과 O 총수익 proxy를 별도 계열로 표시 |
| G3-4 | case switch | Bitcoin만 변경, 실측선 유지 |
| G3-5 | annual table | 2001-03·…·2006-03 체크포인트 |
| G3-6 | keyboard | radiogroup과 화살표/Home/End 조작 유지 |
| G3-7 | public wording | 목표가격·사건확률로 읽히는 금지 문구 없음 |
| G3-8 | payload | `_site/data.json` 320KB 이하; 실측 298,623 bytes |

## G4. 데이터 수치 회귀

다음을 snapshot JSON에서 직접 재계산하라.

- NASDAQ: +27.1%
- O 가격: +82.7%
- O 총수익 proxy: +151.5%
- 2000-03 정점 기준 NASDAQ: -48.8%
- BTC cases 종점: 214.8 / 71.8 / 25.4 / 132.5
- 구조 경로 2026 S1/S2/S3 MDD: -12.2 / -16.0 / -20.4%
- 구조 경로 2027 S1/S2/S3 MDD: -7.8 / -8.0 / -8.0%

숫자가 다르면 보고서가 아니라 코드·JSON을 우선 근거로 삼고 FAIL 처리하라.

## G5. 실행 명령

Linux/macOS:

```bash
PYTHONPATH=src:dualdb python -m pytest -q
PYTHONPATH=src:dualdb python -m ai_fc inventory --check
PYTHONPATH=src:dualdb python -m ai_fc audit-ledgers --check
node --check src/ai_fc/dashboard_parts/dashboard.js
PYTHONPATH=src:dualdb python -m ai_fc dashboard --pages-out _site
```

Windows PowerShell:

```powershell
$env:PYTHONPATH='src;dualdb'
python -m pytest -q
python -m ai_fc inventory --check
python -m ai_fc audit-ledgers --check
node --check src/ai_fc/dashboard_parts/dashboard.js
python -m ai_fc dashboard --pages-out _site
```

