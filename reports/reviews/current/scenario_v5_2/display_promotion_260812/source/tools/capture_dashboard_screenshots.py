"""Capture the static dashboard with Playwright and emit auditable render evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import Page, sync_playwright


VIEWPORTS = {
    "1280": {"width": 1280, "height": 900},
    "390": {"width": 390, "height": 844},
}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _routes(data: dict) -> list[tuple[str, str]]:
    questions = data.get("questions") or []
    question_id = quote(str(questions[0]["id"]), safe="") if questions else None
    rows = [
        ("today", "#today"),
        ("future-default", "#future"),
        ("future-research", "#future/research"),
        ("future-champion", "#future/champion"),
        ("future-history", "#future/history"),
        ("future-cross-asset", "#future/cross-asset"),
        ("future-ai-regime", "#future/ai-regime"),
        ("future-liquidity", "#future/liquidity"),
        ("future-lookup", "#future/lookup"),
        ("statistics", "#statistics"),
        ("records", "#records"),
        ("records-performance", "#records/performance"),
        ("records-journal", "#records/journal"),
        ("trust", "#trust"),
    ]
    rows.append((
        "records-question",
        f"#records/question/{question_id}" if question_id else "#records",
    ))
    return rows


def _inspect(page: Page) -> dict:
    return page.evaluate(r"""() => {
      const app = document.getElementById('app');
      const banner = document.querySelector('[data-display-promotion-banner="persistent"]');
      const root = document.documentElement;
      const body = document.body;
      return {
        title: document.title,
        h1: app?.querySelector('h1')?.textContent?.trim() || null,
        body_view: body?.dataset?.view || null,
        app_text_length: app?.innerText?.length || 0,
        persistent_banner_visible: !!banner && !!(banner.offsetWidth || banner.offsetHeight),
        persistent_banner_text: banner?.innerText?.replace(/\s+/g, ' ').trim() || null,
        horizontal_overflow_px: Math.max(root.scrollWidth - root.clientWidth, body.scrollWidth - body.clientWidth),
        scenario_p50_paths: app?.querySelectorAll('[data-scenario-p50]').length || 0,
        forecast_observation_count: (() => {
          const path = app?.querySelector('[data-scenario-p50="S1"]');
          return path ? (path.getAttribute('d')?.match(/[ML]/g) || []).length : 0;
        })(),
      };
    }""")


def capture(site: Path, output: Path, proof_path: Path) -> dict:
    data = json.loads((site / "data.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    handler = partial(QuietHandler, directory=str(site))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    rows = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser_version = browser.version
            for route_name, route_hash in _routes(data):
                for viewport_name, viewport in VIEWPORTS.items():
                    context = browser.new_context(
                        viewport=viewport,
                        device_scale_factor=1,
                        reduced_motion="reduce",
                    )
                    page = context.new_page()
                    console_errors: list[str] = []
                    page_errors: list[str] = []
                    page.on(
                        "console",
                        lambda message, errors=console_errors: (
                            errors.append(message.text) if message.type == "error" else None
                        ),
                    )
                    page.on(
                        "pageerror",
                        lambda error, errors=page_errors: errors.append(str(error)),
                    )
                    page.goto(
                        f"{base_url}/{route_hash}",
                        wait_until="networkidle",
                        timeout=45_000,
                    )
                    page.locator("#app h1").first.wait_for(
                        state="visible", timeout=30_000,
                    )
                    if route_name == "future-research":
                        page.locator(
                            '[data-display-promotion-banner="persistent"]'
                        ).wait_for(state="visible", timeout=30_000)
                    metrics = _inspect(page)
                    target = output / f"{route_name}__{viewport_name}.png"
                    page.screenshot(
                        path=str(target), full_page=True, animations="disabled",
                    )
                    rows.append({
                        "route": route_hash,
                        "route_name": route_name,
                        "viewport": viewport_name,
                        "viewport_pixels": viewport,
                        "file": target.name,
                        "sha256": _sha256(target),
                        "bytes": target.stat().st_size,
                        "console_errors": console_errors,
                        "page_errors": page_errors,
                        **metrics,
                    })
                    context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    semantic_reference = (data.get("scenario_v5_2") or {}).get(
        "semantic_reference"
    ) or {}
    research_rows = [row for row in rows if row["route_name"] == "future-research"]
    proof = {
        "schema_version": 1,
        "capture_backend": "playwright_bundled_chromium",
        "persistent_banner_visible": (
            len(research_rows) == 2
            and all(row["persistent_banner_visible"] for row in research_rows)
        ),
        "viewports": sorted(row["viewport"] for row in research_rows),
        "route": "#future/research",
        "semantic_reference": semantic_reference,
        "screenshots": [row["file"] for row in research_rows],
    }
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    failures = [
        row for row in rows
        if row["page_errors"] or row["console_errors"]
        or not row["h1"] or row["horizontal_overflow_px"] > 2
    ]
    manifest = {
        "schema_version": 1,
        "capture_backend": "playwright_bundled_chromium",
        "playwright_version": version("playwright"),
        "browser_version": browser_version,
        "site": str(site.resolve()),
        "route_count": len(_routes(data)),
        "viewport_count": len(VIEWPORTS),
        "capture_count": len(rows),
        "gate_pass": len(rows) == 30 and not failures and proof[
            "persistent_banner_visible"
        ],
        "failures": failures,
        "captures": rows,
    }
    manifest_path = output / "render_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", type=Path, default=Path("_site"))
    parser.add_argument(
        "--output", type=Path,
        default=Path(
            "reports/reviews/current/scenario_v5_2/display_promotion_260812/"
            "screenshots"
        ),
    )
    parser.add_argument(
        "--proof", type=Path,
        default=Path(
            "reports/reviews/current/scenario_v5_2/display_promotion_260812/"
            "evidence/render_proof.json"
        ),
    )
    args = parser.parse_args()
    manifest = capture(args.site, args.output, args.proof)
    print(json.dumps({
        "gate_pass": manifest["gate_pass"],
        "capture_count": manifest["capture_count"],
        "failures": len(manifest["failures"]),
    }))
    return 0 if manifest["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
