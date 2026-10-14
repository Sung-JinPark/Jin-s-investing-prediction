"""Run the user's private loopback updater with the existing Python runtime.

The worker reads public history HTML on startup and at KST 07:17/09:17/16:17.
HTTP is read-only and never starts work, accepts commands, or serves originals.
"""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import SimpleNamespace

import refresh_private_trendlines as updater
import preview_trendlines as preview
from ai_fc.trendlines import research as R
from ai_fc.trendlines.local_service import LocalTrendlinesService, make_http_server


def run(options) -> None:
    root = updater.private_root(options.out)
    logger = logging.getLogger("private-trendlines")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(root / "local-service.log", maxBytes=2 * 1024 * 1024,
                                 backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    replay_cache = R.VerifiedReplayCache()

    def refresh_asset(asset_id):
        try:
            with R.use_verified_replay_cache(replay_cache):
                report = updater.run(SimpleNamespace(asset=asset_id, out=root, fetch=True, raw=None,
                                                    receipt=None, allow_rejected_rows=True))
        except Exception:
            logger.exception("Private source refresh failed for %s", asset_id)
            raise
        logger.info("Private refresh %s", json.dumps({key: report.get(key) for key in
                    ("asset_id", "changed", "snapshot_id", "observation_through", "bars")}, ensure_ascii=False))
        if report.get("full_history", {}).get("status") == "unavailable":
            logger.warning("Full-series refresh unavailable for %s: %s", asset_id,
                           report["full_history"].get("error", "full_refresh_failed"))
        if report.get("critical", {}).get("status") == "unavailable":
            logger.warning("Critical selection unavailable for %s: %s", asset_id,
                           report["critical"].get("error", "critical_refresh_failed"))
        return report

    def build_preview():
        try:
            return preview.build_local_service_preview(root, root / "site")
        except ValueError:
            # An empty first installation still has the read-only status API.
            logger.exception("Private preview not yet available")
            return None

    # Existing captured evidence can be opened before the first network cycle.
    build_preview()
    service = LocalTrendlinesService(root, refresh_asset=refresh_asset, build_preview=build_preview,
                                    assets=tuple(options.assets), startup_refresh=not options.no_startup_refresh)
    server = make_http_server(service, port=options.port)
    logger.info("Loopback updater started on 127.0.0.1:%s; private-only assets=%s", options.port, options.assets)
    service.start()
    try:
        server.serve_forever(poll_interval=.5)
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
        server.server_close()
        logger.info("Loopback updater stopped")
        logger.removeHandler(handler)
        handler.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=updater.PROJECT / "outputs/trendlines/private-research-view")
    parser.add_argument("--port", type=int, choices=[8878], default=8878)
    parser.add_argument("--assets", nargs="+", choices=tuple(R.SYMBOLS), default=list(R.SYMBOLS))
    parser.add_argument("--no-startup-refresh", action="store_true",
                        help="Skip startup collection; scheduled daily slots still run")
    options = parser.parse_args()
    try:
        run(options)
    except (OSError, ValueError) as exc:
        parser.exit(1, "로컬 추세선 갱신기를 시작하지 못했습니다: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
