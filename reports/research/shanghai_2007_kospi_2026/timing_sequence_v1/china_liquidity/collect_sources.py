"""Retain historical public documents; no broker or quote API or credentials."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent.parent/"china"
JOBS=[
 ("CSRC_AR2007","https://www.csrc.gov.cn/csrc/c100024/c1492164/1492164/files/fded535cf23d451ab65c3f2786685950.pdf","2008",None),
 ("PBOC_DEC20_QA","https://www.gov.cn/zwhd/2007-12/20/content_839594.htm","2007-12-20",None),
 ("NDRC_MONETARY2008","https://www.ndrc.gov.cn/fzggw/jgsj/cjd/sjdt/200903/t20090303_1111305.html","2009-03-03",None),
 ("MOF_STAMP20080424","https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/200805/t20080519_29133.htm","2008-04-24",None),
 ("CSRC_OCT2007","https://www.csrc.gov.cn/csrc/c105936/c1004300/content.shtml",None,None),
 ("CSRC_MONTHLY_INDEX","https://www.csrc.gov.cn/csrc/c100120/common_list_11.shtml",None,None),
 ("CSDC_AR2006","https://www.chinaclear.cn/old_files/1192763915494.pdf",None,None),
 ("SIN_PBOC20071013","https://finance.sina.com.cn/china/hgjj/20071013/15064057871.shtml","2007-10-13",None),
 ("SIN_PBOC20071110","https://finance.sina.com.cn/g/20071110/23294160050.shtml","2007-11-10",None),
 ("THS_NEWACC20071122","https://fund.10jqka.com.cn/content/200711/24/1531989.shtml","2007-11-24",None),
 ("SIN_NEWACC20080111","https://finance.sina.com.cn/stock/data/20080114/17304402882.shtml","2008-01-14",None),
 ("XIN_RATE20071220","https://finance.sina.com.cn/g/20071220/19524318248.shtml","2007-12-20",None),
 ("XIN_CEWC20071205","https://finance.sina.com.cn/g/20071205/20214255429.shtml","2007-12-05",None),
 ("XIN_SURVEY2007Q4","https://finance.sina.com.cn/stock/t/20071221/11154321816.shtml","2007-12-21",None),
 ("SHNEWS_PREPEAK_NEWACC","https://finance.sina.com.cn/money/fund/20071017/03014067654.shtml","2007-10-17",None),
 ("CAIJING_ACTIVE20080118","https://finance.sina.com.cn/roll/20080124/09011958362.shtml","2008-01-24",None),
 ("SIN_NEWACC20070921","https://finance.sina.com.cn/stock/data/20070924/17554009437.shtml","2007-09-24",None),
 ("XIN_RRR20080116","https://finance.sina.com.cn/g/20080116/18024413676.shtml","2008-01-16",None),
]
REUSE=["pbc_policy_2007q4","pbc_policy_2007q3_highlights","pbc_rate_20070519","mof_stamp_duty_20070530","csrc_dormant_accounts_20071009","csrc_retail_risk_20071018","sse_yearbook_2008","sse_yearbook_2009"]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def fetch(job):
    sid,url,published,_=job
    path=ROOT/"raw"/(sid+(".pdf" if ".pdf" in url.lower() else ".html"))
    meta=dict(source_id=sid,url=url,published_date=published,local_path=path.relative_to(ROOT).as_posix(),
              retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),access="public unauthenticated historical document")
    try:
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=25) as r:
                payload=r.read();meta.update(http_status=r.status,resolved_url=r.url,transport="urllib_default_tls")
            path.write_bytes(payload)
        except Exception as exc:
            meta["urllib_error"]=str(exc)
            result=subprocess.run(["curl.exe","--fail","--location","--max-time","35","--silent","--show-error",url,"--output",str(path)],capture_output=True,text=True)
            if result.returncode:raise RuntimeError(result.stderr.strip())
            meta.update(http_status=200,transport="curl_windows_default_certificate_validation")
        meta.update(status="saved",bytes=path.stat().st_size,sha256=sha(path))
        if path.suffix==".pdf":
            import fitz
            doc=fitz.open(path);text="\n".join(f"\n--- PDF PAGE {i+1} ---\n"+p.get_text() for i,p in enumerate(doc))
            textpath=path.with_suffix(".txt");textpath.write_text(text,encoding="utf8");meta.update(pdf_pages=len(doc),text_path=textpath.relative_to(ROOT).as_posix())
        print(sid,meta["bytes"],"saved",flush=True)
    except Exception as exc:
        meta.update(status="unavailable",error=f"{type(exc).__name__}: {exc}");print(sid,"UNAVAILABLE",str(exc)[:120],flush=True)
    return meta

def main():
    (ROOT/"raw").mkdir(parents=True,exist_ok=True)
    manifest_path=ROOT/"source_manifest.json"
    sources=json.loads(manifest_path.read_text(encoding="utf8"))["sources"] if manifest_path.exists() else []
    old=json.loads((OLD/"source_manifest.json").read_text(encoding="utf8"))["sources"]
    ids={s["source_id"] for s in sources}
    for source in old:
        if source["source_id"] not in REUSE or source["source_id"] in ids:continue
        origin=OLD/source["local_path"];target=ROOT/"raw"/origin.name;target.write_bytes(origin.read_bytes())
        meta=dict(source);meta.update(local_path=target.relative_to(ROOT).as_posix(),copied_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            reuse_origin=str(origin),original_retrieved_at_utc=source["retrieved_at_utc"],published_date=source.get("published_at"))
        meta.pop("retrieved_at_utc",None)
        if target.suffix==".pdf":
            import fitz
            doc=fitz.open(target);textpath=target.with_suffix(".txt")
            textpath.write_text("\n".join(f"\n--- PDF PAGE {i+1} ---\n"+p.get_text() for i,p in enumerate(doc)),encoding="utf8")
            meta.update(pdf_pages=len(doc),text_path=textpath.relative_to(ROOT).as_posix())
        sources.append(meta)
    with ThreadPoolExecutor(max_workers=6) as pool:
        for source in pool.map(fetch,[j for j in JOBS if j[0] not in ids]):sources.append(source)
    manifest_path.write_text(json.dumps(dict(schema_version=1,as_of="2026-10-16T09:00:00+09:00",
        data_role="Retrospective historical source verification; original publication timestamps not always authenticated",sources=sources),ensure_ascii=False,indent=2)+"\n",encoding="utf8")

if __name__=="__main__":main()
