# 최종 자동화·배포 증거

## 최종 판정

- Scenario refresh: `success` · run `31695816670`.
- 첫 통계 실패: `failure` · Python TLS read timeout · run `31695813731`.
- 제한 재시도 후 실패: `failure` · 같은 FRED M2SL URL에서 runner transport timeout 지속 · run `31696739695`.
- 동일 URL curl/public-DNS transport fallback 적용 후 통계 refresh: `success` · run `31697312155`.
- 최종 full verify: `success` · run `31697501558`.
- 최종 Pages: `success` · run `31697501562`.

모든 원문 로그는 `evidence/workflow_logs/`에 있습니다. fallback은 공급자나 데이터 계열을 바꾸지 않고 같은 HTTPS URL의 전송 방식만 바꿉니다. 모든 전송이 실패하면 이전 snapshot을 최신으로 재표시하지 않고 작업이 실패합니다.
