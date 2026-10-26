# MTS Research 체크포인트 (재개용)

갱신: 2026-10-26 · 브랜치 `claude/mts-research-upgrade`

## 완료

- P0 문서 이동(SHA-256 검증·원본 정리) + W0 inventory
- P1 records/contracts/artifacts + 원장 6종 등록 — T08·T21·T47·T50~T52·T55~T60
- P2 sessions/availability/snapshots — T01~T07·T09·T10·T12~T14
- P3 targets/maturity — T11·T15~T20·T48(상태)·T59
- P4 distributions/scores — T28~T37
- P5 adapters(V8 tier-1·PB 전행) + baseline_identity.json — **T49 PASS**
- P6 resampling/prequential/gates + origin_losses.parquet(284행) — T38~T46·T54
- P7 hazard scaffold(합성) — T22~T27
- P8 감사 4종 + 보고서(rv_mechanics·objective_align·coherence·data_time)
- P9 CLI(7 verb)+T53 + test_results.json(60매핑) + verdict + handoff — **127 passed**

## 진행 중 / 대기

- V8 tier-2 replay 1회 감독 실행 (백그라운드) → 완료 시
  `cd src && python -m ai_fc.mts_research.cli replay-baseline` 재실행으로
  baseline_identity.json 의 v8_tier2 갱신.
- P10: 전체 스위트 회귀(`cd src && python -m pytest tests -q`, 8~11분) + inventory 재생성
  (`cd src && python -m ai_fc inventory`) + 최종 커밋.

## 남은 조건 (BLOCKED — implementation_handoff.md 표 참조)

W5 실측=V14-D11 / W6 실자료=원천 권한 / W7=계약 등록·영수증 / W8=운영 승인.

## 다음 실행 명령 (재개 시)

```bash
cd src && python -m pytest tests/test_mts_research_*.py -q   # 127 기대
cd src && python -m pytest tests -q                          # 전체 회귀 (백그라운드 권장)
cd src && python -m ai_fc inventory                          # truth-file 지문 갱신
```
