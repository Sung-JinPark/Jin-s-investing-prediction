---
description: 테스트 실행 규약과 대시보드 검증 함정
globs: ["src/**", "dualdb/**"]
---

# 테스트

## 실행 위치

pytest 는 **`src/` 안에서** 돈다. 저장소 루트에서 돌리면 `ai_fc` 패키지를 못 찾는다.

```bash
cd src && python -m pytest -q
```

- 전체 스위트는 약 8~11분이다. 오래 걸리므로 백그라운드로 돌리고 기다린다.
- `python3` 이 아니라 **`python`** 을 쓴다. 이 환경에서 `python3` 은 프로젝트 의존성
  (`yaml` 등)이 없는 다른 인터프리터를 가리킨다.
- 한글 출력이 섞인 스크립트는 `PYTHONIOENCODING=utf-8` 을 붙인다. 안 붙이면 Windows
  기본 코드페이지(cp949)에서 `UnicodeEncodeError` 로 죽는다.

## 대시보드를 고쳤을 때

`src/ai_fc/dashboard_parts/` 를 건드렸다면 빌드해서 **브라우저로 확인**까지 한다.

```bash
cd src && python -m ai_fc dashboard --pages-out <출력경로>
```

검증할 때 자주 걸리는 함정:

- **스크롤이 잠긴다.** `window.scrollTo` / `scrollIntoView` 를 해도 `scrollY` 가 0 에서
  안 움직이는 경우가 있다. 환경 제약이지 사이트 버그가 아니다. 스크린샷 대신
  `read_page` · DOM 조회로 확인한다.
- **패널이 hidden 이거나 폭이 0 이면** rAF 가 멈춰 스크린샷이 비어 나온다.
- **미리보기 서버가 오래된 빌드를 서빙**할 수 있다. `.claude/launch.json` 이 가리키는
  디렉터리와 실제 빌드 출력 경로가 같은지 먼저 확인한다. 다르면 아무리 새로고침해도
  옛 화면이 나온다.

## 페이로드 예산

`data.json` 에는 바이트 예산이 걸려 있다(`DATA_JSON_BUDGET_BYTES` 등). 데이터를 늘렸으면
빌드가 예산 오류 없이 끝나는지 확인하고, 커진 섹션의 실제 바이트를 재 본다.
