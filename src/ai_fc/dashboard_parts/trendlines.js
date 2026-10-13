(function(){
"use strict";
const TRENDLINES_PROMISES=new Map();
const TREND_PRIVATE_DETAILS=new Map();
async function ensureTrendlineData(assetId){
  if(TREND_PRIVATE_DETAILS.has(assetId))return;
  const dataset=DATA,summary=DATA?.trendlines?.assets?.find(row=>row.asset_id===assetId),pin=summary?.deferred_data;
  if(!pin?.required||pin.loaded)return;
  if(TRENDLINES_PROMISES.has(assetId))return TRENDLINES_PROMISES.get(assetId);
  const pending=(async()=>{
    if(!globalThis.crypto?.subtle||!/^[a-f0-9]{64}$/.test(String(pin.payload_sha256||'')))throw new Error('추세선 파일의 무결성을 확인할 수 없습니다');
    const prefix=window.__TRENDLINES_URL__,url=prefix?`${prefix}${assetId}${prefix.startsWith('/api/')?'':'.json'}`:pin.url;
    const response=await fetch(url,{cache:'no-store'});
    if(!response.ok)throw new Error(`추세선 데이터를 불러오지 못했습니다 (HTTP ${response.status})`);
    const raw=await response.text(),digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw));
    const hash=[...new Uint8Array(digest)].map(value=>value.toString(16).padStart(2,'0')).join('');
    if(hash!==pin.payload_sha256)throw new Error('추세선 파일이 현재 페이지의 기준과 다릅니다. 새로고침해 주세요');
    const payload=JSON.parse(raw),detail=payload?.data?.trendlines;
    if(payload?.schema_version!==1||payload.contract_id!=='trendlines_asset_route_v1'||!detail)throw new Error('추세선 데이터 형식이 올바르지 않습니다');
    for(const key of ['asset_id','snapshot_id','as_of','content_hash'])if(!pin[key]||detail[key]!==pin[key])throw new Error('추세선 기준이 현재 페이지와 다릅니다');
    globalThis.TrendlineUI.validate(detail);
    if(DATA!==dataset||DATA.trendlines.assets.find(row=>row.asset_id===assetId)!==summary)throw new Error('추세선 기준이 변경되었습니다. 새로고침해 주세요');
    DATA.trendlines.details={...(DATA.trendlines.details||{}),[assetId]:detail};
    pin.loaded=true;
  })().finally(()=>TRENDLINES_PROMISES.delete(assetId));
  TRENDLINES_PROMISES.set(assetId,pending);return pending;
}
const TREND_ASSETS=[['sk-hynix','SK하이닉스'],['soxx','SOXX'],['nasdaq','나스닥 종합'],['sp500','S&P 500'],['bitcoin','비트코인'],['dow','다우존스'],['mag7','빅테크 7']];
const TREND_PRIVATE_IDENTITIES={'sk-hynix':['KRX:000660','000660.KS','KRW','XKRX','KRW_per_share','Asia/Seoul','equity','exchange_close'],soxx:['NASDAQ:SOXX','SOXX','USD','XNAS','USD_per_share','America/New_York','etf','exchange_close'],nasdaq:['NASDAQ_COMPOSITE_PRICE_INDEX','^IXIC','USD','XNAS','index_points','America/New_York','index','exchange_close'],sp500:['SP500_PRICE_INDEX','^GSPC','USD','XNYS','index_points','America/New_York','index','exchange_close'],bitcoin:['BTC_USD_SPOT_SOURCE_MUST_BE_DECLARED','BTC-USD','USD','24/7','USD_per_BTC','UTC','crypto','UTC_00_00_next_day'],dow:['DOW_JONES_INDUSTRIAL_AVERAGE_PRICE_INDEX','^DJI','USD','XNYS','index_points','America/New_York','index','exchange_close']};
async function parseTrendPrivateImport(raw,assetId){
  const encoder=new TextEncoder(),sha=/^[a-f0-9]{64}$/;
  if(typeof raw!=='string'||encoder.encode(raw).length>524288)throw new Error('개인 연구 파일이 512KiB 제한을 넘었습니다');
  const envelope=JSON.parse(raw);
  if(envelope?.schema_version!==1||envelope.contract_id!=='trendlines_private_import_v1'||envelope.publication_scope!=='private_only'||envelope.asset_id!==assetId||!Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId)||typeof envelope.payload_json!=='string'||!sha.test(envelope.payload_sha256||'')||encoder.encode(envelope.payload_json).length>262144)throw new Error('현재 자산의 개인 연구 파일 형식이 아닙니다');
  if(!globalThis.crypto?.subtle)throw new Error('이 브라우저에서 파일의 무결성을 확인할 수 없습니다');
  const digest=await crypto.subtle.digest('SHA-256',encoder.encode(envelope.payload_json)),hash=[...new Uint8Array(digest)].map(value=>value.toString(16).padStart(2,'0')).join('');
  if(hash!==envelope.payload_sha256)throw new Error('개인 연구 파일 내용이 저장된 검수 기준과 다릅니다');
  const detail=JSON.parse(envelope.payload_json),identity=TREND_PRIVATE_IDENTITIES[assetId],asset=detail?.asset;
  if(!detail||Object.hasOwn(detail,'content_hash')||detail.asset_id!==assetId||detail.snapshot_id!==envelope.snapshot_id||detail.status!=='unverified_display'||detail.publication_scope!=='private_only'||!/^research-snapshot-[a-f0-9]{64}$/.test(detail.snapshot_id||'')||!/^research-receipt-[a-f0-9]{64}$/.test(detail.receipt_id||'')||!sha.test(detail.raw_sha256||'')||!sha.test(detail.research_archive_sha256||'')||!sha.test(detail.source_snapshot_hash||'')||asset?.asset_id!==assetId||asset.identity!==identity[0]||asset.provider_symbol!==identity[1]||asset.currency!==identity[2]||asset.calendar_id!==identity[3]||detail.source_identity?.source_id!=='yahoo_public_history_html'||detail.source_identity?.provider_symbol!==identity[1]||detail.source_identity?.calendar_id!==identity[3])throw new Error('개인 연구 파일의 자산 또는 원문 근거가 올바르지 않습니다');
  const source=trendSourceUrl(detail.source_url),sourceUrl=source?new URL(source):null;
  const secrets=new Set(['api_key','apikey','api-key','key','token','access_token','accesstoken','api_token','secret','client_secret','password','registrationkey','user_id','userid','authorization']);
  if(!sourceUrl||sourceUrl.protocol!=='https:'||sourceUrl.hostname!=='finance.yahoo.com'||sourceUrl.username||sourceUrl.password||sourceUrl.hash||!['','443'].includes(sourceUrl.port)||[...sourceUrl.searchParams.keys()].some(key=>secrets.has(key.toLowerCase()))||decodeURIComponent(sourceUrl.pathname)!==`/quote/${identity[1]}/history/`)throw new Error('개인 연구 파일의 시세 원문이 올바르지 않습니다');
  const aware=value=>typeof value==='string'&&/(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));
  if(!aware(detail.as_of)||!aware(detail.knowledge_cutoff)||!aware(detail.retrieved_at)||Date.parse(detail.knowledge_cutoff)!==Date.parse(detail.as_of)||Date.parse(detail.retrieved_at)>Date.parse(detail.as_of)||Date.parse(detail.as_of)>Date.now())throw new Error('개인 연구 파일의 기준 시각이 올바르지 않습니다');
  if(detail.intraday_quote&&(!aware(detail.intraday_quote.observed_at)||!aware(detail.intraday_quote.retrieved_at)||Date.parse(detail.intraday_quote.observed_at)>Date.parse(detail.intraday_quote.retrieved_at)||Date.parse(detail.intraday_quote.retrieved_at)>Date.parse(detail.as_of)||detail.intraday_quote.currency!==identity[2]||!Number.isInteger(detail.intraday_quote.session_index)||trendSourceUrl(detail.intraday_quote.source_url)!==source))throw new Error('개인 연구 파일의 별도 관측 근거가 올바르지 않습니다');
  detail.content_hash=hash;
  trendValidateDetail(detail);
  if(detail.bars.length>756||detail.observation_through!==(detail.bars.at(-1).session||detail.bars.at(-1).session_date)||detail.quality?.latest_completed_observation!==detail.observation_through||detail.bars.some(bar=>!/^research-bar-[a-f0-9]{64}$/.test(bar.bar_id||'')))throw new Error('개인 연구 파일의 일봉 기준이 올바르지 않습니다');
  if(asset.unit!==identity[4]||asset.timezone!==identity[5]||asset.kind!==identity[6]||asset.source_day_cutoff!==identity[7]||asset.source_id!=='yahoo_public_history_html')throw new Error('개인 연구 파일의 가격 단위 또는 세션 기준이 올바르지 않습니다');
  if(asset.verified_source!==false||asset.rights_status!=='uncertified_research_source'||asset.price_basis!=='provider_reported_ohlc_current_vintage'||detail.source_identity.verified_source!==false||detail.source_identity.adjustment_verified!==false)throw new Error('개인 연구 파일이 검증된 시세로 표시되어 있습니다');
  const reasons=new Set(['source_null_ohlc_no_fill','source_invalid_ohlc_no_fill','source_session_missing_no_fill','unfinished_session_not_a_final_candle','source_current_session_finality_unverified']);
  if((detail.gaps||[]).some(gap=>!reasons.has(gap.reason)))throw new Error('개인 연구 파일의 결측 근거가 올바르지 않습니다');
  const last=detail.bars.at(-1),offsets=assetId==='bitcoin'?[1,7,30]:[1,5,21];
  for(const axis of ['linear','log'])for(const [period,analysis] of Object.entries(detail.analyses[axis])){
    if(!['63','252','756'].includes(period)||analysis.axis!==axis||analysis.window!==Number(period))throw new Error('개인 연구 파일의 기간 또는 축이 올바르지 않습니다');
    if(analysis.status!=='ready')continue;
    const sessions=analysis.projection_sessions;
    if(!Array.isArray(sessions)||sessions.length!==offsets.length||sessions.some((row,i)=>row.offset!==offsets[i]||row.index!==last.session_index+row.offset||!/^\d{4}-\d{2}-\d{2}$/.test(row.session||'')||row.session<=(i?sessions[i-1].session:(last.session||last.session_date))))throw new Error('개인 연구 파일의 연장 날짜가 올바르지 않습니다');
    const ids=new Set();
    for(const line of analysis.lines){
      if(line.axis!==axis||line.window!==Number(period)||!/^trend-line-[a-f0-9]{32}$/.test(line.line_id||'')||ids.has(line.line_id)||!Array.isArray(line.projections)||line.projections.length!==sessions.length)throw new Error('개인 연구 파일의 빗각선 기준이 올바르지 않습니다');
      ids.add(line.line_id);
      for(const anchor of [line.first_anchor,line.second_anchor]){
        const bar=detail.bars.find(row=>row.session_index===anchor?.index),value=anchor&&trendLinePrice(line,anchor.index,axis);
        if(!bar||anchor.bar_id!==bar.bar_id||anchor.session!==(bar.session||bar.session_date)||anchor.price!==bar[line.side==='support'?'low':'high']||!Number.isFinite(value)||Math.abs(value-anchor.price)>Math.max(1e-6,Math.abs(anchor.price)*1e-10))throw new Error('개인 연구 파일의 고점·저점 근거가 올바르지 않습니다');
      }
      for(const point of line.points){
        const row=point.future===true?sessions.find(row=>row.index===point.index):detail.bars.find(row=>row.session_index===point.index);
        if(typeof point.future!=='boolean'||point.future!==(point.index>last.session_index)||!row||point.session!==(row.session||row.session_date))throw new Error('개인 연구 파일의 선 끝점 날짜가 올바르지 않습니다');
      }
      for(const [i,projection] of line.projections.entries()){
        const session=sessions[i],point=line.points.find(row=>row.future&&row.index===projection.index);
        if(projection.index!==session.index||projection.offset!==session.offset||projection.session!==session.session||!['ready','unavailable'].includes(projection.status)||(projection.status==='ready'?(!point||projection.price!==point.price):(projection.price!==null||!!point)))throw new Error('개인 연구 파일의 선 연장 값이 올바르지 않습니다');
      }
    }
  }
  return detail;
}
function bindTrendPrivateImport(root,initial){
  const input=root.querySelector('[data-trend-private-file]'),button=root.querySelector('[data-trend-private-open]'),message=root.querySelector('[data-trend-private-message]'),assetId=initial.asset||'sk-hynix';
  button.addEventListener('click',()=>input.click());
  input.addEventListener('change',async()=>{const file=input.files?.[0];if(!file)return;button.disabled=true;message.textContent='개인 연구 파일을 확인하고 있습니다';try{if(file.size>524288)throw new Error('개인 연구 파일이 512KiB 제한을 넘었습니다');const detail=await parseTrendPrivateImport(await file.text(),assetId);if(!root.isConnected)return;TREND_PRIVATE_DETAILS.set(assetId,detail);globalThis.TrendlineUI.cleanup();renderTrendlinePage(initial);}catch(error){message.textContent=String(error.message||'개인 연구 파일을 읽지 못했습니다');}finally{button.disabled=false;input.value='';}});
  root.querySelector('[data-trend-private-clear]')?.addEventListener('click',()=>{TREND_PRIVATE_DETAILS.delete(assetId);globalThis.TrendlineUI.cleanup();renderTrendlinePage(initial);});
}
const TREND_BASES={split_adjusted:'주식분할 조정 시세',split_adjusted_price:'주식분할 조정 시세',published_spot_price:'일별 현물 시세',published_price_index:'공식 가격 지수',provider_reported_ohlc_current_vintage:'현재 공개된 일별 시세 이력'};
const TREND_STATES={active:'유지',break_pending:'이탈 확인 중',broken:'이탈',reclaim_pending:'복귀 확인 중',reclaimed:'복귀',research_reference:'현재 자료로 그린 참고선'};
const TREND_REASON_LABELS={latest_completed_session_missing:'최근 마감 시세가 아직 확인되지 않았습니다.',capture_rejected_last_good_preserved:'새 시세의 검수가 보류돼 마지막 검수 자료를 유지합니다.',missing_approved_ohlc:'공개 배포가 확인된 일별 시세를 기다리고 있습니다.',source_rights_pending:'시세의 공개 이용 조건을 확인하고 있습니다.',source_unavailable:'시세를 가져오지 못했습니다.',insufficient_history:'이 기간의 추세선을 확인할 과거 시세가 부족합니다.',insufficient_pivots:'확정된 고점·저점이 부족해 빗각선을 그리지 않았습니다.',no_valid_lines:'이 기간에서 검증을 통과한 빗각선이 없습니다.',stale_source:'새로 마감된 시세가 아직 확인되지 않았습니다.',stale_snapshot:'최근 마감 시세로 갱신이 필요합니다.',invalid_snapshot:'가격 자료 검증을 완료하지 못했습니다.'};
function trendReasons(codes){return [...new Set((codes||[]).map(code=>TREND_REASON_LABELS[code]||'가격 자료 검증을 완료하지 못했습니다.'))].join(' ')||'검증된 시세가 준비되면 자동으로 갱신합니다.';}
function trendPrice(value,asset){return `${Number(value).toLocaleString('ko-KR',{maximumFractionDigits:asset?.price_unit==='KRW'||asset?.currency==='KRW'?0:2})}${['points','index_points'].includes(asset?.price_unit)?' pt':asset?.currency==='KRW'?'원':asset?.currency==='USD'?'달러':''}`;}
function trendSourceUrl(value){try{const url=new URL(String(value));return ['https:','http:'].includes(url.protocol)?url.href:null;}catch(_){return null;}}
function trendResearchMarkup(detail,asset){
  const url=trendSourceUrl(detail.source_url||detail.source_identity?.source_url),gaps=detail.gaps||[],quote=detail.intraday_quote;
  const source=url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">원문 시세 ↗</a>`:'원문 주소 확인 중';
  const gapMarkup=gaps.length?`<p class="trend-gap-note" data-trend-gaps>일봉 미표시 ${gaps.length}개 · ${gaps.map(row=>`${esc(row.session)}${row.reason==='unfinished_session_not_a_final_candle'?' (장중)':''}`).join(', ')} · 원문에 없는 가격은 채우지 않습니다.</p>`:'';
  const quality=detail.quality,qualityMarkup=quality?.stale?`<p class="trend-stale" role="status" data-trend-research-stale>최근 마감 일봉 누락 · ${esc(quality.expected_completed_session||'')}<br><small>${esc(detail.observation_through)} 공개 일봉 종가와 그 날짜 기준 경계입니다.</small></p>`:'';
  const quoteMarkup=quote?`<aside class="trend-quote" data-trend-intraday><div><span>별도 장중 관측 · 일봉 종가 아님</span><strong>${esc(trendPrice(quote.price,asset))}</strong></div><p>${esc(quote.date)} ${esc(quote.time||'')} · 취득 ${esc(quote.retrieved_at||detail.retrieved_at||'시각 확인 중')}${trendSourceUrl(quote.source_url)?` · <a href="${esc(trendSourceUrl(quote.source_url))}" target="_blank" rel="noopener noreferrer">관측 원문 ↗</a>`:''}</p></aside>`:'';
  return `<section class="trend-research" role="status" data-trend-research><strong>공개 시세로 그린 연구 차트</strong><span>개인 연구용 · 원천 검증 미완료 · 공식 예측과 분리</span><p>${source} · 취득 ${esc(detail.retrieved_at||detail.as_of)}</p><small>현재 공개본을 사용합니다. 과거 당시 공개된 가격 이력과 다를 수 있습니다. 과거 이탈·복귀 신호를 판정하지 않습니다.</small></section>${qualityMarkup}${gapMarkup}${quoteMarkup}`;
}
function trendValidateDetail(detail){
  if(!['ready','stale','unverified_display'].includes(detail?.status)||!Array.isArray(detail.bars)||detail.bars.length<2||!detail.analyses)throw new Error('표시할 일봉이 없습니다');
  if(detail.status==='unverified_display'&&(detail.contract_id!=='trendlines_research_display_v1'||detail.publication_class!=='research_source'||detail.verified_source!==false||detail.numbers_visible!==true||detail.official_forecast_write!==false||detail.source_context!=='user_authorized_public_html_research'||detail.source_identity?.rights_status!=='uncertified_research_source'||detail.source_identity?.price_basis!=='provider_reported_ohlc_current_vintage'||detail.adjustment_verified!==false||detail.historical_signals_available!==false||detail.guards?.approved_free_ohlc!==false))throw new Error('연구 시세의 원천 상태가 올바르지 않습니다');
  let previous=null;
  for(const bar of detail.bars){
    const date=bar.session||bar.session_date;
    if(!/^\d{4}-\d{2}-\d{2}$/.test(date||'')||!Number.isInteger(bar.session_index)||(previous&&(date<=previous.session||bar.session_index<=previous.index)))throw new Error('일봉 날짜가 올바르지 않습니다');
    if(!['open','high','low','close'].every(key=>typeof bar[key]==='number'&&Number.isFinite(bar[key])&&bar[key]>0)||bar.low>Math.min(bar.open,bar.close)||bar.high<Math.max(bar.open,bar.close)||bar.low>bar.high)throw new Error('일봉 가격 범위가 올바르지 않습니다');
    previous={session:date,index:bar.session_index};
  }
  const gapDates=new Set(),gapIndices=new Set();
  for(const gap of detail.gaps||[]){if(!/^\d{4}-\d{2}-\d{2}$/.test(gap.session||'')||!Number.isInteger(gap.session_index)||gapDates.has(gap.session)||gapIndices.has(gap.session_index)||detail.bars.some(bar=>(bar.session||bar.session_date)===gap.session||bar.session_index===gap.session_index))throw new Error('결측 일봉의 위치가 올바르지 않습니다');gapDates.add(gap.session);gapIndices.add(gap.session_index);}
  if(detail.intraday_quote&&(typeof detail.intraday_quote.price!=='number'||!Number.isFinite(detail.intraday_quote.price)||detail.intraday_quote.price<=0||detail.intraday_quote.status!=='intraday_snapshot_not_final_close'||!/^\d{4}-\d{2}-\d{2}$/.test(detail.intraday_quote.date||'')))throw new Error('별도 장중 관측이 올바르지 않습니다');
  for(const scale of ['linear','log'])for(const period of ['63','252','756']){
    const analysis=detail.analyses[scale]?.[period];
    if(!analysis||!['ready','hold'].includes(analysis.status))throw new Error('추세선 기간 또는 축 정보가 없습니다');
    if(analysis.status==='hold')continue;
    if(!Array.isArray(analysis.lines)||!analysis.borders)throw new Error('추세선 형식이 올바르지 않습니다');
    if(detail.status==='unverified_display'&&((analysis.events||[]).length||analysis.lines.some(line=>line.state!=='research_reference')))throw new Error('연구 시세에 과거 확정 신호가 포함되어 있습니다');
    for(const line of analysis.lines){
      if(!['support','resistance'].includes(line.side)||!Array.isArray(line.points)||line.points.length<2||!Number.isFinite(line.slope)||!Number.isFinite(line.intercept)||!Number.isInteger(line.coordinate_origin_index))throw new Error('빗각선 정보가 올바르지 않습니다');
      let lastIndex=-Infinity;
      for(const point of line.points){
        if(!Number.isInteger(point.index)||point.index<=lastIndex||typeof point.price!=='number'||!Number.isFinite(point.price)||point.price<=0)throw new Error('빗각선 끝점이 올바르지 않습니다');
        const expected=trendLinePrice(line,point.index,scale);
        if(!Number.isFinite(expected)||Math.abs(expected-point.price)>Math.max(1e-6,Math.abs(point.price)*1e-10))throw new Error('빗각선 끝점이 계산 기준과 다릅니다');
        lastIndex=point.index;
      }
      const expectedCurrent=trendLinePrice(line,detail.bars.at(-1).session_index,scale);
      if(typeof line.current_price!=='number'||!Number.isFinite(line.current_price)||line.current_price<=0||Math.abs(line.current_price-expectedCurrent)>Math.max(1e-6,Math.abs(expectedCurrent)*1e-10))throw new Error('빗각선 기준일 가격이 계산과 다릅니다');
    }
    for(const key of ['down','up','broken'])if(!Array.isArray(analysis.borders[key])||analysis.borders[key].some(row=>typeof row.price!=='number'||!Number.isFinite(row.price)||row.price<=0))throw new Error('가격 경계가 올바르지 않습니다');
    for(const key of ['down','up','broken'])for(const row of analysis.borders[key]){const line=analysis.lines.find(line=>line.line_id===row.line_id);if(!line||Math.abs(row.price-line.current_price)>Math.max(1e-6,Math.abs(row.price)*1e-10))throw new Error('가격 경계가 빗각선과 다릅니다');}
  }
  return detail;
}
function trendLinePrice(line,index,scale){const value=line.intercept+line.slope*(index-line.coordinate_origin_index);return scale==='log'?Math.exp(value):value;}
function trendQuoteBorders(analysis,quote,scale){
  const rows=analysis.lines.map(line=>({...line,price:trendLinePrice(line,quote.session_index,scale)})).filter(row=>Number.isFinite(row.price)&&row.price>0);
  return {down:rows.filter(row=>row.price<=quote.price).sort((a,b)=>b.price-a.price||a.line_id.localeCompare(b.line_id)).slice(0,3),up:rows.filter(row=>row.price>quote.price).sort((a,b)=>a.price-b.price||a.line_id.localeCompare(b.line_id)).slice(0,3)};
}
function trendChartModel(detail,period=63,scale='linear',width=1000){
  trendValidateDetail(detail);
  const analysis=detail.analyses[scale]?.[String(period)];
  if(analysis?.status!=='ready')return null;
  const bars=detail.bars.slice(-period),first=bars[0].session_index,last=bars.at(-1).session_index;
  const lines=analysis.lines,points=lines.flatMap(line=>line.points.filter(point=>point.index>=first));
  const gaps=(detail.gaps||[]).filter(gap=>gap.session_index>=first);
  const quote=Number.isInteger(detail.intraday_quote?.session_index)&&detail.intraday_quote.session_index>=first?detail.intraday_quote:null;
  const end=Math.max(last+1,...points.map(point=>point.index),...gaps.map(gap=>gap.session_index),quote?.session_index??last),prices=bars.flatMap(bar=>[bar.low,bar.high]).concat(points.map(point=>point.price),quote?[quote.price]:[]);
  const transform=value=>scale==='log'?Math.log(value):value,inverse=value=>scale==='log'?Math.exp(value):value;
  let low=Math.min(...prices.map(transform)),high=Math.max(...prices.map(transform)),pad=(high-low)*.07||Math.abs(high)*.02||1;
  low=scale==='linear'?Math.max(0,low-pad):low-pad;high+=pad;
  const W=Math.max(330,Math.round(width)),H=W<600?380:440,L=W<600?62:88,R=20,T=24,B=46;
  const x=index=>L+(index-first)/Math.max(1,end-first)*(W-L-R),y=price=>T+(high-transform(price))/(high-low)*(H-T-B);
  return {bars,lines,analysis,gaps,quote,first,last,end,W,H,L,R,T,B,x,y,ticks:Array.from({length:5},(_,i)=>inverse(low+(high-low)*i/4))};
}
function trendSvg(detail,model,asset){
  const m=model,clip=`trend-clip-${detail.asset_id}`,futureX=m.x(m.last),bodyWidth=Math.max(1,Math.min(8,(m.W-m.L-m.R)/(m.end-m.first+1)*.55));
  const grid=m.ticks.map(price=>`<g><line x1="${m.L}" y1="${m.y(price)}" x2="${m.W-m.R}" y2="${m.y(price)}" stroke="#e1ded5"/><text x="${m.L-7}" y="${m.y(price)+4}" text-anchor="end">${esc(Number(price).toLocaleString('ko-KR',{maximumFractionDigits:0}))}</text></g>`).join('');
  const tickBars=[m.bars[0]],tickGap=m.W<600?75:110;
  for(const bar of m.bars.slice(1,-1))if(m.x(bar.session_index)-m.x(tickBars.at(-1).session_index)>=tickGap)tickBars.push(bar);
  const finalBar=m.bars.at(-1);
  if(tickBars.length>1&&m.x(finalBar.session_index)-m.x(tickBars.at(-1).session_index)<65)tickBars.pop();
  if(finalBar!==tickBars.at(-1))tickBars.push(finalBar);
  const ticks=tickBars.map(bar=>`<text x="${m.x(bar.session_index)}" y="${m.H-15}" text-anchor="middle">${esc((bar.session||bar.session_date).slice(2))}</text>`).join('');
  const candles=m.bars.map(bar=>{const up=bar.close>=bar.open,color=up?'#bb4c1c':'#34738d',top=m.y(Math.max(bar.open,bar.close)),height=Math.max(1,Math.abs(m.y(bar.open)-m.y(bar.close)));return `<g data-trend-bar="${esc(bar.session||bar.session_date)}"><line x1="${m.x(bar.session_index)}" y1="${m.y(bar.high)}" x2="${m.x(bar.session_index)}" y2="${m.y(bar.low)}" stroke="${color}"/><rect x="${m.x(bar.session_index)-bodyWidth/2}" y="${top}" width="${bodyWidth}" height="${height}" fill="${color}"/></g>`;}).join('');
  const gaps=m.gaps.map(gap=>`<g data-trend-gap="${esc(gap.session)}"><rect x="${m.x(gap.session_index)-bodyWidth}" y="${m.T}" width="${bodyWidth*2}" height="${m.H-m.T-m.B}" fill="#b88120" opacity=".15"/><line x1="${m.x(gap.session_index)}" x2="${m.x(gap.session_index)}" y1="${m.T}" y2="${m.H-m.B}" stroke="#a77927" stroke-dasharray="2 4"/><title>${esc(gap.session)} · 원천 결측 일봉</title></g>`).join('');
  const paths=m.lines.map(line=>{const color=line.state==='broken'?'#897b9f':line.side==='support'?'#247d78':'#bd5a20',dash=line.geometry_status==='candidate'||line.state==='broken'?'6 5':'',actual=line.points.filter(point=>!point.future),future=line.points.filter(point=>point.future);const path=points=>points.map(point=>`${m.x(point.index).toFixed(3)},${m.y(point.price).toFixed(3)}`).join(' ');const anchors=[line.first_anchor,line.second_anchor].filter(anchor=>anchor&&anchor.index>=m.first).map(anchor=>`<circle cx="${m.x(anchor.index)}" cy="${m.y(anchor.price)}" r="4" fill="${color}" stroke="#fff"><title>${esc(anchor.session)} · ${esc(trendPrice(anchor.price,asset))}</title></circle>`).join('');return `<g data-trend-line="${esc(line.line_id)}"><polyline points="${path(actual)}" fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="${dash}"/>${future.length?`<polyline data-trend-projection="${esc(line.line_id)}" points="${path([actual.at(-1),...future].filter(Boolean))}" fill="none" stroke="${color}" stroke-width="1.5" stroke-dasharray="3 5"/>`:''}${anchors}</g>`;}).join('');
  const quote=m.quote?`<g data-trend-quote-point="${esc(m.quote.date)}"><circle cx="${m.x(m.quote.session_index)}" cy="${m.y(m.quote.price)}" r="6" fill="#fff8e8" stroke="#a77919" stroke-width="2.5"/><text x="${m.x(m.quote.session_index)-9}" y="${m.y(m.quote.price)-10}" text-anchor="end">장중</text><title>${esc(m.quote.date)} ${esc(m.quote.time||'')} · ${esc(trendPrice(m.quote.price,asset))} · 별도 장중 관측, 일봉 종가 아님</title></g>`:'';
  return `<svg viewBox="0 0 ${m.W} ${m.H}" role="img" tabindex="0" aria-label="${esc(asset.label)} 일봉과 상방·하방 빗각선. 방향키로 날짜를 선택합니다"><defs><clipPath id="${clip}"><rect x="${m.L}" y="${m.T}" width="${m.W-m.L-m.R}" height="${m.H-m.T-m.B}"/></clipPath></defs>${grid}<rect x="${futureX}" y="${m.T}" width="${m.W-m.R-futureX}" height="${m.H-m.T-m.B}" fill="#eeece6" opacity=".8"/><text x="${futureX+5}" y="${m.T+12}">선 연장</text><g clip-path="url(#${clip})">${gaps}${candles}${paths}${quote}<line data-trend-cross x1="${futureX}" x2="${futureX}" y1="${m.T}" y2="${m.H-m.B}" stroke="#777" stroke-dasharray="2 4"/></g>${ticks}<rect data-trend-overlay x="${m.L}" y="${m.T}" width="${m.W-m.L-m.R}" height="${m.H-m.T-m.B}" fill="transparent"/></svg>`;
}
function bindTrendChart(host,detail,m,asset,scale){
  const svg=host.querySelector('svg'),cross=host.querySelector('[data-trend-cross]'),readout=host.querySelector('[data-trend-readout]');
  const entries=[...m.bars.map(row=>({kind:'bar',row})),...m.gaps.map(row=>({kind:'gap',row})),...(m.quote?[{kind:'quote',row:m.quote}]:[])].sort((a,b)=>a.row.session_index-b.row.session_index||Number(a.kind==='quote')-Number(b.kind==='quote'));
  let selected=entries.findIndex(entry=>entry.kind==='bar'&&entry.row===m.bars.at(-1));
  const paint=index=>{selected=Math.max(0,Math.min(entries.length-1,index));const {kind,row}=entries[selected];cross.setAttribute('x1',m.x(row.session_index));cross.setAttribute('x2',m.x(row.session_index));if(kind==='gap'){readout.textContent=`${row.session} · ${row.reason==='unfinished_session_not_a_final_candle'?'장중 관측은 일봉 종가로 사용하지 않습니다':'원천 결측 · 일봉 미표시'}`;return;}const lineRows=m.lines.slice(0,6).map(line=>`${line.side==='support'?'지지':'저항'} ${trendPrice(trendLinePrice(line,row.session_index,scale),asset)}`).join(' · ');readout.textContent=kind==='quote'?`${row.date} ${row.time||''} · 별도 장중 관측 ${trendPrice(row.price,asset)} · 일봉 종가 아님${lineRows?' | 해당 날짜의 선 연장: '+lineRows:''}`:`${row.session||row.session_date} · 시가 ${trendPrice(row.open,asset)} · 고가 ${trendPrice(row.high,asset)} · 저가 ${trendPrice(row.low,asset)} · 종가 ${trendPrice(row.close,asset)}${lineRows?' | '+lineRows:''}`;};
  const pointer=event=>{const bounds=svg.getBoundingClientRect(),x=(event.clientX-bounds.left)/bounds.width*m.W,y=(event.clientY-bounds.top)/bounds.height*m.H,index=m.first+(x-m.L)/(m.W-m.L-m.R)*(m.end-m.first);let nearest=entries.reduce((best,entry,i)=>Math.abs(entry.row.session_index-index)<Math.abs(entries[best].row.session_index-index)?i:best,0);if(m.quote&&Math.abs(m.quote.session_index-index)<.5&&Math.abs(m.y(m.quote.price)-y)<20)nearest=entries.findIndex(entry=>entry.kind==='quote');paint(nearest);};
  svg.addEventListener('pointermove',pointer);svg.addEventListener('pointerdown',pointer);
  svg.addEventListener('focus',()=>paint(selected));
  svg.addEventListener('keydown',event=>{let index=selected;if(event.key==='ArrowLeft')index--;else if(event.key==='ArrowRight')index++;else if(event.key==='Home')index=0;else if(event.key==='End')index=entries.length-1;else return;event.preventDefault();paint(index);});
  paint(selected);
}
let TRENDLINES_RESIZE=null;
function renderTrendlinePage(initial={},loadState=null){
  const assetId=initial?.asset||'sk-hynix',projection=DATA?.trendlines||{},officialAsset=projection.assets?.find(row=>row.asset_id===assetId),localDetail=TREND_PRIVATE_DETAILS.get(assetId),asset=localDetail?{...officialAsset,asset_id:assetId,label:TREND_ASSETS.find(row=>row[0]===assetId)?.[1],currency:localDetail.asset.currency,price_unit:localDetail.asset.unit,status:'unverified_display',last_session:localDetail.observation_through}:officialAsset,detail=localDetail||projection.details?.[assetId];
  const nav=TREND_ASSETS.map(([id,label])=>`<a href="#future/trendlines/${id}"${id===assetId?' aria-current="page"':''}>${esc(label)}</a>`).join('');
  const fixture=detail?.fixture_only===true?'<p class="trend-fixture" role="alert">검토용 가상 시세 · 실제 시장 분석이 아닙니다</p>':'';
  const root=el(`<div class="trend-page"><header class="page-heading"><div><p class="eyebrow">미래 탐색 · 05</p><h1>상·하방 추세선</h1><p class="page-lede">실제 일봉의 고점·저점을 잇는 빗각선과 기준 종가 위·아래의 경계를 확인합니다.</p></div></header><nav class="trend-assets" aria-label="추세선 자산 선택">${nav}</nav>${Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId)?`<section class="trend-private-controls"><button type="button" data-trend-private-open>개인 연구 차트 열기</button>${localDetail?'<button type="button" data-trend-private-clear>개인 자료 지우기</button>':''}<span>파일은 이 브라우저에서만 읽습니다</span><input type="file" accept=".json,application/json" data-trend-private-file hidden><p data-trend-private-message role="status"></p></section>`:''}${fixture}<section class="trend-body"></section></div>`),body=root.querySelector('.trend-body');
  if(root.querySelector('[data-trend-private-file]'))bindTrendPrivateImport(root,initial);
  const held=!asset||!['ready','stale','unverified_display'].includes(asset.status)||!detail||!['ready','stale','unverified_display'].includes(detail.status);
  if(loadState||held){const error=loadState?.error,loading=loadState?.loading;body.innerHTML=`<div class="trend-hold" role="status"><span>${esc(asset?.label||'자산 확인')}</span><h2>${loading?'일봉과 빗각선을 불러오고 있습니다':error?'추세선을 불러오지 못했습니다':'추세선 확인 보류'}</h2><p>${esc(error?String(error.message||error):!asset?'요청한 자산을 찾을 수 없습니다. 위에서 자산을 선택해 주세요.':trendReasons(asset.reason_codes))}</p>${error?'<button type="button" data-trend-retry>다시 불러오기</button>':''}${asset?.last_session?`<small>확인된 마지막 시세 ${esc(asset.last_session)}</small>`:''}</div>`;mount(root);root.querySelector('[data-trend-retry]')?.addEventListener('click',()=>route());return;}
  try{trendValidateDetail(detail);}catch(error){renderTrendlinePage(initial,{error});return;}
  let period=63,scale='linear';
  const stale=asset.status==='stale',research=asset.status==='unverified_display';
  body.innerHTML=`${research?trendResearchMarkup(detail,asset):''}${stale?`<p class="trend-stale" role="status">마지막 검수: ${esc(asset.last_session)} · 갱신 보류<br><small>기준 종가와 당시 경계를 표시합니다. ${esc(trendReasons(asset.reason_codes))}</small></p>`:''}<div class="trend-title"><div><span>${esc(asset.last_session)} · ${research?'공개 일봉 종가':stale?'기준 종가':'마감 기준'}</span><h2>${esc(asset.label)}</h2></div><strong>${esc(trendPrice(detail.bars.at(-1).close,asset))}</strong></div><div class="trend-controls"><div role="group" aria-label="추세선 기간">${[[63,'3개월'],[252,'1년'],[756,'3년']].map(([value,label])=>`<button type="button" data-trend-period="${value}" aria-pressed="${value===63}">${label}</button>`).join('')}</div><div role="group" aria-label="가격 축"><button type="button" data-trend-scale="linear" aria-pressed="true">선형</button><button type="button" data-trend-scale="log" aria-pressed="false">로그</button></div></div><div class="trend-chart"></div><div class="trend-legend">${research&&detail.intraday_quote?'<span><i class="trend-quote-dot"></i>별도 장중 관측</span>':''}<span><i class="trend-support"></i>지지 빗각선</span><span><i class="trend-resistance"></i>저항 빗각선</span><span><i class="trend-broken"></i>${research?'후보선은 점선':'이탈·후보선은 점선'}</span></div><div class="trend-borders"${research?' data-research="true"':''}></div>${research&&detail.intraday_quote?'<div data-trend-quote-borders></div>':''}<p class="trend-note">선의 연장은 가격 예상이나 도달 확률이 아닙니다. 접촉한 날짜와 기준 축이 달라지면 경계 가격도 달라집니다.</p><details class="trend-method"><summary>선을 확인하는 기준</summary><p>${research?'현재 확보한 공개 일봉에서 고점·저점을 찾아 선을 그립니다. 결측을 가로질러 고점·저점을 확정하지 않습니다. 과거 당시의 이탈·복귀 신호를 판정하지 않습니다.':'확정된 고점·저점으로 계산한 선을 그립니다. 종가 이탈과 복귀는 별도로 확인합니다.'} 접촉 횟수는 기하학적 근거이며 지지 성공 확률이 아닙니다.</p><p>기준 시각 ${esc(detail.as_of)} · ${esc(TREND_BASES[detail.source_identity?.price_basis]||'시세 기준 확인 중')}</p></details>`;
  mount(root);
  const host=root.querySelector('.trend-chart'),borders=root.querySelector('.trend-borders'),quoteBorders=root.querySelector('[data-trend-quote-borders]');let drawnWidth=0;
  const paint=()=>{const m=trendChartModel(detail,period,scale,host.clientWidth||1000),analysis=detail.analyses[scale][String(period)];drawnWidth=host.clientWidth;
    root.querySelectorAll('[data-trend-period]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.trendPeriod)===period)));root.querySelectorAll('[data-trend-scale]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendScale===scale)));
    if(!m){host.innerHTML=`<p class="trend-hold">${esc(trendReasons(analysis.reason_codes))}</p>`;borders.innerHTML='';if(quoteBorders)quoteBorders.innerHTML='';return;}
    host.innerHTML=trendSvg(detail,m,asset)+'<p data-trend-readout class="trend-readout" aria-live="polite"></p>';bindTrendChart(host,detail,m,asset,scale);
    borders.innerHTML=(research?[['down',`${asset.last_session} 일봉 기준 아래 경계`],['up',`${asset.last_session} 일봉 기준 위 경계`]]:[['down',stale?'당시 아래 경계':'아래 경계'],['up',stale?'당시 위 경계':'위 경계'],['broken',stale?'당시 이탈한 선':'이미 이탈한 선']]).map(([key,title])=>`<section><h3>${title}</h3>${analysis.borders[key].length?analysis.borders[key].slice(0,3).map((row,index)=>`<article data-trend-border="${esc(row.line_id)}"><span>${index+1}차 · ${esc(TREND_STATES[row.state]||'확인 중')}</span><strong>${esc(trendPrice(row.price,asset))}</strong><small>${row.geometry_status==='candidate'?'후보 · ':''}접촉 ${esc(row.touch_count)}회 · ${row.direction==='rising'?'상승':'하락'}선</small></article>`).join(''):'<p>해당 경계 없음</p>'}</section>`).join('');if(quoteBorders&&m.quote){const quote=detail.intraday_quote,rows=trendQuoteBorders(analysis,quote,scale);quoteBorders.innerHTML=`<h3 class="trend-quote-boundary-title">시세 시각의 추세선 연장 경계</h3><p class="trend-note">${esc(quote.date)} ${esc(quote.time||'')} · 별도 장중 관측 ${esc(trendPrice(quote.price,asset))} 기준 · 일봉 경계와 기준일이 다릅니다.</p><div class="trend-borders" data-research="true">${[['down','관측 가격 아래'],['up','관측 가격 위']].map(([key,title])=>`<section><h3>${title}</h3>${rows[key].length?rows[key].map((row,index)=>`<article data-trend-quote-border="${esc(row.line_id)}"><span>${index+1}차 · 해당 날짜의 선 연장</span><strong>${esc(trendPrice(row.price,asset))}</strong><small>${row.geometry_status==='candidate'?'후보 · ':''}접촉 ${esc(row.touch_count)}회 · ${row.direction==='rising'?'상승':'하락'}선</small></article>`).join(''):'<p>해당 경계 없음</p>'}</section>`).join('')}</div>`;}};
  root.querySelectorAll('[data-trend-period]').forEach(button=>button.onclick=()=>{period=Number(button.dataset.trendPeriod);paint();});root.querySelectorAll('[data-trend-scale]').forEach(button=>button.onclick=()=>{scale=button.dataset.trendScale;paint();});paint();
  if(globalThis.ResizeObserver){TRENDLINES_RESIZE=new ResizeObserver(()=>{if(!root.isConnected){TRENDLINES_RESIZE?.disconnect();TRENDLINES_RESIZE=null;return;}if(Math.abs(host.clientWidth-drawnWidth)>2)paint();});TRENDLINES_RESIZE.observe(host);}
}
globalThis.TrendlineUI={ensure:ensureTrendlineData,render:renderTrendlinePage,validate:trendValidateDetail,cleanup(){if(TRENDLINES_RESIZE){TRENDLINES_RESIZE.disconnect();TRENDLINES_RESIZE=null;}}};

})();
