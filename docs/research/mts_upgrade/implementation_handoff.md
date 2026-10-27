# MTS Research 계층 — 구현 인계 (implementation_handoff)

작성: 2026-10-26 · 브랜치 `claude/mts-research-upgrade` (origin/main @ 0abe0a57 기반)

## 변경 파일 (전부 신규 — 기존 파일 변경은 ledger_registry.yaml 추가-전용 1건)

| 영역 | 파일 |
|---|---|
| 설계 정본 | `docs/design/NASDAQ_forecasting_upgrade_design_20261026.md` (Downloads 원본 SHA-256 검증 이동) |
| 코드 | `src/ai_fc/mts_research/{records,contracts,artifacts,sessions,availability,snapshots,targets,maturity,distributions,scores,resampling,prequential,gates,hazard,cli}.py` + `adapters/{v8,pb,report}.py` + `audits/{coherence,rv_mechanics,objective_align,time_audit}.py` |
| 계약 | `data/mts_research/contracts/mts_research_v1.draft.yaml` (§18 초안 — state: draft) |
| 원장 등록 | `data/contracts/ledger_registry.yaml` 에 mts_research 6종 추가-전용 (expected_state: planned) |
| 테스트 | `src/tests/test_mts_research_*.py` 16파일 + `mts_research_fixtures.py` — **127 passed** |
| 산출물 | `docs/research/mts_upgrade/{repository_inventory,data_time_audit,coherence_audit,objective_align_audit,rv_mechanics_audit,research_verdict}.md` + `baseline_identity.json` + `test_results.json` |
| 파생 | `data/mts_research/derived/{origin_losses.parquet,coherence_audit.json,data_time_audit.json,objective_align_audit.json}` + `experiments/rv_mechanics/{prereg,results}.json` |

## 재현 명령

```bash
cd src && python -m pytest tests/test_mts_research_*.py -q          # 127 테스트
cd src && python -m ai_fc.mts_research.cli inventory                 # §17.1 조사
cd src && python -m ai_fc.mts_research.cli validate-contract --contract ../data/mts_research/contracts/mts_research_v1.draft.yaml
cd src && python -m ai_fc.mts_research.cli audit-time                # 시간 감사 재생성
cd src && python -m ai_fc.mts_research.cli replay-baseline           # T49 identity + baseline_identity.json
cd src && python -m ai_fc.mts_research.cli run-experiment --dry-run  # 예산 0·payload 0 검증
```

## 보호 준수 (실측)

- 동결 파일(`model_code_hash` 범위·V13 계수·계약) 변경 0 — identity 테스트가 read-only 를 단언.
- V5.2 보호 루트 아래 새 파일 0. `timeseries_v14` 문자열/패키지 추가 0 (cli.py 무수정).
- 보호 창 **guarded purpose(research_fit/evaluation) 읽기 0** — `read_scope_guard` 가 영수증
  없는 fit/평가를 거부(거부도 exposures.jsonl 에 기록). 정밀화(2026-10-27, F03):
  replay_identity/audit 은 OPEN purpose 로 시장 아카이브 전 기간(홀드아웃·봉인 구간 날짜
  포함)을 읽는다 — 생산 경로와 동일한 읽기이고 계약의 '소모' 정의(finalist 채점·1회 공개)에
  해당하지 않으며 전부 exposures.jsonl 에 기록된다.
- 예산 소모 0: V13 8/8(기존)·V14 1/4(기존) 불변 — 본 계층은 어떤 실험 원장에도 쓰지 않았다.

## 남은 장애 (구체)

| 항목 | 필요한 것 | 승인 시 정확한 행동 |
|---|---|---|
| W5 실측 (V14 rung-2 hazard) | **V14-D11 결정** + `data/timeseries_v14/ledgers/approvals.jsonl` 리터럴 영수증 + rung-2 prereg | `hazard.py` 를 V14 조건부 코호트에 적합(도구 경로는 tools/ 스크립트 — V14-D10 전 모듈화 금지 유지), 조건부 PB 대비 등록 비교 |
| W6 실자료 (옵션/일중) | 원천 1개의 계약·권한·coverage 확인 (`data/mts_research/source_specs/*.yaml` 의 enabled 전환은 전 좌표 verified 후) | NEW_INFO_ONE_BLOCK 1개 블록만 활성화 |
| W7 등록 실험 | 계약 state: draft→registered (필수 null 전부 채움: read scope/예산 영수증·primary metric·family·블록 규칙·seed manifest) | `run-experiment` (dry-run 통과 후) — 모든 시도를 experiments/ 에 불변 기록 |
| W8 운영 연결 | 운영 계약 + 표시 승급 승인 | shadow 발행·HOLD·모니터링 연결 |
| V8 tier-2 완주 | 장시간 실행 1회 (감독) | `adapters.v8.tier2_replay_forecast` — 결과는 `derived/v8_tier2_replay.json`, 드리프트는 fail-closed 상태로 기록 |

이미 승인된 범위(이 요청의 문서 이동·연구 계층 구현·read-only 감사·합성 테스트)는 완료 —
재승인 불요. push/PR·merge 는 수행하지 않았다(요청 §7: 임의 push 금지).

## 후속 설계 입력 (수정이 아니라 기록)

- grid-종속 라벨(국채 휴장 주식 세션 누락)은 **신규 target 계약**(§4.2 재현 vs 신규 발행
  정책 분리)의 입력 — 동결 V8 은 그대로.
- V13 `labels_rv` 의 부분결측=0 처리와 mts UNRESOLVED 정책의 차이 — adapter 는 V13 정의,
  신규 표적은 mts 정책 (문서화 완료, V13 불변).
- `forward_realized_variance`(알려진 성분 제거) 는 별도 연구 표적 후보로만 등록.
- (Q8, 2026-10-27) 실원장 → LossPanel 빌더(W7)는 손실 행이 아니라 **표적의 예정 원점
  달력에서 origin_grid 를 먼저 구성**하고 손실 행을 투영해, 결측 원점에
  missing_reason(UNRESOLVED/NOT_ISSUED/HOLD)을 부여한다 — 해소 성공 행만으로 패널을
  만들면 분모가 사라진다. 확증 판정 전 `gates.enforce_candidate_failure_policy` 필수.
- (Q13, 2026-10-27) OBJECTIVE_ALIGN 후속 감사 경로: 과거 λ 선택 이력 경유, 잔차/표준화
  이력의 분포 파라미터 전달, lag 변경의 이력 길이·캐시 키 영향, ensemble/재보정 단계 재유입
  — raw FHS/혼합 전후/PIT 보정 전후를 분리 측정.
