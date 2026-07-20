"""ml — 오픈웨이트(Hugging Face) 추론 전용 레이어.

★ ML 게이트 준수 (CLAUDE.md 하드 게이트):
  - 여기서는 어떤 학습(fine-tuning·가중치 갱신)도 하지 않는다. 사전학습 모델의 추론만.
  - 캘리브레이션 보정 학습은 해소 100+ 후, 앙상블 가중 학습은 해소 200+ 후에만.
  - 출력은 base rate·시나리오 밴드 공급용 '추정'이며 매매 신호가 아니다.

구성 (전부 무료·로컬 CPU 추론):
  chronos_fc  — amazon/chronos-bolt-small (Apache-2.0, 48M): 시계열 zero-shot
                분위수 예측. GBM(정규분포 가정)의 비모수 보완재.
  sentiment   — ProsusAI/finbert (110M): 무료 RSS 헤드라인 → 금융 감성 지수.
  runner      — 통합 실행 → data/base_rates/ml_auto.md 갱신.
"""
