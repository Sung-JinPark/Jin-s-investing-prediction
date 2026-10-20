"""Refresh personal research charts from public HTML, without public data delivery.

Use --raw and --receipt to replay the earlier capture, or --fetch to acquire the
same public history page. All vendor originals and derived prices stay beneath
outputs/. The normal approved-source publisher is deliberately not called.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from ai_fc.trendlines import contracts as C, research as R, storage as S, full_history as F, critical as K, representative as V, long_boundaries as B


def private_root(output: Path) -> Path:
    container = PROJECT.resolve() / "outputs"
    if container.resolve() != container:
        raise C.TrendlinesError("private chart outputs container must not redirect outside the checkout")
    output = output.resolve()
    if not output.is_relative_to(container):
        raise C.TrendlinesError("private chart output must stay below this checkout's outputs directory")
    destinations = [C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE, K.POLICY_RELATIVE, V.POLICY_RELATIVE, B.POLICY_RELATIVE,
                    R.ROOT, R.ROOT / "raw", R.ROOT / "receipts", R.ROOT / "snapshots",
                    R.ROOT / "failures", R.ROOT / "latest.json",
                    F.ROOT, F.ROOT / "snapshots", F.ROOT / "exports", F.ROOT / "latest.json",
                    K.ROOT, K.ROOT / "snapshots", K.ROOT / "exports", K.ROOT / "latest.json",
                    V.ROOT, V.ROOT / "snapshots", V.ROOT / "exports", V.ROOT / "latest.json",
                    B.ROOT, B.ROOT / "snapshots", B.ROOT / "exports", B.ROOT / "latest.json",
                    Path("outputs/trendlines/.writer.lock")]
    if any(not (output / path).resolve().is_relative_to(output) for path in destinations):
        raise C.TrendlinesError("private chart output contains a redirected data path")
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE, K.POLICY_RELATIVE, V.POLICY_RELATIVE, B.POLICY_RELATIVE):
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            shutil.copyfile(PROJECT / relative, target)
    return output


def public_page(asset_id: str) -> tuple[bytes, dict]:
    symbol = R.SYMBOLS[asset_id]
    end = datetime.now(timezone.utc)
    start = datetime(2022, 7, 1, tzinfo=timezone.utc)
    url = ("https://finance.yahoo.com/quote/" + quote(symbol, safe="")
           + "/history/?period1=" + str(int(start.timestamp())) + "&period2=" + str(int(end.timestamp())))
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    with urlopen(request, timeout=30) as response:
        raw = response.read(R.MAX_RAW_BYTES + 1)
        if len(raw) > R.MAX_RAW_BYTES:
            raise C.TrendlinesError("personal public history response exceeds the raw size budget")
        receipt = {"url": response.geturl(), "http_status": response.status, "bytes": len(raw),
                   "sha256": hashlib.sha256(raw).hexdigest(),
                   "retrieved_at": datetime.now(timezone.utc).isoformat()}
    return raw, receipt


def run(options) -> dict:
    # Keep the whole-store source/lineage guards while replaying only this
    # asset's arithmetic. A slow unrelated model must not starve the last asset.
    cache = R._ACTIVE_REPLAY_CACHE.get() or R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache), R.use_asset_replay_scope(options.asset):
        return _run(options)


def _run(options) -> dict:
    root = private_root(options.out)
    if options.fetch:
        if options.raw or options.receipt:
            raise C.TrendlinesError("choose public HTML acquisition or an existing raw/receipt pair")
        raw, receipt = public_page(options.asset)
    else:
        if not options.raw or not options.receipt:
            raise C.TrendlinesError("--raw and --receipt are both required unless --fetch is explicit")
        raw = options.raw.read_bytes()
        receipt = json.loads(options.receipt.read_text(encoding="utf-8"))
    acquired = receipt.get("retrieved_at", receipt.get("fetched_at"))
    result = R.capture_html(root, options.asset, raw, receipt, as_of=acquired,
                            allow_rejected_rows=options.allow_rejected_rows)
    audit = R.verify(root, replay=True)
    if not audit["ok"]:
        raise C.TrendlinesError("private original-to-chart replay failed: " + "; ".join(audit["errors"]))
    exported = R.export_private_import(root, options.asset)
    # A full-series failure is isolated from a valid current-range export.
    # Source corruption still prevents publication at the final replay gate.
    try:
        full = F.refresh(root, options.asset, now=acquired)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        full = {"status": "unavailable", "error": str(exc)[:256], "changed": False}
    try:
        if full.get("status") == "unavailable":
            raise C.TrendlinesError("critical full candidate source is unavailable")
        critical = K.refresh(root, options.asset, now=acquired)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        critical = {"status": "unavailable", "error": str(exc)[:256], "changed": False}
    try:
        if full.get("status") == "unavailable":
            raise C.TrendlinesError("representative full source is unavailable")
        representative = V.refresh(root, options.asset, now=acquired)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        representative = {"status": "unavailable", "error": str(exc)[:256], "changed": False}
    try:
        if representative.get("status") == "unavailable":
            raise C.TrendlinesError("long boundaries representative source is unavailable")
        long_boundaries = B.refresh(root, options.asset, now=acquired)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        long_boundaries = {"status": "unavailable", "error": str(exc)[:256], "changed": False}
    audit = R.verify(root, replay=True)
    if not audit["ok"]:
        raise C.TrendlinesError("private original-to-chart replay failed: " + "; ".join(audit["errors"]))
    destination = root / (options.asset + ".trendlines.json")
    S.atomic_json(destination, exported)
    return {**result, "publication_scope": "private_only", "public_prices_published": False,
            "independent_replay": audit, "browser_import_file": str(destination),
            "import_file_bytes": destination.stat().st_size, "full_history": full, "critical": critical,
            "representative": representative, "long_boundaries": long_boundaries}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", choices=tuple(R.SYMBOLS), default="sk-hynix")
    parser.add_argument("--out", type=Path, default=PROJECT / "outputs/trendlines/private-research-view")
    parser.add_argument("--fetch", action="store_true", help="Read the public HTML page, without a pricing API or key")
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--allow-rejected-rows", action="store_true",
                        help="Explicitly leave invalid research OHLC rows as auditable gaps; never repair them")
    options = parser.parse_args()
    try:
        print(json.dumps(run(options), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, "개인 추세선 갱신 중단: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
