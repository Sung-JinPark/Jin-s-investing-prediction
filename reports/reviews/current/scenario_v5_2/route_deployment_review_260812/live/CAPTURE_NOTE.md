# 화면 캡처 기록

라이브 DOM과 SVG 검증은 성공했다. 전체 페이지 및 viewport PNG 캡처는 브라우저의 `Page.captureScreenshot` 시간 제한으로 실패해 이 팩에 포함하지 않았다.

화면 존재나 경로 모양을 자기 보고로 대체하지 않도록 `live_validation.json`에 실제 라이브 SVG에서 읽은 경로별 점 개수, 전망 관측치, 방향 전환 횟수, 축 메타데이터와 종점 라벨을 기록했다.
