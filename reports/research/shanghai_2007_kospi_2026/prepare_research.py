"""Preserve research inputs and a read-only boundary; never touches production data."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
AS_OF = "2026-10-16T09:00:00+09:00"
SOURCES = {
    "msci_acwi": "https://www.msci.com/indexes/index/892400/msci-acwi-index",
    "msci_korea": "https://www.msci.com/indexes/index/941000/msci-korea-index",
    "msci_china": "https://www.msci.com/indexes/index/302400/msci-china-index",
    "imf_2006_reform": "https://www.elibrary.imf.org/view/journals/002/2006/394/article-A001-en.xml",
    "imf_2007_rebalancing": "https://www.imf.org/external/pubs/ft/fandd/2007/09/aziz.htm",
    "bis_2007_capital_controls": "https://www.bis.org/publ/work233.pdf",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def fetch(item: tuple[str, str]) -> dict:
    key, url = item
    suffix = ".pdf" if url.endswith(".pdf") else ".html"
    path = ROOT / "context" / (key + suffix)
    record = {"id": key, "url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
              "role": "context_reference_not_historical_forecast_input", "available_at": None,
              "vintage": "retrieved snapshot; original publication and observation dates verified separately"}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 research archival"})
        with urllib.request.urlopen(req, timeout=25) as response:
            payload = response.read()
            record["content_type"] = response.headers.get("Content-Type")
            record["final_url"] = response.url
        path.write_bytes(payload)
        challenge = b"Challenge Validation" in payload or b"Just a moment" in payload
        record.update(path=str(path.relative_to(ROOT)), bytes=len(payload), sha256=digest(path),
                      status="access_challenge_payload_only" if challenge else "archived")
    except Exception as exc:
        record.update(status="unavailable", error=f"{type(exc).__name__}: {exc}")
    return record


def main() -> None:
    (ROOT / "context").mkdir(parents=True, exist_ok=True)
    baseline = ROOT / "protected_before.json"
    if not baseline.exists():
        tracked = subprocess.check_output(
            ["git", "ls-files", "-z", "src/ai_fc", "data/contracts", "forecasts", ".github", "README.md",
             "data/statistics/official_store/ledgers"], cwd=REPO).decode("utf-8").split("\0")
        hashes = {name: digest(REPO / name) for name in tracked if name and (REPO / name).is_file()}
        write_json(baseline, {"captured_at": datetime.now(timezone.utc).isoformat(), "sha256": hashes})
    attachments = [
        "codex-clipboard-e2001a52-b398-4d23-ba9d-1cb3120759ec.png",
        "codex-clipboard-11a904a2-2274-4eb1-8dfc-ce69c3b70acb.png",
        "codex-clipboard-827bae96-81eb-4ac7-a1dc-972d4c72fa8c.png",
    ]
    records = []
    for i, name in enumerate(attachments, 1):
        src = Path("C:/Users/91ssj/AppData/Local/Temp") / name
        dst = ROOT / "context" / f"user_chart_{i}.png"
        if src.exists() and not dst.exists():
            shutil.copyfile(src, dst)
        records.append({"id": f"user_chart_{i}", "path": str(dst.relative_to(ROOT)),
                        "sha256": digest(dst) if dst.exists() else None,
                        "role": "user_supplied_hypothesis_not_verified_time_series"})
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        sources = list(pool.map(fetch, SOURCES.items()))
    write_json(ROOT / "context" / "source_manifest.json", {"as_of": AS_OF, "sources": sources, "attachments": records})
    write_json(ROOT / "research_contract.json", {
        "as_of": AS_OF, "price_cutoff": "2026-10-15", "official_forecast": False,
        "scope": "independent research; no production model, API, database, ledger or site changes",
        "ratio_storage_unit": "fraction", "probabilities": None,
        "horizons_trading_sessions": [126, 252],
        "future_loss_event": "min(P[t]/P[as_of]-1) <= -0.20 over the specified future horizon",
        "future_max_drawdown": "min(P[t]/running_max(P[as_of:t])-1), distinct from loss versus origin",
        "primary_comparison": ["SSE Composite", "KOSPI"], "supplement": "SSE A Share",
        "alignment": "fixed 19 calendar years; 2006/2025 first trading close normalized to 100",
        "global_rank": "require common provider, contemporaneous ACWI country universe and earnings definition; otherwise unverified",
        "missing_data_policy": "null with reason; no clipping, interpolation, unit guessing or hidden normalization",
        "historical_information_policy": "later yearbooks describe outcomes; not available-at evidence for past decisions",
    })
    print(json.dumps({"protected_files": len(json.loads(baseline.read_text(encoding="utf-8"))["sha256"]),
                      "sources": [{"id": x["id"], "status": x["status"]} for x in sources]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
