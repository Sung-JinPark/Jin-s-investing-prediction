"""Archive public historical documents with verified TLS; no data APIs."""
from pathlib import Path
from urllib.request import Request, urlopen
import concurrent.futures, datetime, hashlib, json, subprocess
import fitz
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
SOURCES = [
 ('orient_daily_20071101','https://www.orient-fund.com/UserFiles/File/11727/11727.pdf','2007-11-01','2007-01-01/2007-09-30','fund_publisher_news_digest_reprinting_exchange_analysis'),
 ('orient_daily_200801','https://www.orient-fund.com/UserFiles/File/11822/11822.pdf',None,'2008_forecasts','fund_publisher_news_digest_reprinting_broker_views'),
 ('mof_2007_early_annual','https://www.mof.gov.cn/zhengwuxinxi/zhengcejiedu/2008/200805/t20080519_28811.htm','2008-02-05','2007-01-01/2007-12-31','official_accounting_analysis_early_nonrandom_sample'),
 ('csrc_2008_annual','https://www.csrc.gov.cn/csrc/c100028/c1002724/content.shtml','2009-05-19','2008-01-01/2008-12-31','official_regulatory_review'),
 ('sse_2007_annual','https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988204.shtml','2008-06-02','2007-01-01/2007-12-31','official_exchange_review'),
 ('szse_2008q1','https://www.szse.cn/aboutus/trends/news/t20080430_517692.html','2008-04-30','2008-01-01/2008-03-31','official_exchange_review'),
 ('huaw_micro_q3_analyst','https://stock.hexun.com/upload/600360.pdf',None,'2007Q3_actual_and_2008_forecast','original_broker_report_third_party_host_identity_pending'),
 ('cicc_200805_strategy_reprint','https://business.sohu.com/20080507/n256703298.shtml','2008-05-07','2008_forecast_revision','attributed_broker_authored_article_reprint_original_vintage_uncertified'),
 ('pingan_20080506','https://www.pingan.com/cms-tmplt/stock/marketReview/pingAnInvestigate/74206.html','2008-05-06','2008_forecast_views','research_house_own_publication'),
 ('icbc_2007q3','https://www.icbc.com.cn/en/page/721855152666738726.html',None,'2007-01-01/2007-09-30','company_own_results_release'),
 ('scfund_2008h2','https://www.scfund.com.cn/articlefilepath/1215135643295.pdf',None,'2008H2_forecasts','fund_own_strategy_report'),
 ('greatwall_20080121','https://epaper.cs.com.cn/zgzqb/html/2008-01/21/nw.D110000zgzqb_20080121_2-C03.htm?div=-1','2008-01-21','2008_forecasts_asof_2008-01-17_prices','broker_authored_strategy_in_original_newspaper_archive'),
]

def collect(item):
 sid,url,pub,period,kind=item
 ext='.pdf' if url.lower().endswith('.pdf') else '.html'
 path=ROOT/'sources'/(sid+ext)
 row=dict(source_id=sid,url=url,published_at=pub,observed_period=period,source_kind=kind,
  local_path=str(path.relative_to(ROOT)).replace('\\','/'),retrieved_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
  original_vintage_authenticated=False,vintage_note='Current retrospective retrieval; stated historical document date is not independent proof of unmodified original publication bytes.')
 try:
  req=Request(url,headers={'User-Agent':'Mozilla/5.0 historical research'})
  try:
   with urlopen(req,timeout=25) as response:
    raw=response.read(); row['resolved_url']=response.url; row['http_status']=response.status
    row['content_type']=response.headers.get('Content-Type'); row['transport']='urllib_verified_tls'
   path.write_bytes(raw)
  except Exception as first:
   cmd=['curl.exe','--location','--fail','--silent','--show-error','--max-time','45','--output',str(path),url]
   out=subprocess.run(cmd,capture_output=True,text=True,timeout=50)
   if out.returncode: raise RuntimeError(f'urllib: {first}; curl: {out.stderr}')
   raw=path.read_bytes(); row['transport']='curl_windows_schannel_verified_tls'; row['urllib_error']=str(first)
  row.update(status='saved',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
  txtpath=path.with_suffix('.txt')
  if ext=='.pdf':
   doc=fitz.open(path)
   txt='\n'.join(f'\n--- PDF page {i+1} ---\n'+p.get_text() for i,p in enumerate(doc))
   row['pdf_pages']=len(doc)
  else:
   soup=BeautifulSoup(raw,'html.parser')
   for tag in soup(['script','style']): tag.decompose()
   txt=soup.get_text('\n',strip=True)
  txtpath.write_text(txt,encoding='utf-8')
  row['extracted_text_path']=str(txtpath.relative_to(ROOT)).replace('\\','/')
  row['extracted_text_sha256']=hashlib.sha256(txtpath.read_bytes()).hexdigest()
 except Exception as e: row.update(status='failed',error=str(e))
 return row

if __name__=='__main__':
 (ROOT/'sources').mkdir(exist_ok=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: rows=list(pool.map(collect,SOURCES))
 (ROOT/'source_manifest.json').write_text(json.dumps({'schema_version':1,'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Public static historical documents only; market context remains frozen at 2026-10-16 09:00 Asia/Seoul and Korean Oct 15 close. No original vintage authentication.','sources':rows},ensure_ascii=False,indent=2),encoding='utf-8')
 for r in rows: print(r['source_id'],r['status'],r.get('bytes'),r.get('error',''))
