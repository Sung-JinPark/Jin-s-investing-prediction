# ADR-001: Point-in-time 분석 저장 계층

- 상태: Accepted
- 날짜: 2026-08-01

## 결정

운영 메타데이터·질문·예측·점수·registry는 SQLite에 둔다. 대량 revision fact는
`data/facts/source_id=<id>/year=<yyyy>/part-<hash>.parquet`에 append하고, 분석 시에만
in-memory DuckDB가 read-only로 조회한다. SQLite/Parquet는 모두 원천과 raw manifest에서
재생 가능하며 데이터베이스 파일 자체를 정본으로 취급하지 않는다.

## 이유

- 현 저장소는 GitHub Pages와 단일 사용자 로컬 실행이 중심이라 server DB 운영비가 불필요하다.
- Parquet는 columnar 압축과 연도 partition으로 긴 revision 이력을 경제적으로 보존한다.
- DuckDB는 Parquet filter/projection pushdown과 Hive partition pruning을 지원한다.
- SQLite는 작은 운영 read model과 atomic rebuild에 충분하고 기존 소비자 호환성이 가장 높다.

## 제약

- 동시 writer나 원격 multi-user API가 필요해질 때 PostgreSQL/warehouse ADR을 새로 작성한다.
- `available_at <= as_of`가 모든 평가/feature 질의의 강제 조건이다.
- Yahoo처럼 native vintage가 없는 backfill은 retrieved_at 이전 시점 평가에 사용할 수 없다.
