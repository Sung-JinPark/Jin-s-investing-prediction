"""Save only public historical documents; never calls a securities/broker API."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
SOURCES = [
    ("sse_yearbook_2006", "SSE Statistical Yearbook 2006 (2005 observations)", "https://www.sse.com.cn/aboutus/publication/yearly/documents/c/10061088/files/02828bf648f9437c9468c28ee3858d3f.pdf", None, "2005-01-01/2005-12-31", "pdf"),
    ("sse_yearbook_2007", "SSE Statistical Yearbook 2007 (2006 observations)", "https://www.sse.com.cn/aboutus/publication/yearly/documents/c/10061087/files/5d57e51da9af4c2b946cc14811c6c4c3.pdf", None, "2006-01-01/2006-12-31", "pdf"),
    ("sse_yearbook_2008", "SSE Statistical Yearbook 2008 (2007 observations)", "https://www.sse.com.cn/aboutus/publication/yearly/documents/c/10061086/files/c6db3f91030b4533ad5bd85cb421b18e.pdf", None, "2007-01-01/2007-12-31", "pdf"),
    ("sse_yearbook_2009", "SSE Statistical Yearbook 2009 (2008 observations)", "https://www.sse.com.cn/aboutus/publication/yearly/documents/c/10061085/files/10093621bdad44b2aaf7fc39c85c9256.pdf", None, "2008-01-01/2008-12-31", "pdf"),
    ("sse_2007_earnings_review", "SSE summary of listed companies' 2007 annual reports", "https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988204.shtml", "2008-06-02", "2007-01-01/2007-12-31", "html"),
    ("sse_2007_earnings_review_en", "SSE Summary of 2007 Annual Reports (English)", "https://english.sse.com.cn/news/newsrelease/c/4946898.shtml", None, "2007-01-01/2007-12-31", "html"),
    ("csrc_retail_risk_20071018", "CSRC Vice Chairman Tu Guangshao on investor risk education", "https://www.csrc.gov.cn/csrc/c100028/c1002860/content.shtml", "2007-10-18", "2007-10-17", "html"),
    ("csrc_dormant_accounts_20071009", "CSRC dormant account segregation implementation", "https://www.csrc.gov.cn/csrc/c100028/c1002861/content.shtml", "2007-10-09", "2007-10-08", "html"),
    ("mof_stamp_duty_20070530", "MOF/SAT Caishui [2007] 84 securities stamp duty notice", "https://www.mofcom.gov.cn/zcfb/zgdwjjmywg/art/2007/art_99829a5529ff4223a7bf6ca48ffc4b24.html", "2007-07-04", "2007-05-30", "html"),
    ("mof_2007_revenue_review", "MOF analysis of 2007 fiscal revenue growth composition", "https://szs.mof.gov.cn/gongzuodongtai/200808/t20080815_63551.htm", "2008-03-05", "2007-01-01/2007-12-31", "html"),
    ("pbc_policy_2007q4", "PBC China Monetary Policy Report Quarter Four 2007", "https://www.pbc.gov.cn/eportal/fileDir/history_file/files/att_20306_1.pdf", "2008-02-22", "2007-01-01/2007-12-31", "pdf"),
    ("pbc_policy_2007q3_highlights", "PBC Highlights of China's Monetary Policy in Q3 2007", "https://www.pbc.gov.cn/english/130721/2025080815063195107/index.html", "2007-11-14", "2007-07-01/2007-09-30", "html"),
    ("pbc_rate_20070519", "PBC May 2007 rate and reserve requirement adjustment", "https://www.pbc.gov.cn/english/130721/2025080815063242147/index.html", "2007-06-04", "2007-05-19/2007-06-05", "html"),
    ("nbs_2007_communique", "NBS Statistical Communique on 2007 economic and social development", "https://www.stats.gov.cn/english/NewsEvents/200802/t20080228_25995.html", "2008-02-28", "2007-01-01/2007-12-31", "html"),
    ("wto_2008_trade_review", "WTO Press 520: Developing, transition economies cushion trade slowdown", "https://www.wto.org/english/news_e/pres08_e/pr520_e.htm", "2008-04-17", "2007-01-01/2007-12-31", "html"),
    ("wto_2008_trade_review_pdf", "WTO Press 520/Rev.1 dated 17 April 2008", "https://www.wto.org/english/news_e/pres08_e/pr520_e.pdf", "2008-04-17", "2007-01-01/2007-12-31", "pdf"),
    ("imf_2006_article_iv", "IMF China 2006 Article IV, nontradable share reform", "https://www.elibrary.imf.org/view/journals/002/2006/394/article-A001-en.xml", "2006-10-31", "2005-04/2006-04", "html"),
    ("imf_rebalancing_200709", "IMF Finance and Development: China's Rebalancing Act", "https://www.imf.org/external/pubs/ft/fandd/2007/09/aziz.htm", "2007-09", "2007", "html"),
    ("csrc_margin_pilot_20100108", "CSRC margin trading pilot and index futures approval", "https://www.csrc.gov.cn/csrc/c100028/c1002676/content.shtml", "2010-01-08", "2010-01-08", "html"),
]


def fetch(item):
    sid, title, url, published, data_period, ext = item
    result = {"source_id": sid, "title": title, "publisher": url.split('/')[2], "url": url,
              "published_at": published, "data_period": data_period,
              "published_at_note": "Original date where verified; null means not established. URL migration timestamps are not publication dates.",
              "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
              "local_path": f"sources/{sid}.{ext}", "source_kind": "official_document", "access": "public_unauthenticated"}
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (historical academic research)", "Accept": "*/*"})
        try:
            with urlopen(req, timeout=45) as resp:
                body = resp.read()
                result["resolved_url"] = resp.url
                result["http_status"] = resp.status
                result["content_type"] = resp.headers.get("Content-Type")
                result["transport"] = "python_urllib_default_tls_verification"
        except Exception as urllib_error:
            # Windows curl uses the Windows certificate store. Never turn off TLS verification.
            result["urllib_error"] = f"{type(urllib_error).__name__}: {urllib_error}"
            marker = b"\n__CURL_METADATA__"
            proc = subprocess.run(["curl.exe", "--location", "--fail", "--silent", "--show-error", "--max-time", "45", "--write-out", "\n__CURL_METADATA__%{http_code}|%{url_effective}|%{content_type}", url], capture_output=True, check=False)
            if proc.returncode:
                raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip())
            body, metadata = proc.stdout.rsplit(marker, 1)
            status, resolved, content_type = metadata.decode("utf8").split("|", 2)
            result.update(http_status=int(status), resolved_url=resolved, content_type=content_type, transport="curl_windows_schannel_default_tls_verification")
        if ext == "pdf" and not body.startswith(b"%PDF-"):
            raise ValueError("Expected PDF but response did not start with PDF signature")
        dest = ROOT / result["local_path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        result.update(status="saved", sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
    except Exception as exc:
        result.update(status="unavailable", error=f"{type(exc).__name__}: {exc}", local_path=None, sha256=None)
    return result


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(fetch, SOURCES))
    manifest = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "scope": "Public historical research documents; no APIs, authentication, keys, or broker access.",
                "sources": results}
    (ROOT / "source_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps([{k:s.get(k) for k in ("source_id", "status", "bytes", "error")} for s in results], indent=2))
