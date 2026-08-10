"""WS-2: 유사 사이클월 event → context payload 배선."""

from __future__ import annotations

from dualdb import db
from dualdb.export import context_bridge


def test_event_context_uses_only_nearby_past_events(tmp_path, monkeypatch) -> None:
    conn = db.connect(tmp_path / "dualdb.sqlite")
    rows = [
        ("dotcom", "1999-06-30", "fed", "Fed 인상 개시", 41.0),
        ("dotcom", "1999-11-01", "product", "Y2K 유동성 공급", 46.0),
        ("dotcom", "1997-10-27", "crash", "너무 먼 사건", 21.0),
        ("japan1989", "1988-08-01", "macro", "과열기 신용 팽창", 43.0),
        ("ai", "2026-07-01", "crash", "현재 시대 사건", 42.0),
    ]
    conn.executemany(
        """INSERT INTO event
           (era_id,date,type,title,cycle_month,source_url,note)
           VALUES (?,?,?,?,?,'https://example.test','fixture')""",
        rows)
    # 트윈 모델 격리 계약: context 빌드 전후 entity 표본은 읽거나 바꾸지 않는다.
    conn.execute(
        """INSERT INTO entity
           (era_id,ticker,name,status,is_twin)
           VALUES ('dotcom','NOTW','Not Twin','alive',0)""")
    conn.commit()

    analog = {
        "asof": "2026-07-31",
        "selected_eras": ["dotcom", "japan1989"],
        "pool_eras": ["dotcom", "japan1989"],
    }
    context = context_bridge._event_context(conn, analog)
    assert context is not None
    assert context["cycle_month"] == 42
    assert {e["title"] for e in context["events"]} == {
        "Fed 인상 개시", "Y2K 유동성 공급", "과열기 신용 팽창",
    }
    assert all(e["era"] != "ai" for e in context["events"])
    assert "너무 먼 사건" not in {e["title"] for e in context["events"]}
    assert "매핑 확률" in context["note"] and "트윈 표본 아님" in context["note"]

    monkeypatch.setattr(context_bridge, "_analog", lambda _conn: analog)
    payload = context_bridge.build_payload(conn)
    assert payload["event_context"] == context
    assert conn.execute(
        "SELECT COUNT(*) c FROM entity WHERE is_twin=0").fetchone()["c"] == 1
