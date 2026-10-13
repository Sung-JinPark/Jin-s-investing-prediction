(function(){
"use strict";
const TRENDLINES_PROMISES=new Map();
async function ensureTrendlineData(assetId){
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
const TREND_BASES={split_adjusted:'주식분할 조정 시세',split_adjusted_price:'주식분할 조정 시세',published_spot_price:'일별 현물 시세',published_price_index:'공식 가격 지수'};
const TREND_STATES={active:'유지',break_pending:'이탈 확인 중',broken:'이탈',reclaim_pending:'복귀 확인 중',reclaimed:'복귀'};
const TREND_REASON_LABELS={latest_completed_session_missing:'최근 마감 시세가 아직 확인되지 않았습니다.',capture_rejected_last_good_preserved:'새 시세의 검수가 보류돼 마지막 검수 자료를 유지합니다.',missing_approved_ohlc:'공개 배포가 확인된 일별 시세를 기다리고 있습니다.',source_rights_pending:'시세의 공개 이용 조건을 확인하고 있습니다.',source_unavailable:'시세를 가져오지 못했습니다.',insufficient_history:'이 기간의 추세선을 확인할 과거 시세가 부족합니다.',insufficient_pivots:'확정된 고점·저점이 부족해 빗각선을 그리지 않았습니다.',no_valid_lines:'이 기간에서 검증을 통과한 빗각선이 없습니다.',stale_source:'새로 마감된 시세가 아직 확인되지 않았습니다.',stale_snapshot:'최근 마감 시세로 갱신이 필요합니다.',invalid_snapshot:'가격 자료 검증을 완료하지 못했습니다.'};
function trendReasons(codes){return [...new Set((codes||[]).map(code=>TREND_REASON_LABELS[code]||'가격 자료 검증을 완료하지 못했습니다.'))].join(' ')||'검증된 시세가 준비되면 자동으로 갱신합니다.';}
function trendPrice(value,asset){return `${Number(value).toLocaleString('ko-KR',{maximumFractionDigits:asset?.price_unit==='KRW'||asset?.currency==='KRW'?0:2})}${['points','index_points'].includes(asset?.price_unit)?' pt':asset?.currency==='KRW'?'원':asset?.currency==='USD'?'달러':''}`;}
function trendValidateDetail(detail){
  if(!['ready','stale'].includes(detail?.status)||!Array.isArray(detail.bars)||detail.bars.length<2||!detail.analyses)throw new Error('검증된 일봉이 없습니다');
  let previous=null;
  for(const bar of detail.bars){
    const date=bar.session||bar.session_date;
    if(!/^\d{4}-\d{2}-\d{2}$/.test(date||'')||!Number.isInteger(bar.session_index)||(previous&&(date<=previous.session||bar.session_index<=previous.index)))throw new Error('일봉 날짜가 올바르지 않습니다');
    if(!['open','high','low','close'].every(key=>typeof bar[key]==='number'&&Number.isFinite(bar[key])&&bar[key]>0)||bar.low>Math.min(bar.open,bar.close)||bar.high<Math.max(bar.open,bar.close)||bar.low>bar.high)throw new Error('일봉 가격 범위가 올바르지 않습니다');
    previous={session:date,index:bar.session_index};
  }
  for(const scale of ['linear','log'])for(const period of ['63','252','756']){
    const analysis=detail.analyses[scale]?.[period];
    if(!analysis||!['ready','hold'].includes(analysis.status))throw new Error('추세선 기간 또는 축 정보가 없습니다');
    if(analysis.status==='hold')continue;
    if(!Array.isArray(analysis.lines)||!analysis.borders)throw new Error('추세선 형식이 올바르지 않습니다');
    for(const line of analysis.lines){
      if(!['support','resistance'].includes(line.side)||!Array.isArray(line.points)||line.points.length<2||!Number.isFinite(line.slope)||!Number.isFinite(line.intercept)||!Number.isInteger(line.coordinate_origin_index))throw new Error('빗각선 정보가 올바르지 않습니다');
      let lastIndex=-Infinity;
      for(const point of line.points){
        if(!Number.isInteger(point.index)||point.index<=lastIndex||typeof point.price!=='number'||!Number.isFinite(point.price)||point.price<=0)throw new Error('빗각선 끝점이 올바르지 않습니다');
        const expected=trendLinePrice(line,point.index,scale);
        if(!Number.isFinite(expected)||Math.abs(expected-point.price)>Math.max(1e-7,Math.abs(point.price)*1e-8))throw new Error('빗각선 끝점이 계산 기준과 다릅니다');
        lastIndex=point.index;
      }
      const expectedCurrent=trendLinePrice(line,detail.bars.at(-1).session_index,scale);
      if(typeof line.current_price!=='number'||!Number.isFinite(line.current_price)||line.current_price<=0||Math.abs(line.current_price-expectedCurrent)>Math.max(1e-7,Math.abs(expectedCurrent)*1e-8))throw new Error('빗각선 기준일 가격이 계산과 다릅니다');
    }
    for(const key of ['down','up','broken'])if(!Array.isArray(analysis.borders[key])||analysis.borders[key].some(row=>typeof row.price!=='number'||!Number.isFinite(row.price)||row.price<=0))throw new Error('가격 경계가 올바르지 않습니다');
    for(const key of ['down','up','broken'])for(const row of analysis.borders[key]){const line=analysis.lines.find(line=>line.line_id===row.line_id);if(!line||Math.abs(row.price-line.current_price)>Math.max(1e-7,Math.abs(row.price)*1e-8))throw new Error('가격 경계가 빗각선과 다릅니다');}
  }
  return detail;
}
function trendLinePrice(line,index,scale){const value=line.intercept+line.slope*(index-line.coordinate_origin_index);return scale==='log'?Math.exp(value):value;}
function trendChartModel(detail,period=63,scale='linear',width=1000){
  trendValidateDetail(detail);
  const analysis=detail.analyses[scale]?.[String(period)];
  if(analysis?.status!=='ready')return null;
  const bars=detail.bars.slice(-period),first=bars[0].session_index,last=bars.at(-1).session_index;
  const lines=analysis.lines,points=lines.flatMap(line=>line.points.filter(point=>point.index>=first));
  const end=Math.max(last+1,...points.map(point=>point.index)),prices=bars.flatMap(bar=>[bar.low,bar.high]).concat(points.map(point=>point.price));
  const transform=value=>scale==='log'?Math.log(value):value,inverse=value=>scale==='log'?Math.exp(value):value;
  let low=Math.min(...prices.map(transform)),high=Math.max(...prices.map(transform)),pad=(high-low)*.07||Math.abs(high)*.02||1;
  low-=pad;high+=pad;
  const W=Math.max(330,Math.round(width)),H=W<600?380:440,L=W<600?62:88,R=20,T=24,B=46;
  const x=index=>L+(index-first)/Math.max(1,end-first)*(W-L-R),y=price=>T+(high-transform(price))/(high-low)*(H-T-B);
  return {bars,lines,analysis,first,last,end,W,H,L,R,T,B,x,y,ticks:Array.from({length:5},(_,i)=>inverse(low+(high-low)*i/4))};
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
  const paths=m.lines.map(line=>{const color=line.state==='broken'?'#897b9f':line.side==='support'?'#247d78':'#bd5a20',dash=line.geometry_status==='candidate'||line.state==='broken'?'6 5':'',actual=line.points.filter(point=>!point.future),future=line.points.filter(point=>point.future);const path=points=>points.map(point=>`${m.x(point.index).toFixed(3)},${m.y(point.price).toFixed(3)}`).join(' ');const anchors=[line.first_anchor,line.second_anchor].filter(anchor=>anchor&&anchor.index>=m.first).map(anchor=>`<circle cx="${m.x(anchor.index)}" cy="${m.y(anchor.price)}" r="4" fill="${color}" stroke="#fff"><title>${esc(anchor.session)} · ${esc(trendPrice(anchor.price,asset))}</title></circle>`).join('');return `<g data-trend-line="${esc(line.line_id)}"><polyline points="${path(actual)}" fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="${dash}"/>${future.length?`<polyline data-trend-projection="${esc(line.line_id)}" points="${path([actual.at(-1),...future].filter(Boolean))}" fill="none" stroke="${color}" stroke-width="1.5" stroke-dasharray="3 5"/>`:''}${anchors}</g>`;}).join('');
  return `<svg viewBox="0 0 ${m.W} ${m.H}" role="img" tabindex="0" aria-label="${esc(asset.label)} 실제 일봉과 상방·하방 빗각선. 방향키로 날짜를 선택합니다"><defs><clipPath id="${clip}"><rect x="${m.L}" y="${m.T}" width="${m.W-m.L-m.R}" height="${m.H-m.T-m.B}"/></clipPath></defs>${grid}<rect x="${futureX}" y="${m.T}" width="${m.W-m.R-futureX}" height="${m.H-m.T-m.B}" fill="#eeece6" opacity=".8"/><text x="${futureX+5}" y="${m.T+12}">선 연장</text><g clip-path="url(#${clip})">${candles}${paths}<line data-trend-cross x1="${futureX}" x2="${futureX}" y1="${m.T}" y2="${m.H-m.B}" stroke="#777" stroke-dasharray="2 4"/></g>${ticks}<rect data-trend-overlay x="${m.L}" y="${m.T}" width="${m.W-m.L-m.R}" height="${m.H-m.T-m.B}" fill="transparent"/></svg>`;
}
function bindTrendChart(host,detail,m,asset,scale){
  const svg=host.querySelector('svg'),cross=host.querySelector('[data-trend-cross]'),readout=host.querySelector('[data-trend-readout]');
  let selected=m.bars.length-1;
  const paint=index=>{selected=Math.max(0,Math.min(m.bars.length-1,index));const bar=m.bars[selected];cross.setAttribute('x1',m.x(bar.session_index));cross.setAttribute('x2',m.x(bar.session_index));const lineRows=m.lines.slice(0,6).map(line=>`${line.side==='support'?'지지':'저항'} ${trendPrice(trendLinePrice(line,bar.session_index,scale),asset)}`).join(' · ');readout.textContent=`${bar.session||bar.session_date} · 시가 ${trendPrice(bar.open,asset)} · 고가 ${trendPrice(bar.high,asset)} · 저가 ${trendPrice(bar.low,asset)} · 종가 ${trendPrice(bar.close,asset)}${lineRows?' | '+lineRows:''}`;};
  const pointer=event=>{const bounds=svg.getBoundingClientRect(),x=(event.clientX-bounds.left)/bounds.width*m.W,index=m.first+(x-m.L)/(m.W-m.L-m.R)*(m.end-m.first);paint(m.bars.reduce((best,bar,i)=>Math.abs(bar.session_index-index)<Math.abs(m.bars[best].session_index-index)?i:best,0));};
  svg.addEventListener('pointermove',pointer);svg.addEventListener('pointerdown',pointer);
  svg.addEventListener('focus',()=>paint(selected));
  svg.addEventListener('keydown',event=>{let index=selected;if(event.key==='ArrowLeft')index--;else if(event.key==='ArrowRight')index++;else if(event.key==='Home')index=0;else if(event.key==='End')index=m.bars.length-1;else return;event.preventDefault();paint(index);});
  paint(selected);
}
let TRENDLINES_RESIZE=null;
function renderTrendlinePage(initial={},loadState=null){
  const assetId=initial?.asset||'sk-hynix',projection=DATA?.trendlines||{},asset=projection.assets?.find(row=>row.asset_id===assetId),detail=projection.details?.[assetId];
  const nav=TREND_ASSETS.map(([id,label])=>`<a href="#future/trendlines/${id}"${id===assetId?' aria-current="page"':''}>${esc(label)}</a>`).join('');
  const fixture=detail?.fixture_only===true?'<p class="trend-fixture" role="alert">검토용 가상 시세 · 실제 시장 분석이 아닙니다</p>':'';
  const root=el(`<div class="trend-page"><header class="page-heading"><div><p class="eyebrow">미래 탐색 · 05</p><h1>상·하방 추세선</h1><p class="page-lede">실제 일봉의 고점·저점을 잇는 빗각선과 기준 종가 위·아래의 경계를 확인합니다.</p></div></header><nav class="trend-assets" aria-label="추세선 자산 선택">${nav}</nav>${fixture}<section class="trend-body"></section></div>`),body=root.querySelector('.trend-body');
  const held=!asset||!['ready','stale'].includes(asset.status)||!detail||!['ready','stale'].includes(detail.status);
  if(loadState||held){const error=loadState?.error,loading=loadState?.loading;body.innerHTML=`<div class="trend-hold" role="status"><span>${esc(asset?.label||'자산 확인')}</span><h2>${loading?'일봉과 빗각선을 불러오고 있습니다':error?'추세선을 불러오지 못했습니다':'추세선 확인 보류'}</h2><p>${esc(error?String(error.message||error):!asset?'요청한 자산을 찾을 수 없습니다. 위에서 자산을 선택해 주세요.':trendReasons(asset.reason_codes))}</p>${error?'<button type="button" data-trend-retry>다시 불러오기</button>':''}${asset?.last_session?`<small>확인된 마지막 시세 ${esc(asset.last_session)}</small>`:''}</div>`;mount(root);root.querySelector('[data-trend-retry]')?.addEventListener('click',()=>route());return;}
  try{trendValidateDetail(detail);}catch(error){renderTrendlinePage(initial,{error});return;}
  let period=63,scale='linear';
  const stale=asset.status==='stale';
  body.innerHTML=`${stale?`<p class="trend-stale" role="status">마지막 검수: ${esc(asset.last_session)} · 갱신 보류<br><small>기준 종가와 당시 경계를 표시합니다. ${esc(trendReasons(asset.reason_codes))}</small></p>`:''}<div class="trend-title"><div><span>${stale?'기준 종가 · ':''}${esc(asset.last_session)} 마감 기준</span><h2>${esc(asset.label)}</h2></div><strong>${esc(trendPrice(detail.bars.at(-1).close,asset))}</strong></div><div class="trend-controls"><div role="group" aria-label="추세선 기간">${[[63,'3개월'],[252,'1년'],[756,'3년']].map(([value,label])=>`<button type="button" data-trend-period="${value}" aria-pressed="${value===63}">${label}</button>`).join('')}</div><div role="group" aria-label="가격 축"><button type="button" data-trend-scale="linear" aria-pressed="true">선형</button><button type="button" data-trend-scale="log" aria-pressed="false">로그</button></div></div><div class="trend-chart"></div><div class="trend-legend"><span><i class="trend-support"></i>지지 빗각선</span><span><i class="trend-resistance"></i>저항 빗각선</span><span><i class="trend-broken"></i>이탈·후보선은 점선</span></div><div class="trend-borders"></div><p class="trend-note">선의 연장은 가격 예상이나 도달 확률이 아닙니다. 접촉한 날짜와 기준 축이 달라지면 경계 가격도 달라집니다.</p><details class="trend-method"><summary>선을 확인하는 기준</summary><p>확정된 고점·저점으로 계산한 선을 그립니다. 접촉 횟수는 기하학적 근거이며 지지 성공 확률이 아닙니다. 종가 이탈과 복귀는 별도로 확인합니다.</p><p>기준 시각 ${esc(detail.as_of)} · ${esc(TREND_BASES[detail.source_identity?.price_basis]||'시세 기준 확인 중')}</p></details>`;
  mount(root);
  const host=root.querySelector('.trend-chart'),borders=root.querySelector('.trend-borders');let drawnWidth=0;
  const paint=()=>{const m=trendChartModel(detail,period,scale,host.clientWidth||1000),analysis=detail.analyses[scale][String(period)];drawnWidth=host.clientWidth;
    root.querySelectorAll('[data-trend-period]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.trendPeriod)===period)));root.querySelectorAll('[data-trend-scale]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.trendScale===scale)));
    if(!m){host.innerHTML=`<p class="trend-hold">${esc(trendReasons(analysis.reason_codes))}</p>`;borders.innerHTML='';return;}
    host.innerHTML=trendSvg(detail,m,asset)+'<p data-trend-readout class="trend-readout" aria-live="polite"></p>';bindTrendChart(host,detail,m,asset,scale);
    borders.innerHTML=[['down',stale?'당시 아래 경계':'아래 경계'],['up',stale?'당시 위 경계':'위 경계'],['broken',stale?'당시 이탈한 선':'이미 이탈한 선']].map(([key,title])=>`<section><h3>${title}</h3>${analysis.borders[key].length?analysis.borders[key].slice(0,3).map((row,index)=>`<article data-trend-border="${esc(row.line_id)}"><span>${index+1}차 · ${esc(TREND_STATES[row.state]||'확인 중')}</span><strong>${esc(trendPrice(row.price,asset))}</strong><small>${row.geometry_status==='candidate'?'후보 · ':''}접촉 ${esc(row.touch_count)}회 · ${row.direction==='rising'?'상승':'하락'}선</small></article>`).join(''):'<p>해당 경계 없음</p>'}</section>`).join('');};
  root.querySelectorAll('[data-trend-period]').forEach(button=>button.onclick=()=>{period=Number(button.dataset.trendPeriod);paint();});root.querySelectorAll('[data-trend-scale]').forEach(button=>button.onclick=()=>{scale=button.dataset.trendScale;paint();});paint();
  if(globalThis.ResizeObserver){TRENDLINES_RESIZE=new ResizeObserver(()=>{if(!root.isConnected){TRENDLINES_RESIZE?.disconnect();TRENDLINES_RESIZE=null;return;}if(Math.abs(host.clientWidth-drawnWidth)>2)paint();});TRENDLINES_RESIZE.observe(host);}
}
globalThis.TrendlineUI={ensure:ensureTrendlineData,render:renderTrendlinePage,validate:trendValidateDetail,cleanup(){if(TRENDLINES_RESIZE){TRENDLINES_RESIZE.disconnect();TRENDLINES_RESIZE=null;}}};

})();
