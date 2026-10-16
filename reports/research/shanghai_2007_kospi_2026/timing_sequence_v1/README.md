# 실적과 주가 하락의 선후관계 연구

한국 기준 시점은 2026-10-16 09:00 KST, 종가 관측 종료는 2026-10-15다. 기존 달력·국면 연구를 보존한 별도 확장 결과다.

- `report.md`, `report.html`: 한국어 분석, 중국 공개정보 타임라인과 한국 신호 비교. HTML은 오프라인 열람 가능.
- `price_chronology.csv/json`: 기존 정본을 읽어 계산한 22개 사건 주변 종가·고점 대비 변화·경과 거래일. 미래 앵커를 참조한 사후 값은 별도 표시.
- `china_earnings/`: 당시 간행물·회사/거래소/정부 발표와 이익 전망 변화. 성장률 전망과 EPS 수준을 구분.
- `china_liquidity/`: 인민은행 정책 발표·시행일, 증감위 월보 원본 XLS와 거래일 보정 활동 지표. 개인 순매수·고유 투자자 수를 추정하지 않음.
- `korea/`: 29개 관측·11개 신호, 정책·급락일 매수·차입 축소와 현재 EPS 패널의 한계.
- `context/`: BIS·연준 당시 자료. PDF URL이 HTML로 이동한 응답과 IMF 조회 실패도 보존하며 사용 범위를 분리.
- 각 영역의 `source_manifest.json`, `evidence.json`, `independent_review.json`: 원문·해시·시점·판정과 세 검토자의 확인. 외부 감사나 미열람 예측 검증은 아님.
- `original_study_before.json`, `validation.json`: 이전 연구·보호된 시스템의 변경 여부, 출처 해시와 독립 산술 확인.
- `visual_qa.json`, `qa/`: 1440·768·390px 오프라인 브라우저 검사와 화면.

## 재현

이미 설치된 Python 3.12와 pandas·markdown·playwright·xlrd를 사용했다. 추가 설치는 하지 않았다. 다음은 보관 자료만 사용하며 운영 시스템이나 원장을 쓰지 않는다.

```powershell
$researchPython = 'C:/Users/91ssj/AppData/Local/Programs/Python/Python312/python.exe'
& $researchPython -X utf8 render_report.py
& $researchPython -X utf8 visual_qa.py
& $researchPython -X utf8 validate_timing.py
```

`prepare_context.py`는 최초 수집·기존 수집 기록 재사용 및 가격 표 생성용이다. 이미 있는 원문으로 결과를 읽는 데 다시 실행할 필요가 없다. `china_liquidity/build_evidence.py`는 보존 XLS를 읽는 독립 재현 스크립트다. 간행물의 PDF·텍스트를 증거 추적용으로 보관했다.

## 판단의 한계

같은 제공자·동일 표본·고정 전망연도의 상해종합/코스피 EPS 수정 패널은 미확보다. 공개된 일부 전망의 하향이 최초 하향 시점 또는 시장 전체 하향 폭을 뜻하지 않는다. 성장 예상 31.6%→25.3%는 -6.3%p이며 EPS 수준의 -6.3%로 대체하지 않는다.

중국 월보의 거래대금은 양시장 모든 투자자, 한국 7.3→3.5조원은 코스피 -5% 이상 급락일 개인 순매수의 조건부 평균이다. 두 지표를 같은 개인 자금 유출로 합치지 않는다. 월보 원문의 일평균과 월누계÷거래일 사이 작은 산술 차이는 두 값을 그대로 보존했으며 수정하지 않았다.

원공개일과 현재 회고 수집 시각을 구분했다. 원발표 당시 보관본의 빈티지를 완전히 인증한 공식 모델 입력이 아니다. 정책·이익 기대·가격·참여의 인과효과나 붕괴 확률을 산출하지 않았다. 기존 전망·확률·원장·모델·공개 API는 변경하지 않는다.
