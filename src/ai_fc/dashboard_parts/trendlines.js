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
const TREND_ASSETS=[['kospi','코스피'],['samsung','삼성전자'],['sk-hynix','SK하이닉스'],['nasdaq','나스닥 종합'],['sp500','S&P 500'],['dow','다우존스'],['soxx','SOXX'],['nvidia','엔비디아'],['micron','마이크론'],['bitcoin','비트코인'],['mag7','빅테크 7']];
const TREND_ASSET_META={kospi:{group:'국내',ticker:'KOSPI'},samsung:{group:'국내',ticker:'005930'},'sk-hynix':{group:'국내',ticker:'000660'},nasdaq:{group:'미국 지수',ticker:'IXIC'},sp500:{group:'미국 지수',ticker:'SPX'},dow:{group:'미국 지수',ticker:'DJI'},soxx:{group:'미국 종목',ticker:'SOXX'},nvidia:{group:'미국 종목',ticker:'NVDA'},micron:{group:'미국 종목',ticker:'MU'},bitcoin:{group:'가상자산',ticker:'BTC'}};
const TREND_VISIBLE_ASSETS=TREND_ASSETS.filter(([id])=>id!=='mag7');
const TREND_PRIVATE_IDENTITIES={'sk-hynix':['KRX:000660','000660.KS','KRW','XKRX','KRW_per_share','Asia/Seoul','equity','exchange_close'],soxx:['NASDAQ:SOXX','SOXX','USD','XNAS','USD_per_share','America/New_York','etf','exchange_close'],nasdaq:['NASDAQ_COMPOSITE_PRICE_INDEX','^IXIC','USD','XNAS','index_points','America/New_York','index','exchange_close'],sp500:['SP500_PRICE_INDEX','^GSPC','USD','XNYS','index_points','America/New_York','index','exchange_close'],bitcoin:['BTC_USD_SPOT_SOURCE_MUST_BE_DECLARED','BTC-USD','USD','24/7','USD_per_BTC','UTC','crypto','UTC_00_00_next_day'],dow:['DOW_JONES_INDUSTRIAL_AVERAGE_PRICE_INDEX','^DJI','USD','XNYS','index_points','America/New_York','index','exchange_close'],kospi:['KRX_KOSPI_PRICE_INDEX','^KS11','KRW','XKRX','index_points','Asia/Seoul','index','exchange_close'],samsung:['KRX:005930','005930.KS','KRW','XKRX','KRW_per_share','Asia/Seoul','equity','exchange_close'],nvidia:['NASDAQ:NVDA','NVDA','USD','XNAS','USD_per_share','America/New_York','equity','exchange_close'],micron:['NASDAQ:MU','MU','USD','XNAS','USD_per_share','America/New_York','equity','exchange_close']};
const TREND_LOCAL_BASE='http://127.0.0.1:8878/api/private-trendlines/';
const TREND_IMPORT_TRANSPORT=Symbol('private_import_transport');
const TREND_VIEW_OPTIONS=new Map();
const TREND_FULL_DETAILS=new Map();
const TREND_CRITICAL_DETAILS=new Map();
const TREND_REPRESENTATIVE_DETAILS=new Map(),TREND_REPRESENTATIVE_VIEW_OPTIONS=new Map();
const TREND_REPRESENTATIVE_PROOF=Symbol('representative_source_and_arithmetic_proof');
const TREND_REPRESENTATIVE_SLOTS=['regression_200','current_structure','major_structure'];
const TREND_REPRESENTATIVE_LABELS={regression_200:'200일 가격추세',current_structure:'현재 추세',major_structure:'장기 주요 고저점',long_upper:'장기 고점 연결선',long_lower:'장기 저점 연결선',cycle_2023:'2023년 장기 추세선'};
const TREND_REPRESENTATIVE_COLORS={regression_200:'#32799c',current_structure:'#bc632d',major_structure:'#72649b',long_upper:'#a85454',long_lower:'#357a61',cycle_2023:'#a47823'};
const TREND_BITCOIN_CYCLE_POLICY=Object.freeze({version:'bitcoin_2023_structure_v1',anchor_year:2023,left:10,right:10,minimum_anchor_gap:180,maximum_second_anchor_age:365,maximum_distance_atr:8,maximum_distance_fraction:.5});
const TREND_BITCOIN_CYCLE_CACHE=new WeakMap();
const TREND_LONG_DETAILS=new Map(),TREND_LONG_PROOF=Symbol('long_boundaries_source_and_arithmetic_proof');
const TREND_LONG_SLOTS=['long_upper','long_lower'];
const TREND_LONG_POLICY_SHA256='4097093809bbf8f3d362c4eacdac545dac7dd65e22490f0ed02aba7b0af8ecb2';
const TREND_REPRESENTATIVE_POLICY_SHA256='3346c8ba94bf38fc6bcac021b416f9c714c9e146c4bc46e407cf172de6b256a1';
const TREND_CRITICAL_POLICY_SHA256='3bbc9d9d15af58886b9a35de7d9796887538a8a424b1c24a716affd597d1f672';
let TREND_ZOOM=null,TREND_CHART_INSTANCE=0;
const TREND_CHART_VIEWS=new Map();
const TREND_MANUAL_STATES=new Map(),TREND_MANUAL_VIEWS=new Map();
const TREND_MANUAL_LIMIT=20,TREND_MANUAL_STORAGE_PREFIX='jins-trendlines-drawings-v1:';
let TREND_LOCAL_ENABLED=readTrendLocalPreference(),TREND_LOCAL_SESSION=null,TREND_LOCAL_EPOCH=0;
function readTrendLocalPreference(){return ['https://sung-jinpark.github.io','http://127.0.0.1:8878'].includes(globalThis.location?.origin);}
function trendLocalVisible(){return typeof document==='undefined'||document.visibilityState!=='hidden';}
function trendLocalCurrent(session,sequence=session.sequence){return TREND_LOCAL_SESSION===session&&session.epoch===TREND_LOCAL_EPOCH&&session.active&&session.root.isConnected&&sequence===session.sequence&&TREND_LOCAL_ENABLED;}
function trendLocalKst(value){return value?new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',dateStyle:'short',timeStyle:'medium'}).format(new Date(value)):'확인 대기';}
function validateTrendLocalStatus(value,assetId){
  const aware=value=>value===null||typeof value==='string'&&/(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));
  if(value?.schema_version!==1||value.contract_id!=='trendlines_local_status_v1'||value.publication_scope!=='private_only'||typeof value.running!=='boolean'||typeof value.refresh_in_progress!=='boolean'||!aware(value.next_refresh_kst)||!Array.isArray(value.assets)||value.assets.length<2||value.assets.length>TREND_ASSETS.length)throw new Error('로컬 갱신 상태를 확인하지 못했습니다');
  const ids=new Set();
  for(const row of value.assets){
    if(!TREND_ASSETS.some(asset=>asset[0]===row?.asset_id)||ids.has(row.asset_id)||!['ready','stale','missing','hold','refreshing'].includes(row.status)||typeof row.stale!=='boolean'||!['last_success','last_attempt','source_asof','next_refresh_kst'].every(key=>aware(row[key]))||row.observation_through!==null&&!/^\d{4}-\d{2}-\d{2}$/.test(row.observation_through||'')||!['reason','error'].every(key=>row[key]===null||typeof row[key]==='string'&&row[key].length<=256))throw new Error('로컬 갱신 상태의 자산 기준이 올바르지 않습니다');
    ids.add(row.asset_id);
  }
  const row=value.assets.find(row=>row.asset_id===assetId);
  if(!row)throw new Error('이 PC의 로컬 갱신기를 최신 버전으로 업데이트해 주세요');
  return row;
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
function pauseTrendLocalSession(session){clearTimeout(session.timer);session.timer=null;session.sequence++;session.controller?.abort();session.fullSequence=(session.fullSequence||0)+1;session.fullController?.abort();session.criticalSequence=(session.criticalSequence||0)+1;session.criticalController?.abort();session.representativeSequence=(session.representativeSequence||0)+1;session.representativeController?.abort();session.longSequence=(session.longSequence||0)+1;session.longController?.abort();}
function stopTrendLocalSession(){const session=TREND_LOCAL_SESSION;if(!session)return;session.active=false;pauseTrendLocalSession(session);document.removeEventListener('visibilitychange',session.visibility);window.removeEventListener('pagehide',session.unload);TREND_LOCAL_SESSION=null;TREND_LOCAL_EPOCH++;}
function scheduleTrendLocalRefresh(session,delay=60000){if(!trendLocalCurrent(session)||!trendLocalVisible())return;clearTimeout(session.timer);session.timer=setTimeout(()=>refreshTrendLocalSession(session),delay);}
async function refreshTrendLocalSession(session){
  if(!trendLocalCurrent(session)||!trendLocalVisible())return;
  if(session.inflight!==null){session.resumePending=true;return session.inflight;}
  const sequence=++session.sequence,controller=new AbortController();session.controller=controller;session.phase='checking';session.problem=null;
  const deadline=setTimeout(()=>controller.abort(),30000),options={method:'GET',mode:'cors',credentials:'omit',cache:'no-store',redirect:'error',targetAddressSpace:'loopback',signal:controller.signal};
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
    if(session.fullMounted&&trendLocalVisible()){refreshTrendFullSession(session);if(session.representativeMounted)refreshTrendRepresentativeSession(session);else refreshTrendCriticalSession(session);}
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
function trendPrice(value,asset){return `${Number(value).toLocaleString('ko-KR',{maximumFractionDigits:(asset?.price_unit==='KRW'||asset?.currency==='KRW')&&!['points','index_points'].includes(asset?.price_unit)?0:2})}${['points','index_points'].includes(asset?.price_unit)?' pt':asset?.currency==='KRW'?'원':asset?.currency==='USD'?'달러':''}`;}
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
function trendLinePrice(line,index,scale){const value=line.intercept+line.slope*(index-line.coordinate_origin_index);return (line.manual?line.axis:scale)==='log'?Math.exp(value):value;}
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
  const deadline=setTimeout(()=>controller.abort(),30000),options={method:'GET',mode:'cors',credentials:'omit',cache:'no-store',redirect:'error',targetAddressSpace:'loopback',signal:controller.signal};
  const active=()=>trendLocalCurrent(session)&&session.fullSequence===sequence&&!controller.signal.aborted&&TREND_PRIVATE_DETAILS.get(session.assetId)?.snapshot_id===key;
  const pending=(async()=>{
    const decoded=await parseTrendFullTransport(await readTrendLocalResponse(await fetch(TREND_LOCAL_BASE+session.assetId+'/full',options),524288),session.assetId),manifest=validateTrendFullManifest(decoded.body,current);
    if(!active())return;
    const existing=TREND_FULL_DETAILS.get(session.assetId);if(existing?.snapshot_id===manifest.snapshot_id){session.fullPhase='connected';return;}
    const chunks=[];
    for(let index=0;index<manifest.chunks.length;index+=2){const rows=await Promise.all(manifest.chunks.slice(index,index+2).map(async pin=>parseTrendFullChunk(await readTrendLocalResponse(await fetch(TREND_LOCAL_BASE+session.assetId+'/full/'+manifest.snapshot_id+'/bars/'+pin.chunk_index,options),262144),manifest,pin)));if(!active())return;chunks.push(...rows);}
    const detail=buildTrendFullDetail(manifest,chunks.flat(),current);Object.defineProperty(detail,'critical_manifest_sha256',{value:decoded.payload_sha256});if(!active())return;
    TREND_FULL_DETAILS.set(session.assetId,detail);session.fullPhase='connected';
  })().catch(error=>{if(!trendLocalCurrent(session)||session.fullSequence!==sequence)return;session.fullPhase=trendLocalVisible()?error instanceof TypeError||error.name==='AbortError'?'offline':'invalid':'paused';session.fullError=String(error.message||error);}).finally(()=>{clearTimeout(deadline);if(session.fullPending===pending)session.fullPending=null;if(trendLocalCurrent(session)&&session.fullSequence===sequence)session.onFullData?.();});
  session.fullPending=pending;return pending;
}
function validateTrendCritical(body,current,full=null){
  const fail=()=>{throw new Error('핵심 경계의 가격 또는 원천 기준이 올바르지 않습니다');},sha=/^[a-f0-9]{64}$/,last=current?.bars?.at(-1);
  if(!last||body?.schema_version!==1||body.contract_id!=='trendlines_private_critical_v1'||body.policy_version!=='critical_v1'||body.policy_sha256!==TREND_CRITICAL_POLICY_SHA256||body.publication_scope!=='private_only'||body.official_forecast_write!==false||body.verified_source!==false||body.historical_signals_available!==false||body.rights_status!=='uncertified_research_source'||body.source_context!=='user_authorized_public_html_research'||body.as_of!==current.as_of||body.asset_id!==current.asset_id||!/^critical-snapshot-[a-f0-9]{64}$/.test(body.snapshot_id||'')||body.source_snapshot_id!==current.snapshot_id||body.source_engine_content_hash!==current.source_snapshot_hash||!/^research-full-snapshot-[a-f0-9]{64}$/.test(body.source_full_snapshot_id||'')||!sha.test(body.source_full_content_hash||'')||!sha.test(body.full_manifest_payload_sha256||'')||body.reference_close!==last.close||body.reference_index!==last.session_index||body.reference_session!==(last.session||last.session_date)||!Number.isFinite(body.atr14)||body.atr14<=0)fail();
  const tail=current.bars.slice(-15);if(tail.length!==15||tail.some((bar,i)=>i&&bar.session_index!==tail[i-1].session_index+1))fail();
  const atr=tail.slice(1).reduce((sum,bar,i)=>sum+Math.max(bar.high-bar.low,Math.abs(bar.high-tail[i].close),Math.abs(bar.low-tail[i].close)),0)/14;
  if(Math.abs(atr-body.atr14)>Math.max(1e-6,Math.abs(atr)*1e-10))fail();
  if(full&&(full.source_snapshot_id!==current.snapshot_id||full.snapshot_id!==body.source_full_snapshot_id||full.critical_manifest_sha256!==body.full_manifest_payload_sha256))fail();
  const future=body.projection_sessions,count=body.asset_id==='bitcoin'?30:21;
  if(!Array.isArray(future)||future.length!==count||future.some((row,i)=>row.offset!==i+1||row.index!==last.session_index+i+1||!trendIsoDate(row.session)||row.session<=(i?future[i-1].session:body.reference_session)))fail();
  if(!body.analyses||Object.keys(body.analyses).sort().join(',')!=='linear,log')fail();
  for(const axis of ['linear','log']){
    if(Object.keys(body.analyses[axis]||{}).sort().join(',')!=='252,63,756,full')fail();
    for(const [period,view] of Object.entries(body.analyses[axis])){
      if(!['ready','no_verified_boundaries','unavailable'].includes(view?.status)||!Array.isArray(view.boundaries)||view.boundaries.length>2||view.status!=='ready'&&view.boundaries.length||!view.parameters||!Number.isInteger(view.parameters.left)||view.parameters.left<1||!Number.isInteger(view.parameters.right)||view.parameters.right<1)fail();
      const roles=new Set(),ids=new Set(),bars=period==='full'&&full?full.bars:current.bars,barMap=new Map(bars.map(bar=>[bar.session_index,bar]));
      for(const line of view.boundaries){
        if(!['diagonal','horizontal_zone'].includes(line.kind)||!['support','resistance'].includes(line.role)||roles.has(line.role)||ids.has(line.boundary_id)||line.line_id!==line.boundary_id||!(/^(?:trend-line|critical-zone)-[a-f0-9]{32}$/.test(line.boundary_id||''))||line.axis!==axis||!Number.isFinite(line.slope)||!Number.isFinite(line.intercept)||!Number.isInteger(line.coordinate_origin_index)||!Number.isFinite(line.current_price)||line.current_price<=0||!['active','reclaimed'].includes(line.structural_state)||!Array.isArray(line.independent_contacts)||line.independent_contacts.length<3||line.contact_count!==line.independent_contacts.length)fail();
        roles.add(line.role);ids.add(line.boundary_id);
        const value=trendLinePrice(line,last.session_index,axis),distance=Math.abs(value-last.close);
        if(!Number.isFinite(value)||Math.abs(value-line.current_price)>Math.max(1e-6,Math.abs(value)*1e-10)||distance>4*body.atr14+1e-6||distance/last.close>.2+1e-12||(line.role==='support'?value>last.close:value<last.close)||last.session_index-line.latest_touch_index>63||line.latest_touch_index!==line.independent_contacts.at(-1).index)fail();
        let prior=-Infinity;
        for(const contact of line.independent_contacts){
          const bar=barMap.get(contact.index);
          if(!Number.isInteger(contact.index)||contact.index<=prior||!trendIsoDate(contact.session)||contact.confirmation_start_index!==contact.index-view.parameters.left||contact.confirmation_end_index!==contact.index+view.parameters.right||contact.confirmation_end_index>last.session_index||contact.confirmation_start_index<=prior||typeof contact.confirmed_at!=='string'||Date.parse(contact.confirmed_at)>Date.parse(current.as_of)||!Number.isFinite(Date.parse(contact.confirmed_at))||!Number.isFinite(contact.price)||contact.price<=0||!/^research-bar-[a-f0-9]{64}$/.test(contact.bar_id||''))fail();
          const confirmedBar=barMap.get(contact.confirmation_end_index);if(confirmedBar&&(confirmedBar.session||confirmedBar.session_date)!==contact.confirmation_session)fail();
          if(bar&&(bar.bar_id!==contact.bar_id||(bar.session||bar.session_date)!==contact.session||bar[line.role==='support'?'low':'high']!==contact.price))fail();
          if((period!=='full'||full)&&!bar)fail();prior=contact.confirmation_end_index;
        }
        for(const anchor of [line.first_anchor,line.second_anchor]){const bar=barMap.get(anchor?.index);if(!anchor||!Number.isInteger(anchor.index)||!trendIsoDate(anchor.session)||!Number.isFinite(anchor.price)||anchor.price<=0||(bar&&(bar.bar_id!==anchor.bar_id||bar[line.role==='support'?'low':'high']!==anchor.price)))fail();if(line.kind==='diagonal'&&Math.abs(trendLinePrice(line,anchor.index,axis)-anchor.price)>Math.max(1e-6,anchor.price*1e-10))fail();}
        if(line.kind==='horizontal_zone'&&(!Number.isFinite(line.zone_low)||!Number.isFinite(line.zone_high)||line.zone_low<=0||line.zone_high<line.zone_low||line.slope!==0||line.level!==line.center||line.level!==line.current_price||line.level<line.zone_low||line.level>line.zone_high||line.direction!=='horizontal'))fail();
        if(!Array.isArray(line.points)||line.points.length<2)fail();let pointPrior=-Infinity;
        for(const point of line.points){const expected=trendLinePrice(line,point.index,axis);if(!Number.isInteger(point.index)||point.index<=pointPrior||typeof point.future!=='boolean'||point.future!==(point.index>last.session_index)||!Number.isFinite(point.price)||point.price<=0||Math.abs(expected-point.price)>Math.max(1e-6,point.price*1e-10)||point.future&&!future.some(row=>row.index===point.index&&row.session===point.session))fail();pointPrior=point.index;}
      }
      if(view.boundaries.length===2&&Math.abs(view.boundaries[0].current_price-view.boundaries[1].current_price)<.5*body.atr14-1e-6)fail();
    }
  }
  return body;
}
async function parseTrendCriticalTransport(raw,current){
  const envelope=trendUniqueJson(raw),sha=/^[a-f0-9]{64}$/;
  if(new TextEncoder().encode(raw).length>524288||envelope?.schema_version!==1||envelope.contract_id!=='trendlines_private_critical_transport_v1'||envelope.publication_scope!=='private_only'||envelope.asset_id!==current.asset_id||typeof envelope.payload_json!=='string'||new TextEncoder().encode(envelope.payload_json).length>262144||!sha.test(envelope.payload_sha256||'')||await trendExactSha(envelope.payload_json)!==envelope.payload_sha256)throw new Error('핵심 경계의 무결성 기준이 올바르지 않습니다');
  const body=validateTrendCritical(trendUniqueJson(envelope.payload_json),current);if(body.snapshot_id!==envelope.snapshot_id)throw new Error('핵심 경계의 snapshot 기준이 다릅니다');return body;
}
async function refreshTrendCriticalSession(session){
  const current=TREND_PRIVATE_DETAILS.get(session.assetId);if(!session.fullMounted||!current||!trendLocalCurrent(session)||!trendLocalVisible())return;
  if(session.criticalPending&&session.criticalSource===current.snapshot_id)return session.criticalPending;
  session.criticalController?.abort();const controller=new AbortController(),sequence=(session.criticalSequence||0)+1,key=current.snapshot_id;session.criticalSequence=sequence;session.criticalController=controller;session.criticalSource=key;
  const deadline=setTimeout(()=>controller.abort(),30000),options={method:'GET',mode:'cors',credentials:'omit',cache:'no-store',redirect:'error',targetAddressSpace:'loopback',signal:controller.signal};
  const active=()=>trendLocalCurrent(session)&&session.criticalSequence===sequence&&!controller.signal.aborted&&TREND_PRIVATE_DETAILS.get(session.assetId)?.snapshot_id===key;
  const pending=(async()=>{const body=await parseTrendCriticalTransport(await readTrendLocalResponse(await fetch(TREND_LOCAL_BASE+session.assetId+'/critical',options),524288),current);if(!active())return;TREND_CRITICAL_DETAILS.set(session.assetId,body);session.criticalError=null;})().catch(error=>{if(!trendLocalCurrent(session)||session.criticalSequence!==sequence)return;TREND_CRITICAL_DETAILS.delete(session.assetId);session.criticalError=String(error.message||error);}).finally(()=>{clearTimeout(deadline);if(session.criticalPending===pending)session.criticalPending=null;if(trendLocalCurrent(session)&&session.criticalSequence===sequence)session.onCriticalData?.();});session.criticalPending=pending;return pending;
}
function trendCriticalAnalysis(current,full,period,axis){
  const body=TREND_CRITICAL_DETAILS.get(current.asset_id);let view=null,verified=null;
  try{if(body){verified=validateTrendCritical(body,current,full||null);view=verified.analyses[axis][String(period)];}}catch(_){view=null;verified=null;}
  return {status:'ready',lines:view?.boundaries||[],projection_sessions:verified?.projection_sessions||[],critical:true,critical_view:view,critical_reference:verified?{price:verified.reference_close,atr14:verified.atr14,date:verified.reference_session,index:verified.reference_index}:null};
}
function trendAccurateSum(values){let sum=0,correction=0;for(const value of values){const next=sum+value;correction+=Math.abs(sum)>=Math.abs(value)?(sum-next)+value:(value-next)+sum;sum=next;}return sum+correction;}
function trendIndependentOls(bars,axis){
  const n=bars.length,origin=bars[0].session_index,x=bars.map(row=>row.session_index-origin),y=bars.map(row=>axis==='log'?Math.log(row.close):row.close),xMean=trendAccurateSum(x)/n,yMean=trendAccurateSum(y)/n;
  const sxx=trendAccurateSum(x.map(value=>(value-xMean)**2)),sxy=trendAccurateSum(x.map((value,i)=>(value-xMean)*(y[i]-yMean))),slope=sxy/sxx,intercept=yMean-slope*xMean,syy=trendAccurateSum(y.map(value=>(value-yMean)**2)),sse=trendAccurateSum(y.map((value,i)=>(value-(intercept+slope*x[i]))**2));
  return {n,origin,x_mean:xMean,y_mean:yMean,sxx,sxy,slope,intercept,r_squared:syy===0?null:1-sse/syy,rmse:Math.sqrt(sse/n)};
}
async function validateTrendRepresentative(body,current,full){
  const fail=()=>{throw new Error('대표 추세선의 원천 또는 계산 기준이 올바르지 않습니다');},sha=/^[a-f0-9]{64}$/,last=current?.bars?.at(-1),near=(a,b)=>typeof a==='number'&&Number.isFinite(a)&&typeof b==='number'&&Number.isFinite(b)&&Math.abs(a-b)<=Math.max(1e-6,Math.abs(b)*1e-10);
  if(!last||!full||body?.schema_version!==1||body.contract_id!=='trendlines_private_representative_v1'||body.policy_version!=='representative_v1'||body.policy_sha256!==TREND_REPRESENTATIVE_POLICY_SHA256||body.publication_scope!=='private_only'||body.official_forecast_write!==false||body.verified_source!==false||body.verified_boundary!==false||body.historical_signals_available!==false||!Array.isArray(body.events)||body.events.length||body.rights_status!=='uncertified_research_source'||body.source_context!=='user_authorized_public_html_research'||body.asset_id!==current.asset_id||body.as_of!==current.as_of||!/^representative-snapshot-[a-f0-9]{64}$/.test(body.snapshot_id||'')||body.source_snapshot_id!==current.snapshot_id||body.source_engine_snapshot_id!==current.engine_snapshot_id||body.source_engine_content_hash!==current.source_snapshot_hash||body.source_archive_sha256!==current.research_archive_sha256||!sha.test(body.source_content_hash||'')||body.source_full_snapshot_id!==full.snapshot_id||full.source_snapshot_id!==current.snapshot_id||body.full_manifest_payload_sha256!==full.critical_manifest_sha256||!sha.test(body.source_full_content_hash||'')||!sha.test(body.input_hash||'')||body.reference_close!==last.close||body.reference_session!==(last.session||last.session_date)||body.reference_index!==last.session_index||!trendSameValue(full.bars.slice(-current.bars.length),current.bars))fail();
  const bars=full.bars,byIndex=new Map(bars.map(bar=>[bar.session_index,bar])),future=body.projection_sessions,count=current.asset_id==='bitcoin'?30:21;
  const tail=bars.slice(-15),contiguous=tail.length===15&&tail.every((bar,i)=>!i||bar.session_index===tail[i-1].session_index+1),atr=contiguous?trendAccurateSum(tail.slice(1).map((bar,i)=>Math.max(bar.high-bar.low,Math.abs(bar.high-tail[i].close),Math.abs(bar.low-tail[i].close))))/14:null;if(atr===null?body.atr14!==null:!near(body.atr14,atr))fail();
  if(!Array.isArray(future)||future.length!==count||future.some((row,i)=>Object.keys(row).sort().join(',')!=='index,offset,session'||row.offset!==i+1||row.index!==last.session_index+i+1||!trendIsoDate(row.session)||row.session<=(i?future[i-1].session:body.reference_session))||await trendExactSha(JSON.stringify(bars.map(row=>row.bar_id)))!==body.input_bar_ids_hash)fail();
  const existing=Object.values(current.analyses.linear).find(analysis=>analysis.status==='ready')?.projection_sessions||[];if(existing.some(row=>!future.some(point=>point.index===row.index&&point.session===row.session&&point.offset===row.offset)))fail();
  if(!body.analyses||Object.keys(body.analyses).sort().join(',')!=='linear,log')fail();
  for(const axis of ['linear','log']){
    const rows=body.analyses[axis]?.representatives;if(!Array.isArray(rows)||rows.length!==3||new Set(rows.map(row=>row.slot)).size!==3||rows.some(row=>!TREND_REPRESENTATIVE_SLOTS.includes(row.slot)))fail();
    const ids=new Set();for(const line of rows){
      if(!['ready','hold'].includes(line.status))fail();if(line.status==='hold'){const required=line.slot==='regression_200'?200:line.slot==='current_structure'?63:252;if(bars.length>=required||line.requested_observations!==required||line.available_observations!==bars.length||line.current_price!==null&&line.current_price!==undefined||line.points?.length||line.markers?.length||line.verified_boundary!==false)fail();continue;}
      const currentValue=trendLinePrice(line,last.session_index,axis),currentAvailable=Number.isFinite(currentValue)&&currentValue>0;
      if(!/^representative-line-[a-f0-9]{32}$/.test(line.line_id||'')||ids.has(line.line_id)||line.axis!==axis||line.verified_boundary!==false||!['regression','pivot_structure'].includes(line.kind)||!['support','resistance','direction_only'].includes(line.role)||!['rising','falling','flat'].includes(line.direction)||!['descriptive','two_anchor','three_contact'].includes(line.geometry_status)||!['descriptive','active','reclaimed','broken','break_pending','reclaim_pending'].includes(line.structural_state)||!Number.isFinite(line.slope)||!Number.isFinite(line.intercept)||!Number.isInteger(line.coordinate_origin_index)||!Number.isInteger(line.display_start_index)||line.display_start_index<bars[0].session_index||line.display_start_index>last.session_index||!Number.isInteger(line.display_end_index)||line.display_end_index!==future.at(-1).index||(currentAvailable?line.current_price_status!=='ready'||!near(line.current_price,currentValue):line.current_price_status!=='unavailable_nonpositive_projection'||line.current_price!==null)||line.direction!==(line.slope>0?'rising':line.slope<0?'falling':'flat'))fail();ids.add(line.line_id);
      if(line.kind==='regression'){
        const fit=line.fit,requested=line.slot==='regression_200'?200:line.slot==='current_structure'?63:252,inputs=bars.slice(-requested);
        if(!fit||inputs.length!==requested||fit.n!==requested||fit.requested_observations!==requested||fit.start_index!==inputs[0].session_index||fit.end_index!==last.session_index||fit.start_session!==(inputs[0].session||inputs[0].session_date)||fit.end_session!==(last.session||last.session_date)||line.coordinate_origin_index!==inputs[0].session_index||line.display_start_index!==inputs[0].session_index||line.first_anchor!==null||line.second_anchor!==null||line.contacts?.length!==0||line.contact_count!==0||line.markers?.length!==0||line.role!=='direction_only'||line.origin_role!==null||line.geometry_status!=='descriptive'||line.structural_state!=='descriptive'||await trendExactSha(JSON.stringify(inputs.map(row=>row.bar_id)))!==fit.input_bar_ids_hash)fail();
        const check=trendIndependentOls(inputs,axis);for(const key of ['x_mean','y_mean','sxx','sxy','rmse'])if(!near(fit[key],check[key]))fail();if((check.r_squared===null?fit.r_squared!==null:!near(fit.r_squared,check.r_squared))||fit.fit_bar_ids_hash!==fit.input_bar_ids_hash||fit.session_span!==last.session_index-inputs[0].session_index+1||fit.missing_sessions!==fit.session_span-requested||!near(line.slope,check.slope)||!near(line.intercept,check.intercept))fail();
        for(const index of [inputs[0].session_index,last.session_index,...future.map(row=>row.index)]){const transformed=check.intercept+check.slope*(index-check.origin),expected=axis==='log'?Math.exp(transformed):transformed,actual=trendLinePrice(line,index,axis);if(Number.isFinite(expected)&&expected>0?!near(actual,expected):Number.isFinite(actual)&&actual>0)fail();}
      }else{
        const window=line.slot==='current_structure'?3:10,gap=line.slot==='current_structure'?10:60;if(line.slot==='regression_200'||!['support','resistance'].includes(line.origin_role)||line.geometry_status==='descriptive'||line.parameters?.left!==window||line.parameters?.right!==window||line.parameters?.min_anchor_gap!==gap||!Array.isArray(line.contacts)||line.contacts.length<2||line.contact_count!==line.contacts.length||line.geometry_status!==(line.contact_count>=3?'three_contact':'two_anchor')||!Array.isArray(line.markers)||line.markers.length<2||line.markers.length>4||line.fit!==null&&line.fit!==undefined)fail();
        const anchors=[line.first_anchor,line.second_anchor,...line.contacts].map(anchor=>({anchor,side:line.origin_role})).concat(line.markers.map(anchor=>({anchor,side:anchor.side})));
        for(const {anchor,side} of anchors){const bar=byIndex.get(anchor?.index),value=anchor&&trendLinePrice(line,anchor.index,axis),field=side==='support'?'low':'high';if(!['support','resistance'].includes(side)||!bar||anchor.side!==side||anchor.bar_id!==bar.bar_id||anchor.session!==(bar.session||bar.session_date)||anchor.price!==bar[field]||!Number.isFinite(value)||!Number.isFinite(Date.parse(anchor.confirmed_at))||Date.parse(anchor.confirmed_at)>Date.parse(body.as_of)||anchor.confirmation_start_index!==anchor.index-window||anchor.confirmation_end_index!==anchor.index+window||anchor.confirmation_end_index>last.session_index||(byIndex.get(anchor.confirmation_end_index)?.session||byIndex.get(anchor.confirmation_end_index)?.session_date)!==anchor.confirmation_session)fail();
          for(let index=anchor.confirmation_start_index;index<=anchor.confirmation_end_index;index++){const neighbor=byIndex.get(index);if(!neighbor)fail();if(index===anchor.index)continue;const left=index<anchor.index;if(side==='support'?(left?anchor.price>=neighbor.low:anchor.price>neighbor.low):(left?anchor.price<=neighbor.high:anchor.price<neighbor.high))fail();}
        }
        if(line.second_anchor.index-line.first_anchor.index<gap||line.display_start_index!==line.first_anchor.index||!near(line.first_anchor.price,trendLinePrice(line,line.first_anchor.index,axis))||!near(line.second_anchor.price,trendLinePrice(line,line.second_anchor.index,axis)))fail();
        const firstPrice=axis==='log'?Math.log(line.first_anchor.price):line.first_anchor.price,secondPrice=axis==='log'?Math.log(line.second_anchor.price):line.second_anchor.price,slope=(secondPrice-firstPrice)/(line.second_anchor.index-line.first_anchor.index);for(const index of [last.session_index,...future.map(row=>row.index)]){const transformed=firstPrice+slope*(index-line.first_anchor.index),expected=axis==='log'?Math.exp(transformed):transformed,actual=trendLinePrice(line,index,axis);if(Number.isFinite(expected)&&expected>0?!near(actual,expected):Number.isFinite(actual)&&actual>0)fail();}
      }
      if(!Array.isArray(line.points)||line.points.length<2||!Array.isArray(line.projections)||line.projections.length!==count)fail();let prior=-Infinity;
      for(const point of line.points){const expected=trendLinePrice(line,point.index,axis),available=Number.isFinite(expected)&&expected>0,session=point.future?future.find(row=>row.index===point.index):byIndex.get(point.index);if(!Number.isInteger(point.index)||point.index<=prior||point.index<line.display_start_index||typeof point.future!=='boolean'||point.future!==(point.index>last.session_index)||!session||point.session!==(session.session||session.session_date)||['open','high','low','close','volume'].some(key=>Object.hasOwn(point,key))||(available?!near(point.price,expected):point.price!==null))fail();prior=point.index;}
      for(const [i,point] of line.projections.entries()){const expected=trendLinePrice(line,point.index,axis),available=Number.isFinite(expected)&&expected>0;if(point.index!==future[i].index||point.session!==future[i].session||point.offset!==future[i].offset||point.status!==(available?'ready':'unavailable')||(available?!near(point.price,expected):point.price!==null))fail();}
    }
  }
  return body;
}
async function parseTrendRepresentativeTransport(raw,current,full){
  if(typeof raw!=='string'||new TextEncoder().encode(raw).length>524288)throw new Error('대표 추세선의 크기 기준이 올바르지 않습니다');
  const envelope=trendUniqueJson(raw),keys='asset_id,contract_id,payload_json,payload_sha256,publication_scope,schema_version,snapshot_id';
  if(Object.keys(envelope||{}).sort().join(',')!==keys||envelope.schema_version!==1||envelope.contract_id!=='trendlines_private_representative_transport_v1'||envelope.publication_scope!=='private_only'||envelope.asset_id!==current.asset_id||typeof envelope.payload_json!=='string'||new TextEncoder().encode(envelope.payload_json).length>262144||!/^[a-f0-9]{64}$/.test(envelope.payload_sha256||'')||await trendExactSha(envelope.payload_json)!==envelope.payload_sha256)throw new Error('대표 추세선의 무결성 기준이 올바르지 않습니다');
  const body=await validateTrendRepresentative(trendUniqueJson(envelope.payload_json),current,full);if(body.snapshot_id!==envelope.snapshot_id)throw new Error('대표 추세선의 snapshot 기준이 다릅니다');
  Object.defineProperty(body,TREND_REPRESENTATIVE_PROOF,{value:{source:current.snapshot_id,sourceHash:current.content_hash,full:full.snapshot_id,manifest:full.critical_manifest_sha256,payload:envelope.payload_sha256}});return body;
}
async function refreshTrendRepresentativeSession(session){
  const current=TREND_PRIVATE_DETAILS.get(session.assetId),full=TREND_FULL_DETAILS.get(session.assetId);if(!session.representativeMounted||!current||!full||full.source_snapshot_id!==current.snapshot_id||!trendLocalCurrent(session)||!trendLocalVisible())return;
  const key=current.snapshot_id+'|'+full.snapshot_id;if(session.representativePending&&session.representativeSource===key)return session.representativePending;
  session.representativeController?.abort();const controller=new AbortController(),sequence=(session.representativeSequence||0)+1;session.representativeSequence=sequence;session.representativeController=controller;session.representativeSource=key;let changed=false;
  const deadline=setTimeout(()=>controller.abort(),60000),options={method:'GET',mode:'cors',credentials:'omit',cache:'no-store',redirect:'error',targetAddressSpace:'loopback',signal:controller.signal},active=()=>trendLocalCurrent(session)&&session.representativeSequence===sequence&&!controller.signal.aborted&&TREND_PRIVATE_DETAILS.get(session.assetId)?.snapshot_id===current.snapshot_id&&TREND_FULL_DETAILS.get(session.assetId)?.snapshot_id===full.snapshot_id;
  const pending=(async()=>{const body=await parseTrendRepresentativeTransport(await readTrendLocalResponse(await fetch(TREND_LOCAL_BASE+session.assetId+'/representative',options),524288),current,full);if(!active())return;changed=TREND_REPRESENTATIVE_DETAILS.get(session.assetId)?.snapshot_id!==body.snapshot_id;TREND_REPRESENTATIVE_DETAILS.set(session.assetId,body);session.representativeError=null;})().catch(error=>{if(!trendLocalCurrent(session)||session.representativeSequence!==sequence)return;changed=TREND_REPRESENTATIVE_DETAILS.delete(session.assetId);session.representativeError=String(error.message||error);}).finally(()=>{clearTimeout(deadline);if(session.representativePending===pending)session.representativePending=null;if(changed&&trendLocalCurrent(session)&&session.representativeSequence===sequence)session.onRepresentativeData?.();if(trendLocalCurrent(session)&&session.representativeSequence===sequence)refreshTrendLongSession(session);});session.representativePending=pending;return pending;
}
function trendLongNear(a,b){return typeof a==='number'&&Number.isFinite(a)&&typeof b==='number'&&Number.isFinite(b)&&Math.abs(a-b)<=Math.max(1e-6,Math.abs(b)*1e-10);}
function trendLongTime(value){const stamp=Date.parse(value);if(!Number.isFinite(stamp))throw new Error('장기선 공개 시각이 올바르지 않습니다');return BigInt(stamp)*1000000n+BigInt((String(value).match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1]||'').padEnd(9,'0').slice(3,9)||'0');}
function trendLongInputs(bars,lookback=756){
  const byIndex=new Map(bars.map(bar=>[bar.session_index,bar])),atr=new Map(),ranges=[],pivots=[];
  bars.forEach((bar,i)=>{if(!i||bar.session_index!==bars[i-1].session_index+1){ranges.length=0;atr.set(bar.session_index,null);return;}const prior=bars[i-1];ranges.push(Math.max(bar.high-bar.low,Math.abs(bar.high-prior.close),Math.abs(bar.low-prior.close)));atr.set(bar.session_index,ranges.length>=14?trendAccurateSum(ranges.slice(-14))/14:null);});
  for(const bar of bars){if(bar.session_index<bars.at(-1).session_index-lookback+1)continue;const neighbors=Array.from({length:21},(_,i)=>byIndex.get(bar.session_index-10+i));if(neighbors.some(row=>!row))continue;for(const [side,field] of [['support','low'],['resistance','high']]){if(neighbors.every((row,i)=>{if(i===10)return true;return side==='support'?(i<10?bar[field]<row[field]:bar[field]<=row[field]):(i<10?bar[field]>row[field]:bar[field]>=row[field]);}))pivots.push({index:bar.session_index,side,price:bar[field],bar_id:bar.bar_id});}}
  return {byIndex,atr,pivots};
}
function trendLongReview(line,inputs,bars,settings,tick){
  const {byIndex,atr,pivots}=inputs,epsilon=(value,at,block)=>Math.max(tick,settings[block].atr_multiple*at,settings[block].price_fraction*value,1e-12*value);
  let missing=0,unavailable=0,penetration=0;
  for(let i=line.first_anchor.index;i<=line.activation_index;i++){const row=byIndex.get(i),at=atr.get(i),price=trendLinePrice(line,i,line.axis);if(!row){missing++;continue;}if(at===null||at===undefined||!Number.isFinite(price)||price<=0){unavailable++;continue;}const adverse=line.origin_role==='support'?price-row.low:row.high-price;penetration=Math.max(penetration,adverse/epsilon(price,at,'touch'));}
  const touches=pivots.filter(p=>{const at=atr.get(p.index),price=trendLinePrice(line,p.index,line.axis);return p.side===line.origin_role&&p.index>=line.first_anchor.index&&at!==null&&at!==undefined&&price>0&&Math.abs(p.price-price)<=epsilon(price,at,'touch');}).sort((a,b)=>b.index-a.index||a.bar_id.localeCompare(b.bar_id));
  const contacts=[];let before=Infinity;for(const p of touches)if(p.index+10<before){contacts.push(p);before=p.index-10;}contacts.reverse();
  let broken=false,streak=0,prior=null,state='active';const breaks=[],reclaims=[];
  for(const row of bars){const i=row.session_index;if(i<=line.activation_index)continue;if(prior!==i-1)streak=0;prior=i;const at=atr.get(i),price=trendLinePrice(line,i,line.axis);if(!(price>0)){state='projection_invalid';break;}if(at===null||at===undefined){streak=0;state=broken?'broken':'active';continue;}const signed=line.origin_role==='support'?row.close-price:price-row.close,buffer=epsilon(price,at,'break'),cross=broken?signed>buffer:signed< -buffer;streak=cross?streak+1:0;if(streak>=2){broken=!broken;streak=0;(broken?breaks:reclaims).push(row.session||row.session_date);}state=streak?(broken?'reclaim_pending':'break_pending'):broken?'broken':reclaims.length?'reclaimed':'active';}
  const valid=!missing&&!unavailable&&penetration<=1+1e-10,intact=valid&&['active','reclaimed'].includes(state),reasons=[];
  if(missing)reasons.push('missing_formation_sessions');if(unavailable)reasons.push('formation_atr_unavailable');if(penetration>1+1e-10)reasons.push('formation_penetration');if(!['active','reclaimed'].includes(state))reasons.push('original_role_not_reestablished');
  return {missing,unavailable,penetration,contacts,valid,intact,state,breaks,reclaims,reasons};
}
// Additive view of the verified full-history cohort; no source or ledger writes.
// Cache only within that immutable cohort so zoom/hover never recalculate a line.
function trendBitcoinCycle(full,context,axis){
  if(full?.asset_id!=='bitcoin'||!context||!['linear','log'].includes(axis))return [];
  let cache=TREND_BITCOIN_CYCLE_CACHE.get(full);if(!cache){cache=new Map();TREND_BITCOIN_CYCLE_CACHE.set(full,cache);}if(cache.has(axis))return cache.get(axis);
  const policy=TREND_BITCOIN_CYCLE_POLICY,hold=reason=>[{slot:'cycle_2023',axis,status:'hold',reason_codes:[reason]}],bars=full.bars,last=bars.at(-1),future=context.projection_sessions;
  if(!last||!future?.length||typeof context.calculation_settings_json!=='string')return hold('verified_full_history_required');
  const settings=JSON.parse(context.calculation_settings_json),tick=context.calculation_tick_size,inputs=trendLongInputs(bars,Infinity),at=inputs.atr.get(last.session_index),pool=inputs.pivots.filter(p=>p.side==='support'),candidates=[];
  if(!settings.touch||!settings.break||!Number.isFinite(tick)||tick<0)return hold('verified_calculation_settings_required');
  if(!(at>0))return hold('latest_contiguous_atr14_unavailable');
  const over=(value,limit)=>value>limit+Math.max(1e-6,Math.abs(limit)*1e-10),anchor=p=>({...p,session:inputs.byIndex.get(p.index).session||inputs.byIndex.get(p.index).session_date,confirmation_start_index:p.index-10,confirmation_end_index:p.index+10}),transform=p=>axis==='log'?Math.log(p):p;
  for(const first of pool){const a=anchor(first);if(!a.session.startsWith(policy.anchor_year+'-'))continue;
    for(const second of pool){const b=anchor(second),gap=b.index-a.index;if(gap<policy.minimum_anchor_gap||b.session<'2024-01-01'||last.session_index-b.index>policy.maximum_second_anchor_age)continue;
      const line={slot:'cycle_2023',axis,status:'ready',kind:'pivot_structure',origin_role:'support',side:'support',first_anchor:a,second_anchor:b,coordinate_origin_index:a.index,intercept:transform(a.price),slope:(transform(b.price)-transform(a.price))/gap,display_start_index:a.index,display_end_index:future.at(-1).index,activation_index:b.index+10,verified_boundary:false,
        line_id:`bitcoin-cycle-v1-${axis}-${a.bar_id.slice(-32)}-${b.bar_id.slice(-32)}`,policy_version:policy.version,source_snapshot_id:full.source_snapshot_id,source_full_snapshot_id:full.snapshot_id,source_full_manifest_sha256:full.critical_manifest_sha256};
      const price=trendLinePrice(line,last.session_index,axis),distance=Math.abs(price-last.close);
      if(!(price>0)||!Number.isFinite(price)||future.some(p=>{const value=trendLinePrice(line,p.index,axis);return !(value>0)||!Number.isFinite(value);})||over(price,last.close)||over(distance,policy.maximum_distance_atr*at)||over(distance,policy.maximum_distance_fraction*last.close))continue;
      const review=trendLongReview(line,inputs,bars,settings,tick),contacts=review.contacts.map(anchor);
      Object.assign(line,{current_price:price,current_price_status:'ready',direction:line.slope>0?'rising':line.slope<0?'falling':'flat',role:review.intact?'support':'direction_only',classification:review.intact?'intact_structure':'reference_structure',structural_state:review.state,formation_valid:review.valid,formation_complete:!review.missing&&!review.unavailable,formation_missing_sessions:review.missing,formation_atr_unavailable:review.unavailable,formation_penetration:review.penetration,reference_reasons:review.reasons,contact_count:contacts.length,geometry_status:contacts.length>=3?'three_contact':'two_anchor',markers:contacts,independent_contacts:contacts,latest_touch_age_sessions:last.session_index-(contacts.at(-1)?.index??b.index),distance_atr:distance/at,break_sessions:review.breaks,reclaim_sessions:review.reclaims,equivalent_to_line_ids:[],points:[{index:a.index,session:a.session,price:a.price,future:false},{index:last.session_index,session:last.session||last.session_date,price,future:false}],projections:future.map(p=>({...p,price:trendLinePrice(line,p.index,axis),status:'ready'}))});
      candidates.push(line);
    }
  }
  const rank=line=>line.classification==='intact_structure'?[0,-line.contact_count,line.latest_touch_age_sessions,line.distance_atr,-(line.second_anchor.index-line.first_anchor.index)]:[1,-Number(line.formation_complete),line.formation_penetration,-line.second_anchor.index,line.distance_atr];
  candidates.sort((a,b)=>{const ar=rank(a),br=rank(b);for(let i=0;i<ar.length;i++)if(ar[i]!==br[i])return ar[i]-br[i];return a.line_id.localeCompare(b.line_id);});
  const selected=candidates.length?[candidates[0]]:hold('no_eligible_2023_confirmed_low_pair');cache.set(axis,selected);return selected;
}
function trendSameGeometry(a,b){return a.kind==='pivot_structure'&&b.kind==='pivot_structure'&&a.axis===b.axis&&a.origin_role===b.origin_role&&['first_anchor','second_anchor'].every(k=>a[k]?.bar_id===b[k]?.bar_id&&a[k]?.price===b[k]?.price)&&a.display_start_index===b.display_start_index&&a.display_end_index===b.display_end_index&&trendLongNear(a.slope,b.slope)&&trendLongNear(a.intercept,b.intercept);}
async function parseTrendLongTransport(raw,current,full,representative){
  const fail=()=>{throw new Error('장기 상·하단선의 원천 또는 계산 기준이 올바르지 않습니다');},proof=representative?.[TREND_REPRESENTATIVE_PROOF];
  if(!proof||typeof raw!=='string'||new TextEncoder().encode(raw).length>524288)fail();
  const envelope=trendUniqueJson(raw),keys='asset_id,contract_id,payload_json,payload_sha256,publication_scope,schema_version,snapshot_id';
  if(Object.keys(envelope||{}).sort().join(',')!==keys||envelope.schema_version!==1||envelope.contract_id!=='trendlines_private_long_boundaries_transport_v1'||envelope.publication_scope!=='private_only'||envelope.asset_id!==current.asset_id||typeof envelope.payload_json!=='string'||new TextEncoder().encode(envelope.payload_json).length>262144||await trendExactSha(envelope.payload_json)!==envelope.payload_sha256)fail();
  const body=trendUniqueJson(envelope.payload_json),last=full.bars.at(-1);
  if(body.schema_version!==1||body.contract_id!=='trendlines_private_long_boundaries_v1'||body.policy_version!=='long_boundaries_v1'||body.policy_sha256!==TREND_LONG_POLICY_SHA256||body.publication_scope!=='private_only'||body.rights_status!=='uncertified_research_source'||body.source_context!=='user_authorized_public_html_research'||['verified_source','verified_boundary','official_forecast_write','historical_signals_available'].some(k=>body[k]!==false)||!Array.isArray(body.events)||body.events.length||!/^long-boundaries-snapshot-[a-f0-9]{64}$/.test(body.snapshot_id||'')||body.snapshot_id!==envelope.snapshot_id||body.asset_id!==current.asset_id||body.source_representative_snapshot_id!==representative.snapshot_id||body.source_representative_payload_sha256!==proof.payload)fail();
  for(const key of ['as_of','source_snapshot_id','source_archive_sha256','source_content_hash','source_full_snapshot_id','source_full_content_hash','source_engine_snapshot_id','source_engine_content_hash','full_manifest_payload_sha256','reference_close','reference_index','reference_session','input_hash','input_bar_ids_hash','atr14'])if(body[key]!==representative[key])fail();
  if(!trendSameValue(body.projection_sessions,representative.projection_sessions)||body.config_sha256!==current.config_sha256||typeof body.calculation_settings_json!=='string'||await trendExactSha(body.calculation_settings_json)!==body.config_sha256||body.calculation_tick_size!==(current.asset.tick_size??0)||!Number.isFinite(body.calculation_tick_size)||body.calculation_tick_size<0||Object.keys(body.analyses||{}).sort().join(',')!=='linear,log')fail();
  const settings=trendUniqueJson(body.calculation_settings_json),inputs=trendLongInputs(full.bars),future=body.projection_sessions,near=trendLongNear;
  if(settings.atr?.period!==14||settings.touch?.atr_multiple!==.25||settings.touch?.price_fraction!==.001||settings.break?.atr_multiple!==.5||settings.break?.price_fraction!==.0025||settings.break?.consecutive_closes!==2)fail();
  for(const axis of ['linear','log']){
    const lines=body.analyses[axis]?.boundaries;if(!Array.isArray(lines)||lines.length!==2||lines.some((line,i)=>line.slot!==TREND_LONG_SLOTS[i]))fail();
    for(const line of lines){
      if(line.axis!==axis||line.kind!=='pivot_structure'||line.verified_boundary!==false)fail();
      if(line.status==='hold'){if(line.current_price!==null||line.points?.length||line.projections?.length||line.markers?.length||!Array.isArray(line.reason_codes)||!line.reason_codes.length)fail();continue;}
      const side=line.slot==='long_upper'?'resistance':'support',first=line.first_anchor,second=line.second_anchor;
      if(line.status!=='ready'||line.origin_role!==side||first?.side!==side||second?.side!==side||!Number.isInteger(first?.index)||!Number.isInteger(second?.index)||first.index<last.session_index-755||second.index-first.index<60||last.session_index-second.index>252||line.parameters?.left!==10||line.parameters?.right!==10||line.parameters?.min_anchor_gap!==60||line.display_start_index!==first.index||line.coordinate_origin_index!==first.index||line.display_end_index!==future.at(-1).index||line.activation_index!==second.confirmation_end_index||line.activation_session!==second.confirmation_session||!Array.isArray(line.contacts)||!Array.isArray(line.markers)||!Array.isArray(line.equivalent_to_line_ids))fail();
      const id='long-boundary-line-'+(await trendExactSha(JSON.stringify({axis,first_bar_id:first.bar_id,origin_role:side,policy_sha256:TREND_LONG_POLICY_SHA256,second_bar_id:second.bar_id,slot:line.slot}))).slice(0,32);if(line.line_id!==id)fail();
      for(const p of [first,second,...line.contacts,...line.markers]){
        const bar=inputs.byIndex.get(p?.index),field=side==='support'?'low':'high';if(!bar||p.side!==side||p.bar_id!==bar.bar_id||p.price!==bar[field]||p.session!==(bar.session||bar.session_date)||p.confirmation_start_index!==p.index-10||p.confirmation_end_index!==p.index+10||p.confirmation_end_index>last.session_index||(inputs.byIndex.get(p.confirmation_end_index)?.session||inputs.byIndex.get(p.confirmation_end_index)?.session_date)!==p.confirmation_session)fail();
        // The compact full-bars contract omits receipt timestamps. Its frozen
        // source/replay supplies vintage proof; confirmation still cannot be
        // later than this bound snapshot. Rich source fixtures check the max too.
        let known=null;for(let i=p.index-10;i<=p.index+10;i++){const neighbor=inputs.byIndex.get(i);if(!neighbor)fail();if(Object.hasOwn(neighbor,'available_at')||Object.hasOwn(neighbor,'fetched_at'))for(const k of ['available_at','fetched_at']){const instant=trendLongTime(neighbor[k]);if(known===null||instant>known)known=instant;}if(i===p.index)continue;if(side==='support'?(i<p.index?p.price>=neighbor.low:p.price>neighbor.low):(i<p.index?p.price<=neighbor.high:p.price<neighbor.high))fail();}if(known!==null&&trendLongTime(p.confirmed_at)!==known||trendLongTime(p.confirmed_at)>trendLongTime(body.as_of))fail();
      }
      const y=axis==='log'?Math.log: value=>value,slope=(y(second.price)-y(first.price))/(second.index-first.index);if(!near(line.slope,slope)||!near(line.intercept,y(first.price))||line.direction!==(slope>0?'rising':slope<0?'falling':'flat')||trendLongTime(line.activation_asof)!==[trendLongTime(first.confirmed_at),trendLongTime(second.confirmed_at)].reduce((a,b)=>a>b?a:b))fail();
      const review=trendLongReview(line,inputs,full.bars,settings,body.calculation_tick_size),price=trendLinePrice(line,last.session_index,axis),distance=Math.abs(price-last.close),at=body.atr14,tolerance=Math.max(1e-6,last.close*1e-10);
      if(!(price>0)||!near(line.current_price,price)||!(at>0)||(side==='support'?price>last.close+tolerance:price<last.close-tolerance)||distance>8*at+Math.max(1e-6,8*at*1e-10)||distance>.5*last.close+tolerance||!near(line.distance_atr,distance/at)||line.formation_valid!==review.valid||line.formation_complete!==(!review.missing&&!review.unavailable)||line.formation_missing_sessions!==review.missing||line.formation_atr_unavailable!==review.unavailable||!near(line.formation_penetration,review.penetration)||line.classification!==(review.intact?'intact_structure':'reference_structure')||line.role!==(review.intact?side:'direction_only')||line.structural_state!==review.state||!trendSameValue(line.reference_reasons,review.reasons)||!trendSameValue(line.structural_review?.break_sessions,review.breaks)||!trendSameValue(line.structural_review?.reclaim_sessions,review.reclaims)||line.contact_count!==review.contacts.length||line.contacts.length!==review.contacts.length||line.contacts.some((p,i)=>p.index!==review.contacts[i].index)||!trendSameValue(line.independent_contacts,line.contacts)||line.geometry_status!==(line.contact_count>=3?'three_contact':'two_anchor')||line.contact_count<2)fail();
      const aliases=representative.analyses[axis].representatives.filter(other=>other.status==='ready'&&trendSameGeometry(line,other)).map(other=>other.line_id);if(!trendSameValue(line.equivalent_to_line_ids,aliases)||line.markers.length!==2||line.markers[0].bar_id!==first.bar_id||line.markers[1].bar_id!==second.bar_id)fail();
      if(!Array.isArray(line.points)||line.points.length!==2||!Array.isArray(line.projections)||line.projections.length!==future.length)fail();
      for(const p of line.points){const bar=inputs.byIndex.get(p.index);if(!bar||p.session!==(bar.session||bar.session_date)||p.future!==false||!near(p.price,trendLinePrice(line,p.index,axis))||['open','high','low','close','volume'].some(k=>Object.hasOwn(p,k)))fail();}
      if(line.points[0].index!==first.index||line.points[1].index!==last.session_index)fail();
      for(const [i,p] of line.projections.entries())if(p.index!==future[i].index||p.session!==future[i].session||p.offset!==future[i].offset||p.status!=='ready'||!(p.price>0)||!near(p.price,trendLinePrice(line,p.index,axis))||['open','high','low','close','volume'].some(k=>Object.hasOwn(p,k)))fail();
    }
  }
  Object.defineProperty(body,TREND_LONG_PROOF,{value:{source:current.snapshot_id,full:full.snapshot_id,representative:representative.snapshot_id,payload:envelope.payload_sha256,representativePayload:proof.payload}});return body;
}
async function refreshTrendLongSession(session){
  const current=TREND_PRIVATE_DETAILS.get(session.assetId),full=TREND_FULL_DETAILS.get(session.assetId),representative=TREND_REPRESENTATIVE_DETAILS.get(session.assetId);
  if(!session.longMounted||!current||!full||!representative?.[TREND_REPRESENTATIVE_PROOF]||full.source_snapshot_id!==current.snapshot_id||representative.source_snapshot_id!==current.snapshot_id||!trendLocalCurrent(session)||!trendLocalVisible())return;
  const key=current.snapshot_id+'|'+full.snapshot_id+'|'+representative.snapshot_id;if(session.longPending&&session.longSource===key)return session.longPending;
  session.longController?.abort();const controller=new AbortController(),sequence=(session.longSequence||0)+1;session.longSequence=sequence;session.longController=controller;session.longSource=key;let changed=false;
  const active=()=>trendLocalCurrent(session)&&session.longSequence===sequence&&!controller.signal.aborted&&TREND_PRIVATE_DETAILS.get(session.assetId)?.snapshot_id===current.snapshot_id&&TREND_FULL_DETAILS.get(session.assetId)?.snapshot_id===full.snapshot_id&&TREND_REPRESENTATIVE_DETAILS.get(session.assetId)?.snapshot_id===representative.snapshot_id;
  const deadline=setTimeout(()=>controller.abort(),60000),options={method:'GET',mode:'cors',credentials:'omit',cache:'no-store',redirect:'error',targetAddressSpace:'loopback',signal:controller.signal};
  const pending=(async()=>{const body=await parseTrendLongTransport(await readTrendLocalResponse(await fetch(TREND_LOCAL_BASE+session.assetId+'/long-boundaries',options),524288),current,full,representative);if(!active())return;changed=TREND_LONG_DETAILS.get(session.assetId)?.snapshot_id!==body.snapshot_id;TREND_LONG_DETAILS.set(session.assetId,body);session.longError=null;})().catch(error=>{if(!trendLocalCurrent(session)||session.longSequence!==sequence)return;TREND_LONG_DETAILS.delete(session.assetId);changed=true;session.longError=String(error.message||error);}).finally(()=>{clearTimeout(deadline);if(session.longPending===pending)session.longPending=null;if(changed&&trendLocalCurrent(session)&&session.longSequence===sequence)session.onRepresentativeData?.();});session.longPending=pending;return pending;
}
function trendMergeSelectedLines(selected){
  const lines=[];for(const line of selected){const same=lines.find(other=>trendSameGeometry(line,other));if(same){same.alias_labels.push(TREND_REPRESENTATIVE_LABELS[line.slot]);same.alias_slots.push(line.slot);if(line.classification==='reference_structure')same.classification='reference_structure';}else lines.push({...line,label:TREND_REPRESENTATIVE_LABELS[line.slot],independent_contacts:line.markers||[],alias_labels:[TREND_REPRESENTATIVE_LABELS[line.slot]],alias_slots:[line.slot]});}return lines;
}
function trendLongBoundaryRows(analysis,asset){
  if(!['all','long_boundaries'].includes(analysis.family))return '';
  const lines=[...(analysis.long_boundaries.length?analysis.long_boundaries:TREND_LONG_SLOTS.map(slot=>({slot,status:'hold'}))),...(analysis.cycle_2023||[])];
  return `<div class="trend-long-rows" aria-label="장기 고점·저점 연결선">${lines.map(line=>{const ready=line.status==='ready',intact=line.classification==='intact_structure',status=!ready?'추가선 미산출':intact?`${line.contact_count>=3?'3회 이상 접촉':'2점 연결'} · 형성·현재 역할 충족`:`구조 참고선 · ${!line.formation_complete?'형성구간 자료 부족':line.structural_state!=='active'&&line.structural_state!=='reclaimed'?'이탈 이력':'과거 관통'}`,alias=line.equivalent_to_line_ids?.length?' · 같은 선은 차트에서 통합 표시':'';return `<article data-trend-long-row="${line.slot}" style="--trend-slot:${TREND_REPRESENTATIVE_COLORS[line.slot]}"><div><span>${esc(TREND_REPRESENTATIVE_LABELS[line.slot])}</span><small>${esc(status)}</small></div><strong${ready?` data-trend-long-price="${esc(line.line_id)}"`:''}>${ready?esc(trendPrice(line.current_price,asset)):'—'}</strong><p>${ready?`${esc(line.first_anchor.session)} ${esc(trendPrice(line.first_anchor.price,asset))} → ${esc(line.second_anchor.session)} ${esc(trendPrice(line.second_anchor.price,asset))}${esc(alias)}`:'확정 고저점과 추가선 자료를 확인합니다.'}</p></article>`;}).join('')}</div>`;
}
function trendLongBoundaryDetails(analysis,asset){
  return [...analysis.long_boundaries,...(analysis.cycle_2023||[])].map(line=>`<p><strong>${esc(TREND_REPRESENTATIVE_LABELS[line.slot])}</strong> · ${line.status!=='ready'?'적격 확정 고저점 연결선 미산출':`${line.contact_count}개 독립 접촉 · 확정 피벗 10·10 · ${esc(line.first_anchor.session)} ${esc(trendPrice(line.first_anchor.price,asset))} → ${esc(line.second_anchor.session)} ${esc(trendPrice(line.second_anchor.price,asset))} · ${line.classification==='intact_structure'?'형성·현재 역할 충족':'구조 참고선'} · 형성구간 결측 ${line.formation_missing_sessions}개 · ATR 확인 불가 ${line.formation_atr_unavailable}개${line.slot==='cycle_2023'?` · ${esc(line.policy_version)} · 종가 2회 이탈 ${line.break_sessions.length}회 · 재진입 ${line.reclaim_sessions.length}회`:''}`}</p>`).join('');
}
function trendRepresentativeAnalysis(current,full,axis,family='all'){
  const body=TREND_REPRESENTATIVE_DETAILS.get(current.asset_id),proof=body?.[TREND_REPRESENTATIVE_PROOF],valid=!!(full&&proof&&proof.source===current.snapshot_id&&proof.sourceHash===current.content_hash&&proof.full===full.snapshot_id&&proof.manifest===full.critical_manifest_sha256&&body.as_of===current.as_of);
  const representatives=valid?body.analyses[axis].representatives:[],supplement=TREND_LONG_DETAILS.get(current.asset_id),longProof=supplement?.[TREND_LONG_PROOF],longValid=valid&&longProof&&longProof.source===current.snapshot_id&&longProof.full===full.snapshot_id&&longProof.representative===body.snapshot_id&&longProof.representativePayload===proof.payload;
  const long_boundaries=longValid?supplement.analyses[axis].boundaries:[],cycle_2023=longValid?trendBitcoinCycle(full,supplement,axis):[],selected=[...representatives,...long_boundaries,...cycle_2023].filter(line=>line.status==='ready'&&(family==='all'||family==='long_boundaries'&&[...TREND_LONG_SLOTS,'cycle_2023'].includes(line.slot)||line.slot===family)),lines=trendMergeSelectedLines(selected);
  return {status:'ready',critical:true,representative:true,axis,family,lines,representatives,long_boundaries,cycle_2023,long_body:longValid?supplement:null,projection_sessions:valid?body.projection_sessions:[],representative_body:valid?body:null,critical_reference:valid?{price:body.reference_close,atr14:body.atr14,date:body.reference_session,index:body.reference_index}:null};
}
function trendLineStart(line){return line.display_start_index??line.first_anchor?.index;}
function trendRepresentativeName(line){return `${line.alias_labels?.join(' · ')||TREND_REPRESENTATIVE_LABELS[line.slot]||'추세선'}${line.classification==='reference_structure'?' · 구조 참고선':''}${line.kind==='regression'&&line.slot!=='regression_200'?` · ${line.fit.n}일 회귀`:''}`;}
function trendPlotFrame(width,view,height,maxPrice=0){
  const W=Math.max(330,Math.round(width)),narrow=W<600;
  if(view?.axis==='right'){const digits=Math.max(1,Math.floor(Math.log10(Math.max(1,Math.abs(maxPrice))))+1),chars=digits+Math.floor((digits-1)/3)+(digits>=7?0:3);return {W,H:Math.max(240,Math.round(view.height||(narrow?380:height))),L:4,R:Math.max(54,Math.min(100,Math.round(chars*7+16))),T:10,B:26,axisRight:true};}
  return {W,H:narrow?380:height,L:narrow?62:88,R:20,T:24,B:46,axisRight:false};
}
// A manual price range is held in transformed (linear or log) units until auto scale returns.
function trendFrameRange(low,high,view){const range=view?.yRange;return Array.isArray(range)&&range.length===2&&range.every(Number.isFinite)&&range[1]>range[0]?[range[0],range[1]]:[low,high];}
function trendNiceTicks(m){
  const bottom=m.ticks[0],top=m.ticks.at(-1),count=Math.max(3,Math.round((m.H-m.T-m.B)/56));
  if(!(top>bottom))return m.ticks;
  if(m.scale==='log'&&bottom>0&&top/bottom>=4){const nice=value=>{const power=10**Math.floor(Math.log10(value)),f=value/power;return [1,1.5,2,2.5,3,4,5,6,8,10].reduce((a,b)=>Math.abs(b-f)<Math.abs(a-f)?b:a)*power;},out=[];for(let i=0;i<=count;i++){const value=+nice(Math.exp(Math.log(bottom)+(Math.log(top)-Math.log(bottom))*i/count)).toPrecision(12);if(value>=bottom&&value<=top&&!out.includes(value))out.push(value);}return out.length>=2?out:m.ticks;}
  const raw=(top-bottom)/count,power=10**Math.floor(Math.log10(raw)),step=[1,2,2.5,5,10].map(f=>f*power).find(value=>value>=raw-1e-12)||10*power,out=[];
  for(let value=Math.ceil(bottom/step-1e-9)*step;value<=top+step*1e-9&&out.length<40;value+=step)if(value>0)out.push(+value.toPrecision(12));
  return out.length>=2?out:m.ticks;
}
function trendAxisNumber(value,ticks){const span=ticks.length>1?Math.abs(ticks.at(-1)-ticks[0])/(ticks.length-1):Math.abs(value),digits=span>=10?0:span>=1?1:span>=.1?2:4;return Number(value).toLocaleString('ko-KR',{minimumFractionDigits:digits,maximumFractionDigits:digits});}
function trendAxisPrice(value,asset){const whole=(asset?.price_unit==='KRW_per_share'||asset?.price_unit==='KRW')&&value>=100;return Number(value).toLocaleString('ko-KR',{minimumFractionDigits:whole?0:2,maximumFractionDigits:whole?0:2});}
function trendPlotModel(detail,analysis,bars,scale,width,view=null){
  if(analysis.representative)return trendRepresentativePlotModel(detail,analysis,bars,scale,width,view);
  if(analysis.critical)return trendCriticalPlotModel(detail,analysis,bars,scale,width,view);
  const first=bars[0].session_index,last=bars.at(-1).session_index;
  const lines=analysis.lines,points=lines.flatMap(line=>line.points.filter(point=>point.index>=first));
  const gaps=(detail.gaps||[]).filter(gap=>gap.session_index>=first);
  const quote=Number.isInteger(detail.intraday_quote?.session_index)&&detail.intraday_quote.session_index>=first?detail.intraday_quote:null;
  const end=Math.max(last+1,...points.map(point=>point.index),...gaps.map(gap=>gap.session_index),quote?.session_index??last),prices=bars.flatMap(bar=>[bar.low,bar.high]).concat(points.map(point=>point.price),quote?[quote.price]:[]);
  const transform=value=>scale==='log'?Math.log(value):value,inverse=value=>scale==='log'?Math.exp(value):value;
  let low=Math.min(...prices.map(transform)),high=Math.max(...prices.map(transform)),pad=(high-low)*.07||Math.abs(high)*.02||1;
  low=scale==='linear'?Math.max(0,low-pad):low-pad;high+=pad;[low,high]=trendFrameRange(low,high,view);
  const {W,H,L,R,T,B,axisRight}=trendPlotFrame(width,view,440,inverse(high));
  const x=index=>L+(index-first)/Math.max(1,end-first)*(W-L-R),y=price=>T+(high-transform(price))/(high-low)*(H-T-B);
  return {bars,lines,analysis,gaps,quote,first,last,end,W,H,L,R,T,B,x,y,scale,axisRight,range:[low,high],ticks:Array.from({length:5},(_,i)=>inverse(low+(high-low)*i/4))};
}
function trendRepresentativePlotModel(detail,analysis,bars,scale,width,view=null){
  const first=bars[0].session_index,last=bars.at(-1).session_index,sourceLast=detail.bars.at(-1).session_index,future=last===sourceLast&&analysis.lines.length?analysis.projection_sessions:[],dateMap=new Map(detail.bars.map(bar=>[bar.session_index,bar.session||bar.session_date])),futureMap=new Map(future.map(row=>[row.index,row.session]));
  const quote=last===sourceLast&&detail.intraday_quote?.session_index>=first?detail.intraday_quote:null,end=Math.max(last,future.at(-1)?.index||last,quote?.session_index||last),gaps=(detail.gaps||[]).filter(row=>row.session_index>=first&&row.session_index<=end);
  const lines=analysis.lines.map(line=>{const indices=[...new Set([Math.max(first,line.display_start_index),...bars.map(bar=>bar.session_index),...future.map(row=>row.index)])].filter(index=>index>=line.display_start_index&&index<=end).sort((a,b)=>a-b);return {...line,points:indices.map(index=>({index,price:trendLinePrice(line,index,scale),session:dateMap.get(index)||futureMap.get(index),future:index>sourceLast})).filter(point=>Number.isFinite(point.price)&&point.price>0)};});
  const candlePrices=bars.flatMap(bar=>[bar.low,bar.high]),candleLow=Math.min(...candlePrices),candleHigh=Math.max(...candlePrices),range=candleHigh-candleLow,atr=analysis.critical_reference?.atr14||0,allowance=Math.max(4*atr,.2*range),minimum=Math.max(candleLow*.7,candleLow-allowance),maximum=Math.min(candleHigh*1.3,candleHigh+allowance);
  const prices=candlePrices.concat(lines.flatMap(line=>line.points.filter(point=>point.price>=minimum&&point.price<=maximum).map(point=>point.price)),quote?[quote.price]:[]),transform=value=>scale==='log'?Math.log(value):value,inverse=value=>scale==='log'?Math.exp(value):value;
  let low=Math.min(...prices.map(transform)),high=Math.max(...prices.map(transform)),pad=(high-low)*.07||Math.abs(high)*.02||1;low=scale==='linear'?Math.max(0,low-pad):low-pad;high+=pad;[low,high]=trendFrameRange(low,high,view);
  const {W,H,L,R,T,B,axisRight}=trendPlotFrame(width,view,460,inverse(high)),x=index=>L+(index-first)/Math.max(1,end-first)*(W-L-R),y=price=>T+(high-transform(price))/(high-low)*(H-T-B);
  return {bars,lines,analysis,gaps,quote,first,last,end,sourceLast,W,H,L,R,T,B,x,y,scale,axisRight,range:[low,high],cssWidth:Number(width)||W,critical:true,representative:true,ticks:Array.from({length:5},(_,i)=>inverse(low+(high-low)*i/4))};
}
function trendRepresentativeViewport(detail,analysis,scope='recent'){
  if(scope==='all')return detail.bars;
  const major=analysis.lines.filter(line=>line.kind==='pivot_structure'&&line.first_anchor).sort((a,b)=>a.first_anchor.index-b.first_anchor.index)[0];
  if(scope==='anchors'&&major?.first_anchor){const position=detail.bars.findIndex(bar=>bar.session_index===major.first_anchor.index);if(position>=0)return detail.bars.slice(Math.max(0,position-10));}
  if(scope==='anchors')return detail.bars.slice(-252);
  if(detail.asset_id==='bitcoin'&&analysis.family==='all')return detail.bars.slice(-1095);
  if(analysis.family==='current_structure')return detail.bars.slice(-126);
  if(analysis.family==='regression_200')return detail.bars.slice(-252);
  if(['major_structure','long_boundaries'].includes(analysis.family)&&major?.first_anchor){const position=detail.bars.findIndex(bar=>bar.session_index===major.first_anchor.index);if(position>=0)return detail.bars.slice(Math.max(0,position-10));}
  const position=major?.first_anchor?detail.bars.findIndex(bar=>bar.session_index===major.first_anchor.index):-1;
  return detail.bars.slice(-(position>=detail.bars.length-504&&position<detail.bars.length-252?504:252));
}
function trendCriticalPlotModel(detail,analysis,bars,scale,width,view=null){
  const first=bars[0].session_index,last=bars.at(-1).session_index,sourceLast=detail.bars.at(-1).session_index;
  const future=last===sourceLast&&analysis.lines.length?analysis.projection_sessions:[],dateMap=new Map(detail.bars.map(bar=>[bar.session_index,bar.session||bar.session_date])),futureMap=new Map(analysis.projection_sessions.map(row=>[row.index,row.session])),visibleQuote=last===sourceLast&&detail.intraday_quote?.session_index>=first?detail.intraday_quote:null,end=Math.max(last,future.at(-1)?.index||last,visibleQuote?.session_index||last);
  const lines=analysis.lines.map(line=>{const indices=[...new Set([Math.max(first,line.first_anchor.index),...bars.map(bar=>bar.session_index),...future.map(row=>row.index)])].filter(index=>index>=line.first_anchor.index&&index<=end).sort((a,b)=>a-b);return {...line,side:line.role,points:indices.map(index=>({index,price:trendLinePrice(line,index,scale),future:index>sourceLast,session:dateMap.get(index)||futureMap.get(index)})).filter(point=>Number.isFinite(point.price)&&point.price>0)};});
  const gaps=(detail.gaps||[]).filter(gap=>gap.session_index>=first&&gap.session_index<=end),quote=visibleQuote;
  const candlePrices=bars.flatMap(bar=>[bar.low,bar.high]),candleLow=Math.min(...candlePrices),candleHigh=Math.max(...candlePrices),atr=analysis.critical_reference?.atr14||0;
  const prices=candlePrices.concat(lines.flatMap(line=>line.points.filter(point=>!point.future||point.price>=Math.max(candleLow-4*atr,candleLow*.8)&&point.price<=Math.min(candleHigh+4*atr,candleHigh*1.2)).map(point=>point.price)),lines.filter(line=>line.kind==='horizontal_zone'&&line.points.length>=2).flatMap(line=>[line.zone_low,line.zone_high]),quote?[quote.price]:[]);
  const transform=value=>scale==='log'?Math.log(value):value,inverse=value=>scale==='log'?Math.exp(value):value;let low=Math.min(...prices.map(transform)),high=Math.max(...prices.map(transform)),pad=(high-low)*.07||Math.abs(high)*.02||1;
  low=scale==='linear'?Math.max(0,low-pad):low-pad;high+=pad;[low,high]=trendFrameRange(low,high,view);
  const {W,H,L,R,T,B,axisRight}=trendPlotFrame(width,view,440,inverse(high)),x=index=>L+(index-first)/Math.max(1,end-first)*(W-L-R),y=price=>T+(high-transform(price))/(high-low)*(H-T-B);
  return {bars,lines,analysis,gaps,quote,first,last,end,sourceLast,W,H,L,R,T,B,x,y,scale,axisRight,range:[low,high],cssWidth:Number(width)||W,critical:true,ticks:Array.from({length:5},(_,i)=>inverse(low+(high-low)*i/4))};
}
function trendFullViewport(detail,analysis,scope='anchors'){
  if(scope==='all')return detail.bars;
  const indices=new Set(detail.bars.map(bar=>bar.session_index)),anchors=(analysis.lines||[]).map(line=>line.first_anchor?.index).filter(index=>Number.isInteger(index)&&indices.has(index));
  if(analysis.critical){if(!anchors.length)return detail.bars.slice(-252);const position=detail.bars.findIndex(bar=>bar.session_index===Math.min(...anchors));return detail.bars.slice(Math.max(0,position-10));}
  return anchors.length?detail.bars.filter(bar=>bar.session_index>=Math.min(...anchors)):detail.bars;
}
// Personal drawing coordinates never enter the source, automatic models or ledgers.
function trendManualDate(value){
  return typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value+'T00:00:00Z'))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;
}
function trendManualValidate(value,assetId){
  const keys=(v,expected)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===expected.split(',').sort().join(',');
  const anchor=p=>keys(p,'session,price')&&trendManualDate(p.session)&&Number.isFinite(p.price)&&p.price>0&&p.price<=1e15;
  if(!TREND_VISIBLE_ASSETS.some(a=>a[0]===assetId)||!keys(value,'schema_version,asset_id,lines')||value.schema_version!==1||value.asset_id!==assetId||!Array.isArray(value.lines)||value.lines.length>TREND_MANUAL_LIMIT)throw new Error('직접 그린 선의 저장 형식을 확인할 수 없습니다');
  const ids=new Set(),numbers=new Set();
  for(const line of value.lines){
    if(!keys(line,'id,number,a,b,extend')||!/^manual-[a-z0-9-]{1,80}$/.test(line.id)||ids.has(line.id)||!Number.isSafeInteger(line.number)||line.number<1||numbers.has(line.number)||typeof line.extend!=='boolean'||!anchor(line.a)||!anchor(line.b)||line.a.session>=line.b.session)throw new Error('직접 그린 선의 기준점을 확인할 수 없습니다');
    ids.add(line.id);numbers.add(line.number);
  }
  return value.lines.map(line=>({...line,a:{...line.a},b:{...line.b}}));
}
// Browser-only workspace. IndexedDB transactions are the sole confirmed-save boundary.
const TREND_WORKSPACE_DB='jins-trendlines-workspace-v2',TREND_WORKSPACE_STORE='documents';
const TREND_MANUAL_STYLE=Object.freeze({color:'#7056a3',opacity:1,width:1.1,dash:'solid',arrow:'none',labels:false,stats:true});
let TREND_WORKSPACE_OPEN=null,TREND_MANUAL_CLIPBOARD=null,TREND_TEMPLATE_STATE={revision:0,items:[],default_id:null};
const trendManualCopy=value=>JSON.parse(JSON.stringify(value));
const TREND_MANUAL_TAB=(()=>{try{let id=globalThis.sessionStorage?.getItem('jins-trendline-tab');if(!id||globalThis.performance?.getEntriesByType?.('navigation')?.[0]?.type==='navigate'){id=globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);globalThis.sessionStorage?.setItem('jins-trendline-tab',id);}return id;}catch(_){return Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);}})();
function trendWorkspaceOpen(){
  if(TREND_WORKSPACE_OPEN)return TREND_WORKSPACE_OPEN;
  TREND_WORKSPACE_OPEN=new Promise((resolve,reject)=>{
    if(!globalThis.indexedDB){reject(new Error('브라우저 저장소를 사용할 수 없습니다'));return;}
    const request=indexedDB.open(TREND_WORKSPACE_DB,1);
    request.onupgradeneeded=()=>request.result.createObjectStore(TREND_WORKSPACE_STORE,{keyPath:'key'});
    request.onerror=()=>reject(request.error);request.onblocked=()=>reject(new Error('다른 탭을 닫은 뒤 다시 시도해 주세요'));
    request.onsuccess=()=>{const db=request.result;db.onversionchange=()=>{db.close();TREND_WORKSPACE_OPEN=null;};resolve(db);};
  }).catch(error=>{TREND_WORKSPACE_OPEN=null;throw error;});return TREND_WORKSPACE_OPEN;
}
async function trendWorkspaceRead(){const db=await trendWorkspaceOpen();return new Promise((resolve,reject)=>{const tx=db.transaction(TREND_WORKSPACE_STORE,'readonly'),request=tx.objectStore(TREND_WORKSPACE_STORE).getAll();tx.oncomplete=()=>resolve(request.result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||new Error('읽기 취소'));});}
async function trendWorkspaceWrite(key,value,expected=undefined){
  const db=await trendWorkspaceOpen();return new Promise((resolve,reject)=>{
    const tx=db.transaction(TREND_WORKSPACE_STORE,'readwrite'),store=tx.objectStore(TREND_WORKSPACE_STORE),request=store.get(key);let conflict=false,result;
    request.onsuccess=()=>{const revision=request.result?.revision||0;if(expected!==undefined&&revision!==expected){conflict=true;tx.abort();return;}result={...trendManualCopy(value),key,revision:revision+1};if(key.startsWith('dismiss:'))result.items=[...new Set([...(request.result?.items||[]),...result.items])].slice(-100);store.put(result);};
    tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(Object.assign(new Error(conflict?'다른 탭의 저장본이 변경됐습니다':'저장 트랜잭션이 취소됐습니다'),{conflict}));
  });
}
async function trendWorkspaceCommit(asset,payload,revision,templates=null){
  const db=await trendWorkspaceOpen();return new Promise((resolve,reject)=>{
    const tx=db.transaction(TREND_WORKSPACE_STORE,'readwrite'),store=tx.objectStore(TREND_WORKSPACE_STORE),items=[{key:'asset:'+asset,value:payload,expected:revision}];
    if(templates)items.push({key:'templates',value:templates,expected:templates.revision});let conflict=false,saved;
    for(const item of items){const read=store.get(item.key);read.onsuccess=()=>{const previous=read.result?.revision||0;if(previous!==item.expected){conflict=true;tx.abort();return;}const value={...trendManualCopy(item.value),key:item.key,revision:previous+1};store.put(value);if(item.key.startsWith('asset:'))saved=value;};}
    tx.oncomplete=()=>resolve(saved);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(Object.assign(new Error(conflict?'다른 탭의 저장본 또는 템플릿이 변경됐습니다':'저장 취소'),{conflict}));
  });
}
let TREND_TEMPLATE_PENDING=false;
function trendManualStyleCheck(style){
  if(!style||Object.keys(style).sort().join(',')!==Object.keys(TREND_MANUAL_STYLE).sort().join(',')||!/^#[a-fA-F0-9]{6}$/.test(style.color)||!Number.isFinite(style.opacity)||style.opacity<.1||style.opacity>1||!Number.isFinite(style.width)||style.width<.5||style.width>6||!['solid','dash','dot'].includes(style.dash)||!['none','start','end','both'].includes(style.arrow)||typeof style.labels!=='boolean'||typeof style.stats!=='boolean')throw new Error('선 스타일이 올바르지 않습니다');return {...style};
}
function trendManualUpgrade(line){return {...trendManualCopy(line),axis:'legacy',extension:line.extend?'right':'none',name:'내 빗각선 '+line.number,note:'',style:{...TREND_MANUAL_STYLE},hidden:false,locked:false};}
function trendManualValidateV2(lines,assetId){
  if(!TREND_VISIBLE_ASSETS.some(a=>a[0]===assetId)||!Array.isArray(lines)||lines.length>TREND_MANUAL_LIMIT)throw new Error('자산 또는 선 개수(최대 20개)를 확인해 주세요');
  const ids=new Set(),numbers=new Set(),keys='a,axis,b,extend,extension,hidden,id,locked,name,note,number,style';
  for(const l of lines){
    if(!l||Object.keys(l).sort().join(',')!==keys||!/^manual-[a-z0-9-]{1,80}$/.test(l.id)||ids.has(l.id)||!Number.isSafeInteger(l.number)||l.number<1||numbers.has(l.number)||!['legacy','linear','log'].includes(l.axis)||!['none','left','right','both'].includes(l.extension)||typeof l.extend!=='boolean'||l.extend!==['right','both'].includes(l.extension)||typeof l.name!=='string'||l.name.length>80||typeof l.note!=='string'||l.note.length>500||typeof l.hidden!=='boolean'||typeof l.locked!=='boolean')throw new Error('개인 선 형식이 올바르지 않습니다');
    for(const p of [l.a,l.b])if(!p||Object.keys(p).sort().join(',')!=='price,session'||!trendManualDate(p.session)||!Number.isFinite(p.price)||p.price<=0||p.price>1e15)throw new Error('기준점 날짜·가격이 올바르지 않습니다');
    if(l.a.session>=l.b.session)throw new Error('서로 다른 두 날짜를 시간순으로 선택해 주세요');trendManualStyleCheck(l.style);ids.add(l.id);numbers.add(l.number);
  }return trendManualCopy(lines);
}
function trendManualViewCheck(view){
  if(!view||Object.keys(view).some(k=>!['family','scope','scale','window','priceStep','snap','continuous'].includes(k))||!['all',...TREND_REPRESENTATIVE_SLOTS,'long_boundaries'].includes(view.family)||!['all','anchors','recent'].includes(view.scope)||!['linear','log'].includes(view.scale)||!Number.isFinite(view.priceStep)||view.priceStep<=0||view.priceStep>1e15||!['off','weak','strong'].includes(view.snap)||typeof view.continuous!=='boolean')throw new Error('화면 설정 형식이 올바르지 않습니다');
  if(view.window!==null&&(!view.window||Object.keys(view.window).sort().join(',')!=='end,factor,start,tail'||!trendManualDate(view.window.start)||!trendManualDate(view.window.end)||view.window.start>view.window.end||!Number.isFinite(view.window.factor)||view.window.factor<1||view.window.factor>8||typeof view.window.tail!=='boolean'))throw new Error('확대 구간이 올바르지 않습니다');return trendManualCopy(view);
}
function trendManualDocumentCheck(doc,assetId){
  if(doc?.revision!==undefined&&(!Number.isSafeInteger(doc.revision)||doc.revision<1))throw new Error('저장 revision 확인 불가');
  if(!doc||doc.schema_version!==2||doc.asset_id!==assetId||doc.unit!==TREND_PRIVATE_IDENTITIES[assetId]?.[4]||Object.keys(doc).some(k=>!['key','revision','schema_version','asset_id','unit','lines','view','saved_at','base_revision','tab_id','updated_at','edit_draft'].includes(k)))throw new Error('저장본 자산·단위·버전이 올바르지 않습니다');
  if(doc.edit_draft!==undefined&&doc.edit_draft!==null){const d=doc.edit_draft;if(typeof d!=='object'||Array.isArray(d)||Object.keys(d).some(k=>!['id','name','note','a_session','a_price','b_session','b_price','extension','color','opacity','width','dash','arrow','labels','stats'].includes(k))||!doc.lines.some(l=>l.id===d.id)||JSON.stringify(d).length>4096)throw new Error('임시 입력 형식 확인 불가');}
  return {lines:trendManualValidateV2(doc.lines,assetId),view:trendManualViewCheck(doc.view)};
}
function trendManualState(assetId){
  if(TREND_MANUAL_STATES.has(assetId))return TREND_MANUAL_STATES.get(assetId);
  const state={assetId,lines:[],undo:[],redo:[],mode:false,first:null,hover:null,selected:null,selection:[],created:[],snap:'weak',continuous:false,message:'',editorOpen:false,listOpen:false,moreOpen:false,editDraft:null,ready:false,dirty:false,saveStatus:'loading',revision:0,confirmed:null,recovery:null,conflict:false,timer:null,editVersion:0,
    view:{family:'all',scope:'all',scale:'linear',window:null,priceStep:1,snap:'weak',continuous:false}};
  try{const raw=globalThis.localStorage?.getItem(TREND_MANUAL_STORAGE_PREFIX+assetId);if(raw){if(raw.length>65536)throw new Error('기존 선 크기 제한 초과');state.lines=trendManualValidate(JSON.parse(raw),assetId).map(trendManualUpgrade);state.legacy=true;}}
  catch(error){state.message='기존 저장본 확인 불가 · 원본 보존: '+error.message;state.legacyError=true;}
  TREND_MANUAL_STATES.set(assetId,state);state.loading=trendManualLoad(state);return state;
}
function trendManualPayload(state){return {schema_version:2,asset_id:state.assetId,unit:TREND_PRIVATE_IDENTITIES[state.assetId][4],lines:trendManualCopy(state.lines),view:trendManualCopy(state.view)};}
async function trendManualLoad(state){
  try{
    const docs=await trendWorkspaceRead(),saved=docs.find(d=>d.key==='asset:'+state.assetId);
    if(saved){const checked=trendManualDocumentCheck(saved,state.assetId);state.lines=checked.lines;state.view=checked.view;state.revision=saved.revision;state.confirmed=trendManualCopy(saved);state.lines=state.lines.map(l=>l.axis==='legacy'?{...l,axis:pending.view.scale}:l);state.legacy=false;}
    state.dismissed=new Set(docs.find(d=>d.key==='dismiss:'+state.assetId)?.items||[]);
    const drafts=docs.filter(d=>d.key.startsWith('draft:'+state.assetId+':')&&!state.dismissed.has(d.key+':'+d.revision)).sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at)));
    for(const draft of drafts){try{trendManualDocumentCheck(draft,state.assetId);if(draft.edit_draft||JSON.stringify({lines:draft.lines,view:draft.view})!==JSON.stringify({lines:state.lines,view:state.view})){state.recovery=draft;break;}}catch(_){state.message='일부 임시본 형식 확인 불가 · 원본 보존';}}
    const templates=docs.find(d=>d.key==='templates');if(templates&&!TREND_TEMPLATE_PENDING)TREND_TEMPLATE_STATE=trendManualTemplatesCheck(templates);
    state.saveStatus='saved';state.ready=true;state.snap=state.view.snap;state.continuous=state.view.continuous;
    if(!TREND_REPRESENTATIVE_VIEW_OPTIONS.has(state.assetId))TREND_REPRESENTATIVE_VIEW_OPTIONS.set(state.assetId,state.view);
    if(state.onLoaded)state.onLoaded();
  }catch(error){state.ready=true;state.saveStatus='failed';state.message='브라우저 저장 실패 · 이 화면에서만 유지됩니다. 파일 백업을 이용하세요. '+error.message;}
  trendManualNotify(state);
}
function trendManualPersist(state){
  state.dirty=true;state.editVersion++;if(state.saveStatus!=='saving')state.saveStatus='dirty';clearTimeout(state.timer);
  if(!state.ready)return;
  state.timer=setTimeout(async()=>{try{const payload=trendManualPayload(state);trendManualDocumentCheck(payload,state.assetId);await trendWorkspaceWrite('draft:'+state.assetId+':'+TREND_MANUAL_TAB,{...payload,edit_draft:state.editDraft?trendManualCopy(state.editDraft):null,base_revision:state.revision,tab_id:TREND_MANUAL_TAB,updated_at:new Date().toISOString()});}catch(error){state.saveStatus='failed';state.message='임시 저장 실패 · 파일 백업을 이용하세요. '+error.message;trendManualNotify(state);}},500);
}
function trendManualNotify(state){for(const [host,view] of TREND_MANUAL_VIEWS){if(host.isConnected===false){TREND_MANUAL_VIEWS.delete(host);continue;}if(view.assetId===state.assetId)view.paint();}}
function trendManualSnapshot(state){return {lines:trendManualCopy(state.lines),view:trendManualCopy(state.view)};}
function trendManualHistory(state){state.undo.push(trendManualSnapshot(state));if(state.undo.length>100)state.undo.shift();state.redo=[];}
function trendManualSelect(state,id,add=false){const ids=new Set(add?state.selection||[]:[]);if(id){if(add&&ids.has(id))ids.delete(id);else ids.add(id);}state.selection=[...ids];state.selected=state.selection.at(-1)||null;state.editDraft=null;state.message='';trendManualNotify(state);}
function trendManualApply(state,lines,selected=null,allowLocked=false){
  if(!state.ready)throw new Error('저장본을 불러온 뒤 편집해 주세요');
  const checked=trendManualValidateV2(lines.map(l=>l.axis?l:trendManualUpgrade(l)),state.assetId);
  if(!allowLocked&&state.lines.some(l=>l.locked&&JSON.stringify(l)!==JSON.stringify(checked.find(x=>x.id===l.id))))throw new Error('잠긴 선을 먼저 잠금 해제해 주세요');
  if(JSON.stringify(checked)!==JSON.stringify(state.lines))trendManualHistory(state);
  state.lines=checked;state.legacy=checked.some(l=>l.axis==='legacy');state.selected=selected;state.selection=selected?[selected]:[];state.mode=false;state.first=null;state.second=null;state.measure=null;state.hover=null;state.message='';state.editDraft=null;
  trendManualPersist(state);trendManualNotify(state);
}
function trendManualUndo(state,redo=false){
  const from=redo?state.redo:state.undo,to=redo?state.undo:state.redo;if(!from.length)return;to.push(trendManualSnapshot(state));const next=from.pop();state.lines=next.lines;state.legacy=state.lines.some(l=>l.axis==='legacy');state.view=next.view;state.selected=null;state.selection=[];state.mode=false;state.first=null;state.hover=null;state.message='';state.editDraft=null;trendManualPersist(state);if(state.onLoaded)state.onLoaded();trendManualNotify(state);
}
function trendManualTargets(state){return state.selection?.length?state.selection:state.selected?[state.selected]:[];}
function trendManualDelete(state,all=false){
  if(state.mode){state.mode=false;state.first=null;state.second=null;state.hover=null;trendManualNotify(state);return;}
  const ids=all?state.lines.map(l=>l.id):trendManualTargets(state),last=state.created?.filter(id=>state.lines.some(l=>l.id===id)).at(-1);if(!ids.length&&last)ids.push(last);if(!ids.length)return;
  if(state.lines.some(l=>ids.includes(l.id)&&l.locked))throw new Error('잠긴 선을 먼저 잠금 해제해 주세요');trendManualApply(state,state.lines.filter(l=>!ids.includes(l.id)));
}
async function trendManualDismiss(state){if(!state.recovery)return;state.dismissed=state.dismissed||new Set();state.dismissed.add(state.recovery.key+':'+state.recovery.revision);await trendWorkspaceWrite('dismiss:'+state.assetId,{items:[...state.dismissed].slice(-100)});}
function trendManualRestore(state,payload){state.message='불러왔습니다 · 저장 전 편집본';state.saveStatus='dirty';const checked=trendManualDocumentCheck(payload,state.assetId);trendManualHistory(state);state.lines=checked.lines;state.legacy=state.lines.some(l=>l.axis==='legacy');state.view=checked.view;state.snap=state.view.snap;state.continuous=state.view.continuous;state.selection=[];state.selected=null;state.editDraft=payload.edit_draft?trendManualCopy(payload.edit_draft):null;if(state.editDraft){state.selected=state.editDraft.id;state.selection=[state.selected];state.editorOpen=true;}state.recovery=null;trendManualPersist(state);if(state.onLoaded)state.onLoaded();trendManualNotify(state);}
async function trendManualSave(state,commitForm=null){
  if(!state.ready||state.saveStatus==='saving')return false;
  try{
    if(state.mode||state.first)throw new Error('그리기를 완료하거나 Esc로 취소한 뒤 저장해 주세요');
    if(commitForm&&!commitForm())return false;
    const pending=trendManualPayload(state);pending.lines=pending.lines.map(l=>({...l,axis:l.axis==='legacy'?state.view.scale:l.axis}));trendManualDocumentCheck(pending,state.assetId);
    const version=state.editVersion;state.saveStatus='saving';state.message='';trendManualNotify(state);
    const hadTemplates=TREND_TEMPLATE_PENDING;const saved=await trendWorkspaceCommit(state.assetId,{...pending,saved_at:new Date().toISOString()},state.revision,hadTemplates?TREND_TEMPLATE_STATE:null);if(hadTemplates){TREND_TEMPLATE_STATE.revision++;TREND_TEMPLATE_PENDING=false;}
    state.revision=saved.revision;state.confirmed=trendManualCopy(saved);state.conflict=false;state.legacy=false;
    try{await trendManualDismiss(state);}catch(_){/* Confirmed save remains valid if a recovery-choice note cannot be recorded. */}
    if(version===state.editVersion){state.lines=trendManualCopy(saved.lines);state.dirty=false;state.saveStatus='saved';state.recovery=null;clearTimeout(state.timer);try{await trendWorkspaceWrite('draft:'+state.assetId+':'+TREND_MANUAL_TAB,{...saved,base_revision:saved.revision,tab_id:TREND_MANUAL_TAB,updated_at:new Date().toISOString()});}catch(_){state.message='확정본 저장됨 · 임시본 정리는 다음 저장 때 재시도합니다';}}
    else{state.saveStatus='dirty';trendManualPersist(state);}
    state.message=state.dirty?'저장 이후의 편집은 미저장입니다':'저장됨 · 다음 방문에도 같은 좌표와 계산값으로 복원됩니다';trendManualNotify(state);return true;
  }catch(error){state.saveStatus='failed';state.conflict=!!error.conflict;state.message='저장 실패 · '+error.message+' · 내 편집은 유지됩니다. 파일 백업 가능';trendManualNotify(state);return false;}
}
function trendManualSessions(detail,analysis){
  const missing=new Set((detail.gaps||[]).filter(g=>g.reason!=='unfinished_session_not_a_final_candle').map(g=>g.session));
  const map=new Map(detail.bars.map(b=>[b.session_index,{index:b.session_index,session:b.session||b.session_date,bar:b}]));
  for(const p of analysis.projection_sessions||[])if(!map.has(p.index)&&!missing.has(p.session))map.set(p.index,{index:p.index,session:p.session});
  const q=detail.intraday_quote;if(q&&!map.has(q.session_index)&&!missing.has(q.date))map.set(q.session_index,{index:q.session_index,session:q.date});
  return [...map.values()].filter(p=>trendManualDate(p.session)).sort((a,b)=>a.index-b.index);
}
function trendManualGeometry(record,detail,analysis,scale,m){
  const sessions=trendManualSessions(detail,analysis),a=sessions.find(p=>p.session===record.a.session),b=sessions.find(p=>p.session===record.b.session);if(!a||!b||a.index>=b.index)return null;
  const axis=record.axis&&record.axis!=='legacy'?record.axis:scale,transform=p=>axis==='log'?Math.log(p):p,intercept=transform(record.a.price),slope=(transform(record.b.price)-intercept)/(b.index-a.index),extension=record.extension||(record.extend?'right':'none');
  const line={manual:true,line_id:record.id,number:record.number,name:record.name,note:record.note,style:record.style||TREND_MANUAL_STYLE,locked:record.locked,axis,role:'manual_reference',kind:'manual',intercept,slope,coordinate_origin_index:a.index,display_start_index:['left','both'].includes(extension)?Math.floor(m.first):a.index,first_anchor:{index:a.index,session:a.session,price:record.a.price},second_anchor:{index:b.index,session:b.session,price:record.b.price},extend:record.extend,extension};
  if(!Number.isFinite(intercept)||!Number.isFinite(slope))return null;
  const last=['right','both'].includes(extension)?Math.ceil(m.end):Math.min(b.index,Math.ceil(m.end));
  line.points=sessions.filter(p=>p.index>=Math.max(line.display_start_index,Math.floor(m.first))&&p.index<=last).map(p=>({index:p.index,session:p.session,price:trendLinePrice(line,p.index,axis),future:p.index>(m.sourceLast??m.last)})).filter(p=>Number.isFinite(p.price)&&p.price>0);return line;
}
function trendManualPriceAt(m,y,scale){const bottom=m.ticks[0],top=m.ticks.at(-1),t=(m.H-m.B-y)/(m.H-m.T-m.B);return scale==='log'?Math.exp(Math.log(bottom)+(Math.log(top)-Math.log(bottom))*t):bottom+(top-bottom)*t;}
function trendManualPoint(m,detail,x,y,scale,snap='weak',sx=1,sy=1){
  if(!Number.isFinite(x)||!Number.isFinite(y)||x<m.L||x>m.W-m.R||y<m.T||y>m.H-m.B)return null;
  const index=Math.round(m.first+(x-m.L)/(m.W-m.L-m.R)*(m.end-m.first)),p=trendManualSessions(detail,m.analysis).find(p=>p.index===index);if(!p)return null;let price=trendManualPriceAt(m,y,scale);
  if(snap&&snap!=='off'&&p.bar){const choices=[p.bar.low,p.bar.high,p.bar.close,p.bar.open].map(price=>({price,distance:Math.hypot((m.x(index)-x)*sx,(m.y(price)-y)*sy)})).sort((a,b)=>a.distance-b.distance);if(snap==='strong'||choices[0].distance<=12)price=choices[0].price;}
  return Number.isFinite(price)&&price>0&&price<=1e15?{session:p.session,price}:null;
}
// TradingView-style tools map onto the same two-anchor record: only extension and name differ.
const TREND_TOOL_ACTIONS={draw:'ray','draw-segment':'segment','draw-extended':'extended','draw-horizontal':'horizontal','draw-hray':'hray','draw-channel':'channel',measure:'measure'};
const TREND_TOOL_SHAPES={segment:['none','추세선'],extended:['both','연장선'],horizontal:['both','수평선'],hray:['right','수평 반직선'],channel:['right','채널']};
function trendManualRecord(state,a,b,extend=true,tool=null){
  if(a.session===b.session)throw new Error('서로 다른 두 날짜를 선택해 주세요');if(state.lines.length>=TREND_MANUAL_LIMIT)throw new Error('직접선은 자산별 20개까지 그릴 수 있습니다');
  const [first,second]=a.session<b.session?[a,b]:[b,a],number=Math.max(0,...state.lines.map(l=>l.number))+1,template=TREND_TEMPLATE_STATE.items.find(t=>t.id===TREND_TEMPLATE_STATE.default_id);
  const record={...trendManualUpgrade({id:'manual-'+(globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)),number,a:{...first},b:{...second},extend}),axis:state.drawingScale||state.view?.scale||'linear',style:{...(template?.style||TREND_MANUAL_STYLE)}},shape=TREND_TOOL_SHAPES[tool];
  if(shape){record.extension=shape[0];record.extend=['right','both'].includes(shape[0]);record.name=(shape[1]+' '+number).slice(0,80);}
  return record;
}
// One click: the clicked session and its neighbour carry the same price.
function trendManualHorizontal(state,point,sessions,tool){
  const index=sessions.findIndex(row=>row.session===point.session),neighbor=index<0?null:sessions[index+1]||sessions[index-1];
  if(!neighbor)throw new Error('확인된 거래일에서 수평선을 그려 주세요');
  return trendManualRecord(state,{session:point.session,price:point.price},{session:neighbor.session,price:point.price},true,tool);
}
// Three clicks: a base line and its parallel through the third point, on the creation axis.
function trendManualChannel(state,first,second,third,sessions){
  if(state.lines.length+2>TREND_MANUAL_LIMIT)throw new Error('직접선은 자산별 20개까지 그릴 수 있습니다');
  const base=trendManualRecord(state,first,second,true,'channel'),log=base.axis==='log',T=price=>log?Math.log(price):price,I=value=>log?Math.exp(value):value,at=session=>sessions.find(row=>row.session===session)?.index;
  const ia=at(base.a.session),ib=at(base.b.session),ic=at(third.session);
  if(![ia,ib,ic].every(Number.isInteger)||ia===ib)throw new Error('확인된 거래일을 선택해 주세요');
  const offset=T(third.price)-(T(base.a.price)+(T(base.b.price)-T(base.a.price))*(ic-ia)/(ib-ia)),pa=I(T(base.a.price)+offset),pb=I(T(base.b.price)+offset);
  if(![pa,pb].every(price=>Number.isFinite(price)&&price>0&&price<=1e15))throw new Error('평행선이 유효한 가격 범위를 벗어났습니다');
  const parallel=trendManualRecord({...state,lines:[...state.lines,base]},{session:base.a.session,price:pa},{session:base.b.session,price:pb},true,'channel');
  base.name=('채널 '+base.number+' · 기준선').slice(0,80);parallel.name=('채널 '+base.number+' · 평행선').slice(0,80);parallel.style={...base.style};
  return [base,parallel];
}
function trendManualChoose(state,point,sessions=[]){
  if(!point)return false;const tool=state.tool||'ray',single=tool==='horizontal'||tool==='hray';
  if(tool==='measure'){
    if(!state.first){state.first={...point};state.measure=null;state.hover=null;state.message='';trendManualNotify(state);return false;}
    state.measure={a:{...state.first},b:{...point}};state.first=null;state.hover=null;state.mode=false;trendManualNotify(state);return true;
  }
  if(!single&&!state.first){state.first={...point};state.hover=null;state.message='';trendManualNotify(state);return false;}
  if(tool==='channel'&&!state.second){if(point.session===state.first.session){state.message='서로 다른 두 날짜를 선택해 주세요';trendManualNotify(state);return false;}state.second={...point};state.hover=null;state.message='';trendManualNotify(state);return false;}
  try{
    const continuous=state.continuous,records=single?[trendManualHorizontal(state,point,sessions,tool)]:tool==='channel'?trendManualChannel(state,state.first,state.second,point,sessions):[trendManualRecord(state,state.first,point,true,tool==='ray'?null:tool)];
    trendManualApply(state,[...state.lines,...records],records.at(-1).id);state.selection=records.map(line=>line.id);state.created.push(...state.selection);
    if(continuous&&state.lines.length<TREND_MANUAL_LIMIT){state.mode=true;state.tool=tool;}
    trendManualNotify(state);return true;
  }catch(error){state.message=error.message;trendManualNotify(state);return false;}
}
function trendManualMove(record,steps,priceDelta,sessions,scale){
  if(record.locked)throw new Error('잠긴 선을 먼저 잠금 해제해 주세요');const axis=record.axis==='legacy'?scale:record.axis;
  const move=p=>{const source=sessions.find(s=>s.session===p.session),q=source&&sessions.find(s=>s.index===source.index+steps);if(!source||!q)throw new Error('검증된 날짜 범위 밖으로 이동할 수 없습니다');const price=axis==='log'?Math.exp(Math.log(p.price)+priceDelta):p.price+priceDelta;if(!Number.isFinite(price)||price<=0||price>1e15)throw new Error('이동 후 가격이 유효하지 않습니다');return {session:q.session,price};};return {...record,a:move(record.a),b:move(record.b)};
}
function trendManualClone(state,records,imported=false){
  if(state.lines.length+records.length>TREND_MANUAL_LIMIT)throw new Error('직접선은 자산별 20개까지 그릴 수 있습니다');if(!imported&&records.some(l=>l.locked))throw new Error('잠긴 선을 먼저 잠금 해제해 주세요');
  let number=Math.max(0,...state.lines.map(l=>l.number));return records.map(l=>({...trendManualCopy(l),id:'manual-'+(globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)),number:++number,name:(l.name+' 복사').slice(0,80)}));
}
function trendManualTemplatesCheck(doc){
  if(!doc||Object.keys(doc).some(k=>!['key','revision','items','default_id'].includes(k))||!Array.isArray(doc.items)||doc.items.length>20||!Number.isSafeInteger(doc.revision)||doc.revision<0)throw new Error('템플릿 형식 확인 불가');const ids=new Set();for(const t of doc.items){if(!t||Object.keys(t).sort().join(',')!=='id,name,style'||!/^template-[a-z0-9-]{1,80}$/.test(t.id)||ids.has(t.id)||typeof t.name!=='string'||!t.name.trim()||t.name.length>80)throw new Error('템플릿 확인 불가');trendManualStyleCheck(t.style);ids.add(t.id);}if(doc.default_id!==null&&!ids.has(doc.default_id))throw new Error('기본 템플릿 확인 불가');return {revision:doc.revision,items:trendManualCopy(doc.items),default_id:doc.default_id};
}
function trendManualBackupCheck(value){
  if(!value||Object.keys(value).sort().join(',')!=='assets,contract_id,exported_at,schema_version,templates'||value.schema_version!==2||value.contract_id!=='trendlines_personal_backup_v2'||!trendIsoDate(String(value.exported_at).slice(0,10))||!Array.isArray(value.assets)||!value.assets.length||value.assets.length>TREND_VISIBLE_ASSETS.length)throw new Error('개인 선 백업 형식이 올바르지 않습니다');
  const ids=new Set();for(const doc of value.assets){trendManualDocumentCheck(doc,doc.asset_id);if(ids.has(doc.asset_id))throw new Error('자산 중복');ids.add(doc.asset_id);}trendManualTemplatesCheck(value.templates);return trendManualCopy(value);
}
async function trendManualExport(state,saveFirst=false,working=false){
  if(saveFirst&&!await trendManualSave(state,state.commitForm))return;
  let docs=[];try{docs=await trendWorkspaceRead();}catch(_){if(!working)throw new Error('확정본 읽기 실패 · 현재 편집 백업을 선택해 주세요');}
  const assets=TREND_VISIBLE_ASSETS.map(([id])=>{const active=TREND_MANUAL_STATES.get(id),doc=docs.find(d=>d.key==='asset:'+id);let legacy=[];if(!doc){const raw=globalThis.localStorage?.getItem(TREND_MANUAL_STORAGE_PREFIX+id);if(raw){if(raw.length>65536)throw new Error('기존 선 크기 제한 초과: '+id);legacy=trendManualValidate(JSON.parse(raw),id).map(trendManualUpgrade);}}return working&&active?trendManualPayload(active):doc?{schema_version:2,asset_id:id,unit:doc.unit,lines:doc.lines,view:doc.view}:{schema_version:2,asset_id:id,unit:TREND_PRIVATE_IDENTITIES[id][4],lines:legacy,view:{family:'all',scope:'all',scale:'linear',window:null,priceStep:1,snap:'weak',continuous:false}};});
  const backup=trendManualBackupCheck({schema_version:2,contract_id:'trendlines_personal_backup_v2',exported_at:new Date().toISOString(),assets,templates:working?TREND_TEMPLATE_STATE:docs.find(d=>d.key==='templates')||{revision:0,items:[],default_id:null}}),blob=new Blob([JSON.stringify(backup,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='jins-personal-trendlines-'+new Date().toISOString().slice(0,10)+(working?'-working':'')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function trendManualSvg(m,state,preview=null){
  const lines=preview?m.manualLines.map(l=>l.line_id===preview.line_id?preview:l):m.manualLines,path=points=>points.map(p=>m.x(p.index).toFixed(3)+','+m.y(p.price).toFixed(3)).join(' ');
  let html=lines.map(line=>{const selected=trendManualTargets(state).includes(line.line_id)||state.selected===line.line_id,style=line.style||TREND_MANUAL_STYLE,actual=line.points.filter(p=>!p.future),future=line.points.filter(p=>p.future),anchors=selected?[line.first_anchor,line.second_anchor]:[],dash=style.dash==='dash'?'7 5':style.dash==='dot'?'1 4':'',marker='manual-arrow-'+line.line_id;
    const attrs=' fill="none" stroke="'+style.color+'" stroke-opacity="'+style.opacity+'" stroke-width="'+style.width+'" vector-effect="non-scaling-stroke"';
    let html='<g data-trend-manual-line="'+esc(line.line_id)+'"'+(selected?' class="is-selected"':'')+'><defs><marker id="'+marker+'" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="'+style.color+'"/></marker></defs><polyline data-trend-manual-path points="'+path(actual)+'"'+attrs+(dash?' stroke-dasharray="'+dash+'"':'')+(['start','both'].includes(style.arrow)?' marker-start="url(#'+marker+')"':'')+(!future.length&&['end','both'].includes(style.arrow)?' marker-end="url(#'+marker+')"':'')+'/>'+(future.length?'<polyline data-trend-manual-projection points="'+path([actual.at(-1),...future].filter(Boolean))+'"'+attrs+' stroke-dasharray="3 5"'+(['end','both'].includes(style.arrow)?' marker-end="url(#'+marker+')"':'')+'/>':'');
    html+=anchors.map((a,i)=>({a,i})).filter(({a})=>a.index>=m.first&&a.index<=m.end).map(({a,i})=>'<circle data-trend-manual-handle="'+i+'" cx="'+m.x(a.index)+'" cy="'+m.y(a.price)+'" r="'+(line.locked?3:4)+'" fill="'+(line.locked?style.color:'#fff')+'" stroke="'+style.color+'" stroke-width="1.4" vector-effect="non-scaling-stroke"><title>'+esc(line.name||'내 빗각선 '+line.number)+' · '+a.session+' · '+a.price+'</title></circle>').join('');
    if(style.labels){for(const a of [line.first_anchor,line.second_anchor])if(a.index>=m.first&&a.index<=m.end)html+='<text x="'+(m.x(a.index)+7)+'" y="'+(m.y(a.price)-8)+'" fill="'+style.color+'">'+esc(Number(a.price).toLocaleString('ko-KR',{maximumFractionDigits:4}))+'</text>';}
    return html+'</g>';
  }).join('');
  const sessions=trendManualSessions(m.manualDetail,m.analysis),point=p=>{const row=sessions.find(s=>s.session===p?.session);return row?{index:row.index,price:p.price}:null;},first=point(state.first),second=point(state.second),hover=point(state.hover),tool=state.tool||'ray';
  const dashed=(a,b)=>'<line x1="'+m.x(a.index)+'" y1="'+m.y(a.price)+'" x2="'+m.x(b.index)+'" y2="'+m.y(b.price)+'" stroke="#7056a3" stroke-width="1.1" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>',dot=p=>'<circle cx="'+m.x(p.index)+'" cy="'+m.y(p.price)+'" r="4" fill="#7056a3"/>';
  if(state.mode&&(tool==='horizontal'||tool==='hray')&&hover)html+='<line x1="'+(tool==='hray'?m.x(hover.index):m.L)+'" y1="'+m.y(hover.price)+'" x2="'+(m.W-m.R)+'" y2="'+m.y(hover.price)+'" stroke="#7056a3" stroke-width="1.1" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>';
  if(state.mode&&tool!=='measure'&&first){
    html+=dot(first);
    if(second){html+=dot(second)+dashed(first,second);if(hover&&second.index!==first.index){const log=(state.drawingScale||m.scale)==='log',T=p=>log?Math.log(p):p,I=v=>log?Math.exp(v):v,offset=T(hover.price)-(T(first.price)+(T(second.price)-T(first.price))*(hover.index-first.index)/(second.index-first.index)),a={index:first.index,price:I(T(first.price)+offset)},b={index:second.index,price:I(T(second.price)+offset)};if([a.price,b.price].every(price=>Number.isFinite(price)&&price>0))html+=dashed(a,b);}}
    else if(hover&&hover.index!==first.index)html+=dashed(first,hover);
  }
  const measure=state.measure?{a:point(state.measure.a),b:point(state.measure.b),from:state.measure.a.session,to:state.measure.b.session}:state.mode&&tool==='measure'&&first&&hover?{a:first,b:hover,from:state.first.session,to:state.hover.session}:null;
  if(measure?.a&&measure.b&&m.x(measure.b.index)>=m.L&&m.x(measure.b.index)<=m.W-m.R){
    const {a,b}=measure,up=b.price>=a.price,color=up?'#bb4c1c':'#34738d',x1=m.x(a.index),x2=m.x(b.index),y1=m.y(a.price),y2=m.y(b.price),delta=b.price-a.price,percent=(b.price/a.price-1)*100,days=Math.round((Date.parse(measure.to)-Date.parse(measure.from))/864e5);
    const whole=m.manualDetail?.asset?.unit==='KRW_per_share',text=[(delta>0?'+':'')+Number(delta).toLocaleString('ko-KR',{maximumFractionDigits:whole?0:2})+' ('+(percent>0?'+':'')+percent.toFixed(2)+'%)',(b.index-a.index)+'봉 · '+days+'일'],bx=Math.max(m.L+2,Math.min(m.W-m.R-152,x2+8)),by=Math.max(m.T+2,Math.min(m.H-m.B-40,up?y2-44:y2+6));
    html+='<g data-trend-measure pointer-events="none"><rect x="'+Math.min(x1,x2)+'" y="'+Math.min(y1,y2)+'" width="'+Math.abs(x2-x1)+'" height="'+Math.abs(y2-y1)+'" fill="'+color+'" opacity=".12"/><line x1="'+x1+'" y1="'+y1+'" x2="'+x2+'" y2="'+y2+'" stroke="'+color+'" stroke-width="1.2" vector-effect="non-scaling-stroke"/><rect x="'+bx+'" y="'+by+'" width="150" height="38" rx="3" fill="'+color+'"/>'+text.map((line,i)=>'<text x="'+(bx+8)+'" y="'+(by+15+i*15)+'" style="fill:#fff;font-weight:'+(i?500:700)+'">'+esc(line)+'</text>').join('')+'</g>';
  }
  if(state.mode&&hover)html+='<circle cx="'+m.x(hover.index)+'" cy="'+m.y(hover.price)+'" r="3" fill="#fff" stroke="#7056a3"/>';return html;
}
function trendManualStats(record,geometry,m,asset){
  if(!geometry||!record.style.stats)return '';const a=geometry.first_anchor,b=geometry.second_anchor,angle=Math.atan2((m.y(a.price)-m.y(b.price))*(m.screenSY||1),(m.x(b.index)-m.x(a.index))*(m.screenSX||1))*180/Math.PI;
  return (record.name||'내 선')+' · Δ '+trendPrice(b.price-a.price,asset)+' ('+((b.price/a.price-1)*100).toFixed(2)+'%) · '+(b.index-a.index)+'봉 · '+Math.round((Date.parse(b.session)-Date.parse(a.session))/86400000)+'일 · 화면 각도 '+angle.toFixed(1)+'°'+(record.note?' · '+record.note:'');
}
function trendManualEditorMarkup(){
  const button=(action,label,cls='')=>'<button type="button" class="'+cls+'" data-trend-manual-action="'+action+'">'+label+'</button>';
  return '<details class="trend-manual-editor" data-trend-manual-editor hidden><summary>선 설정 · 기준점 조정</summary><form data-trend-manual-form><label>이름<input name="name" maxlength="80"></label><label class="trend-span2">메모<input name="note" maxlength="500"></label><label>첫 점 날짜<input type="date" name="a_session" required></label><label>첫 점 가격<input type="number" step="any" min="0.00000001" name="a_price" required></label><label>둘째 점 날짜<input type="date" name="b_session" required></label><label>둘째 점 가격<input type="number" step="any" min="0.00000001" name="b_price" required></label><label>연장<select name="extension"><option value="none">없음</option><option value="left">왼쪽</option><option value="right">오른쪽</option><option value="both">양쪽</option></select></label><label>색<input type="color" name="color"></label><label>불투명도<input type="number" name="opacity" min="0.1" max="1" step="0.1"></label><label>두께(px)<input type="number" name="width" min="0.5" max="6" step="0.1"></label><label>선 모양<select name="dash"><option value="solid">실선</option><option value="dash">파선</option><option value="dot">점선</option></select></label><label>끝 화살표<select name="arrow"><option value="none">없음</option><option value="start">첫 점</option><option value="end">둘째 점</option><option value="both">양쪽</option></select></label><label><input type="checkbox" name="labels">가격 라벨</label><label><input type="checkbox" name="stats">선택 시 통계·메모</label><label>계산 기준<output data-trend-equation-axis></output></label><button type="submit">설정 적용</button></form><div class="trend-template-tools"><select data-trend-template aria-label="스타일 템플릿"></select>'+button('template-save','스타일 템플릿 저장')+button('template-apply','적용')+button('template-rename','이름 변경')+button('template-default','기본 지정')+button('template-delete','템플릿 삭제')+'<input data-trend-template-name maxlength="80" aria-label="템플릿 이름" placeholder="템플릿 이름"></div></details>';
}
let TREND_MANUAL_KEY_BOUND=false,TREND_MANUAL_ACTIVE_HOST=null;
function trendManualBindKeys(){if(!TREND_MANUAL_KEY_BOUND&&globalThis.document?.addEventListener){document.addEventListener('keydown',trendManualKeyboard,true);TREND_MANUAL_KEY_BOUND=true;}}
function trendManualKeyboard(event){
  const letter=value=>String(event.key||'').toLowerCase()===value||event.code==='Key'+value.toUpperCase();
  if(!TREND_ZOOM&&event.altKey&&!event.ctrlKey&&!event.metaKey&&!event.target?.closest?.('input,textarea,select,[contenteditable="true"]')){const action=letter('t')?'draw':letter('h')?'draw-horizontal':letter('j')?'draw-hray':null,opener=action&&globalThis.document?.querySelector?.('[data-trend-preview]')?._trendOpenWorkspace;if(opener){event.preventDefault();event.stopImmediatePropagation();opener({action});return;}}
  const host=TREND_ZOOM?.layer?.querySelector('[data-trend-zoom-chart]')||TREND_MANUAL_ACTIVE_HOST;if(!host?.isConnected||!host._trendManual)return;
  const c=host._trendManual,state=c.state,target=event.target,input=target?.closest?.('input,textarea,select,[contenteditable="true"]'),mod=event.ctrlKey||event.metaKey;
  if(mod&&event.key.toLowerCase()==='s'){event.preventDefault();event.stopImmediatePropagation();c.action('save');return;}
  if(input)return;
  const stop=()=>{event.preventDefault();event.stopImmediatePropagation();};
  if(event.altKey&&mod&&letter('h')){stop();c.action('hide-all');return;}
  if(event.altKey&&!mod){const action=letter('t')?'draw':letter('h')?'draw-horizontal':letter('j')?'draw-hray':null;if(action){stop();c.action(action);return;}}
  if(mod&&event.key.toLowerCase()==='z'){stop();c.action(event.shiftKey?'redo':'undo');return;}
  if(mod&&event.key.toLowerCase()==='y'){stop();c.action('redo');return;}
  if(mod&&event.key.toLowerCase()==='c'&&trendManualTargets(state).length){stop();TREND_MANUAL_CLIPBOARD={assetId:state.assetId,lines:trendManualCopy(state.lines.filter(l=>trendManualTargets(state).includes(l.id)))};return;}
  if(mod&&event.key.toLowerCase()==='v'&&TREND_MANUAL_CLIPBOARD){stop();if(TREND_MANUAL_CLIPBOARD.assetId!==state.assetId){state.message='같은 자산의 개인 선만 붙여넣을 수 있습니다';trendManualNotify(state);}else c.clone(TREND_MANUAL_CLIPBOARD.lines);return;}
  if(['Delete','Backspace'].includes(event.key)){stop();c.action('delete');return;}
  if(event.key==='Escape'&&(state.mode||state.selected||state.measure||c.busy())){stop();c.cancel();return;}
  if(!state.mode&&state.selected&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){stop();c.nudge(event.key);}
}
function bindTrendManual(host,detail,m,asset,scale){
  const svg=host.querySelector('svg[data-trend-plot]')||host.querySelector('svg'),layer=host.querySelector('[data-trend-manual-layer]');if(!svg?.ownerDocument?.createElementNS||!layer)return;
  const state=m.manualState,select=host.querySelector('[data-trend-manual-select]'),status=host.querySelector('[data-trend-manual-status]'),editor=host.querySelector('[data-trend-manual-editor]'),form=host.querySelector('[data-trend-manual-form]');
  let gesture=null,cursor={session:m.bars.at(-1).session||m.bars.at(-1).session_date,price:m.bars.at(-1).close};
  const element=s=>host.querySelector(s),fields=['name','note','a_session','a_price','b_session','b_price','extension','color','opacity','width','dash','arrow','labels','stats'];
  const error=err=>{state.message=err.message||String(err);trendManualNotify(state);};
  const selectedLines=()=>state.lines.filter(l=>trendManualTargets(state).includes(l.id));
  const refresh=()=>{
    const matrix=svg.getScreenCTM?.();if(matrix){m.screenSX=Math.hypot(matrix.a,matrix.b);m.screenSY=Math.hypot(matrix.c,matrix.d);}
    m.manualLines=state.lines.filter(l=>!l.hidden).map(l=>trendManualGeometry(l,detail,m.analysis,scale,m)).filter(Boolean);layer.innerHTML=trendManualSvg(m,state);const tags=host.querySelector('[data-trend-manual-tags]');if(tags)tags.innerHTML=trendManualTags(m,state,asset);svg.classList.toggle('trend-manual-drawing',state.mode);
    select.innerHTML='<option value="">내 빗각선 '+state.lines.length+'개</option>'+state.lines.map(l=>'<option value="'+esc(l.id)+'">'+esc(l.name)+'</option>').join('');select.value=state.selected||'';select.disabled=!state.lines.length;
    host.querySelectorAll('[data-trend-manual-action]').forEach(button=>{const a=button.dataset.trendManualAction;button.disabled=!state.ready||a==='save'&&state.saveStatus==='saving'||a==='undo'&&!state.undo.length||a==='redo'&&!state.redo.length||a==='clear'&&!state.lines.length;const tool=TREND_TOOL_ACTIONS[a];if(tool){button.setAttribute('aria-pressed',String(!!state.mode&&(state.tool||'ray')===tool));if(a==='draw'&&!button.classList?.contains('trend-ws-tool'))button.textContent=state.mode?(state.first?'● 둘째 점 선택 · 취소':'● 첫 점 선택 · 취소'):'＋ 빗각 그리기';}else if(a==='cursor')button.setAttribute('aria-pressed',String(!state.mode));else if(a==='snap-cycle'){button.dataset.level=state.snap;button.setAttribute('aria-pressed',String(state.snap!=='off'));}else if(a==='continuous-toggle')button.setAttribute('aria-pressed',String(!!state.continuous));else if(a==='hide-all'||a==='lock-all'){const key=a==='hide-all'?'hidden':'locked';button.setAttribute('aria-pressed',String(state.lines.length>0&&state.lines.every(l=>l[key])));}});
    const chosen=state.lines.find(l=>l.id===state.selected),geometry=chosen&&trendManualGeometry(chosen,detail,m.analysis,scale,m),missing=state.lines.filter(l=>!trendManualGeometry(l,detail,m.analysis,scale,m)).length,price=geometry?trendLinePrice(geometry,m.sourceLast??m.last,scale):null;
    editor.hidden=!chosen;editor.open=!!state.editorOpen;
    if(chosen&&!form.contains(document.activeElement)){
      const draft=state.editDraft?.id===chosen.id?state.editDraft:null,values=draft||{name:chosen.name,note:chosen.note,a_session:chosen.a.session,a_price:chosen.a.price,b_session:chosen.b.session,b_price:chosen.b.price,extension:chosen.extension,...chosen.style};
      for(const name of fields){const field=form.elements[name];if(!field)continue;if(['labels','stats'].includes(name))field.checked=!!values[name];else field.value=values[name];field.disabled=!!chosen.locked;}
    }
    if(element('[data-trend-equation-axis]'))element('[data-trend-equation-axis]').textContent=chosen?.axis==='legacy'?'첫 저장 시 현재 축 고정':chosen?.axis==='log'?'로그 (고정)':'선형 (고정)';
    const selection=element('[data-trend-selection]');if(selection)selection.hidden=!state.selection.length;
    if(element('[data-trend-save-state]'))element('[data-trend-save-state]').textContent=({loading:'불러오는 중',saved:state.legacy?'기존 v1 · 저장 필요':'저장됨',dirty:'● 미저장',saving:'저장 중…',failed:'저장 실패'})[state.saveStatus];
    if(element('[data-trend-save-state]'))element('[data-trend-save-state]').dataset.status=state.saveStatus;
    if(element('[data-trend-more]'))element('[data-trend-more]').hidden=!state.moreOpen;
    if(element('[data-trend-snap]'))element('[data-trend-snap]').value=state.snap;
    if(element('[data-trend-continuous]'))element('[data-trend-continuous]').checked=state.continuous;
    if(element('[data-trend-price-step]')&&document.activeElement!==element('[data-trend-price-step]'))element('[data-trend-price-step]').value=state.view.priceStep;
    const list=element('[data-trend-manual-list]');if(list){list.hidden=!state.listOpen;list.innerHTML=state.lines.length?state.lines.map(l=>'<div class="trend-object-row"><button type="button" data-trend-object="'+esc(l.id)+'" aria-pressed="'+trendManualTargets(state).includes(l.id)+'"><i style="background:'+l.style.color+'"></i>'+esc(l.name||'내 선 '+l.number)+(l.locked?' 🔒':'')+(l.hidden?' · 숨김':'')+(!trendManualGeometry(l,detail,m.analysis,scale,m)?' · 기준점 미확인':'')+'</button><button type="button" data-trend-object-hide="'+esc(l.id)+'" aria-label="'+esc(l.name)+' 숨김 전환">'+(l.hidden?'표시':'숨김')+'</button><button type="button" data-trend-object-lock="'+esc(l.id)+'" aria-label="'+esc(l.name)+' 잠금 전환">'+(l.locked?'해제':'잠금')+'</button></div>').join(''):'<p>직접 그린 선이 없습니다.</p>';}
    const templates=element('[data-trend-template]');if(templates){const old=templates.value;templates.innerHTML='<option value="">스타일 템플릿</option>'+TREND_TEMPLATE_STATE.items.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.name)+(t.id===TREND_TEMPLATE_STATE.default_id?' ★':'')+'</option>').join('');templates.value=old;}
    const recovery=element('[data-trend-recovery]');if(recovery){recovery.hidden=!state.recovery&&!state.conflict&&!state.legacy;recovery.innerHTML=state.conflict?'<p>다른 탭에서 새 저장본이 생겼습니다. 내 편집은 유지됩니다.</p><button type="button" data-trend-recover="latest">최신본 불러오기</button><button type="button" data-trend-recover="mine">내 편집 복구 후 저장</button><button type="button" data-trend-manual-action="working-export">내 편집 백업</button>':state.recovery?'<p>미저장 임시본이 있습니다. 자동으로 확정본을 덮어쓰지 않습니다.</p><button type="button" data-trend-recover="restore">임시본 복구</button><button type="button" data-trend-recover="saved">저장본 사용</button>':state.legacy?'<p>기존 선은 생성 축 기록이 없습니다. 첫 명시적 저장 시 현재 '+(scale==='log'?'로그':'선형')+' 계산 축으로 고정합니다. v1 원본은 보존합니다.</p>':'';}
    const count=element('[data-trend-ws-count]');if(count)count.textContent=state.lines.length+'/'+TREND_MANUAL_LIMIT;
    if(element('[data-trend-manual-statistics]'))element('[data-trend-manual-statistics]').textContent=chosen?trendManualStats(chosen,geometry,m,asset):'';
    const tool=state.tool||'ray',hint=tool==='measure'?(state.first?'측정 끝점 선택 · Esc 취소':'측정 시작점 · 드래그 또는 두 번 클릭'):tool==='horizontal'||tool==='hray'?'가격을 눌러 '+(tool==='hray'?'수평 반직선':'수평선')+' · Esc 취소':tool==='channel'&&state.second?'평행선 위치 선택 · Esc 취소':null;
    status.textContent=state.message||(state.mode?hint||(state.first?'둘째 점 선택 · Enter · Esc 취소':'첫 점 선택 · Enter · Esc 취소'):chosen?(chosen.name||'내 선 '+chosen.number)+(Number.isFinite(price)&&price>0?' · 최근 확정일 선 가격 '+trendPrice(price,asset):'')+(chosen.locked?' · 잠김':''):'두 점을 찍어 빗각을 그린 뒤 저장하세요')+(missing?' · '+missing+'개 기준점 자료 확인 중':'');
  };
  for(const [other] of TREND_MANUAL_VIEWS)if(other.isConnected===false)TREND_MANUAL_VIEWS.delete(other);TREND_MANUAL_VIEWS.set(host,{assetId:state.assetId,paint:refresh});
  trendManualBindKeys();TREND_MANUAL_ACTIVE_HOST=host;
  host.onfocusin=()=>{TREND_MANUAL_ACTIVE_HOST=host;};editor._trendToggle=()=>{state.editorOpen=editor.open;};if(!editor._trendToggleBound){editor._trendToggleBound=true;editor.addEventListener?.('toggle',()=>editor._trendToggle());}
  const remember=()=>{if(!state.selected)return;const draft={id:state.selected};for(const name of fields){const field=form.elements[name];if(field)draft[name]=['labels','stats'].includes(name)?field.checked:field.value;}state.editDraft=draft;state.message='입력 변경 · 적용 또는 저장해 주세요';trendManualPersist(state);trendManualNotify(state);};form._trendRemember=remember;if(!form._trendRememberBound){form._trendRememberBound=true;form.addEventListener?.('input',()=>form._trendRemember());form.addEventListener?.('change',()=>form._trendRemember());}
  const commitForm=()=>{
    if(!state.editDraft)return true;const line=state.lines.find(l=>l.id===state.editDraft.id);if(!line)return true;
    try{
      if(line.locked)throw new Error('잠긴 선을 먼저 잠금 해제해 주세요');const d=state.editDraft,anchors=['a','b'].map(k=>({session:d[k+'_session'],price:Number(d[k+'_price'])})).sort((a,b)=>a.session.localeCompare(b.session));
      const changed={...line,a:anchors[0],b:anchors[1],name:d.name,note:d.note,extension:d.extension,extend:['right','both'].includes(d.extension),style:{color:d.color,opacity:Number(d.opacity),width:Number(d.width),dash:d.dash,arrow:d.arrow,labels:d.labels,stats:d.stats}};
      trendManualValidateV2([changed],state.assetId);if(!trendManualGeometry(changed,detail,m.analysis,scale,m))throw new Error('확인된 거래일 또는 제공된 연장 날짜를 선택해 주세요');trendManualApply(state,state.lines.map(l=>l.id===line.id?changed:l),line.id);return true;
    }catch(err){error(err);return false;}
  };state.commitForm=commitForm;
  const point=event=>{const bounds=svg.getBoundingClientRect(),sx=bounds.width/m.W,sy=bounds.height/m.H;let x=(event.clientX-bounds.left)/sx,y=(event.clientY-bounds.top)/sy;if(svg.getScreenCTM&&globalThis.DOMPoint){const matrix=svg.getScreenCTM();if(matrix){const p=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());x=p.x;y=p.y;}}let anchor=trendManualPoint(m,detail,x,y,scale,state.snap,sx,sy);if(anchor&&event.shiftKey&&state.mode&&state.first&&!['measure','horizontal','hray'].includes(state.tool||'ray')&&!(state.tool==='channel'&&state.second))anchor={...anchor,price:state.first.price};return {x,y,sx,sy,anchor};};
  const consume=event=>{event.preventDefault();event.stopPropagation();},cancel=()=>{gesture=null;state.mode=false;state.first=null;state.second=null;state.measure=null;state.hover=null;state.selected=null;state.selection=[];state.message='';trendManualNotify(state);};
  const clone=records=>{try{const lines=trendManualClone(state,records);trendManualApply(state,[...state.lines,...lines],lines.at(-1)?.id);state.selection=lines.map(l=>l.id);state.created.push(...state.selection);trendManualNotify(state);}catch(err){error(err);}};
  const change=(fn,unlock=false,all=false)=>{const ids=all?state.lines.map(l=>l.id):trendManualTargets(state);if(!ids.length)return;if(!unlock&&state.lines.some(l=>ids.includes(l.id)&&l.locked))throw new Error('잠긴 선을 먼저 잠금 해제해 주세요');const selected=state.selected;trendManualApply(state,state.lines.map(l=>ids.includes(l.id)?fn(l):l),selected,unlock);state.selection=ids;trendManualNotify(state);};
  const action=async(name,value=null)=>{try{
    if(!state.ready)throw new Error('저장본을 불러온 뒤 편집해 주세요');
    if(TREND_TOOL_ACTIONS[name]){const tool=TREND_TOOL_ACTIONS[name];if(state.mode&&(state.tool||'ray')===tool)cancel();else{if(tool!=='measure'&&state.lines.length>=TREND_MANUAL_LIMIT-(tool==='channel'?1:0))throw new Error('직접선은 자산별 20개까지 그릴 수 있습니다');state.mode=true;state.tool=tool;state.drawingScale=scale;state.first=null;state.second=null;state.measure=null;state.hover=null;state.selected=null;state.selection=[];state.message='';trendManualNotify(state);svg.focus?.();}}
    else if(name==='cursor')cancel();
    else if(name==='set-color'&&/^#[0-9a-fA-F]{6}$/.test(value||''))change(l=>({...l,style:{...l.style,color:value}}));
    else if(name==='set-width'&&Number(value)>=.5&&Number(value)<=6)change(l=>({...l,style:{...l.style,width:Number(value)}}));
    else if(name==='set-dash'&&['solid','dash','dot'].includes(value))change(l=>({...l,style:{...l.style,dash:value}}));
    else if(name==='set-extension'&&['none','left','right','both'].includes(value))change(l=>({...l,extension:value,extend:['right','both'].includes(value)}));
    else if(name==='snap-cycle'){state.snap=({off:'weak',weak:'strong',strong:'off'})[state.snap]||'weak';state.view.snap=state.snap;trendManualPersist(state);refresh();}
    else if(name==='continuous-toggle'){state.continuous=!state.continuous;state.view.continuous=state.continuous;trendManualPersist(state);refresh();}
    else if(name==='settings'){state.editorOpen=true;host._trendWorkspace?.openPanel();refresh();}
    else if(name==='save')await trendManualSave(state,commitForm);
    else if(name==='undo'||name==='redo')trendManualUndo(state,name==='redo');
    else if(name==='delete'||name==='clear')trendManualDelete(state,name==='clear');
    else if(name==='list'||name==='more'){state[name==='list'?'listOpen':'moreOpen']=!state[name==='list'?'listOpen':'moreOpen'];refresh();}
    else if(name==='clone')clone(selectedLines());
    else if(name==='hide'||name==='hide-all'){const all=name==='hide-all',records=all?state.lines:selectedLines(),hidden=!records.every(l=>l.hidden);change(l=>({...l,hidden}),false,all);}
    else if(name==='lock'||name==='lock-all'){const all=name==='lock-all',records=all?state.lines:selectedLines(),locked=!records.every(l=>l.locked);change(l=>({...l,locked}),true,all);}
    else if(name==='front'||name==='back'){const records=selectedLines();if(records.some(l=>l.locked))throw new Error('잠긴 선을 먼저 잠금 해제해 주세요');const rest=state.lines.filter(l=>!trendManualTargets(state).includes(l.id));trendManualApply(state,name==='front'?[...rest,...records]:[...records,...rest],state.selected);state.selection=records.map(l=>l.id);refresh();}
    else if(name==='revert'){if(state.confirmed)trendManualRestore(state,state.confirmed);else throw new Error('확정 저장본이 없습니다');}
    else if(['export','save-export','working-export'].includes(name))await trendManualExport(state,name==='save-export',name==='working-export');
    else if(name.startsWith('template-')){
      const id=element('[data-trend-template]').value,chosen=state.lines.find(l=>l.id===state.selected),template=TREND_TEMPLATE_STATE.items.find(t=>t.id===id),text=element('[data-trend-template-name]').value.trim();
      if(name==='template-apply'){if(!template)throw new Error('템플릿을 선택해 주세요');change(l=>({...l,style:{...template.style}}));return;}
      const next=trendManualCopy(TREND_TEMPLATE_STATE);
      if(name==='template-save'){if(!chosen||!commitForm())return;if(!text)throw new Error('템플릿 이름을 입력해 주세요');if(next.items.length>=20)throw new Error('템플릿은 20개까지 저장할 수 있습니다');next.items.push({id:'template-'+(globalThis.crypto?.randomUUID?.()||Date.now().toString(36)),name:text,style:{...state.lines.find(l=>l.id===state.selected).style}});}
      else{if(!template)throw new Error('템플릿을 선택해 주세요');if(name==='template-rename'){if(!text)throw new Error('새 이름을 입력해 주세요');next.items=next.items.map(t=>t.id===id?{...t,name:text}:t);}if(name==='template-default')next.default_id=next.default_id===id?null:id;if(name==='template-delete'){next.items=next.items.filter(t=>t.id!==id);if(next.default_id===id)next.default_id=null;}}
      trendManualTemplatesCheck(next);const saved=await trendWorkspaceWrite('templates',next,TREND_TEMPLATE_STATE.revision);TREND_TEMPLATE_STATE=trendManualTemplatesCheck(saved);TREND_TEMPLATE_PENDING=false;state.message='스타일 템플릿 저장됨';trendManualNotify(state);
    }
  }catch(err){error(err);}};
  host._trendManual={state,action,cancel,clone,busy:()=>state.mode||!!gesture,select:id=>trendManualSelect(state,id),nudge:key=>{try{const rows=trendManualSessions(detail,m.analysis),steps=key==='ArrowLeft'?-1:key==='ArrowRight'?1:0,delta=key==='ArrowUp'?state.view.priceStep:key==='ArrowDown'?-state.view.priceStep:0,ids=trendManualTargets(state);const moved=state.lines.map(l=>ids.includes(l.id)?trendManualMove(l,steps,((l.axis==='log'||l.axis==='legacy'&&scale==='log')?Math.log((l.a.price+delta)/l.a.price):delta),rows,scale):l);trendManualApply(state,moved,state.selected);state.selection=ids;refresh();}catch(err){error(err);}}};
  // One delegated listener survives object-list refreshes; automatic lines have no command IDs.
  host.onclick=event=>{const button=event.target.closest?.('[data-trend-manual-action],[data-trend-object],[data-trend-object-hide],[data-trend-object-lock],[data-trend-recover],[data-trend-import-confirm],[data-trend-import-cancel]');if(!button)return;TREND_MANUAL_ACTIVE_HOST=host;
    if(button.dataset.trendManualAction){action(button.dataset.trendManualAction,button.dataset.trendManualValue);return;}
    if(button.dataset.trendObject){if(state.editDraft&&!commitForm())return;trendManualSelect(state,button.dataset.trendObject,event.ctrlKey||event.metaKey);return;}
    if(button.dataset.trendObjectHide||button.dataset.trendObjectLock){if(state.editDraft&&!commitForm())return;trendManualSelect(state,button.dataset.trendObjectHide||button.dataset.trendObjectLock);action(button.dataset.trendObjectHide?'hide':'lock');return;}
    if(button.dataset.trendImportCancel!==undefined){state.importPreview=null;element('[data-trend-import-preview]').hidden=true;return;}
    if(button.dataset.trendImportConfirm!==undefined)(async()=>{try{
      const replace=element('[data-trend-import-replace]').checked,all=element('[data-trend-import-all]').checked,withTemplates=element('[data-trend-import-templates]').checked,backup=state.importPreview,targets=all?backup.assets:backup.assets.filter(d=>d.asset_id===state.assetId),prepared=[];
      for(const doc of targets){const target=trendManualState(doc.asset_id);await target.loading;const incoming=replace?doc.lines:trendManualClone(target,doc.lines,true),lines=replace?incoming:[...target.lines,...incoming];trendManualValidateV2(lines,target.assetId);if(target.lines.some(l=>l.locked&&JSON.stringify(l)!==JSON.stringify(lines.find(n=>n.id===l.id))))throw new Error('잠긴 선이 있는 자산을 먼저 잠금 해제해 주세요: '+target.assetId);prepared.push({target,lines});}
      let templates=null;if(withTemplates){templates=trendManualCopy(TREND_TEMPLATE_STATE);for(const t of backup.templates.items){let added=templates.items.find(i=>JSON.stringify(i)===JSON.stringify(t));if(!added){added={...t,id:'template-'+(globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2))};templates.items.push(added);}if(!templates.default_id&&t.id===backup.templates.default_id)templates.default_id=added.id;}trendManualTemplatesCheck(templates);}
      for(const {target,lines} of prepared)trendManualApply(target,lines);if(templates){TREND_TEMPLATE_STATE=templates;TREND_TEMPLATE_PENDING=true;}
      state.importPreview=null;element('[data-trend-import-preview]').hidden=true;state.message=prepared.length+'개 자산 가져오기 완료 · 미저장. 자산별 저장 버튼으로 확정하세요.'+(templates?' 템플릿은 다음 저장 때 확정됩니다.':'');refresh();
    }catch(err){error(err);}})();
    if(button.dataset.trendRecover)(async()=>{try{const choice=button.dataset.trendRecover;if(choice==='restore'){await trendManualDismiss(state);trendManualRestore(state,state.recovery);return;}if(choice==='saved'){await trendManualDismiss(state);state.recovery=null;await trendWorkspaceWrite('draft:'+state.assetId+':'+TREND_MANUAL_TAB,{...trendManualPayload(state),base_revision:state.revision,tab_id:TREND_MANUAL_TAB,updated_at:new Date().toISOString()});refresh();return;}const docs=await trendWorkspaceRead(),latest=docs.find(d=>d.key==='asset:'+state.assetId);if(!latest)throw new Error('최신본 확인 불가');trendManualDocumentCheck(latest,state.assetId);state.revision=latest.revision;state.confirmed=trendManualCopy(latest);const latestTemplates=docs.find(d=>d.key==='templates');if(choice==='latest'&&latestTemplates){TREND_TEMPLATE_STATE=trendManualTemplatesCheck(latestTemplates);TREND_TEMPLATE_PENDING=false;}else if(latestTemplates)TREND_TEMPLATE_STATE.revision=trendManualTemplatesCheck(latestTemplates).revision;state.conflict=false;if(choice==='latest')trendManualRestore(state,latest);else await trendManualSave(state,commitForm);}catch(err){error(err);}})();
  };
  // Keep direct bindings for keyboards/test hosts; real clicks use delegation exactly once.
  host.querySelectorAll('[data-trend-manual-action]').forEach(button=>button.onclick=event=>{event?.stopPropagation?.();action(button.dataset.trendManualAction,button.dataset.trendManualValue);});
  select.onchange=()=>{if(state.editDraft&&!commitForm())return;trendManualSelect(state,select.value||null);state.mode=false;state.first=null;state.hover=null;};
  form.onsubmit=event=>{event.preventDefault();remember();commitForm();};
  if(element('[data-trend-snap]'))element('[data-trend-snap]').onchange=event=>{state.snap=event.target.value;state.view.snap=state.snap;trendManualPersist(state);refresh();};
  if(element('[data-trend-continuous]'))element('[data-trend-continuous]').onchange=event=>{state.continuous=event.target.checked;state.view.continuous=state.continuous;trendManualPersist(state);};
  if(element('[data-trend-price-step]'))element('[data-trend-price-step]').onchange=event=>{const value=Number(event.target.value);if(!Number.isFinite(value)||value<=0||value>1e15){error(new Error('양수인 가격 이동 단위를 입력해 주세요'));return;}state.view.priceStep=value;trendManualPersist(state);};
  if(element('[data-trend-import]'))element('[data-trend-import]').onchange=async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>524288)throw new Error('백업은 512KiB 이하여야 합니다');const backup=trendManualBackupCheck(trendUniqueJson(await file.text())),doc=backup.assets.find(d=>d.asset_id===state.assetId);state.importPreview=backup;const preview=element('[data-trend-import-preview]');preview.hidden=false;preview.innerHTML='<p>가져오기 미리보기 · '+esc(asset.label)+' '+doc.lines.length+'개 선 · 현재 '+state.lines.length+'개. 좌표·단위 검증 완료.</p><p>'+backup.assets.map(d=>esc(TREND_ASSETS.find(a=>a[0]===d.asset_id)[1])+': '+d.lines.length+'개').join(' · ')+'</p><label><input type="checkbox" data-trend-import-all>'+backup.assets.length+'개 자산 모두 가져오기</label><label><input type="checkbox" data-trend-import-templates>스타일 템플릿도 추가 ('+backup.templates.items.length+'개)</label><label><input type="checkbox" data-trend-import-replace>현재 자산의 선 교체 (기본은 추가)</label><button type="button" data-trend-import-confirm>선택 범위에 가져오기</button><button type="button" data-trend-import-cancel>취소</button><p>체크하지 않으면 현재 자산의 선만 추가합니다. 가져온 내용은 저장 전까지 편집본입니다.</p>';}catch(err){error(err);}};
  svg.addEventListener('pointerdown',event=>{
    if(state.editDraft&&!commitForm())return;
    if(!state.ready||event.button!==0&&event.pointerType!=='touch')return;TREND_MANUAL_ACTIVE_HOST=host;const p=point(event),tolerance=event.pointerType==='touch'?12:6;if(p.x<m.L||p.x>m.W-m.R||p.y<m.T||p.y>m.H-m.B)return;if(state.measure&&!state.mode){state.measure=null;layer.innerHTML=trendManualSvg(m,state);}
    const chosen=m.manualLines.find(l=>l.line_id===state.selected),handle=chosen&&!chosen.locked?[chosen.first_anchor,chosen.second_anchor].findIndex(a=>Math.hypot((m.x(a.index)-p.x)*p.sx,(m.y(a.price)-p.y)*p.sy)<=tolerance+2):-1,hit=!state.mode&&handle<0?trendLineHit({...m,lines:m.manualLines},p.x,p.y,tolerance,p.sx,p.sy):chosen;
    const hitSelected=hit&&trendManualTargets(state).includes(hit.line_id);
    if(!state.mode&&event.shiftKey&&!(event.ctrlKey||event.metaKey)&&handle<0&&!hit&&p.anchor){state.mode=true;state.tool='measure';state.first=null;state.second=null;}
    if(state.mode||handle>=0||hit){consume(event);if(gesture)return;if(hit&&!state.mode&&handle<0&&!trendManualTargets(state).includes(hit.line_id))trendManualSelect(state,hit.line_id,event.ctrlKey||event.metaKey);else if(hit&&!state.mode&&handle<0&&(event.ctrlKey||event.metaKey)&&!event.altKey){/* Ctrl-drag clones; Ctrl-click toggles on release. */}
      gesture={id:event.pointerId,anchor:p.anchor,start:p,handle,line:state.lines.find(l=>l.id===state.selected),records:trendManualCopy(selectedLines()),clone:!!(event.ctrlKey||event.metaKey),hitId:hit?.line_id,hitSelected,draw:state.mode};if(state.mode&&!state.first&&p.anchor&&!['horizontal','hray'].includes(state.tool||'ray')){state.first={...p.anchor};state.hover=null;gesture.setFirst=true;layer.innerHTML=trendManualSvg(m,state);}if(event.isTrusted)svg.setPointerCapture?.(event.pointerId);return;}
    if(state.selected)trendManualSelect(state,null);
  });
  const movedRecords=(g,p)=>{
    if(!p.anchor)throw new Error('검증된 날짜·가격 범위에서 이동해 주세요');if(g.records.some(l=>l.locked))throw new Error('잠긴 선을 먼저 잠금 해제해 주세요');
    if(g.handle>=0){const record={...g.line,[g.handle===0?'a':'b']:p.anchor};if(record.a.session>record.b.session)[record.a,record.b]=[record.b,record.a];return [record];}
    const rows=trendManualSessions(detail,m.analysis),from=Math.round(m.first+(g.start.x-m.L)/(m.W-m.L-m.R)*(m.end-m.first)),to=Math.round(m.first+(p.x-m.L)/(m.W-m.L-m.R)*(m.end-m.first)),start=rows.findIndex(s=>s.index===from),end=rows.findIndex(s=>s.index===to);if(start<0||end<0)throw new Error('확인된 날짜 범위 안에서 이동해 주세요');const a=trendManualPriceAt(m,g.start.y,scale),b=trendManualPriceAt(m,p.y,scale);
    return g.records.map(l=>trendManualMove(l,to-from,(l.axis==='log'||l.axis==='legacy'&&scale==='log')?Math.log(b/a):b-a,rows,scale));
  };
  svg.addEventListener('pointermove',event=>{const p=point(event);if(gesture&&gesture.id===event.pointerId){consume(event);gesture.anchor=p.anchor;if(gesture.draw){state.hover=p.anchor;layer.innerHTML=trendManualSvg(m,state);}else{try{const records=movedRecords(gesture,p);const old=m.manualLines;m.manualLines=old.map(l=>{const record=records.find(r=>r.id===l.line_id);return record?trendManualGeometry(record,detail,m.analysis,scale,m):l;}).filter(Boolean);layer.innerHTML=trendManualSvg(m,state);m.manualLines=old;}catch(_){/* Out-of-range preview does not mutate the working copy. */}}return;}if(state.mode){state.hover=p.anchor;layer.innerHTML=trendManualSvg(m,state);}});
  svg.addEventListener('pointerup',event=>{if(!gesture||gesture.id!==event.pointerId)return;consume(event);const g=gesture,p=point(event);gesture=null;if(svg.hasPointerCapture?.(event.pointerId))svg.releasePointerCapture(event.pointerId);if(g.draw){if(g.setFirst&&Math.hypot((p.x-g.start.x)*p.sx,(p.y-g.start.y)*p.sy)<6){refresh();return;}if(p.anchor)trendManualChoose(state,p.anchor,trendManualSessions(detail,m.analysis));else{if(g.setFirst)state.first=null;refresh();}return;}
    if(Math.hypot((p.x-g.start.x)*p.sx,(p.y-g.start.y)*p.sy)<3){if(g.clone&&g.hitId&&g.hitSelected)trendManualSelect(state,g.hitId,true);else refresh();return;}
    try{let records=movedRecords(g,p);trendManualValidateV2(records,state.assetId);if(g.clone){records=trendManualClone(state,records);trendManualApply(state,[...state.lines,...records],records.at(-1).id);state.created.push(...records.map(l=>l.id));}else trendManualApply(state,state.lines.map(l=>records.find(r=>r.id===l.id)||l),g.line?.id);state.selection=records.map(l=>l.id);refresh();}catch(err){error(err);}
  });
  svg.addEventListener('pointercancel',()=>{if(gesture?.setFirst)state.first=null;gesture=null;state.hover=null;refresh();});svg.addEventListener('pointerleave',()=>{if(!gesture){state.hover=null;layer.innerHTML=trendManualSvg(m,state);}});
  svg.addEventListener('keydown',event=>{if(!state.mode)return;if(event.key==='Escape'){consume(event);cancel();return;}if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','Enter'].includes(event.key))return;consume(event);const rows=trendManualSessions(detail,m.analysis).filter(p=>p.index>=m.first&&p.index<=m.end);if(!rows.length)return;let i=Math.max(0,rows.findIndex(p=>p.session===cursor.session));if(event.key==='Enter'){trendManualChoose(state,cursor,trendManualSessions(detail,m.analysis));return;}if(event.key==='ArrowLeft')i=Math.max(0,i-1);if(event.key==='ArrowRight')i=Math.min(rows.length-1,i+1);if(event.key==='Home')i=0;if(event.key==='End')i=rows.length-1;if(event.key==='ArrowUp'||event.key==='ArrowDown'){const price=trendManualPriceAt(m,m.y(cursor.price)+(event.key==='ArrowUp'?-5:5),scale);if(Number.isFinite(price)&&price>0&&price<=1e15)cursor.price=price;}else cursor={session:rows[i].session,price:rows[i].bar?.close||cursor.price};state.hover={...cursor};layer.innerHTML=trendManualSvg(m,state);});
  refresh();
}

function trendSegmentDistance(x,y,a,b,sx=1,sy=1){const dx=(b.x-a.x)*sx,dy=(b.y-a.y)*sy,px=(x-a.x)*sx,py=(y-a.y)*sy,t=Math.max(0,Math.min(1,(px*dx+py*dy)/(dx*dx+dy*dy||1)));return Math.hypot(px-t*dx,py-t*dy);}
function trendVisibleSegment(m,a,b){
  const dx=b.x-a.x,dy=b.y-a.y,p=[-dx,dx,-dy,dy],q=[a.x-m.L,m.W-m.R-a.x,a.y-m.T,m.H-m.B-a.y];let from=0,to=1;
  for(let i=0;i<4;i++){if(p[i]===0){if(q[i]<0)return null;continue;}const ratio=q[i]/p[i];if(p[i]<0){if(ratio>to)return null;from=Math.max(from,ratio);}else{if(ratio<from)return null;to=Math.min(to,ratio);}}
  return [{x:a.x+from*dx,y:a.y+from*dy},{x:a.x+to*dx,y:a.y+to*dy}];
}
function trendLineHit(m,x,y,tolerance=6,sx=1,sy=1){
  const hits=[];for(const line of m.lines){let distance=Infinity;for(let i=1;i<line.points.length;i++){const a=line.points[i-1],b=line.points[i],visible=trendVisibleSegment(m,{x:m.x(a.index),y:m.y(a.price)},{x:m.x(b.index),y:m.y(b.price)});if(visible)distance=Math.min(distance,trendSegmentDistance(x,y,visible[0],visible[1],sx,sy));}if(distance<=tolerance)hits.push({line,distance});}
  return hits.sort((a,b)=>Number(!!b.line.manual&&b.line.line_id===m.manualState?.selected)-Number(!!a.line.manual&&a.line.line_id===m.manualState?.selected)||a.distance-b.distance||a.line.line_id.localeCompare(b.line.line_id))[0]?.line||null;
}
function trendHoverAt(m,x,y,options={}){
  if(!Number.isFinite(x)||!Number.isFinite(y)||x<m.L||x>m.W-m.R||y<m.T||y>m.H-m.B)return null;
  const selectedManual=m.manualLines?.find(line=>line.line_id===m.manualState?.selected),selectedManualHit=selectedManual&&trendLineHit({...m,lines:[selectedManual]},x,y,options.touch?12:6,options.sx||1,options.sy||1);
  if(m.quote&&!selectedManualHit&&Math.hypot(m.x(m.quote.session_index)-x,m.y(m.quote.price)-y)<=12)return {kind:'quote',row:m.quote,index:m.quote.session_index};
  const index=Math.round(Math.max(m.first,Math.min(m.end,m.first+(x-m.L)/(m.W-m.L-m.R)*(m.end-m.first)))),gap=m.gaps.find(row=>row.session_index===index);
  if(m.critical||m.manualLines?.length){const line=trendLineHit({...m,lines:[...(m.manualLines||[]),...m.lines]},x,y,options.touch?12:6,options.sx||1,options.sy||1);if(line){const price=trendLinePrice(line,index,m.analysis.axis||options.scale||line.axis),bar=m.bars.find(row=>row.session_index===index),session=bar?.session||gap?.session||m.analysis.projection_sessions?.find(row=>row.index===index)?.session||null;if(price>0&&index>=trendLineStart(line))return {kind:'line',row:{session,session_index:index,price,close:bar?.close??null},index,line,future:index>(m.sourceLast??m.last)};}}
  if(gap)return {kind:'gap',row:gap,index};
  if(index>m.last){const session=m.analysis.projection_sessions?.find(row=>row.index===index)?.session||null;return {kind:'future',row:{session_index:index,session},index};}
  const bar=m.bars.find(row=>row.session_index===index);
  return bar?{kind:'bar',row:bar,index}:{kind:'gap',row:{session_index:index,session:null},index};
}
function trendHoverText(hit,asset){
  if(!hit)return '';
  const {kind,row}=hit,date=row.session||row.session_date||row.date||'';
  if(kind==='line'){const role=hit.line.role==='support'?'지지':'저항',zone=hit.line.kind==='horizontal_zone'?` · 가격대 ${trendPrice(hit.line.zone_low,asset)}–${trendPrice(hit.line.zone_high,asset)}`:'',name=hit.line.manual?'내 빗각선 '+hit.line.number+' · ':hit.line.slot?trendRepresentativeName(hit.line)+' · ':'';return `${date} · ${name}${hit.future?'추세선 연장값':hit.line.manual||hit.line.slot?'선 가격':role+'선 가격'} ${trendPrice(row.price,asset)}${zone}${row.close===null?' · 실제 종가 없음':` · 실제 종가 ${trendPrice(row.close,asset)} · 차이 ${trendPrice(row.price-row.close,asset)}`}`;}
  if(kind==='gap')return `${date} · 일봉 미표시 · 시세 없음`;
  if(kind==='future')return `${date||'선 연장 구간'} · 선 연장 · 미래 시세 없음`;
  if(kind==='quote')return `${date} ${row.time||''} · 장중 ${trendPrice(row.price,asset)} · 종가 아님`;
  return `${date} · 종가 ${trendPrice(row.close,asset)} · 시가 ${trendPrice(row.open,asset)} · 고가 ${trendPrice(row.high,asset)} · 저가 ${trendPrice(row.low,asset)}`;
}
function trendSvg(detail,model,asset,version='current'){
  const m=model,clip=`trend-clip-${detail.asset_id}-${version}`,futureX=Math.max(m.L,Math.min(m.W-m.R,m.x(m.last))),showFuture=m.end>m.last&&[...m.lines,...(m.manualLines||[])].some(line=>line.points.some(point=>point.future)),showFutureLabel=(m.W-m.R-futureX)*(m.cssWidth||m.W)/m.W>=50,bodyWidth=Math.max(1,Math.min(m.axisRight?16:8,(m.W-m.L-m.R)/(m.end-m.first+1)*.55));
  const gridTicks=m.axisRight?trendNiceTicks(m):m.ticks;
  const grid=gridTicks.map(price=>`<g><line x1="${m.L}" y1="${m.y(price)}" x2="${m.W-m.R}" y2="${m.y(price)}" stroke="#e1ded5"/>${m.axisRight?`<text x="${m.W-m.R+7}" y="${m.y(price)+4}">${esc(trendAxisNumber(price,gridTicks))}</text>`:`<text x="${m.L-7}" y="${m.y(price)+4}" text-anchor="end">${esc(Number(price).toLocaleString('ko-KR',{maximumFractionDigits:0}))}</text>`}</g>`).join('');
  const visibleBars=m.bars.filter(bar=>bar.session_index>=m.first&&bar.session_index<=m.end),tickBars=visibleBars.length?[visibleBars[0]]:[],tickGap=m.W<600?75:110;
  for(const bar of visibleBars.slice(1,-1))if(m.x(bar.session_index)-m.x(tickBars.at(-1).session_index)>=tickGap)tickBars.push(bar);
  const finalBar=visibleBars.at(-1);
  if(tickBars.length>1&&m.x(finalBar.session_index)-m.x(tickBars.at(-1).session_index)<(m.axisRight?tickGap:65))tickBars.pop();
  if(finalBar&&finalBar!==tickBars.at(-1))tickBars.push(finalBar);
  const ticks=tickBars.map(bar=>`<text x="${m.x(bar.session_index)}" y="${m.axisRight?m.H-9:m.H-15}" text-anchor="${m.axisRight&&m.x(bar.session_index)-m.L<30?'start':m.axisRight&&m.W-m.R-m.x(bar.session_index)<30?'end':'middle'}">${esc((bar.session||bar.session_date).slice(2))}</text>`).join('');
  const candles=m.bars.map(bar=>{const up=bar.close>=bar.open,color=up?'#bb4c1c':'#34738d',top=m.y(Math.max(bar.open,bar.close)),height=Math.max(1,Math.abs(m.y(bar.open)-m.y(bar.close)));return `<g data-trend-bar="${esc(bar.session||bar.session_date)}"><line x1="${m.x(bar.session_index)}" y1="${m.y(bar.high)}" x2="${m.x(bar.session_index)}" y2="${m.y(bar.low)}" stroke="${color}"/><rect x="${m.x(bar.session_index)-bodyWidth/2}" y="${top}" width="${bodyWidth}" height="${height}" fill="${color}"/></g>`;}).join('');
  const gaps=m.gaps.map(gap=>`<g data-trend-gap="${esc(gap.session)}"><rect x="${m.x(gap.session_index)-bodyWidth}" y="${m.T}" width="${bodyWidth*2}" height="${m.H-m.T-m.B}" fill="#b88120" opacity=".15"/><line x1="${m.x(gap.session_index)}" x2="${m.x(gap.session_index)}" y1="${m.T}" y2="${m.H-m.B}" stroke="#a77927" stroke-dasharray="2 4"/><title>${esc(gap.session)} · 원천 결측 일봉</title></g>`).join('');
  const paths=m.lines.map(line=>{const role=line.role||line.side,color=line.slot?TREND_REPRESENTATIVE_COLORS[line.slot]:role==='support'?'#247d78':'#bd5a20',actual=line.points.filter(point=>!point.future),future=line.points.filter(point=>point.future),path=points=>points.map(point=>`${m.x(point.index).toFixed(3)},${m.y(point.price).toFixed(3)}`).join(' ');const anchors=(m.critical?line.independent_contacts:[line.first_anchor,line.second_anchor]).filter(anchor=>anchor&&anchor.index>=m.first&&anchor.index<=m.end).map(anchor=>`<circle data-trend-marker="${esc(anchor.bar_id||anchor.index)}:${esc(anchor.side||line.role||line.side||'reference')}" cx="${m.x(anchor.index)}" cy="${m.y(anchor.price)}" r="2" fill="${color}" stroke="#fff" stroke-width=".7" vector-effect="non-scaling-stroke"><title>${esc(anchor.session)} · ${esc(trendPrice(anchor.price,asset))}</title></circle>`).join('');const zone=line.kind==='horizontal_zone'&&line.points.length>=2&&line.first_anchor.index<=m.end?`<rect x="${m.x(Math.max(m.first,line.first_anchor.index))}" y="${m.y(line.zone_high)}" width="${m.x(m.end)-m.x(Math.max(m.first,line.first_anchor.index))}" height="${Math.max(1,m.y(line.zone_low)-m.y(line.zone_high))}" fill="${color}" opacity=".07"/>`:'';return `<g data-trend-line="${esc(line.line_id)}" data-trend-role="${esc(role)}" data-trend-kind="${esc(line.kind||'diagonal')}"${line.slot?` data-trend-slot="${esc(line.slot)}" data-trend-aliases="${esc((line.alias_slots||[line.slot]).join(','))}"`:''}${line.classification==='reference_structure'?' opacity=".5"':''}>${zone}<polyline data-trend-line-path points="${path(actual)}" fill="none" stroke="${color}" stroke-width="1.1" vector-effect="non-scaling-stroke"/>${future.length?`<polyline data-trend-projection="${esc(line.line_id)}" points="${path([actual.at(-1),...future].filter(Boolean))}" fill="none" stroke="${color}" stroke-width="1" stroke-dasharray="3 5" vector-effect="non-scaling-stroke"/>`:''}${anchors}</g>`;}).join('');
  const quote=m.quote?`<g data-trend-quote-point="${esc(m.quote.date)}"><circle cx="${m.x(m.quote.session_index)}" cy="${m.y(m.quote.price)}" r="6" fill="#fff8e8" stroke="#a77919" stroke-width="2.5"/><text x="${m.x(m.quote.session_index)-9}" y="${m.y(m.quote.price)-10}" text-anchor="end">장중</text><title>${esc(m.quote.date)} ${esc(m.quote.time||'')} · ${esc(trendPrice(m.quote.price,asset))} · 별도 장중 관측, 일봉 종가 아님</title></g>`:'';
  const tipId=`trend-tooltip-${detail.asset_id}-${version}`;
  return `<svg data-trend-plot viewBox="0 0 ${m.W} ${m.H}" role="img" tabindex="0" aria-describedby="${tipId}" aria-label="${esc(asset.label)} 일봉과 상방·하방 빗각선. ${m.axisRight?'좌우 방향키로 차트를 이동합니다':'좌우 방향키로 날짜, 상하 방향키로 선을 선택합니다'}"><defs><clipPath id="${clip}"><rect x="${m.L}" y="${m.T}" width="${m.W-m.L-m.R}" height="${m.H-m.T-m.B}"/></clipPath></defs>${grid}${showFuture?`<rect x="${futureX}" y="${m.T}" width="${m.W-m.R-futureX}" height="${m.H-m.T-m.B}" fill="#eeece6" opacity=".8"/>${showFutureLabel?`<text x="${futureX+5}" y="${m.T+12}">선 연장</text>`:''}`:''}<g clip-path="url(#${clip})">${gaps}${candles}${paths}<g data-trend-manual-layer>${m.manualState?trendManualSvg(m,m.manualState):''}</g>${quote}<line data-trend-cross x1="${futureX}" x2="${futureX}" y1="${m.T}" y2="${m.H-m.B}" stroke="#777" stroke-dasharray="2 4" visibility="hidden"/><line data-trend-cross-price x1="${m.L}" x2="${m.W-m.R}" y1="${m.T}" y2="${m.T}" stroke="#247d78" stroke-dasharray="3 4" visibility="hidden"/><circle data-trend-hover-point cx="${futureX}" cy="${m.T}" r="4" fill="#247d78" stroke="#fff" visibility="hidden"/></g>${ticks}${m.axisRight?trendAxisChrome(detail,m,asset):''}<rect data-trend-overlay x="${m.L}" y="${m.T}" width="${m.W-m.L-m.R}" height="${m.H-m.T-m.B}" fill="transparent"/></svg><div id="${tipId}" class="trend-tooltip" data-trend-tooltip role="tooltip" hidden><span data-trend-tooltip-date></span><div><span data-trend-tooltip-kind></span><strong data-trend-tooltip-price></strong></div><p data-trend-tooltip-ohlc></p><small data-trend-tooltip-current></small></div>`;
}
// Workspace axis chrome: latest price and personal-line tags, drag zones and crosshair labels.
function trendAxisChrome(detail,m,asset){
  const reference=trendReference(detail),bars=detail.bars,base=reference.quote?bars.at(-1).close:bars.length>1?bars.at(-2).close:null,color=base!==null&&reference.price<base?'#34738d':'#bb4c1c',y=m.y(reference.price),visible=y>=m.T&&y<=m.H-m.B;
  const tag=(top,fill,text,attrs='')=>`<g${attrs} pointer-events="none"><rect x="${m.W-m.R+1}" y="${top-9}" width="${m.R-2}" height="18" rx="2" fill="${fill}"/><text x="${m.W-m.R+6}" y="${top+4}" style="fill:#fff;font-weight:700">${esc(text)}</text></g>`;
  return `<line x1="${m.W-m.R}" x2="${m.W-m.R}" y1="${m.T}" y2="${m.H-m.B}" stroke="#d6d3ca"/><line x1="${m.L}" x2="${m.W-m.R}" y1="${m.H-m.B}" y2="${m.H-m.B}" stroke="#d6d3ca"/>`
    +(visible?`<line data-trend-last-line x1="${m.L}" x2="${m.W-m.R}" y1="${y}" y2="${y}" stroke="${color}" stroke-dasharray="1 3" opacity=".8" pointer-events="none"/>`+tag(y,color,trendAxisPrice(reference.price,asset),' data-trend-last-tag'):'')
    +`<g data-trend-manual-tags>${m.manualState?trendManualTags(m,m.manualState,asset):''}</g>`
    +`<rect data-trend-price-axis x="${m.W-m.R}" y="${m.T}" width="${m.R}" height="${m.H-m.B-m.T}" fill="transparent"><title>드래그: 세로 배율 · 더블클릭: 자동</title></rect><rect data-trend-time-axis x="${m.L}" y="${m.H-m.B}" width="${m.W-m.L-m.R}" height="${m.B}" fill="transparent"><title>드래그: 가로 배율</title></rect>`
    +`<g data-trend-ws-ylabel visibility="hidden" pointer-events="none"><rect x="${m.W-m.R+1}" y="0" width="${m.R-2}" height="18" rx="2" fill="#26302b"/><text x="${m.W-m.R+6}" y="13" style="fill:#fff"></text></g>`
    +`<g data-trend-ws-xlabel visibility="hidden" pointer-events="none"><rect x="0" y="${m.H-m.B+3}" width="80" height="18" rx="2" fill="#26302b"/><text x="40" y="${m.H-m.B+16}" text-anchor="middle" style="fill:#fff"></text></g>`;
}
function trendManualTags(m,state,asset){
  if(!m.axisRight)return '';
  const selected=new Set(trendManualTargets(state));
  return (m.manualLines||[]).filter(line=>selected.has(line.line_id)||line.first_anchor.price===line.second_anchor.price).map(line=>{
    const end=[...line.points].reverse().find(point=>point.index<=m.end&&point.index>=m.first),y=end?m.y(end.price):NaN;if(!(y>=m.T&&y<=m.H-m.B))return '';
    return `<g data-trend-manual-tag="${esc(line.line_id)}" pointer-events="none"><rect x="${m.W-m.R+1}" y="${y-9}" width="${m.R-2}" height="18" rx="2" fill="${(line.style||TREND_MANUAL_STYLE).color}"/><text x="${m.W-m.R+6}" y="${y+4}" style="fill:#fff">${esc(trendAxisPrice(end.price,asset))}</text></g>`;
  }).join('');
}
function bindTrendChart(host,detail,m,asset,scale){
  const svg=host.querySelector('svg'),cross=host.querySelector('[data-trend-cross]'),horizontal=host.querySelector('[data-trend-cross-price]'),marker=host.querySelector('[data-trend-hover-point]'),readout=host.querySelector('[data-trend-readout]'),tip=host.querySelector('[data-trend-tooltip]');
  const linePool=()=>[...m.lines,...(m.manualLines||[])];
  const entries=[...m.bars.map(row=>({kind:'bar',row})),...m.gaps.map(row=>({kind:'gap',row})),...(m.quote?[{kind:'quote',row:m.quote}]:[]),...(m.critical?m.analysis.projection_sessions.filter(row=>row.index>m.last&&row.index<=m.end).map(row=>({kind:'future',row:{...row,session_index:row.index}})):[])].sort((a,b)=>a.row.session_index-b.row.session_index||Number(a.kind==='quote')-Number(b.kind==='quote'));
  let selected=entries.findIndex(entry=>entry.kind==='bar'&&entry.row===m.bars.at(-1)),selectedLine=-1;
  const emphasize=line=>host.querySelectorAll?.('[data-trend-line],[data-trend-manual-line]').forEach(group=>{const manual=group.dataset.trendManualLine,id=manual||group.dataset.trendLine,active=id===line?.line_id||manual&&m.manualState?.selected===id;if(manual)return;group.querySelector(manual?'[data-trend-manual-path]':'[data-trend-line-path]')?.setAttribute('stroke-width',active?'1.8':'1.1');group.querySelector(manual?'[data-trend-manual-projection]':'[data-trend-projection]')?.setAttribute('stroke-width',active?'1.8':'1');});
  const hide=()=>{tip.hidden=true;emphasize(null);for(const node of [cross,horizontal,marker])node.setAttribute('visibility','hidden');};
  const paint=(hit,show=true)=>{if(!hit){hide();return;}const {kind,row,index}=hit,entry=entries.findIndex(entry=>kind==='line'?entry.kind!=='quote'&&entry.row.session_index===index:entry.kind===kind&&entry.row===row);if(entry>=0)selected=entry;readout.textContent=trendHoverText(hit,asset);if(!show)return;
    const price=kind==='bar'?row.close:kind==='quote'||kind==='line'?row.price:null,reference=trendReference(detail);emphasize(kind==='line'?hit.line:null);cross.setAttribute('x1',m.x(index));cross.setAttribute('x2',m.x(index));cross.setAttribute('visibility','visible');
    for(const node of [horizontal,marker])node.setAttribute('visibility',price===null?'hidden':'visible');
    if(price!==null){horizontal.setAttribute('y1',m.y(price));horizontal.setAttribute('y2',m.y(price));marker.setAttribute('cx',m.x(index));marker.setAttribute('cy',m.y(price));}
    tip.dataset.trendKind=kind;host.querySelector('[data-trend-tooltip-date]').textContent=row.session||row.session_date||row.date||(kind==='future'?'선 연장 구간':'일봉 미확인');
    host.querySelector('[data-trend-tooltip-kind]').textContent=kind==='line'?hit.line.manual?'내 빗각선 '+hit.line.number+' · '+(hit.future?'추세선 연장값':'선 가격'):hit.line.slot?`${trendRepresentativeName(hit.line)} · ${hit.future?'추세선 연장값':'선 가격'}`:hit.future?'추세선 연장값':`${hit.line.role==='support'?'지지':'저항'}선 가격`:kind==='bar'?'종가':kind==='quote'?'장중 관측':kind==='future'?'선 연장':'일봉';
    host.querySelector('[data-trend-tooltip-price]').textContent=price===null?'시세 없음':trendPrice(price,asset);
    host.querySelector('[data-trend-tooltip-ohlc]').textContent=kind==='line'?[hit.line.kind==='horizontal_zone'?`가격대 ${trendPrice(hit.line.zone_low,asset)}–${trendPrice(hit.line.zone_high,asset)}`:null,row.close===null?'실제 종가 없음':`실제 종가 ${trendPrice(row.close,asset)} · 차이 ${trendPrice(row.price-row.close,asset)}`].filter(Boolean).join(' · '):kind==='bar'?`시가 ${trendPrice(row.open,asset)} · 고가 ${trendPrice(row.high,asset)} · 저가 ${trendPrice(row.low,asset)}`:kind==='quote'?'별도 장중 관측 · 종가 아님':kind==='future'?'미래 가격이 아닌 추세선 연장 구간':'확인되지 않은 일봉';
    host.querySelector('[data-trend-tooltip-current]').textContent=`최근 관측 ${trendPrice(reference.price,asset)} · ${reference.date}${reference.time?' '+reference.time:''}`;
    tip.hidden=false;const bounds=svg.getBoundingClientRect(),px=m.x(index)/m.W*bounds.width,py=(price===null?m.T+18:m.y(price))/m.H*bounds.height,w=tip.offsetWidth,h=tip.offsetHeight;
    const hostBounds=host.getBoundingClientRect?.(),offsetLeft=hostBounds?bounds.left-hostBounds.left:0,offsetTop=hostBounds?bounds.top-hostBounds.top:0;
    tip.style.left=`${offsetLeft+Math.max(4,Math.min(bounds.width-w-4,px+w+16>bounds.width?px-w-14:px+14))}px`;tip.style.top=`${offsetTop+Math.max(4,Math.min(bounds.height-h-4,py-h/2))}px`;
  };
  const paintEntry=index=>{selected=Math.max(0,Math.min(entries.length-1,index));const entry=entries[selected],ordinal=entry.row.session_index,line=linePool()[selectedLine];if(line&&ordinal>=trendLineStart(line)){const price=trendLinePrice(line,ordinal,scale);if(price>0){paint({kind:'line',index:ordinal,line,row:{session:entry.row.session||entry.row.session_date||entry.row.date,price,close:entry.kind==='bar'?entry.row.close:null},future:ordinal>(m.sourceLast??m.last)});return;}}paint({...entry,index:ordinal});};
  const pointer=event=>{if(host._trendManual?.busy())return;const bounds=svg.getBoundingClientRect(),sx=bounds.width/m.W,sy=bounds.height/m.H;let x=(event.clientX-bounds.left)/sx,y=(event.clientY-bounds.top)/sy;if(svg.getScreenCTM&&globalThis.DOMPoint){const matrix=svg.getScreenCTM();if(matrix){const point=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());x=point.x;y=point.y;}}const hit=trendHoverAt(m,x,y,{touch:event.pointerType==='touch',sx,sy,scale});selectedLine=hit?.kind==='line'?linePool().findIndex(line=>line.line_id===hit.line.line_id):-1;paint(hit);};
  svg.addEventListener('pointermove',pointer);svg.addEventListener('pointerdown',pointer);
  svg.addEventListener('pointerleave',event=>{if(event.pointerType!=='touch')hide();});svg.addEventListener('blur',hide);
  svg.addEventListener('focus',()=>{if(!host._trendManual?.busy())paintEntry(selected);});
  svg.addEventListener('keydown',event=>{if(host._trendManual?.busy()||host._trendManual?.state.selected)return;if(event.key==='Escape'){event.preventDefault();hide();return;}let index=selected;if(event.key==='ArrowLeft')index--;else if(event.key==='ArrowRight')index++;else if(event.key==='ArrowUp'||event.key==='ArrowDown'){if(!m.critical&&!m.manualLines?.length||!linePool().length)return;selectedLine=(selectedLine+1+(event.key==='ArrowUp'?1:-1)+linePool().length+1)%(linePool().length+1)-1;host._trendManual?.select(linePool()[selectedLine]?.manual?linePool()[selectedLine].line_id:null);}else if(event.key==='Home')index=0;else if(event.key==='End')index=entries.length-1;else return;event.preventDefault();paintEntry(index);});
  paint({...entries[selected],index:entries[selected].row.session_index},false);
}
function trendZoomViewport(bars,state){
  // Expanded workspaces keep a continuous display window; source rows stay intact.
  if(state.xRange?.length===2&&state.xRange.every(Number.isFinite)&&state.xRange[1]>state.xRange[0]){
    const first=bars.findIndex(bar=>bar.session_index>=state.xRange[0]),last=bars.findLastIndex(bar=>bar.session_index<=state.xRange[1]);
    let from=first<0?bars.length-1:Math.max(0,first-1),to=last<0?1:Math.min(bars.length,last+2);
    if(to-from<20){from=Math.max(0,from-Math.ceil((20-(to-from))/2));to=Math.min(bars.length,Math.max(to,from+20));from=Math.max(0,Math.min(from,to-20));}
    state.offset=from;state.heldCount=to-from;return bars.slice(from,to);
  }
  const maximum=Math.max(1,Math.min(state.maxFactor??8,bars.length/20));state.factor=Math.max(1,Math.min(maximum,Number(state.factor)||1));const count=Math.min(bars.length,Math.max(20,Number.isInteger(state.heldCount)?state.heldCount:Math.ceil(bars.length/state.factor))),limit=bars.length-count;
  const offset=state.offset===null||state.offset===undefined?limit:Math.max(0,Math.min(limit,Math.round(state.offset)));state.offset=offset;return bars.slice(offset,offset+count);
}
function closeTrendZoom(restore=true){
  if(!TREND_ZOOM)return;const zoom=TREND_ZOOM;TREND_ZOOM=null;
  if(globalThis.document?.fullscreenElement&&zoom.layer.contains?.(document.fullscreenElement))document.exitFullscreen?.()?.catch?.(()=>{});
  zoom.layer.remove();document.body.classList.remove('trend-zoom-open');for(const [node,value] of zoom.inert)if(node.isConnected)node.inert=value;
  window.removeEventListener('keydown',zoom.key);window.removeEventListener('resize',zoom.resize);document.removeEventListener?.('fullscreenchange',zoom.resize);
  if(zoom.host){zoom.host._trendWsDisposeNavigation?.();TREND_MANUAL_VIEWS.delete(zoom.host);}
  if(restore){const trigger=zoom.trigger?.isConnected?zoom.trigger:document.querySelector(zoom.triggerSelector);trigger?.focus();if(!zoom.ws?.pendingAsset)zoom.ws?.context?.onClose?.(zoom.ws);}
}
// Page charts are previews: a press or the button opens the drawing workspace.
function trendPreviewBar(detail){
  const manual=trendManualState(detail.asset_id),notes=[manual.lines.length?'내 선 '+manual.lines.length+'개':null,manual.saveStatus==='dirty'?'● 미저장':null,manual.recovery||manual.conflict?'임시본 확인 필요':null].filter(Boolean).join(' · ');
  return `<div class="trend-chart-tools trend-preview-bar"><button type="button" class="trend-expand-primary" data-trend-tool="expand" aria-haspopup="dialog">크게 열어 추세선 그리기 <span aria-hidden="true">⤢</span></button>${notes?`<span class="trend-preview-meta">${esc(notes)}</span>`:''}</div>`;
}
function trendManualSummary(m,detail,asset){
  const reference=trendReference(detail),rows=(m.manualLines||[]).filter(line=>['right','both'].includes(line.extension)||line.second_anchor.index>=reference.index).map(line=>({line,price:trendLinePrice(line,reference.index,line.axis)})).filter(row=>Number.isFinite(row.price)&&row.price>0);
  if(!rows.length)return '';
  return `<div class="trend-manual-summary" aria-label="내 선의 최근 관측일 가격">${rows.map(({line,price})=>{const distance=(price/reference.price-1)*100;return `<span><i style="background:${esc((line.style||TREND_MANUAL_STYLE).color)}"></i>${esc(line.name||'내 선 '+line.number)} <b>${esc(trendPrice(price,asset))}</b> <small>${distance>0?'+':''}${distance.toFixed(2)}%</small></span>`;}).join('')}</div>`;
}
function trendGenericWorkspaceContext(detail,analysis,baseBars,bars,asset,scale,version){
  return {assetId:detail.asset_id,asset,scale,family:null,version,initialBars:bars,fixedScale:true,build:()=>({source:{...detail,bars:baseBars},analysis})};
}
function drawTrendInteractiveChart(host,detail,analysis,baseBars,asset,scale,version,state,onState=()=>{},modal=false){
  const ws=modal&&typeof modal==='object'?modal:null;
  const active=globalThis.document?.activeElement,restoreName=host.contains?.(active)&&active?.closest?.('[data-trend-manual-form]')?active.name:null,restoreTool=host.contains?.(active)?active?.dataset?.trendTool:null;
  const workspace=trendManualState(detail.asset_id),window=ws?null:state.dateWindow||workspace.view.window,date=bar=>bar.session||bar.session_date;
  // Passive updates preserve both historical date bounds, including while the
  // first short response is still waiting for the verified full series.
  const pendingWindow=window&&!window.tail&&(window.start<date(baseBars[0])||window.end>date(baseBars.at(-1)));
  if(window){state.factor=window.factor;if(window.tail){state.offset=null;state.heldCount=null;}else if(!pendingWindow){const first=baseBars.findIndex(b=>date(b)>=window.start),last=baseBars.findLastIndex(b=>date(b)<=window.end);state.offset=Math.max(0,first);state.heldCount=last>=first?last-first+1:null;}}
  const bars=trendZoomViewport(baseBars,state),maximum=Math.max(1,Math.min(state.maxFactor??8,baseBars.length/20));
  if(ws)return drawTrendWorkspace(host,detail,analysis,baseBars,bars,asset,scale,version,state,ws,maximum,restoreName);
  const m=trendPlotModel(detail,analysis,bars,scale,host.clientWidth||1000);
  state.dateWindow=pendingWindow?window:{start:date(bars[0]),end:date(bars.at(-1)),factor:state.factor,tail:state.offset+bars.length>=baseBars.length};workspace.view.window={...state.dateWindow};
  m.manualState=workspace;m.manualDetail=detail;m.manualLines=m.manualState.lines.filter(l=>!l.hidden).map(l=>trendManualGeometry(l,detail,analysis,scale,m)).filter(Boolean);
  host.innerHTML=trendPreviewBar(detail)+trendSvg(detail,m,asset,version)+'<p data-trend-readout class="trend-readout" aria-live="polite"></p>'+trendManualSummary(m,detail,asset)+(!analysis.lines.length?`<p class="trend-direction-empty">${analysis.representative?'추세선 자료를 확인하고 있습니다.':'확인된 경계 없음'}</p>`:'');bindTrendChart(host,detail,m,asset,scale);trendManualBindKeys();
  if(host.dataset)host.dataset.trendPreview='';
  const open=(options={})=>openTrendWorkspace(host._trendWorkspaceContext||trendGenericWorkspaceContext(detail,analysis,baseBars,bars,asset,scale,version),host.querySelector?.('[data-trend-tool="expand"]'),options);
  host._trendOpenWorkspace=open;host._trendNavigation={m,state,baseBars,bars};
  if(restoreTool&&/^[a-z]+$/.test(restoreTool))host.querySelector('[data-trend-tool="'+restoreTool+'"]')?.focus();
  host.querySelectorAll?.('[data-trend-tool]').forEach(button=>{button.onclick=()=>open();});
  const svg=host.querySelector?.('svg');
  if(svg?.addEventListener){let press=null;svg.addEventListener('pointerdown',event=>{press={id:event.pointerId,x:event.clientX,y:event.clientY};});svg.addEventListener('pointercancel',()=>{press=null;});svg.addEventListener('pointerup',event=>{const start=press;press=null;if(start&&start.id===event.pointerId&&Math.hypot(event.clientX-start.x,event.clientY-start.y)<=8&&(event.button===0||event.pointerType==='touch'))open();});svg.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open();}});}
}
const TREND_RANGE_PRESETS=[['1M',21,30],['3M',63,91],['6M',126,182],['1Y',252,365],['3Y',756,1095],['전체',null,null]];
const TREND_WS_ICONS={
  cursor:'<path d="M5.5 3.2v12.3l3.3-3.1 2.2 4.8 2-.9-2.2-4.7h4.4z" fill="currentColor"/>',
  ray:'<path d="M4 16 16.5 3.5M12.6 3.5h3.9v3.9" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="4" cy="16" r="1.9" fill="#fff" stroke="currentColor" stroke-width="1.3"/><circle cx="9.5" cy="10.5" r="1.9" fill="#fff" stroke="currentColor" stroke-width="1.3"/>',
  segment:'<path d="M4.5 15.5 15.5 4.5" stroke="currentColor" stroke-width="1.5"/><circle cx="4.5" cy="15.5" r="1.9" fill="#fff" stroke="currentColor" stroke-width="1.3"/><circle cx="15.5" cy="4.5" r="1.9" fill="#fff" stroke="currentColor" stroke-width="1.3"/>',
  extended:'<path d="M1.5 18.5 18.5 1.5" stroke="currentColor" stroke-width="1.5"/><circle cx="7" cy="13" r="1.9" fill="#fff" stroke="currentColor" stroke-width="1.3"/><circle cx="13" cy="7" r="1.9" fill="#fff" stroke="currentColor" stroke-width="1.3"/>',
  horizontal:'<path d="M1.5 10h17" stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="10" r="1.9" fill="#fff" stroke="currentColor" stroke-width="1.3"/>',
  hray:'<path d="M5 10h13M15 7.5l3 2.5-3 2.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><circle cx="5" cy="10" r="1.9" fill="#fff" stroke="currentColor" stroke-width="1.3"/>',
  channel:'<path d="M2.5 12.5 13.5 4.5M6.5 17.5l11-8" stroke="currentColor" stroke-width="1.5"/><path d="M4 11.5v4.8" stroke="currentColor" stroke-width="1" stroke-dasharray="1.5 1.5"/>',
  measure:'<path d="M3 13.5 13.5 3 17 6.5 6.5 17z" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M6.4 10.1l1.5 1.5M8.9 7.6l1.5 1.5M11.4 5.1l1.5 1.5" stroke="currentColor" stroke-width="1.2"/>',
  magnet:'<path d="M5 3.5v6.2a5 5 0 0 0 10 0V3.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M3.6 3.6h2.8M13.6 3.6h2.8" stroke="currentColor" stroke-width="2.6"/>',
  repeat:'<path d="M4 8.5a6 6 0 0 1 10.6-3.3L16 6.6M16 3.4v3.2h-3.2M16 11.5a6 6 0 0 1-10.6 3.3L4 13.4M4 16.6v-3.2h3.2" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
  eye:'<path d="M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10z" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="10" cy="10" r="2.4" fill="none" stroke="currentColor" stroke-width="1.4"/>',
  lock:'<rect x="5" y="9" width="10" height="8" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M7 9V6.6a3 3 0 0 1 6 0V9" fill="none" stroke="currentColor" stroke-width="1.4"/>',
  trash:'<path d="M4.5 6h11M8 6V4h4v2M6 6l.8 10.5h6.4L14 6" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>',
  undo:'<path d="M7 5 3.5 8.5 7 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M4 8.5h7.5a4.3 4.3 0 0 1 0 8.6H9" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  redo:'<path d="M13 5l3.5 3.5L13 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M16 8.5H8.5a4.3 4.3 0 0 0 0 8.6H11" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  panel:'<rect x="2.5" y="3.5" width="15" height="13" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M12 3.5v13M13.8 7h2M13.8 10h2M13.8 13h2" stroke="currentColor" stroke-width="1.3"/>',
  camera:'<rect x="2.5" y="6" width="15" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="10" cy="11" r="2.8" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M7 6l1.2-2h3.6L13 6" fill="none" stroke="currentColor" stroke-width="1.4"/>',
  fullscreen:'<path d="M3 7.5V3h4.5M12.5 3H17v4.5M17 12.5V17h-4.5M7.5 17H3v-4.5" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  close:'<path d="M5 5l10 10M15 5 5 15" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
};
function trendIcon(name){return `<svg class="trend-ico" viewBox="0 0 20 20" aria-hidden="true" focusable="false">${TREND_WS_ICONS[name]||''}</svg>`;}
function trendWorkspaceAssetMenu(ws){
  const current=ws.pendingAsset||ws.assetId,groups=[...new Set(TREND_VISIBLE_ASSETS.map(([id])=>TREND_ASSET_META[id]?.group||'기타'))];
  return `<div class="trend-ws-menu" role="menu" aria-label="자산 선택">${groups.map(group=>`<div role="group" aria-label="${esc(group)}"><span>${esc(group)}</span>${TREND_VISIBLE_ASSETS.filter(([id])=>(TREND_ASSET_META[id]?.group||'기타')===group).map(([id,label])=>`<button type="button" role="menuitemradio" aria-checked="${id===current}" data-trend-ws-asset="${esc(id)}"><strong>${esc(label)}</strong><small>${esc(TREND_ASSET_META[id]?.ticker||'')}</small></button>`).join('')}</div>`).join('')}</div>`;
}
function trendWorkspaceSymbol(ws,label,ticker){
  return `<div class="trend-ws-symbol"><button type="button" class="trend-ws-asset" data-trend-ws-action="assets" aria-haspopup="menu" aria-expanded="${ws.assetMenu}"><strong>${esc(label)}</strong>${ticker?`<small>${esc(ticker)}</small>`:''}<span aria-hidden="true">▾</span></button>${ws.assetMenu?trendWorkspaceAssetMenu(ws):''}</div>`;
}
function trendWorkspaceHelp(){
  const rows=[['그리기',[['Alt+T','추세선'],['Alt+H','수평선'],['Alt+J','수평 반직선'],['Shift+드래그','측정'],['Shift (그리는 중)','수평 고정'],['Esc','취소']]],['편집',[['Delete','삭제'],['Ctrl+Z · Ctrl+Y','되돌리기 · 다시'],['Ctrl+C · Ctrl+V','복사 · 붙여넣기'],['Ctrl+드래그','복제'],['Ctrl+클릭','여러 선 선택'],['방향키','선택한 선 이동'],['Ctrl+S','저장'],['Ctrl+Alt+H','모두 숨김']]],['화면',[['휠','확대 · 축소'],['Shift+휠','좌우 이동'],['드래그','이동'],['가격축 드래그','세로 배율'],['가격축 더블클릭','자동 배율'],['시간축 드래그','가로 배율'],['← · →','1봉 이동'],['Ctrl+↑ · ↓','확대 · 축소'],['Alt+R','초기화'],['Alt+L','로그 축'],['Alt+G','날짜로 이동']]]];
  return `<div class="trend-ws-help" role="dialog" aria-label="단축키"><div class="trend-ws-help-head"><strong>단축키</strong><button type="button" class="trend-ws-icon" data-trend-ws-action="help" aria-label="닫기">${trendIcon('close')}</button></div>${rows.map(([title,items])=>`<section><h3>${esc(title)}</h3><dl>${items.map(([key,text])=>`<div><dt><kbd>${esc(key)}</kbd></dt><dd>${esc(text)}</dd></div>`).join('')}</dl></section>`).join('')}</div>`;
}
function trendWorkspaceFrame(detail,asset,scale,ws){
  const meta=TREND_ASSET_META[detail.asset_id]||{},label=asset?.label||TREND_ASSETS.find(row=>row[0]===detail.asset_id)?.[1]||detail.asset_id,fixed=!!ws.context.fixedScale;
  const tool=(action,icon,title,key='')=>`<button type="button" class="trend-ws-tool" data-trend-manual-action="${action}" title="${esc(title+(key?' · '+key:''))}" aria-label="${esc(title)}" aria-pressed="false">${trendIcon(icon)}</button>`;
  const icon=(attrs,name,title)=>`<button type="button" class="trend-ws-icon" ${attrs} title="${esc(title)}" aria-label="${esc(title.split(' · ')[0])}">${trendIcon(name)}</button>`;
  const families=ws.context.family===null?'':`<div class="trend-ws-seg trend-ws-families" role="group" aria-label="자동 추세선">${[['all','모두'],['regression_200','200일'],['current_structure','현재'],['major_structure','장기'],['long_boundaries','상·하단']].map(([value,text])=>`<button type="button" data-trend-ws-family="${value}" aria-pressed="${!ws.hideAuto&&ws.family===value}">${text}</button>`).join('')}<button type="button" data-trend-ws-family="none" aria-pressed="${ws.hideAuto}">끄기</button></div>`;
  const button=(action,text)=>`<button type="button" data-trend-manual-action="${action}">${text}</button>`;
  return `<header class="trend-ws-top"><div class="trend-ws-top-scroll">${trendWorkspaceSymbol(ws,label,meta.ticker)}<span class="trend-ws-interval" title="일봉">1D</span>${families}<div class="trend-ws-seg" role="group" aria-label="가격 축"><button type="button" data-trend-ws-action="linear" aria-pressed="${scale==='linear'}"${fixed?' disabled':''}>선형</button><button type="button" data-trend-ws-action="log" aria-pressed="${scale==='log'}" title="Alt+L"${fixed?' disabled':''}>로그</button></div></div><div class="trend-ws-actions">${icon('data-trend-manual-action="undo"','undo','되돌리기 · Ctrl+Z')}${icon('data-trend-manual-action="redo"','redo','다시 실행 · Ctrl+Y')}<button type="button" class="trend-save trend-ws-save" data-trend-manual-action="save" title="Ctrl+S">저장</button><output data-trend-save-state></output>${icon(`data-trend-ws-action="panel" aria-pressed="${ws.panelOpen}"`,'panel','내 선 목록')}${icon('data-trend-ws-action="snapshot"','camera','이미지 저장').replace('trend-ws-icon','trend-ws-icon trend-ws-wide')}${icon('data-trend-ws-action="fullscreen"','fullscreen','전체 화면').replace('trend-ws-icon','trend-ws-icon trend-ws-wide')}<button type="button" class="trend-ws-icon trend-ws-wide" data-trend-ws-action="help" aria-pressed="${ws.helpOpen}" title="단축키 · ?" aria-label="단축키">?</button>${icon('data-trend-ws-action="close"','close','닫기 · Esc').replace('trend-ws-icon','trend-ws-icon trend-ws-close')}</div></header>`
    +`<div class="trend-ws-main${ws.panelOpen?' has-panel':''}"><nav class="trend-ws-tools" role="toolbar" aria-label="그리기 도구">${tool('cursor','cursor','커서','Esc')}${tool('draw','ray','추세선','Alt+T')}${tool('draw-segment','segment','선분')}${tool('draw-extended','extended','연장선')}${tool('draw-horizontal','horizontal','수평선','Alt+H')}${tool('draw-hray','hray','수평 반직선','Alt+J')}${tool('draw-channel','channel','평행 채널')}${tool('measure','measure','측정','Shift+드래그')}<span class="trend-ws-divider" aria-hidden="true"></span>${tool('snap-cycle','magnet','자석')}${tool('continuous-toggle','repeat','연속 그리기')}<span class="trend-ws-divider" aria-hidden="true"></span>${tool('hide-all','eye','모두 숨김','Ctrl+Alt+H')}${tool('lock-all','lock','모두 잠금')}${tool('clear','trash','모두 지우기')}</nav>`
    +`<div class="trend-ws-stage" data-trend-ws-stage></div>`
    +`<aside class="trend-ws-panel" data-trend-ws-panel aria-label="내 선 목록"${ws.panelOpen?'':' hidden'}><div class="trend-ws-panel-head"><strong>내 선</strong><span data-trend-ws-count></span><button type="button" class="trend-ws-icon" data-trend-ws-action="panel" aria-label="목록 닫기">${trendIcon('close')}</button></div><div class="trend-recovery" data-trend-recovery hidden></div><div class="trend-manual-list" data-trend-manual-list></div>${trendManualEditorMarkup()}<p class="trend-manual-statistics" data-trend-manual-statistics></p>${button('more','설정 · 백업')}<div class="trend-manual-extra" data-trend-more hidden><label>자석<select data-trend-snap><option value="off">꺼짐</option><option value="weak">약함</option><option value="strong">강함</option></select></label><label><input type="checkbox" data-trend-continuous>연속 그리기</label><label>가격 이동 단위<input type="number" min="0.00000001" step="any" data-trend-price-step value="1"></label>${button('revert','저장본으로 되돌리기')}${button('export','확정본 백업')}${button('save-export','저장 후 백업')}${button('working-export','편집본 백업')}<label class="trend-import-label">백업 가져오기<input type="file" accept="application/json,.json" data-trend-import></label></div><div data-trend-import-preview hidden></div><select data-trend-manual-select aria-label="내 선 선택" hidden></select></aside></div>`
    +`<footer class="trend-ws-bottom"><div class="trend-ws-seg trend-ws-ranges" role="group" aria-label="표시 기간">${TREND_RANGE_PRESETS.map(([text])=>`<button type="button" data-trend-tool="range" data-trend-range="${text}" aria-pressed="false">${text}</button>`).join('')}</div><div class="trend-ws-zoom" role="group" aria-label="시간축"><button type="button" data-trend-tool="out" aria-label="축소" title="축소 · Ctrl+↓">−</button><button type="button" data-trend-tool="in" aria-label="확대" title="확대 · Ctrl+↑">＋</button><button type="button" data-trend-tool="left" aria-label="이전 구간" title="이전 구간 · ←">‹</button><button type="button" data-trend-tool="right" aria-label="다음 구간" title="다음 구간 · →">›</button><button type="button" data-trend-tool="reset" title="초기화 · Alt+R">초기화</button></div><output class="trend-ws-span" data-trend-ws-span></output><label class="trend-ws-goto"><span>날짜</span><input type="date" data-trend-ws-goto aria-label="날짜로 이동" title="Alt+G"></label><p class="trend-manual-status trend-ws-status" data-trend-manual-status role="status"></p><button type="button" class="trend-ws-auto" data-trend-ws-action="auto" aria-pressed="true" title="가격축 자동 · 가격축 더블클릭">자동</button></footer>`
    +(ws.helpOpen?trendWorkspaceHelp():'')
    +(ws.confirmClose?`<div class="trend-ws-confirm" role="alertdialog" aria-label="저장하지 않은 변경"><div><strong>저장하지 않은 변경이 있습니다</strong><p>임시본은 이 브라우저에 남습니다.</p><div><button type="button" class="trend-save" data-trend-ws-action="confirm-save">저장 후 닫기</button><button type="button" data-trend-ws-action="confirm-discard">저장하지 않고 닫기</button><button type="button" data-trend-ws-action="confirm-cancel">계속 편집</button></div></div></div>`:'');
}
function trendWorkspaceLegend(detail,analysis,asset,scale){
  const meta=TREND_ASSET_META[detail.asset_id]||{},chips=(analysis.lines||[]).map(line=>{const role=line.role||line.side,color=line.slot?TREND_REPRESENTATIVE_COLORS[line.slot]:role==='support'?'#247d78':'#bd5a20';return `<span><i style="background:${color}"></i>${esc(line.slot?trendRepresentativeName(line):role==='support'?'지지':'저항')}</span>`;}).join('');
  return `<div class="trend-ws-legend" data-trend-ws-legend><div><strong>${esc(asset?.label||'')}</strong><span>${esc(meta.ticker||detail.asset_id)} · 1D${scale==='log'?' · 로그':''}</span><span class="trend-ws-ohlc" data-trend-ws-ohlc></span>${detail.status==='unverified_display'?'<em>개인 연구 시세 · 참고선</em>':''}</div>${chips?`<div class="trend-ws-chips">${chips}</div>`:''}</div>`;
}
function trendWorkspaceSelectionBar(){
  const button=(action,value,label,content,extra='')=>`<button type="button" data-trend-manual-action="${action}"${value===null?'':` data-trend-manual-value="${value}"`} title="${esc(label)}" aria-label="${esc(label)}"${extra}>${content}</button>`;
  const colors=['#7056a3','#bb4c1c','#c98a14','#2f8a57','#2f6fb2','#34738d','#1f2421','#8a8f86'];
  return `<div class="trend-ws-float" data-trend-selection role="toolbar" aria-label="선택한 선" hidden>${colors.map(color=>button('set-color',color,'색 '+color,'',` class="trend-swatch" style="--swatch:${color}"`)).join('')}<span class="trend-ws-sep" aria-hidden="true"></span>${[1,2,3].map(width=>button('set-width',width,'두께 '+width+'px',`<i style="height:${width}px"></i>`,' class="trend-width"')).join('')}<span class="trend-ws-sep" aria-hidden="true"></span>${button('set-dash','solid','실선','실선')}${button('set-dash','dash','파선','파선')}${button('set-dash','dot','점선','점선')}<span class="trend-ws-sep" aria-hidden="true"></span>${button('set-extension','none','연장 없음','선분')}${button('set-extension','right','오른쪽 연장','→')}${button('set-extension','both','양쪽 연장','↔')}<span class="trend-ws-sep" aria-hidden="true"></span>${button('lock',null,'잠금/해제',trendIcon('lock'))}${button('hide',null,'숨김/표시',trendIcon('eye'))}${button('clone',null,'복제','복제')}${button('settings',null,'선 설정','설정')}${button('delete',null,'삭제 · Delete',trendIcon('trash'))}</div>`;
}
function trendWorkspacePending(ws,error=null){
  const id=ws.pendingAsset||ws.assetId,label=TREND_ASSETS.find(row=>row[0]===id)?.[1]||id;
  return `<header class="trend-ws-top"><div class="trend-ws-top-scroll">${trendWorkspaceSymbol(ws,label,TREND_ASSET_META[id]?.ticker)}</div><div class="trend-ws-actions"><button type="button" class="trend-ws-icon trend-ws-close" data-trend-ws-action="close" title="닫기 · Esc" aria-label="닫기">${trendIcon('close')}</button></div></header><div class="trend-ws-pending" role="status"><span aria-hidden="true">${error?'—':'⋯'}</span><strong>${esc(error?'차트를 표시하지 못했습니다':label+' 시세를 확인하고 있습니다')}</strong><p>${esc(error||ws.pendingMessage||'')}</p></div>`;
}
// Crosshair follows the pointer price (TradingView), with axis labels and an OHLC legend.
function bindTrendWorkspaceChart(host,detail,m,asset){
  const svg=host.querySelector('svg[data-trend-plot]'),cross=svg?.querySelector('[data-trend-cross]'),horizontal=svg?.querySelector('[data-trend-cross-price]'),ylabel=svg?.querySelector('[data-trend-ws-ylabel]'),xlabel=svg?.querySelector('[data-trend-ws-xlabel]'),ohlc=host.querySelector('[data-trend-ws-ohlc]');if(!svg||!cross||!horizontal||!ylabel||!xlabel)return;
  const position=new Map(detail.bars.map((bar,i)=>[bar.session_index,i])),visible=new Map(m.bars.map(bar=>[bar.session_index,bar])),sessions=new Map(trendManualSessions(detail,m.analysis).map(row=>[row.index,row.session])),format=value=>trendAxisPrice(value,asset);
  const legend=bar=>{if(!ohlc)return;const row=bar||detail.bars.at(-1),i=position.get(row.session_index),previous=i>0?detail.bars[i-1].close:null,change=previous?(row.close/previous-1)*100:null;ohlc.innerHTML=`<span>${esc(row.session||row.session_date)}</span> 시 <b>${esc(format(row.open))}</b> 고 <b>${esc(format(row.high))}</b> 저 <b>${esc(format(row.low))}</b> 종 <b>${esc(format(row.close))}</b>${change===null?'':` <b class="${change>=0?'is-up':'is-down'}">${change>=0?'+':''}${change.toFixed(2)}%</b>`}`;};
  const hide=()=>{for(const node of [cross,horizontal,ylabel,xlabel])node.setAttribute('visibility','hidden');legend(null);};
  const show=event=>{
    const bounds=svg.getBoundingClientRect();if(!bounds.width||!bounds.height)return;const x=(event.clientX-bounds.left)/bounds.width*m.W,y=(event.clientY-bounds.top)/bounds.height*m.H;
    if(x<m.L||x>m.W-m.R||y<m.T||y>m.H-m.B){hide();return;}
    const index=Math.round(Math.max(m.first,Math.min(m.end,m.first+(x-m.L)/(m.W-m.L-m.R)*(m.end-m.first)))),cx=m.x(index),price=trendManualPriceAt(m,y,m.scale),label=sessions.get(index)||'',left=Math.max(m.L,Math.min(m.W-m.R-80,cx-40));
    cross.setAttribute('x1',cx);cross.setAttribute('x2',cx);horizontal.setAttribute('y1',y);horizontal.setAttribute('y2',y);
    ylabel.querySelector('rect').setAttribute('y',y-9);const text=ylabel.querySelector('text');text.setAttribute('y',y+4);text.textContent=Number.isFinite(price)&&price>0?format(price):'';
    xlabel.querySelector('rect').setAttribute('x',left);const date=xlabel.querySelector('text');date.setAttribute('x',left+40);date.textContent=label;
    for(const node of [cross,horizontal,ylabel])node.setAttribute('visibility','visible');xlabel.setAttribute('visibility',label?'visible':'hidden');
    const bar=visible.get(index);if(bar)legend(bar);
  };
  svg.addEventListener('pointermove',show);svg.addEventListener('pointerdown',show);svg.addEventListener('pointerleave',hide);legend(null);
}
function drawTrendWorkspace(host,detail,analysis,baseBars,bars,asset,scale,version,state,ws,maximum,restoreName){
  const manual=trendManualState(detail.asset_id),narrow=(globalThis.innerWidth||1280)<760,date=bar=>bar.session||bar.session_date;
  const frameKey=[detail.asset_id,scale,ws.family,ws.hideAuto,ws.panelOpen,ws.helpOpen,ws.assetMenu,ws.confirmClose,narrow].join('|');
  if(host._trendWsFrameKey!==frameKey||!host.querySelector?.('[data-trend-ws-stage]')){host.innerHTML=trendWorkspaceFrame(detail,asset,scale,ws);host._trendWsFrameKey=frameKey;}
  const stage=host.querySelector('[data-trend-ws-stage]'),width=stage?.clientWidth||Math.max(330,(host.clientWidth||1200)-48-(ws.panelOpen&&!narrow?300:0)),height=stage?.clientHeight||Math.max(260,(host.clientHeight||720)-96);
  const m=trendPlotModel(detail,analysis,bars,scale,width,{axis:'right',height,yRange:state.yRange});
  const domain=[baseBars[0].session_index,Math.max(baseBars.at(-1).session_index+(analysis.representative||analysis.critical?0:1),m.end,analysis.projection_sessions?.at(-1)?.index??0)];
  if(state.xRange){[m.first,m.end]=state.xRange;m.x=index=>m.L+(index-m.first)/(m.end-m.first)*(m.W-m.L-m.R);}
  m.manualState=manual;m.manualDetail=detail;m.manualLines=manual.lines.filter(l=>!l.hidden).map(l=>trendManualGeometry(l,detail,analysis,scale,m)).filter(Boolean);
  if(stage)stage.innerHTML=trendWorkspaceLegend(detail,analysis,asset,scale)+trendSvg(detail,m,asset,'workspace')+trendWorkspaceSelectionBar();
  host._trendWorkspace=ws;bindTrendWorkspaceChart(host,detail,m,asset);bindTrendManual(host,detail,m,asset,scale);
  if(restoreName&&/^[a-z_]+$/.test(restoreName))host.querySelector('[data-trend-manual-form] [name="'+restoreName+'"]')?.focus();
  const repaint=()=>{if(host._trendWsFrameRequest)return;const run=()=>{host._trendWsFrameRequest=0;if(host.isConnected!==false&&TREND_ZOOM?.ws===ws)drawTrendInteractiveChart(host,detail,analysis,baseBars,asset,scale,version,state,()=>{},ws);};host._trendWsFrameRequest=globalThis.requestAnimationFrame?requestAnimationFrame(run):(run(),0);};
  const limit=()=>baseBars.length-bars.length,clampOffset=value=>Math.max(0,Math.min(limit(),Math.round(value)));
  const windowRange=()=>state.xRange||[m.first,m.end];
  const validRange=range=>range.every(Number.isFinite)&&range[1]>range[0]&&(scale!=='log'||range.every(value=>Math.exp(value)>0&&Number.isFinite(Math.exp(value))));
  const boundedWindow=(start,span)=>{const size=Math.min(domain[1]-domain[0],span),first=Math.max(domain[0],Math.min(domain[1]-size,start));return [first,first+size];};
  const priceFrame=range=>trendPlotFrame(m.W,{axis:'right',height:m.H},m.H,scale==='log'?Math.exp(range[1]):range[1]);
  const zoom=(factor,ratio=.5,point=null)=>{
    const target=Math.max(1,Math.min(maximum,factor));if(!Number.isFinite(target)||Math.abs(target-state.factor)<1e-12)return;
    const current=windowRange(),range=state.yRange||m.range,frame=priceFrame(range),clamp=value=>Math.max(0,Math.min(1,value));
    const rx=point?clamp((point.x-frame.L)/(frame.W-frame.L-frame.R)):clamp(ratio),anchor=current[0]+rx*(current[1]-current[0]),step=target/state.factor;
    let nextRange=range;
    if(point&&point.y>=frame.T&&point.y<=frame.H-frame.B){const ry=clamp((point.y-frame.T)/(frame.H-frame.T-frame.B)),price=range[1]-ry*(range[1]-range[0]),span=(range[1]-range[0])/step;nextRange=[price-(1-ry)*span,price+ry*span];if(!validRange(nextRange))return;}
    const nextFrame=priceFrame(nextRange),nextRatio=point?clamp((point.x-nextFrame.L)/(nextFrame.W-nextFrame.L-nextFrame.R)):rx;
    const span=target===1?domain[1]-domain[0]:(current[1]-current[0])/step;
    state.xRange=boundedWindow(anchor-nextRatio*span,span);state.factor=target;state.heldCount=null;
    if(nextRange!==range)state.yRange=nextRange;ws.range=null;repaint();
  };
  const panWindow=(first,range=null)=>{const current=windowRange();state.xRange=boundedWindow(first,current[1]-current[0]);if(range)state.yRange=range;ws.range=null;repaint();};
  const pan=delta=>{if(state.xRange){panWindow(state.xRange[0]+delta);return;}state.heldCount=bars.length;state.offset=clampOffset((state.offset??limit())+delta);ws.range=null;repaint();};
  const panTo=(offset,range=null)=>{state.heldCount=bars.length;state.offset=clampOffset(offset);if(range)state.yRange=range;ws.range=null;repaint();};
  const setRange=range=>{if(range&&!validRange(range))return;state.yRange=range;repaint();};
  const scalePrice=(factor,ratio=.5)=>{const [low,high]=state.yRange||m.range,anchor=low+ratio*(high-low),span=(high-low)*factor;setRange([anchor-ratio*span,anchor+(1-ratio)*span]);};
  const preset=label=>{const row=TREND_RANGE_PRESETS.find(item=>item[0]===label);if(!row)return;const crypto=detail.asset?.kind==='crypto'||detail.asset_id==='bitcoin',count=row[1]===null?baseBars.length:Math.min(baseBars.length,Math.max(20,crypto?row[2]:row[1]));state.heldCount=count;state.factor=baseBars.length/count;state.offset=null;state.yRange=null;state.xRange=null;ws.range=label;repaint();};
  const goto=value=>{if(!trendManualDate(value))return;let position=baseBars.findIndex(bar=>date(bar)>=value);if(position<0)position=baseBars.length-1;state.heldCount=bars.length;state.offset=clampOffset(position-Math.floor(bars.length/2));state.xRange=null;ws.range=null;repaint();};
  host._trendNavigation={m,zoom,pan,panTo,panWindow,setRange,scalePrice,preset,goto,repaint,state,baseBars,bars};
  host.querySelectorAll?.('[data-trend-tool]').forEach(button=>{const action=button.dataset.trendTool;button.disabled=action==='in'&&state.factor>=maximum||action==='out'&&(state.factor<=1||(state.xRange?state.xRange[1]-state.xRange[0]>=domain[1]-domain[0]-1e-9:bars.length>=baseBars.length))||action==='left'&&(state.xRange?state.xRange[0]<=domain[0]+1e-9:state.offset<=0)||action==='right'&&(state.xRange?state.xRange[1]>=domain[1]-1e-9:state.offset>=limit());if(action==='range')button.setAttribute('aria-pressed',String(ws.range===button.dataset.trendRange));button.onclick=()=>{if(action==='range'){preset(button.dataset.trendRange);return;}if(action==='in'||action==='out'){zoom(state.factor*(action==='in'?1.5:1/1.5));return;}if(action==='reset'){ws.resetView();return;}pan(Math.round(bars.length*.4)*(action==='left'?-1:1));};});
  const span=host.querySelector('[data-trend-ws-span]');if(span)span.textContent=`${date(bars[0])} — ${date(bars.at(-1))} · ${bars.length.toLocaleString('ko-KR')}봉`;
  const auto=host.querySelector('[data-trend-ws-action="auto"]');auto?.setAttribute('aria-pressed',String(!state.yRange));
  const goto_=host.querySelector('[data-trend-ws-goto]');if(goto_&&globalThis.document?.activeElement!==goto_){goto_.min=date(baseBars[0]);goto_.max=date(baseBars.at(-1));}
  if(host._trendWsNavBound||!host.addEventListener)return;host._trendWsNavBound=true;
  const local=event=>{const nav=host._trendNavigation,svg=host.querySelector('svg[data-trend-plot]'),bounds=svg?.getBoundingClientRect();if(!nav?.zoom||!bounds?.width||!bounds.height)return null;return {nav,bounds,x:(event.clientX-bounds.left)/bounds.width*nav.m.W,y:(event.clientY-bounds.top)/bounds.height*nav.m.H};};
  host.addEventListener('wheel',event=>{if(!event.target.closest?.('svg[data-trend-plot]'))return;const p=local(event);if(!p)return;event.preventDefault();const {nav}=p,plot=nav.m;
    const unitY=event.deltaMode===1?16:event.deltaMode===2?(plot.H-plot.T-plot.B)/plot.H*p.bounds.height:1,unitX=event.deltaMode===2?(plot.W-plot.L-plot.R)/plot.W*p.bounds.width:unitY;
    const dx=event.deltaX*unitX,dy=event.deltaY*unitY;if(!Number.isFinite(dx)||!Number.isFinite(dy)||!dx&&!dy)return;
    const delta=Math.max(-160,Math.min(160,dy));
    if(p.x>plot.W-plot.R){nav.scalePrice(Math.exp(delta*.0015),Math.max(0,Math.min(1,(plot.H-plot.B-p.y)/(plot.H-plot.T-plot.B))));return;}
    if(event.shiftKey||Math.abs(dx)>Math.abs(dy)){const move=event.shiftKey?dy||dx:dx;nav.pan(Math.round(move/Math.max(1,plot.W-plot.L-plot.R)*nav.bars.length)||Math.sign(move));return;}
    nav.zoom(nav.state.factor*Math.exp(-delta*.002),.5,{x:p.x,y:p.y});},{passive:false});
  const pointers=new Map();let gesture=null;
  const clearGesture=()=>{gesture=null;delete host.dataset.trendGesture;};
  host.addEventListener('pointerdown',event=>{if(event.button!==0&&event.pointerType!=='touch'||!event.target.closest?.('svg[data-trend-plot]'))return;const p=local(event);if(!p)return;const {nav}=p,plot=nav.m;
    // Suppress native text selection before the SVG is repainted during panning.
    event.preventDefault();event.target.closest('svg[data-trend-plot]')?.focus?.({preventScroll:true});
    pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});if(event.isTrusted)host.setPointerCapture?.(event.pointerId);
    if(pointers.size===2){const values=[...pointers.values()];gesture={kind:'pinch',distance:Math.hypot(values[0].x-values[1].x,values[0].y-values[1].y),factor:nav.state.factor};host.dataset.trendGesture='plot';return;}
    gesture={kind:p.x>plot.W-plot.R?'price':p.y>plot.H-plot.B?'time':'plot',id:event.pointerId,x:event.clientX,y:event.clientY,offset:nav.state.offset,factor:nav.state.factor,range:(nav.state.yRange||plot.range).slice(),plotWidth:Math.max(1,(plot.W-plot.L-plot.R)/plot.W*p.bounds.width),plotHeight:Math.max(1,(plot.H-plot.T-plot.B)/plot.H*p.bounds.height),count:nav.bars.length,first:plot.first,span:plot.end-plot.first,moved:false};host.dataset.trendGesture=gesture.kind;});
  host.addEventListener('pointermove',event=>{if(!pointers.has(event.pointerId))return;pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});const nav=host._trendNavigation;if(!gesture||!nav?.zoom)return;
    if(gesture.kind==='pinch'){if(pointers.size===2){const values=[...pointers.values()];event.preventDefault();nav.zoom(gesture.factor*Math.hypot(values[0].x-values[1].x,values[0].y-values[1].y)/Math.max(1,gesture.distance));}return;}
    if(gesture.id!==event.pointerId)return;const dx=event.clientX-gesture.x,dy=event.clientY-gesture.y;if(!gesture.moved&&Math.hypot(dx,dy)<5)return;gesture.moved=true;event.preventDefault();
    const [low,high]=gesture.range;
    if(gesture.kind==='price'){const half=(high-low)/2*Math.exp(dy*.006),mid=(low+high)/2;nav.setRange([mid-half,mid+half]);return;}
    if(gesture.kind==='time'){nav.zoom(gesture.factor*Math.exp(-dx*.006),1);return;}
    const shift=dy/gesture.plotHeight*(high-low),range=nav.state.yRange||Math.abs(dy)>12?[low+shift,high+shift]:null;if(nav.state.xRange)nav.panWindow(gesture.first-dx/gesture.plotWidth*gesture.span,range);else nav.panTo(gesture.offset-dx/gesture.plotWidth*gesture.count,range);});
  const release=event=>{if(!pointers.delete(event.pointerId))return;if(gesture?.kind==='pinch'&&pointers.size<2||gesture?.id===event.pointerId)clearGesture();if(host.hasPointerCapture?.(event.pointerId))host.releasePointerCapture(event.pointerId);};
  host.addEventListener('pointerup',release);host.addEventListener('pointercancel',release);host.addEventListener('lostpointercapture',release);
  const cancel=()=>{for(const id of [...pointers.keys()])release({pointerId:id});clearGesture();};
  window.addEventListener('blur',cancel);host._trendWsDisposeNavigation=()=>{cancel();window.removeEventListener('blur',cancel);};
  host.addEventListener('dblclick',event=>{const p=local(event);if(p&&p.x>p.nav.m.W-p.nav.m.R)p.nav.setRange(null);});
  host.addEventListener('click',event=>{const w=host._trendWorkspace;if(!w)return;if(w.assetMenu&&!event.target.closest?.('.trend-ws-symbol')){w.assetMenu=false;w.render();}const target=event.target.closest?.('[data-trend-ws-action],[data-trend-ws-family],[data-trend-ws-asset]');if(!target)return;
    if(target.dataset.trendWsAsset){w.switchAsset(target.dataset.trendWsAsset);return;}if(target.dataset.trendWsFamily){w.setFamily(target.dataset.trendWsFamily);return;}w.command(target.dataset.trendWsAction);});
  host.addEventListener('change',event=>{if(event.target.matches?.('[data-trend-ws-goto]'))host._trendNavigation?.goto?.(event.target.value);});
}
function trendWorkspaceSnapshot(host,label){
  const svg=host.querySelector('svg[data-trend-plot]'),box=svg?.viewBox?.baseVal;if(!svg||!box?.width||!globalThis.XMLSerializer)return;
  const clone=svg.cloneNode(true),namespace='http://www.w3.org/2000/svg',style=document.createElementNS(namespace,'style'),title=document.createElementNS(namespace,'text');
  clone.setAttribute('xmlns',namespace);clone.setAttribute('width',box.width);clone.setAttribute('height',box.height);clone.querySelectorAll('[visibility="hidden"],[data-trend-overlay],[data-trend-price-axis],[data-trend-time-axis]').forEach(node=>node.remove());
  style.textContent='text{font:11px ui-monospace,Menlo,Consolas,monospace}text:not([fill]):not([style]){fill:#6f6a60}';clone.insertBefore(style,clone.firstChild);
  title.setAttribute('x','8');title.setAttribute('y','18');title.setAttribute('style','fill:#1f2421;font-weight:700');title.textContent=label;clone.appendChild(title);
  const image=new Image(),scale=2;image.onload=()=>{const canvas=document.createElement('canvas');canvas.width=box.width*scale;canvas.height=box.height*scale;const context=canvas.getContext('2d');context.fillStyle='#fff';context.fillRect(0,0,canvas.width,canvas.height);context.scale(scale,scale);context.drawImage(image,0,0);canvas.toBlob(blob=>{if(!blob)return;const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=label.replace(/[^\w가-힣.-]+/g,'-')+'.png';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);},'image/png');};
  image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(clone));
}
function openTrendWorkspace(context,trigger=null,options={}){
  if(!context||!globalThis.document?.body)return null;
  closeTrendZoom(false);
  const label=context.asset?.label||context.assetId,layer=el(`<div class="trend-ws-layer" data-trend-zoom><section class="trend-ws" role="dialog" aria-modal="true" tabindex="-1" aria-label="${esc(label)} 차트"><div class="trend-ws-host" data-trend-zoom-chart></div></section></div>`);
  document.body.appendChild(layer);const inert=[...document.body.children].filter(node=>node!==layer).map(node=>[node,node.inert]);for(const [node] of inert)node.inert=true;document.body.classList.add('trend-zoom-open');
  const host=layer.querySelector('[data-trend-zoom-chart]'),date=bar=>bar.session||bar.session_date;
  const ws={context,assetId:context.assetId,scale:context.scale||'linear',family:context.family??null,hideAuto:false,panelOpen:(globalThis.innerWidth||1280)>=1180,helpOpen:false,assetMenu:false,confirmClose:false,pendingAsset:null,pendingMessage:null,range:null};
  const prime=()=>{ws.state={factor:1,offset:null,heldCount:null,maxFactor:Infinity,yRange:null};const bars=ws.context.initialBars;ws.home=bars?.length?{start:date(bars[0]),end:date(bars.at(-1))}:null;ws.pendingWindow=ws.home;ws.range=null;};
  prime();
  ws.render=()=>{
    if(!host.isConnected)return;
    if(ws.pendingAsset){host._trendWsFrameKey=null;host.innerHTML=trendWorkspacePending(ws);return;}
    let built;try{built=ws.context.build(ws.scale,ws.family||'all');}catch(error){host._trendWsFrameKey=null;host.innerHTML=trendWorkspacePending(ws,String(error.message||error));return;}
    const base=built.source.bars;
    if(ws.pendingWindow){const first=base.findIndex(bar=>date(bar)>=ws.pendingWindow.start),last=base.findLastIndex(bar=>date(bar)<=ws.pendingWindow.end);if(first>=0&&last>=first){ws.state.heldCount=Math.max(20,last-first+1);ws.state.factor=base.length/ws.state.heldCount;ws.state.offset=last+1>=base.length?null:first;}ws.pendingWindow=null;}
    drawTrendInteractiveChart(host,built.source,ws.hideAuto?{...built.analysis,lines:[]}:built.analysis,base,ws.context.asset,ws.scale,ws.context.version||'workspace',ws.state,()=>{},ws);
  };
  ws.openPanel=()=>{if(!ws.panelOpen){ws.panelOpen=true;ws.render();}};
  ws.resetView=()=>{ws.state.factor=1;ws.state.offset=null;ws.state.heldCount=null;ws.state.yRange=null;ws.state.xRange=null;ws.pendingWindow=ws.home;ws.range=null;ws.render();};
  ws.setScale=scale=>{if(ws.context.fixedScale||!['linear','log'].includes(scale)||scale===ws.scale)return;ws.scale=scale;ws.state.yRange=null;ws.render();};
  ws.setFamily=value=>{if(value==='none')ws.hideAuto=!ws.hideAuto;else{ws.hideAuto=false;ws.family=value;}ws.render();};
  ws.switchAsset=id=>{ws.assetMenu=false;if(id===ws.assetId&&!ws.pendingAsset){ws.render();return;}if(!TREND_VISIBLE_ASSETS.some(row=>row[0]===id))return;ws.pendingAsset=id;ws.pendingMessage=null;ws.render();globalThis.location.hash='#trendlines/'+id;};
  ws.showPending=message=>{ws.pendingMessage=message;if(ws.pendingAsset)ws.render();};
  ws.attach=next=>{if(ws.pendingAsset&&next.assetId!==ws.pendingAsset)return;const switched=next.assetId!==ws.assetId;ws.context=next;ws.pendingAsset=null;if(switched){ws.assetId=next.assetId;if(next.fixedScale)ws.scale=next.scale;prime();trendManualState(ws.assetId).listOpen=true;host._trendWsFrameKey=null;}ws.render();};
  ws.requestClose=()=>{const manual=TREND_MANUAL_STATES.get(ws.assetId);if(!ws.pendingAsset&&manual?.saveStatus==='dirty'&&!ws.confirmClose){ws.confirmClose=true;ws.render();host.querySelector('[data-trend-ws-action="confirm-save"]')?.focus();return;}closeTrendZoom(true);};
  ws.command=async name=>{
    if(name==='assets'){ws.assetMenu=!ws.assetMenu;ws.render();return;}
    if(name==='linear'||name==='log'){ws.setScale(name);return;}
    if(name==='panel'){ws.panelOpen=!ws.panelOpen;ws.render();return;}
    if(name==='help'){ws.helpOpen=!ws.helpOpen;ws.render();return;}
    if(name==='auto'){ws.state.yRange=null;ws.render();return;}
    if(name==='snapshot'){trendWorkspaceSnapshot(host,(ws.context.asset?.label||ws.assetId)+' '+(new Date().toISOString().slice(0,10)));return;}
    if(name==='fullscreen'){if(document.fullscreenElement)document.exitFullscreen?.()?.catch?.(()=>{});else layer.requestFullscreen?.()?.catch?.(()=>{});return;}
    if(name==='close'){ws.requestClose();return;}
    if(name==='confirm-cancel'){ws.confirmClose=false;ws.render();return;}
    if(name==='confirm-discard'){closeTrendZoom(true);return;}
    if(name==='confirm-save'){const manual=trendManualState(ws.assetId);ws.confirmClose=false;ws.render();if(await trendManualSave(manual,manual.commitForm))closeTrendZoom(true);}
  };
  const key=event=>{
    const target=event.target,input=target?.closest?.('input,textarea,select,[contenteditable="true"]'),mod=event.ctrlKey||event.metaKey,letter=value=>String(event.key||'').toLowerCase()===value||event.code==='Key'+value.toUpperCase();
    if(event.key==='Escape'){event.preventDefault();if(ws.confirmClose){ws.command('confirm-cancel');return;}if(ws.helpOpen||ws.assetMenu){ws.helpOpen=false;ws.assetMenu=false;ws.render();return;}ws.requestClose();return;}
    if(event.key==='Tab'){const nodes=[...layer.querySelectorAll('button:not([disabled]):not([tabindex="-1"]),svg[tabindex="0"],input:not([disabled]),select:not([disabled]),summary')].filter(node=>node.getClientRects().length),first=nodes[0],last=nodes.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}return;}
    if(input)return;const nav=host._trendNavigation;if(!nav?.zoom)return;
    if(event.altKey&&!mod&&letter('r')){event.preventDefault();ws.resetView();return;}
    if(event.altKey&&!mod&&letter('l')){event.preventDefault();ws.setScale(ws.scale==='log'?'linear':'log');return;}
    if(event.altKey&&!mod&&letter('g')){event.preventDefault();host.querySelector('[data-trend-ws-goto]')?.focus();return;}
    if(event.key==='?'){event.preventDefault();ws.command('help');return;}
    if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();nav.pan((event.key==='ArrowLeft'?-1:1)*(mod?Math.max(2,Math.round(nav.bars.length*.2)):1));return;}
    if(mod&&(event.key==='ArrowUp'||event.key==='ArrowDown')){event.preventDefault();nav.zoom(nav.state.factor*(event.key==='ArrowUp'?1.25:.8));}
  };
  const resize=()=>{if(ws.resizeFrame)return;const run=()=>{ws.resizeFrame=0;host._trendWsFrameKey=null;ws.render();};ws.resizeFrame=globalThis.requestAnimationFrame?requestAnimationFrame(run):(run(),0);};
  TREND_ZOOM={layer,host,trigger,triggerSelector:`[data-trend-${context.version||'representative'}-chart] [data-trend-tool="expand"]`,inert,key,resize,ws};
  window.addEventListener('keydown',key);window.addEventListener('resize',resize);document.addEventListener?.('fullscreenchange',resize);
  trendManualState(ws.assetId).listOpen=true;ws.render();
  if(options.action&&TREND_TOOL_ACTIONS[options.action])host._trendManual?.action(options.action);
  layer.querySelector('.trend-ws')?.focus?.();
  return ws;
}
let TRENDLINES_RESIZE=null;
function trendCriticalInsights(detail,analysis,asset){
  const last=detail.bars.at(-1),reference=analysis.critical_reference||{price:last.close,date:last.session},lines=analysis.lines;
  return `<section class="trend-insights"><div class="trend-insight-heading"><h3>핵심 지지·저항</h3><span>${esc(reference.date)} · 확정 종가 기준</span></div><div class="trend-insight-grid">${[['support','지지'],['resistance','저항']].map(([role,title])=>{const line=lines.find(line=>line.role===role),distance=line?(line.current_price/reference.price-1)*100:null;return `<article data-trend-insight="${role==='support'?'down':'up'}"><span>${title}</span>${line?`<strong data-trend-border="${esc(line.line_id)}">${esc(trendPrice(line.current_price,asset))}</strong><p>${distance>0?'+':''}${distance.toFixed(2)}% <small>종가 대비</small></p><small>${line.kind==='horizontal_zone'?'수평 가격대':line.direction==='rising'?'상승 빗각선':'하락 빗각선'} · 독립 접촉 ${line.contact_count}회</small>`:'<strong>—</strong><p>확인된 경계 없음</p>'}</article>`;}).join('')}</div><p class="trend-insight-note">3회 이상 독립 접촉 · 최근 63세션 접촉 · 종가와 4 ATR·20% 이내. 거리 기준은 반등 확률을 뜻하지 않습니다.</p></section>`;
}
function trendCriticalDetails(analysis,asset){
  const view=analysis.critical_view,selected=analysis.lines.map(line=>`<p>${line.role==='support'?'지지':'저항'} · ${line.kind==='horizontal_zone'?'수평 가격대':'빗각선'} · ${esc(line.first_anchor.session)}부터 · ${line.contact_count}회 접촉 · ${esc(trendPrice(line.current_price,asset))}${line.kind==='horizontal_zone'?` · 범위 ${esc(trendPrice(line.zone_low,asset))}–${esc(trendPrice(line.zone_high,asset))}`:''}</p>`).join('');
  if(!view)return '<p>핵심 경계 검수 자료를 확인하고 있습니다. 일봉을 먼저 표시합니다.</p>';
  const labels={fewer_than_three_independent_confirmed_contacts:'독립 접촉 3회 미만',contact_older_than_63_sessions:'최근 접촉 없음',nonpositive_or_invalid_current_projection:'현재 경계 가격 미산출',original_role_on_wrong_side_of_final_close:'현재 지지·저항 역할 불일치',latest_contiguous_atr14_unavailable:'연속 일봉 부족',distance_exceeds_four_atr:'종가에서 4 ATR 초과',distance_exceeds_twenty_percent:'종가에서 20% 초과',original_role_not_reestablished:'종가 이탈 후 역할 미확인',overlaps_nearer_representative_within_half_atr:'겹치는 경계',one_boundary_per_role_display_limit:'더 가까운 경계를 표시'};
  return selected+`<p>전체 후보 ${Number(view.candidate_count||0).toLocaleString('ko-KR')}개 검수 · 기준 통과 ${Number(view.eligible_count||0).toLocaleString('ko-KR')}개</p>`+Object.entries(view.rejection_counts||{}).map(([reason,count])=>`<p>${esc(labels[reason]||'경계 검수 제외')} · ${count}개</p>`).join('');
}
function renderCriticalTrendlinePage(initial={},loadState=null,localSession=null){
  if(TREND_ZOOM)closeTrendZoom(false);
  if(localSession&&TRENDLINES_RESIZE){TRENDLINES_RESIZE.disconnect();TRENDLINES_RESIZE=null;}
  const assetId=initial?.asset||'sk-hynix',projection=DATA?.trendlines||{},officialAsset=projection.assets?.find(row=>row.asset_id===assetId),localDetail=TREND_PRIVATE_DETAILS.get(assetId);
  let detail=localDetail||projection.details?.[assetId],validationError=null;
  if(detail&&['ready','stale','unverified_display'].includes(detail.status)){try{trendValidateDetail(detail);}catch(error){validationError=error;detail=null;}}
  const asset=localDetail&&detail?{...officialAsset,asset_id:assetId,label:TREND_ASSETS.find(row=>row[0]===assetId)?.[1],currency:detail.asset.currency,price_unit:detail.asset.unit,status:'unverified_display',last_session:detail.observation_through}:officialAsset;
  if(localDetail&&detail)loadState=null;
  const nav=TREND_VISIBLE_ASSETS.map(([id,label])=>`<a href="#trendlines/${id}"${id===assetId?' aria-current="page"':''}>${esc(label)}</a>`).join(''),fixture=detail?.fixture_only===true?'<p class="trend-fixture" role="alert">검토용 가상 시세 · 실제 시장 분석이 아닙니다</p>':'';
  const root=el(`<div class="trend-page"><header class="trend-heading"><p class="eyebrow">상·하방 추세선 · 03</p><h1>상·하방 추세선</h1></header><nav class="trend-assets" aria-label="추세선 자산 선택">${nav}</nav>${fixture}<section class="trend-body"><p class="trend-update-status" data-trend-local-message role="status"></p><div class="trend-content"></div></section></div>`),body=root.querySelector('.trend-content');
  const held=!asset||!['ready','stale','unverified_display'].includes(asset.status)||!detail||!['ready','stale','unverified_display'].includes(detail.status);
  if(loadState||held){const invalid=validationError||loadState?.error,phase=invalid?'invalid':Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId)?'checking':'idle';body.innerHTML=`<div class="trend-empty" data-trend-empty role="status">${trendEmptyMarkup(assetId,phase,invalid?'가격 기준을 확인한 뒤 표시합니다.':null)}</div>`;mount(root);if(Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId))bindTrendLocalConnection(root,initial,localSession);return;}
  const previousView=TREND_VIEW_OPTIONS.get(assetId);let period=previousView?.period||63,scale=previousView?.scale||'linear',direction=previousView?.direction||'all',fullScope=previousView?.fullScope||'anchors';
  const reference=trendReference(detail),delayed=asset.status==='stale'||detail.quality?.stale,legend=`<div class="trend-explanation"><div class="trend-legend"><span><i class="trend-support"></i>지지</span><span><i class="trend-resistance"></i>저항</span><span><i class="trend-broken"></i>미래 연장</span></div><p>각 차트는 현재 의미가 확인된 지지·저항을 최대 하나씩 표시합니다. 선 위에서 해당 날짜의 경계 가격을 확인하세요.</p></div>`;
  body.innerHTML=`<div class="trend-title"><div><h2>${esc(asset.label)}</h2><span>일봉 ${esc(detail.observation_through||asset.last_session)} 기준${delayed?' · 갱신 지연':''}</span></div><div class="trend-price"><strong>${esc(trendPrice(reference.price,asset))}</strong><span>${esc(reference.date)}${reference.time?' '+esc(reference.time):''} · ${reference.kind}${reference.quote?' · 지연 시세':''}</span></div></div><div class="trend-controls trend-axis-controls"><span>두 차트 공통 축</span><div role="group" aria-label="가격 축"><button type="button" data-trend-scale="linear" aria-pressed="true">선형</button><button type="button" data-trend-scale="log" aria-pressed="false">로그</button></div></div><section class="trend-chart-section" data-trend-version="full"><div class="trend-chart-heading"><div><h3>전체 추세선</h3><p data-trend-full-coverage>확보된 전체 일봉을 확인하고 있습니다.</p></div><div class="trend-controls" role="group" aria-label="전체 추세선 표시 범위"><div>${[['anchors','핵심 구간'],['all','전체 기간']].map(([value,label])=>`<button type="button" data-trend-full-view="${value}" aria-pressed="${value===fullScope}">${label}</button>`).join('')}</div></div></div><div class="trend-chart" data-trend-full-chart></div>${legend}<div data-trend-full-insights></div><details class="trend-line-meta"><summary>경계 선정 세부</summary><div data-trend-full-line-details></div></details></section><section class="trend-chart-section" data-trend-version="current"><div class="trend-chart-heading"><div><h3>현재 상·하방 추세선</h3><p>선택한 기간의 핵심 지지·저항</p></div><div class="trend-controls" role="group" aria-label="추세선 기간"><div>${[[63,'3개월'],[252,'1년'],[756,'3년']].map(([value,label])=>`<button type="button" data-trend-period="${value}" aria-pressed="${value===63}">${label}</button>`).join('')}</div></div></div><div class="trend-controls trend-direction-controls" data-trend-direction-controls></div><div class="trend-chart" data-trend-current-chart></div>${legend}<div data-trend-insights></div><details class="trend-line-meta"><summary>경계 선정 세부</summary><div data-trend-line-details></div></details></section>${trendResearchMarkup(detail,asset)}`;
  mount(root);const session=Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId)?bindTrendLocalConnection(root,initial,localSession):null;
  const host=root.querySelector('[data-trend-current-chart]'),fullHost=root.querySelector('[data-trend-full-chart]'),insights=root.querySelector('[data-trend-insights]'),lineDetails=root.querySelector('[data-trend-line-details]');let drawnWidth=0,fullDrawnWidth=0;
  const stateFor=version=>{const key=assetId+':'+version;if(!TREND_CHART_VIEWS.has(key))TREND_CHART_VIEWS.set(key,{factor:1,offset:null});return TREND_CHART_VIEWS.get(key);};
  const paintFull=()=>{
    const full=TREND_FULL_DETAILS.get(assetId),coverage=root.querySelector('[data-trend-full-coverage]'),fullInsights=root.querySelector('[data-trend-full-insights]'),fullLines=root.querySelector('[data-trend-full-line-details]');fullDrawnWidth=fullHost.clientWidth;
    if(!full){coverage.textContent='확보된 전체 일봉';fullHost.innerHTML=trendFullEmptyMarkup(session?.fullPhase);fullInsights.innerHTML='';fullLines.innerHTML='';return;}
    const older=full.source_snapshot_id!==TREND_PRIVATE_DETAILS.get(assetId)?.snapshot_id,analysis=trendCriticalAnalysis(detail,full,'full',scale),bars=trendFullViewport(full,analysis,fullScope);
    root.querySelectorAll('[data-trend-full-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendFullView===fullScope)));
    coverage.textContent=`${bars[0].session} — ${full.observation_through} · ${bars.length.toLocaleString('ko-KR')}개 일봉${older?' · 기준 자료 유지':full.quality?.stale?' · 갱신 지연':''}`;
    fullInsights.innerHTML=trendCriticalInsights(full,analysis,asset);fullLines.innerHTML=trendCriticalDetails(analysis,asset);drawTrendInteractiveChart(fullHost,full,analysis,bars,asset,scale,'full',stateFor('full'));
  };
  const directionHost=root.querySelector('[data-trend-direction-controls]');directionHost.innerHTML=`<div role="group" aria-label="현재 추세선 기울기">${[['all','전체 경계'],['rising','상승선'],['falling','하락선']].map(([value,label])=>`<button type="button" data-trend-direction="${value}" aria-pressed="${value==='all'}">${label}</button>`).join('')}</div><span>기울기와 지지·저항 역할은 별도 기준</span>`;
  const paint=()=>{TREND_VIEW_OPTIONS.set(assetId,{period,scale,direction,fullScope});const original=trendCriticalAnalysis(detail,null,period,scale),analysis=direction==='all'?original:{...original,lines:original.lines.filter(line=>line.direction===direction)};drawnWidth=host.clientWidth;
    root.setAttribute?.('data-trend-core-snapshot',original.critical_view?TREND_CRITICAL_DETAILS.get(assetId).snapshot_id:'');
    root.querySelectorAll('[data-trend-period]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.trendPeriod)===period)));root.querySelectorAll('[data-trend-scale]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendScale===scale)));root.querySelectorAll('[data-trend-direction]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendDirection===direction)));
    insights.innerHTML=trendCriticalInsights(detail,analysis,asset);lineDetails.innerHTML=trendCriticalDetails(analysis,asset);drawTrendInteractiveChart(host,detail,analysis,detail.bars.slice(-period),asset,scale,'current',stateFor('current'));paintFull();
  };
  root.querySelectorAll('[data-trend-period]').forEach(button=>button.onclick=()=>{period=Number(button.dataset.trendPeriod);TREND_CHART_VIEWS.delete(assetId+':current');paint();});root.querySelectorAll('[data-trend-scale]').forEach(button=>button.onclick=()=>{scale=button.dataset.trendScale;paint();});root.querySelectorAll('[data-trend-direction]').forEach(button=>button.onclick=()=>{direction=button.dataset.trendDirection;paint();});root.querySelectorAll('[data-trend-full-view]').forEach(button=>button.onclick=()=>{fullScope=button.dataset.trendFullView;TREND_CHART_VIEWS.delete(assetId+':full');paint();});paint();
  if(session){session.fullMounted=true;session.onFullData=paintFull;session.onCriticalData=paint;Promise.resolve().then(()=>{refreshTrendFullSession(session);refreshTrendCriticalSession(session);});}
  if(globalThis.ResizeObserver){TRENDLINES_RESIZE=new ResizeObserver(()=>{if(!root.isConnected){TRENDLINES_RESIZE?.disconnect();TRENDLINES_RESIZE=null;return;}if(Math.abs(host.clientWidth-drawnWidth)>2||Math.abs(fullHost.clientWidth-fullDrawnWidth)>2)paint();});TRENDLINES_RESIZE.observe(host);TRENDLINES_RESIZE.observe(fullHost);}
}
function trendRepresentativeCards(analysis,asset,family='all'){
  const rows=analysis.representatives.length?analysis.representatives:TREND_REPRESENTATIVE_SLOTS.map(slot=>({slot,status:'hold'})),selected=rows.filter(line=>family==='all'||line.slot===family),reference=analysis.critical_reference;
  return `<section class="trend-representative-insights"><div class="trend-insight-heading"><h3>추세 인사이트</h3><span>${reference?esc(reference.date)+' · 확정 종가 기준':'확정 일봉 기준'}</span></div><div class="trend-representative-cards">${selected.map(line=>{const ready=line.status==='ready',priceReady=ready&&typeof line.current_price==='number'&&line.current_price>0,direction=line.direction==='rising'?'상승':line.direction==='falling'?'하락':'횡보',distance=priceReady&&reference?(line.current_price/reference.price-1)*100:null,period=ready?(line.kind==='regression'?`${line.fit.start_session} — ${line.fit.end_session}`:`${line.first_anchor.session} → ${line.second_anchor.session}`):'',description=!ready?(analysis.representative_body?'확정 일봉이 더 필요합니다.':'자료 확인 중'):line.kind==='regression'?(line.slot==='regression_200'?`${line.fit.n}개 종가의 회귀 방향`:`고저점 연결 대신 ${line.fit.n}일 회귀`):`${line.origin_role==='support'?'저점':'고점'} 연결 · ${line.contact_count}개 확정 기준점`;return `<article data-trend-representative-card="${esc(line.slot)}" style="--trend-slot:${TREND_REPRESENTATIVE_COLORS[line.slot]}"><div><span>${esc(TREND_REPRESENTATIVE_LABELS[line.slot])}</span>${ready?`<small>${direction}</small>`:''}</div><strong${ready?` data-trend-border="${esc(line.line_id)}"`:''}>${priceReady?esc(trendPrice(line.current_price,asset)):'—'}</strong><p>${esc(description)}</p>${ready?`<small>${distance===null?'현재 선 값 미산출':`${distance>0?'+':''}${distance.toFixed(2)}% · 종가 대비`}</small><small>${esc(period)}</small>${line.kind==='pivot_structure'&&!['active','reclaimed'].includes(line.structural_state)?'<small>이탈 상태의 구조 참고선</small>':''}`:''}</article>`;}).join('')}</div><p class="trend-insight-note">회귀선은 가격의 대표 방향입니다. 고저점 연결선의 기울기와 현재 지지·저항 역할을 구분해 봅니다. 점선은 미래 가격이 아닌 선의 연장입니다.</p></section>`;
}
function trendRepresentativeDetails(analysis,asset){
  if(!analysis.representative_body)return '<p>같은 기준의 전체 일봉과 추세선 계산을 확인하고 있습니다.</p>';
  return analysis.representatives.map(line=>`<p><strong>${esc(TREND_REPRESENTATIVE_LABELS[line.slot])}</strong> · ${line.status!=='ready'?'계산에 필요한 일봉 부족':line.kind==='regression'?`${line.fit.n}개 확정 종가 · ${line.axis==='log'?'로그 가격':'가격'} 회귀 · 결정계수 ${line.fit.r_squared===null?'정의되지 않음':Number(line.fit.r_squared).toFixed(3)}`:`${line.origin_role==='support'?'확정 저점':'확정 고점'} 연결 · ${line.geometry_status==='two_anchor'?'2개 앵커 참고선':'3회 이상 접촉선'} · ${esc(line.first_anchor.session)} ${esc(trendPrice(line.first_anchor.price,asset))} → ${esc(line.second_anchor.session)} ${esc(trendPrice(line.second_anchor.price,asset))}`}</p>`).join('');
}
function trendlineAppNavigation(origin,view,hash,asset='sk-hynix'){
  if(origin==='https://sung-jinpark.github.io'&&view==='trendlines')return 'http://127.0.0.1:8878/#future/trendlines/'+encodeURIComponent(asset);
  if(origin==='http://127.0.0.1:8878'&&view!=='trendlines')return 'https://sung-jinpark.github.io/Jin-s-investing-prediction/'+hash;
  return null;
}
function leaveTrendlineApp(event){
  if(globalThis.location?.origin!=='http://127.0.0.1:8878')return;
  const hash=globalThis.location.hash||'#today';if(hash==='#app'||/^#(?:future\/)?trendlines(?:\/|$)/.test(hash))return;
  const target=trendlineAppNavigation(globalThis.location.origin,'other',hash);event.stopImmediatePropagation();globalThis.TrendlineUI?.cleanup();globalThis.location.replace(target);
}
function renderTrendlinePage(initial={},loadState=null,localSession=null){
  if(initial?.asset==='mag7'){globalThis.history?.replaceState(null,'','#trendlines/sk-hynix');initial={...initial,asset:'sk-hynix'};}
  if(TREND_ZOOM&&!(TREND_ZOOM.ws&&[TREND_ZOOM.ws.assetId,TREND_ZOOM.ws.pendingAsset].includes(initial?.asset||'sk-hynix')))closeTrendZoom(false);if(TRENDLINES_RESIZE){TRENDLINES_RESIZE.disconnect();TRENDLINES_RESIZE=null;}
  const assetId=initial?.asset||'sk-hynix',projection=DATA?.trendlines||{},officialAsset=projection.assets?.find(row=>row.asset_id===assetId),localDetail=TREND_PRIVATE_DETAILS.get(assetId);let detail=localDetail||projection.details?.[assetId],validationError=null;
  const chartNavigation=!['ready','stale'].includes(officialAsset?.status)&&trendlineAppNavigation(globalThis.location?.origin,'trendlines','',assetId);if(chartNavigation){globalThis.location.replace(chartNavigation);return;}
  const workspace=trendManualState(assetId);
  if(workspace.ready&&!TREND_REPRESENTATIVE_VIEW_OPTIONS.has(assetId)&&workspace.view)TREND_REPRESENTATIVE_VIEW_OPTIONS.set(assetId,workspace.view);
  if(detail&&['ready','stale','unverified_display'].includes(detail.status)){try{trendValidateDetail(detail);}catch(error){validationError=error;detail=null;}}
  const asset=localDetail&&detail?{...officialAsset,asset_id:assetId,label:TREND_ASSETS.find(row=>row[0]===assetId)?.[1],currency:detail.asset.currency,price_unit:detail.asset.unit,status:'unverified_display',last_session:detail.observation_through}:officialAsset;if(localDetail&&detail)loadState=null;
  const nav=TREND_VISIBLE_ASSETS.map(([id,label])=>`<a href="#trendlines/${id}"${id===assetId?' aria-current="page"':''}>${esc(label)}</a>`).join(''),fixture=detail?.fixture_only===true?'<p class="trend-fixture" role="alert">검토용 가상 시세 · 실제 시장 분석이 아닙니다</p>':'';
  const root=el(`<div class="trend-page"><header class="trend-heading"><p class="eyebrow">상·하방 추세선 · 03</p><h1>상·하방 추세선</h1></header><nav class="trend-assets" aria-label="추세선 자산 선택">${nav}</nav>${fixture}<section class="trend-body"><p class="trend-update-status" data-trend-local-message role="status"></p><div class="trend-content"></div></section></div>`),body=root.querySelector('.trend-content');
  const held=!asset||!['ready','stale','unverified_display'].includes(asset.status)||!detail||!['ready','stale','unverified_display'].includes(detail.status);
  if(loadState||held){const invalid=validationError||loadState?.error,phase=invalid?'invalid':Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId)?'checking':'idle';body.innerHTML=`<div class="trend-empty" data-trend-empty role="status">${trendEmptyMarkup(assetId,phase,invalid?'가격 기준을 확인한 뒤 표시합니다.':null)}</div>`;mount(root);if(Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId))bindTrendLocalConnection(root,initial,localSession);if(TREND_ZOOM?.ws?.pendingAsset===assetId)TREND_ZOOM.ws.showPending(invalid?'가격 기준을 확인한 뒤 표시합니다.':'가격과 추세선을 곧 표시합니다.');return;}
  const previous=TREND_REPRESENTATIVE_VIEW_OPTIONS.get(assetId)||workspace.view;let family=previous?.family||'all',scope=previous?.scope||'all',scale=previous?.scale||'linear';const reference=trendReference(detail);
  body.innerHTML=`<div class="trend-title"><div><h2>${esc(asset.label)}</h2><span>일봉 ${esc(detail.observation_through||asset.last_session)} 기준</span></div><div class="trend-price"><strong>${esc(trendPrice(reference.price,asset))}</strong><span>${esc(reference.date)}${reference.time?' '+esc(reference.time):''} · ${reference.kind}</span></div></div><section class="trend-chart-section" data-trend-version="representative"><div class="trend-chart-heading"><div><h3>대표 추세선</h3><p data-trend-representative-coverage>200일 가격추세 · 현재 추세 · 장기 주요 고저점</p></div><div class="trend-controls" role="group" aria-label="가격 축"><div>${[['linear','선형'],['log','로그']].map(([value,label])=>`<button type="button" data-trend-scale="${value}" aria-pressed="${scale===value}">${label}</button>`).join('')}</div></div></div><div class="trend-controls trend-representative-filters" role="group" aria-label="추세선 종류"><div>${[['all','모두'],...TREND_REPRESENTATIVE_SLOTS.map(slot=>[slot,TREND_REPRESENTATIVE_LABELS[slot]]),['long_boundaries','상·하단']].map(([value,label])=>`<button type="button" data-trend-family="${value}" aria-pressed="${family===value}">${label}</button>`).join('')}</div></div><div class="trend-controls trend-representative-scopes" role="group" aria-label="표시 기간"><div>${[['recent','최근 구간'],['anchors','장기 기준점'],['all','전체 기간']].map(([value,label])=>`<button type="button" data-trend-scope="${value}" aria-pressed="${scope===value}">${label}</button>`).join('')}</div></div><div class="trend-chart" data-trend-representative-chart></div><div class="trend-explanation"><div class="trend-legend" data-trend-line-legend>${TREND_REPRESENTATIVE_SLOTS.map(slot=>`<span><i style="border-color:${TREND_REPRESENTATIVE_COLORS[slot]}"></i>${esc(TREND_REPRESENTATIVE_LABELS[slot])}</span>`).join('')}</div><p>선 위에서 해당 날짜의 선 가격과 실제 종가를 비교하세요.</p></div><div data-trend-representative-insights></div><details class="trend-line-meta"><summary>계산 · 기준점</summary><div data-trend-representative-details></div></details></section>${trendResearchMarkup(detail,asset)}`;
  mount(root);const session=Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId)?bindTrendLocalConnection(root,initial,localSession):null,host=root.querySelector('[data-trend-representative-chart]');let drawnWidth=0;
  const paint=()=>{TREND_REPRESENTATIVE_VIEW_OPTIONS.set(assetId,{family,scope,scale});workspace.view={...workspace.view,family,scope,scale};const full=TREND_FULL_DETAILS.get(assetId),pinnedFull=full?.source_snapshot_id===detail.snapshot_id?full:null,source=pinnedFull||detail,analysis=trendRepresentativeAnalysis(detail,pinnedFull,scale,family),bars=trendRepresentativeViewport(source,analysis,scope);drawnWidth=host.clientWidth;
    root.setAttribute?.('data-trend-representative-snapshot',analysis.representative_body?.snapshot_id||'');root.setAttribute?.('data-trend-long-snapshot',analysis.long_body?.snapshot_id||'');root.querySelectorAll('[data-trend-family]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendFamily===family)));root.querySelectorAll('[data-trend-scope]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendScope===scope)));root.querySelectorAll('[data-trend-scale]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendScale===scale)));
    root.querySelector('[data-trend-representative-coverage]').textContent=`${bars[0].session||bars[0].session_date} — ${source.observation_through} · ${bars.length.toLocaleString('ko-KR')}개 일봉${scope==='all'&&!pinnedFull?' · 전체 기간 확인 중':''}`;
    root.querySelector('[data-trend-representative-insights]').innerHTML=trendRepresentativeCards(analysis,asset,family)+trendLongBoundaryRows(analysis,asset);root.querySelector('[data-trend-line-legend]').innerHTML=analysis.lines.map(line=>`<span><i style="border-color:${TREND_REPRESENTATIVE_COLORS[line.slot]}"></i>${esc(trendRepresentativeName(line))}</span>`).join('');root.querySelector('[data-trend-representative-details]').innerHTML=trendRepresentativeDetails(analysis,asset)+trendLongBoundaryDetails(analysis,asset);
    const key=assetId+':representative:'+family+':'+scope;if(!TREND_CHART_VIEWS.has(key))TREND_CHART_VIEWS.set(key,{factor:1,offset:null});
    const context={assetId,asset,scale,family,version:'representative',initialBars:bars,build:(nextScale,nextFamily)=>{const latest=TREND_FULL_DETAILS.get(assetId),pinned=latest?.source_snapshot_id===detail.snapshot_id?latest:null;return {source:pinned||detail,analysis:trendRepresentativeAnalysis(detail,pinned,nextScale,nextFamily||'all')};},onClose:view=>{if(!root.isConnected)return;if(['linear','log'].includes(view?.scale))scale=view.scale;if(view?.family)family=view.family;paint();}};
    host._trendWorkspaceContext=context;drawTrendInteractiveChart(host,source,analysis,bars,asset,scale,'representative',TREND_CHART_VIEWS.get(key));
    if(TREND_ZOOM?.ws&&[TREND_ZOOM.ws.assetId,TREND_ZOOM.ws.pendingAsset].includes(assetId))TREND_ZOOM.ws.attach(context);
  };
  workspace.onLoaded=()=>{family=workspace.view.family;scope=workspace.view.scope;scale=workspace.view.scale;for(const key of TREND_CHART_VIEWS.keys())if(key.startsWith(assetId+':representative:'))TREND_CHART_VIEWS.delete(key);paint();};
  root.querySelectorAll('[data-trend-family]').forEach(button=>button.onclick=()=>{family=button.dataset.trendFamily;workspace.view.window=null;paint();trendManualPersist(workspace);});root.querySelectorAll('[data-trend-scope]').forEach(button=>button.onclick=()=>{scope=button.dataset.trendScope;workspace.view.window=null;TREND_CHART_VIEWS.delete(assetId+':representative:'+family+':'+scope);paint();trendManualPersist(workspace);});root.querySelectorAll('[data-trend-scale]').forEach(button=>button.onclick=()=>{scale=button.dataset.trendScale;paint();trendManualPersist(workspace);});paint();
  if(session){session.fullMounted=true;session.representativeMounted=true;session.longMounted=true;session.onRepresentativeData=paint;session.onFullData=()=>{paint();refreshTrendRepresentativeSession(session);};Promise.resolve().then(()=>{refreshTrendFullSession(session);refreshTrendRepresentativeSession(session);});}
  if(globalThis.ResizeObserver){TRENDLINES_RESIZE=new ResizeObserver(()=>{if(!root.isConnected){TRENDLINES_RESIZE?.disconnect();TRENDLINES_RESIZE=null;return;}if(Math.abs(host.clientWidth-drawnWidth)>2)paint();});TRENDLINES_RESIZE.observe(host);}
}
if(globalThis.window?.addEventListener)window.addEventListener('hashchange',leaveTrendlineApp,true);
globalThis.TrendlineUI={ensure:ensureTrendlineData,render:renderTrendlinePage,validate:trendValidateDetail,cleanup(){if(!TREND_ZOOM?.ws?.pendingAsset)closeTrendZoom(false);stopTrendLocalSession();if(TRENDLINES_RESIZE){TRENDLINES_RESIZE.disconnect();TRENDLINES_RESIZE=null;}}};

})();
