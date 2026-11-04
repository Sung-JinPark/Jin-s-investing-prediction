import importlib.util
import json
from pathlib import Path
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("diagnostic", ROOT / "tools/diagnose_alfred_inventory.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def test_error_report_preserves_status_and_redacts_credential(monkeypatch):
    import io
    def denied(url, timeout):
        raise urllib.error.HTTPError(url, 500, "server", {}, io.BytesIO(
            json.dumps({"error_message": "key=fixture-secret failed"}).encode()))
    monkeypatch.setattr(M.urllib.request, "urlopen", denied)
    r = M.probe("M2SL", "2026-10-28", "9999-12-31", "fixture-secret")
    assert r["status"] == 500 and len(r["raw_sha256"]) == 64
    assert "fixture-secret" not in json.dumps(r)
    assert "REDACTED" in r["response"]["error_message"]


def test_numeric_inventory_response_is_reported_without_source_writes(monkeypatch):
    import io
    class Response(io.BytesIO):
        status = 200
    monkeypatch.setattr(M.urllib.request, "urlopen", lambda *a, **kw:
                        Response(b'{"count":1,"vintage_dates":["2026-10-27"]}'))
    r = M.probe("M2SL", "2025-11-03", "9999-12-31", "fixture-secret")
    assert r["status"] == 200 and r["response"]["vintage_dates"] == ["2026-10-27"]
