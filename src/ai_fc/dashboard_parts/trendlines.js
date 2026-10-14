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
const TREND_LOCAL_BASE='http://127.0.0.1:8878/api/private-trendlines/';
const TREND_IMPORT_TRANSPORT=Symbol('private_import_transport');
const TREND_VIEW_OPTIONS=new Map();
const TREND_FULL_DETAILS=new Map();
let TREND_LOCAL_ENABLED=readTrendLocalPreference(),TREND_LOCAL_SESSION=null,TREND_LOCAL_EPOCH=0;
function readTrendLocalPreference(){return ['https://sung-jinpark.github.io','http://127.0.0.1:8878'].includes(globalThis.location?.origin);}
function trendLocalVisible(){return typeof document==='undefined'||document.visibilityState!=='hidden';}
function trendLocalCurrent(session,sequence=session.sequence){return TREND_LOCAL_SESSION===session&&session.epoch===TREND_LOCAL_EPOCH&&session.active&&session.root.isConnected&&sequence===session.sequence&&TREND_LOCAL_ENABLED;}
function trendLocalKst(value){return value?new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',dateStyle:'short',timeStyle:'medium'}).format(new Date(value)):'확인 대기';}
function validateTrendLocalStatus(value,assetId){
  const aware=value=>value===null||typeof value==='string'&&/(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));
  if(value?.schema_version!==1||value.contract_id!=='trendlines_local_status_v1'||value.publication_scope!=='private_only'||typeof value.running!=='boolean'||typeof value.refresh_in_progress!=='boolean'||!aware(value.next_refresh_kst)||!Array.isArray(value.assets)||value.assets.length!==7)throw new Error('로컬 갱신 상태를 확인하지 못했습니다');
  const ids=new Set();
  for(const row of value.assets){
    if(!TREND_ASSETS.some(asset=>asset[0]===row?.asset_id)||ids.has(row.asset_id)||!['ready','stale','missing','hold','refreshing'].includes(row.status)||typeof row.stale!=='boolean'||!['last_success','last_attempt','source_asof','next_refresh_kst'].every(key=>aware(row[key]))||row.observation_through!==null&&!/^\d{4}-\d{2}-\d{2}$/.test(row.observation_through||'')||!['reason','error'].every(key=>row[key]===null||typeof row[key]==='string'&&row[key].length<=256))throw new Error('로컬 갱신 상태의 자산 기준이 올바르지 않습니다');
    ids.add(row.asset_id);
  }
  if(ids.size!==7)throw new Error('로컬 갱신 상태의 자산이 누락됐습니다');
  return value.assets.find(row=>row.asset_id===assetId);
}
async function readTrendLocalResponse(response,limit){
  if(!response.ok)throw new Error(response.status===404?'이 자산의 로컬 자료를 준비하고 있습니다':'로컬 갱신 서비스가 응답하지 않습니다');
  const stated=response.headers?.get('content-length');
  if(stated!==null&&stated!==undefined&&(!/^\d+$/.test(stated)||Number(stated)>limit))throw new Error('로컬 응답이 크기 제한을 넘었습니다');
  if(!response.body?.getReader){const raw=await response.text();if(new TextEncoder().encode(raw).length>limit)throw new Error('로컬 응답이 크기 제한을 넘었습니다');return raw;}
  const reader=response.body.getReader(),decoder=new TextDecoder('utf-8',{fatal:true});let raw='',size=0;
  try{while(true){const part=await reader.read();if(part.done)break;size+=part.value.byteLength;if(size>limit)throw new Error('로컬 응답이 크기 제한을 넘었습니다');raw+=decoder.decode(part.value,{stream:true});}return raw+decoder.decode();}catch(error){await reader.cancel().catch(()=>{});throw error;}
}
function assertTrendLocalRevision(current,incoming,status){
  const stamp=value=>BigInt(Date.parse(value))*1000000n+BigInt((value.match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1]||'').padEnd(9,'0').slice(3,9)||'0');
  if(current&&stamp(incoming.as_of)<stamp(current.as_of)||status.source_asof&&stamp(incoming.as_of)<stamp(status.source_asof))throw new Error('이전 기준의 응답을 받아 마지막 정상 차트를 유지합니다');
}
function paintTrendLocalStatus(session){
  const host=session.root.querySelector('[data-trend-local-message]');if(!host)return;
  const detail=TREND_PRIVATE_DETAILS.get(session.assetId),labels={idle:'시세 확인 대기',checking:'시세 확인 중',connected:'자동 갱신',stale:'최근 일봉 갱신 지연',paused:'갱신 대기',offline:'시세 확인 지연',invalid:'자료 검증 보류'};
  host.textContent=[labels[session.phase]||labels.idle,session.problem,detail&&['offline','invalid','paused','stale'].includes(session.phase)?`${detail.observation_through} 확인 자료 유지`:null].filter(Boolean).join(' · ');
  host.dataset.trendStatus=session.phase;
  const empty=session.root.querySelector('[data-trend-empty]');
  if(empty)empty.innerHTML=trendEmptyMarkup(session.assetId,session.phase,session.problem);
}
function pauseTrendLocalSession(session){clearTimeout(session.timer);session.timer=null;session.sequence++;session.controller?.abort();session.fullSequence=(session.fullSequence||0)+1;session.fullController?.abort();}
function stopTrendLocalSession(){const session=TREND_LOCAL_SESSION;if(!session)return;session.active=false;pauseTrendLocalSession(session);document.removeEventListener('visibilitychange',session.visibility);window.removeEventListener('pagehide',session.unload);TREND_LOCAL_SESSION=null;TREND_LOCAL_EPOCH++;}
function scheduleTrendLocalRefresh(session,delay=60000){if(!trendLocalCurrent(session)||!trendLocalVisible())return;clearTimeout(session.timer);session.timer=setTimeout(()=>refreshTrendLocalSession(session),delay);}
async function refreshTrendLocalSession(session){
  if(!trendLocalCurrent(session)||!trendLocalVisible())return;
  if(session.inflight!==null){session.resumePending=true;return session.inflight;}
  const sequence=++session.sequence,controller=new AbortController();session.controller=controller;session.phase='checking';session.problem=null;
  const deadline=setTimeout(()=>controller.abort(),8000),options={method:'GET',mode:'cors',credentials:'omit',cache:'no-store',redirect:'error',targetAddressSpace:'loopback',signal:controller.signal};
  const pending=(async()=>{
    const status=JSON.parse(await readTrendLocalResponse(await fetch(TREND_LOCAL_BASE+'status',options),32768));
    if(!trendLocalCurrent(session,sequence))return;if(controller.signal.aborted)throw new DOMException('Aborted','AbortError');
    const row=validateTrendLocalStatus(status,session.assetId);session.row=row;
    if(!status.running)throw new Error('이 PC의 로컬 갱신 서비스를 실행해 주세요');
    const raw=await readTrendLocalResponse(await fetch(TREND_LOCAL_BASE+session.assetId,options),524288),incoming=await parseTrendPrivateImport(raw,session.assetId);
    if(!trendLocalCurrent(session,sequence))return;if(controller.signal.aborted)throw new DOMException('Aborted','AbortError');
    const current=TREND_PRIVATE_DETAILS.get(session.assetId);assertTrendLocalRevision(current,incoming,row);
    const changed=current?.content_hash!==incoming.content_hash;
    TREND_PRIVATE_DETAILS.set(session.assetId,incoming);
    session.phase=row.stale||row.error?'stale':'connected';session.problem=row.error?'마지막 확인 자료를 표시합니다':null;
    if(changed)session.onData();
  })().catch(error=>{
    if(!trendLocalCurrent(session,sequence))return;
    const validation=!(error instanceof TypeError||error.name==='AbortError')&&/기준|검수|무결성|형식|올바|제한|계산|이전|자산|내용/.test(String(error.message));
    session.phase=trendLocalVisible()?(validation?'invalid':'offline'):'paused';session.problem=validation?'가격 기준을 확인한 뒤 갱신합니다':'자료를 불러오지 못했습니다';session.lastError=String(error.message||error);
  }).finally(()=>{
    clearTimeout(deadline);
    if(session.inflight===pending)session.inflight=null;
    if(!session.active||TREND_LOCAL_SESSION!==session)return;
    paintTrendLocalStatus(session);const resume=session.resumePending;session.resumePending=false;scheduleTrendLocalRefresh(session,resume?0:60000);
    if(session.fullMounted&&trendLocalVisible())refreshTrendFullSession(session);
  });
  session.inflight=pending;paintTrendLocalStatus(session);return pending;
}
function bindTrendLocalConnection(root,initial,reuse=null){
  const assetId=initial.asset||'sk-hynix';if(!Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId))return null;
  let session=reuse;
  if(!session||session!==TREND_LOCAL_SESSION||!session.active){
    stopTrendLocalSession();
    session={assetId,initial,root,epoch:++TREND_LOCAL_EPOCH,active:true,sequence:0,inflight:null,controller:null,timer:null,row:null,problem:null,resumePending:false,phase:TREND_LOCAL_ENABLED?'checking':'idle'};
    TREND_LOCAL_SESSION=session;
    session.visibility=()=>{if(!session.active||!TREND_LOCAL_ENABLED)return;if(!trendLocalVisible()){pauseTrendLocalSession(session);session.phase='paused';paintTrendLocalStatus(session);}else if(TREND_LOCAL_ENABLED)refreshTrendLocalSession(session);};
    session.unload=()=>stopTrendLocalSession();document.addEventListener('visibilitychange',session.visibility);window.addEventListener('pagehide',session.unload);
    Promise.resolve().then(()=>{if(TREND_LOCAL_ENABLED&&trendLocalCurrent(session))refreshTrendLocalSession(session);});
  }
  session.root=root;session.initial=initial;session.onData=()=>renderTrendlinePage(initial,null,session);
  paintTrendLocalStatus(session);return session;
}
async function parseTrendPrivateImport(raw,assetId){
  const encoder=new TextEncoder(),sha=/^[a-f0-9]{64}$/;
  if(typeof raw!=='string'||encoder.encode(raw).length>524288)throw new Error('개인 연구 파일이 512KiB 제한을 넘었습니다');
  const envelope=JSON.parse(raw),v1=envelope?.schema_version===1&&envelope.contract_id==='trendlines_private_import_v1',v2=envelope?.schema_version===2&&envelope.contract_id==='trendlines_private_import_v2';
  if((!v1&&!v2)||envelope.publication_scope!=='private_only'||envelope.asset_id!==assetId||!Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId)||typeof envelope.payload_json!=='string'||!sha.test(envelope.payload_sha256||'')||encoder.encode(envelope.payload_json).length>262144)throw new Error('현재 자산의 개인 연구 파일 형식이 아닙니다');
  if(!globalThis.crypto?.subtle)throw new Error('이 브라우저에서 파일의 무결성을 확인할 수 없습니다');
  const digest=await crypto.subtle.digest('SHA-256',encoder.encode(envelope.payload_json)),hash=[...new Uint8Array(digest)].map(value=>value.toString(16).padStart(2,'0')).join('');
  if(hash!==envelope.payload_sha256)throw new Error('개인 연구 파일 내용이 저장된 검수 기준과 다릅니다');
  const detail=JSON.parse(envelope.payload_json),identity=TREND_PRIVATE_IDENTITIES[assetId];let originalHash=hash;
  if(v2){
    const packed=detail?.bars_packed,columns=['session','session_index','open','high','low','close','bar_id'];
    const prefix=packed&&Object.hasOwn(packed,'bar_id_prefix'),keys=prefix?'bar_id_prefix,columns,rows':'columns,rows';
    if(typeof envelope.original_detail_sha256!=='string'||!sha.test(envelope.original_detail_sha256)||detail?.original_detail_sha256!==envelope.original_detail_sha256||Object.hasOwn(detail,'bars')||Object.hasOwn(detail,'content_hash')||!packed||Array.isArray(packed)||Object.keys(packed).sort().join(',')!==keys||prefix&&packed.bar_id_prefix!=='research-bar-'||!Array.isArray(packed.columns)||packed.columns.length!==columns.length||packed.columns.some((name,index)=>name!==columns[index])||!Array.isArray(packed.rows)||packed.rows.length>756||packed.rows.some(row=>!Array.isArray(row)||row.length!==columns.length||prefix&&(typeof row[6]!=='string'||!sha.test(row[6]))))throw new Error('압축된 개인 연구 파일의 일봉 기준이 올바르지 않습니다');
    detail.bars=packed.rows.map(row=>Object.fromEntries(columns.map((key,index)=>[key,prefix&&index===6?packed.bar_id_prefix+row[index]:row[index]])));
    originalHash=envelope.original_detail_sha256;delete detail.bars_packed;delete detail.original_detail_sha256;
  }else if(Object.hasOwn(detail||{},'bars_packed')||Object.hasOwn(detail||{},'original_detail_sha256'))throw new Error('개인 연구 파일의 전송 형식이 올바르지 않습니다');
  const asset=detail?.asset;
  if(!detail||Object.hasOwn(detail,'content_hash')||detail.asset_id!==assetId||detail.snapshot_id!==envelope.snapshot_id||detail.status!=='unverified_display'||detail.publication_scope!=='private_only'||!/^research-snapshot-[a-f0-9]{64}$/.test(detail.snapshot_id||'')||!/^research-receipt-[a-f0-9]{64}$/.test(detail.receipt_id||'')||!sha.test(detail.raw_sha256||'')||!sha.test(detail.research_archive_sha256||'')||!sha.test(detail.source_snapshot_hash||'')||asset?.asset_id!==assetId||asset.identity!==identity[0]||asset.provider_symbol!==identity[1]||asset.currency!==identity[2]||asset.calendar_id!==identity[3]||detail.source_identity?.source_id!=='yahoo_public_history_html'||detail.source_identity?.provider_symbol!==identity[1]||detail.source_identity?.calendar_id!==identity[3])throw new Error('개인 연구 파일의 자산 또는 원문 근거가 올바르지 않습니다');
  const source=trendSourceUrl(detail.source_url),sourceUrl=source?new URL(source):null;
  const secrets=new Set(['api_key','apikey','api-key','key','token','access_token','accesstoken','api_token','secret','client_secret','password','registrationkey','user_id','userid','authorization']);
  if(!sourceUrl||sourceUrl.protocol!=='https:'||sourceUrl.hostname!=='finance.yahoo.com'||sourceUrl.username||sourceUrl.password||sourceUrl.hash||!['','443'].includes(sourceUrl.port)||[...sourceUrl.searchParams.keys()].some(key=>secrets.has(key.toLowerCase()))||decodeURIComponent(sourceUrl.pathname)!==`/quote/${identity[1]}/history/`)throw new Error('개인 연구 파일의 시세 원문이 올바르지 않습니다');
  const aware=value=>typeof value==='string'&&/(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));
  if(!aware(detail.as_of)||!aware(detail.knowledge_cutoff)||!aware(detail.retrieved_at)||Date.parse(detail.knowledge_cutoff)!==Date.parse(detail.as_of)||Date.parse(detail.retrieved_at)>Date.parse(detail.as_of)||Date.parse(detail.as_of)>Date.now())throw new Error('개인 연구 파일의 기준 시각이 올바르지 않습니다');
  if(detail.intraday_quote&&(!aware(detail.intraday_quote.observed_at)||!aware(detail.intraday_quote.retrieved_at)||Date.parse(detail.intraday_quote.observed_at)>Date.parse(detail.intraday_quote.retrieved_at)||Date.parse(detail.intraday_quote.retrieved_at)>Date.parse(detail.as_of)||detail.intraday_quote.currency!==identity[2]||!Number.isInteger(detail.intraday_quote.session_index)||trendSourceUrl(detail.intraday_quote.source_url)!==source))throw new Error('개인 연구 파일의 별도 관측 근거가 올바르지 않습니다');
  detail.content_hash=originalHash;
  Object.defineProperty(detail,TREND_IMPORT_TRANSPORT,{value:{schema_version:envelope.schema_version,payload_sha256:hash,original_detail_sha256:originalHash},enumerable:false});
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
const TREND_BASES={split_adjusted:'주식분할 조정 시세',split_adjusted_price:'주식분할 조정 시세',published_spot_price:'일별 현물 시세',published_price_index:'공식 가격 지수',provider_reported_ohlc_current_vintage:'현재 공개된 일별 시세 이력'};
const TREND_STATES={active:'유지',break_pending:'이탈 확인 중',broken:'이탈',reclaim_pending:'복귀 확인 중',reclaimed:'복귀',research_reference:'현재 자료로 그린 참고선'};
const TREND_REASON_LABELS={latest_completed_session_missing:'최근 마감 시세가 아직 확인되지 않았습니다.',capture_rejected_last_good_preserved:'새 시세의 검수가 보류돼 마지막 검수 자료를 유지합니다.',missing_approved_ohlc:'공개 배포가 확인된 일별 시세를 기다리고 있습니다.',source_rights_pending:'시세의 공개 이용 조건을 확인하고 있습니다.',source_unavailable:'시세를 가져오지 못했습니다.',insufficient_history:'이 기간의 추세선을 확인할 과거 시세가 부족합니다.',insufficient_pivots:'확정된 고점·저점이 부족해 빗각선을 그리지 않았습니다.',no_valid_lines:'이 기간에서 검증을 통과한 빗각선이 없습니다.',stale_source:'새로 마감된 시세가 아직 확인되지 않았습니다.',stale_snapshot:'최근 마감 시세로 갱신이 필요합니다.',invalid_snapshot:'가격 자료 검증을 완료하지 못했습니다.'};
function trendReasons(codes){return [...new Set((codes||[]).map(code=>TREND_REASON_LABELS[code]||'가격 자료 검증을 완료하지 못했습니다.'))].join(' ')||'검증된 시세가 준비되면 자동으로 갱신합니다.';}
function trendPrice(value,asset){return `${Number(value).toLocaleString('ko-KR',{maximumFractionDigits:asset?.price_unit==='KRW'||asset?.currency==='KRW'?0:2})}${['points','index_points'].includes(asset?.price_unit)?' pt':asset?.currency==='KRW'?'원':asset?.currency==='USD'?'달러':''}`;}
function trendSourceUrl(value){try{const url=new URL(String(value));return ['https:','http:'].includes(url.protocol)?url.href:null;}catch(_){return null;}}
function trendResearchMarkup(detail,asset){
  const url=trendSourceUrl(detail.source_url||detail.source_identity?.source_url),quote=detail.intraday_quote;
  return `<details class="trend-data-meta"><summary>자료 정보</summary><p>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">원천 시세 ↗</a>`:'원천 확인 중'} · 확인 ${esc(trendLocalKst(detail.retrieved_at||detail.as_of))}</p><p>일봉 ${esc(detail.observation_through||detail.bars.at(-1).session)} 기준${quote?` · 장중 관측 ${esc(quote.date)} ${esc(quote.time||'')} ${esc(trendPrice(quote.price,asset))}`:''}</p>${detail.status==='unverified_display'?'<p>현재 공개 시세로 그린 참고선 · 가격 조정 검증 전</p>':''}${(detail.gaps||[]).length?`<p>미표시 일봉 ${(detail.gaps||[]).length}개 · 확인되지 않은 가격은 채우지 않습니다.</p>`:''}</details>`;
}
function trendEmptyMarkup(assetId,phase='checking',problem=null){
  const known=TREND_ASSETS.some(row=>row[0]===assetId),loading=['checking','idle'].includes(phase)&&Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId);
  const title=!known?'자산을 선택해 주세요':assetId==='mag7'?'차트 자료 준비 중':loading?'시세를 확인하고 있습니다':phase==='invalid'?'자료 검증 보류':'차트 자료를 불러오지 못했습니다';
  const text=!known?'위에서 자산을 선택하면 추세선을 확인할 수 있습니다.':assetId==='mag7'?'같은 기준의 가격 자료가 준비되면 표시합니다.':loading?'가격과 추세선을 곧 표시합니다.':problem||'자료가 확인되면 자동으로 다시 표시합니다.';
  return `<div class="trend-empty-content${loading?' is-loading':''}"><span class="trend-empty-icon" aria-hidden="true">${loading?'⋯':'—'}</span><h2>${title}</h2><p>${esc(text)}</p></div>`;
}
function trendReference(detail){const last=detail.bars.at(-1),quote=detail.intraday_quote;return quote&&quote.session_index>last.session_index?{price:quote.price,index:quote.session_index,date:quote.date,time:quote.time||'',kind:'장중 관측',quote:true}:{price:last.close,index:last.session_index,date:last.session||last.session_date,time:'',kind:'종가',quote:false};}
function trendInsightModel(detail,period,scale){
  const analysis=detail.analyses[scale]?.[String(period)];if(analysis?.status!=='ready')return null;
  return trendInsightFromAnalysis(detail,analysis,scale);
}
function trendInsightFromAnalysis(detail,analysis,scale){
  const reference=trendReference(detail),rows=reference.quote?trendQuoteBorders(analysis,detail.intraday_quote,scale):analysis.borders;
  const distance=row=>row?{...row,distance_percent:(row.price/reference.price-1)*100}:null;
  return {reference,down:distance(rows.down[0]),up:distance(rows.up[0]),research:detail.status==='unverified_display'};
}
function trendInsightMarkup(detail,period,scale,asset,full=false,selectedAnalysis=null){
  const analysis=selectedAnalysis||(full?detail.analyses[scale]?.full:null),model=analysis?.status==='ready'?trendInsightFromAnalysis(detail,analysis,scale):full?null:trendInsightModel(detail,period,scale);if(!model)return '<section class="trend-insights"><h3>가격과 가까운 경계</h3><p class="trend-insight-note">이 기간의 추세선 자료를 준비하고 있습니다.</p></section>';
  return `<section class="trend-insights"><div class="trend-insight-heading"><h3>가격과 가까운 경계</h3><span>${esc(model.reference.date)}${model.reference.time?' '+esc(model.reference.time):''} · ${model.reference.kind} 기준</span></div><div class="trend-insight-grid">${[['down','아래 경계'],['up','위 경계']].map(([side,title])=>{const row=model[side],distance=row?`${row.distance_percent>0?'+':''}${row.distance_percent.toLocaleString('ko-KR',{minimumFractionDigits:2,maximumFractionDigits:2})}%`:null;return `<article data-trend-insight="${side}"><span>${title}</span>${row?`<strong data-trend-border="${esc(row.line_id)}">${esc(trendPrice(row.price,asset))}</strong><p data-trend-distance="${side}">${esc(distance)} <small>관측 가격 대비</small></p><small>${row.side==='support'?'지지':'저항'}선 · ${row.geometry_status==='candidate'?'후보선':`접촉 ${esc(row.touch_count)}회`}</small>`:'<strong>—</strong><p>가까운 경계 없음</p>'}</article>`;}).join('')}</div><p class="trend-insight-note">${model.research?'현재 자료로 그린 참고선이며, 추세 이탈을 확정하지 않습니다.':'기준 가격과 경계의 거리를 비교합니다.'}</p></section>`;
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
      const available=Number.isFinite(expectedCurrent)&&expectedCurrent>0;
      if(available?(typeof line.current_price!=='number'||!Number.isFinite(line.current_price)||line.current_price<=0||Math.abs(line.current_price-expectedCurrent)>Math.max(1e-6,Math.abs(expectedCurrent)*1e-10)):(line.current_price!==null||line.points.some(point=>point.index===detail.bars.at(-1).session_index)))throw new Error('빗각선 기준일 가격이 계산과 다릅니다');
    }
    for(const key of ['down','up','broken'])if(!Array.isArray(analysis.borders[key])||analysis.borders[key].some(row=>typeof row.price!=='number'||!Number.isFinite(row.price)||row.price<=0))throw new Error('가격 경계가 올바르지 않습니다');
    for(const key of ['down','up','broken'])for(const row of analysis.borders[key]){const line=analysis.lines.find(line=>line.line_id===row.line_id);if(!line||typeof line.current_price!=='number'||!Number.isFinite(line.current_price)||line.current_price<=0||Math.abs(row.price-line.current_price)>Math.max(1e-6,Math.abs(row.price)*1e-10))throw new Error('가격 경계가 빗각선과 다릅니다');}
  }
  return detail;
}
function trendLinePrice(line,index,scale){const value=line.intercept+line.slope*(index-line.coordinate_origin_index);return scale==='log'?Math.exp(value):value;}
function trendLineReadout(line,index,scale,asset){const price=trendLinePrice(line,index,scale);return `${line.side==='support'?'지지':'저항'} ${Number.isFinite(price)&&price>0?trendPrice(price,asset):'연장값 없음'}`;}
function trendQuoteBorders(analysis,quote,scale){
  const rows=analysis.lines.map(line=>({...line,price:trendLinePrice(line,quote.session_index,scale)})).filter(row=>Number.isFinite(row.price)&&row.price>0);
  return {down:rows.filter(row=>row.price<=quote.price).sort((a,b)=>b.price-a.price||a.line_id.localeCompare(b.line_id)).slice(0,3),up:rows.filter(row=>row.price>quote.price).sort((a,b)=>a.price-b.price||a.line_id.localeCompare(b.line_id)).slice(0,3)};
}
function trendChartModel(detail,period=63,scale='linear',width=1000){
  trendValidateDetail(detail);
  const analysis=detail.analyses[scale]?.[String(period)];
  if(analysis?.status!=='ready')return null;
  return trendPlotModel(detail,analysis,detail.bars.slice(-period),scale,width);
}
function trendDirectionalAnalysis(detail,analysis,scale,direction='all'){
  if(direction==='all'||analysis.status!=='ready')return analysis;
  const lines=analysis.lines.filter(line=>line.direction===direction),reference=trendReference(detail);
  return {...analysis,lines,borders:{...trendQuoteBorders({lines},{price:reference.price,session_index:reference.index},scale),broken:analysis.borders.broken.filter(row=>lines.some(line=>line.line_id===row.line_id))}};
}
function trendLineDetailsMarkup(analysis,reference,scale,asset){return (analysis.lines||[]).map(line=>{const anchors=[line.first_anchor,line.second_anchor].filter(anchor=>anchor&&typeof anchor.price==='number');return `<p>${line.side==='support'?'지지':'저항'} · ${anchors.map(anchor=>`${esc(anchor.session)} ${esc(trendPrice(anchor.price,asset))}`).join(' → ')} · ${esc(trendLineReadout(line,reference.index,scale,asset))}</p>`;}).join('');}
function trendFullEmptyMarkup(phase='checking'){const delayed=['offline','invalid','paused'].includes(phase);return `<div class="trend-empty trend-period-empty" role="status"><div class="trend-empty-content"><span class="trend-empty-icon" aria-hidden="true">${delayed?'—':'⋯'}</span><h3>${phase==='invalid'?'전체 자료 검증 보류':delayed?'전체 자료 갱신 확인 중':'전체 추세선을 확인하고 있습니다'}</h3><p>현재 구간의 차트는 아래에서 확인할 수 있습니다.</p></div></div>`;}
async function trendExactSha(raw){const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw));return [...new Uint8Array(digest)].map(value=>value.toString(16).padStart(2,'0')).join('');}
function trendSameValue(left,right){if(left===right)return true;if(!left||!right||typeof left!=='object'||typeof right!=='object'||Array.isArray(left)!==Array.isArray(right))return false;const a=Object.keys(left).sort(),b=Object.keys(right).sort();return a.length===b.length&&a.every((key,index)=>key===b[index]&&trendSameValue(left[key],right[key]));}
function trendIsoDate(value){const stamp=typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)?Date.parse(value+'T00:00:00Z'):NaN;return Number.isFinite(stamp)&&new Date(stamp).toISOString().slice(0,10)===value;}
function trendUniqueJson(raw){
  let index=0;const fail=()=>{throw new Error('전체 자료의 JSON 형식 또는 중복 필드가 올바르지 않습니다');},space=()=>{while(/\s/.test(raw[index]||'')&&index<raw.length)index++;};
  const string=()=>{const start=index++;while(index<raw.length){const char=raw[index++];if(char==='\\'){index++;continue;}if(char==='"')return JSON.parse(raw.slice(start,index));}fail();};
  const value=depth=>{if(depth>40)fail();space();const char=raw[index];if(char==='"'){string();return;}if(char==='{'||char==='['){index++;space();const object=char==='{',end=object?'}':']',keys=new Set();if(raw[index]===end){index++;return;}while(index<raw.length){if(object){if(raw[index]!=='"')fail();const key=string();if(keys.has(key))fail();keys.add(key);space();if(raw[index++]!==':')fail();}value(depth+1);space();if(raw[index]===end){index++;return;}if(raw[index++]!==',')fail();space();}fail();}const match=/^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(raw.slice(index));if(!match)fail();index+=match[0].length;};
  value(0);space();if(index!==raw.length)fail();return JSON.parse(raw);
}
async function parseTrendFullTransport(raw,assetId,snapshotId=null){
  const encoder=new TextEncoder(),sha=/^[a-f0-9]{64}$/;
  if(typeof raw!=='string'||encoder.encode(raw).length>524288||!globalThis.crypto?.subtle)throw new Error('전체 자료의 크기 또는 무결성 검수 기준이 올바르지 않습니다');
  const envelope=trendUniqueJson(raw),keys='asset_id,contract_id,payload_json,payload_sha256,publication_scope,schema_version,snapshot_id';
  if(!envelope||Object.keys(envelope).sort().join(',')!==keys||envelope.schema_version!==1||envelope.contract_id!=='trendlines_private_full_transport_v1'||envelope.publication_scope!=='private_only'||envelope.asset_id!==assetId||!Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId)||!/^research-full-snapshot-[a-f0-9]{64}$/.test(envelope.snapshot_id||'')||snapshotId&&envelope.snapshot_id!==snapshotId||typeof envelope.payload_json!=='string'||encoder.encode(envelope.payload_json).length>262144||!sha.test(envelope.payload_sha256||''))throw new Error('전체 자료의 전송 형식이 올바르지 않습니다');
  if(await trendExactSha(envelope.payload_json)!==envelope.payload_sha256)throw new Error('전체 자료가 저장된 검수 기준과 다릅니다');
  const body=trendUniqueJson(envelope.payload_json);
  if(body?.schema_version!==1||body.publication_scope!=='private_only'||body.asset_id!==assetId||body.snapshot_id!==envelope.snapshot_id)throw new Error('전체 자료의 자산 또는 기준이 올바르지 않습니다');
  return {body,payload_sha256:envelope.payload_sha256,envelope_sha256:await trendExactSha(raw)};
}
function validateTrendFullManifest(manifest,current){
  const sha=/^[a-f0-9]{64}$/;
  if(!current||manifest.contract_id!=='trendlines_private_full_manifest_v1'||manifest.full_scope!=='all_captured_finalized_sessions'||manifest.points_encoding!=='equations'||manifest.source_snapshot_id!==current.snapshot_id||manifest.source_engine_snapshot_id!==current.engine_snapshot_id||manifest.source_engine_content_hash!==current.source_snapshot_hash||!Number.isInteger(manifest.bar_count)||manifest.bar_count<2||manifest.bar_count>4096||!sha.test(manifest.full_config_sha256||''))throw new Error('전체 추세선의 원천 기준이 현재 자료와 다릅니다');
  for(const key of ['asset_id','asset','as_of','knowledge_cutoff','observation_through','receipt_id','raw_sha256','research_archive_sha256','source_snapshot_hash','source_identity','source_url','retrieved_at','intraday_quote','gaps','row_validation_policy','rejected_rows'])if(!trendSameValue(manifest[key]??null,current[key]??null))throw new Error('전체 추세선의 가격 원천 또는 기준 시각이 다릅니다');
  if(!trendIsoDate(manifest.observation_start)||manifest.observation_start>manifest.observation_through||manifest.chunk_size!==512||!sha.test(manifest.bars_sha256||'')||!trendSameValue(manifest.full_parameters,{bars:manifest.bar_count,minimum_bars:771,left:10,right:10,min_anchor_gap:60})||!Array.isArray(manifest.chunks)||manifest.chunks.length!==Math.ceil(manifest.bar_count/512)||!manifest.analyses||Object.keys(manifest.analyses).sort().join(',')!=='linear,log')throw new Error('전체 확보 기간 또는 일봉 수가 올바르지 않습니다');
  let prior=-Infinity,total=0;
  for(const [index,pin] of manifest.chunks.entries()){
    if(Object.keys(pin).sort().join(',')!=='chunk_index,count,end_index,envelope_sha256,payload_sha256,start_index'||pin.chunk_index!==index||pin.count!==Math.min(512,manifest.bar_count-total)||!Number.isInteger(pin.start_index)||pin.start_index<0||!Number.isInteger(pin.end_index)||pin.start_index<=prior||pin.end_index<pin.start_index||!sha.test(pin.payload_sha256||'')||!sha.test(pin.envelope_sha256||''))throw new Error('전체 일봉 조각의 검수 기준이 올바르지 않습니다');
    total+=pin.count;prior=pin.end_index;
  }
  return manifest;
}
async function parseTrendFullChunk(raw,manifest,pin){
  const decoded=await parseTrendFullTransport(raw,manifest.asset_id,manifest.snapshot_id),body=decoded.body,packed=body.bars_packed,columns=['session','session_index','open','high','low','close','bar_id'];
  if(decoded.envelope_sha256!==pin.envelope_sha256||decoded.payload_sha256!==pin.payload_sha256||body.contract_id!=='trendlines_private_full_bars_v1'||body.source_snapshot_id!==manifest.source_snapshot_id||['chunk_index','count','start_index','end_index'].some(key=>body[key]!==pin[key])||!packed||Object.keys(packed).sort().join(',')!=='bar_id_prefix,columns,rows'||packed.bar_id_prefix!=='research-bar-'||!trendSameValue(packed.columns,columns)||!Array.isArray(packed.rows)||packed.rows.length!==pin.count||packed.rows.some(row=>!Array.isArray(row)||row.length!==7||!trendIsoDate(row[0])||!Number.isInteger(row[1])||row[1]<0||!row.slice(2,6).every(price=>typeof price==='number'&&Number.isFinite(price)&&price>0)||row[4]>Math.min(row[2],row[5])||row[3]<Math.max(row[2],row[5])||!/^[a-f0-9]{64}$/.test(row[6]||'')))throw new Error('전체 일봉 조각이 검수 기준과 다릅니다');
  const bars=packed.rows.map(row=>Object.fromEntries(columns.map((key,index)=>[key,index===6?'research-bar-'+row[index]:row[index]])));
  if(bars[0].session_index!==pin.start_index||bars.at(-1).session_index!==pin.end_index)throw new Error('전체 일봉 조각의 순서가 올바르지 않습니다');
  return bars;
}
function buildTrendFullDetail(manifest,bars,current){
  validateTrendFullManifest(manifest,current);
  if(bars.length!==manifest.bar_count||new Set(bars.map(bar=>bar.bar_id)).size!==bars.length||bars[0].session!==manifest.observation_start||bars.at(-1).session!==manifest.observation_through||!trendSameValue(bars.slice(-current.bars.length),current.bars))throw new Error('전체 일봉과 현재 일봉의 가격 기준이 다릅니다');
  const analyses={},last=bars.at(-1),barMap=new Map(bars.map(bar=>[bar.session_index,bar])),offsets=manifest.asset_id==='bitcoin'?[1,7,30]:[1,5,21];
  for(const scale of ['linear','log']){
    const windows=manifest.analyses[scale],analysis=windows?.full;
    if(!windows||Object.keys(windows).join(',')!=='full'||!analysis||analysis.axis!==scale||analysis.window!==bars.length||!['ready','hold'].includes(analysis.status)||!Array.isArray(analysis.lines)||!analysis.borders||['down','up','broken'].some(side=>!Array.isArray(analysis.borders[side]))||(analysis.events||[]).length||bars.length<771&&analysis.status!=='hold')throw new Error('전체 추세선의 기간 또는 축 기준이 올바르지 않습니다');
    if(analysis.status==='hold'){if((analysis.lines||[]).length||Object.values(analysis.borders||{}).some(rows=>rows.length))throw new Error('보류된 전체 분석에 가격 경계가 포함됐습니다');analyses[scale]={full:analysis};continue;}
    const sessions=analysis.projection_sessions,ids=new Set();
    if(!Array.isArray(sessions)||sessions.length!==3||sessions.some((row,index)=>row.offset!==offsets[index]||row.index!==last.session_index+row.offset||!/^\d{4}-\d{2}-\d{2}$/.test(row.session||'')||row.session<=(index?sessions[index-1].session:last.session)))throw new Error('전체 추세선의 연장 날짜가 올바르지 않습니다');
    const lines=analysis.lines.map(line=>{
      if(line.axis!==scale||line.window!==bars.length||!/^trend-line-[a-f0-9]{32}$/.test(line.line_id||'')||ids.has(line.line_id)||!['rising','falling'].includes(line.direction)||!Array.isArray(line.projections)||line.projections.length!==3)throw new Error('전체 추세선의 빗각선 기준이 올바르지 않습니다');ids.add(line.line_id);
      for(const anchor of [line.first_anchor,line.second_anchor]){const bar=barMap.get(anchor?.index),value=anchor&&trendLinePrice(line,anchor.index,scale);if(!bar||anchor.bar_id!==bar.bar_id||anchor.session!==bar.session||anchor.price!==bar[line.side==='support'?'low':'high']||!Number.isFinite(value)||Math.abs(value-anchor.price)>Math.max(1e-6,Math.abs(anchor.price)*1e-10))throw new Error('전체 추세선의 고점·저점 근거가 올바르지 않습니다');}
      if(line.second_anchor.index-line.first_anchor.index<60)throw new Error('전체 추세선의 기준점 간격이 올바르지 않습니다');
      const points=line.points.map(point=>{const row=point.future===true?sessions.find(row=>row.index===point.index):barMap.get(point.index),price=trendLinePrice(line,point.index,scale);if(typeof point.future!=='boolean'||point.future!==(point.index>last.session_index)||!row||point.session!==row.session||!Number.isFinite(price)||price<=0||typeof point.price!=='number'||Math.abs(price-point.price)>Math.max(1e-6,Math.abs(point.price)*1e-10))throw new Error('전체 추세선 끝점이 계산 기준과 다릅니다');return {...point,price};});
      for(const [index,projection] of line.projections.entries()){const session=sessions[index],point=points.find(row=>row.future&&row.index===projection.index),price=trendLinePrice(line,session.index,scale),available=Number.isFinite(price)&&price>0;if(projection.index!==session.index||projection.offset!==session.offset||projection.session!==session.session||projection.status!==(available?'ready':'unavailable')||(available?(!point||typeof projection.price!=='number'||Math.abs(point.price-projection.price)>Math.max(1e-6,Math.abs(projection.price)*1e-10)):(projection.price!==null||!!point)))throw new Error('전체 추세선의 연장 값이 올바르지 않습니다');}
      const expectedIndices=[...new Set([line.first_anchor.index,line.second_anchor.index,last.session_index,...sessions.map(row=>row.index)].filter(index=>{const price=trendLinePrice(line,index,scale);return Number.isFinite(price)&&price>0;}))].sort((a,b)=>a-b);if(!trendSameValue(points.map(point=>point.index),expectedIndices))throw new Error('전체 추세선 끝점이 누락됐습니다');
      return {...line,points};
    });
    for(const side of ['down','up','broken'])for(const border of analysis.borders[side]){const line=lines.find(row=>row.line_id===border.line_id);if(!line||['side','direction','state','geometry_status','touch_count'].some(key=>border[key]!==line[key]))throw new Error('전체 추세선의 경계 표시 기준이 다릅니다');}
    analyses[scale]={full:{...analysis,lines}};
  }
  const detail={...manifest,bars,analyses},view={...detail,contract_id:'trendlines_research_display_v1',analyses:Object.fromEntries(['linear','log'].map(scale=>[scale,{'63':analyses[scale].full,'252':{status:'hold'},'756':{status:'hold'}}]))};
  trendValidateDetail(view);return detail;
}
async function refreshTrendFullSession(session){
  const current=TREND_PRIVATE_DETAILS.get(session.assetId);
  if(!session.fullMounted||!current||!trendLocalCurrent(session)||!trendLocalVisible())return;
  const key=current.snapshot_id;
  if(session.fullPending&&session.fullSource===key)return session.fullPending;
  session.fullController?.abort();const sequence=(session.fullSequence||0)+1;session.fullSequence=sequence;session.fullSource=key;
  const controller=new AbortController();session.fullController=controller;session.fullPhase='checking';session.onFullData?.();
  const deadline=setTimeout(()=>controller.abort(),20000),options={method:'GET',mode:'cors',credentials:'omit',cache:'no-store',redirect:'error',targetAddressSpace:'loopback',signal:controller.signal};
  const active=()=>trendLocalCurrent(session)&&session.fullSequence===sequence&&!controller.signal.aborted&&TREND_PRIVATE_DETAILS.get(session.assetId)?.snapshot_id===key;
  const pending=(async()=>{
    const decoded=await parseTrendFullTransport(await readTrendLocalResponse(await fetch(TREND_LOCAL_BASE+session.assetId+'/full',options),524288),session.assetId),manifest=validateTrendFullManifest(decoded.body,current);
    if(!active())return;
    const existing=TREND_FULL_DETAILS.get(session.assetId);if(existing?.snapshot_id===manifest.snapshot_id){session.fullPhase='connected';return;}
    const chunks=[];
    for(let index=0;index<manifest.chunks.length;index+=2){const rows=await Promise.all(manifest.chunks.slice(index,index+2).map(async pin=>parseTrendFullChunk(await readTrendLocalResponse(await fetch(TREND_LOCAL_BASE+session.assetId+'/full/'+manifest.snapshot_id+'/bars/'+pin.chunk_index,options),262144),manifest,pin)));if(!active())return;chunks.push(...rows);}
    const detail=buildTrendFullDetail(manifest,chunks.flat(),current);if(!active())return;
    TREND_FULL_DETAILS.set(session.assetId,detail);session.fullPhase='connected';
  })().catch(error=>{if(!trendLocalCurrent(session)||session.fullSequence!==sequence)return;session.fullPhase=trendLocalVisible()?error instanceof TypeError||error.name==='AbortError'?'offline':'invalid':'paused';session.fullError=String(error.message||error);}).finally(()=>{clearTimeout(deadline);if(session.fullPending===pending)session.fullPending=null;if(trendLocalCurrent(session)&&session.fullSequence===sequence)session.onFullData?.();});
  session.fullPending=pending;return pending;
}
function trendPlotModel(detail,analysis,bars,scale,width){
  const first=bars[0].session_index,last=bars.at(-1).session_index;
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
function trendSvg(detail,model,asset,version='current'){
  const m=model,clip=`trend-clip-${detail.asset_id}-${version}`,futureX=m.x(m.last),bodyWidth=Math.max(1,Math.min(8,(m.W-m.L-m.R)/(m.end-m.first+1)*.55));
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
  const paint=index=>{selected=Math.max(0,Math.min(entries.length-1,index));const {kind,row}=entries[selected];cross.setAttribute('x1',m.x(row.session_index));cross.setAttribute('x2',m.x(row.session_index));if(kind==='gap'){readout.textContent=`${row.session} · 일봉 미표시`;return;}const price=value=>Number(value).toLocaleString('ko-KR',{maximumFractionDigits:asset.currency==='KRW'?0:2});readout.textContent=kind==='quote'?`${row.date} ${row.time||''} · 장중 ${trendPrice(row.price,asset)} · 종가 아님`:`${row.session||row.session_date} · 시가 ${price(row.open)} · 고가 ${price(row.high)} · 저가 ${price(row.low)} · 종가 ${price(row.close)}`;};
  const pointer=event=>{const bounds=svg.getBoundingClientRect(),x=(event.clientX-bounds.left)/bounds.width*m.W,y=(event.clientY-bounds.top)/bounds.height*m.H,index=m.first+(x-m.L)/(m.W-m.L-m.R)*(m.end-m.first);let nearest=entries.reduce((best,entry,i)=>Math.abs(entry.row.session_index-index)<Math.abs(entries[best].row.session_index-index)?i:best,0);if(m.quote&&Math.abs(m.quote.session_index-index)<.5&&Math.abs(m.y(m.quote.price)-y)<20)nearest=entries.findIndex(entry=>entry.kind==='quote');paint(nearest);};
  svg.addEventListener('pointermove',pointer);svg.addEventListener('pointerdown',pointer);
  svg.addEventListener('focus',()=>paint(selected));
  svg.addEventListener('keydown',event=>{let index=selected;if(event.key==='ArrowLeft')index--;else if(event.key==='ArrowRight')index++;else if(event.key==='Home')index=0;else if(event.key==='End')index=entries.length-1;else return;event.preventDefault();paint(index);});
  paint(selected);
}
let TRENDLINES_RESIZE=null;
function renderTrendlinePage(initial={},loadState=null,localSession=null){
  if(localSession&&TRENDLINES_RESIZE){TRENDLINES_RESIZE.disconnect();TRENDLINES_RESIZE=null;}
  const assetId=initial?.asset||'sk-hynix',projection=DATA?.trendlines||{},officialAsset=projection.assets?.find(row=>row.asset_id===assetId),localDetail=TREND_PRIVATE_DETAILS.get(assetId);
  let detail=localDetail||projection.details?.[assetId],validationError=null;
  if(detail&&['ready','stale','unverified_display'].includes(detail.status)){try{trendValidateDetail(detail);}catch(error){validationError=error;detail=null;}}
  const asset=localDetail&&detail?{...officialAsset,asset_id:assetId,label:TREND_ASSETS.find(row=>row[0]===assetId)?.[1],currency:detail.asset.currency,price_unit:detail.asset.unit,status:'unverified_display',last_session:detail.observation_through}:officialAsset;
  if(localDetail&&detail)loadState=null;
  const nav=TREND_ASSETS.map(([id,label])=>`<a href="#future/trendlines/${id}"${id===assetId?' aria-current="page"':''}>${esc(label)}</a>`).join('');
  const fixture=detail?.fixture_only===true?'<p class="trend-fixture" role="alert">검토용 가상 시세 · 실제 시장 분석이 아닙니다</p>':'';
  const root=el(`<div class="trend-page"><header class="trend-heading"><p class="eyebrow">미래 탐색 · 05</p><h1>상·하방 추세선</h1></header><nav class="trend-assets" aria-label="추세선 자산 선택">${nav}</nav>${fixture}<section class="trend-body"><p class="trend-update-status" data-trend-local-message role="status"></p><div class="trend-content"></div></section></div>`),body=root.querySelector('.trend-content');
  const held=!asset||!['ready','stale','unverified_display'].includes(asset.status)||!detail||!['ready','stale','unverified_display'].includes(detail.status);
  if(loadState||held){const invalid=validationError||loadState?.error,phase=invalid?'invalid':Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId)?'checking':'idle';body.innerHTML=`<div class="trend-empty" data-trend-empty role="status">${trendEmptyMarkup(assetId,phase,invalid?'가격 기준을 확인한 뒤 표시합니다.':null)}</div>`;mount(root);if(Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId))bindTrendLocalConnection(root,initial,localSession);return;}
  const previousView=TREND_VIEW_OPTIONS.get(assetId);let period=previousView?.period||63,scale=previousView?.scale||'linear',direction=previousView?.direction||'all';
  const research=asset.status==='unverified_display',reference=trendReference(detail),delayed=asset.status==='stale'||detail.quality?.stale;
  const legend=`<div class="trend-explanation"><div class="trend-legend"><span><i class="trend-support"></i>지지선</span><span><i class="trend-resistance"></i>저항선</span><span><i class="trend-broken"></i>후보·연장선</span>${reference.quote?'<span><i class="trend-quote-dot"></i>장중 관측</span>':''}</div><p>지지선은 저점을, 저항선은 고점을 잇습니다. 점선은 후보선과 선의 연장입니다.</p></div>`;
  body.innerHTML=`<div class="trend-title"><div><h2>${esc(asset.label)}</h2><span>${research?'참고선 · ':''}일봉 ${esc(detail.observation_through||asset.last_session)} 기준${delayed?' · 갱신 지연':''}</span></div><div class="trend-price"><strong>${esc(trendPrice(reference.price,asset))}</strong><span>${esc(reference.date)}${reference.time?' '+esc(reference.time):''} · ${reference.kind}${reference.quote?' · 지연 시세':''}</span></div></div><div class="trend-controls trend-axis-controls"><span>두 차트 공통 축</span><div role="group" aria-label="가격 축"><button type="button" data-trend-scale="linear" aria-pressed="true">선형</button><button type="button" data-trend-scale="log" aria-pressed="false">로그</button></div></div><section class="trend-chart-section" data-trend-version="full"><div class="trend-chart-heading"><div><h3>전체 추세선</h3><p data-trend-full-coverage>확보된 전체 일봉을 확인하고 있습니다.</p></div></div><div class="trend-chart" data-trend-full-chart></div>${legend}<div data-trend-full-insights></div><details class="trend-line-meta"><summary>전체 선 세부</summary><div data-trend-full-line-details></div></details></section><section class="trend-chart-section" data-trend-version="current"><div class="trend-chart-heading"><div><h3>현재 상·하방 추세선</h3><p>선택한 기간의 지지·저항 경계</p></div><div class="trend-controls" role="group" aria-label="추세선 기간"><div>${[[63,'3개월'],[252,'1년'],[756,'3년']].map(([value,label])=>`<button type="button" data-trend-period="${value}" aria-pressed="${value===63}">${label}</button>`).join('')}</div></div></div><div class="trend-controls trend-direction-controls" data-trend-direction-controls></div><div class="trend-chart" data-trend-current-chart></div>${legend}<div data-trend-insights></div><details class="trend-line-meta"><summary>선 세부</summary><div data-trend-line-details></div></details></section>${trendResearchMarkup(detail,asset)}`;
  mount(root);
  const session=Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId)?bindTrendLocalConnection(root,initial,localSession):null;
  const host=root.querySelector('[data-trend-current-chart]'),fullHost=root.querySelector('[data-trend-full-chart]'),insights=root.querySelector('[data-trend-insights]'),lineDetails=root.querySelector('[data-trend-line-details]');let drawnWidth=0,fullDrawnWidth=0;
  const paintFull=()=>{
    const full=TREND_FULL_DETAILS.get(assetId),coverage=root.querySelector('[data-trend-full-coverage]'),fullInsights=root.querySelector('[data-trend-full-insights]'),fullLines=root.querySelector('[data-trend-full-line-details]');fullDrawnWidth=fullHost.clientWidth;
    if(!full){coverage.textContent='확보된 전체 일봉';fullHost.innerHTML=trendFullEmptyMarkup(session?.fullPhase);fullInsights.innerHTML='';fullLines.innerHTML='';return;}
    const older=full.source_snapshot_id!==TREND_PRIVATE_DETAILS.get(assetId)?.snapshot_id,analysis=full.analyses[scale].full;
    coverage.textContent=`${full.observation_start} — ${full.observation_through} · ${full.bar_count.toLocaleString('ko-KR')}개 일봉${older?' · 기준 자료 유지':full.quality?.stale?' · 갱신 지연':''}${session?.fullPhase==='invalid'?' · 자료 검증 보류':session?.fullPhase==='offline'?' · 갱신 확인 중':''}`;
    const m=trendPlotModel(full,analysis,full.bars,scale,fullHost.clientWidth||1000);
    fullInsights.innerHTML=trendInsightMarkup(full,null,scale,asset,true);fullLines.innerHTML=trendLineDetailsMarkup(analysis,trendReference(full),scale,asset);
    fullHost.innerHTML=trendSvg(full,m,asset,'full')+'<p data-trend-readout class="trend-readout" aria-live="polite"></p>'+(analysis.status==='hold'?`<p class="trend-direction-empty">${full.bar_count<771?'전체 기간의 참고선을 확인할 일봉이 더 필요합니다.':'전체 기간에서 확인된 참고선이 없습니다.'}</p>`:'');bindTrendChart(fullHost,full,m,asset,scale);
  };
  const directionHost=root.querySelector('[data-trend-direction-controls]');
  directionHost.innerHTML=`<div role="group" aria-label="현재 추세선 기울기">${[['all','상·하방'],['rising','상방'],['falling','하방']].map(([value,label])=>`<button type="button" data-trend-direction="${value}" aria-pressed="${value==='all'}">${label}</button>`).join('')}</div><span>상방·하방은 선의 기울기 기준</span>`;
  const paint=()=>{TREND_VIEW_OPTIONS.set(assetId,{period,scale,direction});const analysis=trendDirectionalAnalysis(detail,detail.analyses[scale][String(period)],scale,direction),m=analysis.status==='ready'?trendPlotModel(detail,analysis,detail.bars.slice(-period),scale,host.clientWidth||1000):null;drawnWidth=host.clientWidth;
    root.querySelectorAll('[data-trend-period]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.trendPeriod)===period)));root.querySelectorAll('[data-trend-scale]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendScale===scale)));
    root.querySelectorAll('[data-trend-direction]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendDirection===direction)));
    insights.innerHTML=trendInsightMarkup(detail,period,scale,asset,false,analysis);
    lineDetails.innerHTML=trendLineDetailsMarkup(analysis,reference,scale,asset);paintFull();
    if(!m){host.innerHTML='<div class="trend-empty trend-period-empty"><h3>이 기간의 추세선을 준비하고 있습니다.</h3><p>확인된 일봉이 충분해지면 표시합니다.</p></div>';return;}
    host.innerHTML=trendSvg(detail,m,asset)+'<p data-trend-readout class="trend-readout" aria-live="polite"></p>'+(!analysis.lines.length&&direction!=='all'?`<p class="trend-direction-empty">이 기간에는 ${direction==='rising'?'상방':'하방'} 기울기의 참고선이 없습니다.</p>`:'');bindTrendChart(host,detail,m,asset,scale);
  };
  root.querySelectorAll('[data-trend-period]').forEach(button=>button.onclick=()=>{period=Number(button.dataset.trendPeriod);paint();});root.querySelectorAll('[data-trend-scale]').forEach(button=>button.onclick=()=>{scale=button.dataset.trendScale;paint();});root.querySelectorAll('[data-trend-direction]').forEach(button=>button.onclick=()=>{direction=button.dataset.trendDirection;paint();});paint();
  if(session){session.fullMounted=true;session.onFullData=paintFull;Promise.resolve().then(()=>refreshTrendFullSession(session));}
  if(globalThis.ResizeObserver){TRENDLINES_RESIZE=new ResizeObserver(()=>{if(!root.isConnected){TRENDLINES_RESIZE?.disconnect();TRENDLINES_RESIZE=null;return;}if(Math.abs(host.clientWidth-drawnWidth)>2||Math.abs(fullHost.clientWidth-fullDrawnWidth)>2)paint();});TRENDLINES_RESIZE.observe(host);TRENDLINES_RESIZE.observe(fullHost);}
}
globalThis.TrendlineUI={ensure:ensureTrendlineData,render:renderTrendlinePage,validate:trendValidateDetail,cleanup(){stopTrendLocalSession();if(TRENDLINES_RESIZE){TRENDLINES_RESIZE.disconnect();TRENDLINES_RESIZE=null;}}};

})();
