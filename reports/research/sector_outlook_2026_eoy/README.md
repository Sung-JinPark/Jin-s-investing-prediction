# 2026년 연말 섹터 연구 묶음

이 폴더는 **2026-10-12 09:16:14 KST**를 기준으로 작성한 별도 연구 산출물이다. 공식 예측·모델·원장·DB·사이트를 변경하거나 결과를 승격하지 않았다. 핵심 판단은 AI 반도체·전력 장비·AI 수익화 플랫폼의 공동 우선군이며, 숫자 수익은 명시적 가정에 대한 what-if다.

## 읽는 순서

1. [종합 보고서](report.md): 결론, 미국 11개 섹터, 내부 성과, 거시·기업 원문, 한국 비교, 시나리오·반증 조건.
2. [수익률 가정 그림](scenario_comparison.png): 중심값·가정 범위·상승/기준/하락 결과. [SVG 원본](scenario_comparison.svg)도 제공한다.
3. [가정](assumptions.json) → [계산 결과](scenario_results.json) → [검증](validation.json): 숫자의 역할과 한계를 먼저 확인한다.
4. [독립 검토 메모](review_notes.md), [최종 검증 기록](validation.md): 단위·관측일·공개일·회계·예측 검증의 한계와 실행 명령.
5. [미국 기술 심층 메모](notes_us_tech.md), [한국 심층 메모](notes_korea.md): 보조 분석과 세부 공백.

PDF나 별도 요약 파일이 추가되면 동일 보고서의 표시 산출물로 보며, 계산의 원본은 아래 JSON·CSV다.

## 데이터·계산 파일

| 파일 | 역할 |
|---|---|
| [sector_comparison.csv](sector_comparison.csv) | 미국 11개 섹터·SPY의 10/9 종가, 10/8 FY1 P/E, 9/30 NAV 성과·이익 전망과 반증 조건 |
| [sector_research_matrix.csv](sector_research_matrix.csv), [JSON](sector_research_matrix.json) | 같은 7개 연구 항목과 반증·신뢰도·공백·출처를 12개 비교 대상에 적용한 상세 행렬 |
| [theme_comparison.csv](theme_comparison.csv) | 반도체·소프트웨어·보안·클라우드·전력 ETF의 실제 노출, 정의가 붙은 배수·집중도 |
| [scenario_calculations.csv](scenario_calculations.csv) | 이익 기준·배수 변화, 배당·보수, 각 가정 수익을 재현하는 계산표 |
| [sensitivity.csv](sensitivity.csv) | 16개 선택 가중치 조합. 최고값 횟수는 승률이 아님 |
| [driver_sensitivity.csv](driver_sensitivity.csv) | 이익 ±2%p, 배수 ±3%p, 무배당 민감도 |
| [assumptions.json](assumptions.json) | 0.30/0.45/0.25 가중치와 자산별 g·m·범위·배당·비용 가정 |
| [scenario_results.json](scenario_results.json) | USD 기준 가정 중심값·범위·SPY 차이·환율 산술 예시 |
| [closing_quotes.json](closing_quotes.json) | 10/9 정규장 종가 관측과 전일 issuer 대조. 게시시각은 미확인 |
| [issuer_observations.json](issuer_observations.json) | State Street 12개 ETF의 보존 관측·HTML 해시·정의 |

저장 확률·가중치·수익·성장률은 명시된 fraction 단위를 사용하며 보고서에서만 퍼센트로 변환한다. 각 증거의 원문 숫자 단위는 원래 정의를 함께 유지한다. null은 미확보·정의 미확정이며 0으로 대체하지 않는다.

## 근거와 보존 원문

- [source_manifest.json](source_manifest.json): 85개 **출처 역할 ID**와 URL·관측일·발표일·수집일·제한. 독립 기관/리포트 85개를 뜻하지 않는다.
- [evidence_us_macro_sectors.json](evidence_us_macro_sectors.json): Fed·BLS·기관 전망·11개 섹터의 Q3 EPS와 2027 수정 통계.
- [evidence_us_tech.json](evidence_us_tech.json): 기업 IR·SEC·ETF issuer와 기술·AI 인프라 논리.
- [evidence_korea.json](evidence_korea.json): 한국 기업·증권사 원문·ETF·환율·가격 공백.
- [한국 시세 추가 대조](korea_price_crosscheck.md), [후보 JSON](korea_price_crosscheck.json): 종가 후보의 시장·세션 정의 차이와 채택 보류 기록. 계산 입력 85개 ID의 범위 밖이다.
- [internal_audit.json](internal_audit.json): DB 읽기 전용 감사, 공개 성과 재현, 모델·경로·vintage 경계, 원본 242개 해시.
- [public_snapshot/data.json](public_snapshot/data.json), [statistics.json](public_snapshot/statistics.json), [future_paths.json](public_snapshot/future_paths.json): 수집해 해시를 보존한 공개 read-model 원문.
- [source_pdfs](source_pdfs): 보존 가능한 기관 원문 PDF. 임시경로에서 검토한 모든 원문이 이 폴더에 저장된 것은 아니다.

발표일이 있는 자료와 `publication_time_unverified_reference_only` 자료를 구분한다. 동적 ETF·가격 페이지, 일부 전망 장표, 컷오프 후 수집한 공개 사이트는 정확한 과거 게시·수정 vintage를 인증하지 못한다. 해당 자료를 공식 forecast 입력이나 과거 원점의 실행 가능한 신호로 설명하지 않는다.

## 오프라인 재현

번들 런타임 조회는 사용할 모듈을 제공하지 못했으나 기존 로컬 Python·matplotlib으로 계산·차트 생성을 완료했다. 의존성 설치·업그레이드는 하지 않았다. 다음 명령은 이 연구 폴더에서 실행한다.

```powershell
python -m unittest test_calculations -v
python calculations.py --output-dir replay
python export_sector_research_matrix.py
python render_chart.py
```

- [calculations.py](calculations.py)는 보존 입력에서 표·가정 산술·manifest·validation을 다시 계산한다. `--output-dir replay`는 기존 결과를 보존하고 연구 폴더 안의 별도 하위 폴더에 재생 결과를 쓴다. 네트워크를 사용하지 않으며 보호 원본 해시가 바뀌면 중단한다. 원본 보존 검사에 기존 저장소가 필요하므로 연구 폴더만 다른 위치에 복사해 실행하는 방식은 지원하지 않는다.
- [render_chart.py](render_chart.py)는 계산 결과를 PNG·SVG로 표시한다. 기존 matplotlib과 한글 폰트를 사용하며 추가 설치를 하지 않는다.
- [export_sector_research_matrix.py](export_sector_research_matrix.py)는 보존 입력에서 11개 섹터·SPY의 상세 행렬만 재생한다. 미확보 항목은 null이며 정성 해석·조건부 촉매의 연구 역할을 표시한다.
- [test_calculations.py](test_calculations.py)는 단위·가중치·누락·범위·분할·환율의 의미 있는 산술 검증이다. 실제 원장·DB를 수정하지 않는다.
- [audit_internal.py](audit_internal.py)를 `--offline`으로 실행하면 보존한 공개 JSON을 재생하고 현재 로컬 DB는 읽기 전용으로 검사한다. 원래 감사 시점 이후 DB가 바뀌면 같은 vintage의 완전 재현을 보장하지 않는다.
- [collect_issuer_pages.py](collect_issuer_pages.py)는 외부 issuer 페이지를 새로 수집한다. **과거 연구 재현에 다시 실행하지 않는다.** 이후 날짜 페이지로 기존 참고값을 교체하면 10/12 연구와 다른 자료가 된다.

새 산술 검사 15개와 분리한 기존 안전 validator 36개, 총 51개가 통과했다. 레포 전체 기본 테스트는 일부 DB 연결 경로에서 ALTER/UPDATE·실제 마이그레이션을 수행할 수 있어 실행 범위를 분리했다. 안전한 검증 결과와 환경·자료 공백은 최종 검증 문서에 기록한다.

## 해석할 때 지킬 경계

- SOXX·GRID·XLC의 약 4~5%는 고른 가정의 가중 산술 결과다. 검증된 시장 기대수익·승률·목표가가 아니다.
- 이익·배수·배당 범위는 신뢰구간·손실 제한이 아니다. 순위는 가중치·배수·무배당 변경으로 바뀐다.
- GRID는 글로벌 주식, XLC는 통신서비스 전체의 대용치다. 기존 기술·시장 ETF와 AI 노출이 겹칠 수 있다.
- 배당은 미확정 대용치이며, 세금·환전·스프레드·매매비용은 수익 계산에 포함하지 않았다.
- 미국 10/9 가격, issuer 10/8 가치, 9/30 NAV 성과·전망의 날짜를 분리한다. 한국 최신 종목 가격·현재 ETF holdings·정상화 이익 공백 때문에 한국 숫자 수익률은 보류했다.
- SOXX 미래 3:1 분할과 LS의 과거 5:1 분할은 경제적 수익과 주당 표시 단위를 구분한다.
- 내부 실적 사건 Brier와 시장 일간 방향·섹터 연말 수익 예측력은 별도의 검증 문제다. V8·V13·구조경로 확률을 이 연구의 가정 가중치로 옮기지 않았다.
