# 제한과 미해결 위험

1. 통계 역사는 latest-release reconstructed라 native PIT backtest가 아닙니다.
2. IPO broad cohort는 완전한 keyword census가 아니라 공개 시장서사 기반 검토 cohort입니다.
3. SK하이닉스는 실제 IPO가 아닙니다. `영향력 포함 6`은 실제 IPO 5 + 기존 상장 수혜주 1의 별도 진단입니다.
4. IPO/HMI는 자동 분류·수집이 아니라 freshness gate가 있는 수동 참조입니다.
5. V5.2 direct event/calibration 표본과 30일 shadow가 부족합니다.
6. market-extensions는 weekly captured vintage를 보존하므로 같은 금요일 이후 공개된 과거 수정치를 소급 반영하지 않습니다. 수정은 승인 correction으로만 append합니다.
7. 네 하락 사례는 사용자가 지정한 선택 사례이며 exhaustive base rate가 아닙니다.
8. BTC는 닷컴기에 존재하지 않았고 beta는 국면에 따라 비선형입니다.
9. KOSPI 선행성은 현재 1~3개월 상관이 약하며 거래시간·환율·국가위험이 섞입니다.
10. 과거 Q1 quarantined benchmark 2건의 probability unit 오류(22.0, 5.0 fraction)가 sync 경고에 남아 있습니다. 격리되어 공식 benchmark에는 유입되지 않지만 별도 승인 correction 대상입니다.
