"""Exercise the trendline renderer with conspicuously synthetic, disposable input."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import threading
from datetime import date, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from ai_fc import dashboard


def fixture_projection(*, engine_fit=False):
    bars = []
    day = date(2023, 1, 2)
    while len(bars) < 780:
        if day.weekday() < 5:
            i = len(bars)
            close = 800000 * math.exp(i * .0007 + .035 * math.sin(i / 13))
            opening = close * (1 + .004 * math.sin(i / 3))
            bars.append({"session": day.isoformat(), "session_date": day.isoformat(), "session_index": i,
                         "open": opening, "close": close, "high": max(opening, close) * 1.008,
                         "low": min(opening, close) * .992})
        day += timedelta(days=1)
    analyses = {}
    for scale in ("linear", "log"):
        analyses[scale] = {}
        for period in (63, 252, 756):
            lines = []
            for side, first, second in (("support", len(bars) - period + 2, len(bars) - 15),
                                        ("resistance", len(bars) - period + 6, len(bars) - 8)):
                field = "low" if side == "support" else "high"
                p1, p2 = bars[first][field], bars[second][field]
                transform = math.log if scale == "log" else lambda value: value
                origin = first
                intercept = transform(p1)
                slope = (transform(p2) - intercept) / (second - first)
                price = lambda index: math.exp(intercept + slope * (index - origin)) if scale == "log" else intercept + slope * (index - origin)
                indices = [first, second, len(bars) - 1, len(bars), len(bars) + 4, len(bars) + 20]
                lines.append({"line_id": f"fixture-{scale}-{period}-{side}", "side": side,
                              "direction": "rising" if slope > 0 else "falling", "state": "active",
                              "geometry_status": "confirmed", "coordinate_origin_index": origin,
                              "intercept": intercept, "slope": slope, "current_price": price(len(bars) - 1),
                              "touch_count": 3, "rank": 1,
                              "first_anchor": {"session": bars[first]["session"], "index": first, "price": p1},
                              "second_anchor": {"session": bars[second]["session"], "index": second, "price": p2},
                              "points": [{"session": (day + timedelta(days=max(0, index - len(bars)))).isoformat() if index >= len(bars) else bars[index]["session"],
                                          "index": index, "price": price(index), "future": index >= len(bars)} for index in indices]})
            border = lambda line: {"line_id": line["line_id"], "price": line["current_price"], "state": line["state"],
                                   "side": line["side"], "direction": line["direction"], "geometry_status": line["geometry_status"], "touch_count": 3}
            analyses[scale][str(period)] = {"status": "ready", "reason_codes": [], "lines": lines,
                                           "borders": {"down": sorted([border(line) for line in lines if line["current_price"] < bars[-1]["close"]], key=lambda row: -row["price"]),
                                                       "up": sorted([border(line) for line in lines if line["current_price"] >= bars[-1]["close"]], key=lambda row: row["price"]), "broken": []}}
    detail = {"schema_version": 1, "asset_id": "sk-hynix", "status": "ready", "fixture_only": True,
              "snapshot_id": "fixture-rendering-only", "as_of": bars[-1]["session"] + "T22:00:00+00:00",
              "bars": bars, "analyses": analyses, "source_identity": {"price_basis": "split_adjusted", "source_id": "synthetic_fixture"}}
    if engine_fit:
        from copy import deepcopy
        from ai_fc.trendlines import contracts as C, engine as E
        asset = deepcopy(C.load_asset_registry(PROJECT)["sk-hynix"])
        asset.update(enabled=True, source_id="synthetic_fixture", name="검토용 가상 SK하이닉스")
        policy = {"sources": {"synthetic_fixture": {"rights_status": "approved_free", "allow_collection": True,
                  "allow_derived_display": True, "allow_ohlc": True, "asset_ids": ["sk-hynix"],
                  "allowed_price_bases": [asset["price_basis"]], "calendar_ids": [asset["calendar_id"]],
                  "allowed_domains": ["fixture.invalid"], "parser_id": "json_ohlc_v1", "adjustment_method": "split_only",
                  "adjustment_vintage_guarantee": True}}}
        sessions = C.session_schedule(asset["calendar_id"], "2023-01-02", "2026-10-12")[:len(bars)]
        engine_bars = []
        for i, (session, _opened, closed) in enumerate(sessions):
            available = (closed + timedelta(minutes=20)).isoformat()
            low = 800000 + i * 800 + abs(i % 26 - 13) * 6000
            engine_bars.append({"open": low + 10000, "high": low + 40000, "low": low, "close": low + 20000,
                                "bar_id": f"fixture-bar-{i}", "asset_id": "sk-hynix", "source_id": "synthetic_fixture", "session_date": session,
                                "currency": asset["currency"], "unit": asset["unit"], "price_basis": asset["price_basis"],
                                "calendar_id": asset["calendar_id"], "available_at": available, "fetched_at": available, "finalized_at": closed.isoformat(),
                                "revision_seq": 1, "supersedes_bar_id": None, "receipt_id": f"fixture-receipt-{i}", "raw_sha256": C.canonical_hash({"fixture": i})})
        cutoff = (C.aware_time(engine_bars[-1]["available_at"]) + timedelta(minutes=10)).isoformat()
        snapshot = E.build_asset_snapshot(asset, engine_bars, cutoff, source_policy=policy)
        verified = E.verify_asset_snapshot(snapshot, engine_bars, asset, source_policy=policy)
        if snapshot["status"] != "ready" or not verified["ok"]:
            raise ValueError(f"Synthetic engine fixture did not pass: {verified}")
        from ai_fc.trendlines.display import compact_snapshot
        detail = compact_snapshot(snapshot)
        detail['fixture_only'] = True
        bars = detail["bars"]
    detail["content_hash"] = hashlib.sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()
    assets = []
    for asset_id, label in (("sk-hynix", "SK하이닉스"), ("soxx", "SOXX"), ("nasdaq", "나스닥 종합"),
                            ("sp500", "S&P 500"), ("bitcoin", "비트코인"), ("dow", "다우존스"), ("mag7", "빅테크 7")):
        assets.append({"asset_id": asset_id, "label": label, "currency": "KRW" if asset_id == "sk-hynix" else "USD",
                       "price_unit": "KRW" if asset_id == "sk-hynix" else "points",
                       "status": "ready" if asset_id == "sk-hynix" else "hold", "reason_codes": [] if asset_id == "sk-hynix" else ["missing_approved_ohlc"],
                       "snapshot_id": detail["snapshot_id"] if asset_id == "sk-hynix" else None,
                       "as_of": detail["as_of"] if asset_id == "sk-hynix" else None,
                       "last_session": bars[-1]["session"] if asset_id == "sk-hynix" else None,
                       "content_hash": detail["content_hash"] if asset_id == "sk-hynix" else None})
    return {"schema_version": 1, "contract_id": "trendlines_display_v1", "status": "partial", "generated_at": detail["as_of"],
            "assets": assets, "details": {"sk-hynix": detail}}


def build_preview(output: Path):
    model = {"meta": {"generated": "fixture", "phase": "FIXTURE", "n_questions": 0}, "questions": [],
             "forecast_history": {}, "resolutions": {}, "clusters": [], "scenario": {}, "trendlines": fixture_projection(engine_fit=True)}
    base, sidecars = dashboard.split_trendlines_data(model)
    output.mkdir(parents=True, exist_ok=True)
    html = dashboard.render_html(base, mode="embed")
    html = html.replace("</head>", '<script>if(!location.hash)location.hash="#future/trendlines/sk-hynix";</script></head>')
    (output / "index.html").write_text(html, encoding="utf-8")
    dashboard._write_trendlines_sidecars(sidecars, output)
    (output / "fixture_manifest.json").write_text(json.dumps({"fixture_only": True, "sidecar_bytes": (output / "trendlines/sk-hynix.json").stat().st_size,
                                                               "summary_bytes": len(json.dumps(base["trendlines"]).encode())}, indent=2), encoding="utf-8")
    return output / "index.html"


def build_research_preview(research_root: Path, output: Path):
    """Opt-in private display; the normal read model and Pages never attach research."""
    from ai_fc.trendlines import display, research
    research_root, output = research_root.resolve(), output.resolve()
    if not output.is_relative_to(research_root):
        raise ValueError("private research preview must remain inside its local research root")
    projection = research.attach_projection(research_root, display.load_projection(research_root), allow_private_research=True)
    if not any(row['status'] == 'unverified_display' for row in projection['assets']):
        raise ValueError("no replayed private research snapshot is available")
    model = {"meta": {"generated": projection.get("generated_at"), "phase": "개인 연구", "n_questions": 0},
             "questions": [], "forecast_history": {}, "resolutions": {}, "clusters": [], "scenario": {},
             "trendlines": projection}
    base, sidecars = dashboard.split_trendlines_data(model)
    output.mkdir(parents=True, exist_ok=True)
    html = dashboard.render_html(base, mode="embed")
    html = html.replace("</head>", '<meta name="robots" content="noindex,nofollow"><script>if(!location.hash)location.hash="#future/trendlines/sk-hynix";</script></head>')
    (output / "index.html").write_text(html, encoding="utf-8")
    (output / "data.json").write_text(json.dumps(base, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding="utf-8")
    dashboard._write_trendlines_sidecars(sidecars, output)
    (output / "private_preview_manifest.json").write_text(json.dumps({
        "private_research_only": True, "public_export_allowed": False,
        "official_forecast_write": False, "summary_bytes": len(json.dumps(base['trendlines'], ensure_ascii=False, separators=(',', ':')).encode()),
        "assets": [{"asset_id": asset, "sidecar_bytes": (output / f'trendlines/{asset}.json').stat().st_size} for asset in sidecars],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return output / 'index.html'


def build_local_service_preview(research_root: Path, output: Path):
    """Private loopback shell; candle values arrive through verified import GETs.

    The shell carries the ordinary approved-source HOLD summary. It neither
    embeds private prices nor replays the immutable history on every startup.
    """
    from ai_fc.trendlines import display, storage
    from ai_fc.trendlines.local_service import _atomic_bytes
    research_root, output = research_root.resolve(), output.resolve()
    if not output.is_relative_to(research_root):
        raise ValueError("local service preview must remain inside its research root")
    projection = display.load_projection(research_root)
    model = {"meta": {"generated": datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
                      "phase": "개인 연구 자동갱신", "n_questions": 0},
             "questions": [], "forecast_history": {}, "resolutions": {}, "clusters": [],
             "scenario": {}, "trendlines": projection}
    base, sidecars = dashboard.split_trendlines_data(model)
    if sidecars:
        raise ValueError("local service shell must not embed private research candles")
    output.mkdir(parents=True, exist_ok=True)
    html = dashboard.render_html(base, mode='embed')
    html = html.replace('</head>', '<meta name="robots" content="noindex,nofollow"><script>if(!location.hash)location.hash="#future/trendlines/sk-hynix";</script></head>')
    # Replace each bounded file atomically. A stale HTML/script generation pair
    # is rejected by the existing bundle SHA check and can be retried safely.
    for suffix in ('js', 'css'):
        target = (output / f'assets/trendlines.{suffix}').resolve()
        if not target.is_relative_to(output):
            raise ValueError('local preview asset path redirected')
        _atomic_bytes(target, (dashboard.DASHBOARD_PARTS / f'trendlines.{suffix}').read_bytes())
    _atomic_bytes(output / 'data.json', storage.encode(base))
    _atomic_bytes(output / 'index.html', html.encode('utf-8'))
    storage.atomic_json(output / 'private_preview_manifest.json', {
        'private_research_only': True, 'public_export_allowed': False,
        'official_forecast_write': False, 'prices_via': 'read_only_private_import_api',
        'summary_bytes': len(storage.encode(base['trendlines'])), 'embedded_private_prices': False,
    })
    return output / 'index.html'


def capture_preview(output: Path, *, research=False):
    from playwright.sync_api import sync_playwright
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(output.resolve())))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    results = []
    try:
        with sync_playwright() as runtime:
            chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
            browser = runtime.chromium.launch(headless=True, channel="chrome" if chrome.is_file() else None)
            for width, height in ((1280, 900), (390, 844)):
                context = browser.new_context(viewport={"width": width, "height": height}, reduced_motion="reduce", has_touch=width == 390)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/#future/trendlines/sk-hynix", wait_until="networkidle")
                svg = page.locator('.trend-chart svg')
                svg.wait_for(state="visible")
                assert page.locator('[data-trend-bar]').count() == 63
                assert page.locator('.trend-fixture').count() == (0 if research else 1)
                if research:
                    assert page.locator('.trend-data-meta').count() == 1
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), "body overflow"
                linear_points = page.locator('[data-trend-projection]').first.get_attribute('points')
                page.get_by_role('button', name='로그', exact=True).click()
                assert page.locator('[data-trend-projection]').first.get_attribute('points') != linear_points
                page.get_by_role('button', name='1년', exact=True).click()
                assert page.locator('[data-trend-bar]').count() == 252
                page.get_by_role('button', name='3년', exact=True).click()
                assert page.locator('[data-trend-bar]').count() == 756
                page.get_by_role('button', name='3개월', exact=True).click()
                page.get_by_role('button', name='선형', exact=True).click()
                svg.focus()
                before = page.locator('[data-trend-readout]').inner_text()
                page.keyboard.press('ArrowLeft')
                assert page.locator('[data-trend-readout]').inner_text() != before
                box = svg.bounding_box()
                if width == 390:
                    page.touchscreen.tap(box['x'] + box['width'] * .5, box['y'] + box['height'] * .4)
                else:
                    page.mouse.move(box['x'] + box['width'] * .5, box['y'] + box['height'] * .4)
                assert page.locator('[data-trend-readout]').inner_text()
                page.evaluate('document.activeElement?.blur(); window.scrollTo(0,0)')
                page.wait_for_function("document.querySelector('.skip-link').getBoundingClientRect().bottom < 0")
                page.screenshot(path=str(output / f'trendlines__{width}.png'), full_page=True)
                page.get_by_role('link', name='SOXX', exact=True).click()
                assert page.locator('.trend-empty').count() == 1
                assert page.locator('.trend-chart svg').count() == 0
                assert not errors, errors
                results.append({"width": width, "page_errors": errors, "period_counts": [63, 252, 756], "keyboard_and_pointer": True, "hold_without_chart": True, "overflow": False})
                context.close()
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            original_script = (output / 'assets/trendlines.js').read_bytes()
            page.route('**/assets/trendlines.js', lambda route: route.fulfill(body=original_script + b'\n/* mismatched deployment fixture */', content_type='text/javascript'))
            page.goto(f"http://127.0.0.1:{server.server_port}/#future/trendlines/sk-hynix", wait_until='networkidle')
            page.get_by_role('heading', name='추세선을 불러오지 못했습니다', exact=True).wait_for(state='visible')
            assert page.locator('.trend-chart svg').count() == 0
            page.unroute('**/assets/trendlines.js')
            page.get_by_role('button', name='다시 불러오기', exact=True).click()
            page.locator('.trend-chart svg').wait_for(state='visible')
            results.append({'integrity_failure_blocked': True, 'retry_recovers_original_bundle': True})
            context.close()
            browser.close()
    finally:
        server.shutdown()
        worker.join(10)
        server.server_close()
    (output / 'browser_checks.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--research-root', type=Path, help='Explicit local-only public-HTML research root; writes its private site subdirectory')
    parser.add_argument('--capture', action='store_true')
    options = parser.parse_args()
    output = options.out or (options.research_root / 'site' if options.research_root else PROJECT / 'outputs/trendlines_preview')
    print((build_research_preview(options.research_root, output) if options.research_root else build_preview(output)).resolve())
    if options.capture:
        capture_preview(output, research=bool(options.research_root))
