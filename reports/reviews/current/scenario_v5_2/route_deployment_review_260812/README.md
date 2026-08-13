# Scenario V5.2 경로 표시·배포 검토 팩

검토 기준일: 2026-08-12 KST  
기능 변경 범위: `5dc1e148` → `3e3578b2`  
현재 저장소 HEAD: `19e58b7`  
라이브 URL: <https://sung-jinpark.github.io/Jin-s-investing-prediction/#future>

## 결론

- `#future` 기본 화면에 독립 DB 기반 S1/S2/S3 통합 로그 차트가 배포되어 있다.
- 3개월 구간은 시나리오별 14개 전망 관측치를 사용하며, 20거래일 간격으로 축약되던 이전 표시 결함이 제거됐다.
- 기존 champion 화면은 `#future/champion`에 보존되어 있다.
- 기능 변경 3건의 PR·검증·병합·Pages 배포는 모두 성공했다.
- 기능 변경 구간에는 official snapshot, ledger, archive, forecast probability 변경이 없다.
- 단, 기능 병합 뒤 실행된 데이터 갱신 커밋 `60b4d4d` 때문에 현재 HEAD의 집중 테스트는 66 pass / 3 fail이다. 이 상태를 완료로 숨기지 않고 `05_TEST_AND_DRIFT_REPORT.md`에 분리 기록했다.

## 주요 파일

- `00_EXECUTIVE_VERDICT.md`: 최종 판정과 제한사항
- `01_SCOPE_AND_CHANGE_MATRIX.md`: 변경 목적·파일·효과
- `live/live_validation.json`: 캐시 파라미터 없는 라이브 URL의 SVG 실측값
- `evidence/git_and_deployment.json`: 커밋·PR·CI·Pages 증거
- `evidence/protected_scope.json`: 보호 범위 불변 증거
- `evidence/targeted_tests.xml`: 현재 HEAD 집중 테스트 원문
- `05_TEST_AND_DRIFT_REPORT.md`: 기능 검증과 후속 데이터 드리프트 분리
- `source/patches/`: 기능 커밋 3건의 원본 patch
- `source/`: 변경 소스·테스트·현재 candidate snapshot
- `static_build/`: 현재 HEAD에서 재생성한 정적 `index.html`과 `data.json`
- `MANIFEST.sha256`: ZIP 내부 파일별 SHA-256

## 검토 시 주의

이 팩은 표시 및 배포 변경을 검증한다. Scenario V5.2는 여전히 `degraded` 연구 후보이며 champion 승격이나 보정된 발생확률을 주장하지 않는다.
