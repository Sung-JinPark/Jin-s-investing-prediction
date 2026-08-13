# 갱신·배포 체인 감사

## 통계

- `statistics-refresh.yml`: 토요일 00:20 UTC. FRED/Fed Z.1을 live fetch하고 reference-only 통계를 재계산합니다.
- 변경 시 append-only `data/statistics/archive`를 추가하고 latest를 바꿉니다.
- 이번 수정으로 inventory도 같은 커밋에 포함합니다.
- IPO 분류는 14일, HMI는 62일 수동 참조 freshness gate를 넘으면 실패합니다.

## 미래 전망

- `scenario-refresh.yml`: 화~토 01:30 UTC. scenario, cross-asset, V5.2 rebuild/replay를 수행합니다.
- 2026-08-13 run은 `market-extensions` 내부 실패가 `continue-on-error`에 가려진 것을 확인했습니다. 이번 수정은 마지막 단계에서 보조 작업 실패를 전체 실패로 보고합니다.
- 같은 금요일 weekly tracker를 반복 수집해 current-vintage revision과 충돌하던 원인은, 이미 검증된 동일 weekly vintage를 재사용하도록 수정했습니다. 기존 archive는 수정하지 않았습니다.

## Pages

- main의 데이터·통계·dashboard·V5.2·multi-year stress 변경이 Pages build를 유발합니다.
- 통계는 `statistics.json`, 미래 경로는 `future_paths.json`으로 라우트별 lazy fetch합니다. 예산 상향 없이 future payload 여유를 회복했습니다.

원문 실행 기록은 `evidence/GITHUB_ACTIONS_RUNS.json`에 있습니다. 구현 커밋 이후 run은 최종 live 증거 파일에서 다시 확인해야 합니다.
