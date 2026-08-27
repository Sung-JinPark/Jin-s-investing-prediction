# NASDAQ V7 R5 RALPH GATE-PASS PACK (20260827)

R4 HOLD(전 성분 기각, w_E0=1.0)에 대한 근본원인 분석과 R5 재도전 설계.
배치 위치: 저장소의 `data/timeseries_v7_r5/ralph/spec/` 하위에 전체 복사.

## 구성
- `R5_GATE_PASS_BLUEPRINT_MATH_20260827.md` — 수학 정본: CRPS 분해 기반 원인 진단,
  E0-내포(nest) 챌린저 5가족(E1' FHS-HAR 최우선), σ̂ 3원, 자격 통계·MDE, 결정 D-1~D-3
- `ralph_spec/CODEX_MASTER_PROMPT_V7_R5_RALPH_20260827.md` — 루프 헌법(불변 계약 8항 + 프로토콜)
- `ralph_spec/CODEX_LAUNCH_PROMPT_V7_R5_20260827.md` — 붙여넣기용 런처
- `ralph_spec/R5_BOOTSTRAP_BACKLOG_20260827.json` — 태스크 큐 13개(A1→P1, deps·수용기준 포함)
- `ralph_spec/R5_GATE_DEFICIT_ROUTER_20260827.yaml` — 결손→후속 라우팅(금지 경로 명시)
- `ralph_spec/R5_CONFIG_20260827.yaml` — ralph 루프 파라미터
- `ralph_spec/R5_TASK_ENVELOPE_TEMPLATE.json` / `R5_RESULT_TEMPLATE.json`

## 실행
1. 위 경로에 배치 후 Codex 세션에 LAUNCH 프롬프트 전문 붙여넣기.
2. 루프는 R5-A1(계약 원문 인용)부터. first-light 마일스톤 = R5-M1(FHS-HAR) 전 파이프라인 관통.
3. 정지 지점: 전원 기각 시 D-1/D-2 결정 대기, admitted 존재 시에만 R5-G4 outer 1회.

## 원칙 (한 줄)
게이트 임계·E0·평가 그리드는 불변. 챌린저 전원이 퇴화 파라미터에서 E0와 1e-12 일치해야
하며(no-regret 구조 보장), 그래도 HOLD면 HOLD를 기록하는 것까지가 성공이다.
