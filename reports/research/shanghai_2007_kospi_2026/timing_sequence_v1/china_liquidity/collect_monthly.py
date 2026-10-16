"""Retain CSRC's original public XLS monthly statistics and expose cell values."""
from concurrent.futures import ThreadPoolExecutor
import csv,datetime as dt,hashlib,json,re,urllib.request,urllib.parse
from pathlib import Path
import xlrd

ROOT=Path(__file__).resolve().parent
MONTHS=[("2007-07",1004303,"2007-08-10"),("2007-08",1004302,"2007-09-11"),("2007-09",1004301,"2007-10-11"),
 ("2007-10",1004300,"2007-11-12"),("2007-11",1004299,"2007-12-10"),("2007-12",1004298,"2008-01-10"),
 ("2008-01",1004297,"2008-02-11"),("2008-02",1004296,"2008-03-10"),("2008-03",1004295,"2008-04-11"),
 ("2008-04",1004294,"2008-05-12"),("2008-05",1004293,"2008-06-09"),("2008-06",1004292,"2008-07-08")]

def one(job):
    month,code,published=job;sid="CSRC_MONTH_"+month.replace("-","")
    page=f"https://www.csrc.gov.cn/csrc/c105936/c{code}/content.shtml"
    req=lambda url:urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=30).read()
    meta=dict(source_id=sid,url=page,observation_period=month,published_date=published,
       published_date_basis="CSRC_MONTHLY_INDEX dated listing, not migration-year URL",retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
       access="unauthenticated original historical XLS download")
    try:
        html=req(page);hp=ROOT/"raw"/(sid+".html");hp.write_bytes(html)
        links=re.findall(r'href="([^"]+\.xls)"',html.decode("utf8"))
        if len(links)!=1:raise ValueError("Expected one original XLS attachment")
        url=urllib.parse.quote(urllib.parse.urljoin(page,links[0]),safe=":/?=&%")
        payload=req(url);path=ROOT/"raw"/(sid+".xls");path.write_bytes(payload)
        book=xlrd.open_workbook(file_contents=payload)
        meta.update(status="saved",attachment_url=url,local_path=path.relative_to(ROOT).as_posix(),bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),html_path=hp.relative_to(ROOT).as_posix(),html_sha256=hashlib.sha256(html).hexdigest(),
            sheets=[dict(name=s.name,nrows=s.nrows,ncols=s.ncols) for s in book.sheets()])
        cells=[]
        for sheet in book.sheets():
            for r in range(sheet.nrows):
                values=sheet.row_values(r)
                cells.append(dict(source_id=sid,period=month,sheet=sheet.name,row_1based=r+1,values_json=json.dumps(values,ensure_ascii=False)))
        print(month,meta["sheets"],flush=True)
        return meta,cells
    except Exception as exc:
        meta.update(status="unavailable",error=str(exc));print(month,"UNAVAILABLE",str(exc),flush=True);return meta,[]

def main():
    manifest_path=ROOT/"source_manifest.json";manifest=json.loads(manifest_path.read_text(encoding="utf8"))
    ids={s["source_id"] for s in manifest["sources"]};cells=[]
    expected={"CSRC_MONTH_"+month.replace("-","") for month,_,_ in MONTHS}
    if expected.issubset(ids) and (ROOT/"csrc_monthly_cells.csv").exists():
        # Preserve the retained historical download vintage when rerun. A new
        # acquisition must use a new path/manifest revision rather than replace bytes.
        for source in manifest["sources"]:
            if source["source_id"] not in expected:continue
            if source.get("status")!="saved":raise ValueError("An expected retained XLS is unavailable")
            for pathkey,hashkey in [("local_path","sha256"),("html_path","html_sha256")]:
                if hashlib.sha256((ROOT/source[pathkey]).read_bytes()).hexdigest()!=source[hashkey]:
                    raise ValueError("Retained source vintage changed: "+source["source_id"])
        print("All12 original monthly vintages retained and verified; no downloads or overwrites")
        return
    with ThreadPoolExecutor(max_workers=5) as pool:
        for meta,rows in pool.map(one,MONTHS):
            if meta["source_id"] not in ids:manifest["sources"].append(meta)
            cells.extend(rows)
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    with (ROOT/"csrc_monthly_cells.csv").open("w",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=list(cells[0]));w.writeheader();w.writerows(cells)

if __name__=="__main__":main()
