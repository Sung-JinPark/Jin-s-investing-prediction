# CKPT — 월요일 체크포인트 봉인표

브랜치 `claude/v12-sunday` · HEAD `96f705d1` (loop(v12): S3-2 result JSON + 자기주장 대사 자동화)

## 1. 봉인 재대사 (V8/V2 + v8 원장)

| 대상 | 재계산 sha256 | BOOT 기준선 | 일치 |
|---|---|---|---|
| V8 전체 .py + V2 봉인 8종 | `e3ff2fdb64ac71c0f05ae8e4508ef1c5a7c8fba7b78d81548918881032c8d224` | `e3ff2fdb64ac71c0f05ae8e4508ef1c5a7c8fba7b78d81548918881032c8d224` | ✅ |
| data/timeseries_v8/ledgers/*.jsonl | `b9c492be276f684832aac373f80252b305cee980d4312ba3d1e5a707b04bf803` | `b9c492be276f684832aac373f80252b305cee980d4312ba3d1e5a707b04bf803` | ✅ |

접두사 `e3ff2fdb` 확인: ✅ · 규약: tools/v12_seal_check.py (sunday_opus_loop.sh sealed_hash() 규약 재현)

## 2. 단계별 산출물 대사 (선언 sha256 vs 재계산)

| 태스크 | 제목 | 상태 | 산출물 | 선언과 일치 | 유실 | 변조(drift) | result JSON sha256 |
|---|---|---|---|---|---|---|---|
| S1-1 | 세 동결 독립 재계산 | 완료 | 3 | 3 | 0 | 0 | `2733986cd10b8107…` |
| S1-2 | 공통 방법론 민감도 | 완료 | 6 | 6 | 0 | 0 | `614da556a4b19090…` |
| S1-3 | 저비용 옵션 판정 + PROMPT 5문 답 | 완료 | 5 | 5 | 0 | 0 | `f640216100babbef…` |
| S2-1 | first_touch 실력 계측 | 완료 | 8 | 8 | 0 | 0 | `68e5613a985dc0e6…` |
| S2-2 | 반사원리 기계 기준선 | 완료 | 12 | 12 | 0 | 0 | `32ddc6793a2f7a3c…` |
| S2-3 | S2 진단서 | 완료 | 9 | 9 | 0 | 0 | `1b960d08a1edb678…` |
| S3-0 | 가설 사전등록 커밋 | 완료 | 6 | 6 | 0 | 0 | `b4ed358e44f1c539…` |
| S3-1 | T1~T4 양방향 전이 + CI + 귀무 | 완료 | 6 | 6 | 0 | 0 | `404214ff74abb99e…` |
| S3-2 | S3 판정 | 완료 | 8 | 8 | 0 | 0 | `a9b4452a9a2cd2c3…` |
| **합계** | S1~S3 9태스크 | 전부 완료 | **63** | **63** | **0** | **0** | result JSON 9종 |

## 3. 앵커 해시 (`<sha256> *<relpath>` 정렬 후 재해시 — sealed_hash() 규약)

| 앵커 | 범위 | sha256 |
|---|---|---|
| artifacts | 산출물 63개 | `cdf359100d55097a13392a8105f45b4f161be4a87ec291a51c6cfcf46711c75f` |
| results | result JSON 9종 | `7a50cb3c58dbe1a3935ccc2fad444330fef198aa8da7e584bcbd2a69f054f2d0` |
| **CHECKPOINT** | 위 둘의 합집합 72개 | `a4b817d445847d18302c7c6dd8da28915e36842f6e071404193e828113eaeb9e` |

## 4. 무변경 대사

| 항목 | 결과 |
|---|---|
| 봉인 산출물 git 추적·커밋 완료 (72개 경로) | ✅ 미추적 0 · 미커밋 0 |
| 불변 경로 워킹트리 (forecasts · calibration · src · data/timeseries_v8 · data/timeseries_v2 · questions) | ✅ 변경 0 |

## 5. 백로그 상태

- 완료: S1-1, S1-2, S1-3, S2-1, S2-2, S2-3, S3-0, S3-1, S3-2
- 대기: S4-1, S4-2, S5-1
- S3 결과: 채택 0/8 — 전이 불가 부정 결과 확정 (S3-2)
- 다음 단계: S4-1 (부정 결과 계약)

## 6. 봉인 판정

**봉인 성립 = True** — 봉인 해시 2종 일치 · 산출물 유실 0 · drift 0 · 불변 경로 무변경.

- 이 파일이 체크포인트 봉인 정본이다. state.json 은 감독 스크립트가 종료 시 {'ended','iters'} 로 덮어쓰므로(sunday_opus_loop.sh:75) 같은 앵커를 심되 정본이 아니다.
- 감독 스크립트의 00:00 KST 자동 체크포인트(monday_ckpt.sha256)는 epoch 1788706800 이후 별도로 기록된다 — 본 태스크는 그와 독립인 태스크 봉인이다.
- 백테스트·홀드아웃·refresh·push 0회. 이 스크립트는 읽기 + 봉인 파일 2개 쓰기만 한다.
