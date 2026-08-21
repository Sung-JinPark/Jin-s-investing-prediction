# 모델 리스크와 다음 단계

## 현재 채택할 수 있는 결론

- 장기 평균 CRPS는 기준선보다 개선 방향이지만 사전등록 2% 문턱에는 미달한다.
- 63일에서는 개선이 확인됐지만 21일 개선 폭은 작다.
- 평균 성과보다 중요한 tail calibration이 부족하다. 특히 가장 큰 움직임의 Q4 coverage가 크게 낮다.
- 따라서 현재 결과로 고객용 수익률·상승확률·밴드를 제공할 수 없다.

## 주요 리스크

1. **역사평가 비봉인성**: 과거 구간은 설계 과정에서 관찰됐다. 성능 추정은 연구용이며 실제 forward shadow가 필요하다.
2. **tail under-dispersion**: Q4와 위기구간의 p10–p90 밴드가 너무 좁다.
3. **DFM 미연결**: factor loading 명칭·부호·scale 계보가 없는 V2 cache를 억지로 사용하지 않았다.
4. **event 표본 부재**: 고용·CPI·FOMC 컨센서스와 시장확률을 사용할 수 있는 인터페이스는 있으나 역사 PIT sample이 없다.
5. **시장확률 calibration 부재**: risk-neutral 확률을 물리확률로 직접 쓰지 않았다.
6. **analyst challenger 미검증**: 출판시각·중복클러스터·신뢰도 walk-forward가 채워지기 전 numerical weight는 0이다.

## V3를 사후 조정하지 않는 이유

극단구간 coverage를 맞추기 위해 band를 임의 확대하거나 Gate를 낮추면 같은 역사 결과에 대한 사후 최적화가 된다. 현재 V3는 HOLD benchmark로 보존한다.

## 후속 V4가 허용되는 조건

- 별도 계약과 새 model ID/version을 사전등록한다.
- 현재 V3 결과와 threshold를 수정하지 않는다.
- tail 목표를 별도 proper score로 학습하고 Q4·위기 coverage를 직접 검증한다.
- V3-native named-loading DFM cache를 구축한다.
- event·market-implied 모듈은 실제 PIT sample과 ablation을 통과한 뒤에만 활성화한다.
- 진정한 성과 주장은 동결 이후 forward shadow만 사용한다.
