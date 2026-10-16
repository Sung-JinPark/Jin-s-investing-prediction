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
const TREND_VISIBLE_ASSETS=TREND_ASSETS.filter(([id])=>id!=='mag7');
const TREND_PRIVATE_IDENTITIES={'sk-hynix':['KRX:000660','000660.KS','KRW','XKRX','KRW_per_share','Asia/Seoul','equity','exchange_close'],soxx:['NASDAQ:SOXX','SOXX','USD','XNAS','USD_per_share','America/New_York','etf','exchange_close'],nasdaq:['NASDAQ_COMPOSITE_PRICE_INDEX','^IXIC','USD','XNAS','index_points','America/New_York','index','exchange_close'],sp500:['SP500_PRICE_INDEX','^GSPC','USD','XNYS','index_points','America/New_York','index','exchange_close'],bitcoin:['BTC_USD_SPOT_SOURCE_MUST_BE_DECLARED','BTC-USD','USD','24/7','USD_per_BTC','UTC','crypto','UTC_00_00_next_day'],dow:['DOW_JONES_INDUSTRIAL_AVERAGE_PRICE_INDEX','^DJI','USD','XNYS','index_points','America/New_York','index','exchange_close']};
const TREND_LOCAL_BASE='http://127.0.0.1:8878/api/private-trendlines/';
const TREND_IMPORT_TRANSPORT=Symbol('private_import_transport');
const TREND_VIEW_OPTIONS=new Map();
const TREND_FULL_DETAILS=new Map();
const TREND_CRITICAL_DETAILS=new Map();
const TREND_REPRESENTATIVE_DETAILS=new Map(),TREND_REPRESENTATIVE_VIEW_OPTIONS=new Map();
const TREND_REPRESENTATIVE_PROOF=Symbol('representative_source_and_arithmetic_proof');
const TREND_REPRESENTATIVE_SLOTS=['regression_200','current_structure','major_structure'];
const TREND_REPRESENTATIVE_LABELS={regression_200:'200일 가격추세',current_structure:'현재 추세',major_structure:'장기 주요 고저점',long_upper:'장기 고점 연결선',long_lower:'장기 저점 연결선'};
const TREND_REPRESENTATIVE_COLORS={regression_200:'#32799c',current_structure:'#bc632d',major_structure:'#72649b',long_upper:'#a85454',long_lower:'#357a61'};
const TREND_LONG_DETAILS=new Map(),TREND_LONG_PROOF=Symbol('long_boundaries_source_and_arithmetic_proof');
const TREND_LONG_SLOTS=['long_upper','long_lower'];
const TREND_LONG_POLICY_SHA256='4097093809bbf8f3d362c4eacdac545dac7dd65e22490f0ed02aba7b0af8ecb2';
const TREND_REPRESENTATIVE_POLICY_SHA256='3346c8ba94bf38fc6bcac021b416f9c714c9e146c4bc46e407cf172de6b256a1';
const TREND_CRITICAL_POLICY_SHA256='3bbc9d9d15af58886b9a35de7d9796887538a8a424b1c24a716affd597d1f672';
let TREND_ZOOM=null,TREND_CHART_INSTANCE=0;
const TREND_CHART_VIEWS=new Map();
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
function pauseTrendLocalSession(session){clearTimeout(session.timer);session.timer=null;session.sequence++;session.controller?.abort();session.fullSequence=(session.fullSequence||0)+1;session.fullController?.abort();session.criticalSequence=(session.criticalSequence||0)+1;session.criticalController?.abort();session.representativeSequence=(session.representativeSequence||0)+1;session.representativeController?.abort();session.longSequence=(session.longSequence||0)+1;session.longController?.abort();}
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
  const deadline=setTimeout(()=>controller.abort(),8000),options={method:'GET',mode:'cors',credentials:'omit',cache:'no-store',redirect:'error',targetAddressSpace:'loopback',signal:controller.signal};
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
  const deadline=setTimeout(()=>controller.abort(),20000),options={method:'GET',mode:'cors',credentials:'omit',cache:'no-store',redirect:'error',targetAddressSpace:'loopback',signal:controller.signal},active=()=>trendLocalCurrent(session)&&session.representativeSequence===sequence&&!controller.signal.aborted&&TREND_PRIVATE_DETAILS.get(session.assetId)?.snapshot_id===current.snapshot_id&&TREND_FULL_DETAILS.get(session.assetId)?.snapshot_id===full.snapshot_id;
  const pending=(async()=>{const body=await parseTrendRepresentativeTransport(await readTrendLocalResponse(await fetch(TREND_LOCAL_BASE+session.assetId+'/representative',options),524288),current,full);if(!active())return;changed=TREND_REPRESENTATIVE_DETAILS.get(session.assetId)?.snapshot_id!==body.snapshot_id;TREND_REPRESENTATIVE_DETAILS.set(session.assetId,body);session.representativeError=null;})().catch(error=>{if(!trendLocalCurrent(session)||session.representativeSequence!==sequence)return;changed=TREND_REPRESENTATIVE_DETAILS.delete(session.assetId);session.representativeError=String(error.message||error);}).finally(()=>{clearTimeout(deadline);if(session.representativePending===pending)session.representativePending=null;if(changed&&trendLocalCurrent(session)&&session.representativeSequence===sequence)session.onRepresentativeData?.();if(trendLocalCurrent(session)&&session.representativeSequence===sequence)refreshTrendLongSession(session);});session.representativePending=pending;return pending;
}
function trendLongNear(a,b){return typeof a==='number'&&Number.isFinite(a)&&typeof b==='number'&&Number.isFinite(b)&&Math.abs(a-b)<=Math.max(1e-6,Math.abs(b)*1e-10);}
function trendLongTime(value){const stamp=Date.parse(value);if(!Number.isFinite(stamp))throw new Error('장기선 공개 시각이 올바르지 않습니다');return BigInt(stamp)*1000000n+BigInt((String(value).match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1]||'').padEnd(9,'0').slice(3,9)||'0');}
function trendLongInputs(bars){
  const byIndex=new Map(bars.map(bar=>[bar.session_index,bar])),atr=new Map(),ranges=[],pivots=[];
  bars.forEach((bar,i)=>{if(!i||bar.session_index!==bars[i-1].session_index+1){ranges.length=0;atr.set(bar.session_index,null);return;}const prior=bars[i-1];ranges.push(Math.max(bar.high-bar.low,Math.abs(bar.high-prior.close),Math.abs(bar.low-prior.close)));atr.set(bar.session_index,ranges.length>=14?trendAccurateSum(ranges.slice(-14))/14:null);});
  for(const bar of bars){if(bar.session_index<bars.at(-1).session_index-755)continue;const neighbors=Array.from({length:21},(_,i)=>byIndex.get(bar.session_index-10+i));if(neighbors.some(row=>!row))continue;for(const [side,field] of [['support','low'],['resistance','high']]){if(neighbors.every((row,i)=>{if(i===10)return true;return side==='support'?(i<10?bar[field]<row[field]:bar[field]<=row[field]):(i<10?bar[field]>row[field]:bar[field]>=row[field]);}))pivots.push({index:bar.session_index,side,price:bar[field],bar_id:bar.bar_id});}}
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
  const deadline=setTimeout(()=>controller.abort(),20000),options={method:'GET',mode:'cors',credentials:'omit',cache:'no-store',redirect:'error',targetAddressSpace:'loopback',signal:controller.signal};
  const pending=(async()=>{const body=await parseTrendLongTransport(await readTrendLocalResponse(await fetch(TREND_LOCAL_BASE+session.assetId+'/long-boundaries',options),524288),current,full,representative);if(!active())return;changed=TREND_LONG_DETAILS.get(session.assetId)?.snapshot_id!==body.snapshot_id;TREND_LONG_DETAILS.set(session.assetId,body);session.longError=null;})().catch(error=>{if(!trendLocalCurrent(session)||session.longSequence!==sequence)return;TREND_LONG_DETAILS.delete(session.assetId);changed=true;session.longError=String(error.message||error);}).finally(()=>{clearTimeout(deadline);if(session.longPending===pending)session.longPending=null;if(changed&&trendLocalCurrent(session)&&session.longSequence===sequence)session.onRepresentativeData?.();});session.longPending=pending;return pending;
}
function trendMergeSelectedLines(selected){
  const lines=[];for(const line of selected){const same=lines.find(other=>trendSameGeometry(line,other));if(same){same.alias_labels.push(TREND_REPRESENTATIVE_LABELS[line.slot]);same.alias_slots.push(line.slot);if(line.classification==='reference_structure')same.classification='reference_structure';}else lines.push({...line,label:TREND_REPRESENTATIVE_LABELS[line.slot],independent_contacts:line.markers||[],alias_labels:[TREND_REPRESENTATIVE_LABELS[line.slot]],alias_slots:[line.slot]});}return lines;
}
function trendLongBoundaryRows(analysis,asset){
  if(!['all','long_boundaries'].includes(analysis.family))return '';
  const lines=analysis.long_boundaries.length?analysis.long_boundaries:TREND_LONG_SLOTS.map(slot=>({slot,status:'hold'}));
  return `<div class="trend-long-rows" aria-label="장기 고점·저점 연결선">${lines.map(line=>{const ready=line.status==='ready',intact=line.classification==='intact_structure',status=!ready?'추가선 미산출':intact?`${line.contact_count>=3?'3회 이상 접촉':'2점 연결'} · 형성·현재 역할 충족`:`구조 참고선 · ${!line.formation_complete?'형성구간 자료 부족':line.structural_state!=='active'&&line.structural_state!=='reclaimed'?'이탈 이력':'과거 관통'}`,alias=line.equivalent_to_line_ids?.length?' · 같은 선은 차트에서 통합 표시':'';return `<article data-trend-long-row="${line.slot}" style="--trend-slot:${TREND_REPRESENTATIVE_COLORS[line.slot]}"><div><span>${esc(TREND_REPRESENTATIVE_LABELS[line.slot])}</span><small>${esc(status)}</small></div><strong${ready?` data-trend-long-price="${esc(line.line_id)}"`:''}>${ready?esc(trendPrice(line.current_price,asset)):'—'}</strong><p>${ready?`${esc(line.first_anchor.session)} ${esc(trendPrice(line.first_anchor.price,asset))} → ${esc(line.second_anchor.session)} ${esc(trendPrice(line.second_anchor.price,asset))}${esc(alias)}`:'확정 고저점과 추가선 자료를 확인합니다.'}</p></article>`;}).join('')}</div>`;
}
function trendLongBoundaryDetails(analysis,asset){
  return analysis.long_boundaries.map(line=>`<p><strong>${esc(TREND_REPRESENTATIVE_LABELS[line.slot])}</strong> · ${line.status!=='ready'?'적격 확정 고저점 연결선 미산출':`${line.contact_count}개 독립 접촉 · 확정 피벗 10·10 · ${esc(line.first_anchor.session)} ${esc(trendPrice(line.first_anchor.price,asset))} → ${esc(line.second_anchor.session)} ${esc(trendPrice(line.second_anchor.price,asset))} · ${line.classification==='intact_structure'?'형성·현재 역할 충족':'구조 참고선'} · 형성구간 결측 ${line.formation_missing_sessions}개 · ATR 확인 불가 ${line.formation_atr_unavailable}개`}</p>`).join('');
}
function trendRepresentativeAnalysis(current,full,axis,family='all'){
  const body=TREND_REPRESENTATIVE_DETAILS.get(current.asset_id),proof=body?.[TREND_REPRESENTATIVE_PROOF],valid=!!(full&&proof&&proof.source===current.snapshot_id&&proof.sourceHash===current.content_hash&&proof.full===full.snapshot_id&&proof.manifest===full.critical_manifest_sha256&&body.as_of===current.as_of);
  const representatives=valid?body.analyses[axis].representatives:[],supplement=TREND_LONG_DETAILS.get(current.asset_id),longProof=supplement?.[TREND_LONG_PROOF],longValid=valid&&longProof&&longProof.source===current.snapshot_id&&longProof.full===full.snapshot_id&&longProof.representative===body.snapshot_id&&longProof.representativePayload===proof.payload;
  const long_boundaries=longValid?supplement.analyses[axis].boundaries:[],selected=[...representatives,...long_boundaries].filter(line=>line.status==='ready'&&(family==='all'||family==='long_boundaries'&&TREND_LONG_SLOTS.includes(line.slot)||line.slot===family)),lines=trendMergeSelectedLines(selected);
  return {status:'ready',critical:true,representative:true,axis,family,lines,representatives,long_boundaries,long_body:longValid?supplement:null,projection_sessions:valid?body.projection_sessions:[],representative_body:valid?body:null,critical_reference:valid?{price:body.reference_close,atr14:body.atr14,date:body.reference_session,index:body.reference_index}:null};
}
function trendLineStart(line){return line.display_start_index??line.first_anchor?.index;}
function trendRepresentativeName(line){return `${line.alias_labels?.join(' · ')||TREND_REPRESENTATIVE_LABELS[line.slot]||'추세선'}${line.classification==='reference_structure'?' · 구조 참고선':''}${line.kind==='regression'&&line.slot!=='regression_200'?` · ${line.fit.n}일 회귀`:''}`;}
function trendPlotModel(detail,analysis,bars,scale,width){
  if(analysis.representative)return trendRepresentativePlotModel(detail,analysis,bars,scale,width);
  if(analysis.critical)return trendCriticalPlotModel(detail,analysis,bars,scale,width);
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
function trendRepresentativePlotModel(detail,analysis,bars,scale,width){
  const first=bars[0].session_index,last=bars.at(-1).session_index,sourceLast=detail.bars.at(-1).session_index,future=last===sourceLast&&analysis.lines.length?analysis.projection_sessions:[],dateMap=new Map(detail.bars.map(bar=>[bar.session_index,bar.session||bar.session_date])),futureMap=new Map(future.map(row=>[row.index,row.session]));
  const quote=last===sourceLast&&detail.intraday_quote?.session_index>=first?detail.intraday_quote:null,end=Math.max(last,future.at(-1)?.index||last,quote?.session_index||last),gaps=(detail.gaps||[]).filter(row=>row.session_index>=first&&row.session_index<=end);
  const lines=analysis.lines.map(line=>{const indices=[...new Set([Math.max(first,line.display_start_index),...bars.map(bar=>bar.session_index),...future.map(row=>row.index)])].filter(index=>index>=line.display_start_index&&index<=end).sort((a,b)=>a-b);return {...line,points:indices.map(index=>({index,price:trendLinePrice(line,index,scale),session:dateMap.get(index)||futureMap.get(index),future:index>sourceLast})).filter(point=>Number.isFinite(point.price)&&point.price>0)};});
  const candlePrices=bars.flatMap(bar=>[bar.low,bar.high]),candleLow=Math.min(...candlePrices),candleHigh=Math.max(...candlePrices),range=candleHigh-candleLow,atr=analysis.critical_reference?.atr14||0,allowance=Math.max(4*atr,.2*range),minimum=Math.max(candleLow*.7,candleLow-allowance),maximum=Math.min(candleHigh*1.3,candleHigh+allowance);
  const prices=candlePrices.concat(lines.flatMap(line=>line.points.filter(point=>point.price>=minimum&&point.price<=maximum).map(point=>point.price)),quote?[quote.price]:[]),transform=value=>scale==='log'?Math.log(value):value,inverse=value=>scale==='log'?Math.exp(value):value;
  let low=Math.min(...prices.map(transform)),high=Math.max(...prices.map(transform)),pad=(high-low)*.07||Math.abs(high)*.02||1;low=scale==='linear'?Math.max(0,low-pad):low-pad;high+=pad;
  const W=Math.max(330,Math.round(width)),H=W<600?380:460,L=W<600?62:88,R=20,T=24,B=46,x=index=>L+(index-first)/Math.max(1,end-first)*(W-L-R),y=price=>T+(high-transform(price))/(high-low)*(H-T-B);
  return {bars,lines,analysis,gaps,quote,first,last,end,sourceLast,W,H,L,R,T,B,x,y,cssWidth:Number(width)||W,critical:true,representative:true,ticks:Array.from({length:5},(_,i)=>inverse(low+(high-low)*i/4))};
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
function trendCriticalPlotModel(detail,analysis,bars,scale,width){
  const first=bars[0].session_index,last=bars.at(-1).session_index,sourceLast=detail.bars.at(-1).session_index;
  const future=last===sourceLast&&analysis.lines.length?analysis.projection_sessions:[],dateMap=new Map(detail.bars.map(bar=>[bar.session_index,bar.session||bar.session_date])),futureMap=new Map(analysis.projection_sessions.map(row=>[row.index,row.session])),visibleQuote=last===sourceLast&&detail.intraday_quote?.session_index>=first?detail.intraday_quote:null,end=Math.max(last,future.at(-1)?.index||last,visibleQuote?.session_index||last);
  const lines=analysis.lines.map(line=>{const indices=[...new Set([Math.max(first,line.first_anchor.index),...bars.map(bar=>bar.session_index),...future.map(row=>row.index)])].filter(index=>index>=line.first_anchor.index&&index<=end).sort((a,b)=>a-b);return {...line,side:line.role,points:indices.map(index=>({index,price:trendLinePrice(line,index,scale),future:index>sourceLast,session:dateMap.get(index)||futureMap.get(index)})).filter(point=>Number.isFinite(point.price)&&point.price>0)};});
  const gaps=(detail.gaps||[]).filter(gap=>gap.session_index>=first&&gap.session_index<=end),quote=visibleQuote;
  const candlePrices=bars.flatMap(bar=>[bar.low,bar.high]),candleLow=Math.min(...candlePrices),candleHigh=Math.max(...candlePrices),atr=analysis.critical_reference?.atr14||0;
  const prices=candlePrices.concat(lines.flatMap(line=>line.points.filter(point=>!point.future||point.price>=Math.max(candleLow-4*atr,candleLow*.8)&&point.price<=Math.min(candleHigh+4*atr,candleHigh*1.2)).map(point=>point.price)),lines.filter(line=>line.kind==='horizontal_zone'&&line.points.length>=2).flatMap(line=>[line.zone_low,line.zone_high]),quote?[quote.price]:[]);
  const transform=value=>scale==='log'?Math.log(value):value,inverse=value=>scale==='log'?Math.exp(value):value;let low=Math.min(...prices.map(transform)),high=Math.max(...prices.map(transform)),pad=(high-low)*.07||Math.abs(high)*.02||1;
  low=scale==='linear'?Math.max(0,low-pad):low-pad;high+=pad;
  const W=Math.max(330,Math.round(width)),H=W<600?380:440,L=W<600?62:88,R=20,T=24,B=46,x=index=>L+(index-first)/Math.max(1,end-first)*(W-L-R),y=price=>T+(high-transform(price))/(high-low)*(H-T-B);
  return {bars,lines,analysis,gaps,quote,first,last,end,sourceLast,W,H,L,R,T,B,x,y,cssWidth:Number(width)||W,critical:true,ticks:Array.from({length:5},(_,i)=>inverse(low+(high-low)*i/4))};
}
function trendFullViewport(detail,analysis,scope='anchors'){
  if(scope==='all')return detail.bars;
  const indices=new Set(detail.bars.map(bar=>bar.session_index)),anchors=(analysis.lines||[]).map(line=>line.first_anchor?.index).filter(index=>Number.isInteger(index)&&indices.has(index));
  if(analysis.critical){if(!anchors.length)return detail.bars.slice(-252);const position=detail.bars.findIndex(bar=>bar.session_index===Math.min(...anchors));return detail.bars.slice(Math.max(0,position-10));}
  return anchors.length?detail.bars.filter(bar=>bar.session_index>=Math.min(...anchors)):detail.bars;
}
function trendSegmentDistance(x,y,a,b,sx=1,sy=1){const dx=(b.x-a.x)*sx,dy=(b.y-a.y)*sy,px=(x-a.x)*sx,py=(y-a.y)*sy,t=Math.max(0,Math.min(1,(px*dx+py*dy)/(dx*dx+dy*dy||1)));return Math.hypot(px-t*dx,py-t*dy);}
function trendVisibleSegment(m,a,b){
  const dx=b.x-a.x,dy=b.y-a.y,p=[-dx,dx,-dy,dy],q=[a.x-m.L,m.W-m.R-a.x,a.y-m.T,m.H-m.B-a.y];let from=0,to=1;
  for(let i=0;i<4;i++){if(p[i]===0){if(q[i]<0)return null;continue;}const ratio=q[i]/p[i];if(p[i]<0){if(ratio>to)return null;from=Math.max(from,ratio);}else{if(ratio<from)return null;to=Math.min(to,ratio);}}
  return [{x:a.x+from*dx,y:a.y+from*dy},{x:a.x+to*dx,y:a.y+to*dy}];
}
function trendLineHit(m,x,y,tolerance=6,sx=1,sy=1){
  const hits=[];for(const line of m.lines){let distance=Infinity;for(let i=1;i<line.points.length;i++){const a=line.points[i-1],b=line.points[i],visible=trendVisibleSegment(m,{x:m.x(a.index),y:m.y(a.price)},{x:m.x(b.index),y:m.y(b.price)});if(visible)distance=Math.min(distance,trendSegmentDistance(x,y,visible[0],visible[1],sx,sy));}if(distance<=tolerance)hits.push({line,distance});}
  return hits.sort((a,b)=>a.distance-b.distance||a.line.line_id.localeCompare(b.line.line_id))[0]?.line||null;
}
function trendHoverAt(m,x,y,options={}){
  if(!Number.isFinite(x)||!Number.isFinite(y)||x<m.L||x>m.W-m.R||y<m.T||y>m.H-m.B)return null;
  if(m.quote&&Math.hypot(m.x(m.quote.session_index)-x,m.y(m.quote.price)-y)<=12)return {kind:'quote',row:m.quote,index:m.quote.session_index};
  const index=Math.max(m.first,Math.min(m.end,Math.round(m.first+(x-m.L)/(m.W-m.L-m.R)*(m.end-m.first)))),gap=m.gaps.find(row=>row.session_index===index);
  if(m.critical){const line=trendLineHit(m,x,y,options.touch?12:6,options.sx||1,options.sy||1);if(line){const price=trendLinePrice(line,index,m.analysis.axis||options.scale||line.axis),bar=m.bars.find(row=>row.session_index===index),session=bar?.session||gap?.session||m.analysis.projection_sessions?.find(row=>row.index===index)?.session||null;if(price>0&&index>=trendLineStart(line))return {kind:'line',row:{session,session_index:index,price,close:bar?.close??null},index,line,future:index>(m.sourceLast??m.last)};}}
  if(gap)return {kind:'gap',row:gap,index};
  if(index>m.last){const session=m.analysis.projection_sessions?.find(row=>row.index===index)?.session||null;return {kind:'future',row:{session_index:index,session},index};}
  const bar=m.bars.find(row=>row.session_index===index);
  return bar?{kind:'bar',row:bar,index}:{kind:'gap',row:{session_index:index,session:null},index};
}
function trendHoverText(hit,asset){
  if(!hit)return '';
  const {kind,row}=hit,date=row.session||row.session_date||row.date||'';
  if(kind==='line'){const role=hit.line.role==='support'?'지지':'저항',zone=hit.line.kind==='horizontal_zone'?` · 가격대 ${trendPrice(hit.line.zone_low,asset)}–${trendPrice(hit.line.zone_high,asset)}`:'',name=hit.line.slot?trendRepresentativeName(hit.line)+' · ':'';return `${date} · ${name}${hit.future?'추세선 연장값':hit.line.slot?'선 가격':role+'선 가격'} ${trendPrice(row.price,asset)}${zone}${row.close===null?' · 실제 종가 없음':` · 실제 종가 ${trendPrice(row.close,asset)} · 차이 ${trendPrice(row.price-row.close,asset)}`}`;}
  if(kind==='gap')return `${date} · 일봉 미표시 · 시세 없음`;
  if(kind==='future')return `${date||'선 연장 구간'} · 선 연장 · 미래 시세 없음`;
  if(kind==='quote')return `${date} ${row.time||''} · 장중 ${trendPrice(row.price,asset)} · 종가 아님`;
  return `${date} · 종가 ${trendPrice(row.close,asset)} · 시가 ${trendPrice(row.open,asset)} · 고가 ${trendPrice(row.high,asset)} · 저가 ${trendPrice(row.low,asset)}`;
}
function trendSvg(detail,model,asset,version='current'){
  const m=model,clip=`trend-clip-${detail.asset_id}-${version}`,futureX=m.x(m.last),showFuture=m.lines.some(line=>line.points.some(point=>point.future)),showFutureLabel=(m.W-m.R-futureX)*(m.cssWidth||m.W)/m.W>=50,bodyWidth=Math.max(1,Math.min(8,(m.W-m.L-m.R)/(m.end-m.first+1)*.55));
  const grid=m.ticks.map(price=>`<g><line x1="${m.L}" y1="${m.y(price)}" x2="${m.W-m.R}" y2="${m.y(price)}" stroke="#e1ded5"/><text x="${m.L-7}" y="${m.y(price)+4}" text-anchor="end">${esc(Number(price).toLocaleString('ko-KR',{maximumFractionDigits:0}))}</text></g>`).join('');
  const tickBars=[m.bars[0]],tickGap=m.W<600?75:110;
  for(const bar of m.bars.slice(1,-1))if(m.x(bar.session_index)-m.x(tickBars.at(-1).session_index)>=tickGap)tickBars.push(bar);
  const finalBar=m.bars.at(-1);
  if(tickBars.length>1&&m.x(finalBar.session_index)-m.x(tickBars.at(-1).session_index)<65)tickBars.pop();
  if(finalBar!==tickBars.at(-1))tickBars.push(finalBar);
  const ticks=tickBars.map(bar=>`<text x="${m.x(bar.session_index)}" y="${m.H-15}" text-anchor="middle">${esc((bar.session||bar.session_date).slice(2))}</text>`).join('');
  const candles=m.bars.map(bar=>{const up=bar.close>=bar.open,color=up?'#bb4c1c':'#34738d',top=m.y(Math.max(bar.open,bar.close)),height=Math.max(1,Math.abs(m.y(bar.open)-m.y(bar.close)));return `<g data-trend-bar="${esc(bar.session||bar.session_date)}"><line x1="${m.x(bar.session_index)}" y1="${m.y(bar.high)}" x2="${m.x(bar.session_index)}" y2="${m.y(bar.low)}" stroke="${color}"/><rect x="${m.x(bar.session_index)-bodyWidth/2}" y="${top}" width="${bodyWidth}" height="${height}" fill="${color}"/></g>`;}).join('');
  const gaps=m.gaps.map(gap=>`<g data-trend-gap="${esc(gap.session)}"><rect x="${m.x(gap.session_index)-bodyWidth}" y="${m.T}" width="${bodyWidth*2}" height="${m.H-m.T-m.B}" fill="#b88120" opacity=".15"/><line x1="${m.x(gap.session_index)}" x2="${m.x(gap.session_index)}" y1="${m.T}" y2="${m.H-m.B}" stroke="#a77927" stroke-dasharray="2 4"/><title>${esc(gap.session)} · 원천 결측 일봉</title></g>`).join('');
  const paths=m.lines.map(line=>{const role=line.role||line.side,color=line.slot?TREND_REPRESENTATIVE_COLORS[line.slot]:role==='support'?'#247d78':'#bd5a20',actual=line.points.filter(point=>!point.future),future=line.points.filter(point=>point.future),path=points=>points.map(point=>`${m.x(point.index).toFixed(3)},${m.y(point.price).toFixed(3)}`).join(' ');const anchors=(m.critical?line.independent_contacts:[line.first_anchor,line.second_anchor]).filter(anchor=>anchor&&anchor.index>=m.first&&anchor.index<=m.end).map(anchor=>`<circle data-trend-marker="${esc(anchor.bar_id||anchor.index)}:${esc(anchor.side||line.role||line.side||'reference')}" cx="${m.x(anchor.index)}" cy="${m.y(anchor.price)}" r="2" fill="${color}" stroke="#fff" stroke-width=".7" vector-effect="non-scaling-stroke"><title>${esc(anchor.session)} · ${esc(trendPrice(anchor.price,asset))}</title></circle>`).join('');const zone=line.kind==='horizontal_zone'&&line.points.length>=2&&line.first_anchor.index<=m.end?`<rect x="${m.x(Math.max(m.first,line.first_anchor.index))}" y="${m.y(line.zone_high)}" width="${m.x(m.end)-m.x(Math.max(m.first,line.first_anchor.index))}" height="${Math.max(1,m.y(line.zone_low)-m.y(line.zone_high))}" fill="${color}" opacity=".07"/>`:'';return `<g data-trend-line="${esc(line.line_id)}" data-trend-role="${esc(role)}" data-trend-kind="${esc(line.kind||'diagonal')}"${line.slot?` data-trend-slot="${esc(line.slot)}" data-trend-aliases="${esc((line.alias_slots||[line.slot]).join(','))}"`:''}${line.classification==='reference_structure'?' opacity=".5"':''}>${zone}<polyline data-trend-line-path points="${path(actual)}" fill="none" stroke="${color}" stroke-width="1.1" vector-effect="non-scaling-stroke"/>${future.length?`<polyline data-trend-projection="${esc(line.line_id)}" points="${path([actual.at(-1),...future].filter(Boolean))}" fill="none" stroke="${color}" stroke-width="1" stroke-dasharray="3 5" vector-effect="non-scaling-stroke"/>`:''}${anchors}</g>`;}).join('');
  const quote=m.quote?`<g data-trend-quote-point="${esc(m.quote.date)}"><circle cx="${m.x(m.quote.session_index)}" cy="${m.y(m.quote.price)}" r="6" fill="#fff8e8" stroke="#a77919" stroke-width="2.5"/><text x="${m.x(m.quote.session_index)-9}" y="${m.y(m.quote.price)-10}" text-anchor="end">장중</text><title>${esc(m.quote.date)} ${esc(m.quote.time||'')} · ${esc(trendPrice(m.quote.price,asset))} · 별도 장중 관측, 일봉 종가 아님</title></g>`:'';
  const tipId=`trend-tooltip-${detail.asset_id}-${version}`;
  return `<svg viewBox="0 0 ${m.W} ${m.H}" role="img" tabindex="0" aria-describedby="${tipId}" aria-label="${esc(asset.label)} 일봉과 상방·하방 빗각선. 좌우 방향키로 날짜, 상하 방향키로 선을 선택합니다"><defs><clipPath id="${clip}"><rect x="${m.L}" y="${m.T}" width="${m.W-m.L-m.R}" height="${m.H-m.T-m.B}"/></clipPath></defs>${grid}${showFuture?`<rect x="${futureX}" y="${m.T}" width="${m.W-m.R-futureX}" height="${m.H-m.T-m.B}" fill="#eeece6" opacity=".8"/>${showFutureLabel?`<text x="${futureX+5}" y="${m.T+12}">선 연장</text>`:''}`:''}<g clip-path="url(#${clip})">${gaps}${candles}${paths}${quote}<line data-trend-cross x1="${futureX}" x2="${futureX}" y1="${m.T}" y2="${m.H-m.B}" stroke="#777" stroke-dasharray="2 4" visibility="hidden"/><line data-trend-cross-price x1="${m.L}" x2="${m.W-m.R}" y1="${m.T}" y2="${m.T}" stroke="#247d78" stroke-dasharray="3 4" visibility="hidden"/><circle data-trend-hover-point cx="${futureX}" cy="${m.T}" r="4" fill="#247d78" stroke="#fff" visibility="hidden"/></g>${ticks}<rect data-trend-overlay x="${m.L}" y="${m.T}" width="${m.W-m.L-m.R}" height="${m.H-m.T-m.B}" fill="transparent"/></svg><div id="${tipId}" class="trend-tooltip" data-trend-tooltip role="tooltip" hidden><span data-trend-tooltip-date></span><div><span data-trend-tooltip-kind></span><strong data-trend-tooltip-price></strong></div><p data-trend-tooltip-ohlc></p><small data-trend-tooltip-current></small></div>`;
}
function bindTrendChart(host,detail,m,asset,scale){
  const svg=host.querySelector('svg'),cross=host.querySelector('[data-trend-cross]'),horizontal=host.querySelector('[data-trend-cross-price]'),marker=host.querySelector('[data-trend-hover-point]'),readout=host.querySelector('[data-trend-readout]'),tip=host.querySelector('[data-trend-tooltip]');
  const entries=[...m.bars.map(row=>({kind:'bar',row})),...m.gaps.map(row=>({kind:'gap',row})),...(m.quote?[{kind:'quote',row:m.quote}]:[]),...(m.critical?m.analysis.projection_sessions.filter(row=>row.index>m.last&&row.index<=m.end).map(row=>({kind:'future',row:{...row,session_index:row.index}})):[])].sort((a,b)=>a.row.session_index-b.row.session_index||Number(a.kind==='quote')-Number(b.kind==='quote'));
  let selected=entries.findIndex(entry=>entry.kind==='bar'&&entry.row===m.bars.at(-1)),selectedLine=-1;
  const emphasize=line=>host.querySelectorAll?.('[data-trend-line]').forEach(group=>{const active=group.dataset.trendLine===line?.line_id;group.querySelector('[data-trend-line-path]')?.setAttribute('stroke-width',active?'1.8':'1.1');group.querySelector('[data-trend-projection]')?.setAttribute('stroke-width',active?'1.8':'1');});
  const hide=()=>{tip.hidden=true;emphasize(null);for(const node of [cross,horizontal,marker])node.setAttribute('visibility','hidden');};
  const paint=(hit,show=true)=>{if(!hit){hide();return;}const {kind,row,index}=hit,entry=entries.findIndex(entry=>kind==='line'?entry.kind!=='quote'&&entry.row.session_index===index:entry.kind===kind&&entry.row===row);if(entry>=0)selected=entry;readout.textContent=trendHoverText(hit,asset);if(!show)return;
    const price=kind==='bar'?row.close:kind==='quote'||kind==='line'?row.price:null,reference=trendReference(detail);emphasize(kind==='line'?hit.line:null);cross.setAttribute('x1',m.x(index));cross.setAttribute('x2',m.x(index));cross.setAttribute('visibility','visible');
    for(const node of [horizontal,marker])node.setAttribute('visibility',price===null?'hidden':'visible');
    if(price!==null){horizontal.setAttribute('y1',m.y(price));horizontal.setAttribute('y2',m.y(price));marker.setAttribute('cx',m.x(index));marker.setAttribute('cy',m.y(price));}
    tip.dataset.trendKind=kind;host.querySelector('[data-trend-tooltip-date]').textContent=row.session||row.session_date||row.date||(kind==='future'?'선 연장 구간':'일봉 미확인');
    host.querySelector('[data-trend-tooltip-kind]').textContent=kind==='line'?hit.line.slot?`${trendRepresentativeName(hit.line)} · ${hit.future?'추세선 연장값':'선 가격'}`:hit.future?'추세선 연장값':`${hit.line.role==='support'?'지지':'저항'}선 가격`:kind==='bar'?'종가':kind==='quote'?'장중 관측':kind==='future'?'선 연장':'일봉';
    host.querySelector('[data-trend-tooltip-price]').textContent=price===null?'시세 없음':trendPrice(price,asset);
    host.querySelector('[data-trend-tooltip-ohlc]').textContent=kind==='line'?[hit.line.kind==='horizontal_zone'?`가격대 ${trendPrice(hit.line.zone_low,asset)}–${trendPrice(hit.line.zone_high,asset)}`:null,row.close===null?'실제 종가 없음':`실제 종가 ${trendPrice(row.close,asset)} · 차이 ${trendPrice(row.price-row.close,asset)}`].filter(Boolean).join(' · '):kind==='bar'?`시가 ${trendPrice(row.open,asset)} · 고가 ${trendPrice(row.high,asset)} · 저가 ${trendPrice(row.low,asset)}`:kind==='quote'?'별도 장중 관측 · 종가 아님':kind==='future'?'미래 가격이 아닌 추세선 연장 구간':'확인되지 않은 일봉';
    host.querySelector('[data-trend-tooltip-current]').textContent=`최근 관측 ${trendPrice(reference.price,asset)} · ${reference.date}${reference.time?' '+reference.time:''}`;
    tip.hidden=false;const bounds=svg.getBoundingClientRect(),px=m.x(index)/m.W*bounds.width,py=(price===null?m.T+18:m.y(price))/m.H*bounds.height,w=tip.offsetWidth,h=tip.offsetHeight;
    const hostBounds=host.getBoundingClientRect?.(),offsetLeft=hostBounds?bounds.left-hostBounds.left:0,offsetTop=hostBounds?bounds.top-hostBounds.top:0;
    tip.style.left=`${offsetLeft+Math.max(4,Math.min(bounds.width-w-4,px+w+16>bounds.width?px-w-14:px+14))}px`;tip.style.top=`${offsetTop+Math.max(4,Math.min(bounds.height-h-4,py-h/2))}px`;
  };
  const paintEntry=index=>{selected=Math.max(0,Math.min(entries.length-1,index));const entry=entries[selected],ordinal=entry.row.session_index,line=m.lines[selectedLine];if(line&&ordinal>=trendLineStart(line)){const price=trendLinePrice(line,ordinal,scale);if(price>0){paint({kind:'line',index:ordinal,line,row:{session:entry.row.session||entry.row.session_date||entry.row.date,price,close:entry.kind==='bar'?entry.row.close:null},future:ordinal>(m.sourceLast??m.last)});return;}}paint({...entry,index:ordinal});};
  const pointer=event=>{const bounds=svg.getBoundingClientRect(),sx=bounds.width/m.W,sy=bounds.height/m.H;let x=(event.clientX-bounds.left)/sx,y=(event.clientY-bounds.top)/sy;if(svg.getScreenCTM&&globalThis.DOMPoint){const matrix=svg.getScreenCTM();if(matrix){const point=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());x=point.x;y=point.y;}}const hit=trendHoverAt(m,x,y,{touch:event.pointerType==='touch',sx,sy,scale});selectedLine=hit?.kind==='line'?m.lines.findIndex(line=>line.line_id===hit.line.line_id):-1;paint(hit);};
  svg.addEventListener('pointermove',pointer);svg.addEventListener('pointerdown',pointer);
  svg.addEventListener('pointerleave',event=>{if(event.pointerType!=='touch')hide();});svg.addEventListener('blur',hide);
  svg.addEventListener('focus',()=>paintEntry(selected));
  svg.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();hide();return;}let index=selected;if(event.key==='ArrowLeft')index--;else if(event.key==='ArrowRight')index++;else if(event.key==='ArrowUp'||event.key==='ArrowDown'){if(!m.critical||!m.lines.length)return;selectedLine=(selectedLine+1+(event.key==='ArrowUp'?1:-1)+m.lines.length+1)%(m.lines.length+1)-1;}else if(event.key==='Home')index=0;else if(event.key==='End')index=entries.length-1;else return;event.preventDefault();paintEntry(index);});
  paint({...entries[selected],index:entries[selected].row.session_index},false);
}
function trendZoomViewport(bars,state){
  const maximum=Math.max(1,Math.min(8,bars.length/20));state.factor=Math.max(1,Math.min(maximum,Number(state.factor)||1));const count=Math.min(bars.length,Math.max(20,Math.ceil(bars.length/state.factor))),limit=bars.length-count;
  const offset=state.offset===null||state.offset===undefined?limit:Math.max(0,Math.min(limit,Math.round(state.offset)));state.offset=offset;return bars.slice(offset,offset+count);
}
function closeTrendZoom(restore=true){
  if(!TREND_ZOOM)return;const zoom=TREND_ZOOM;TREND_ZOOM=null;zoom.layer.remove();document.body.classList.remove('trend-zoom-open');for(const [node,value] of zoom.inert)if(node.isConnected)node.inert=value;window.removeEventListener('keydown',zoom.key);window.removeEventListener('resize',zoom.resize);if(restore){const trigger=zoom.trigger?.isConnected?zoom.trigger:document.querySelector(zoom.triggerSelector);trigger?.focus();}
}
function trendChartTools(state,modal=false){return `<div class="trend-chart-tools" role="group" aria-label="시간축 확대와 이동">${modal?'':'<button type="button" data-trend-tool="expand">크게 보기 ↗</button>'}<button type="button" data-trend-tool="out" aria-label="시간축 축소">−</button><output data-trend-zoom-factor>${Number(state.factor||1).toFixed(1)}×</output><button type="button" data-trend-tool="in" aria-label="시간축 확대">＋</button><button type="button" data-trend-tool="left" aria-label="이전 구간">←</button><button type="button" data-trend-tool="right" aria-label="다음 구간">→</button><button type="button" data-trend-tool="reset">초기화</button></div>`;}
function drawTrendInteractiveChart(host,detail,analysis,baseBars,asset,scale,version,state,onState=()=>{},modal=false){
  const bars=trendZoomViewport(baseBars,state),m=trendPlotModel(detail,analysis,bars,scale,host.clientWidth||1000),maximum=Math.max(1,Math.min(8,baseBars.length/20));
  host.innerHTML=trendChartTools(state,modal)+trendSvg(detail,m,asset,version)+'<p data-trend-readout class="trend-readout" aria-live="polite"></p>'+(!analysis.lines.length?`<p class="trend-direction-empty">${analysis.representative?'추세선 자료를 확인하고 있습니다.':'확인된 경계 없음'}</p>`:'');bindTrendChart(host,detail,m,asset,scale);
  const repaint=()=>{const action=document.activeElement?.dataset?.trendTool;onState();drawTrendInteractiveChart(host,detail,analysis,baseBars,asset,scale,version,state,onState,modal);if(action)host.querySelector(`[data-trend-tool="${action}"]`)?.focus();};
  const zoom=(factor,ratio=.5)=>{const before=trendZoomViewport(baseBars,state),anchor=state.offset+ratio*(before.length-1);state.factor=Math.max(1,Math.min(maximum,factor));const count=Math.min(baseBars.length,Math.max(20,Math.ceil(baseBars.length/state.factor)));state.offset=anchor-ratio*(count-1);repaint();};
  host.querySelectorAll?.('[data-trend-tool]').forEach(button=>{const action=button.dataset.trendTool;button.disabled=action==='in'&&state.factor>=maximum||action==='out'&&state.factor<=1||action==='left'&&state.offset<=0||action==='right'&&state.offset>=baseBars.length-bars.length;button.onclick=()=>{if(action==='expand'){openTrendZoom(host,button,detail,analysis,baseBars,asset,scale,version,state);return;}if(action==='in'||action==='out'){zoom(state.factor*(action==='in'?1.5:1/1.5));return;}if(action==='reset'){state.factor=1;state.offset=null;}else state.offset+=Math.round(bars.length*.4)*(action==='left'?-1:1);repaint();};});
  host._trendNavigation={m,zoom,repaint,state,baseBars,bars};
  if(host._trendNavigationBound||!host.addEventListener)return;host._trendNavigationBound=true;const pointers=new Map();let drag=null,pinch=null;
  host.addEventListener('wheel',event=>{if(!event.target.closest('svg'))return;event.preventDefault();const nav=host._trendNavigation,bounds=host.querySelector('svg').getBoundingClientRect(),ratio=Math.max(0,Math.min(1,(event.clientX-bounds.left)/bounds.width));nav.zoom(nav.state.factor*Math.exp(-event.deltaY*.002),ratio);},{passive:false});
  host.addEventListener('pointerdown',event=>{if(!event.target.closest('svg')||event.button!==0&&event.pointerType!=='touch')return;const nav=host._trendNavigation;pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});if(event.isTrusted)host.setPointerCapture?.(event.pointerId);if(pointers.size===2){const values=[...pointers.values()];pinch={distance:Math.hypot(values[0].x-values[1].x,values[0].y-values[1].y),factor:nav.state.factor};drag=null;}else drag={id:event.pointerId,x:event.clientX,offset:nav.state.offset,width:host.querySelector('svg').getBoundingClientRect().width,count:nav.bars.length};});
  host.addEventListener('pointermove',event=>{if(!pointers.has(event.pointerId))return;pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});const nav=host._trendNavigation;if(pinch&&pointers.size===2){const values=[...pointers.values()],distance=Math.hypot(values[0].x-values[1].x,values[0].y-values[1].y);event.preventDefault();nav.zoom(pinch.factor*distance/Math.max(1,pinch.distance));}else if(drag?.id===event.pointerId&&nav.state.factor>1&&Math.abs(event.clientX-drag.x)>6){event.preventDefault();nav.state.offset=drag.offset-(event.clientX-drag.x)/drag.width*drag.count;nav.repaint();}});
  const release=event=>{pointers.delete(event.pointerId);if(pointers.size<2)pinch=null;drag=null;};host.addEventListener('pointerup',release);host.addEventListener('pointercancel',release);
}
function openTrendZoom(host,trigger,detail,analysis,bars,asset,scale,version,state){
  closeTrendZoom(false);const unique=`${version}-expanded-${++TREND_CHART_INSTANCE}`,layer=el(`<div class="trend-zoom-layer" data-trend-zoom><button class="trend-zoom-scrim" type="button" tabindex="-1" data-trend-zoom-close aria-label="닫기"></button><section class="trend-zoom-dialog" role="dialog" aria-modal="true" aria-labelledby="${unique}-title"><header><h2 id="${unique}-title">${esc(asset.label)} · ${version==='representative'?'대표 추세선':version==='full'?'전체 경계':'현재 경계'}</h2><button type="button" data-trend-zoom-close>닫기</button></header><div class="trend-chart" data-trend-zoom-chart></div><p class="trend-zoom-help">휠·두 손가락으로 확대 · 드래그로 이동 · 방향키로 날짜와 선 선택</p></section></div>`),zoomState={...state};
  document.body.appendChild(layer);const inert=[...document.body.children].filter(node=>node!==layer).map(node=>[node,node.inert]);for(const [node] of inert)node.inert=true;document.body.classList.add('trend-zoom-open');
  const chart=layer.querySelector('[data-trend-zoom-chart]'),render=()=>drawTrendInteractiveChart(chart,detail,analysis,bars,asset,scale,unique,zoomState,()=>{},true),key=event=>{if(event.key==='Escape'){event.preventDefault();closeTrendZoom();return;}if(event.key==='Tab'){const nodes=[...layer.querySelectorAll('button:not([disabled]):not([tabindex="-1"]),svg[tabindex="0"]')],first=nodes[0],last=nodes.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}};
  TREND_ZOOM={layer,trigger,triggerSelector:`[data-trend-${version}-chart] [data-trend-tool="expand"]`,inert,key,resize:render};layer.querySelectorAll('[data-trend-zoom-close]').forEach(button=>button.onclick=()=>closeTrendZoom());window.addEventListener('keydown',key);window.addEventListener('resize',render);render();layer.querySelector('.trend-zoom-dialog [data-trend-zoom-close]').focus();
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
  const nav=TREND_VISIBLE_ASSETS.map(([id,label])=>`<a href="#future/trendlines/${id}"${id===assetId?' aria-current="page"':''}>${esc(label)}</a>`).join(''),fixture=detail?.fixture_only===true?'<p class="trend-fixture" role="alert">검토용 가상 시세 · 실제 시장 분석이 아닙니다</p>':'';
  const root=el(`<div class="trend-page"><header class="trend-heading"><p class="eyebrow">미래 탐색 · 05</p><h1>상·하방 추세선</h1></header><nav class="trend-assets" aria-label="추세선 자산 선택">${nav}</nav>${fixture}<section class="trend-body"><p class="trend-update-status" data-trend-local-message role="status"></p><div class="trend-content"></div></section></div>`),body=root.querySelector('.trend-content');
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
function renderTrendlinePage(initial={},loadState=null,localSession=null){
  if(initial?.asset==='mag7'){globalThis.history?.replaceState(null,'','#future/trendlines/sk-hynix');initial={...initial,asset:'sk-hynix'};}
  if(TREND_ZOOM)closeTrendZoom(false);if(TRENDLINES_RESIZE){TRENDLINES_RESIZE.disconnect();TRENDLINES_RESIZE=null;}
  const assetId=initial?.asset||'sk-hynix',projection=DATA?.trendlines||{},officialAsset=projection.assets?.find(row=>row.asset_id===assetId),localDetail=TREND_PRIVATE_DETAILS.get(assetId);let detail=localDetail||projection.details?.[assetId],validationError=null;
  if(!localSession){TREND_REPRESENTATIVE_VIEW_OPTIONS.delete(assetId);for(const key of TREND_CHART_VIEWS.keys())if(key.startsWith(assetId+':representative:'))TREND_CHART_VIEWS.delete(key);}
  if(detail&&['ready','stale','unverified_display'].includes(detail.status)){try{trendValidateDetail(detail);}catch(error){validationError=error;detail=null;}}
  const asset=localDetail&&detail?{...officialAsset,asset_id:assetId,label:TREND_ASSETS.find(row=>row[0]===assetId)?.[1],currency:detail.asset.currency,price_unit:detail.asset.unit,status:'unverified_display',last_session:detail.observation_through}:officialAsset;if(localDetail&&detail)loadState=null;
  const nav=TREND_VISIBLE_ASSETS.map(([id,label])=>`<a href="#future/trendlines/${id}"${id===assetId?' aria-current="page"':''}>${esc(label)}</a>`).join(''),fixture=detail?.fixture_only===true?'<p class="trend-fixture" role="alert">검토용 가상 시세 · 실제 시장 분석이 아닙니다</p>':'';
  const root=el(`<div class="trend-page"><header class="trend-heading"><p class="eyebrow">미래 탐색 · 05</p><h1>상·하방 추세선</h1></header><nav class="trend-assets" aria-label="추세선 자산 선택">${nav}</nav>${fixture}<section class="trend-body"><p class="trend-update-status" data-trend-local-message role="status"></p><div class="trend-content"></div></section></div>`),body=root.querySelector('.trend-content');
  const held=!asset||!['ready','stale','unverified_display'].includes(asset.status)||!detail||!['ready','stale','unverified_display'].includes(detail.status);
  if(loadState||held){const invalid=validationError||loadState?.error,phase=invalid?'invalid':Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId)?'checking':'idle';body.innerHTML=`<div class="trend-empty" data-trend-empty role="status">${trendEmptyMarkup(assetId,phase,invalid?'가격 기준을 확인한 뒤 표시합니다.':null)}</div>`;mount(root);if(Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId))bindTrendLocalConnection(root,initial,localSession);return;}
  const previous=TREND_REPRESENTATIVE_VIEW_OPTIONS.get(assetId);let family=previous?.family||'all',scope=previous?.scope||'all',scale=previous?.scale||'linear';const reference=trendReference(detail);
  body.innerHTML=`<div class="trend-title"><div><h2>${esc(asset.label)}</h2><span>일봉 ${esc(detail.observation_through||asset.last_session)} 기준</span></div><div class="trend-price"><strong>${esc(trendPrice(reference.price,asset))}</strong><span>${esc(reference.date)}${reference.time?' '+esc(reference.time):''} · ${reference.kind}</span></div></div><section class="trend-chart-section" data-trend-version="representative"><div class="trend-chart-heading"><div><h3>대표 추세선</h3><p data-trend-representative-coverage>200일 가격추세 · 현재 추세 · 장기 주요 고저점</p></div><div class="trend-controls" role="group" aria-label="가격 축"><div>${[['linear','선형'],['log','로그']].map(([value,label])=>`<button type="button" data-trend-scale="${value}" aria-pressed="${scale===value}">${label}</button>`).join('')}</div></div></div><div class="trend-controls trend-representative-filters" role="group" aria-label="추세선 종류"><div>${[['all','모두'],...TREND_REPRESENTATIVE_SLOTS.map(slot=>[slot,TREND_REPRESENTATIVE_LABELS[slot]]),['long_boundaries','상·하단']].map(([value,label])=>`<button type="button" data-trend-family="${value}" aria-pressed="${family===value}">${label}</button>`).join('')}</div></div><div class="trend-controls trend-representative-scopes" role="group" aria-label="표시 기간"><div>${[['recent','최근 구간'],['anchors','장기 기준점'],['all','전체 기간']].map(([value,label])=>`<button type="button" data-trend-scope="${value}" aria-pressed="${scope===value}">${label}</button>`).join('')}</div></div><div class="trend-chart" data-trend-representative-chart></div><div class="trend-explanation"><div class="trend-legend" data-trend-line-legend>${TREND_REPRESENTATIVE_SLOTS.map(slot=>`<span><i style="border-color:${TREND_REPRESENTATIVE_COLORS[slot]}"></i>${esc(TREND_REPRESENTATIVE_LABELS[slot])}</span>`).join('')}</div><p>선 위에서 해당 날짜의 선 가격과 실제 종가를 비교하세요.</p></div><div data-trend-representative-insights></div><details class="trend-line-meta"><summary>계산 · 기준점</summary><div data-trend-representative-details></div></details></section>${trendResearchMarkup(detail,asset)}`;
  mount(root);const session=Object.hasOwn(TREND_PRIVATE_IDENTITIES,assetId)?bindTrendLocalConnection(root,initial,localSession):null,host=root.querySelector('[data-trend-representative-chart]');let drawnWidth=0;
  const paint=()=>{TREND_REPRESENTATIVE_VIEW_OPTIONS.set(assetId,{family,scope,scale});const full=TREND_FULL_DETAILS.get(assetId),pinnedFull=full?.source_snapshot_id===detail.snapshot_id?full:null,source=pinnedFull||detail,analysis=trendRepresentativeAnalysis(detail,pinnedFull,scale,family),bars=trendRepresentativeViewport(source,analysis,scope);drawnWidth=host.clientWidth;
    root.setAttribute?.('data-trend-representative-snapshot',analysis.representative_body?.snapshot_id||'');root.setAttribute?.('data-trend-long-snapshot',analysis.long_body?.snapshot_id||'');root.querySelectorAll('[data-trend-family]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendFamily===family)));root.querySelectorAll('[data-trend-scope]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendScope===scope)));root.querySelectorAll('[data-trend-scale]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendScale===scale)));
    root.querySelector('[data-trend-representative-coverage]').textContent=`${bars[0].session||bars[0].session_date} — ${source.observation_through} · ${bars.length.toLocaleString('ko-KR')}개 일봉${scope==='all'&&!pinnedFull?' · 전체 기간 확인 중':''}`;
    root.querySelector('[data-trend-representative-insights]').innerHTML=trendRepresentativeCards(analysis,asset,family)+trendLongBoundaryRows(analysis,asset);root.querySelector('[data-trend-line-legend]').innerHTML=analysis.lines.map(line=>`<span><i style="border-color:${TREND_REPRESENTATIVE_COLORS[line.slot]}"></i>${esc(trendRepresentativeName(line))}</span>`).join('');root.querySelector('[data-trend-representative-details]').innerHTML=trendRepresentativeDetails(analysis,asset)+trendLongBoundaryDetails(analysis,asset);
    const key=assetId+':representative:'+family+':'+scope;if(!TREND_CHART_VIEWS.has(key))TREND_CHART_VIEWS.set(key,{factor:1,offset:null});drawTrendInteractiveChart(host,source,analysis,bars,asset,scale,'representative',TREND_CHART_VIEWS.get(key));
  };
  root.querySelectorAll('[data-trend-family]').forEach(button=>button.onclick=()=>{family=button.dataset.trendFamily;paint();});root.querySelectorAll('[data-trend-scope]').forEach(button=>button.onclick=()=>{scope=button.dataset.trendScope;TREND_CHART_VIEWS.delete(assetId+':representative:'+family+':'+scope);paint();});root.querySelectorAll('[data-trend-scale]').forEach(button=>button.onclick=()=>{scale=button.dataset.trendScale;paint();});paint();
  if(session){session.fullMounted=true;session.representativeMounted=true;session.longMounted=true;session.onRepresentativeData=paint;session.onFullData=()=>{paint();refreshTrendRepresentativeSession(session);};Promise.resolve().then(()=>{refreshTrendFullSession(session);refreshTrendRepresentativeSession(session);});}
  if(globalThis.ResizeObserver){TRENDLINES_RESIZE=new ResizeObserver(()=>{if(!root.isConnected){TRENDLINES_RESIZE?.disconnect();TRENDLINES_RESIZE=null;return;}if(Math.abs(host.clientWidth-drawnWidth)>2)paint();});TRENDLINES_RESIZE.observe(host);}
}
globalThis.TrendlineUI={ensure:ensureTrendlineData,render:renderTrendlinePage,validate:trendValidateDetail,cleanup(){closeTrendZoom(false);stopTrendLocalSession();if(TRENDLINES_RESIZE){TRENDLINES_RESIZE.disconnect();TRENDLINES_RESIZE=null;}}};

})();
