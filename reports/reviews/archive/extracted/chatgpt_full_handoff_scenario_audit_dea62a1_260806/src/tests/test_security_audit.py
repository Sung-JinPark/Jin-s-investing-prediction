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
