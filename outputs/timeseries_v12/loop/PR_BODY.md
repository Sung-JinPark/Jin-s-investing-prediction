# V12 이벤트 확률화 트랙 — 일요일 Opus 루프 (부정 결과)

> **상태: PR 준비만 완료. 푸시하지 않았고 PR 을 열지도 않았다** (envelope spec `PR 준비(push 금지)`).
> 이 파일은 사람이 PR 을 열 때 붙여넣을 본문 초안이다.

## 한 줄

V8 `first_touch_probability`(−10% 접촉) 를 재보정해 창을 넘어 전이시키려는 사전등록 가설 4종이
**전부 기각**됐다(채택 0/8 셀). 음성 대조까지 실패해 이 검정 기계로 얻는 통과는 증거로 쓸 수 없다.
V12 는 **부정 결과 계약**으로 고정됐고 게이트는 등록되되 무장되지 않는다.

## 왜 이 PR 이 안전한가

- **백테스트·홀드아웃·봉인·refresh 실행 0회.** 전 단계가 커밋된 원장·run 의 읽기 전용 재분석이다.
- **V8/V2 봉인 무변경** — `e3ff2fdb64ac71c0f05ae8e4508ef1c5a7c8fba7b78d81548918881032c8d224`
  (BOOT 기준선과 일치). V8 원장 `b9c492be276f684832aac373f80252b305cee980d4312ba3d1e5a707b04bf803`.
- **불변 경로 무수정** — `forecasts/` · `calibration/` · `src/` · `data/timeseries_v8` ·
  `data/timeseries_v2` · `questions/` 워킹트리 변경 0.
- **2015+ 홀드아웃 미소모** — 어떤 단계도 봉인창을 계산하지 않았다.
- **제품 코드 변경 0** — `src/` 아래 수정 파일 없음. 추가된 것은 `tools/v12_*.py` 재분석
  스크립트, `data/timeseries_v12/**` 산출물, `docs/` 문서, `data/contracts/*.draft.yaml` 뿐이다.

## 무엇이 들어 있나

| 갈래 | 내용 |
|---|---|
| S1 독립 반박 검증 | V9·V10·V11 세 동결을 원장에서 재계산 — **번복 0**. 방법론 민감도 33셀(블록길이·창 경계·calm 백분위) |
| S2 이벤트 표적 진단 | V8 first_touch 실력 전수 계측 + 반사원리(2Φ·BGK) 기계 기준선 대비. **과신은 V8 의 결함이 아니라 표적의 성질** |
| S3 사전등록 검정 | 가설 T1~T5 를 결과 보기 전 커밋(`ec496463`) → 양방향 전이 + 블록부트 CI90 + 순열 귀무 1000회. **채택 0/8** |
| S4 계약·게이트 | `multivariate_timeseries_v12.draft.yaml`(부정 결과 계약, 게이트 6종 등록·armed=false) + 게이트 설계서(산술·MDE·예산·배포 경계) |
| S5 종합 | 최종 보고 + 사용자 결정표 V12-D1~D5 + 미완 정직 기록 + inventory 재생성 |

## 리뷰어가 먼저 볼 파일

1. `docs/review/SUNDAY_LOOP_FINAL_REPORT.md` — 이 PR 의 전부가 여기 요약돼 있다(결정표 포함).
2. `docs/design/v12_s3_verdict.md` — 부정 결과 판정서.
3. `data/contracts/multivariate_timeseries_v12.draft.yaml` — 승인 대상 계약 draft.
4. `docs/design/v12_gate_design.md` — 게이트 산술·예산·배포 경계.

## 재현 방법

```
.venv/Scripts/python.exe tools/v12_run.py tools/v12_seal_check.py      # 봉인 대사
.venv/Scripts/python.exe tools/v12_run.py tools/v12_ckpt_seal.py --check
.venv/Scripts/python.exe tools/v12_run.py tools/v12_s5_report.py       # 무결성 + 최종 수치
.venv/Scripts/python.exe tools/v12_run.py tools/v12_s5_doc_check.py    # 보고서 대사
```

## 병합 전 확인 사항

- **브랜치 범위 주의**: `claude/v12-sunday` 는 `main` 보다 545 커밋 앞서 있다. 이 루프의 실제
  기여는 `af7b8d63^..HEAD` 30 커밋 / 123 파일이다. 브랜치 전체를 그대로 PR 로 열면 루프 밖
  작업이 함께 실린다 — 범위를 분리할지 사람이 결정해야 한다.
- **사용자 결정 5건이 열려 있다** (V12-D1~D5). 병합은 결정을 대신하지 않는다 — 계약은
  `status: negative_result_draft` 이고 게이트는 무장되지 않은 채로 병합된다.
- 원격 푸시는 이 루프가 하지 않는다. 비밀 스캔 후 소유자가 직접 푸시한다.

## 이 PR 이 주장하지 않는 것

- "V8 확률이 잘 보정돼 있다" — 아니다. 과신 구조는 그대로 남아 있다.
- "어떤 재보정도 불가능하다" — 아니다. 부정된 것은 **등록된 네 맵과 이 검정 절차**다.
- "V8 이 기계 기준선을 이긴다/진다" — 어느 쪽도 CI90 으로 확립되지 않았다.
- 2015+ 봉인창에 대한 어떤 주장도 하지 않는다.
