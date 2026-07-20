# P1 운영 가이드 — ai-fc CLI

## 설치 (1회)

```powershell
pip install anthropic pydantic typer python-frontmatter pyyaml pytest
$env:ANTHROPIC_API_KEY = "<YOUR_API_KEY>"   # 또는 OS 암호화 저장(DPAPI) — 키를 파일·저장소에 평문으로 두지 않는다
```

실행은 항상 `src/` 디렉터리에서 (또는 PYTHONPATH에 src 추가):

```powershell
cd C:\workspace\ai-investing\src
python -m ai_fc --help
```

## 일상 워크플로

```powershell
python -m ai_fc due                    # 오늘 할 일 (재예측·해소 기한)
python -m ai_fc forecast <qid> --yes   # 질문 1개 예측 (리서치→추론→불변 기록)
python -m ai_fc forecast --due --max 3 # due 예측 일괄 (기본 3개 상한)
python -m ai_fc resolve <qid>          # 해소 판정 (Brier 미리보기 → 확인 → 원장)
python -m ai_fc report --open          # 캘리브레이션 대시보드
python -m ai_fc sync --check           # 파일↔DB 정합·불변성 검사 (이상 시 종료코드 1)
```

- `python -m ai_fc quant`: 정량 재적합 (오버레이·Hurst·LPPL·GBM·미드텀) → `base_rates/quant_auto.md`
- `python -m ai_fc ml`: 오픈웨이트 추론 앙상블 (Chronos-Bolt + Chronos-2 공변량 + T5 샘플경로 + GBM 배리어 + FinBERT 감성 5피드, 전부 로컬 CPU) → `base_rates/ml_auto.md` + `data/ml_history/*.jsonl` 이력. **주 1회 실행 권장** (due의 ML 신선도 7일과 정합). 학습 없음 — 결합은 고정 중앙값. 최초 실행 시 HF 다운로드: bolt ~190MB, chronos-2 ~480MB, t5-small ~200MB
- `python -m ai_fc market`: 시장내재확률 수집 (Kalshi→Polymarket 폴백, CBOE QQQ 옵션 BL) → `base_rates/market_auto.md`. 이후 예측 실행 시 frontmatter의 market_implied/edge가 자동 기입 (기록 전용 — edge 시그널은 P3 게이트 봉인)
- `due`에 `divergence` 항목이 뜨면: LLM 최신 확률과 ML 앙상블 참조의 괴리 15%p+ — 재예측 **후보**일 뿐 자동 실행되지 않는다. 모델 간 불일치 20%p+면 참조 신뢰가 낮아 표시 자체가 억제된다
- 예측 파이프라인은 신선한(7일 내) ml 실행이 있으면 분위수 밴드·감성 다이제스트를 추론 프롬프트에 자동 주입한다 (질문별 ML 매핑 확률은 앵커링 방지를 위해 의도적으로 미주입)
- `forecast --dry-run`: 실 LLM로 배선 점검하되 `db/scratch/`에만 기록 (forecasts/ 무접촉)
- `--agents 4`: 중요 질문은 펀더멘털/매크로/수급/데블스 4에이전트로 확장
- `--budget 4.00`: 파이프라인당 비용 상한 (기본 $4, 월 상한 $100 — 환경변수 `AI_FC_MONTHLY_BUDGET`)
- deadline이 null인 질문은 실행 거부됨 → 발표일 확인 후 registry에 deadline 기록하고 재실행

## 매일 아침 due 다이제스트 (Windows Task Scheduler, 선택)

관리자 PowerShell에서 1회:

```powershell
$action = New-ScheduledTaskAction -Execute "python" `
  -Argument "-m ai_fc due --notify" -WorkingDirectory "C:\workspace\ai-investing\src"
$trigger = New-ScheduledTaskTrigger -Daily -At 09:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable   # 놓친 실행 재시작 후 보충
Register-ScheduledTask -TaskName "ai-fc-due-digest" -Action $action -Trigger $trigger -Settings $settings
```

텔레그램 연동: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 환경변수 설정 후 `python -m ai_fc notify --test`.
due 계산은 순수 함수라 PC가 꺼져 있던 날이 있어도 다음 실행에서 자동 복구된다.

## 불변성 규칙 (P0과 동일)

**정확한 능력 서술 (AUDIT-260715 T-5)**: 코드는 배타적 생성으로 **덮어쓰기를 차단**하고,
해시 대조로 **우발적·수동 변경을 탐지**한다 — OS 수준 쓰기 방지(예방 통제)는 없다.
독립 기준선: `forecasts/.hashes` (git 추적 — DB 재구축과 무관).

- `forecasts/` 파일은 배타적-생성만 가능 — 코드로는 덮어쓰기 불가(ImmutabilityError)
- `ledger.csv`는 append-only — 행 변조·축소는 `sync --check`가 E3로 검출
- 예측 있는 질문의 판정기준 변경은 W1 경고
- DB(`db/index.db`)는 파생 인덱스 — 삭제해도 `sync --rebuild`로 완전 복구.
  단 `--rebuild`는 재기준화 전에 기존 해시와 대조하며, 불일치(E1/E2) 발견 시
  `--force` 없이는 중단한다 (침묵 재기준화 차단)

## 스케줄(cadence) 관리

registry.yaml의 `schedule:` 필드가 기계 판독 스케줄이다:

```yaml
schedule:
  - per_week: 1              # 기본: 주 1회
  - from: D-14               # 기한 14일 전부터는
    per_day: 1               #   일 1회
  # {once: true} = 1회성, {from_date: "2026-09-29"} = 특정일부터
```

`python -m ai_fc due --explain`으로 질문별 활성 간격 확인. 해석 불가 질문은 manual-review로 표시된다.

## 문제 해결

- **락파일 오류**: 이전 실행이 강제 종료된 경우 `db/.ai_fc.lock` 삭제
- **한글 깨짐**: `$env:PYTHONUTF8='1'` 설정
- **드리프트 경보**: `sync --check` 출력의 E1/E2/E3는 불변성 위반 — git으로 원인 추적 (`git log -p <파일>`)
