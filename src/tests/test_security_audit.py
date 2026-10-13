from pathlib import Path

from ai_fc.security_audit import scan


def test_secret_scan_detects_key_shape_without_exposing_value(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("TOKEN = 'sk-" + "A" * 30 + "'\n", encoding="utf-8")
    assert scan(tmp_path) == ["sample.py:1"]


def test_secret_scan_ignores_environment_variable_names(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("key = os.environ['OPENAI_API_KEY']\n", encoding="utf-8")
    assert scan(tmp_path) == []


def test_secret_scan_does_not_match_sk_inside_public_url_slug(tmp_path: Path) -> None:
    source = tmp_path / "capture.html"
    source.write_text(
        '<a href="/analysis/the-leverage-risk-wall-street-can-afford-123">public</a>\n',
        encoding="utf-8",
    )
    assert scan(tmp_path) == []


def test_public_trendline_snapshot_id_does_not_hide_a_key(tmp_path: Path) -> None:
    source = tmp_path / "snapshot.json"
    public_id = "trendlines-sk-hynix-" + "a" * 24
    source.write_text('{"snapshot_id":"' + public_id + '"}\n', encoding="utf-8")
    assert scan(tmp_path) == []
    source.write_text(
        '{"snapshot_id":"' + public_id + '","token":"sk-' + "A" * 30 + '"}\n',
        encoding="utf-8",
    )
    assert scan(tmp_path) == ["snapshot.json:1"]


def test_snapshot_slug_is_exempt_only_in_the_exact_public_field(tmp_path: Path) -> None:
    source = tmp_path / "snapshot.json"
    source.write_text('{"token":"trendlines-sk-hynix-' + "a" * 24 + '"}\n', encoding="utf-8")
    assert scan(tmp_path) == ["snapshot.json:1"]
