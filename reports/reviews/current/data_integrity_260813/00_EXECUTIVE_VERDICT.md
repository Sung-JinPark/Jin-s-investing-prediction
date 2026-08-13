# 종합 판정

## PASS

- 최신 통계 스냅샷: `2026-08-13T10:42:40+00:00`, 관측 최댓값 `2026-08-12`, 장표 28개.
- FRED/Fed Z.1 live raw receipt exact match: 22/22.
- KOSPI/NASDAQ 공식 공개 계열 재계산 일치: `true`.
- SK하이닉스 포함 영향력 진단: 실제 IPO 5와 별도로 영향력 포함 6, 재계산 일치 `true`.
- 다년 스트레스: 화면 SVG 1개, official input `false`.
- 보호 파일: 123/123 불변, 허용 연구후보 변경 0건, 무단 변경 0건.

## HOLD / 제한

- V5.2 promotion은 HOLD: `NOT_OFFICIAL_NOT_CHAMPION`. S2 표본은 16/20이고 30거래일 threshold 관측은 0/30입니다.
- kernel 전체 gate는 `false`입니다. 실패를 경로 수정이나 확률 보정으로 숨기지 않았습니다.
- IPO/HMI는 수동 검토 참조입니다. 14일/62일 freshness gate가 초과 시 주간 작업을 실패시키지만 자동 원문 분류기는 아닙니다.
- rate probability는 유료 CME API가 아니라 CME futures 기반 Investing.com 공개 화면 캡처입니다. BLS 고용은 공식 BLS 원문입니다.
- 현재 KOSPI 월수익 선행 상관은 1개월 +0.03, 2개월 +0.07, 3개월 +0.13로 약합니다. 강한 선행 신호라는 주장은 기각합니다.
