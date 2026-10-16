# 상해–코스피 국면 비교 확장 연구

기준: 2026-10-16 09:00 KST. 한국 가격의 최종 관측일: 2026-10-15.
이 디렉터리는 상위의 달력 정렬 연구를 보존한 별도 결과다. 공식 전망·확률·원장·모델·API에 쓰지 않는다.

- `report.md`, `report.html`: 한국어 분석과 조건표. HTML은 그림을 내장하며 오프라인 열람 가능.
- `charts/`: 상승 시작·전체 중간 조정·관측 고점 정렬 및 사건별 모양 비교. 한국 미래 경로는 없음.
- `prices/`: 10·15·20% 전환 확인, 전체 후보와 개별 지표 비교, 상해 A주 민감도, 2009년 사후 결과 확장 원문.
- `fundamentals/`: 공개 원문·수집 시각·출처 해시·46개 관측과 7개 관찰 조건. 숫자 문턱은 미검증 연구 가정.
- `phase_support.json`, `current_levels.csv`: 가격 기준점, 현재 확인 일수, 126거래일 대조 사례, EPS/PER 산술.
- `review/`: 별도 재계산, 전환 확인 전 정보 사용 방지 및 반등 쌍 시간순서 검사.
- 각 영역의 `independent_review_parent.json`: 세 검토자의 보고서·계산 검토. 외부 감사나 미열람 예측 검증을 뜻하지 않음.
- `validation.json`, `test_results.txt`, `visual_qa.json`, `qa/`: 최종 검증과 화면 확인.
- `original_study_before.json`: 이번 작업 전 상위 연구 파일 해시. 상위 연구와 보호된 기존 시스템 파일의 변경 여부를 검증한다.

## 재현

추가 패키지 설치는 하지 않는다. 이 환경의 Python 3.12와 이미 설치된 numpy·pandas·scipy·matplotlib·markdown·playwright를 사용한다. 브라우저 검증은 기존 Chrome을 사용하며 외부 HTTP 요청은 차단한다.

아래를 이 디렉터리에서 순서대로 실행한다. 계산은 보관된 원문과 가격만 읽는다. 네트워크 재수집은 필요하지 않다.

```powershell
$researchPython = 'C:/Users/91ssj/AppData/Local/Programs/Python/Python312/python.exe'
& $researchPython -X utf8 prices/phase_analysis.py
& $researchPython -X utf8 phase_support.py
& $researchPython -X utf8 render_phase.py
& $researchPython -X utf8 build_phase_report.py
& $researchPython -X utf8 visual_qa.py
& $researchPython -X utf8 validate_phase.py
```

`validate_phase.py`는 새로운 16개 연구 테스트와 상위 연구의 27개 테스트를 실행하지만, 상위 테스트 결과 파일이나 원장을 덮어쓰지 않는다. 운영 애플리케이션 테스트는 이 연구와 무관하므로 실행하지 않는다.

## 해석 범위

앵커는 확보 자료 내 사후 관측점이며 최종 사이클 고점을 인증하지 않는다. 모든 특징 계산은 해당 역사 날짜까지의 가격만 사용하지만, 비교 설계자는 2008년 결과를 이미 알고 있다. 엄격·기본 조건의 일치가 없으므로 ‘가장 비슷한 단일 날짜’를 통계적으로 확정하지 않는다. 예시는 같은 중국 경로에 속하고 서로 겹치며, 확률의 표본으로 사용하지 않는다.

자료의 원발표일과 회고 수집 시각을 구분했다. 원발표 당시 보관본의 빈티지는 완전히 인증하지 못했다. 고정 FY2027 예상 EPS, 비교 가능한 반대매매, 종목 확산 및 조업일 보정 수출 패널의 결측은 판단 보류다. MSCI World 원문 불일치도 기존 연구대로 미해결 상태를 유지한다.
