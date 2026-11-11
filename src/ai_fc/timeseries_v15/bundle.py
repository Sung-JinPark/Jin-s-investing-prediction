"""V15 번들 조립 `bundle_at` — kernel (값에 영향을 주므로 kernel 해시 대상).

봉인 V8 `_sealed_bundle`(timeseries_v8/pipeline.py)을 옮겼다. 차이는 셋이다.
- 시각: 원본은 `datetime.now()`, 여기서는 **인자 knowledge_cutoff** (같은 입력 재현).
- 조립: 포크 `assemble_candidate_bundle`(frame_mode·provenance 전달).
- 반환: `(bundle, provenance)`. `truncate_at` 이면 그 날짜 이후 세션을 자르고 DFM 완결성 기대
  집합도 그 끝까지만 본다(V8 `_development_bundle` 방식 — MDE 설계창 2014-12-31).
DFM 완결성 검사는 그대로 두고, 절단 후 `np.isfinite(exogenous).all()` 을 확인한다.
참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ai_fc.timeseries.ledger import read_facts
from ai_fc.timeseries_v2.contracts import frozen_hash as frozen_hash_v2
from ai_fc.timeseries_v2.contracts import load_contract_v2
from ai_fc.timeseries_v2.dfm_cache import macro_release_cutoffs, read_dfm_manifest

from .features import CandidateFeatureBundle, assemble_candidate_bundle


class V15BundleError(RuntimeError):
    """V15 번들 조립 전제 위반 — fail-closed."""


def truncate_bundle(bundle: CandidateFeatureBundle, *, last_date: str) -> CandidateFeatureBundle:
    """dates ≤ last_date 로 자른다(원점 고정·설계창 절단 공통)."""
    stop = next((index for index, day in enumerate(bundle.dates) if day > last_date), len(bundle.dates))
    return CandidateFeatureBundle(
        candidate_id=bundle.candidate_id, status=bundle.status,
        dates=bundle.dates[:stop], endogenous=bundle.endogenous[:stop],
        endogenous_names=bundle.endogenous_names, exogenous=bundle.exogenous[:stop],
        exogenous_names=bundle.exogenous_names, data_grades=bundle.data_grades,
        missing_features=bundle.missing_features, dfm_cache_ids=bundle.dfm_cache_ids,
        transform_manifest=bundle.transform_manifest,
        dfm_cache_complete=bundle.dfm_cache_complete,
    )


def bundle_at(
    data_root: Path,
    *,
    knowledge_cutoff: str,
    frame_mode: str,
    truncate_at: str | None = None,
) -> tuple[CandidateFeatureBundle, dict[str, Any]]:
    contract_v2 = load_contract_v2(data_root)
    facts = read_facts(data_root)
    provenance: dict[str, Any] = {"frame_mode": frame_mode, "knowledge_cutoff": knowledge_cutoff}
    bundle = assemble_candidate_bundle(
        data_root, contract=contract_v2, macro_facts=facts,
        candidate_id="C1", knowledge_cutoff=knowledge_cutoff,
        frame_mode=frame_mode, provenance=provenance,
    )
    tolerated = {"dfm_origin_cache_incomplete"}
    blocking = [item for item in bundle.missing_features if item not in tolerated]
    if blocking or not bundle.dates:
        raise V15BundleError(
            f"V2 C1 bundle unavailable: {', '.join(blocking) or 'insufficient sessions'}"
        )
    if truncate_at is not None:
        bundle = truncate_bundle(bundle, last_date=str(truncate_at))
        if not bundle.dates or bundle.dates[-1] > str(truncate_at):
            raise V15BundleError("설계창 절단 실패")
        expected_end = f"{truncate_at}T23:59:59+00:00"
    else:
        expected_end = f"{bundle.dates[-1]}T23:59:59+00:00"
    expected = set(macro_release_cutoffs(facts, start="2007-01-01", end=expected_end))
    ready = {
        str(row["cutoff"]) for row in read_dfm_manifest(data_root)
        if row.get("contract_hash") == frozen_hash_v2(contract_v2)
        and row.get("status") == "ready"
    }
    missing_cutoffs = sorted(expected - ready)
    if not expected or missing_cutoffs:
        raise V15BundleError(f"DFM cache incomplete: {len(missing_cutoffs)} cutoff(s) missing")
    if not np.isfinite(bundle.exogenous).all():
        raise V15BundleError("factor states contain gaps")
    provenance["dates"] = {"first": bundle.dates[0], "last": bundle.dates[-1], "count": len(bundle.dates)}
    return bundle, provenance
