# data/ — 데이터 계층 지도 (CCDS v2 관례 대응표)

> "data is immutable" 원칙의 우리식 구현 — 계층별 원천·재생성 가능 여부를 명시한다.
> 업계 명명(raw/interim/processed)으로 개명하지 않는 이유: `forecasts/.hashes`·append-only
> 규약이 경로를 참조하므로 이동/개명은 금지 (docs/ARCHITECTURE.md §1, 벤치마킹 260720 ②-B).

| 디렉터리 | CCDS 대응 | 성격 | 재생성 |
|---|---|---|---|
| `base_rates/*.md` (수동) | references | Outside view 라이브러리 — 수동 큐레이션, 가변 (수집일 표기 의무) | 사람 |
| `base_rates/*_auto.md` | processed | 자동 산출본 (`ai_fc ml`/`market`/`quant`, `dualdb export`) | 커맨드로 전량 재생성 |
| `ml_history/*.jsonl` | raw (불변) | 모델 산출 이력 — **append-only**, DB 재구축의 원천 | 불가 (원천) |

인접 계층: `forecasts/`(불변 기록 — 수정·삭제 절대 금지) · `calibration/`(append-only 원장) ·
`db/`(SQLite 파생 인덱스 — gitignore, `sync --rebuild`로 재구축) · `dualdb/data/`(원천 보존).
