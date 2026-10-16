# 2007년 상해와 2026년 코스피 비교 연구

2026년 10월 16일 오전 9시 KST, 직전 완료 거래일인 10월 15일을 기준으로 한 별도 연구다.

[보고서 HTML](report.html)은 그림을 포함한 단일 파일로 열 수 있다. [Markdown 보고서](report.md), [핵심 비교 그림](charts/fixed_calendar_comparison.png), [검증 기록](validation.json)도 제공한다.

주요 결과는 공통 상승 구조의 부분적 유사성과 가격 경로 예측 근거의 부족이다. 고정한 19년 달력 정렬의 주간 수익률 Pearson은 0.00089이며, 코스피는 종가 고점 대비 이미 39.06% 하락했다. 정부의 국내투자 유도 정책이 개인 열풍의 주원인이라는 인과효과와 글로벌 이익성장률 1위는 미확인이다. 숫자의 기간과 정의는 본문을 참조한다.

## 파일 구성

- `report.html`, `report.md`: 판정표, 이익·정책·개인 수급, 고점·하락 비교, 126·252거래일 위험 조건.
- `prices/`: 정본 7,287행과 계산, 공식 중국 가격에 대한 전수 교차검증, 원자료와 한계.
- `china/`, `korea/`, `context/`: 출처·공개일·단위·빈티지·접근 상태를 갖춘 증거와 보존 원문.
- `source_catalog.json`: 하위 manifest를 묶은 인덱스. 저장 응답 수에는 오류·challenge·부분 응답이 포함될 수 있으며 유효 출처 수와 다르다.
- `supporting_analysis.json`, `policy_windows.csv`, `valuation_sensitivity.csv`: 정책 전후 20개 수익률, 조건부 역사 진단, 가정 산술.
- `charts/`: 4개 PNG와 편집 가능한 SVG.
- `validation.json`, `test_results.txt`, `independent_review.json`, `visual_qa.json`, `qa/`: 계산·단위·원문 해시·원본 보호·독립 검토·화면 검증.

## 오프라인 재현

이 폴더에서 기존 Python 환경으로 다음 순서로 실행한다. `consolidate.py --offline`은 보존 원문을 재사용하며 새 네트워크 수집을 하지 않는다.

```powershell
python -X utf8 prices/consolidate.py --offline
python -X utf8 prices/analytics.py
python -X utf8 build_supporting_analysis.py
python -X utf8 render_charts.py
python -X utf8 build_report.py
python -X utf8 -m unittest discover -p 'test_*.py' -v
python -X utf8 visual_qa.py
python -X utf8 validate_research.py
```

수집용 스크립트는 나중의 수정 자료로 이 연구를 바꿀 수 있으므로 재현에 실행하지 않는다. 원문 발표 시점과 실제 조회 시점은 다르고, 원래 게시 빈티지 전체를 인증하지 못한 자료는 당시 실행 가능한 예측 입력으로 간주하지 않는다.

MSCI World의 같은 날짜 공개 값이 서로 달라 세계 대비 수익은 미산출이다. 상해 2008년 하락과 같은 낙폭 진단은 사후 단일 사례이며 한국 미래 예측·확률이 아니다. EPS·PER 민감도는 설명용 산술이다. 원장·공식 전망·기존 모델·사이트·API·DB를 변경하지 않았다.
