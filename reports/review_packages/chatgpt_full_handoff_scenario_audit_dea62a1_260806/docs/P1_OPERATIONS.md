# P1 운영 가이드 — ai-fc CLI

## 설치 (1회)

```powershell
pip install -e "."
$env:OPENAI_API_KEY = "<YOUR_API_KEY>"      # 로컬 실행용; 저장소 파일에 쓰지 않는다
```

## 즉시 푸시 규율 (v3.5 WS-T3 — 공증 등급 A의 성립 조건, 2026-07-30~)

**예측·해소 기록을 만들면 즉시 커밋 + `git push`한다. 커밋 지연 = 공증 공백.**
공개 리포의 커밋 시각이 "질문 마감 전에 예측했다"의 외부 증거가 되려면, 기록 생성과
푸시 사이 간격이 없어야 한다 (등급 체계: `tools/verify_track_record.py` 출력 참조).
`.hashes` 갱신 시 OpenTimestamps 재스탬프(`ots stamp forecasts/.hashes` — .ots 함께 커밋).

```powershell
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

- `due`는 `resolve`를 먼저 표시하고, 같은 resolve 큐는 **기한/윈도우 경과일이 긴 순서**로
  정렬한다. JSON 출력에는 `overdue_days`가 추가된다.
- 가격 임계형 판정 초안: `python -m ai_fc resolve <qid> --draft`.
- macro/earnings 수치형 판정 초안:
  `python -m ai_fc resolve <qid> --draft --resolution-data ..\docs\examples\resolution_observations.example.json`.
  관측 JSON은 1·2차 출처의 `actual`과 필요 시 `reference`만 제공한다. 판정 연산자와 임계는
  registry 문언에서 추출하며, 숫자·단위·출처가 불일치하면 `held`로 보류한다.
  초안은 어떤 경우에도 원장을 쓰지 않는다. 확정은 사람이 공식 근거를 검토한 뒤 기존
  `resolve <qid> --outcome yes|no --evidence <URL·설명>` 경로로 수행한다.
- `python -m ai_fc dashboard`: 예측 흐름 조회 대시보드 (읽기 전용, 자기완결 HTML) → `reports/dashboard.html`. 브라우저로 열면 끝, 의존성 0. 6뷰: 개요·흐름차트(주간 시나리오 S1/S2/S3)·질문브라우저·질문상세(회차 이력+추론)·날짜조회(as-of)·캘리브레이션
  - **팀 공유(LAN)**: `python -m ai_fc dashboard --serve --host 0.0.0.0 [--port 8899]` — 표준 라이브러리 http.server, 읽기 전용(POST 차단), 매 요청 라이브 재조회. LAN 노출은 공개 예측 데이터만(시크릿 미포함)이나 신뢰 네트워크에서만 사용
- `python -m ai_fc quant`: 정량 재적합 (오버레이·Hurst·LPPL·GBM·미드텀) → `base_rates/quant_auto.md`
- `python -m ai_fc ml`: 오픈웨이트 추론 앙상블 (Chronos-Bolt + Chronos-2 공변량 + T5 샘플경로 + GBM 배리어 + FinBERT 감성 5피드, 전부 로컬 CPU) → `base_rates/ml_auto.md` + `data/ml_history/*.jsonl` 이력. **주 1회 실행 권장** (due의 ML 신선도 7일과 정합). 학습 없음 — 결합은 고정 중앙값. 최초 실행 시 HF 다운로드: bolt ~190MB, chronos-2 ~480MB, t5-small ~200MB
- `python -m ai_fc market`: 시장내재확률 수집 (Kalshi→Polymarket 폴백, CBOE QQQ 옵션 BL) → `base_rates/market_auto.md`. 이후 예측 실행 시 frontmatter의 market_implied/edge가 자동 기입 (기록 전용 — edge 시그널은 P3 게이트 봉인)
- `due`에 `divergence` 항목이 뜨면: LLM 최신 확률과 ML 앙상블 참조의 괴리 15%p+ — 재예측 **후보**일 뿐 자동 실행되지 않는다. 모델 간 불일치 20%p+면 참조 신뢰가 낮아 표시 자체가 억제된다
- 예측 파이프라인은 신선한(7일 내) ml 실행이 있으면 분위수 밴드·감성 다이제스트를 추론 프롬프트에 자동 주입한다 (질문별 ML 매핑 확률은 앵커링 방지를 위해 의도적으로 미주입)
- `forecast --dry-run`: 실 LLM로 배선 점검하되 `db/scratch/`에만 기록 (forecasts/ 무접촉)
- `--agents 4`: 중요 질문은 펀더멘털/매크로/수급/데블스 4에이전트로 확장
- `--budget 4.00`: 파이프라인당 비용 상한 (기본 $4, 전역 월 상한 $20 — 환경변수 `AI_FC_MONTHLY_BUDGET`)
- deadline이 null인 질문은 실행 거부됨 → 발표일 확인 후 registry에 deadline 기록하고 재실행

## LLM provider 운영과 비용

- 로컬 기본값은 기존 호환성을 위해 `anthropic`이며, GitHub 자동 갱신은 승인 원장에 고정된
  `openai:gpt-5.6-terra`를 공식 생산자로 사용한다.
- OpenAI 모델은 명시적 tier(`gpt-5.6-sol|terra|luna`) 또는 검증된 날짜 snapshot만 허용한다.
  `gpt-5.6` 같은 이동 family alias는 재현성을 위해 거부한다.
- OpenAI shadow는 `AI_FC_OPENAI_SHADOW_MODEL`과 신규 question id allowlist인
  `AI_FC_OPENAI_SHADOW_QUESTIONS`를 함께 지정한 경우에만 실행한다.
- provider별 월 상한은 `AI_FC_ANTHROPIC_MONTHLY_BUDGET`, `AI_FC_OPENAI_MONTHLY_BUDGET`으로 분리한다.
- `python -m ai_fc provider-guard`는 승인 없는 공식 전환을 검사한다. `calibration/approvals.csv`를 임의로 채우는 것은 사용자 승인을 대체하지 않는다.
- OpenAI 결과는 `calibration/provider_shadow_ledger.csv`에만 append하고 공식 forecast와 결합하지 않는다.
- 비용 감사는 `calibration/cost_log.csv`의 provider/model snapshot/request id/cached input/web search 열을 사용한다.
- 장애 시 공식 provider를 `anthropic`으로 되돌린다. shadow ledger는 삭제하지 않는다.

### GitHub 자동 갱신

`.github/workflows/investing-refresh.yml`은 매주 토요일 11:15 KST에 다음 순서로 실행된다.

1. 커밋된 원천 원장에서 SQLite 인덱스를 재구축한다.
2. Yahoo·FRED 정량 데이터와 Kalshi·Polymarket·CBOE 시장 참조값을 갱신한다.
3. 최신 확정 일봉으로 Nasdaq 시나리오를 갱신한다.
4. due 질문이 있으면 OpenAI로 최대 1건만 새 회차 예측한다.
5. 비용 원장·데이터·예측·인벤토리를 커밋하고 Pages 재빌드를 유도한다.

봇 커밋은 GitHub의 재귀 실행 차단 때문에 일반 `push` 이벤트를 발생시키지 않는다. 따라서
Pages와 verify는 `workflow_run`으로 수집 워크플로 완료를 직접 구독한다. Pages 산출물은
UI shell(`index.html`)과 캐시 가능한 로컬 `data.json`을 분리해 예측 이력이 늘어나도 단일
HTML 용량 한도로 배포가 멈추지 않는다.
예측 해시의 OpenTimestamps 스탬프도 같은 완료 이벤트를 구독해 봇이 만든 신규 예측을
빠뜨리지 않는다.

OpenAI 단계는 `OPENAI_API_KEY` secret을 그 단계에만 주입하며 로그나 파일에 출력하지 않는다.
자동 실행 한도는 회당 `$1.50`, OpenAI/전역 월 `$10`, 검색 최대 4회, 출력 토큰 상한으로
중첩 적용된다. 비용은 SQLite가 아니라 append-only `calibration/cost_log.csv`가 정본이므로
새 Actions runner에서도 월간 사용액이 이어진다. 대시보드 수집·빌드는 API 키가 필요 없다.
파이프라인 후반이 실패해도 이미 성공한 API 호출은 `failed:pipeline:*` 단계로 기록한다.
provider가 usage를 반환하기 전에 실패한 과거 호출은 과소 집계를 피하기 위해
`failed:unmetered-reserve`로 회당 상한을 보수적으로 예약하며 실제 청구액과 구분한다.

수동 연결 검증(아주 작은 유료 호출):

```powershell
gh workflow run investing-refresh.yml --ref main -f mode=smoke
gh run list --workflow investing-refresh.yml --limit 3
```

전체 수동 갱신:

```powershell
gh workflow run investing-refresh.yml --ref main -f mode=full
```

> `cost_log.csv`는 SDK usage 기반 **추정 비용 원장**이다. 결제 청구서와 프로젝트 하드 지출
> 한도는 OpenAI Platform의 Usage/Billing 화면에서 별도로 대조한다.

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
