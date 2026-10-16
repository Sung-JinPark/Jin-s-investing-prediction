# 반도체 vs 소프트웨어 — 2026년 연말 상대강세 연구

미국 SOXX와 IGV를 2026-10-09 확정 종가부터 2026-12-31까지 비교한다. 남은 지평은 83일·57거래일이며 연구 기준시각은 2026-10-12 10:38:50 KST다. 이전 섹터 연구는 보존하고 별도 분석으로 계산했다.

## 결과를 읽는 순서

1. [HTML 보고서](report.html): 사업·가격·시황·수학·머신러닝을 한 화면에서 비교한다. 인터넷 연결 없이 읽고 가정을 바꿀 수 있다.
2. [실제 머신러닝 계산](quantitative_ml.json), [입력·시점 감사](data_inventory.json): 실제 훈련/평가 결과와 채택 보류 이유.
3. [수학 계산 결과](analytical_results.json), [가정 원본](analysis_assumptions.json), [시나리오 CSV](pair_scenarios.csv): 수익 격차·소프트웨어 역전 경계·분포 가정 민감도.
4. [공시·기관 근거](relative_evidence.json), [심층 해석](interpretation.md): 회계기간·현금 정의·시황·반증 조건.
5. [독립 계산 감사](independent_qa.json), [독립 연구 검토](research_review.json), [최종 검증 기록](validation_summary.json): 저장 CSV의 label·Brier·MAE·purge 경계·원본 보존, HTML 동작과 파일 해시 확인 기록.

사업 실적과 수요의 가시성은 반도체를 먼저 검토할 근거다. 실제 최근 57거래일 가격은 소프트웨어가 더 강했다. 훈련한 Ridge·Logistic·Random Forest는 검증 구간에서 단순 기준모형보다 오차가 컸다. 따라서 검증된 연말 승자 확률은 제시하지 않는다.

## 실제 계산과 가정의 구분

- **관측:** SOXX·IGV·SPY 2008-01-02~2026-10-09 각 4,723개의 공개 조정가격, 과거 수익·변동성·시장 beta, 기업 발표와 기관 전망. 원문 HTML과 SHA-256을 보존했다.
- **사후 머신러닝 평가:** 12개 가격 특징, 21·57거래일 label, 5년 초기 학습, 63거래일마다 확대 학습, train label 종료가 test 시작보다 앞서는 1세션 purge, 학습 구간에서만 scaling. 하이퍼파라미터는 이번 실행 전에 고정했으며 역사적 결과를 보기 전 사전 등록한 것은 아니다.
- **검증 표본:** h57 일별 원점 3,280개는 label이 겹친다. 별도 비중첩 원점은 58개지만 완전한 통계적 독립을 보장하지 않는다. 지평 크기의 이동 블록 bootstrap으로 기준모형 대비 오차 차이를 검토했다. 시장 국면 변화와 연구 선택의 불확실성이 모두 해결된 것은 아니다.
- **연구 가정:** 이전 연구의 이익능력·배수 변화·배당·보수와 상승/기준/하락 가중치를 그대로 대조했다. 삼각분포·가우시안 copula의 20만 회 시뮬레이션은 이 가정 분포의 계산이다. 그 안의 우위 빈도와 정밀한 시뮬레이션 오차를 시장 승률·예측 신뢰도로 읽지 않는다.
- **시황:** 기업·Fed·BLS 원문은 별도 해석에 반영했다. 현재 발표 수치를 역사적 모델 feature에 소급 삽입하지 않았다. 훈련 모델은 가격 특징만 사용한다.

가격 원문의 과거 전달 시각·수정 vintage를 확보하지 못했고 수집은 연구 컷오프 이후였다. 관측 날짜가 붙은 사후 연구로 사용했으며 엄격한 prospective gate는 blocked다. 현재 모델 출력이 소프트웨어를 선호하더라도 성능·vintage 게이트를 통과하지 못했으므로 공식 확률로 채택하지 않았다.

## 재현

기존 설치된 Python·NumPy·SciPy·pandas·scikit-learn·exchange-calendars·Playwright와 Edge를 사용했다. 의존성 설치·업그레이드는 없다. 다음은 저장소 루트에서 실행한다.

```powershell
python -B -X utf8 -m unittest discover -s reports/research/semiconductor_vs_software_2026_eoy -p "test_*.py" -v
python -B -X utf8 reports/research/semiconductor_vs_software_2026_eoy/build_analytics.py
python -B -X utf8 reports/research/semiconductor_vs_software_2026_eoy/relative_ml.py
python -B -X utf8 reports/research/semiconductor_vs_software_2026_eoy/validate_research.py
python -B -X utf8 reports/research/semiconductor_vs_software_2026_eoy/build_html.py
python -B -X utf8 reports/research/semiconductor_vs_software_2026_eoy/validate_html.py
python -B -X utf8 reports/research/semiconductor_vs_software_2026_eoy/finalize_validation.py
```

`build_analytics.py --initialize`는 최초 스냅샷 작성용이며 기존 가정이 있으면 대체를 거부한다. 재현에는 `--initialize`를 사용하지 않는다. 가격 수집기 `collect_price_history.py`도 과거 연구 재생 때 실행하지 않는다. 원문 수집과 기존 원문으로 계산을 재생하는 과정을 구분한다.

수익 차이는 `R_SOXX−R_IGV`이며 HTML에서 %p로 표시한다. 머신러닝 label은 로그 총수익 비율 차이다. `expm1(label)`은 총수익 비율−1이고 %p 수익 차이와 다르다. 과거 조정가격 수익에 배당·연 보수를 다시 더하거나 차감하지 않는다. 미래 배당은 확정액이 아닌 연구 가정이다.

SOXX의 예정 11월 3:1 분할은 미래 기업행동이다. 역사 파일에는 2024년 시행된 분할만 있고 11월 예정 분할을 미래 수익이나 가격 손실로 넣지 않았다. 공식 예측·원장·사이트·기존 모델 수정은 0건이다.

최종 신규 연구 테스트 23개, 독립 산술 확인 48개, HTML 브라우저 확인 16개가 통과했다. 별도 연구 검토 95개 항목에서도 중대한 오류가 없었다. 이 확인 횟수는 예측 성공 횟수·독립 시장 표본 수가 아니다. 실제 DB를 변경할 수 있는 저장소 전체 기본 테스트 대신 이 연구 범위의 전체 검사와 읽기 전용 원본 보존 감사를 실행했다.
