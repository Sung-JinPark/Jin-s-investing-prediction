import copy

import pytest

from ai_fc.timeseries_v7_r5.contract_freeze import (
    EXPECTED_GRID_HASH,
    EXPECTED_ROLE_HASHES,
    ROLE_ORDER,
    digest,
    verify_frozen_identities,
)


def _fixture():
    role_origins = {role: [f"{role}-origin"] for role in ROLE_ORDER}
    role_hashes = {role: digest(rows) for role, rows in role_origins.items()}
    coordinates = [["2020-01-03", 1], ["2020-01-03", 5]]
    export = {"five_role_plan": {
        "role_order": list(ROLE_ORDER), "role_origins": role_origins, "role_hashes": role_hashes,
    }}
    g0 = {
        "coordinate_sample_identity": [
            {"origin_session": row[0], "horizon_sessions": row[1]} for row in coordinates
        ],
        "source": {"evaluation_coordinate_grid_hash": digest(coordinates)},
    }
    g3 = {
        "role_hashes": role_hashes,
        "frozen_evaluation": {"evaluation_coordinate_grid_hash": digest(coordinates)},
    }
    return export, g0, g3, role_hashes, digest(coordinates)


def test_frozen_identity_accepts_exact_recomputed_metadata(monkeypatch) -> None:
    export, g0, g3, roles, grid = _fixture()
    monkeypatch.setattr("ai_fc.timeseries_v7_r5.contract_freeze.EXPECTED_ROLE_HASHES", roles)
    monkeypatch.setattr("ai_fc.timeseries_v7_r5.contract_freeze.EXPECTED_GRID_HASH", grid)
    result = verify_frozen_identities(export=export, g0=g0, g3=g3)
    assert result["role_hashes_match"] is True
    assert result["evaluation_coordinate_grid_hash_match"] is True
    assert result["outer_outcomes_read"] == 0
    assert result["row_use_counters"]["outer_rows_used"] == 0


def test_frozen_identity_rejects_role_origin_mutation(monkeypatch) -> None:
    export, g0, g3, roles, grid = _fixture()
    monkeypatch.setattr("ai_fc.timeseries_v7_r5.contract_freeze.EXPECTED_ROLE_HASHES", roles)
    monkeypatch.setattr("ai_fc.timeseries_v7_r5.contract_freeze.EXPECTED_GRID_HASH", grid)
    changed = copy.deepcopy(export)
    changed["five_role_plan"]["role_origins"]["train"].append("new-origin")
    with pytest.raises(ValueError, match="role hashes"):
        verify_frozen_identities(export=changed, g0=g0, g3=g3)


def test_frozen_identity_rejects_coordinate_mutation(monkeypatch) -> None:
    export, g0, g3, roles, grid = _fixture()
    monkeypatch.setattr("ai_fc.timeseries_v7_r5.contract_freeze.EXPECTED_ROLE_HASHES", roles)
    monkeypatch.setattr("ai_fc.timeseries_v7_r5.contract_freeze.EXPECTED_GRID_HASH", grid)
    changed = copy.deepcopy(g0)
    changed["coordinate_sample_identity"][0]["horizon_sessions"] = 21
    with pytest.raises(ValueError, match="grid hash"):
        verify_frozen_identities(export=export, g0=changed, g3=g3)


def test_registered_hash_constants_remain_frozen() -> None:
    assert EXPECTED_GRID_HASH == "1f2403b7b15c100741a29816304056c2ad7b91cd777b29534a96a567068fa7e8"
    assert set(EXPECTED_ROLE_HASHES) == set(ROLE_ORDER)
