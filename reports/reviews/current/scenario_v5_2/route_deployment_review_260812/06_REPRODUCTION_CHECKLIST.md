# 재현 체크리스트

저장소 루트에서 다음 순서로 확인한다.

```powershell
git checkout 19e58b7
python -m ai_fc sync --rebuild
python -m ai_fc dashboard --pages-out .\_site
pytest -q src/tests/test_dashboard.py src/tests/test_scenario_v5_2.py
```

라이브 화면에서는 다음을 확인한다.

1. <https://sung-jinpark.github.io/Jin-s-investing-prediction/#future> 접속.
2. H1이 `세 가지 시장 경로`인지 확인.
3. SVG에 `data-scale="log"`, `data-history-share="0.25"`, `data-forecast-share="0.75"`가 있는지 확인.
4. `[data-scenario-p50]`가 S1/S2/S3 세 개이며 각 경로가 44개 SVG 점을 갖는지 확인.
5. 3개월 전망 경계 뒤 관측치가 각 14개인지 확인.
6. `#future/champion`에서 기존 시장 전망이 보존되는지 확인.

기능 patch 재검토는 `source/patches/`의 세 파일을 순서대로 읽는다.
