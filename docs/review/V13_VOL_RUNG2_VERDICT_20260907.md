# V13-VOL rung-2 판정 — HAR 증분 없음: 스킬은 지속성 지배 (2026-09-07)

> 계약 `data/contracts/multivariate_timeseries_v13_vol.yaml` · 도구 `tools/v13_vol_rung2.py`
> · 결과 `data/timeseries_v13/vol/ladder_har_logit.json`. 봉인 read-only, 홀드아웃 미열람.

## 판정 (사용자 Q1 직답)

HAR-logistic(다중스케일 1d/5d/22d)은 기후 대비 게이트를 **9/9 통과**하나, EWMA-logit(사실상 지속성)
**대비 증분은 0/9**. 쌍대 Brier(EWMA−HAR) CI90이 모든 셀에서 0을 가로지르고 일부는 HAR가 더 나쁘다
(예: vix25_h63 l2e −0.00388 CI[−0.00697,−0.00090], rv_h5 l2e −0.00246 CI[−0.00516,−0.00013]).

**→ 스킬은 변동성 지속성 지배. richer 모형(HAR) 무익.** GARCH-t는 같은 지속성을 다른 기전으로 볼 뿐이라
moot — HAR의 null 증분이 이미 지속성 지배를 확증한다(arch 미설치이기도 함). rung 종료. GARCH-t 미실행
(사유: HAR null 증분·재확인 가치 없음·의존성 부재). 사용자가 원하면 별도 착수 가능.

## champion 확정 = EWMA-logit

최단순 지속성 모형이 champion. 기후 대비 실 스킬(BSS +0.09~+0.90·양방향 CI90>0·건전귀무≤0.017),
richer로 개선 안 됨. reliability(HAR, late): h5 rel=0.002(잘 보정)·res=0.087(변별력), h63 rel=0.08(장기 오보정).

## 가치·한계 (정직)

- 가치 = **EXIT 트리거 base rate·조기경보 공급**(CLAUDE.md 1차 목표). 지속성 기반 이벤트 확률이지 시장 엣지 아님.
- 기후는 지속 계열에 약한 기준선 — "기후 통과"는 쉬운 편. 진짜 검정(지속성 대비 증분)에서 richer는 실패.
- 설계창 한정·early(2007-2010) GFC 지배. 진짜 표본외 = 홀드아웃(2015-2018) 미열람 → V13-D3(별도 승인).

## 예산·규율

EWMA-logit 1 + HAR 1 = 2/8 소모. 봉인 e3ff2fdb 무변경·forecasts/·calibration/·V8/V2 원장 무접촉·홀드아웃 미열람.
