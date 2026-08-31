"use strict";
async function loadData(){
  if(window.__DATA__) return window.__DATA__;
  if(window.__DATA_URL__){ const r = await fetch(window.__DATA_URL__,{cache:'no-store'}); return await r.json(); }
  return null;
}
let FUTURE_PATHS_PROMISE=null,FUTURE_PATHS_ERROR=null;
let STATISTICS_PROMISE=null,STATISTICS_ERROR=null;
function semanticReferenceMatches(left={},right={}){
  return ['candidate_id','model_version','rules_version'].every(key=>left?.[key]&&left[key]===right?.[key]);
}
async function ensureFuturePaths(){
  const summary=DATA?.scenario_v5_2||{},deferred=summary.deferred_paths||{};
  if(!deferred.required||deferred.loaded)return true;
  if(FUTURE_PATHS_PROMISE)return FUTURE_PATHS_PROMISE;
  FUTURE_PATHS_PROMISE=(async()=>{
    const url=window.__FUTURE_PATHS_URL__||deferred.url;
    if(!url)throw new Error('future paths URL missing');
    const response=await fetch(url,{cache:'no-store'});
    if(!response.ok)throw new Error(`future paths HTTP ${response.status}`);
    const payload=await response.json();
    if(payload?.contract_id!=='future_paths_v1'||!payload.data?.scenario_v5_2)throw new Error('future paths contract invalid');
    if(!semanticReferenceMatches(summary.semantic_reference,payload.semantic_reference))throw new Error('future paths semantic reference mismatch');
    Object.assign(DATA,payload.data);
    DATA.scenario_v5_2.deferred_paths={...deferred,loaded:true,loaded_at:new Date().toISOString()};
    FUTURE_PATHS_ERROR=null;
    return true;
  })().catch(error=>{FUTURE_PATHS_ERROR=String(error?.message||error);FUTURE_PATHS_PROMISE=null;throw error;});
  return FUTURE_PATHS_PROMISE;
}
async function ensureStatistics(){
  const summary=DATA?.statistics_lab||{},deferred=summary.deferred_data||{};
  if(!deferred.required||deferred.loaded)return true;
  if(STATISTICS_PROMISE)return STATISTICS_PROMISE;
  STATISTICS_PROMISE=(async()=>{
    const url=window.__STATISTICS_URL__||deferred.url;
    if(!url)throw new Error('statistics URL missing');
    const response=await fetch(url,{cache:'no-store'});
    if(!response.ok)throw new Error(`statistics HTTP ${response.status}`);
    const payload=await response.json();
    if(payload?.contract_id!=='statistics_route_v1'||payload.data?.statistics_lab?.status!=='ok')throw new Error('statistics route contract invalid');
    DATA.statistics_lab=payload.data.statistics_lab;
    DATA.statistics_lab.deferred_data={...deferred,loaded:true,loaded_at:new Date().toISOString()};
    STATISTICS_ERROR=null;
    return true;
  })().catch(error=>{STATISTICS_ERROR=String(error?.message||error);STATISTICS_PROMISE=null;throw error;});
  return STATISTICS_PROMISE;
}
let DATA=null;
const $=(s,r=document)=>r.querySelector(s);
const app=()=>document.getElementById('app');
const pct=v=>(v==null?'—':Math.round(v*100)+'%');
const hasNumeric=v=>v!==null&&v!==''&&Number.isFinite(Number(v));
const p1=v=>(hasNumeric(v)?v+'%':'산출 전');
const roundLabel=v=>(Number(v)>0?`R${v}`:'회차 없음');
const num=v=>(v==null?'—':Number(v).toLocaleString());
const esc=s=>(s==null?'':String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])));
const UI_TERMS={
  as_of:'데이터 기준일',ATH:'사상 최고치',GBM:'고정 가정 경로 모형',p10_p90:'넓은 구간',p25_p75:'중심 구간',p50:'중앙값',
  scenario_conditional:'시나리오 안의 조건부 값',physical_event:'사전등록 사건 확률',reference_only:'참고용',probability_space:'확률의 종류',
  path_realism:'경로 현실성 검사',hazard:'위험 구간',regime:'시장 국면',coverage:'확보된 입력 비율',blocked:'판정 보류',vintage:'당시 공개본',PIT:'당시 정보 기준',reconstructed:'사후 복원 자료'
};
const plainTerm=value=>UI_TERMS[value]||value;
function el(html){const t=document.createElement('template');t.innerHTML=html.trim();return t.content.firstChild;}
function mount(root){
  cleanupExperienceLayer();closeQuickPeek();
  root.classList.add('view-enter');app().innerHTML='';app().appendChild(root);
  requestAnimationFrame(()=>{root.classList.add('is-ready');bindDynamicMotion(root);bindExperienceLayer(root);syncQuestionActions(root);});
}
function bindDynamicMotion(root){
  const fine=window.matchMedia('(pointer: fine)').matches;
  if(!motionAllowed()||!fine)return;
  root.querySelectorAll('.forecast-card').forEach(card=>{
    let frame=0,lastEvent=null;
    const paint=()=>{
      frame=0;if(!lastEvent)return;const r=card.getBoundingClientRect();
      const x=Math.max(0,Math.min(1,(lastEvent.clientX-r.left)/r.width));
      const y=Math.max(0,Math.min(1,(lastEvent.clientY-r.top)/r.height));
      card.style.setProperty('--spot-x',(x*100).toFixed(1)+'%');card.style.setProperty('--spot-y',(y*100).toFixed(1)+'%');
      card.style.setProperty('--tilt-x',((.5-y)*2.4).toFixed(2)+'deg');card.style.setProperty('--tilt-y',((x-.5)*2.4).toFixed(2)+'deg');
    };
    card.addEventListener('pointermove',e=>{lastEvent=e;card.classList.add('is-pointer');if(!frame)frame=requestAnimationFrame(paint);});
    card.addEventListener('pointerleave',()=>{lastEvent=null;if(frame)cancelAnimationFrame(frame);frame=0;
      card.classList.remove('is-pointer');['--spot-x','--spot-y','--tilt-x','--tilt-y'].forEach(k=>card.style.removeProperty(k));});
  });
  root.querySelectorAll('.page-heading').forEach(head=>head.addEventListener('pointermove',e=>{
    const r=head.getBoundingClientRect();head.style.setProperty('--spot-x',(((e.clientX-r.left)/r.width-.5)*8).toFixed(2));
  }));
}
const menuOpen=document.getElementById('menu-open'),menuClose=document.getElementById('menu-close'),mobileMore=document.getElementById('mobile-more');
const drawer=document.getElementById('mobile-drawer'),drawerBackdrop=document.getElementById('drawer-backdrop');
let drawerReturnFocus=null;
function setDrawer(open,restoreFocus=true){
  if(open&&!briefingLayer.hidden)setBriefing(false,false);
  if(open){closeQuickPeek();drawerReturnFocus=document.activeElement;}
  document.body.classList.toggle('drawer-open',open);
  menuOpen.setAttribute('aria-expanded',String(open));
  mobileMore?.setAttribute('aria-expanded',String(open));
  mobileMore?.classList.toggle('active',open);
  drawer.setAttribute('aria-hidden',String(!open));
  drawerBackdrop.setAttribute('aria-hidden',String(!open));
  document.querySelector('.content-shell').inert=open;
  document.querySelector('.product-rail').inert=open;
  document.querySelector('.mobile-header').inert=open;
  document.getElementById('mobile-bottom-nav').inert=open;
  if(open)menuClose.focus();else if(restoreFocus)(drawerReturnFocus?.focus?drawerReturnFocus:menuOpen).focus();
}
menuOpen.addEventListener('click',()=>setDrawer(true));
mobileMore?.addEventListener('click',()=>setDrawer(!document.body.classList.contains('drawer-open')));
menuClose.addEventListener('click',()=>setDrawer(false));
drawerBackdrop.addEventListener('click',()=>setDrawer(false));
document.addEventListener('keydown',e=>{
  if(!document.body.classList.contains('drawer-open'))return;
  if(e.key==='Tab')trapFocus(e,drawer);
  else if(e.key==='Escape')setDrawer(false);
});
document.querySelectorAll('#mobile-nav a').forEach(a=>a.addEventListener('click',()=>setDrawer(false,false)));
document.querySelectorAll('#mobile-bottom-nav a').forEach(a=>a.addEventListener('click',()=>setDrawer(false,false)));

// device-local workspace memory and utility layers
const UI_KEY='jin-investing-ui-v1',UI_DEFAULTS={version:4,density:'comfortable',motion:'adaptive',pins:[],recent:[],notes:{},compare:[],compareCollapsed:false,compareAutoExpanded:false,lastSeenGeneratedAt:null,questionView:{preset:'all',sort:'priority',layout:'table',domain:'',driver:'',status:''}};
function loadUIState(){
  try{
    const raw=JSON.parse(localStorage.getItem(UI_KEY)||'null');
    if(!raw||![1,2,3,4].includes(raw.version))return {...UI_DEFAULTS,pins:[],recent:[],notes:{},compare:[],questionView:{...UI_DEFAULTS.questionView}};
    const notes=raw.notes&&typeof raw.notes==='object'?Object.fromEntries(Object.entries(raw.notes)
      .filter(([k,v])=>/^#(today|future(?:\/|$)|statistics(?:\/|$)|timeseries(?:\/|$)|records(?:\/|$)|trust(?:\/|$)|overview|flow|ask|questions|asof|track|q\/|compare\/)/.test(k)&&typeof v==='string'&&v.trim())
      .slice(0,20).map(([k,v])=>[k,v.slice(0,700)])):{};
    const questionView=raw.questionView&&typeof raw.questionView==='object'?raw.questionView:{};
    return {...UI_DEFAULTS,...raw,version:4,motion:raw.motion==='reduced'?'reduced':'adaptive',
      pins:Array.isArray(raw.pins)?raw.pins.slice(0,8):[],recent:Array.isArray(raw.recent)?raw.recent.slice(0,6):[],
      compare:Array.isArray(raw.compare)?raw.compare.slice(0,3):[],compareCollapsed:!!raw.compareCollapsed,compareAutoExpanded:!!raw.compareAutoExpanded,
      lastSeenGeneratedAt:typeof raw.lastSeenGeneratedAt==='string'?raw.lastSeenGeneratedAt:null,notes,
      questionView:{
        preset:['all','review','moving','due','pinned'].includes(questionView.preset)?questionView.preset:'all',
        sort:['priority','deadline','probability','movement','updated'].includes(questionView.sort)?questionView.sort:'priority',
        layout:['table','cards'].includes(questionView.layout)?questionView.layout:'table',
        domain:typeof questionView.domain==='string'?questionView.domain.slice(0,80):'',
        driver:typeof questionView.driver==='string'?questionView.driver.slice(0,80):'',
        status:['','active','resolved'].includes(questionView.status)?questionView.status:''
      }};
  }catch(_){return {...UI_DEFAULTS,pins:[],recent:[],notes:{},compare:[],questionView:{...UI_DEFAULTS.questionView}};}
}
function saveUIState(){try{localStorage.setItem(UI_KEY,JSON.stringify(UI_STATE));}catch(_){}}
let UI_STATE=loadUIState(),toastTimer=0,utilityReturnFocus=null,shortcutReturnFocus=null;
const VISIT_SEEN_AT=UI_STATE.lastSeenGeneratedAt;
function rememberVisitSnapshot(){if(!DATA?.meta?.generated)return;UI_STATE.lastSeenGeneratedAt=DATA.meta.generated;saveUIState();}
function syncModalInert(){
  const open=['command-layer','utility-layer','shortcut-layer','briefing-layer','share-layer'].some(id=>!document.getElementById(id).hidden);
  document.querySelector('.product-shell').inert=open;document.getElementById('mobile-bottom-nav').inert=open;
}
const utilityLayer=document.getElementById('utility-layer'),utilityPanel=document.getElementById('utility-panel');
const utilityContent=document.getElementById('utility-content'),utilityClose=document.getElementById('utility-close');
const shortcutLayer=document.getElementById('shortcut-layer'),shortcutSheet=document.getElementById('shortcut-sheet');
const shortcutClose=document.getElementById('shortcut-close'),focusExit=document.getElementById('focus-exit');
const toastRegion=document.getElementById('toast-region');
const routeProgressBar=document.getElementById('route-progress-bar'),viewMap=document.getElementById('view-map');
const viewMapItems=document.getElementById('view-map-items'),quickPeek=document.getElementById('quick-peek');
const compareTray=document.getElementById('compare-tray'),compareItems=document.getElementById('compare-items');
const compareOpen=document.getElementById('compare-open'),compareClear=document.getElementById('compare-clear');
const compareToggle=document.getElementById('compare-toggle'),compareCount=document.getElementById('compare-count');
const briefingLayer=document.getElementById('briefing-layer'),briefingSheet=document.getElementById('briefing-sheet');
const briefingContent=document.getElementById('briefing-content'),briefingClose=document.getElementById('briefing-close');
const briefingPrev=document.getElementById('briefing-prev'),briefingNext=document.getElementById('briefing-next');
const briefingStepLabel=document.getElementById('briefing-step-label'),briefingProgress=document.getElementById('briefing-progress');
const shareLayer=document.getElementById('share-layer'),sharePopover=document.getElementById('share-popover'),shareClose=document.getElementById('share-close'),shareSummary=document.getElementById('share-summary'),shareQrCanvas=document.getElementById('share-qr-canvas');
let viewObserver=null,revealObserver=null,viewScrollHandler=null,viewResizeHandler=null,viewSections=[];
let peekTimer=0,peekAnchor=null,briefingIndex=0,briefingReturnFocus=null,shareReturnFocus=null;
function motionAllowed(){return UI_STATE.motion!=='reduced'&&!window.matchMedia('(prefers-reduced-motion: reduce)').matches;}
function currentNoteKey(){return location.hash||'#today';}
function currentNote(){return UI_STATE.notes[currentNoteKey()]||'';}
function saveCurrentNote(value){
  const key=currentNoteKey(),note=String(value||'').slice(0,700),notes={...UI_STATE.notes};
  if(note.trim())notes[key]=note;else delete notes[key];
  UI_STATE.notes=Object.fromEntries(Object.entries(notes).slice(-20));saveUIState();
}
function openCurrentNote(){
  setUtility(true);
  requestAnimationFrame(()=>utilityContent.querySelector('#workspace-note')?.focus());
}
function copyCurrentNote(){
  const note=currentNote();
  if(!note)return showToast('복사할 메모가 없습니다.','warning');
  copyText(note).then(()=>showToast('현재 화면 메모를 복사했습니다.')).catch(()=>showToast('메모를 복사하지 못했습니다.','warning'));
}
function setMotion(value){
  UI_STATE.motion=value==='reduced'?'reduced':'adaptive';saveUIState();
  document.body.classList.toggle('motion-reduced',UI_STATE.motion==='reduced');
  if(UI_STATE.motion==='reduced')document.querySelectorAll('.section-reveal').forEach(x=>x.classList.add('is-visible'));
  if(!utilityLayer.hidden)renderUtilityPanel();
  showToast(UI_STATE.motion==='reduced'?'움직임을 최소화했습니다.':'시스템 설정에 맞춰 움직임을 적용합니다.');
}

function cleanupExperienceLayer(){
  viewObserver?.disconnect();revealObserver?.disconnect();viewObserver=null;revealObserver=null;
  if(viewScrollHandler)window.removeEventListener('scroll',viewScrollHandler);
  if(viewResizeHandler)window.removeEventListener('resize',viewResizeHandler);
  viewScrollHandler=null;viewResizeHandler=null;viewSections=[];viewMap.hidden=true;viewMapItems.innerHTML='';
}
function sectionLabel(node,index){
  const heading=node.querySelector('h1,h2,h3'),label=(heading?.textContent||node.getAttribute('aria-label')||`섹션 ${index+1}`).trim().replace(/\s+/g,' ');
  return label.length>42?label.slice(0,41)+'…':label;
}
function updateViewPosition(){
  const max=Math.max(1,document.documentElement.scrollHeight-window.innerHeight);
  routeProgressBar.style.width=Math.max(0,Math.min(100,window.scrollY/max*100)).toFixed(2)+'%';
  if(!viewSections.length)return;
  let active=0;
  viewSections.forEach((section,i)=>{if(section.node.getBoundingClientRect().top<=window.innerHeight*.34)active=i;});
  viewMapItems.querySelectorAll('button').forEach((b,i)=>{const on=i===active;b.classList.toggle('is-active',on);if(on)b.setAttribute('aria-current','location');else b.removeAttribute('aria-current');});
}
function animateNumberElement(node){
  if(!motionAllowed()||node.dataset.rolled)return;
  const raw=node.textContent.trim(),match=raw.match(/^(-?[\d,]+(?:\.\d+)?)(.*)$/);if(!match)return;
  const final=Number(match[1].replaceAll(',',''));if(!Number.isFinite(final))return;
  node.dataset.rolled='1';node.setAttribute('aria-label',raw);
  const decimals=(match[1].split('.')[1]||'').length,suffix=match[2],start=performance.now(),duration=420;
  const paint=now=>{const t=Math.min(1,(now-start)/duration),eased=1-Math.pow(1-t,3),value=final*eased;
    node.textContent=(decimals?value.toFixed(decimals):Math.round(value).toLocaleString())+suffix;
    if(t<1)requestAnimationFrame(paint);else node.textContent=raw;
  };
  requestAnimationFrame(paint);
}
function animateNumbers(root){
  root.querySelectorAll('.probability-row strong,.metric-ribbon strong,.track-kpis strong').forEach(animateNumberElement);
}
function buildSectionNavigator(root){
  const selector='.overview-stage,.page-heading,.chart-panel,.panel,.table-shell,.metric-ribbon,.track-kpis,.reasoning-panel';
  const raw=[...root.querySelectorAll(selector)];
  const nodes=raw.filter(node=>!raw.some(parent=>parent!==node&&parent.contains(node)&&!parent.matches('.overview-stage,.page-heading')))
    .filter(node=>node.getBoundingClientRect().height>90).slice(0,7);
  viewSections=nodes.map((node,index)=>{const label=sectionLabel(node,index),id=`view-section-${document.body.dataset.view||'overview'}-${index}`;
    node.id=node.id||id;return {node,label,id:node.id};});
  if(viewSections.length<2){
    viewMap.hidden=true;let frame=0;
    viewScrollHandler=()=>{closeQuickPeek();if(frame)return;frame=requestAnimationFrame(()=>{frame=0;updateViewPosition();});};
    viewResizeHandler=()=>updateViewPosition();
    window.addEventListener('scroll',viewScrollHandler,{passive:true});window.addEventListener('resize',viewResizeHandler,{passive:true});
    updateViewPosition();animateNumbers(root);return;
  }
  viewMapItems.innerHTML=viewSections.map((x,i)=>`<button type="button" data-section="${i}" aria-label="섹션 이동: ${esc(x.label)}"><i></i><span>${esc(x.label)}</span></button>`).join('');
  viewMap.hidden=false;
  viewMapItems.onclick=e=>{const b=e.target.closest('button[data-section]');if(!b)return;viewSections[Number(b.dataset.section)]?.node.scrollIntoView({behavior:motionAllowed()?'smooth':'auto',block:'start'});};
  viewObserver=new IntersectionObserver(()=>updateViewPosition(),{rootMargin:'-18% 0px -62% 0px',threshold:[0,.15,.4]});
  viewSections.forEach(x=>viewObserver.observe(x.node));
  let frame=0;
  viewScrollHandler=()=>{closeQuickPeek();if(frame)return;frame=requestAnimationFrame(()=>{frame=0;updateViewPosition();});};
  viewResizeHandler=()=>updateViewPosition();
  window.addEventListener('scroll',viewScrollHandler,{passive:true});window.addEventListener('resize',viewResizeHandler,{passive:true});
  updateViewPosition();
  if(!motionAllowed()){viewSections.forEach(x=>x.node.classList.add('section-reveal','is-visible'));return;}
  revealObserver=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('is-visible');revealObserver.unobserve(entry.target);}}),{rootMargin:'0px 0px -8% 0px',threshold:.08});
  viewSections.forEach((x,i)=>{if(i===0)x.node.classList.add('is-visible');else{x.node.classList.add('section-reveal');revealObserver.observe(x.node);}});
}
function blockingLayerOpen(){
  return !commandLayer.hidden||!utilityLayer.hidden||!shortcutLayer.hidden||!briefingLayer.hidden||!shareLayer.hidden||document.body.classList.contains('drawer-open');
}
function closeQuickPeek(){
  clearTimeout(peekTimer);peekTimer=0;
  if(peekAnchor?.getAttribute('aria-describedby')==='quick-peek')peekAnchor.removeAttribute('aria-describedby');
  peekAnchor=null;quickPeek.hidden=true;quickPeek.setAttribute('aria-hidden','true');
}
const DRIVER_LABELS=Object.freeze({
  'ai-capex-cycle':'AI 투자 사이클',
  'memory-cycle':'메모리 업황',
  'vol-regime':'변동성 국면',
  'fed-path':'연준 정책 경로',
  'midterm-2026':'2026 중간선거'
});
const DOMAIN_LABELS=Object.freeze({
  'market-regime':'시장 국면',
  'market-daily':'일간 시장',
  'earnings':'실적',
  'macro':'거시경제',
  'volatility':'변동성',
  'corporate-event':'기업 이벤트',
  'crypto':'가상자산'
});
function humanDomain(value){return DOMAIN_LABELS[value]||String(value||'기타').replaceAll('-',' ');}
function humanDriver(value){return DRIVER_LABELS[value]||String(value||'기타').replaceAll('-',' ');}
function generatedDay(){return String(DATA?.meta?.generated||'').slice(0,10);}
function dayDiff(from,to){
  const a=Date.parse(`${from}T00:00:00Z`),b=Date.parse(`${to}T00:00:00Z`);
  return Number.isFinite(a)&&Number.isFinite(b)?Math.round((b-a)/86400000):null;
}
function businessDayDiff(from,to){
  const start=new Date(`${from}T00:00:00Z`),end=new Date(`${to}T00:00:00Z`);
  if(!Number.isFinite(+start)||!Number.isFinite(+end)||end<=start)return 0;
  let count=0,cursor=new Date(start);
  while(cursor<end){cursor.setUTCDate(cursor.getUTCDate()+1);const day=cursor.getUTCDay();if(day!==0&&day!==6)count++;}
  return count;
}
function addIsoDays(value,days){
  const t=Date.parse(`${value}T00:00:00Z`);if(!Number.isFinite(t))return value;
  return new Date(t+days*86400000).toISOString().slice(0,10);
}
function scenarioVintage(){
  const scenario=DATA?.scenario||{},asof=scenario.asof||generatedDay();
  const calendarDays=dayDiff(asof,generatedDay()),businessDays=businessDayDiff(asof,generatedDay());
  const status=scenario.fallback||businessDays>3?'stale':businessDays>1?'aging':'current';
  return {asof,calendarDays:calendarDays==null?0:Math.max(0,calendarDays),businessDays,status,
    current:status==='current',method:scenario.method||'unknown',fallback:Boolean(scenario.fallback)};
}
function scenarioHistoryRows(){
  const rows=Array.isArray(DATA?.scenario_history)?DATA.scenario_history:[];
  return rows.filter(row=>row&&row.asof&&row.paths?.S1&&row.paths?.S2&&row.paths?.S3)
    .sort((a,b)=>String(a.asof).localeCompare(String(b.asof)));
}
function signedDelta(value,digits=0,suffix=''){
  if(!Number.isFinite(value))return '기록 없음';
  return `${value>0?'+':''}${Number(value).toFixed(digits)}${suffix}`;
}
function scenarioDeltaNarrative(base,current){
  const s1=current.paths.S1.prob-base.paths.S1.prob,s3=current.paths.S3.prob-base.paths.S3.prob;
  const median=(current.bands?.eoy_median??0)-(base.bands?.eoy_median??0);
  if(s1>=3)return '상방 돌파 경로가 확대됐습니다.';
  if(s3>=3)return '조정·횡보 경로가 확대됐습니다.';
  if(Math.abs(median)>=250)return '연말 가격 중심이 이동했습니다.';
  return '경로 분포는 큰 변화 없이 유지됐습니다.';
}
function scenarioStack(row,label){
  const description=['S1','S2','S3'].map(k=>`${k} ${row.paths[k].prob}%`).join(', ');
  return `<div class="scenario-stack-row"><span>${esc(label)}</span><div class="scenario-stack" role="img" aria-label="${esc(label+' 경로 분포 '+description)}">${['S1','S2','S3'].map(k=>`<i class="${k.toLowerCase()}" style="width:${row.paths[k].prob}%" title="${k} ${row.paths[k].prob}%"></i>`).join('')}</div><b>${row.paths.S1.prob}/${row.paths.S2.prob}/${row.paths.S3.prob}</b></div>`;
}
function scenarioDeltaBody(base,current){
  const anchor=current.anchor-base.anchor,anchorPct=base.anchor?anchor/base.anchor*100:null;
  const median=(current.bands?.eoy_median??0)-(base.bands?.eoy_median??0);
  const s1=current.paths.S1.prob-base.paths.S1.prob,s3=current.paths.S3.prob-base.paths.S3.prob;
  return `<div class="scenario-change-copy"><span>WHAT CHANGED · ${esc(base.asof)} → ${esc(current.asof)}</span><h2>${esc(scenarioDeltaNarrative(base,current))}</h2><p>저장된 시나리오 수치의 차이만 요약하며 뉴스나 이벤트를 원인으로 추론하지 않습니다.</p></div>
    <div class="scenario-change-metrics">
      <div><span>NASDAQ 앵커</span><strong class="${anchor>=0?'up':'down'}">${signedDelta(anchor,0)}</strong><small>${signedDelta(anchorPct,1,'%')}</small></div>
      <div><span>연말 중앙값</span><strong class="${median>=0?'up':'down'}">${signedDelta(median,0)}</strong><small>${num(current.bands?.eoy_median)}</small></div>
      <div><span>S1 · ATH 돌파</span><strong class="${s1>=0?'up':'down'}">${signedDelta(s1,0,'%p')}</strong><small>${current.paths.S1.prob}%</small></div>
      <div><span>S3 · 조정·횡보</span><strong class="${s3>0?'down':s3<0?'improve':''}">${signedDelta(s3,0,'%p')}</strong><small>${current.paths.S3.prob}%</small></div>
    </div>
    <div class="scenario-stacks">${scenarioStack(base,'이전')}${scenarioStack(current,'현재')}</div>`;
}
function scenarioChangePanel(interactive=false){
  const rows=scenarioHistoryRows();if(rows.length<2)return null;
  const current=rows[rows.length-1],model=DATA?.scenario?.model||{};
  const panel=el(`<section class="scenario-change" aria-labelledby="scenario-change-title"><div class="scenario-change-head"><div><span>SCENARIO CHANGE</span><strong id="scenario-change-title">시장 경로 변화 추적</strong></div><b>${rows.length} SNAPSHOTS</b></div>
    <div class="scenario-change-body" data-scenario-delta aria-live="polite"></div>
    ${interactive?`<div class="scenario-history-nav"><span>COMPARE FROM</span><div>${rows.slice(0,-1).map((row,index)=>`<button type="button" data-scenario-base="${index}" aria-pressed="${index===rows.length-2}">${esc(row.asof.slice(5))}</button>`).join('')}</div></div>
    <details class="model-receipt"><summary>MODEL RECEIPT · 산식과 한계 보기</summary><div><span>METHOD <b>${esc(DATA.scenario.method||'기록 없음')}</b></span><span>LOOKBACK <b>${model.lookback_days??'기록 없음'}일</b></span><span>PATHS <b>${model.n_paths?num(model.n_paths):'기록 없음'}</b></span><span>SEED <b>${model.seed??'기록 없음'}</b></span></div><p>${esc(DATA.scenario.note||'모델 설명이 기록되지 않았습니다.')}</p><small>${esc(DATA.scenario.source||'출처 기록 없음')}</small></details>`:''}
  </section>`);
  const output=panel.querySelector('[data-scenario-delta]');
  const render=index=>{output.innerHTML=scenarioDeltaBody(rows[index],current);panel.querySelectorAll('[data-scenario-base]').forEach(button=>button.setAttribute('aria-pressed',String(+button.dataset.scenarioBase===index)));};
  panel.querySelectorAll('[data-scenario-base]').forEach(button=>button.onclick=()=>render(+button.dataset.scenarioBase));
  render(rows.length-2);return panel;
}
function median(values){
  const a=values.filter(Number.isFinite).sort((x,y)=>x-y);if(!a.length)return null;
  const m=Math.floor(a.length/2);return a.length%2?a[m]:(a[m-1]+a[m])/2;
}
function isQuestionPinned(qid){return UI_STATE.pins.some(x=>x.hash==='#records/question/'+qid||x.hash==='#q/'+qid);}
function toggleQuestionPin(qid){
  const q=DATA?.questions?.find(x=>x.id===qid);if(!q)return;
  const hash='#records/question/'+qid,on=isQuestionPinned(qid),d={hash,title:q.title,type:'question'};
  UI_STATE.pins=on?UI_STATE.pins.filter(x=>x.hash!==hash):[d,...UI_STATE.pins.filter(x=>x.hash!==hash&&descriptorExists(x))].slice(0,8);
  saveUIState();syncQuestionActions();renderCompareTray();
  const old=document.getElementById('my-radar');if(old)old.replaceWith(myRadarPanel());
  showToast(on?'개인 레이더에서 제거했습니다.':'개인 레이더에 추가했습니다.');
  if(!commandLayer.hidden)renderCommandResults(commandInput.value);
}
function myRadarQuestions(){
  return UI_STATE.pins.filter(x=>x.type==='question').map(x=>DATA?.questions?.find(q=>'#records/question/'+q.id===x.hash||'#q/'+q.id===x.hash)).filter(Boolean);
}
function myRadarPanel(){
  const qs=myRadarQuestions();
  return el(`<section class="my-radar" id="my-radar" aria-labelledby="my-radar-title"><div class="panel-head"><div><h2 id="my-radar-title">MY RADAR</h2><p>이 기기에 고정한 질문을 빠르게 다시 봅니다.</p></div><a class="text-button" href="#records">질문 찾기</a></div>
    ${qs.length?`<div class="radar-pins">${qs.slice(0,6).map(q=>`<button type="button" class="radar-pin" data-open-q="${esc(q.id)}"><span>${p1(q.latest_prob)} · ${esc(humanDomain(q.domain))}</span><b>${esc(q.title)}</b><small>${q.deadline?esc(q.deadline):'수시 판정'} · ${roundLabel(q.n_rounds)}</small></button>`).join('')}</div>`:
    '<div class="radar-empty">예측 상세 또는 목록의 ☆ 버튼으로 질문을 고정하면 여기에 표시됩니다.</div>'}</section>`);
}
const REVIEW_DISMISSED_KEY='jin-review-dismissed-v1';
function reviewDismissedIds(){
  try{const value=JSON.parse(sessionStorage.getItem(REVIEW_DISMISSED_KEY)||'[]');return Array.isArray(value)?value.filter(x=>typeof x==='string'):[];}catch(_){return [];}
}
function dismissReviewQuestion(qid){
  const ids=[...new Set([...reviewDismissedIds(),qid])].slice(-40);
  try{sessionStorage.setItem(REVIEW_DISMISSED_KEY,JSON.stringify(ids));}catch(_){}
}
function selectDecisionItems({since=VISIT_SEEN_AT,includePinned=true,dueWithinDays=14,minAbsoluteDelta=5,limit=5}={}){
  const today=generatedDay(),sinceMs=since?Date.parse(since):null;
  return (DATA?.questions||[]).map(q=>{
    const history=DATA.forecast_history?.[q.id]||[],latest=history[history.length-1],delta=latestDelta(q.id);
    const latestTs=latest?.forecast_ts||q.latest_ts||'',latestMs=latestTs?Date.parse(latestTs):null;
    const days=q.deadline?dayDiff(today,q.deadline):null,pinned=isQuestionPinned(q.id),reasons=[],signals=[];
    const newSince=Number.isFinite(sinceMs)&&Number.isFinite(latestMs)&&latestMs>sinceMs;
    if(newSince){reasons.push(delta===0?'새 회차 · 확률 재확인':'새 예측 회차');signals.push('new');}
    if(delta!=null&&Math.abs(delta)>=minAbsoluteDelta){reasons.push(`직전 대비 ${delta>0?'+':''}${delta}%p`);signals.push('changed');}
    if(q.status==='active'&&days!=null&&days>=0&&days<=dueWithinDays){reasons.push(days===0?'오늘 판정':`D-${days} 판정 임박`);signals.push('due');}
    if(includePinned&&pinned){reasons.push('MY RADAR');signals.push('pinned');}
    const score=(newSince?220:0)+(days!=null&&days>=0&&days<=dueWithinDays?140-days:0)+(delta==null?0:Math.abs(delta)*4)+(pinned?28:0);
    return {q,reasons:[...new Set(reasons)],signals:[...new Set(signals)],score,delta,days,newSince};
  }).filter(x=>x.reasons.length).sort((a,b)=>b.score-a.score||String(a.q.deadline||'').localeCompare(String(b.q.deadline||''))).slice(0,limit);
}
function reviewQueueData(){
  const dismissed=new Set(reviewDismissedIds());
  return selectDecisionItems({limit:40}).filter(x=>!dismissed.has(x.q.id)).slice(0,5);
}
function reviewQueuePanel(){
  const items=reviewQueueData();
  return `<section class="utility-section"><div class="review-queue" role="region" aria-labelledby="review-queue-title">
    <div class="review-queue-head"><div><span>DECISION SUPPORT</span><h3 id="review-queue-title">REVIEW QUEUE</h3><small>변화 · 판정 임박 · MY RADAR만 모았습니다.</small></div><b>${items.length}</b></div>
    ${items.length?`<div class="review-items">${items.map(({q,reasons})=>`<div class="review-item">
      <button type="button" class="review-open" data-open-q="${esc(q.id)}"><span>${esc(q.title)}<small>${esc(reasons.join(' · '))}</small></span><strong class="${hasNumeric(q.latest_prob)?'':'pending-value'}">${p1(q.latest_prob)}</strong></button>
      <button type="button" class="review-dismiss" data-review-dismiss="${esc(q.id)}" aria-label="${esc(q.title)} 이번 세션에서 숨기기">×</button>
    </div>`).join('')}</div>`:'<p class="review-empty">지금 다시 확인할 변화나 임박한 판정이 없습니다.</p>'}
  </div></section>`;
}
function cleanCompareIds(ids=UI_STATE.compare){
  return [...new Set(ids)].filter(id=>DATA?.questions?.some(q=>q.id===id)).slice(0,3);
}
function isCompared(qid){return cleanCompareIds().includes(qid);}
function setCompareQuestions(ids){
  const prev=cleanCompareIds(),next=cleanCompareIds(ids);
  UI_STATE.compare=next;
  if(!next.length){UI_STATE.compareCollapsed=false;UI_STATE.compareAutoExpanded=false;}
  else if(next.length===1&&!prev.length)UI_STATE.compareCollapsed=true;
  else if(next.length>=2&&prev.length<2&&!UI_STATE.compareAutoExpanded){UI_STATE.compareCollapsed=false;UI_STATE.compareAutoExpanded=true;}
  saveUIState();renderCompareTray();syncQuestionActions();
}
function toggleCompareQuestion(qid){
  const ids=cleanCompareIds(),on=ids.includes(qid);
  if(!on&&ids.length>=3)return showToast('비교는 최대 3개까지 선택할 수 있습니다.','warning');
  const next=on?ids.filter(id=>id!==qid):[...ids,qid];
  setCompareQuestions(next);
  showToast(on?'비교 선택에서 제외했습니다.':'비교 선택에 추가했습니다.');
  if(!on&&next.length===2&&!location.hash.startsWith('#records/compare/'))location.hash='#records/compare/'+next.join(',');
}
function syncQuestionActions(root=document){
  root.querySelectorAll('[data-pin-q]').forEach(b=>{const on=isQuestionPinned(b.dataset.pinQ),icon=b.querySelector('[data-pin-icon]');b.setAttribute('aria-pressed',String(on));if(icon)icon.textContent=on?'★':'☆';else b.textContent=on?'★':'☆';});
  root.querySelectorAll('[data-compare-q]').forEach(b=>{const on=isCompared(b.dataset.compareQ);b.setAttribute('aria-pressed',String(on));});
}
function toggleCompareTray(){
  UI_STATE.compareCollapsed=!UI_STATE.compareCollapsed;saveUIState();renderCompareTray();
}
function renderCompareTray(){
  if(!DATA)return;const ids=cleanCompareIds();UI_STATE.compare=ids;
  compareTray.hidden=!ids.length||!location.hash.startsWith('#records');
  const collapsed=location.hash.startsWith('#records/compare/')||UI_STATE.compareCollapsed;
  compareTray.classList.toggle('is-collapsed',collapsed);compareToggle.setAttribute('aria-expanded',String(!collapsed));compareCount.textContent=String(ids.length);
  compareToggle.setAttribute('aria-label',collapsed?`비교 선택 ${ids.length}개 펼치기`:`비교 선택 ${ids.length}개 접기`);
  compareItems.innerHTML=ids.map(id=>{const q=DATA.questions.find(x=>x.id===id);return `<button type="button" class="compare-chip" data-remove-compare="${esc(id)}"><b>${p1(q.latest_prob)}</b><span>${esc(q.title)}</span><i>×</i></button>`;}).join('');
  compareOpen.disabled=ids.length<2;compareOpen.textContent=ids.length<2?'1개 더 선택':'비교 보기';
}
function icsEscape(value){return String(value||'').replaceAll('\\','\\\\').replaceAll('\n','\\n').replaceAll(',','\\,').replaceAll(';','\\;');}
function downloadQuestionCalendar(ids=null){
  const wanted=ids?new Set(ids):null,qs=(DATA?.questions||[]).filter(q=>q.status==='active'&&q.deadline&&(!wanted||wanted.has(q.id)));
  if(!qs.length)return showToast('저장할 판정일이 없습니다.','warning');
  const stamp=generatedDay().replaceAll('-','')+'T000000Z';
  const base=location.origin+location.pathname;
  const events=qs.map(q=>`BEGIN:VEVENT\r\nUID:${icsEscape(q.id)}@jin-investing\r\nDTSTAMP:${stamp}\r\nDTSTART;VALUE=DATE:${q.deadline.replaceAll('-','')}\r\nDTEND;VALUE=DATE:${addIsoDays(q.deadline,1).replaceAll('-','')}\r\nSUMMARY:${icsEscape('[예측 판정] '+q.title)}\r\nDESCRIPTION:${icsEscape(`현재 확률 ${p1(q.latest_prob)} · ${humanDomain(q.domain)} · ${roundLabel(q.n_rounds)}`)}\r\nURL:${icsEscape(base+'#records/question/'+q.id)}\r\nEND:VEVENT`).join('\r\n');
  const content=`BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Jin's Investing//Forecast Calendar//KO\r\nCALSCALE:GREGORIAN\r\nMETHOD:PUBLISH\r\n${events}\r\nEND:VCALENDAR\r\n`;
  const url=URL.createObjectURL(new Blob([content],{type:'text/calendar;charset=utf-8'})),a=document.createElement('a');
  a.href=url;a.download=ids?.length===1?`${ids[0]}-deadline.ics`:'jin-investing-deadlines.ics';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  showToast(`${qs.length}개 판정일 캘린더를 저장했습니다.`);
}
function quickPeekProbability(probability){
  if(probability==null||probability==='')return {band:'데이터 대기',copy:'아직 확률이 없어 근거가 쌓이는 과정을 먼저 봐야 합니다.'};
  const p=Number(probability);
  if(!Number.isFinite(p))return {band:'데이터 대기',copy:'아직 확률이 없어 근거가 쌓이는 과정을 먼저 봐야 합니다.'};
  if(p>=70)return {band:'뚜렷한 우세',copy:'현재 근거는 이 경로를 뚜렷한 우세로 보고 있습니다.'};
  if(p>=55)return {band:'우세',copy:'현재는 우세한 쪽이지만 뒤집힐 여지를 함께 봐야 합니다.'};
  if(p>=45)return {band:'경합',copy:'양쪽 가능성이 팽팽해 방향 확인이 더 필요합니다.'};
  if(p>=30)return {band:'보조 경로',copy:'기본 경로는 아니지만 무시하기 어려운 가능성입니다.'};
  return {band:'낮은 가능성',copy:'현재는 가능성이 낮은 보조 경로로 보고 있습니다.'};
}
function quickPeekTrend(delta){
  if(delta==null)return '첫 회차라 변화보다 초기 기준선에 의미가 있습니다.';
  const size=Math.abs(delta);
  if(size===0)return '직전 회차와 같은 확률을 유지하고 있습니다.';
  if(delta>=5)return `직전 회차보다 ${size}%p 올라 관찰 강도가 커졌습니다.`;
  if(delta<=-5)return `직전 회차보다 ${size}%p 내려 우세도가 약해졌습니다.`;
  return `직전 회차 대비 ${delta>0?'소폭 상승':'소폭 하락'}해 비슷한 범위를 유지합니다.`;
}
function deadlineWindow(q){
  if(!q.deadline)return {short:'수시 판정',next:'새 데이터와 조건 충족 여부 확인'};
  const asOf=String(DATA?.meta?.generated||'').slice(0,10);
  const end=Date.parse(`${q.deadline}T00:00:00Z`),start=Date.parse(`${asOf}T00:00:00Z`);
  if(!Number.isFinite(end)||!Number.isFinite(start))return {short:q.deadline,next:'판정 기준과 공식 자료 확인'};
  const days=Math.round((end-start)/86400000);
  if(days>30)return {short:`D-${days}`,next:'주간 변화와 핵심 근거 확인'};
  if(days>7)return {short:`D-${days}`,next:'이벤트 변동과 판정 기준 확인'};
  if(days>0)return {short:`D-${days}`,next:'판정 임박 · 근거 재확인'};
  if(days===0)return {short:'D-DAY',next:'공식 자료와 해소 여부 확인'};
  return {short:`D+${Math.abs(days)}`,next:'판정 시점 경과 · 해소 여부 확인'};
}
function quickPeekCopy(anchor,q){
  const delta=latestDelta(q.id),prob=quickPeekProbability(q.latest_prob),deadline=deadlineWindow(q);
  const context=anchor.classList.contains('forecast-card')?'WHY IT MATTERS':anchor.closest('.deadline-list')?'DECISION WINDOW':'FORECAST CONTEXT';
  const drivers=(q.drivers||[]).slice(0,2).map(x=>DRIVER_LABELS[x]||String(x).replaceAll('-',' '));
  return {
    context,prob,deadline,drivers,
    meta:`${DOMAIN_LABELS[q.domain]||q.domain} · ${q.latest_prob==null?'확률 대기':`${q.latest_prob}% 기준`}`,
    trend:quickPeekTrend(delta),
    round:q.n_rounds?`R${q.n_rounds} · ${delta==null?'첫 기준선':`직전 대비 ${delta>0?'+':''}${delta}%p`}`:'예측 대기'
  };
}
function showQuickPeek(anchor){
  if(blockingLayerOpen()||window.matchMedia('(pointer: coarse)').matches)return;
  const q=DATA?.questions?.find(x=>x.id===anchor.dataset.q);if(!q)return;
  const view=quickPeekCopy(anchor,q);
  quickPeek.innerHTML=`<div class="peek-top"><span>${esc(view.meta)}</span><b>${esc(view.context)}</b></div>
    <div class="peek-summary"><span>한 줄 해석 · ${esc(view.prob.band)}</span><strong>${esc(view.prob.copy)}</strong><p>${esc(view.trend)}</p></div>
    <div class="peek-glance">
      <div><span>판정 시계</span><strong>${esc(view.deadline.short)}</strong></div>
      <div><span>다음 확인</span><strong>${esc(view.deadline.next)}</strong></div>
    </div>
    ${view.drivers.length?`<div class="peek-drivers"><span class="peek-driver-label">관찰 변수</span><div class="peek-driver-list">${view.drivers.map(x=>`<span>${esc(x)}</span>`).join('')}</div></div>`:''}`;
  peekAnchor=anchor;anchor.setAttribute('aria-describedby','quick-peek');quickPeek.hidden=false;quickPeek.setAttribute('aria-hidden','false');
  requestAnimationFrame(()=>{const r=anchor.getBoundingClientRect(),w=quickPeek.offsetWidth,h=quickPeek.offsetHeight;
    let left=r.right+14,top=r.top+(r.height-h)/2;if(left+w>window.innerWidth-14)left=r.left-w-14;
    left=Math.max(14,Math.min(window.innerWidth-w-14,left));top=Math.max(14,Math.min(window.innerHeight-h-14,top));
    quickPeek.style.left=left+'px';quickPeek.style.top=top+'px';
  });
}
function bindQuickPeek(root){
  root.querySelectorAll('[data-q]').forEach(node=>{
    if(node.dataset.peekBound)return;node.dataset.peekBound='1';
    node.addEventListener('pointerenter',()=>{clearTimeout(peekTimer);peekTimer=setTimeout(()=>showQuickPeek(node),220);});
    node.addEventListener('pointerleave',()=>{if(document.activeElement!==node)closeQuickPeek();});
    node.addEventListener('focus',()=>showQuickPeek(node));node.addEventListener('blur',closeQuickPeek);
  });
}
function bindExperienceLayer(root){buildSectionNavigator(root);bindQuickPeek(root);animateNumbers(root);}

function briefingScenes(){
  const sc=DATA.scenario,upProb=sc.paths.S1.prob+sc.paths.S2.prob,rangeProb=sc.paths.S3.prob;
  const vintage=scenarioVintage(),thesis=vintage.status==='stale'
    ?{lead:'시장 시나리오 갱신이 필요합니다.',accent:`마지막 유효 기준은 ${vintage.asof}입니다.`}
    :marketThesis(upProb,rangeProb);
  const featured=featureQs()[0]||DATA.questions.find(q=>q.status==='active');
  const next=upcoming(1)[0]||featured,d=featured?latestDelta(featured.id):null;
  const featuredReady=hasNumeric(featured?.latest_prob),nextReady=hasNumeric(next?.latest_prob);
  return [
    {eyebrow:'01 · MARKET STANCE',lead:thesis.lead,accent:thesis.accent,metric:vintage.status==='stale'?'STALE':upProb,unit:vintage.status==='stale'?'':'%',pending:vintage.status==='stale',description:vintage.status==='stale'?`보관된 ${vintage.asof} 경로는 시장 맵에서 확인할 수 있지만 현재 판단에는 사용하지 않습니다.`:`상승 경로 ${upProb}%와 조정·횡보 ${rangeProb}%를 분리해 읽습니다. 두 체계는 질문별 확률과 합산하지 않습니다.`,visual:vintage.status==='stale'?0:upProb},
    {eyebrow:'02 · FEATURED FORECAST',lead:'대표 예측의 현재 확률',accent:featured?.title||'진행 중인 질문',metric:featuredReady?featured.latest_prob:'산출 전',unit:featuredReady?'%':'',pending:!featuredReady,description:featuredReady?`${roundLabel(featured.n_rounds)} · ${d==null?'첫 예측':`직전 회차 대비 ${d>=0?'+':''}${d}%p`} · ${featured.domain}`:'아직 등록된 예측 회차가 없습니다.',visual:featuredReady?featured.latest_prob:0,qid:featured?.id},
    {eyebrow:'03 · NEXT DECISION',lead:'다음 판정일을 먼저 확인하세요.',accent:next?.deadline||'예정된 판정 없음',metric:nextReady?next.latest_prob:'산출 전',unit:nextReady?'%':'',pending:!nextReady,description:next?`${next.title}${nextReady?'':' · 아직 등록된 예측 회차 없음'}`:'현재 등록된 판정 일정이 없습니다.',visual:nextReady?next.latest_prob:0,qid:next?.id}
  ];
}
function renderBriefingStep(){
  const scenes=briefingScenes(),scene=scenes[briefingIndex],total=scenes.length;
  briefingStepLabel.textContent=String(briefingIndex+1).padStart(2,'0')+' / '+String(total).padStart(2,'0');
  [...briefingProgress.children].forEach((x,i)=>{x.classList.toggle('is-complete',i<briefingIndex);x.classList.toggle('is-active',i===briefingIndex);});
  briefingPrev.disabled=briefingIndex===0;briefingNext.textContent=briefingIndex===total-1?'DONE':'NEXT →';
  briefingContent.innerHTML=`<div class="briefing-scene"><div class="briefing-copy">
    <p class="eyebrow">${esc(scene.eyebrow)}</p><h2>${esc(scene.lead)}<em>${esc(scene.accent)}</em></h2>
    <p>${esc(scene.description)}</p>${scene.qid?`<button type="button" class="briefing-detail" data-brief-q="${esc(scene.qid)}">예측 상세 열기 ↗</button>`:''}
    </div><div class="briefing-visual${scene.pending?' is-pending':''}" style="--brief-signal:${Number(scene.visual)||0}"><b>${scene.metric}<small>${esc(scene.unit)}</small></b></div></div>`;
  animateNumbers(briefingContent);
}
function setBriefing(open,restoreFocus=true){
  if(open){
    briefingReturnFocus=document.activeElement;closeQuickPeek();clearTimeout(toastTimer);toastRegion.innerHTML='';
    if(document.body.classList.contains('drawer-open'))setDrawer(false,false);
    if(!commandLayer.hidden)setCommand(false,false);if(!utilityLayer.hidden)setUtility(false,false);if(!shortcutLayer.hidden)setShortcuts(false,false);
    briefingIndex=0;renderBriefingStep();
  }
  briefingLayer.hidden=!open;briefingLayer.setAttribute('aria-hidden',String(!open));document.body.classList.toggle('briefing-open',open);
  syncModalInert();
  if(open)requestAnimationFrame(()=>briefingClose.focus());else if(restoreFocus&&briefingReturnFocus?.focus)briefingReturnFocus.focus();
}
function stepBriefing(delta){
  const last=briefingScenes().length-1;
  if(delta>0&&briefingIndex===last)return setBriefing(false);
  briefingIndex=Math.max(0,Math.min(last,briefingIndex+delta));renderBriefingStep();
}
function currentDescriptor(){
  const hash=location.hash||'#today';
  if(hash.startsWith('#records/question/')){
    const id=hash.slice(18),q=DATA?.questions?.find(x=>x.id===id);
    return q?{hash,title:q.title,type:'question'}:null;
  }
  if(hash.startsWith('#records/compare/'))return {hash,title:'예측 질문 비교',type:'route'};
  const r=COMMAND_ROUTES.find(x=>x.hash===hash);
  return r?{hash,title:r.title,type:'route'}:null;
}
function descriptorExists(item){
  if(!item?.hash)return false;
  if(item.hash.startsWith('#records/question/'))return !!DATA?.questions?.some(q=>'#records/question/'+q.id===item.hash);
  if(item.hash.startsWith('#records/compare/'))return item.hash.slice(17).split(',').filter(id=>DATA?.questions?.some(q=>q.id===id)).length>=2;
  return COMMAND_ROUTES.some(r=>r.hash===item.hash);
}
function isCurrentPinned(){const d=currentDescriptor();return !!d&&UI_STATE.pins.some(x=>x.hash===d.hash);}
function updateUtilityButtons(){
  const pinned=isCurrentPinned();
  document.querySelectorAll('.pin-current').forEach(b=>{b.setAttribute('aria-pressed',String(pinned));b.setAttribute('aria-label',pinned?'현재 화면 고정 해제':'현재 화면 고정');const s=b.querySelector('span');if(s)s.textContent=pinned?'★':'☆';});
}
function recordRecent(){
  const d=currentDescriptor();if(!d)return;
  UI_STATE.recent=[d,...UI_STATE.recent.filter(x=>x.hash!==d.hash&&descriptorExists(x))].slice(0,6);
  saveUIState();updateUtilityButtons();
}
function toggleCurrentPin(){
  const d=currentDescriptor();if(!d)return showToast('이 화면은 고정할 수 없습니다.','warning');
  const on=UI_STATE.pins.some(x=>x.hash===d.hash);
  UI_STATE.pins=on?UI_STATE.pins.filter(x=>x.hash!==d.hash):[d,...UI_STATE.pins.filter(x=>x.hash!==d.hash&&descriptorExists(x))].slice(0,8);
  saveUIState();updateUtilityButtons();syncQuestionActions();showToast(on?'고정을 해제했습니다.':'현재 화면을 고정했습니다.');
  if(!commandLayer.hidden)renderCommandResults(commandInput.value);
}
function showToast(message,tone='success'){
  clearTimeout(toastTimer);toastRegion.innerHTML=`<div class="toast ${tone==='warning'?'warning':''}" role="status">${esc(message)}</div>`;
  toastTimer=setTimeout(()=>{toastRegion.innerHTML='';},2400);
}
function copyText(text){
  if(navigator.clipboard?.writeText)return navigator.clipboard.writeText(text);
  return new Promise((resolve,reject)=>{const t=document.createElement('textarea');t.value=text;t.setAttribute('readonly','');t.style.position='fixed';t.style.opacity='0';document.body.appendChild(t);t.select();
    try{document.execCommand('copy')?resolve():reject(new Error('copy failed'));}catch(e){reject(e);}finally{t.remove();}});
}
async function shareCurrentView(nativeShare=true){
  const d=currentDescriptor(),payload={title:d?.title||document.title,text:d?.title||document.title,url:location.href};
  try{
    if(nativeShare&&navigator.share){await navigator.share(payload);showToast('공유 메뉴를 열었습니다.');}
    else{await copyText(payload.url);showToast('현재 화면 링크를 복사했습니다.');}
  }catch(e){if(e?.name!=='AbortError')showToast('공유하지 못했습니다. 링크 복사를 이용해 주세요.','warning');}
}
function canonicalShareUrl(){
  let url=new URL(location.href);url.search='';
  if(url.href.length>200){url.hash='#today';}
  return url.href.slice(0,200);
}
function honestSharePayload(){
  const descriptor=currentDescriptor(),screenTitle=document.querySelector('main h1')?.textContent.trim()||descriptor?.title||document.title;
  const asof=DATA?.scenario?.asof||String(DATA?.meta?.generated||'').slice(0,10)||'등록 스냅샷';
  const primary=document.querySelector('.lookup-metrics .lookup-primary strong')?.textContent.trim(),median=document.querySelector('.lookup-metrics>div:nth-child(2) strong')?.textContent.trim();
  const distribution=primary?`10–90% 구간 ${primary}${median?` · 중앙값 ${median}`:''} (모델 조건부)\n`:'';
  const url=canonicalShareUrl();
  return {title:`${screenTitle} — Jin's Investing Prediction`,url,text:`${distribution}${screenTitle} — Jin's Investing Prediction\n시장 기준 ${asof} · 조건부 시나리오이며 단일 가격 제시·투자자문이 아닙니다.\n${url}`};
}
function configureShareTargets(payload){
  const encodedUrl=encodeURIComponent(payload.url),encodedTitle=encodeURIComponent(payload.title),encodedText=encodeURIComponent(payload.text);
  const targets={
    gmail:`https://mail.google.com/mail/?view=cm&fs=1&su=${encodedTitle}&body=${encodedText}`,
    mail:`mailto:?subject=${encodedTitle}&body=${encodedText}`,
    'naver-blog':`https://blog.naver.com/openapi/share?url=${encodedUrl}&title=${encodedTitle}`,
    'naver-band':`https://band.us/plugin/share?body=${encodedText}&route=${encodedUrl}`,
    line:`https://social-plugins.line.me/lineit/share?url=${encodedUrl}&text=${encodedText}`,
    telegram:`https://t.me/share/url?url=${encodedUrl}&text=${encodedText}`,
    x:`https://twitter.com/intent/tweet?text=${encodedText}&url=${encodedUrl}`
  };
  Object.entries(targets).forEach(([target,href])=>{const link=shareLayer.querySelector(`[data-share-target="${target}"]`);if(link)link.href=href;});
  shareSummary.innerHTML=`<strong>${esc(payload.title)}</strong><p>${esc(payload.text.replace(`\n${payload.url}`,''))}</p><code>${esc(payload.url)}</code>`;
  if(self.QrCreator&&shareQrCanvas)QrCreator.render({text:payload.url,size:188,ecLevel:'M',fill:'#1d2925',background:'#ffffff',radius:.15,quiet:2},shareQrCanvas);
}
function setShare(open,restoreFocus=true){
  if(open){shareReturnFocus=document.activeElement;closeQuickPeek();if(document.body.classList.contains('drawer-open'))setDrawer(false,false);if(!commandLayer.hidden)setCommand(false,false);if(!utilityLayer.hidden)setUtility(false,false);if(!shortcutLayer.hidden)setShortcuts(false,false);if(!briefingLayer.hidden)setBriefing(false,false);configureShareTargets(honestSharePayload());}
  shareLayer.hidden=!open;shareLayer.setAttribute('aria-hidden',String(!open));document.body.classList.toggle('share-open',open);syncModalInert();
  if(open)requestAnimationFrame(()=>shareClose.focus());else if(restoreFocus&&shareReturnFocus?.focus)shareReturnFocus.focus();
}
async function enhancedShareCurrentView(nativeShare=true){
  const payload=honestSharePayload();
  try{
    if(nativeShare&&navigator.share&&window.matchMedia('(pointer:coarse)').matches){await navigator.share(payload);showToast('기기 공유 메뉴를 열었습니다.');}
    else if(!nativeShare){await copyText(payload.url);showToast('현재 화면 링크를 복사했습니다.');}
    else setShare(true);
  }catch(error){if(error?.name!=='AbortError')showToast('공유하지 못했습니다. 링크 복사를 이용해 주세요.','warning');}
}
shareCurrentView=enhancedShareCurrentView;
shareClose.addEventListener('click',()=>setShare(false));document.getElementById('share-scrim').addEventListener('click',()=>setShare(false));
shareLayer.addEventListener('click',event=>{const copy=event.target.closest('[data-share-target="copy"]');if(!copy)return;copyText(honestSharePayload().url).then(()=>showToast('현재 화면 링크를 복사했습니다.')).catch(()=>showToast('링크를 복사하지 못했습니다.','warning'));});
document.addEventListener('keydown',event=>{if(shareLayer.hidden)return;if(event.key==='Tab')trapFocus(event,sharePopover);else if(event.key==='Escape'){event.preventDefault();setShare(false);}});

function copyCurrentSummary(){
  const d=currentDescriptor(),headline=document.querySelector('main h1')?.textContent.trim()||d?.title||document.title;
  copyText(`${headline}\n${location.href}`).then(()=>showToast('화면 요약을 복사했습니다.')).catch(()=>showToast('요약을 복사하지 못했습니다.','warning'));
}
function freshnessInfo(){
  const raw=DATA?.meta?.generated||'',stamp=Date.parse(/[zZ]|[+-]\d{2}:?\d{2}$/.test(raw)?raw:raw+'+09:00');
  const hours=Number.isFinite(stamp)?Math.max(0,(Date.now()-stamp)/36e5):999;
  const base=hours<=24?{label:'CURRENT',cls:'status-current'}:(hours<=72?{label:'AGING',cls:'status-aging'}:{label:'STALE',cls:'status-stale'});
  const scenarioStatus=scenarioVintage().status;
  if(scenarioStatus==='stale')return {label:'STALE',cls:'status-stale'};
  if(scenarioStatus==='aging'&&base.label==='CURRENT')return {label:'AGING',cls:'status-aging'};
  return base;
}
function updateFreshnessBadges(){
  const f=freshnessInfo();
  document.querySelectorAll('.rail-status,.drawer-meta').forEach(x=>{x.classList.remove('status-current','status-aging','status-stale');x.classList.add(f.cls);});
  document.querySelectorAll('.freshness-label').forEach(x=>x.textContent=f.label);
}
function renderUtilityPanel(){
  const f=freshnessInfo(),questions=DATA?.questions||[],history=DATA?.forecast_history||{};
  const active=questions.filter(q=>q.status==='active').length,resolved=questions.length-active;
  const rounds=Object.values(history).reduce((n,x)=>n+(Array.isArray(x)?x.length:0),0);
  const generated=(DATA?.meta?.generated||'—').replace('T',' ').slice(0,16)+' KST',note=currentNote(),pinnedQs=myRadarQuestions();
  utilityContent.innerHTML=`${reviewQueuePanel()}<section class="utility-section"><div class="utility-label">Data status</div>
    <div class="freshness-card ${f.cls}"><div><b>${f.label}</b><small>SELF-CONTAINED SNAPSHOT</small></div><strong>${esc(generated)}</strong></div>
    <div class="utility-stats"><div><span>QUESTIONS</span><strong>${questions.length}</strong></div><div><span>ACTIVE</span><strong>${active}</strong></div><div><span>RESOLVED</span><strong>${resolved}</strong></div><div><span>ROUNDS</span><strong>${rounds}</strong></div></div></section>
    <section class="utility-section"><div class="utility-label">View density</div><div class="segmented-control">
      <button type="button" data-util="density" data-value="comfortable" class="${UI_STATE.density==='comfortable'?'active':''}">Comfortable</button>
      <button type="button" data-util="density" data-value="compact" class="${UI_STATE.density==='compact'?'active':''}">Compact</button></div></section>
    <section class="utility-section"><div class="utility-label">Motion</div><div class="segmented-control">
      <button type="button" data-util="motion" data-value="adaptive" class="${UI_STATE.motion==='adaptive'?'active':''}">Adaptive</button>
      <button type="button" data-util="motion" data-value="reduced" class="${UI_STATE.motion==='reduced'?'active':''}">Reduced</button></div></section>
    <section class="utility-section"><div class="utility-label">Workspace</div><div class="utility-list">
      <button type="button" data-util="pin">현재 화면 ${isCurrentPinned()?'고정 해제':'고정'}<span>${isCurrentPinned()?'★':'☆'}</span></button>
      <button type="button" data-util="briefing">3단계 시장 브리핑<span>B</span></button>
      <button type="button" data-util="focus">${document.body.classList.contains('focus-mode')?'집중 모드 종료':'집중 모드 시작'}<span>F</span></button>
      <button type="button" data-util="shortcuts">키보드 단축키<span>?</span></button></div></section>
    <section class="utility-section"><div class="utility-label">My Radar · ${pinnedQs.length}</div><div class="utility-list">
      ${pinnedQs.length?pinnedQs.slice(0,5).map(q=>`<button type="button" data-open-q="${esc(q.id)}">${esc(q.title)}<span>${p1(q.latest_prob)}</span></button>`).join(''):
      '<button type="button" data-util-route="#records">고정한 질문이 없습니다<span>＋</span></button>'}</div></section>
    <section class="utility-section"><div class="utility-label">Research note · This device</div><div class="note-editor">
      <label for="workspace-note" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)">현재 화면 메모</label>
      <textarea id="workspace-note" maxlength="700" placeholder="이 화면에 대한 판단, 확인할 조건, 다음 행동을 기록하세요.">${esc(note)}</textarea>
      <div class="note-meta"><span id="note-save-state">현재 기기에 저장됨 · <b id="note-count">${note.length}</b>/700</span><button type="button" data-util="copy-note">메모 복사</button></div>
    </div></section>
    <section class="utility-section"><div class="utility-label">Output</div><div class="utility-list">
      <button type="button" data-util="share">현재 화면 공유<span>↗</span></button>
      <button type="button" data-util="copy">링크 복사<span>⌘C</span></button>
      <button type="button" data-util="summary">화면 요약 복사<span>TXT</span></button>
      <button type="button" data-util="print">인쇄 / PDF 저장<span>PDF</span></button></div></section>`;
}
function setUtility(open,restoreFocus=true){
  if(open){
    closeQuickPeek();if(!briefingLayer.hidden)setBriefing(false,false);
    const fromDrawer=document.body.classList.contains('drawer-open');utilityReturnFocus=fromDrawer?menuOpen:document.activeElement;
    if(fromDrawer)setDrawer(false,false);if(!commandLayer.hidden)setCommand(false,false);if(!shortcutLayer.hidden)setShortcuts(false,false);
    renderUtilityPanel();
  }
  utilityLayer.hidden=!open;utilityLayer.setAttribute('aria-hidden',String(!open));document.body.classList.toggle('utility-open',open);
  syncModalInert();
  if(open)requestAnimationFrame(()=>utilityClose.focus());else if(restoreFocus&&utilityReturnFocus?.focus)utilityReturnFocus.focus();
}
function setShortcuts(open,restoreFocus=true){
  if(open){
    closeQuickPeek();if(!briefingLayer.hidden)setBriefing(false,false);
    const fromUtility=!utilityLayer.hidden;
    shortcutReturnFocus=fromUtility?(utilityReturnFocus||document.querySelector('.rail-command')):document.activeElement;
    if(!commandLayer.hidden)setCommand(false,false);if(fromUtility)setUtility(false,false);if(document.body.classList.contains('drawer-open'))setDrawer(false,false);
  }
  shortcutLayer.hidden=!open;shortcutLayer.setAttribute('aria-hidden',String(!open));document.body.classList.toggle('shortcut-open',open);
  syncModalInert();
  if(open)requestAnimationFrame(()=>shortcutClose.focus());else if(restoreFocus&&shortcutReturnFocus?.focus)shortcutReturnFocus.focus();
}
function setFocusMode(on){
  document.body.classList.toggle('focus-mode',on);focusExit.hidden=!on;
  try{if(on)sessionStorage.setItem('jin-focus','1');else sessionStorage.removeItem('jin-focus');}catch(_){}
  if(!utilityLayer.hidden)renderUtilityPanel();showToast(on?'집중 모드를 켰습니다.':'집중 모드를 종료했습니다.');
}
function setDensity(value){
  UI_STATE.density=value==='compact'?'compact':'comfortable';saveUIState();document.body.classList.toggle('density-compact',UI_STATE.density==='compact');
  if(!utilityLayer.hidden)renderUtilityPanel();showToast(UI_STATE.density==='compact'?'Compact 보기를 적용했습니다.':'Comfortable 보기를 적용했습니다.');
}
function printCurrentView(){setUtility(false,false);setTimeout(()=>window.print(),80);}
function trapFocus(e,container){
  if(e.key!=='Tab')return;const nodes=[...container.querySelectorAll('button,input,textarea,select,[href],[tabindex]:not([tabindex="-1"])')].filter(x=>!x.disabled&&x.offsetParent!==null);
  if(!nodes.length)return;const first=nodes[0],last=nodes[nodes.length-1];
  if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
}
document.getElementById('utility-scrim').addEventListener('click',()=>setUtility(false));
utilityClose.addEventListener('click',()=>setUtility(false));
document.getElementById('shortcut-scrim').addEventListener('click',()=>setShortcuts(false));
shortcutClose.addEventListener('click',()=>setShortcuts(false));
focusExit.addEventListener('click',()=>setFocusMode(false));
utilityContent.addEventListener('click',e=>{const dismiss=e.target.closest('[data-review-dismiss]');if(dismiss){dismissReviewQuestion(dismiss.dataset.reviewDismiss);renderUtilityPanel();showToast('이번 세션의 검토 큐에서 숨겼습니다.');return;}
  const q=e.target.closest('[data-open-q]');if(q){setUtility(false,false);location.hash='#records/question/'+q.dataset.openQ;return;}
  const routeButton=e.target.closest('[data-util-route]');if(routeButton){setUtility(false,false);location.hash=routeButton.dataset.utilRoute;return;}
  const b=e.target.closest('button[data-util]');if(!b)return;const a=b.dataset.util;
  if(a==='density')setDensity(b.dataset.value);else if(a==='motion')setMotion(b.dataset.value);else if(a==='pin'){toggleCurrentPin();renderUtilityPanel();}else if(a==='focus')setFocusMode(!document.body.classList.contains('focus-mode'));
  else if(a==='briefing')setBriefing(true);else if(a==='shortcuts')setShortcuts(true);else if(a==='copy-note')copyCurrentNote();
  else if(a==='share')shareCurrentView(true);else if(a==='copy')shareCurrentView(false);else if(a==='summary')copyCurrentSummary();else if(a==='print')printCurrentView();
});
utilityContent.addEventListener('input',e=>{if(e.target.id!=='workspace-note')return;saveCurrentNote(e.target.value);
  const count=utilityContent.querySelector('#note-count');if(count)count.textContent=e.target.value.length;
  const state=utilityContent.querySelector('#note-save-state');if(state)state.firstChild.textContent='현재 기기에 저장됨 · ';
});
document.addEventListener('click',e=>{const b=e.target.closest('[data-action]');if(!b)return;const a=b.dataset.action;
  if(a==='pin')toggleCurrentPin();else if(a==='share')shareCurrentView(true);else if(a==='utility')setUtility(true);else if(a==='briefing')setBriefing(true);
});
app().addEventListener('click',e=>{
  const open=e.target.closest('[data-open-q]');if(open){e.preventDefault();location.hash='#records/question/'+open.dataset.openQ;return;}
  const pin=e.target.closest('[data-pin-q]');if(pin){e.preventDefault();e.stopPropagation();toggleQuestionPin(pin.dataset.pinQ);return;}
  const compare=e.target.closest('[data-compare-q]');if(compare){e.preventDefault();e.stopPropagation();toggleCompareQuestion(compare.dataset.compareQ);return;}
  const calendar=e.target.closest('[data-calendar-q]');if(calendar){e.preventDefault();e.stopPropagation();downloadQuestionCalendar([calendar.dataset.calendarQ]);return;}
  if(e.target.closest('[data-calendar-all]')){e.preventDefault();downloadQuestionCalendar();return;}
});
compareItems.addEventListener('click',e=>{const b=e.target.closest('[data-remove-compare]');if(b)toggleCompareQuestion(b.dataset.removeCompare);});
compareClear.addEventListener('click',()=>setCompareQuestions([]));
compareOpen.addEventListener('click',()=>{const ids=cleanCompareIds();if(ids.length>=2)location.hash='#records/compare/'+ids.join(',');});
compareToggle.addEventListener('click',toggleCompareTray);
document.getElementById('briefing-scrim').addEventListener('click',()=>setBriefing(false));
briefingClose.addEventListener('click',()=>setBriefing(false));
briefingPrev.addEventListener('click',()=>stepBriefing(-1));briefingNext.addEventListener('click',()=>stepBriefing(1));
briefingContent.addEventListener('click',e=>{const b=e.target.closest('[data-brief-q]');if(!b)return;setBriefing(false,false);location.hash='#records/question/'+b.dataset.briefQ;});

// keyboard-first quick navigation
const commandLayer=document.getElementById('command-layer'),commandInput=document.getElementById('command-input');
const commandResults=document.getElementById('command-results'),commandScrim=document.getElementById('command-scrim');
let commandReturnFocus=null;
const SECTION_TITLES={today:'오늘',future:'미래 탐색',statistics:'통계 비교',records:'기록과 검증',timeseries:'시계열 예측',trust:'데이터와 신뢰'};
const MID_CATEGORIES={
  today:[],
  future:[
    {key:'graph',label:'전망 그래프',hash:'#future',hint:'세 가지 시장 경로 · 단일 시나리오'},
    {key:'history',label:'과거 사이클',hash:'#future/history',hint:'혁신 사이클 참고 비교'},
    {key:'cross-asset',label:'교차자산 비교',hash:'#future/cross-asset',hint:'NASDAQ·Bitcoin·리츠·주택주'},
    {key:'liquidity',label:'유동성',hash:'#future/liquidity',hint:'시장 자금 흐름'}
  ],
  statistics:[
    {key:'all',label:'전체',hash:'#statistics',hint:'모든 비교 지표',railHidden:true},
    {key:'ipo',label:'IPO·상장',hash:'#statistics/ipo',hint:'상장 열기와 흡수 강도'},
    {key:'liquidity',label:'유동성',hash:'#statistics/liquidity',hint:'M2·가계 현금성 자산'},
    {key:'rates',label:'금리',hash:'#statistics/rates',hint:'장단기 금리차·정책금리'},
    {key:'economy',label:'경기·물가',hash:'#statistics/economy',hint:'실업률·물가·선행 지표'},
    {key:'valuation',label:'기업가치',hash:'#statistics/valuation',hint:'PER 대용치·이익 증가율'},
    {key:'credit',label:'신용',hash:'#statistics/credit',hint:'신용잔고·대출 심사·상환 부담'}
  ],
  records:[
    {key:'questions',label:'질문 목록',hash:'#records',hint:'등록 질문과 모든 라운드'},
    {key:'performance',label:'성과 검증',hash:'#records/performance',hint:'Brier·신뢰도 곡선'},
    {key:'journal',label:'변경 일지',hash:'#records/journal',hint:'언제 무엇이 왜 바뀌었나'},
    {key:'compare',label:'비교 작업공간',hash:'#records/compare',hint:'선택한 질문 나란히 보기',available:()=>cleanCompareIds().length>=2}
  ],
  timeseries:[
    {key:'summary',label:'전망 요약',hash:'#timeseries',hint:'기간별 분포 요약'},
    {key:'path',label:'경로 분포',hash:'#timeseries/path',hint:'최근 흐름과 향후 분포'},
    {key:'drivers',label:'기여 요인',hash:'#timeseries/drivers',hint:'올린 요인과 내린 요인'},
    {key:'backtest',label:'검증 성적',hash:'#timeseries/backtest',hint:'워크포워드 성적'}
  ],
  trust:[
    {key:'status',label:'데이터 상태',hash:'#trust',hint:'원장 건전성과 최신성'},
    {key:'sources',label:'출처와 방법',hash:'#trust/sources',hint:'수집 경로와 이용 조건'},
    {key:'audit',label:'감사 기록',hash:'#trust/audit',hint:'영수증과 정정 이력'}
  ]
};
function midCategories(section,forRail){return (MID_CATEGORIES[section]||[]).filter(item=>(!item.available||item.available())&&!(forRail&&item.railHidden));}
// 번호는 레일에서 걸러낸 뒤 1부터 매긴다. railHidden·비활성 항목이 01을 먹지 않는다.
function midCategoryCode(index){return String(index+1).padStart(2,'0');}
function currentMidCategory(section,rawHash){
  const items=midCategories(section);
  let best=null;
  items.forEach(item=>{
    if(rawHash!==item.hash&&!rawHash.startsWith(item.hash+'/'))return;
    if(!best||item.hash.length>best.hash.length)best=item;
  });
  return best||items[0]||null;
}
const COMMAND_ROUTES=[
  {hash:'#today',code:'01',title:'오늘',hint:'시장 판단과 핵심 신호'},
  {hash:'#future',code:'02',title:'미래 탐색',hint:'시나리오 경로와 위험 구간'},
  {hash:'#statistics',code:'03',title:'통계 비교',hint:'닷컴과 현재의 유동성·금리·가치·신용'},
  {hash:'#records',code:'04',title:'기록과 검증',hint:'질문·변경·결과 기록'},
  {hash:'#timeseries',code:'05',title:'시계열 예측',hint:'다변량 시계열 연구모델'},
  {hash:'#trust',code:'06',title:'데이터와 신뢰',hint:'원장·근거·방법론'},
  ...Object.entries(MID_CATEGORIES).flatMap(([section,items])=>items.filter(item=>!item.railHidden).map((item,index)=>({item,code:midCategoryCode(index)})).filter(row=>row.item.hash!=='#'+section).map(row=>({hash:row.item.hash,code:row.code,title:`${SECTION_TITLES[section]} · ${row.item.label}`,hint:row.item.hint||''})))
];
function syncMidHash(hash){
  history.replaceState(null,'',hash);
  paintRailSubNav(document.body.dataset.view||'today',hash);
}
function paintRailSubNav(navView,rawHash){
  const items=midCategories(navView,true),current=currentMidCategory(navView,rawHash);
  document.querySelectorAll('.view-nav').forEach(nav=>{
    nav.querySelectorAll('.rail-sub').forEach(node=>node.remove());
    if(items.length<2)return;
    const anchor=nav.querySelector(`a[data-v="${navView}"]`);
    if(!anchor)return;
    const list=el(`<ul class="rail-sub" aria-label="${esc(SECTION_TITLES[navView]||navView)} 중분류">${items.map((item,index)=>`<li><a href="${esc(item.hash)}" data-mid="${esc(item.key)}"${current&&item.key===current.key?' aria-current="page"':''}><span class="rail-sub-num">${esc(midCategoryCode(index))}</span><span class="rail-sub-label">${esc(item.label)}</span></a></li>`).join('')}</ul>`);
    anchor.after(list);
  });
}
function commandCatalog(){
  const actions=[
    {id:'briefing',code:'B',title:'3단계 시장 브리핑',hint:'현재 데이터를 큰 장면으로 빠르게 읽기',group:'작업',search:'briefing tour story 브리핑',run:()=>setBriefing(true)},
    {id:'pin-current',code:isCurrentPinned()?'★':'☆',title:isCurrentPinned()?'현재 화면 고정 해제':'현재 화면 고정',hint:'브라우저에 즐겨찾기 저장',group:'작업',search:'pin favorite 고정',run:toggleCurrentPin},
    {id:'share-current',code:'↗',title:'현재 화면 공유',hint:'기기 공유 또는 링크 복사',group:'작업',search:'share copy link 공유',run:()=>shareCurrentView(true)},
    ...(cleanCompareIds().length>=2?[{id:'compare-selected',code:'⇄',title:'선택한 예측 비교',hint:`${cleanCompareIds().length}개 질문 나란히 보기`,group:'작업',search:'compare 비교',run:()=>location.hash='#records/compare/'+cleanCompareIds().join(',')}]:[]),
    {id:'calendar-all',code:'CAL',title:'판정일 캘린더 저장',hint:'활성 질문을 ICS로 내보내기',group:'작업',search:'calendar ics 일정 판정일',run:()=>downloadQuestionCalendar()},
    {id:'current-note',code:'N',title:'현재 화면 메모',hint:'이 기기에 research note 저장',group:'작업',search:'note memo research 메모',run:openCurrentNote},
    {id:'data-status',code:'●',title:'데이터 상태',hint:'갱신 시각과 snapshot 범위',group:'작업',search:'data status freshness 갱신',run:()=>setUtility(true)},
    {id:'focus-mode',code:'F',title:document.body.classList.contains('focus-mode')?'집중 모드 종료':'집중 모드',hint:'navigation을 숨기고 내용에 집중',group:'작업',search:'focus present 집중',run:()=>setFocusMode(!document.body.classList.contains('focus-mode'))},
    {id:'density',code:'≡',title:'보기 밀도 전환',hint:`현재 ${UI_STATE.density}`,group:'작업',search:'density compact comfortable 밀도',run:()=>setDensity(UI_STATE.density==='compact'?'comfortable':'compact')},
    {id:'print',code:'PDF',title:'인쇄 / PDF 저장',hint:'현재 화면만 보고서로 출력',group:'작업',search:'print export pdf 인쇄',run:printCurrentView},
    {id:'shortcuts',code:'?',title:'키보드 단축키',hint:'사용 가능한 명령 보기',group:'작업',search:'keyboard help shortcut 단축키',run:()=>setShortcuts(true)}
  ];
  const pins=UI_STATE.pins.filter(descriptorExists).map((x,i)=>({...x,id:'pin-'+i,code:'★',hint:x.type==='question'?'고정한 예측 질문':'고정한 화면',group:'고정',search:x.title.toLowerCase()}));
  const recent=UI_STATE.recent.filter(descriptorExists).map((x,i)=>({...x,id:'recent-'+i,code:'↺',hint:x.type==='question'?'최근 본 예측 질문':'최근 본 화면',group:'최근',search:x.title.toLowerCase()}));
  const routes=COMMAND_ROUTES.map(x=>({...x,group:'화면'}));
  const qs=(DATA?.questions||[]).map(q=>({id:'q-'+q.id,hash:'#records/question/'+q.id,code:(hasNumeric(q.latest_prob)?q.latest_prob+'%':'대기'),title:q.title,hint:`${humanDomain(q.domain)} · ${q.status==='active'?'진행 중':'완료'}`,group:'예측 질문',search:[q.title,q.id,q.domain,humanDomain(q.domain),...(q.drivers||[]),(q.drivers||[]).map(humanDriver)].join(' ').toLowerCase()}));
  return actions.concat(pins,recent,routes,qs);
}
let activeCommandItems=[];
function renderCommandResults(query=''){
  const needle=query.trim().toLowerCase();
  const catalog=commandCatalog();
  let items;
  if(needle)items=catalog.filter(x=>x.title.toLowerCase().includes(needle)||(x.hint||'').toLowerCase().includes(needle)||(x.search||'').includes(needle)).slice(0,12);
  else{
    const limits={작업:7,고정:5,최근:4,화면:6,'예측 질문':3},counts={};
    items=catalog.filter(x=>{counts[x.group]=(counts[x.group]||0)+1;return counts[x.group]<=limits[x.group];});
  }
  if(!items.length){activeCommandItems=[];commandResults.innerHTML='<div class="command-empty">일치하는 화면이나 예측 질문이 없습니다.</div>';return;}
  activeCommandItems=items;
  let group='';
  commandResults.innerHTML=items.map((x,i)=>{
    const heading=x.group!==group?`<div class="command-group">${esc(group=x.group)}</div>`:'';
    return `${heading}<button type="button" class="command-result${i===0?' is-active':''}" data-command-index="${i}">
      <i>${esc(x.code)}</i><span><b>${esc(x.title)}</b><small>${esc(x.hint)}</small></span><kbd>↵</kbd></button>`;
  }).join('');
}
function setCommand(open,restoreFocus=true){
  if(open&&document.body.classList.contains('drawer-open'))setDrawer(false,false);
  if(open){closeQuickPeek();if(!briefingLayer.hidden)setBriefing(false,false);}
  if(open&&!utilityLayer.hidden)setUtility(false,false);
  if(open&&!shortcutLayer.hidden)setShortcuts(false,false);
  if(open)commandReturnFocus=document.activeElement;
  commandLayer.hidden=!open;
  commandLayer.setAttribute('aria-hidden',String(!open));
  document.body.classList.toggle('command-open',open);
  syncModalInert();
  if(open){commandInput.value='';renderCommandResults();requestAnimationFrame(()=>commandInput.focus());}
  else if(restoreFocus&&commandReturnFocus?.focus)commandReturnFocus.focus();
}
function bindCommandTriggers(){
  document.querySelectorAll('.command-open').forEach(b=>{if(b.dataset.commandBound)return;b.dataset.commandBound='1';b.addEventListener('click',()=>setCommand(true));});
}
bindCommandTriggers();
commandScrim.addEventListener('click',()=>setCommand(false));
commandInput.addEventListener('input',e=>renderCommandResults(e.target.value));
commandResults.addEventListener('click',e=>{const b=e.target.closest('button[data-command-index]');if(!b)return;const item=activeCommandItems[Number(b.dataset.commandIndex)];if(!item)return;
  setCommand(false,false);if(item.run)item.run();else if(item.hash)location.hash=item.hash;
});
document.addEventListener('keydown',e=>{
  const target=e.target,editing=target?.matches?.('input,select,textarea,[contenteditable="true"]');
  if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setCommand(commandLayer.hidden);return;}
  if(e.key==='/'&&!editing&&commandLayer.hidden){e.preventDefault();setCommand(true);return;}
  if(e.key==='Escape'&&!commandLayer.hidden){e.preventDefault();setCommand(false);return;}
  if(e.key==='Tab'&&!commandLayer.hidden){trapFocus(e,commandLayer.querySelector('.command-palette'));return;}
  if(!commandLayer.hidden&&e.key==='Enter'){const active=commandResults.querySelector('.command-result.is-active')||commandResults.querySelector('.command-result');if(active){e.preventDefault();active.click();}return;}
  if(commandLayer.hidden||!['ArrowDown','ArrowUp'].includes(e.key))return;
  e.preventDefault();const buttons=[...commandResults.querySelectorAll('.command-result')];if(!buttons.length)return;
  let i=buttons.indexOf(document.activeElement);i=e.key==='ArrowDown'?Math.min(buttons.length-1,i+1):Math.max(0,i<0?0:i-1);
  buttons.forEach((b,j)=>b.classList.toggle('is-active',j===i));buttons[i].focus();
});
document.addEventListener('keydown',e=>{
  const editing=e.target?.matches?.('input,select,textarea,[contenteditable="true"]');
  if(!briefingLayer.hidden){
    if(e.key==='Tab'){trapFocus(e,briefingSheet);return;}
    if(e.key==='Escape'){e.preventDefault();setBriefing(false);return;}
    if(!editing&&e.key==='ArrowRight'){e.preventDefault();stepBriefing(1);return;}
    if(!editing&&e.key==='ArrowLeft'){e.preventDefault();stepBriefing(-1);return;}
    return;
  }
  if(e.key==='Tab'){if(!utilityLayer.hidden)trapFocus(e,utilityPanel);else if(!shortcutLayer.hidden)trapFocus(e,shortcutSheet);return;}
  if(e.key==='Escape'){
    if(!utilityLayer.hidden){e.preventDefault();setUtility(false);return;}
    if(!shortcutLayer.hidden){e.preventDefault();setShortcuts(false);return;}
    if(document.body.classList.contains('focus-mode')){e.preventDefault();setFocusMode(false);return;}
  }
  if(editing||!commandLayer.hidden||!utilityLayer.hidden||!shortcutLayer.hidden)return;
  if(e.key==='?'){e.preventDefault();setShortcuts(true);return;}
  if(e.shiftKey&&e.key.toLowerCase()==='b'){e.preventDefault();setBriefing(true);return;}
  if(e.shiftKey&&e.key.toLowerCase()==='n'){e.preventDefault();openCurrentNote();return;}
  if(e.shiftKey&&e.key.toLowerCase()==='p'){e.preventDefault();toggleCurrentPin();return;}
  if(e.shiftKey&&e.key.toLowerCase()==='s'){e.preventDefault();shareCurrentView(true);return;}
  if(e.shiftKey&&e.key.toLowerCase()==='f'){e.preventDefault();setFocusMode(!document.body.classList.contains('focus-mode'));}
});

// 차트 표현 색(light analysis surface용) — 확률·값·가중치 불변, 표현만
const CHART_COL={S1:'#ff4f17',S2:'#ff9d19',S3:'#c9002d'};
const CHART_LABEL_COL={S1:'#9b2c0b',S2:'#715000',S3:'#9e1332'};
const FEATURE_QIDS=['nasdaq-corr10-augoct-2026','nasdaq-eoy-above-jul9-2026','nasdaq-ath-eoy-2026'];

function latestDelta(qid){
  const h=DATA.forecast_history[qid]||[];
  if(h.length<2)return null;
  return h[h.length-1].probability-h[h.length-2].probability;
}
function featureQs(){
  const byId=id=>DATA.questions.find(q=>q.id===id);
  let list=FEATURE_QIDS.map(byId).filter(Boolean);
  if(list.length<3){const extra=DATA.questions.filter(q=>q.status==='active'&&q.latest_prob!=null&&!list.includes(q));
    list=list.concat(extra).slice(0,3);}
  return list.slice(0,3);
}

function statisticsValue(unit,value){
  const n=Number(value);
  if(!Number.isFinite(n))return '—';
  if(unit==='count')return `${Math.round(n).toLocaleString('ko-KR')}건`;
  if(unit==='multiple')return `${n.toFixed(1)}×`;
  if(unit==='billions_usd')return `$${n.toFixed(1)}B`;
  if(unit==='cycle_start_100'||unit==='year_start_100')return `${n.toFixed(0)}`;
  if(unit==='percent'||unit==='percent_yoy'||unit==='net_percent'||unit==='percent_of_us_corporate_equity_value'||unit==='percent_20d_log_return'||unit==='percent_vs_trend')return `${n>=0?'+':''}${n.toFixed(1)}%`;
  if(unit==='percentage_point_change')return `${n>=0?'+':''}${n.toFixed(1)}%p`;
  if(unit==='neutral_line_distance')return `${n>=0?'+':''}${n.toFixed(1)}p`;
  if(unit==='standard_deviation_index')return `${n>=0?'+':''}${n.toFixed(2)}`;
  return n.toFixed(1);
}
function statisticsProfileRows(metric){
  const comparisons=Array.isArray(metric?.comparisons)?metric.comparisons.filter(row=>row?.value!==null&&row?.value!==''&&Number.isFinite(Number(row?.value))):[];
  if(comparisons.length)return comparisons.map(row=>({...row,value:Number(row.value)}));
  const value=Number(metric?.value);
  return Number.isFinite(value)?[{
    label:metric?.benchmark_label||'1999 닷컴',era:metric?.era||'dotcom',value,
    display_value:metric?.display_value,level:metric?.level
  }]:[];
}
function statisticsProfileCards(chart){
  const groups=(chart.profile_groups||[]).filter(group=>(group.metrics||[]).length);
  if(!groups.length)return '<div class="empty-block">표시할 통계가 없습니다.</div>';
  return `<div class="statistics-profile" role="group" aria-label="${esc(chart.title)} 핵심 지표">${groups.map(group=>`<section class="statistics-profile-group"><header><strong>${esc(group.title)}</strong><span>${esc(group.basis)}</span></header><div>${(group.metrics||[]).map(metric=>{const rows=statisticsProfileRows(metric);return `<article><div class="statistics-profile-metric"><b>${esc(metric.label)}</b></div><p>${esc(metric.meaning)}</p><div class="statistics-profile-comparison">${rows.map(row=>{const levelValue=Number(row.level),level=Math.max(0,Math.min(100,Number.isFinite(levelValue)?levelValue:Number(row.value)));return `<div class="statistics-profile-row" data-era="${esc(row.era||'reference')}"><div><span>${esc(row.label||'비교값')}</span><strong>${esc(row.display_value||statisticsValue(chart.unit,row.value))}</strong></div><i aria-hidden="true"><span style="width:${level.toFixed(1)}%"></span></i></div>`;}).join('')}</div></article>`;}).join('')}</div></section>`).join('')}</div>`;
}
function statisticsLiquidityBars(chart){
  const panels=(chart.liquidity_panels||[]).filter(panel=>(panel.metrics||[]).length);
  if(panels.length!==2)return '<div class="empty-block">표시할 자금 지도가 없습니다.</div>';
  return `<div class="statistics-liquidity-map">${panels.map(panel=>{
    const metrics=(panel.metrics||[]).map(metric=>({...metric,value:Number(metric.value)})).filter(metric=>Number.isFinite(metric.value));
    const diverging=panel.mode==='diverging',maximum=Math.max(1,...metrics.map(metric=>Math.abs(metric.value)));
    const step=diverging?10:(maximum>=100?10:maximum>=20?5:maximum>=10?2:1),axisMax=Math.ceil(maximum/step)*step;
    const aria=metrics.map(metric=>`${metric.label} ${metric.display_value||metric.value}`).join(', ');
    const rows=metrics.map(metric=>{
      const magnitude=Math.min(100,Math.abs(metric.value)/axisMax*100);
      const width=diverging?magnitude/2:magnitude;
      const left=diverging?(metric.value<0?50-width:50):0;
      const direction=metric.value<0?'is-negative':'is-positive';
      return `<article class="statistics-liquidity-row ${direction}"><div class="statistics-liquidity-label"><span>${esc(metric.label)}</span><strong>${esc(metric.display_value||statisticsValue(chart.unit,metric.value))}</strong></div><div class="statistics-liquidity-track${diverging?' is-diverging':''}" aria-hidden="true">${diverging?'<b></b>':''}<i style="--bar-left:${left.toFixed(2)}%;--bar-width:${width.toFixed(2)}%"></i></div></article>`;
    }).join('');
    const axis=diverging?`<span>−${axisMax.toFixed(0)}%</span><span>0</span><span>+${axisMax.toFixed(0)}%</span>`:`<span>0</span><span>$${axisMax.toFixed(0)}T</span>`;
    return `<section class="statistics-liquidity-panel" data-mode="${esc(panel.mode)}" role="img" aria-label="${esc(`${panel.title}: ${aria}`)}"><header><strong>${esc(panel.title)}</strong><span>${esc(panel.basis)}</span></header><div class="statistics-liquidity-rows">${rows}</div><div class="statistics-liquidity-axis">${axis}</div></section>`;
  }).join('')}</div>`;
}
function statisticsChartSvg(chart,alignment={}){
  const series=(chart.series||[]).filter(row=>(row.points||[]).length),points=series.flatMap(row=>row.points||[]);
  if(!points.length)return '<div class="empty-block">표시할 통계가 없습니다.</div>';
  const maxPeriod=Math.max(1,Number(chart.max_period)||Number(alignment.comparison_months)||0,...points.map(row=>Number(row.period)||0));
  const W=780,H=390,ML=76,MR=34,MT=44,denseCategorical=chart.axis_type==='categorical'&&maxPeriod>=6,MB=denseCategorical?82:56,PW=W-ML-MR,PH=H-MT-MB;
  const currentPoints=series.filter(row=>row.era==='current').flatMap(row=>row.points||[]),currentEnd=currentPoints.length?Math.max(...currentPoints.map(row=>Number(row.period)||0)):null;
  const stackedBar=chart.chart_type==='stacked_bar',barChart=chart.chart_type==='bar'||chart.chart_type==='grouped_bar'||stackedBar;
  const rawValues=points.map(row=>Number(row.value)).filter(Number.isFinite);
  const stackTotals=stackedBar?[...new Set(points.map(row=>Number(row.period)))].map(period=>series.reduce((sum,row)=>sum+Number((row.points||[]).find(point=>Number(point.period)===period)?.value||0),0)):[];
  const domainValues=rawValues.concat(stackTotals),rawMin=Math.min(...domainValues),rawMax=Math.max(...domainValues);
  const useLog=chart.scale==='log1p'&&rawMin>=0,transform=value=>useLog?Math.log1p(Number(value)):Number(value),inverse=value=>useLog?Math.expm1(value):value;
  const transformed=domainValues.map(transform),transformedMin=Math.min(...transformed),transformedMax=Math.max(...transformed);
  const span=Math.max(Math.abs(transformedMax-transformedMin),Math.abs(transformedMax)*.08,useLog?.4:1),logLow=rawMin>0?Math.max(0,transformedMin-span*.12):0,low=useLog?logLow:(barChart?Math.min(0,transformedMin):transformedMin-span*.12),high=transformedMax+span*.12;
  const X=value=>barChart?ML+PW*((Number(value)||0)+.5)/(maxPeriod+1):ML+PW*(Number(value)||0)/maxPeriod,Y=value=>MT+PH*(1-(transform(value)-low)/(high-low));
  const yTicks=Array.from({length:5},(_,i)=>low+(high-low)*i/4);
  const calendarAxis=chart.axis_type==='calendar_day_of_year';
  const xTicks=((chart.x_ticks||[]).length?chart.x_ticks:(calendarAxis?[
    [0,'1월'],[59,'3월'],[120,'5월'],[181,'7월'],[243,'9월'],[304,'11월'],[maxPeriod,'12월']
  ]:[0,12,24,36,48,maxPeriod].map(value=>[value,`M+${value}`])))
    .filter(([value],index,array)=>value<=maxPeriod&&array.findIndex(([peer])=>peer===value)===index)
    .sort((a,b)=>a[0]-b[0]);
  const line=values=>values.map((row,index)=>`${index?'L':'M'}${X(row.period).toFixed(1)},${Y(row.value).toFixed(1)}`).join(' ');
  const tickY=value=>MT+PH*(1-(value-low)/(high-low));
  const calendarLabel=chart.unit==='percent_20d_log_return'
    ?'실제 20거래일 로그수익률. 미국 SOX는 한국 날짜보다 엄격히 이전인 종가만 사용.'
    :'각 지수의 2026년 첫 실제 종가 100. 변동성·날짜 조정 없음.';
  const groupedBars=barChart&&!stackedBar?series.flatMap((row,seriesIndex)=>(row.points||[]).map(point=>{
    const groupWidth=Math.min(92,PW/Math.max(2,maxPeriod+1)*.72),count=chart.chart_type==='bar'?1:series.length,barWidth=Math.max(6,groupWidth/count),offset=(seriesIndex-(count-1)/2)*barWidth,x=X(point.period)+offset-barWidth*.42,y0=Y(0),yv=Y(point.value),top=Math.min(y0,yv),height=Math.max(1,Math.abs(yv-y0));
    return `<rect x="${x.toFixed(1)}" y="${top.toFixed(1)}" width="${(barWidth*.84).toFixed(1)}" height="${height.toFixed(1)}" rx="2" fill="${esc(row.color||'#111')}" fill-opacity="${seriesIndex===0?'.9':'.72'}" data-stat-series="${esc(row.label)}"/>`;
  })).join(''):'';
  const stackedBars=stackedBar?[...new Set(points.map(row=>Number(row.period)))].flatMap(period=>{let cumulative=0;const width=Math.min(150,PW/Math.max(2,maxPeriod+1)*.54),x=X(period)-width/2,segments=series.map((row,seriesIndex)=>{const value=Number((row.points||[]).find(point=>Number(point.period)===period)?.value||0),bottom=Y(cumulative),top=Y(cumulative+value),height=Math.max(1,bottom-top);cumulative+=value;return `<g><rect x="${x.toFixed(1)}" y="${top.toFixed(1)}" width="${width.toFixed(1)}" height="${height.toFixed(1)}" rx="2" fill="${esc(row.color||'#111')}" fill-opacity="${seriesIndex===0?'.9':'.76'}" data-stat-series="${esc(row.label)}"/>${chart.show_bar_values&&height>24?`<text x="${X(period).toFixed(1)}" y="${(top+height/2+5).toFixed(1)}" text-anchor="middle" class="statistics-bar-value is-inside">${Math.round(value)}</text>`:''}</g>`;});segments.push(`<text x="${X(period).toFixed(1)}" y="${(Y(cumulative)-10).toFixed(1)}" text-anchor="middle" class="statistics-bar-total">총 ${Math.round(cumulative)}건</text>`);return segments;}).join(''):'';
  const eventLines=(chart.events||[]).map((event,index)=>`<line x1="${X(event.period).toFixed(1)}" x2="${X(event.period).toFixed(1)}" y1="${MT+12+(index%3)*19}" y2="${H-MB}" stroke="#8c867c" stroke-dasharray="3 5" opacity=".55"/><text x="${(X(event.period)+5).toFixed(1)}" y="${MT+10+(index%3)*19}" text-anchor="start" fill="#625f58" class="statistics-event-label">${esc(event.label)}</text>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(chart.title)}. ${calendarAxis?calendarLabel:'닷컴 1995~1999와 현재 공개 관측자료 비교.'} ${useLog?'세로축 log(1+x). ':''}예측값 없음" data-forecast-extension="false" data-stat-scale="${useLog?'log1p':'linear'}" data-stat-axis="${esc(chart.axis_type||'elapsed-month')}">
    ${yTicks.map(value=>`<line x1="${ML}" x2="${W-MR}" y1="${tickY(value).toFixed(1)}" y2="${tickY(value).toFixed(1)}" stroke="#e5e1d8"/><text x="${ML-10}" y="${(tickY(value)+4).toFixed(1)}" text-anchor="end">${esc(statisticsValue(chart.unit,inverse(value)))}</text>`).join('')}
    ${!useLog&&low<0&&high>0?`<line x1="${ML}" x2="${W-MR}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}" stroke="#77746d" stroke-dasharray="4 5"/>`:''}
    ${xTicks.map(([value,label])=>{const x=X(value).toFixed(1),y=H-17;return denseCategorical?`<text x="${x}" y="${y}" text-anchor="end" transform="rotate(-34 ${x} ${y})">${esc(label)}</text>`:`<text x="${x}" y="${y}" text-anchor="middle">${esc(label)}</text>`;}).join('')}
    ${currentEnd!==null&&currentEnd<maxPeriod?`<line x1="${X(currentEnd).toFixed(1)}" x2="${X(currentEnd).toFixed(1)}" y1="${MT}" y2="${H-MB}" stroke="#28756a" stroke-dasharray="3 5" opacity=".55"/><text x="${X(currentEnd).toFixed(1)}" y="${MT-8}" text-anchor="middle" fill="#28756a">${esc(chart.observed_end_label||'AI 실제 관측 종료')}</text>`:''}
    ${eventLines}
    ${stackedBar?stackedBars:barChart?groupedBars:series.map(row=>`<path d="${line(row.points)}" fill="none" stroke="${esc(row.color||'#111')}" stroke-width="${row.era==='current'?'3.2':'2.4'}" stroke-dasharray="${row.era==='dotcom'?'6 5':'none'}" stroke-linejoin="round" data-stat-series="${esc(row.label)}"/>`).join('')}
    ${chart.category==='ipo'&&!barChart?series.flatMap(row=>(row.points||[]).map(point=>{const radius=Math.max(3,Math.min(12,Number(point.marker_radius??row.marker_radius??4)));const emphasized=radius>4;return `<circle cx="${X(point.period).toFixed(1)}" cy="${Y(point.value).toFixed(1)}" r="${radius}" fill="${emphasized?esc(row.color||'#111'):'#fff'}" fill-opacity="${emphasized?'.24':'1'}" stroke="${esc(row.color||'#111')}" stroke-width="${emphasized?'3':'2'}" data-marker-emphasis="${emphasized?'true':'false'}"/>`;}).join('')).join(''):''}
  </svg>`;
}
function renderStatistics(initialState){
  const requestedCategory=typeof initialState==='string'?initialState:initialState?.category;
  const stats=DATA.statistics_lab||{},root=el('<div class="statistics-page"></div>');
  root.appendChild(el(`<div class="page-heading statistics-heading"><div><p class="eyebrow">STATISTICS · DOTCOM VS NOW</p><h1>닷컴과 지금, 숫자로 나란히 보기</h1><p class="page-lede">IPO 열기, 유동성, 금리, 기업가치와 신용 흐름에서 지금 시장의 위치를 살펴봅니다.</p></div></div>`));
  if(stats.status!=='ok'){
    root.appendChild(el('<section class="statistics-blocked"><strong>통계 DB 갱신 대기</strong><p>공개 원천 검증을 마친 뒤 이 화면에 표시합니다.</p></section>'));mount(root);return;
  }
  const alignment=stats.cycle_alignment||{},charts=stats.charts||[];
  const categories=[['all','전체'],['ipo','IPO·상장'],['liquidity','유동성'],['rates','금리'],['economy','경기·물가'],['valuation','기업가치'],['credit','신용']];
  root.appendChild(el(`<nav class="statistics-filters" aria-label="통계 그래프 분류">${categories.map(([key,label])=>`<button type="button" data-stat-filter="${key}" aria-pressed="${key==='all'}">${label}</button>`).join('')}</nav>`));
  const grid=el('<div class="statistics-grid"></div>');
  const appendCards=(target,rows,startIndex=0)=>rows.forEach((chart,index)=>{
    const latest=(chart.series||[]).map(row=>{const point=(row.points||[]).at(-1);return point?`<div><i style="background:${esc(row.color||'#111')}"></i><span>${esc(row.label)}</span><strong>${esc(statisticsValue(chart.unit,point.value))}</strong><small>${esc(row.latest_date||'최근 관측')}</small></div>`:'';}).join('');
    const profile=chart.chart_type==='profile_cards',liquidity=chart.chart_type==='liquidity_bars';
    const guide=chart.reading_guide?`<div class="statistics-reading-guide"><strong>그래프 읽는 법</strong><p>${esc(chart.reading_guide)}</p></div>`:'';
    const visual=liquidity?statisticsLiquidityBars(chart):(profile?statisticsProfileCards(chart):`<div class="statistics-chart">${statisticsChartSvg(chart,alignment)}</div>`);
    const cardClass=`statistics-card${profile?' is-profile-card':''}${liquidity?' is-liquidity-map':''}`;
    target.appendChild(el(`<section class="${cardClass}" data-stat-category="${esc(chart.category)}" data-stat-id="${esc(chart.id)}"><div class="statistics-card-head"><div><span>${String(startIndex+index+1).padStart(2,'0')} · ${esc(chart.category.toUpperCase())}</span><h2>${esc(chart.title)}</h2></div><b>${esc(chart.display_unit||(profile?'핵심 지표':chart.unit))}</b></div>${profile||liquidity?'':`<div class="statistics-legend">${latest}</div>`}${guide}${visual}<p class="statistics-scope-note">${esc(chart.scope_note||'')}</p><div class="statistics-meaning"><strong>한눈에 보는 의미</strong><p>${esc(chart.insight||'현재 값과 닷컴 당시 같은 경과월을 비교해 과열·완화 방향을 확인합니다.')}</p><div class="statistics-now"><strong>현재 결론</strong><p>${esc(chart.conclusion||'단독 판단 신호로 사용하지 않습니다.')}</p></div></div></section>`));
  });
  appendCards(grid,charts);
  root.appendChild(grid);
  const reference=stats.reference_statistics||{},referenceCharts=reference.status==='ok'?(reference.charts||[]):[];
  if(referenceCharts.length){
    const referenceSection=el(`<section class="statistics-reference" data-stat-reference-section aria-labelledby="statistics-reference-title"><header><span>REFERENCE · IPO</span><h2 id="statistics-reference-title">IPO 참고 통계</h2><b>${referenceCharts.length}개 비교</b></header><div class="statistics-grid"></div></section>`);
    appendCards(referenceSection.querySelector('.statistics-grid'),referenceCharts,charts.length);
    root.appendChild(referenceSection);
  }
  mount(root);
  const applyStatCategory=(key,sync)=>{
    const active=categories.some(([id])=>id===key)?key:'all';
    root.querySelectorAll('[data-stat-filter]').forEach(item=>item.setAttribute('aria-pressed',String(item.dataset.statFilter===active)));
    root.querySelectorAll('[data-stat-category]').forEach(card=>card.hidden=active!=='all'&&card.dataset.statCategory!==active);
    const referenceSection=root.querySelector('[data-stat-reference-section]');
    if(referenceSection)referenceSection.hidden=active!=='all'&&active!=='ipo';
    if(sync)syncMidHash(active==='all'?'#statistics':'#statistics/'+active);
  };
  root.querySelectorAll('[data-stat-filter]').forEach(button=>{button.onclick=()=>applyStatCategory(button.dataset.statFilter,true);});
  applyStatCategory(requestedCategory||'all',false);
}

function timeseriesFeatureLabel(name){
  const labels={intercept:'기본 절편',nasdaq_return:'NASDAQ 수익률',vix_change:'변동성 변화',dgs2_change_bps:'2년물 금리 변화',curve_change_bps:'장단기 금리차 변화',hy_oas_change_bps:'하이일드 신용스프레드',dollar_change:'달러 변화',growth_factor:'성장 상태',inflation_factor:'물가 상태',nfci_level:'금융여건',nfci_change:'금융여건 변화',dff_level:'정책금리',dff_change:'정책금리 변화',m2_log_growth:'통화량 증가율',walcl_change:'연준 자산 변화',wtregen_change:'재무부 현금 변화',rrpontsyd_change:'역레포 변화',dfm_age_since_release:'거시 발표 경과일',NFCI:'금융여건',M2SL:'통화량',WALCL:'연준 자산',WTREGEN:'재무부 현금',RRPONTSYD:'역레포',DFF:'정책금리'};
  const base=String(name||'').replace(/_lag\d+$/,'');return labels[base]||base.replaceAll('_',' ');
}
function timeseriesPathSvg(ts){
  const path=ts.path||{},history=path.history_index||[],future=path.p50||[],dates=path.dates||[];
  if(history.length<2||future.length!==63)return '<div class="timeseries-chart-empty">경로 검증이 완료되면 최근 63일과 향후 63일을 한 축에서 보여드립니다.</div>';
  const W=1200,H=500,ML=74,MR=28,MT=36,MB=54,PW=W-ML-MR,PH=H-MT-MB,split=.25;
  const all=[...history,...['p10','p25','p50','p75','p90'].flatMap(key=>path[key]||[])].filter(value=>Number(value)>0).map(Number);
  const logMin=Math.log(Math.min(...all)*.985),logMax=Math.log(Math.max(...all)*1.015),span=Math.max(1e-9,logMax-logMin);
  const Y=value=>MT+(logMax-Math.log(Number(value)))/span*PH;
  const HX=index=>ML+(history.length===1?0:index/(history.length-1))*PW*split;
  const FX=index=>ML+PW*split+(index/(future.length-1))*PW*(1-split);
  const line=(values,x)=>values.map((value,index)=>`${index?'L':'M'}${x(index).toFixed(1)},${Y(value).toFixed(1)}`).join(' ');
  const band=(lower,upper)=>upper.map((value,index)=>`${FX(index).toFixed(1)},${Y(value).toFixed(1)}`).concat(lower.map((_,index)=>`${FX(lower.length-1-index).toFixed(1)},${Y(lower[lower.length-1-index]).toFixed(1)}`)).join(' ');
  const ticks=Array.from({length:5},(_,index)=>Math.exp(logMin+(logMax-logMin)*index/4));
  const anchorX=ML+PW*split;
  const labels=[[ML,path.history_dates?.[0]||''],[anchorX,ts.as_of],[FX(20),dates[20]||''],[FX(62),dates[62]||'']];
  return `<div class="timeseries-chart" role="img" aria-label="최근 63거래일과 향후 63거래일 NASDAQ 로그축 예측 범위"><svg viewBox="0 0 ${W} ${H}">
    ${ticks.map(value=>`<line x1="${ML}" x2="${W-MR}" y1="${Y(value).toFixed(1)}" y2="${Y(value).toFixed(1)}" class="ts-grid"/><text x="${ML-12}" y="${(Y(value)+4).toFixed(1)}" text-anchor="end">${Math.round(value).toLocaleString()}</text>`).join('')}
    <rect x="${ML}" y="${MT}" width="${(PW*split).toFixed(1)}" height="${PH}" class="ts-history-zone"/><rect x="${anchorX.toFixed(1)}" y="${MT}" width="${(PW*(1-split)).toFixed(1)}" height="${PH}" class="ts-forecast-zone"/>
    <polygon points="${band(path.p10,path.p90)}" class="ts-band-outer"/><polygon points="${band(path.p25,path.p75)}" class="ts-band-inner"/>
    <path d="${line(history,HX)}" class="ts-history-line"/><path d="${line(path.p50,FX)}" class="ts-median-line"/>
    <line x1="${anchorX.toFixed(1)}" x2="${anchorX.toFixed(1)}" y1="${MT}" y2="${H-MB}" class="ts-now-line"/><text x="${(anchorX+8).toFixed(1)}" y="${MT+16}" class="ts-now-label">현재</text>
    ${labels.map(([x,label],index)=>`<text x="${Number(x).toFixed(1)}" y="${H-20}" text-anchor="${index===0?'start':index===labels.length-1?'end':'middle'}">${esc(String(label).slice(5))}</text>`).join('')}
    <g class="ts-legend"><circle cx="${ML+10}" cy="${MT+12}" r="4" class="ts-history-dot"/><text x="${ML+20}" y="${MT+16}">실제</text><line x1="${ML+78}" x2="${ML+102}" y1="${MT+12}" y2="${MT+12}" class="ts-median-line"/><text x="${ML+110}" y="${MT+16}">중앙 경로</text><rect x="${ML+202}" y="${MT+5}" width="20" height="12" class="ts-band-inner"/><text x="${ML+230}" y="${MT+16}">중심 50%</text><rect x="${ML+320}" y="${MT+5}" width="20" height="12" class="ts-band-outer"/><text x="${ML+348}" y="${MT+16}">넓은 80%</text></g>
  </svg></div>`;
}
const TS_TABS=[['summary','전망 요약','01'],['path','경로 분포','02'],['drivers','기여 요인','03'],['backtest','검증 성적','04']];
function timeseriesTabsMarkup(active,enabled){
  return `<nav class="lab-tabs timeseries-tabs" role="tablist" aria-label="시계열 예측 화면">${TS_TABS.map(([key,label,code])=>{
    const on=enabled.includes(key);
    return `<button type="button" id="lab-tab-ts-${key}" role="tab" data-ts-tab="${key}" aria-selected="${String(key===active)}" aria-controls="lab-ts-${key}"${on?'':' disabled'}><span>${code}</span> ${label}<small>${on?'':'검증 대기'}</small></button>`;
  }).join('')}</nav>`;
}
function renderTimeseries(initialState){
  const ts=DATA.timeseries||{},visible=ts.numbers_visible===true;
  const requested=typeof initialState==='string'?initialState:initialState?.tsTab;
  const enabled=visible?TS_TABS.map(([key])=>key):['summary'];
  const active=enabled.includes(requested)?requested:'summary';
  const footnote=`<footer class="timeseries-footnote">${esc(ts.footnote||'*미국 시장·미국 공식 거시자료 기준')}</footer>`;
  const panel=(key,inner)=>`<div id="lab-ts-${key}" role="tabpanel" aria-labelledby="lab-tab-ts-${key}"${key===active?'':' hidden'}>${inner}</div>`;
  if(!visible){
    const root=el(`<div class="timeseries-page"><header class="timeseries-hero"><div><span class="timeseries-chip">연구모델</span><p class="eyebrow">05 · MULTIVARIATE TIME SERIES</p><h1>NASDAQ 시계열 예측</h1><p>당시 공개된 데이터만으로 다변량 관계를 다시 맞추고 있습니다.</p></div></header>${timeseriesTabsMarkup('summary',enabled)}${panel('summary',`<section class="timeseries-pending"><div class="timeseries-pending-mark" aria-hidden="true">∿</div><div><span>VALIDATION IN PROGRESS</span><h2>검증을 통과한 숫자만 표시합니다</h2><p>2007년 이후 워크포워드와 구간 적중률 검사가 끝나기 전에는 예상값과 경로를 노출하지 않습니다. 기존 미래전망으로 자동 전환하지 않습니다.</p></div></section>`)}${TS_TABS.slice(1).map(([key])=>panel(key,'')).join('')}${footnote}</div>`);
    mount(root);
    if(requested&&requested!=='summary')syncMidHash('#timeseries');
    return;
  }
  const one=ts.horizons?.['1']||{},horizons=[1,5,21,63],anchor=Number(ts.anchor?.value||ts.anchor||0);
  const cards=horizons.map(horizon=>{const row=ts.horizons?.[String(horizon)]||{},ret=Number(row.point_return||0),up=Number(row.probability_up||0);return `<article><span>${horizon}거래일</span><strong>${ret>=0?'+':''}${(ret*100).toFixed(1)}%</strong><p>상승 가능성 ${Math.round(up*100)}%</p><small>중앙값 ${Number(row.median_index||0).toLocaleString(undefined,{maximumFractionDigits:0})}</small></article>`;}).join('');
  const components=Object.entries(ts.contributions_1d?.components||{}).map(([name,value])=>({name,value:Number(value)}));
  const positive=components.filter(row=>row.value>0).sort((a,b)=>b.value-a.value).slice(0,3),negative=components.filter(row=>row.value<0).sort((a,b)=>a.value-b.value).slice(0,3);
  const contributionRows=(rows,tone)=>rows.map(row=>`<li><span>${esc(timeseriesFeatureLabel(row.name))}</span><strong class="${tone}">${row.value>=0?'+':''}${(row.value*100).toFixed(3)}%p</strong></li>`).join('')||'<li><span>뚜렷한 요인 없음</span><strong>—</strong></li>';
  const metrics=ts.backtest?.metrics?.horizons||{},long=[metrics['21'],metrics['63']].filter(Boolean),improvement=long.length?long.reduce((sum,row)=>sum+Number(row.crps_improvement_vs_best||0),0)/long.length:null,coverage=metrics['63']?.coverage_p10_p90;
  const root=el(`<div class="timeseries-page"><header class="timeseries-hero"><div><span class="timeseries-chip">연구모델</span><p class="eyebrow">05 · MULTIVARIATE TIME SERIES</p><h1>NASDAQ 시계열 예측</h1><p>${esc(ts.as_of)} 종가 이후 1·5·21·63거래일 분포입니다.</p></div><div class="timeseries-next"><span>다음 거래일 중앙 예상</span><strong>${Number(one.median_index||0).toLocaleString(undefined,{maximumFractionDigits:0})}</strong><p>${Number(one.point_return||0)>=0?'+':''}${(Number(one.point_return||0)*100).toFixed(2)}% · p10–p90 ${Number(one.quantiles?.p10||0).toLocaleString(undefined,{maximumFractionDigits:0})}–${Number(one.quantiles?.p90||0).toLocaleString(undefined,{maximumFractionDigits:0})}</p></div></div></header>${timeseriesTabsMarkup(active,enabled)}${panel('summary',`<section class="timeseries-horizons" aria-label="예측 기간별 요약">${cards}</section>`)}${panel('path',`<section class="timeseries-path-panel"><header><div><span>LOG SCALE · 63 + 63 SESSIONS</span><h2>최근 흐름과 향후 분포</h2></div><p>과거 1/4 · 전망 3/4</p></header>${timeseriesPathSvg(ts)}</section>`)}${panel('drivers',`<section class="timeseries-evidence"><article><header><span>올린 요인</span><strong>상방 기여</strong></header><ul>${contributionRows(positive,'up')}</ul></article><article><header><span>내린 요인</span><strong>하방 기여</strong></header><ul>${contributionRows(negative,'down')}</ul></article></section>`)}${panel('backtest',`<section class="timeseries-evidence"><article class="timeseries-score"><header><span>검증 성적</span><strong>워크포워드</strong></header><div><p><span>기준선 대비 CRPS</span><b>${improvement==null?'—':`${improvement>=0?'+':''}${(improvement*100).toFixed(1)}%`}</b></p><p><span>63일 넓은 구간 적중률</span><b>${coverage==null?'—':`${(Number(coverage)*100).toFixed(1)}%`}</b></p><p><span>경로 수</span><b>${Number(ts.ensemble?.path_count||0).toLocaleString()}</b></p></div></article></section>`)}${footnote}</div>`);
  mount(root);
  const tabs=$('.timeseries-tabs',root);
  const activateTs=(key,sync)=>{
    const next=enabled.includes(key)?key:'summary';
    TS_TABS.forEach(([name])=>{const node=$(`#lab-ts-${name}`,root);if(node)node.hidden=name!==next;});
    tabs.querySelectorAll('[data-ts-tab]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.tsTab===next)));
    if(sync)syncMidHash(next==='summary'?'#timeseries':'#timeseries/'+next);
  };
  tabs.querySelectorAll('[data-ts-tab]:not(:disabled)').forEach(button=>{button.onclick=()=>activateTs(button.dataset.tsTab,true);});
  activateTs(active,Boolean(requested)&&requested!==active);
}

const VIEWS={overview:renderOverview,flow:renderFlow,statistics:renderStatistics,timeseries:renderTimeseries,questions:renderQuestions,asof:renderDecisionJournal,track:renderTrack,q:renderDetail,compare:renderCompare};
const CHART_ZOOM_SELECTOR='.chart-wrap,.statistics-chart,.scenario-v52-chart,.timeseries-chart';
let CHART_ZOOM_LAYER=null,CHART_ZOOM_TRIGGER=null,CHART_ZOOM_SCALE=1,CHART_ZOOM_WIDTH=0;
function chartZoomTitle(surface,index){
  const owner=surface.closest('.statistics-card,.timeseries-path-panel,.scenario-v52-main,.chart-panel,section,article');
  return owner?.querySelector('h2,h3')?.textContent?.trim()||`그래프 ${index+1}`;
}
function setChartZoomScale(value){
  if(!CHART_ZOOM_LAYER)return;
  const scale=Math.max(1,Math.min(3,Number(value)||1)),content=$('.chart-zoom-content',CHART_ZOOM_LAYER),output=$('.chart-zoom-scale',CHART_ZOOM_LAYER);
  CHART_ZOOM_SCALE=scale;if(content&&CHART_ZOOM_WIDTH)content.style.width=`${Math.round(CHART_ZOOM_WIDTH*scale)}px`;
  if(output)output.textContent=`${Math.round(scale*100)}%`;
  $('[data-chart-zoom="out"]',CHART_ZOOM_LAYER).disabled=scale<=1;$('[data-chart-zoom="in"]',CHART_ZOOM_LAYER).disabled=scale>=3;
}
function closeChartZoom(restoreFocus=true){
  if(!CHART_ZOOM_LAYER||CHART_ZOOM_LAYER.hidden)return;
  CHART_ZOOM_LAYER.hidden=true;document.body.classList.remove('chart-zoom-open');$('.chart-zoom-content',CHART_ZOOM_LAYER).replaceChildren();
  const trigger=CHART_ZOOM_TRIGGER;CHART_ZOOM_TRIGGER=null;CHART_ZOOM_SCALE=1;CHART_ZOOM_WIDTH=0;
  if(restoreFocus&&trigger?.isConnected)trigger.focus();
}
function chartZoomLayer(){
  if(CHART_ZOOM_LAYER)return CHART_ZOOM_LAYER;
  const layer=el(`<div class="chart-zoom-layer" id="chart-zoom-layer" hidden>
    <button type="button" class="chart-zoom-scrim" data-chart-zoom="close" tabindex="-1" aria-label="확대 그래프 닫기"></button>
    <section class="chart-zoom-dialog" role="dialog" aria-modal="true" aria-labelledby="chart-zoom-title">
      <header><div><span>DETAIL VIEW</span><h2 id="chart-zoom-title">그래프 확대</h2></div><button type="button" class="chart-zoom-close" data-chart-zoom="close">닫기</button></header>
      <div class="chart-zoom-controls" role="group" aria-label="그래프 확대 배율">
        <button type="button" data-chart-zoom="out" aria-label="축소">−</button><output class="chart-zoom-scale" aria-live="polite">100%</output><button type="button" data-chart-zoom="in" aria-label="확대">＋</button><button type="button" data-chart-zoom="reset">화면 맞춤</button>
      </div>
      <div class="chart-zoom-canvas"><div class="chart-zoom-content"></div></div>
      <p class="chart-zoom-help">＋/− 또는 두 손가락으로 확대하고 밀어서 이동하세요.</p>
    </section>
  </div>`);
  document.body.appendChild(layer);CHART_ZOOM_LAYER=layer;
  layer.onclick=event=>{const action=event.target.closest('[data-chart-zoom]')?.dataset.chartZoom;if(action==='close')closeChartZoom();else if(action)setChartZoomScale(action==='reset'?1:CHART_ZOOM_SCALE+(action==='in' ? 0.25 : -0.25));};
  const canvas=$('.chart-zoom-canvas',layer),distance=touches=>Math.hypot(touches[0].clientX-touches[1].clientX,touches[0].clientY-touches[1].clientY);
  let pinch=0,pinchScale=1;canvas.addEventListener('touchstart',event=>{if(event.touches.length===2){pinch=distance(event.touches);pinchScale=CHART_ZOOM_SCALE;}},{passive:true});
  canvas.addEventListener('touchmove',event=>{if(event.touches.length===2&&pinch){event.preventDefault();setChartZoomScale(pinchScale*distance(event.touches)/pinch);}},{passive:false});
  canvas.addEventListener('touchend',()=>{pinch=0;},{passive:true});canvas.ondblclick=()=>setChartZoomScale(CHART_ZOOM_SCALE>1?1:2);
  window.addEventListener('keydown',event=>{if(!layer.hidden&&event.key==='Escape')closeChartZoom();});
  return layer;
}
function openChartZoom(surface,trigger,label){
  const layer=chartZoomLayer(),content=$('.chart-zoom-content',layer),canvas=$('.chart-zoom-canvas',layer),clone=surface.cloneNode(true);
  clone.removeAttribute('id');clone.removeAttribute('tabindex');clone.removeAttribute('data-chart-zoom-bound');clone.classList.add('chart-zoom-clone');
  clone.querySelectorAll('[id]').forEach(node=>node.removeAttribute('id'));
  clone.querySelectorAll('[tabindex]').forEach(node=>node.removeAttribute('tabindex'));
  clone.querySelectorAll('[style*="min-width"]').forEach(node=>node.style.minWidth='0');
  content.replaceChildren(clone);$('#chart-zoom-title',layer).textContent=label;
  CHART_ZOOM_TRIGGER=trigger;CHART_ZOOM_SCALE=1;layer.hidden=false;document.body.classList.add('chart-zoom-open');
  requestAnimationFrame(()=>{CHART_ZOOM_WIDTH=Math.max(280,canvas.clientWidth-24);setChartZoomScale(1);canvas.scrollTo(0,0);$('.chart-zoom-close',layer).focus();});
}
function enhanceChartZoom(root=document){
  root.querySelectorAll(CHART_ZOOM_SELECTOR).forEach((surface,index)=>{
    if(surface.dataset.chartZoomBound||!surface.querySelector('svg'))return;
    surface.dataset.chartZoomBound='1';surface.classList.add('chart-fit-surface');
    const label=chartZoomTitle(surface,index),tools=el(`<div class="chart-fit-tools"><span>전체 그래프</span><button type="button" aria-label="${esc(label)} 확대해서 보기"><i aria-hidden="true">↗</i> 확대해서 보기</button></div>`),button=$('button',tools);
    surface.before(tools);button.onclick=()=>openChartZoom(surface,button,label);
  });
}
function contextTabs(group,current){
  const groups={
    research:[['questions','질문 목록','#records'],['performance','성과 검증','#records/performance'],['journal','변경 일지','#records/journal'],['compare','비교 작업공간','#records/compare/'+cleanCompareIds().join(',')]],
    replay:[['ask','기간 조회','#future/lookup'],['asof','AS-OF 타임머신','#records/journal']],
    track:[['track','요약과 Calibration','#trust']]
  };
  const items=(groups[group]||[]).filter(([id])=>id!=='compare'||cleanCompareIds().length>=2);
  if(items.length<2)return '';
  return `<nav class="context-tabs" aria-label="${group==='replay'?'시점 리플레이':'예측 연구'} 세부 화면">${items.map(([id,label,href])=>{
    return `<a href="${href}" ${id===current?'aria-current="page"':''}>${label}</a>`;}).join('')}</nav>`;
}
function appendContextTabs(root,group,current){const html=contextTabs(group,current);if(html)root.appendChild(el(html));}
function legacyRouteRedirect(rawHash){
  if(!rawHash||rawHash==='#')return '#today';
  if(rawHash==='#future/range')return '#future/lookup';
  if(/^#(?:today|future(?:\/|$)|statistics(?:\/|$)|timeseries(?:\/|$)|records(?:\/|$)|trust(?:\/|$))/.test(rawHash))return rawHash;
  if(rawHash==='#overview')return '#today';
  if(rawHash==='#flow')return '#future';
  if(rawHash==='#questions')return '#records';
  if(rawHash==='#ask')return '#future/lookup';
  if(rawHash==='#asof')return '#records/journal';
  if(rawHash==='#track')return '#records/performance';
  if(rawHash.startsWith('#q/'))return `#records/question/${rawHash.slice(3)}`;
  if(rawHash.startsWith('#compare/'))return `#records/compare/${rawHash.slice(9)}`;
  if(rawHash.startsWith('#asof/'))return `#records/journal/question/${rawHash.slice(6)}`;
  const asofMatch=rawHash.match(/^#asof=(\d{4}-\d{2}-\d{2})$/);
  if(asofMatch)return `#records/journal/${asofMatch[1]}`;
  if(rawHash.startsWith('#lookup=')){
    const params=new URLSearchParams(rawHash.slice(1)),date=params.get('lookup'),mode=params.get('mode')==='current'?'current':'rebase';
    if(date&&/^\d{4}-\d{2}-\d{2}$/.test(date))return `#future/lookup/${date}/${mode}`;
  }
  if(rawHash.startsWith('#lab=')){
    const params=new URLSearchParams(rawHash.slice(1)),lab=params.get('lab')||'future',scenario=params.get('scenario');
    return lab==='future'?'#future':`#future/${encodeURIComponent(lab)}${scenario?`/${encodeURIComponent(scenario)}`:''}`;
  }
  return '#today';
}
function parseCanonicalRoute(rawHash){
  const parts=rawHash.slice(1).split('/').map(part=>decodeURIComponent(part));
  if(parts[0]==='today')return {section:'today',view:'overview'};
  if(parts[0]==='statistics')return {section:'statistics',view:'statistics',arg:{category:parts[1]||null}};
  if(parts[0]==='timeseries')return {section:'timeseries',view:'timeseries',arg:{tsTab:parts[1]||null}};
  if(parts[0]==='future'){
    if(parts[1]==='champion')return {section:'future',view:'flow',arg:{modelView:'champion'}};
    if(parts[1]==='research')return {section:'future',view:'flow',arg:{modelView:'research'}};
    if(parts[1]==='original')return {section:'future',view:'flow',arg:{futureGraph:'original'}};
    if(parts[1]==='lookup'&&!parts[2])return {section:'future',view:'flow',arg:{lookupOverlay:true}};
    if(parts[1]==='lookup'&&/^\d{4}-\d{2}-\d{2}$/.test(parts[2]||''))return {section:'future',view:'flow',arg:{lookup:parts[2],lookupMode:parts[3]==='current'?'current':'rebase'}};
    if(['history','cross-asset','ai-regime','liquidity'].includes(parts[1]))return {section:'future',view:'flow',arg:{lab:parts[1],scenario:parts[2]||null}};
    return {section:'future',view:'flow'};
  }
  if(parts[0]==='records'){
    if(parts[1]==='performance')return {section:'records',view:'track',arg:{trackMode:'performance'}};
    if(parts[1]==='question'&&parts[2])return {section:'records',view:'q',arg:parts.slice(2).join('/')};
    if(parts[1]==='compare'&&parts[2])return {section:'records',view:'compare',arg:parts.slice(2).join('/')};
    if(parts[1]==='journal'){
      if(parts[2]==='question'&&parts[3])return {section:'records',view:'asof',arg:{question:parts.slice(3).join('/')}};
      if(/^\d{4}-\d{2}-\d{2}$/.test(parts[2]||''))return {section:'records',view:'asof',arg:{mode:'replay',date:parts[2]}};
      return {section:'records',view:'asof'};
    }
    return {section:'records',view:'questions'};
  }
  if(parts[0]==='trust')return {section:'trust',view:'track',arg:{trackMode:new URLSearchParams(location.search).get('mode')==='operator'?'operator':'trust',trustTab:parts[1]||null}};
  return {section:'today',view:'overview'};
}
function renderFuturePathsLoadState(summary,error=null){
  const checkpoints=summary?.path_checkpoints||[],failed=!!error;
  const root=el(`<div class="future-paths-load-state" data-future-paths-state="${failed?'failed':'loading'}"><div class="page-heading"><div><p class="eyebrow">미래 탐색</p><h1>${failed?'전망 데이터를 불러오지 못했습니다':'세 가지 시나리오를 준비하고 있습니다'}</h1><p class="page-lede">${failed?'잠시 뒤 다시 시도해 주세요. 이전 방식의 그래프로 자동 전환하지 않습니다.':'상승·균형·스트레스 경로와 각 경로의 독립 DB를 불러오고 있습니다.'}</p></div></div><section class="future-paths-checkpoints" aria-label="시나리오 체크포인트 요약">${checkpoints.map(row=>`<article><span>${esc(row.label)} · ${esc(row.date)}</span><div>${Object.entries(row.return_from_anchor||{}).map(([key,value])=>`<strong>${esc(key)} ${Number(value)>=0?'+':''}${(Number(value)*100).toFixed(1)}%</strong>`).join('')}</div><small>조건부 p50 요약</small></article>`).join('')||'<p>표시할 체크포인트가 없습니다.</p>'}</section>${failed?'<div class="future-paths-actions"><button type="button" data-future-retry>다시 불러오기</button></div>':''}</div>`);
  mount(root);
  root.querySelector('[data-future-retry]')?.addEventListener('click',()=>{FUTURE_PATHS_ERROR=null;route();});
}
let ROUTE_EPOCH=0;
async function route(){
  const epoch=++ROUTE_EPOCH;
  const enteredHash=location.hash||'#today',rawHash=legacyRouteRedirect(enteredHash);
  if(rawHash!==enteredHash)history.replaceState(null,'',rawHash);
  const parsed=parseCanonicalRoute(rawHash),v=parsed.view,arg=parsed.arg,navView=parsed.section;
  closeQuickPeek();closeChartZoom(false);if(!briefingLayer.hidden)setBriefing(false,false);if(!shareLayer.hidden)setShare(false,false);
  document.querySelector('.future-lookup-layer')?.remove();document.body.classList.remove('future-lookup-open');
  document.body.dataset.view=navView;
  document.querySelectorAll('.view-nav a[data-v]').forEach(a=>{const on=a.dataset.v===navView;a.classList.toggle('active',on);
    if(on)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  document.querySelectorAll('.mobile-bottom-nav a[data-v]').forEach(a=>{const on=a.dataset.v===navView;a.classList.toggle('active',on);
    if(on)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  paintRailSubNav(navView,rawHash);
  mobileMore?.classList.toggle('active',false);
  const researchPathsRequested=v==='flow'&&arg?.modelView!=='champion'&&!arg?.lookup&&!arg?.lookupOverlay;
  if(researchPathsRequested&&DATA?.scenario_v5_2?.deferred_paths?.required&&!DATA.scenario_v5_2.deferred_paths.loaded){
    const summary=DATA.scenario_v5_2;
    if(researchPathsRequested)renderFuturePathsLoadState(summary);
    try{await ensureFuturePaths();}
    catch(error){
      if(epoch!==ROUTE_EPOCH)return;
      if(arg?.modelView==='champion')DATA.future_paths_error=String(error?.message||error);
      else{renderFuturePathsLoadState(summary,error);return;}
    }
    if(epoch!==ROUTE_EPOCH)return;
  }
  if(v==='statistics'&&DATA?.statistics_lab?.deferred_data?.required&&!DATA.statistics_lab.deferred_data.loaded){
    try{await ensureStatistics();}
    catch(error){
      if(epoch!==ROUTE_EPOCH)return;
      DATA.statistics_lab={status:'blocked',reason:String(error?.message||error),charts:[],sources:[]};
    }
    if(epoch!==ROUTE_EPOCH)return;
  }
  (VIEWS[v]||renderOverview)(arg);
  requestAnimationFrame(()=>enhanceChartZoom(app()));
  renderCompareTray();
  recordRecent();
  if(document.body.classList.contains('drawer-open'))setDrawer(false,false);
  if(!commandLayer.hidden)setCommand(false,false);
  window.scrollTo(0,0);
}
window.addEventListener('hashchange',route);

// ── 요약 ──
function marketThesis(upProb,rangeProb){
  if(upProb>=60)return {lead:'단기 조정 위험은 남아 있지만,',accent:`연말 상승 경로가 ${upProb}%로 우세합니다.`};
  if(rangeProb>=55)return {lead:'방어 경로의 무게가 커졌습니다.',accent:`지지선 확인 전까지 조정 가능성 ${rangeProb}%에 대비합니다.`};
  return {lead:'상승과 조정 경로가 맞서고 있습니다.',accent:'핵심 이벤트 전까지 변동성 우위입니다.'};
}
function renderOverview(){
  const sc=DATA.scenario;
  const upProb=sc.paths.S1.prob+sc.paths.S2.prob, rangeProb=sc.paths.S3.prob;
  const vintage=scenarioVintage();
  const thesis=vintage.status==='stale'
    ?{lead:'시장 시나리오 갱신이 필요합니다.',accent:`마지막 유효 기준은 ${vintage.asof}입니다.`}
    :marketThesis(upProb,rangeProb);
  const decisions=selectDecisionItems({minAbsoluteDelta:1,limit:8});
  const recent=[...decisions].filter(item=>item.delta!=null||item.newSince).slice(0,3);
  decisions.filter(item=>!recent.includes(item)).slice(0,3-recent.length).forEach(item=>recent.push(item));
  const today=generatedDay(),calendar=(DATA.calendar_events||[]).filter(item=>item.date>=today).sort((a,b)=>a.date.localeCompare(b.date)).slice(0,3);
  const fallbackEvents=upcoming(3).map(item=>({date:item.deadline,title:item.title,status:'question',id:item.id}));
  const events=calendar.length?calendar:fallbackEvents;
  const status=vintage.status==='stale'?'갱신 필요':'정상';
  const root=el(`<div class="overview-page today-page"><section class="today-dashboard" data-home-core="true" aria-labelledby="market-thesis">
    <header class="today-hero"><div><p class="eyebrow">TODAY · ${esc(sc.asof)}</p><h1 id="market-thesis">${esc(thesis.lead)} <em>${esc(thesis.accent)}</em></h1><p>${vintage.status==='stale'?'마지막 유효 스냅샷이며 최신 질문 기록과 결합하지 않습니다.':'시나리오 조건부 분포와 공식 질문 확률은 서로 다른 공간이며 합산하지 않습니다.'}</p></div><div class="today-actions"><a href="#future">미래 경로 보기 <span>↗</span></a><button type="button" data-action="briefing">3 STEP BRIEFING · 30초</button></div></header>
    <div class="today-signals" aria-label="핵심 신호 2개">
      <article><span>신호 01 · 시나리오</span><strong>${vintage.status==='stale'?'판정 보류':`상승 경로 ${num(upProb)}%`}</strong><small>방어 경로 ${num(rangeProb)}% · ${esc(status)}</small></article>
      <article><span>신호 02 · 변화 감지</span><strong>${recent.length}개 기록 확인</strong><small>${recent[0]?`${esc(recent[0].q.title)} ${recent[0].delta==null?'새 회차':`${recent[0].delta>0?'+':''}${recent[0].delta}%p`}`:'새 변경 없음'}</small></article>
    </div>
    <div class="today-columns">
      <section aria-labelledby="today-changes"><div class="today-section-head"><h2 id="today-changes">최근 변경 3</h2><a href="#records/journal">전체 기록</a></div><div class="today-list">${recent.map(item=>`<a href="#records/question/${esc(item.q.id)}"><time>${esc(String(item.q.latest_ts||'').slice(5,10)||'—')}</time><span>${esc(item.q.title)}</span><strong class="${item.delta>0?'edge-pos':item.delta<0?'edge-neg':''}">${item.delta==null?'NEW':`${item.delta>0?'+':''}${item.delta}%p`}</strong></a>`).join('')||'<p>표시할 변경이 없습니다.</p>'}</div></section>
      <section aria-labelledby="today-events"><div class="today-section-head"><h2 id="today-events">다음 이벤트 3</h2><a href="#future">전체 일정</a></div><div class="today-list">${events.map(item=>`<a href="${item.id?`#records/question/${esc(item.id)}`:'#future'}"><time>${esc(String(item.date||'').slice(5))}</time><span>${esc(item.title||item.label||'일정')}</span><strong>${item.status==='estimated'?'추정':item.status==='question'?'판정':'확정'}</strong></a>`).join('')||'<p>예정된 이벤트가 없습니다.</p>'}</div></section>
    </div>
    <footer class="today-context"><span>as_of ${esc(sc.asof)} · seed ${num(sc.model?.seed)} · ${num(sc.model?.n_paths)}경로</span><strong>조건부 분포 · 단일 가격 제시·사건확률·투자자문 아님</strong></footer>
  </section></div>`);
  mount(root);
}
function upcoming(limit=6){
  const today=DATA.meta.generated.slice(0,10);
  return DATA.questions.filter(q=>q.status==='active'&&q.deadline&&q.deadline>=today)
    .sort((a,b)=>a.deadline<b.deadline?-1:1).slice(0,limit);
}

// ── 시장 전망 ──
// 라벨은 시작정렬 차트에 맞춘 build-up 시작년(M+0 = 시작월). 툴팁은 실제 달력월 표시.
const ERA_META={
  ai:['AI 2023','#ff4f17',3,'',1],
  dotcom:['닷컴 1995','#247d78',2.2,'',.96],
  japan1989:['일본 1985','#c9002d',2,'6 4',.92],
  niftyfifty1972:['니프티50 1970','#6b4bc3',1.7,'3 4',.88],
  crypto2021:['크립토 2019 시작','#1f6feb',1.9,'8 4',.94],
  biotech2015:['바이오 2013','#a43c82',1.7,'2 5',.9],
  dow1929:['다우 1925','#6b5845',1.8,'10 5',.88],
  electricity1900:['전기 1901','#9a6700',1.7,'5 3',.9]
};
// 각 사이클 오버레이 시작월(M+0) — 툴팁의 실제 달력월 계산용 (config overlay_start와 정합)
const ERA_START={ai:'2023-01',dotcom:'1995-01',japan1989:'1985-01',niftyfifty1972:'1970-01',
  crypto2021:'2019-01',biotech2015:'2013-01',dow1929:'1925-01',electricity1900:'1901-01'};
const CROSS_META={
  nasdaq:['NASDAQ','#ff4f17',''],
  bitcoin:['Bitcoin 반사실','#1f6feb','7 4'],
  realty_income:['Realty Income','#247d78',''],
  realty_income_total_return:['Realty Income · 배당 포함','#247d78',''],
  dr_horton:['D.R. Horton','#8b4f9f',''],
  dr_horton_total_return:['D.R. Horton · 배당 포함','#8b4f9f',''],
  nasdaq_price:['NASDAQ 가격','#ff4f17',''],
  realty_income_price:['Realty Income 가격','#9a6700','7 4'],
  dr_horton_price:['D.R. Horton 가격','#8b4f9f','7 4']
};
function monthAt(ym,m){const t=(+ym.slice(0,4))*12+(+ym.slice(5,7)-1)+m;
  return Math.floor(t/12)+'-'+String(t%12+1).padStart(2,'0');}
const LOOKUP_WEEKDAYS=['일요일','월요일','화요일','수요일','목요일','금요일','토요일'];
function lookupDateLabel(mapped){
  const requested=ForecastLookup.parseIso(mapped.requested),weekday=LOOKUP_WEEKDAYS[requested.getUTCDay()];
  if(mapped.mapping==='exact')return `${mapped.requested} (${weekday} · D+${mapped.tradingDay} 거래일)`;
  const relation=mapped.mapping==='previous'?'직전 거래일':'다음 산출 거래일';
  return `${mapped.requested} (${weekday} — 휴장, ${relation} ${mapped.mapped.slice(5)} 기준 · D+${mapped.tradingDay} 거래일)`;
}
function lookupErrorMarkup(result){
  const copy=result.reason==='out_of_range'?`시뮬레이션 범위 밖 (최대 ${result.max})`:
    result.reason==='before_asof'?`기준일 ${result.asof} 이후 날짜를 선택해 주세요.`:
    result.reason==='blocked'?'이 스냅샷에는 날짜별 분포가 없습니다.':
    result.reason==='parse_failed'?'날짜를 이해하지 못했습니다. 달력 입력을 사용해 주세요.':'날짜 형식을 확인해 주세요.';
  return `<div class="lookup-empty" role="status"><strong>${esc(copy)}</strong><span>달력 입력 또는 빠른 날짜를 사용해 다시 조회할 수 있습니다.</span></div>`;
}
function horizonCoverageForDay(sc,tradingDay){
  const buckets=sc?.horizon_coverage?.buckets||[];
  const selected=buckets.find(bucket=>Number(tradingDay)<=Number(bucket.max_trading_days))||buckets.at(-1);
  if(!selected)return {label:'미검증 구간',detail:'적중 기록 축적 중 (0일 · 0/60)',status:'accumulating'};
  const n=Number(selected.observations||0),minimum=Number(selected.minimum_observations||60);
  if(selected.inside_p10_p90_rate_pct==null||n<minimum)return {label:`${selected.label} 미검증 구간`,detail:`적중 기록 축적 중 (${n}일 · ${n}/${minimum})`,status:'accumulating'};
  return {label:`${selected.label} 검증 표본`,detail:`p10–p90 적중률 ${selected.inside_p10_p90_rate_pct}% · n=${n}`,status:'verified'};
}
const EVENT_KIND_META={fomc:['FOMC','◇'],cpi:['CPI','□'],nfp:['고용','○'],gdp:['GDP','△'],earnings:['실적','⬡'],other:['기타','·']};
function lookupEventSummary(sc,mapped){
  const events=(sc.calendar_events||[]).filter(event=>event.date>sc.asof&&event.date<=mapped.mapped),counts=new Map();
  events.forEach(event=>{const key=event.kind==='earnings'?(event.ticker||'실적'):EVENT_KIND_META[event.kind]?.[0]||'기타';counts.set(key,(counts.get(key)||0)+1);});
  const body=counts.size?[...counts].map(([key,count])=>`${key} ${count}회`).join(' · '):'등록 일정 0회';
  const estimated=events.filter(event=>event.status==='estimated').length;
  return `<p class="lookup-event-summary"><strong>등록 일정 · 정보 표식만</strong><span>asof→${esc(mapped.mapped)} 사이: ${esc(body)}${estimated?` · 이 중 추정 ${estimated}건`:''}</span><small>일정과 분포 확률을 연결하지 않습니다.</small></p>`;
}
function lookupCardMarkup(sc,mapped){
  const table=sc.quantile_table,index=mapped.index,q=table.quantiles,model=sc.model||{};
  const coverage=horizonCoverageForDay(sc,mapped.tradingDay);
  const scenarioNames={S1:'S1 상승·ATH 돌파',S2:'S2 상승·ATH 미달',S3:'S3 조정·횡보'};
  const shortNote=mapped.tradingDay<=5?'<p class="lookup-short-note">단기 구간일수록 모델 가정 민감도가 큽니다.</p>':'';
  const eventQuestions=(DATA.questions||[]).filter(question=>question.deadline===mapped.requested&&question.probability_space==='physical_event'&&hasNumeric(question.latest_prob));
  const physicalEvents=eventQuestions.length?`<section class="lookup-physical-events" aria-label="별도 physical event 확률"><header><span>PHYSICAL EVENT · 별도 확률 공간</span><strong>시나리오 분포와 결합 금지</strong></header>${eventQuestions.map(question=>`<article><div><small>${esc(question.id)}</small><a href="#q/${esc(question.id)}">${esc(question.title)}</a></div><strong>p=${(Number(question.latest_prob)/100).toFixed(2)}</strong><small>${esc(question.probability_space)} · ${esc(String(question.latest_ts||'').slice(0,10)||'기준 미상')} 기준</small></article>`).join('')}</section>`:'';
  return `<article class="lookup-card" data-lookup-date="${esc(mapped.mapped)}">
    <header><div class="horizon-coverage-badge is-${coverage.status}"><strong>${esc(coverage.label)}</strong><span>${esc(coverage.detail)}</span></div><p class="eyebrow">DATE DISTRIBUTION · MODEL CONDITIONAL</p><h3>${esc(lookupDateLabel(mapped))}</h3></header>
    <div class="lookup-metrics">
      <div class="lookup-primary"><span>10–90% 구간</span><strong>${num(q.p10[index])} – ${num(q.p90[index])}</strong></div>
      <div><span>25–75% 구간</span><strong>${num(q.p25[index])} – ${num(q.p75[index])}</strong></div>
      <div><span>중앙값</span><strong>${num(q.p50[index])}</strong></div>
      <div><span>현재가(${num(Math.round(sc.anchor))}) 상회</span><strong>${table.prob_above_anchor[index]}%</strong><small>모델 조건부 확률</small></div>
      <div><span>ATH 상회</span><strong>${table.prob_above_ath[index]}%</strong><small>모델 조건부 확률</small></div>
    </div>
    ${shortNote}
    ${lookupEventSummary(sc,mapped)}
    <details class="lookup-scenarios"><summary>S1/S2/S3 조건부 중앙값 보기</summary><div>${['S1','S2','S3'].map(key=>`<p><span>${scenarioNames[key]}</span><strong>${num(table.per_scenario_p50[key][index])}</strong><small>${num(table.per_scenario_counts?.[key]||0)}경로</small></p>`).join('')}</div></details>
    ${physicalEvents}
    <p class="lookup-warning">⚠ GBM 고정 가정의 조건부 분포입니다. 단일 가격 제시·사건확률·투자자문이 아닙니다.</p>
    <footer>as_of ${esc(sc.asof)} 스냅샷 · seed ${esc(model.seed)} · ${num(model.n_paths)}경로 · ${esc(table.probability_space)}</footer>
  </article>`;
}
const FLOW_LAB_COPY={
  future:['시장 전망 · Scenario Map','향후 12개월 시장 경로는 어떤 분포인가','나스닥 종합의 조건부 구간과 조정·회복 경로를 함께 봅니다.'],
  history:['혁신 사이클 · Analog','과거 혁신 사이클은 현재와 얼마나 닮았나','닷컴·일본·크립토 등 과거 사례를 같은 시작점에서 비교합니다. 확률이 아닌 참고용 유사도입니다.'],
  'cross-asset':['교차자산 비교 · Dotcom 이후','닷컴 조정 뒤 자산별 회복은 어떻게 달랐을까','2001-03~2006-03 NASDAQ·Realty Income·D.R. Horton 실측과 Bitcoin 반사실 민감도를 같은 기준점에서 비교합니다.'],
  'ai-regime':['AI 자본 사이클 · Coverage Gate','AI 자본 사이클을 지금 판정할 수 있는가','필수 데이터 커버리지가 기준에 못 미치면 지도를 그리지 않고 판정을 보류합니다.'],
  liquidity:['유동성 · Tide Map','유동성 조건은 위험 선호를 지지하는가','주간 유동성·금융여건과 위험자산의 시차 관계를 참고용으로 점검합니다.']
};
function scenarioV5FlowModel(legacy,candidate){
  if(!candidate||!['ok','degraded'].includes(candidate.status)||candidate.runtime_gate?.display_eligible===false)return legacy;
  const distribution=candidate.conditional_distribution||{},allDates=distribution.dates||[];
  const scenarios=distribution.scenarios||{},bands=distribution.unconditional_bands||{};
  if(allDates.length!==253||!['S1','S2','S3'].every(key=>scenarios[key]?.representative_path_values?.length===allDates.length))return legacy;
  const indexes=[0];for(let index=5;index<allDates.length;index+=5)indexes.push(index);if(indexes.at(-1)!==allDates.length-1)indexes.push(allDates.length-1);
  const pick=values=>indexes.map(index=>values[index]);
  const labels={S1:'ATH breakout',S2:'No ATH; above reference',S3:'No ATH; at/below reference'};
  const risk=(distribution.unconditional_prob_touch_corr10||[]).map(value=>Number(value)>=.35?'고':(Number(value)>=.15?'중':'저'));
  return {
    ...legacy,asof:candidate.asof,method:'scenario-v5-evidence-conditioned-legacy-prior-v1',
    source:'Registered physical forecasts with separated risk-neutral and reference-only evidence',
    note:'Research candidate using entropy pooling over a reproduced legacy GBM prior. Not official and not champion.',
    anchor:Number(candidate.source_snapshot.anchor),ath:Number(candidate.source_snapshot.ath),corr10:Number(candidate.source_snapshot.corr10),
    weeks:indexes.map(index=>{const day=allDates[index]||'';return `${Number(day.slice(5,7))}/${Number(day.slice(8,10))}`;}),week_dates:indexes.map(index=>allDates[index]),
    paths:Object.fromEntries(['S1','S2','S3'].map(key=>[key,{label:labels[key],prob:Number((Number(scenarios[key].probability)*100).toFixed(1)),color:scenarios[key].color,end:Math.round(Number(scenarios[key].bands.p50.at(-1))),values:pick(scenarios[key].bands.p50),actual_member_values:pick(scenarios[key].representative_path_values)}])),
    fan:{probability_space:'posterior_predictive_unconditional',monitoring:'daily-discrete',baseline_method:'evidence-conditioned-posterior',quantiles:Object.fromEntries(Object.entries(bands).map(([key,values])=>[key,pick(values)]))},
    quantile_table:{status:'ok',probability_space:'scenario_conditional',probability_label:'model_conditional',basis:'Scenario V5 posterior',trading_days:allDates.slice(1),quantiles:Object.fromEntries(Object.entries(bands).map(([key,values])=>[key,values.slice(1)])),prob_above_anchor:(distribution.unconditional_prob_above_anchor||[]).slice(1).map(value=>Number((Number(value)*100).toFixed(1))),prob_above_ath:(distribution.unconditional_prob_above_ath||[]).slice(1).map(value=>Number((Number(value)*100).toFixed(1))),per_scenario_p50:Object.fromEntries(['S1','S2','S3'].map(key=>[key,scenarios[key].bands.p50.slice(1)])),per_scenario_counts:Object.fromEntries(['S1','S2','S3'].map(key=>[key,scenarios[key].path_count]))},
    risk:pick(risk),events:legacy.events,calendar_events:legacy.calendar_events,horizon_coverage:legacy.horizon_coverage,
    model:{lookback_days:legacy.model?.lookback_days,horizon_business_days:252,classification_date:candidate.source_snapshot.classification_date,n_paths:candidate.prior.path_count,seed:candidate.prior.seed,probability_space:'scenario_conditional',promotion_state:candidate.promotion.state},
    analog:null,path_realism:null,structural_forecast:null,scenario_v5_candidate:true,
    representative_lines_visible:distribution.representative_lines_visible,same_shape_diagnostics:distribution.same_shape_diagnostics,
    evidence_views:candidate.evidence_views,posterior_diagnostics:candidate.posterior_diagnostics,banner:candidate.banner,model_content_sha256:candidate.model_content_sha256,
    three_distinct_2027_paths:candidate.display_contract?.three_distinct_2027_paths!==false,continuation_disclosure:candidate.display_contract?.continuation_disclosure
  };
}
function scenarioV5ConditionalFanMarkup(candidate){
  const scenarios=candidate?.conditional_distribution?.scenarios||{},keys=['S1','S2','S3'],allDates=candidate?.conditional_distribution?.dates||[];
  if(!keys.every(key=>scenarios[key]?.bands?.p10?.length))return '';
  const classification=candidate?.source_snapshot?.classification_date||'2026-12-31',endIndex=Math.max(0,allDates.findLastIndex(day=>day<=classification));
  const indexes=[0];for(let index=5;index<endIndex;index+=5)indexes.push(index);if(indexes.at(-1)!==endIndex)indexes.push(endIndex);
  const pick=values=>indexes.map(index=>Number(values[index]));
  const all=keys.flatMap(key=>{const row=scenarios[key],visibility=row.band_visibility||{},bandKeys=visibility.p10_p90?['p10','p90']:(visibility.p25_p75?['p25','p75']:[]);return [...bandKeys.flatMap(name=>pick(row.bands[name])),...pick(row.bands.p50),...pick(row.representative_path_values)];});
  const low=Math.min(...all),high=Math.max(...all),W=320,H=132,P=10,X=index=>P+(W-P*2)*index/(indexes.length-1),Y=value=>P+(H-P*2)*(1-(value-low)/Math.max(1,high-low));
  const line=values=>values.map((value,index)=>`${index?'L':'M'}${X(index).toFixed(1)},${Y(value).toFixed(1)}`).join(' ');
  return `<section class="scenario-v5-fans" aria-labelledby="scenario-v5-fans-title"><div class="scenario-v5-section-head"><div><span>CONDITIONAL DISTRIBUTIONS</span><h3 id="scenario-v5-fans-title">시나리오별 조건부 p50과 실제 모의 멤버</h3></div><small>굵은 실선 = weighted p50 · 가는 점선 = one actual member · ESS gate</small></div><div class="scenario-v5-fan-grid">${keys.map(key=>{const row=scenarios[key],p50=pick(row.bands.p50),member=pick(row.representative_path_values),visibility=row.band_visibility||{},bandKeys=visibility.p10_p90?['p10','p90']:(visibility.p25_p75?['p25','p75']:null),lower=bandKeys?pick(row.bands[bandKeys[0]]):null,upper=bandKeys?pick(row.bands[bandKeys[1]]):null;let band='';if(bandKeys){band=line(upper);for(let index=lower.length-1;index>=0;index--)band+=` L${X(index).toFixed(1)},${Y(lower[index]).toFixed(1)}`;}return `<article><header><div><strong style="color:${esc(row.color)}">${key}</strong><span>${esc(row.label)}</span></div><b>${(Number(row.probability)*100).toFixed(1)}%</b></header><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${key} conditional weighted p50 and one simulated member">${bandKeys?`<path d="${band} Z" fill="${esc(row.color)}" opacity=".12"></path>`:''}<path d="${line(member)}" fill="none" stroke="${esc(row.color)}" stroke-width="1.2" stroke-dasharray="3 4" opacity=".62"></path><path d="${line(p50)}" fill="none" stroke="${esc(row.color)}" stroke-width="2.8" stroke-linejoin="round"></path></svg><footer><span>${bandKeys?`${bandKeys[0]} ${num(Math.round(lower.at(-1)))}`:'fan gated'}</span><span>p50 ${num(Math.round(p50.at(-1)))}</span><span>${bandKeys?`${bandKeys[1]} ${num(Math.round(upper.at(-1)))}`:'ESS < 500'}</span><span>ESS ${num(row.weighted_effective_sample_size)}</span></footer><p>실제로 나온 경로 하나 · 날짜별 값을 맞히는 선이 아닙니다</p></article>`;}).join('')}</div></section>`;
}
function scenarioV5TimingMarkup(candidate){const timing=candidate?.correction_timing_distribution;if(!timing?.dates?.length)return '';const points=Object.entries(timing.cdf_points||{});const maxDensity=Math.max(...timing.density,1e-12);const bars=timing.density.map((value,index)=>`<i title="${esc(timing.dates[index])}" style="height:${Math.max(1,Math.round(Number(value)/maxDensity*100))}%"></i>`).join('');return `<section class="scenario-v5-timing" aria-labelledby="scenario-v5-timing-title"><div class="scenario-v5-section-head"><div><span>FIRST-TOUCH DISTRIBUTION</span><h3 id="scenario-v5-timing-title">−10%선 조정 최초 터치 시점 분포</h3></div><strong>${(Number(timing.any_touch_probability)*100).toFixed(1)}% any touch</strong></div><div class="scenario-v5-density" aria-label="first-touch density histogram">${bars}</div><div class="scenario-v5-timing-points">${points.map(([day,value])=>`<span><b>${esc(day.slice(5))}</b>${(Number(value)*100).toFixed(1)}% CDF</span>`).join('')}</div><footer>조건부 p25 ${esc(timing.conditional_on_touch_quantiles?.p25||'–')} · median ${esc(timing.conditional_on_touch_quantiles?.p50||'–')} · p75 ${esc(timing.conditional_on_touch_quantiles?.p75||'–')} · exact date forecast=false</footer></section>`;}
function scenarioV5EvidenceMarkup(candidate){
  const views=candidate?.evidence_views||[];if(!views.length)return '';
  const state=row=>row.used_numerically?'USED':(String(row.numerical_status||'').startsWith('BLOCKED')||row.approval_status==='blocked'?'BLOCKED':(row.view_kind==='event_probability'&&row.origin_type==='registered_forecast'?'EVENT STATE ONLY':'REFERENCE'));
  return `<section class="scenario-v5-evidence" aria-labelledby="scenario-v5-evidence-title"><div class="scenario-v5-section-head"><div><span>EVIDENCE VIEW REGISTRY</span><h3 id="scenario-v5-evidence-title">무엇이 경로를 움직였고 무엇이 참고값인가</h3></div><small>probability unit = fraction · PIT source hash recorded</small></div><div class="scenario-v5-evidence-grid">${views.map(row=>`<article class="is-${state(row).toLowerCase().replaceAll(' ','-')}"><header><span>${esc(state(row))}</span><b>${hasNumeric(row.target)?(Number(row.target)*100).toFixed(1)+'%':'–'}</b></header><strong>${esc(row.source_id)}</strong><small>${esc(row.probability_space)} · ${esc(row.view_kind)}</small><p>${esc(row.used_numerically?row.condition:(row.blocked_reason||'numerical use blocked'))}</p></article>`).join('')}</div><footer>승인된 report view: ${(views.filter(row=>['strategist_report','analyst_consensus','macro_consensus'].includes(row.origin_type)&&row.used_numerically)).length} · 보고서 문장을 임의 숫자로 변환하지 않았습니다.</footer></section>`;
}
const V52_SCENARIO_META={
  S1:{title:'확장 경로',copy:'닷컴·완화·AI 확장 6개 등록 에피소드',color:'#147a5b'},
  S2:{title:'균형 경로',copy:'비위기 연착륙·횡보 4개 등록 에피소드',color:'#d98600'},
  S3:{title:'스트레스 경로',copy:'닷컴 붕괴·GFC·긴축 5개 등록 에피소드',color:'#be123c'}
};
// V5.2 paths are daily observations. Resolve month controls by calendar date,
// never by array index: index 3 is three days, not three months.
const V52_RANGE_META={month:['다음 1개월',{months:1}],quarter:['3개월',{months:3}],year2026:['2026 연말',null],year2027:['2027 연말',null]};
function scenarioV52CalendarEnd(dates,months){
  if(!dates.length)return 0;
  const start=new Date(`${dates[0]}T00:00:00Z`),target=new Date(start);
  target.setUTCMonth(target.getUTCMonth()+Number(months||0));
  const targetDay=target.toISOString().slice(0,10),found=dates.findLastIndex(day=>day<=targetDay);
  return found>=0?found:dates.length-1;
}
function scenarioV52Range(candidate,key='month'){
  const dates=candidate?.conditional_small_multiples?.dates||candidate?.distribution?.dates||[];
  const rule=V52_RANGE_META[key]?.[1];
  let end=rule?.months?scenarioV52CalendarEnd(dates,rule.months):dates.length-1;
  if(key==='year2026'){const found=dates.findLastIndex(day=>day<='2026-12-31');end=found>=0?found:end;}
  if(key==='year2027'){const found=dates.findLastIndex(day=>day<='2027-12-31');end=found>=0?found:end;}
  end=Math.max(1,Math.min(end,dates.length-1));
  return {key,label:V52_RANGE_META[key]?.[0]||V52_RANGE_META.quarter[0],dates:dates.slice(0,end+1),end};
}
function scenarioV52UnifiedChart(candidate,rangeKey='quarter'){
  const range=scenarioV52Range(candidate,rangeKey),scenarios=candidate?.conditional_small_multiples?.scenarios||{},dist=candidate?.distribution||{};
  const historical=dist.historical_actual||{},histDates=(historical.dates||[]).slice(-31,-1),histValues=(historical.values||[]).slice(-31,-1);
  const dates=[...histDates,...range.dates],histLength=histDates.length,n=dates.length,keys=['S1','S2','S3'];
  const scenarioSeries=Object.fromEntries(keys.map(key=>[key,[...histValues,...(scenarios[key]?.bands?.p50||[]).slice(0,range.end+1).map(Number)]]));
  const medoids=Object.fromEntries(keys.map(key=>[key,[...histValues,...(scenarios[key]?.central_path_bundle?.medoid_values||[]).slice(0,range.end+1).map(Number)]]));
  const mixtureLower=[...histValues,...(dist.bands?.p25||[]).slice(0,range.end+1).map(Number)],mixtureUpper=[...histValues,...(dist.bands?.p75||[]).slice(0,range.end+1).map(Number)];
  const all=[...Object.values(scenarioSeries).flat(),...Object.values(medoids).flat(),...mixtureLower,...mixtureUpper].filter(value=>Number.isFinite(value)&&value>0);
  if(!dates.length||!all.length)return '<p class="empty-copy">표시할 전망 경로가 없습니다.</p>';
  const W=1160,H=450,ML=72,MR=46,MT=32,MB=54,lo=Math.min(...all)*.985,hi=Math.max(...all)*1.015,logLo=Math.log(lo),logHi=Math.log(hi),PW=W-ML-MR,historyShare=.25,forecastShare=.75,boundaryX=ML+PW*historyShare;
  const X=index=>index<histLength?ML+PW*historyShare*index/Math.max(1,histLength-1):boundaryX+PW*forecastShare*(index-histLength)/Math.max(1,range.dates.length-1),Y=value=>MT+(H-MT-MB)*(1-(Math.log(Math.max(Number(value),1e-9))-logLo)/Math.max(1e-9,logHi-logLo));
  const line=values=>values.map((value,index)=>`${index?'L':'M'}${X(index).toFixed(1)},${Y(value).toFixed(1)}`).join(' ');
  const area=(lower,upper)=>`${line(upper)} ${lower.map((value,index)=>`L${X(n-1-index).toFixed(1)},${Y(lower[n-1-index]).toFixed(1)}`).join(' ')} Z`;
  const yTicks=Array.from({length:5},(_,index)=>Math.exp(logLo+(logHi-logLo)*index/4));
  const xTicks=[0,Math.floor(Math.max(0,histLength-1)/2),...(range.dates.length>4?[Math.max(0,histLength-1),histLength+Math.floor(range.dates.length/2)]:[]),n-1].filter((value,index,array)=>array.indexOf(value)===index&&value<n);
  const boundary=histLength?X(histLength):null;
  const endpointLabel=key=>{const values=medoids[key],start=Number(values[histLength]),end=Number(values.at(-1)),change=(end/start-1)*100;return `${key} ${change>=0?'+':''}${change.toFixed(1)}%`;};
  return `<svg viewBox="0 0 ${W} ${H}" role="img" data-scale="log" data-history-share="0.25" data-forecast-share="0.75" aria-label="${esc(range.label)} S1 S2 S3 실제 모의 중심 경로 통합 로그 스케일 전망. 굵은 선은 시나리오별 실제 모의 경로 한 개이며 중심 경향이 아닙니다">
    <rect x="${ML}" y="${MT}" width="${(PW*historyShare).toFixed(1)}" height="${H-MT-MB}" fill="#f5f3ee" opacity=".58" data-time-zone="history"/>
    <rect x="${boundaryX.toFixed(1)}" y="${MT}" width="${(PW*forecastShare).toFixed(1)}" height="${H-MT-MB}" fill="#fff8ef" opacity=".52" data-time-zone="forecast"/>
    ${yTicks.map(value=>`<line x1="${ML}" x2="${W-MR}" y1="${Y(value).toFixed(1)}" y2="${Y(value).toFixed(1)}" stroke="#e5e1d8"/><text x="${ML-10}" y="${(Y(value)+4).toFixed(1)}" text-anchor="end">${num(Math.round(value))}</text>`).join('')}
    ${xTicks.map(index=>`<text x="${X(index).toFixed(1)}" y="${H-18}" text-anchor="${index===0?'start':index===n-1?'end':'middle'}">${esc(String(dates[index]||'').slice(2))}</text>`).join('')}
    <path d="${area(mixtureLower,mixtureUpper)}" fill="#8893a4" opacity=".10" data-path-role="mixture-p25-p75"/>
    ${boundary!=null?`<line x1="${boundary.toFixed(1)}" x2="${boundary.toFixed(1)}" y1="${MT}" y2="${H-MB}" stroke="#82786a" stroke-dasharray="4 5" data-forecast-boundary="true"/><text x="${(boundary+8).toFixed(1)}" y="${MT+14}">전망 시작</text>`:''}
    ${histValues.length?`<path d="${line([...histValues,range.dates.length?[histValues.at(-1)]:[]].flat())}" fill="none" stroke="#34322e" stroke-width="2.2" data-path-role="historical-actual"/>`:''}
    ${keys.map(key=>`<path d="${line(scenarioSeries[key])}" fill="none" stroke="${V52_SCENARIO_META[key].color}" stroke-width="1.4" stroke-dasharray="4 6" opacity=".42" data-scenario-p50="${key}"/>`).join('')}
    ${keys.map(key=>`<path d="${line(medoids[key])}" fill="none" stroke="${V52_SCENARIO_META[key].color}" stroke-width="2.8" stroke-linejoin="round" stroke-linecap="round" data-path-role="${key}-actual-medoid"/>`).join('')}
    ${keys.map(key=>`<circle cx="${X(n-1).toFixed(1)}" cy="${Y(medoids[key].at(-1)).toFixed(1)}" r="4.5" fill="${V52_SCENARIO_META[key].color}"/><text x="${(X(n-1)-10).toFixed(1)}" y="${(Y(medoids[key].at(-1))-9).toFixed(1)}" text-anchor="end" fill="${V52_SCENARIO_META[key].color}" font-weight="700" data-scenario-end-label="${key}">${endpointLabel(key)}</text>`).join('')}
  </svg>`;
}
function scenarioV52RangeReadout(candidate,rangeKey='quarter'){
  const range=scenarioV52Range(candidate,rangeKey),scenarios=candidate?.conditional_small_multiples?.scenarios||{},anchor=Number(candidate.anchor?.close??candidate.anchor??candidate.distribution?.bands?.p50?.[0]);
  return `<div class="scenario-v52-range-date"><span>선택 기간</span><strong>${esc(range.label)}</strong><small>${esc(range.dates.at(-1)||'—')} 기준</small></div>${['S1','S2','S3'].map(key=>{const value=Number(scenarios[key]?.bands?.p50?.[range.end]),change=(value/anchor-1)*100,direction=change>1?'상승':change< -1?'하락':'중립';return `<div><span>${key} · ${V52_SCENARIO_META[key].title}</span><strong style="color:${V52_SCENARIO_META[key].color}">${direction} · ${num(Math.round(value))}</strong><small>${change>=0?'+':''}${change.toFixed(1)}% · 연구 코호트 가중치 ${Math.round(Number(scenarios[key]?.probability||0)*100)}%</small></div>`;}).join('')}`;
}
const hasStructuralPaths=candidate=>['S1','S2','S3'].every(key=>Array.isArray(candidate?.structural_forecast?.paths?.[key]?.values)&&candidate.structural_forecast.paths[key].values.length===candidate?.week_dates?.length);
function chartGuide(rows,caution){
  const items=(rows||[]).filter(Boolean).map(([swatch,label,text])=>`<div class="chart-guide-row"><i class="chart-guide-mark" style="${swatch}"></i><b>${label}</b><span>${text}</span></div>`).join('');
  return `<div class="chart-guide"><p class="chart-guide-title">읽는 법</p>${items}${caution?`<p class="chart-guide-caution"><b>참고용</b> ${caution}</p>`:''}</div>`;
}
const GUIDE_SOLID=color=>`background:${color};height:3px`;
const GUIDE_DASH=color=>`background:repeating-linear-gradient(90deg,${color} 0 4px,transparent 4px 8px);height:3px`;
const GUIDE_BAND=color=>`background:${color};height:11px;border-radius:2px`;
function drawOriginalWeeklyFlow(host,sc,showSamples=false,scenarioKey='S1'){
  const NS='http://www.w3.org/2000/svg';
  const W=1160,H=620,ML=58,MR=148,MT=120,MB=30,HCH=550;
  const weeks=sc.weeks||[],n=weeks.length,riskValues=sc.risk||[];
  if(n<2){host.replaceChildren(el('<p class="chart-note">주간 시나리오 데이터가 없어 이 그래프를 그릴 수 없습니다.</p>'));return;}
  const structuralSource=Object.fromEntries(['S1','S2','S3'].map(key=>[key,flowDisplayPath(sc,key)]));
  const rawSource=Object.fromEntries(['S1','S2','S3'].map(key=>[key,sc.paths?.[key]?.values||[]]));
  const usingStructural=hasStructuralPaths(sc);
  const paths=Object.fromEntries(['S1','S2','S3'].map(key=>[key,structuralSource[key].slice(0,n).map(Number)]));
  const rawPaths=Object.fromEntries(['S1','S2','S3'].map(key=>[key,rawSource[key].slice(0,n).map(Number)]));
  const activeKey=['S1','S2','S3'].includes(scenarioKey)?scenarioKey:'S1';
  const sampleRows=showSamples?[activeKey].flatMap(key=>(sc.path_realism?.[key]?.sample_paths||[]).map((row,order)=>({key,order,percentile:Number(row.terminal_percentile),values:(row.values||[]).slice(0,n).map(Number)}))).filter(row=>row.values.length===n):[];
  const clip=Number(sc.analog?.clip),rawAnalog=(sc.analog?.values||[]).slice(0,n).map(Number);
  const analogValues=rawAnalog.map(value=>Number.isFinite(clip)?Math.min(value,clip):value).filter(Number.isFinite);
  const chartValues=[sc.ath,sc.corr10,sc.anchor,...Object.values(paths).flat(),...(usingStructural?Object.values(rawPaths).flat():[]),...sampleRows.flatMap(row=>row.values),...analogValues].map(Number).filter(Number.isFinite);
  const chartLow=Math.min(...chartValues),chartHigh=Math.max(...chartValues),chartPad=Math.max(500,(chartHigh-chartLow)*.08);
  const Y0=Math.floor((chartLow-chartPad)/500)*500,Y1=Math.ceil((chartHigh+chartPad)/500)*500;
  const PW=W-ML-MR,PH=HCH-MT-MB,X=index=>ML+PW*index/Math.max(1,n-1),Y=value=>MT+PH*(1-(value-Y0)/(Y1-Y0));
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width','100%');
  svg.setAttribute('role','img');svg.setAttribute('tabindex','0');
  svg.setAttribute('aria-label',`${sc.asof} 앵커 기준 단일 시나리오 주간 흐름. ${esc(sc.paths?.[activeKey]?.label||activeKey)} ${usingStructural?'DB 조건부 구조 경로':'조건부 중앙 경로'}와 혁신사이클 참조선${usingStructural?', 굴곡 적용 전 GBM 중앙값 고스트 선':''}${showSamples?', 실제 모의 경로 표본':''}, 주차별 −10%선 누적 터치확률. 좌우 화살표로 기준 주차 이동`);
  const mk=(tag,attrs)=>{const node=document.createElementNS(NS,tag);for(const key in attrs)node.setAttribute(key,attrs[key]);return node;};
  const tx=(x,y,value,opts={})=>{const node=mk('text',{x,y,fill:opts.fill||'rgba(17,17,15,.66)','font-size':opts.fs||12,'text-anchor':opts.anc||'start','font-weight':opts.w||400});node.textContent=value;return node;};
  const halo=node=>{node.setAttribute('paint-order','stroke');node.setAttribute('stroke','#fff');node.setAttribute('stroke-width','4');node.setAttribute('stroke-linejoin','round');return node;};
  const gridStep=Math.max(500,Math.ceil(((Y1-Y0)/6)/500)*500);
  for(let value=Math.ceil(Y0/gridStep)*gridStep;value<=Y1;value+=gridStep){
    svg.appendChild(mk('line',{x1:ML,y1:Y(value),x2:ML+PW,y2:Y(value),stroke:'rgba(17,17,15,.09)','stroke-width':1}));
    svg.appendChild(tx(ML-8,Y(value)+4,(value/1000)+'k',{anc:'end',fill:'#5f5d57'}));
  }
  svg.appendChild(mk('line',{x1:ML,y1:Y(sc.ath),x2:ML+PW,y2:Y(sc.ath),stroke:'rgba(17,17,15,.3)','stroke-width':1,'stroke-dasharray':'5 4'}));
  svg.appendChild(mk('line',{x1:ML,y1:Y(sc.corr10),x2:ML+PW,y2:Y(sc.corr10),stroke:'rgba(255,128,102,.55)','stroke-width':1,'stroke-dasharray':'5 4'}));
  const eventRows=(sc.events||[]).filter(row=>Array.isArray(row)&&Number.isFinite(Number(row[0]))).map(row=>[Number(row[0]),String(row[1]||'')]);
  flowEventLayout(eventRows,n-1,X,ML,ML+PW,4).forEach(({label,eventX,labelX,lane})=>{
    const labelY=22+lane*24,circleY=labelY+9;
    svg.appendChild(mk('line',{x1:eventX,y1:circleY+3,x2:eventX,y2:MT+PH,stroke:'rgba(17,17,15,.13)','stroke-width':1,'stroke-dasharray':'2 4'}));
    if(Math.abs(labelX-eventX)>1)svg.appendChild(mk('line',{x1:labelX,y1:circleY,x2:eventX,y2:circleY,stroke:'rgba(17,17,15,.28)','stroke-width':1}));
    svg.appendChild(mk('circle',{cx:eventX,cy:circleY,r:2.4,fill:'rgba(17,17,15,.55)'}));
    svg.appendChild(halo(tx(labelX,labelY,label,{anc:'middle',fill:'#4f4d47',fs:11,w:700})));
  });
  const rightLabels=[];
  if(analogValues.length===n){
    let analogPath='';analogValues.forEach((value,index)=>{analogPath+=(index?'L':'M')+X(index)+','+Y(value)+' ';});
    svg.appendChild(mk('path',{d:analogPath,fill:'none',stroke:'#706f68','stroke-width':1.6,'stroke-dasharray':'6 5','stroke-linejoin':'round',opacity:.72,'data-reference-path':'innovation-cycle'}));
    const rawEnd=rawAnalog[n-1],shownEnd=analogValues[n-1];
    if(Number.isFinite(rawEnd)&&Number.isFinite(shownEnd)&&rawEnd>shownEnd)svg.appendChild(halo(tx(X(n-1)-6,Y(shownEnd)-9,`↗ +${Math.round((rawEnd/Number(sc.anchor)-1)*100)}%`,{anc:'end',fill:'#706f68',fs:11,w:700})));
    rightLabels.push({key:'analog',y:Y(shownEnd),text:'혁신사이클 참조',color:'#706f68',opacity:1,weight:650,fontSize:11});
  }
  sampleRows.forEach(row=>{
    let d='';row.values.forEach((value,index)=>{d+=(index?'L':'M')+X(index)+','+Y(value)+' ';});
    svg.appendChild(mk('path',{d,fill:'none',stroke:'#5f6470','stroke-width':row.percentile===50?1.25:1,'stroke-dasharray':row.order===0?'3 3':'7 3',opacity:row.percentile===50?.42:.28,'data-sample-path':`${row.key}-${row.percentile}`}));
  });
  if(usingStructural)[activeKey].forEach(key=>{
    const values=rawPaths[key];if(values.length!==n)return;
    let d='';values.forEach((value,index)=>{d+=(index?'L':'M')+X(index)+','+Y(value)+' ';});
    svg.appendChild(mk('path',{d,fill:'none',stroke:'#697078','stroke-width':1.35,'stroke-dasharray':'2 5','stroke-linecap':'round','stroke-linejoin':'round',opacity:.5,'data-baseline-path':key}));
  });
  [activeKey].forEach(key=>{
    const values=paths[key];if(values.length!==n)return;
    let d='';values.forEach((value,index)=>{d+=(index?'L':'M')+X(index)+','+Y(value)+' ';});
    svg.appendChild(mk('path',{d,fill:'none',stroke:CHART_COL[key],'stroke-width':2.6,'stroke-linejoin':'round','data-original-path':key}));
    const endValue=values[n-1];
    svg.appendChild(mk('circle',{cx:X(n-1),cy:Y(endValue),r:3.8,fill:CHART_COL[key],stroke:'#fff','stroke-width':1.6}));
    rightLabels.push({key,y:Y(endValue),text:`${key} ${num(endValue)} · ${sc.paths?.[key]?.prob}%`,color:CHART_LABEL_COL[key],opacity:1,weight:750,fontSize:12});
  });
  rightLabels.push({key:'ath',y:Y(sc.ath),text:`ATH ${num(sc.ath)}`,color:'rgba(17,17,15,.62)',opacity:1,weight:650,fontSize:11});
  rightLabels.push({key:'corr10',y:Y(sc.corr10),text:`−10% ${num(sc.corr10)}`,color:'#c9002d',opacity:1,weight:650,fontSize:11});
  resolveEndpointLabels(rightLabels,19,MT+10,MT+PH-10).forEach(item=>{
    const labelX=ML+PW+19;
    svg.appendChild(mk('path',{d:`M${ML+PW+5},${item.y} L${ML+PW+12},${item.y} L${labelX-3},${item.labelY}`,fill:'none',stroke:item.color,'stroke-width':1,opacity:item.opacity*.72}));
    svg.appendChild(halo(tx(labelX,item.labelY+4,item.text,{fill:item.color,fs:item.fontSize,w:item.weight})));
  });
  svg.appendChild(mk('circle',{cx:X(0),cy:Y(sc.anchor),r:4,fill:'#11110f',stroke:'#fff','stroke-width':1.5}));
  svg.appendChild(halo(tx(X(0)-6,Y(sc.anchor)-11,'현재 '+num(Math.round(Number(sc.anchor))),{fill:'#11110f',w:600})));
  flowAxisTickIndexes(n,7).forEach((index,tickPosition)=>{
    svg.appendChild(mk('line',{x1:X(index),y1:MT+PH,x2:X(index),y2:MT+PH+5,stroke:'rgba(17,17,15,.28)'}));
    svg.appendChild(tx(X(index),MT+PH+18,tickPosition===0?'현재 · '+weeks[index]:weeks[index],{anc:'middle',fs:12,fill:tickPosition?'#5f5d57':'#174c49',w:tickPosition?500:750}));
  });
  const RY=HCH+8,RH=28;svg.appendChild(tx(ML-8,RY+19,'−10%선 누적 터치확률',{anc:'end',fill:'#5f5d57',fs:11}));
  let segmentStart=0;
  for(let index=1;index<=n;index++){
    if(index<n&&riskValues[index]===riskValues[segmentStart])continue;
    const end=index-1,risk=riskValues[segmentStart];
    const left=segmentStart===0?X(0)-2:(X(segmentStart-1)+X(segmentStart))/2,right=end===n-1?X(end)+2:(X(end)+X(end+1))/2,width=Math.max(1,right-left);
    const fill=risk==='고'?'rgba(201,0,45,.92)':(risk==='중'?'rgba(255,157,25,.48)':'rgba(36,125,120,.34)'),textColor=risk==='고'?'#fff':(risk==='중'?'#513300':'#174c49');
    svg.appendChild(mk('rect',{x:left,y:RY,width,height:RH,fill,stroke:'rgba(17,17,15,.1)'}));
    if(width>=28&&risk)svg.appendChild(tx(left+width/2,RY+18,risk,{anc:'middle',fs:12,fill:textColor,w:700}));
    segmentStart=index;
  }
  const xh=mk('line',{stroke:'rgba(17,17,15,.44)','stroke-width':1.2,'stroke-dasharray':'4 3'});svg.appendChild(xh);
  const cursorMarkers=[activeKey].map(key=>{const marker=mk('circle',{r:5.2,fill:CHART_COL[key],stroke:'#fff','stroke-width':2,opacity:paths[key].length===n?1:0});svg.appendChild(marker);return marker;});
  const overlay=mk('rect',{x:ML,y:MT,width:PW,height:PH,fill:'transparent'});svg.appendChild(overlay);
  const tip=document.getElementById('tip'),finePointer=window.matchMedia('(pointer: fine)').matches;
  let cursorIndex=0;
  const paintCursor=index=>{
    cursorIndex=Math.max(0,Math.min(n-1,index));const x=X(cursorIndex);
    xh.setAttribute('x1',x);xh.setAttribute('x2',x);xh.setAttribute('y1',MT);xh.setAttribute('y2',MT+PH);
    [activeKey].forEach((key,markerIndex)=>{if(paths[key].length!==n)return;cursorMarkers[markerIndex].setAttribute('cx',x);cursorMarkers[markerIndex].setAttribute('cy',Y(paths[key][cursorIndex]));});
  };
  const indexFromPointer=event=>{const rect=svg.getBoundingClientRect(),mouseX=(event.clientX-rect.left)*(W/rect.width);return Math.max(0,Math.min(n-1,Math.round((mouseX-ML)/(PW/Math.max(1,n-1)))));};
  overlay.addEventListener('pointermove',event=>{
    const index=indexFromPointer(event);paintCursor(index);
    if(!finePointer)return;
    tip.style.display='block';tip.style.left=(event.clientX+14)+'px';tip.style.top=(event.clientY-10)+'px';
    tip.innerHTML=`<b>${esc(weeks[index])}</b> · −10%선 누적 터치확률 ${esc(riskValues[index]||'—')}<br>${[activeKey].filter(key=>paths[key].length===n).map(key=>`<span style="color:${CHART_COL[key]}">${esc(sc.paths?.[key]?.label||key)} ${num(paths[key][index])}</span>`).join('<br>')}${analogValues[index]!=null?`<br><span style="color:#706f68">혁신사이클 참조 ${num(analogValues[index])} · 확률 아님</span>`:''}`;
  });
  overlay.addEventListener('pointerdown',event=>{paintCursor(indexFromPointer(event));if(!finePointer)tip.style.display='none';svg.focus();});
  overlay.addEventListener('pointerleave',()=>{tip.style.display='none';});
  svg.addEventListener('keydown',event=>{
    if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();paintCursor(cursorIndex+(event.key==='ArrowLeft'?-1:1));}
    else if(event.key==='Home'){event.preventDefault();paintCursor(0);}
    else if(event.key==='End'){event.preventDefault();paintCursor(n-1);}
  });
  host.replaceChildren(svg);paintCursor(0);
}
function originalFlowPanel(){
  const sc=DATA.scenario;
  if(!sc||!Array.isArray(sc.weeks)||sc.weeks.length<2||!sc.paths)return null;
  const structural=hasStructuralPaths(sc);
  const memberCount=['S1','S2','S3'].reduce((total,key)=>total+((sc.path_realism?.[key]?.sample_paths||[]).length),0);
  const scenarioPick=`<div class="cross-view-switch original-scenario-switch" role="group" aria-label="표시할 시나리오">${['S1','S2','S3'].map(key=>`<button type="button" data-original-scenario="${key}" aria-pressed="${String(key==='S1')}">${key} ${esc(sc.paths?.[key]?.label||'')} · ${esc(sc.paths?.[key]?.prob)}%</button>`).join('')}</div>`;
  const analogLegend=sc.analog?.values?.length?`<span><b style="background:#706f68"></b>${esc(sc.analog.label||'혁신사이클 참조선 — 시나리오 아님')}</span>`:'';
  const ghostLegend=structural?'<span><b class="baseline-swatch"></b>굴곡 적용 전 GBM 중앙값</span>':'';
  const memberControl=memberCount?`<div class="flow-shape-controls" role="group" aria-label="실제 모의 경로 표시"><span>PATH LAYERS</span><button type="button" data-original-samples aria-pressed="false"><i></i>실제 모의 경로 ${num(memberCount)}개 같이 보기</button><small>기본 숨김 · 대표선으로 쓰지 않습니다</small></div>`:'';
  const panel=el(`<section class="chart-panel original-flow-panel" aria-labelledby="original-flow-title">
    <div class="panel-head"><div><p class="eyebrow">단일 시나리오 · 챔피언 GBM · 참고 의견</p>
      <h2 id="original-flow-title">주간 시나리오 흐름 · 앵커 ${num(Math.round(Number(sc.anchor)))}</h2>
      <p>최초 버전의 그래프입니다. 한 번에 한 경로만 그립니다. 기본 그래프인 세 가지 시장 경로를 대체하지 않습니다.</p></div>
      <span class="count-chip">기준 ${esc(sc.asof)}</span></div>
    ${scenarioPick}
    <div class="band-inline"><span><b data-original-active-swatch style="background:${CHART_COL.S1}"></b><b data-original-active-label>${esc(sc.paths?.S1?.label||'S1')} 경로</b></span>${ghostLegend}${analogLegend}</div>
    ${memberControl}
    <div class="chart-wrap"><div id="original-flow-chart"></div></div>
    <details class="chart-method"><summary>이 그래프는 어떻게 만들었나</summary><p>${esc(sc.note||'')}</p><p>굵은 선은 과거 조정 모양을 입힌 경로이고, 회색 점선은 그 모양을 입히기 전의 밋밋한 평균입니다. 굴곡은 '이 달쯤 위험했다'는 과거 형태이지 특정 날짜 예측이 아니며, 모의 표본을 대표선으로 쓰지 않습니다.</p></details>
    ${chartGuide([
      [GUIDE_SOLID(CHART_COL.S1),'굵은 선','과거 조정 모양을 입힌 이 시나리오의 경로'],
      structural?[GUIDE_DASH('#697078'),'회색 점선','그 모양을 입히기 전의 밋밋한 평균']:null,
      [GUIDE_BAND('rgba(255,157,25,.48)'),'아래 띠','이 주까지 −10%선 누적 터치확률 (저·중·고)'],
      sc.analog?.values?.length?[GUIDE_DASH('#706f68'),'긴 회색 대시','닷컴 때 흐름 — 참조선일 뿐 시나리오 아님']:null,
      memberCount?[GUIDE_DASH('#5f6470'),'얇은 점선','켜면 보이는 실제 모의 경로 (표본이지 대표선 아님)']:null
    ],'특정 날짜의 가격을 맞히는 그래프가 아닙니다. 투자 자문이 아닙니다.')}
    ${structural?'<p class="chart-note">세 경로는 <b>조정 모양이 같고 크기만 다릅니다.</b> 겹치면 서로 다른 세 경로처럼 보여서 한 번에 하나만 보여줍니다.</p>':''}
    <div class="scenario-v52-readout" data-original-endpoints>${['S1','S2','S3'].map(key=>`<div><span>${key} · ${esc(sc.paths?.[key]?.label||'')}</span><strong style="color:${CHART_LABEL_COL[key]}">${num(Math.round(Number((flowDisplayPath(sc,key)||[]).at(-1)||0)))}</strong><small>연구 코호트 비중 ${esc(sc.paths?.[key]?.prob)}%</small></div>`).join('')}</div>
    ${memberCount?'<p class="chart-note chart-note-accent" data-original-sample-note hidden>얇은 점선은 <b>실제로 나온 경로 하나하나</b>입니다. 표본일 뿐 대표선이 아니고, 날짜별 값을 맞히려는 선도 아닙니다.</p>':''}
  </section>`);
  const chartHost=$('#original-flow-chart',panel),sampleNote=$('[data-original-sample-note]',panel),sampleButton=$('[data-original-samples]',panel);
  const activeSwatch=$('[data-original-active-swatch]',panel),activeLabel=$('[data-original-active-label]',panel);
  let samplesOn=false,scenarioKey='S1';
  const paintOriginal=()=>{
    drawOriginalWeeklyFlow(chartHost,sc,samplesOn,scenarioKey);
    panel.querySelectorAll('[data-original-scenario]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.originalScenario===scenarioKey)));
    if(activeSwatch)activeSwatch.style.background=CHART_COL[scenarioKey];
    if(activeLabel)activeLabel.textContent=`${sc.paths?.[scenarioKey]?.label||scenarioKey} 경로`;
    if(sampleButton)sampleButton.setAttribute('aria-pressed',String(samplesOn));
    if(sampleNote)sampleNote.hidden=!samplesOn;
  };
  if(sampleButton)sampleButton.onclick=()=>{samplesOn=!samplesOn;paintOriginal();};
  panel.querySelectorAll('[data-original-scenario]').forEach(button=>{button.onclick=()=>{scenarioKey=button.dataset.originalScenario;paintOriginal();};});
  paintOriginal();
  return panel;
}
function renderScenarioV52(candidate,initialState={}){
  const root=el('<div></div>'),scenarios=candidate.conditional_small_multiples?.scenarios||{},touch=candidate.first_touch_distribution||{},attr=candidate.evidence_attribution||{},ablations=candidate.ablations||{},dotcom=candidate.dotcom_scenario_weighting||{},governance=candidate.governance||{},hard=candidate.model?.hard_event_mapping||{},clusters=candidate.model?.cluster_disclosure||{},layerGate=candidate.model?.database_layer_gate||{},promotionGates=governance.gates||{},weightSpaces=candidate.weight_spaces||{},distinctness=candidate.distinctness||{};
  const pct=value=>`${Math.round(Number(value)*100)}%`,pp=value=>`${Number(value)>=0?'+':''}${(Number(value)*100).toFixed(1)}%p`,weightPct=value=>`${Math.round(Number(value||0)*100)}%`;
  const full=ablations.full_evidence?.probabilities||{},terminalAttr=attr.terminal_above_anchor_2026||{},anchor=Number(candidate.anchor?.close??candidate.anchor??candidate.distribution?.bands?.p50?.[0]);
  root.appendChild(el(`<div class="page-heading"><div><p class="eyebrow" id="v52-page-eyebrow">미래 탐색</p><h1 id="v52-page-title">세 가지 시장 경로</h1><p class="page-lede" id="v52-page-lede">상승·균형·스트레스에 맞는 서로 다른 과거 데이터로 만든 경로를 한 그래프에서 비교합니다.</p></div></div>`));
  const outlook=el(`<div id="lab-future" role="tabpanel" aria-labelledby="lab-tab-future">
    <section class="scenario-v52-overview" aria-label="전망 기준 요약"><div><span>기준일</span><strong>${esc(candidate.as_of.slice(0,10))}</strong></div><div><span>현재 지수</span><strong>${num(Math.round(anchor))}</strong></div><div><span>검토 경로</span><strong>${num(candidate.model.path_count)}개</strong></div><div><span>사용 DB</span><strong>서로 다른 3개 군집</strong></div></section>
    <div class="cross-view-switch future-graph-switch" role="group" aria-label="전망 그래프 보기"><button type="button" data-future-graph="unified" aria-pressed="true">세 가지 시장 경로</button><button type="button" data-future-graph="original" aria-pressed="false">단일 시나리오 주간 흐름</button></div>
    <div data-future-graph-panel="unified">
    <section class="scenario-v52-main" data-chart-role="unified-scenarios"><div class="panel-head"><div><p class="eyebrow">SAME SCALE · LOG VIEW</p><h2 id="scenario-v52-chart-title">3개월 · 세 시나리오 한눈에</h2></div><span class="count-chip">로그 스케일</span></div>
      <div class="scenario-v52-range" role="group" aria-label="전망 기간">${Object.entries(V52_RANGE_META).map(([key,row])=>`<button type="button" data-v52-range="${key}" aria-pressed="${key==='quarter'}">${row[0]}</button>`).join('')}</div>
      <div class="scenario-v52-legend">${['S1','S2','S3'].map(key=>`<span><i style="background:${V52_SCENARIO_META[key].color}"></i><b>${key} ${V52_SCENARIO_META[key].title}</b><small>${esc(V52_SCENARIO_META[key].copy)}</small><em>독립 원천 ${num(clusters[key]?.unique_sampled_source_origins||0)}개 · 모의 ${num(clusters[key]?.simulation_path_count||scenarios[key]?.path_count||0)}경로</em></span>`).join('')}<span class="is-path-key"><i></i><b>선 읽는 법</b><small>굵은 선=실제로 나온 경로 하나 · 점선=수천 번 돌린 한가운데 · 회색 영역=전체 중심 구간</small><em>과거 1/4 · 전망 3/4 시간축</em></span></div>
      <div class="scenario-v52-chart" id="scenario-v52-unified-chart">${scenarioV52UnifiedChart(candidate,'quarter')}</div>
      <div class="scenario-v52-readout" id="scenario-v52-readout">${scenarioV52RangeReadout(candidate,'quarter')}</div>
      ${chartGuide([
        [GUIDE_SOLID(V52_SCENARIO_META.S1.color),'굵은 선','그 시나리오에서 실제로 나온 경로 하나'],
        [GUIDE_DASH(V52_SCENARIO_META.S1.color),'같은 색 점선','수천 번 돌린 결과의 한가운데'],
        [GUIDE_BAND('rgba(136,147,164,.28)'),'회색 영역','전체 경로의 중심 구간'],
        ['background:#82786a;height:14px;width:2px','세로 점선','여기서부터 전망 (왼쪽은 실제 기록)']
      ],'굵은 선은 평균이 아니라 가능한 경로 하나입니다. 특정 날짜의 가격을 맞히는 그래프가 아닙니다.')}
    </section>
    <section class="scenario-v52-insights scenario-v52-core-insights" aria-labelledby="scenario-v52-insights-title"><div class="scenario-v52-section-title"><p class="eyebrow">경로별 핵심</p><h2 id="scenario-v52-insights-title">어떤 데이터가 어떤 방향을 만드는가</h2></div><div>
      <article style="--scenario-accent:${V52_SCENARIO_META.S1.color}"><span>S1 · 확장</span><strong>닷컴 + 완화 + AI 성장</strong><p>닷컴 성장 국면과 금리 부담 완화, AI 확장 구간을 묶습니다. 닷컴 강도는 S1에만 ${Number(dotcom.scenario_strength?.S1||0).toFixed(2)}로 적용합니다.</p></article>
      <article style="--scenario-accent:${V52_SCENARIO_META.S2.color}"><span>S2 · 균형</span><strong>연착륙 + 중립 금융여건</strong><p>비위기 연착륙과 중간 변동성 구간을 사용합니다. 급등·급락보다 평균 회귀와 안정 구간을 더 많이 반영합니다.</p></article>
      <article style="--scenario-accent:${V52_SCENARIO_META.S3.color}"><span>S3 · 스트레스</span><strong>긴축 + 신용 위험 + 성장 둔화</strong><p>긴축과 금융 스트레스 구간만 사용합니다. 반등 뒤 재하락과 스트레스 지속 사례를 별도 DB에서 가져옵니다.</p></article>
      <article class="is-current-reading"><span>현재 읽기</span><strong>고용 ${pp(terminalAttr.labor_growth_risk_effect)} · 금리 ${pp(terminalAttr.policy_relief_effect)}</strong><p>고용 둔화의 성장 위험과 금리 부담 완화를 분리해 반영합니다. 세 경로 비중은 보정된 발생확률이 아니라 연구용 코호트 비중입니다.</p></article>
    </div></section>
    <section class="scenario-v52-timing"><div class="scenario-v52-section-title"><p class="eyebrow">세부 통계</p><h2>−10%선을 처음 만나는 시기</h2><p>정확한 날짜 예측이 아니라, 조정이 발생한 경로들의 시점 분포입니다.</p></div><div>${(touch.density||[]).map((value,index)=>`<i title="${esc(touch.dates[index])}" style="height:${Math.max(1,Number(value)/Math.max(...(touch.density||[]),1e-12)*100)}%"></i>`).join('')}</div><p>중앙 시점 ${esc(touch.conditional_on_touch_quantiles?.p50||'–')} · 빠른 25% ${esc(touch.conditional_on_touch_quantiles?.p25||'–')} · 늦은 25% ${esc(touch.conditional_on_touch_quantiles?.p75||'–')} · 특정 날짜 확정 아님</p></section>
    <details class="scenario-v52-method"></details>
    </div>
    <div data-future-graph-panel="original" hidden></div>
  </div>`);
  const baselineAudit=distinctness.baseline_comparison||{},adapter=layerGate.structural_event_adapter||{};
  const legacyInsights=$('#scenario-v52-insights-title',outlook)?.closest('.scenario-v52-insights');
  if(legacyInsights)legacyInsights.classList.add('scenario-v52-core-insights');
  const methodDetails=$('.scenario-v52-method',outlook);
  if(methodDetails)methodDetails.innerHTML=`<summary>분석 방법과 세부 통계</summary><div>
    <article><strong>연구 상태</strong><p>${esc(candidate.banner)} · 적격 사건 ${num(hard.eligible_historical_event_count||0)}/${num(hard.preferred_minimum||60)} · band calibration ${num(promotionGates.band_calibration?.observations||0)}/${num(promotionGates.band_calibration?.minimum||60)} · champion이 아닌 참고 경로입니다.</p></article>
    <article><strong>결과 비율</strong><p>2026 연말 기준점 상회 ${pct(full.terminal_above_anchor_2026)} · 2027 연말 상회 ${pct(full.terminal_above_anchor_2027)} · 2026 최고치 ${pct(full.new_ath_by_2026)} · 10월 말까지 −10%선 접촉 ${pct(full.first_touch_minus_10_by_october_end)}. 모두 보정되지 않은 모의 경로 비율입니다.</p></article>
    <article><strong>조정 시점 범위</strong><p>−10%선을 만난 경로의 중앙 시점 ${esc(touch.conditional_on_touch_quantiles?.p50||'–')} · 빠른 25% ${esc(touch.conditional_on_touch_quantiles?.p25||'–')} · 늦은 25% ${esc(touch.conditional_on_touch_quantiles?.p75||'–')}. 정확한 날짜 예측이 아닙니다.</p></article>
    <article><strong>증거 효과 분리</strong><p>고용 성장위험 ${pp(terminalAttr.labor_growth_risk_effect)} · 금리 부담완화 ${pp(terminalAttr.policy_relief_effect)}. 가산 잔차는 항등 분해상 정의상 0이며 독립 성과 검정이 아닙니다.</p></article>
    <article><strong>닷컴 가중치 계약</strong><p>S1 닷컴 강도 ${Number(dotcom.scenario_strength?.S1||0).toFixed(2)} · 의존도 cap ${Number(dotcom.dependency_cap||0).toFixed(2)}. 0.40/0.60은 감도 비교, 0.80은 cap 초과로 차단합니다.</p></article>
    <article><strong>A · B · C 분리</strong><p>A ${Number(weightSpaces.A_evidence_strength?.value||0).toFixed(2)}는 증거 강도, B ${Number(weightSpaces.B_generator_dotcom_block_share?.value||0).toFixed(2)}는 S1 생성기의 닷컴 블록 비중, C ${weightPct(weightSpaces.C_mixture_probability?.value?.S1)}는 계산된 연구 코호트 질량입니다. C는 직접 입력하지 않습니다.</p></article>
    <article><strong>같은 DB를 색만 바꾼 그래프가 아닙니다</strong><p>S1·S2 경로 상관 ${Number(baselineAudit.baseline||0).toFixed(3)} → ${Number(baselineAudit.redesigned_shadow||0).toFixed(3)} · 발표 근거는 ${adapter.structural_update_applied?'구조 선택에 반영':'새 수치 없음'}했습니다.</p></article>
    <article><strong>공유되는 것은 두 가지뿐</strong><p>현재 지수 기준점과 거래일 달력만 공유합니다. 특징 변수, 과거 에피소드, 잔차 풀, 국면 길이와 전환 규칙은 S1/S2/S3별로 분리했습니다.</p></article>
    <article><strong>에피소드가 겹치지 않는가</strong><p>교차 시나리오 날짜 겹침 ${num(layerGate.episode_interval_overlap_count||0)}건 · 독립 잔차 풀 ${num(layerGate.unique_residual_pool_count||0)}개 · 특징 스키마 분리 ${String(layerGate.feature_schemas_distinct===true)}.</p></article>
    <article><strong>고정 꺾임을 썼는가</strong><p>fixed_phase_template_active=${String(layerGate.fixed_phase_template_active===true)}. 관측된 연속 국면의 길이 분포와 전환 빈도로 샘플링하며, 끝값이나 특정 날짜를 강제하지 않습니다.</p></article>
    <article><strong>승격을 막는 항목</strong><p>직접 사건 ${num(promotionGates.direct_event_observations?.observations||0)}/${num(promotionGates.direct_event_observations?.minimum||60)} · 원천 표본 ${String(promotionGates.scenario_native_origin_minimums?.pass===true)} · 커널 ${String(promotionGates.empirical_kernel_calibration?.pass===true)} · band calibration ${num(promotionGates.band_calibration?.observations||0)}/${num(promotionGates.band_calibration?.minimum||60)} · 승인 run_id ${esc(promotionGates.human_approval?.approval_run_id||'없음')}.</p></article>
    <article><strong>왜 굵은 선을 실제 모의 경로로 바꿨나</strong><p>p50은 수천 경로의 날짜별 중앙값이라 흔들림이 상쇄돼 거의 직선으로 보입니다. 실제 시장이 그렇게 움직이지 않으므로 굵은 선은 각 시나리오 묶음의 중앙 멤버(medoid)로 그리고, p50은 같은 색 점선으로 남겨 중심 경향을 함께 봅니다. 어느 쪽에도 가짜 흔들림을 넣지 않았습니다.</p></article>
    <article><strong>재현 식별값</strong><p>${esc(candidate.model_content_sha256)}</p></article>
  </div>`;
  $('.scenario-v52-timing',outlook)?.remove();
  const historyPanel=analogPanel(),crossAsset=crossAssetPanel(),liquidity=liquidityPanel();
  if(historyPanel){historyPanel.id='lab-history';historyPanel.setAttribute('role','tabpanel');historyPanel.setAttribute('aria-labelledby','lab-tab-history');historyPanel.hidden=true;}
  if(crossAsset){crossAsset.id='lab-cross-asset';crossAsset.setAttribute('role','tabpanel');crossAsset.setAttribute('aria-labelledby','lab-tab-cross-asset');crossAsset.hidden=true;}
  if(liquidity){liquidity.id='lab-liquidity';liquidity.setAttribute('role','tabpanel');liquidity.setAttribute('aria-labelledby','lab-tab-liquidity');liquidity.hidden=true;}
  const labTabs=el(`<nav class="lab-tabs scenario-v52-tabs" role="tablist" aria-label="미래 탐색 화면"><button type="button" id="lab-tab-future" role="tab" data-lab-tab="future" aria-selected="true" aria-controls="lab-future"><span>01</span> 전망 그래프<small>3개월·1개월·2026·2027</small></button><button type="button" id="lab-tab-history" role="tab" data-lab-tab="history" aria-selected="false" aria-controls="lab-history" ${historyPanel?'':'disabled'}><span>02</span> 과거 사이클<small>참고 비교</small></button><button type="button" id="lab-tab-cross-asset" role="tab" data-lab-tab="cross-asset" aria-selected="false" aria-controls="lab-cross-asset" ${crossAsset?'':'disabled'}><span>03</span> 교차자산 비교<small>NASDAQ·Bitcoin·리츠·주택주</small></button><button type="button" id="lab-tab-liquidity" role="tab" data-lab-tab="liquidity" aria-selected="false" aria-controls="lab-liquidity" ${liquidity?'':'disabled'}><span>04</span> 유동성<small>시장 자금 흐름</small></button></nav>`);
  root.appendChild(labTabs);root.appendChild(outlook);if(historyPanel)root.appendChild(historyPanel);if(crossAsset)root.appendChild(crossAsset);if(liquidity)root.appendChild(liquidity);mount(root);
  let rangeKey='quarter';const chartHost=$('#scenario-v52-unified-chart',outlook),readout=$('#scenario-v52-readout',outlook),chartTitle=$('#scenario-v52-chart-title',outlook);
  const paintRange=key=>{rangeKey=V52_RANGE_META[key]?key:'quarter';chartHost.innerHTML=scenarioV52UnifiedChart(candidate,rangeKey);readout.innerHTML=scenarioV52RangeReadout(candidate,rangeKey);chartTitle.textContent=`${V52_RANGE_META[rangeKey][0]} · 세 시나리오 한눈에`;outlook.querySelectorAll('[data-v52-range]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.v52Range===rangeKey)));};
  outlook.querySelectorAll('[data-v52-range]').forEach(button=>button.onclick=()=>paintRange(button.dataset.v52Range));
  const graphPanels={unified:$('[data-future-graph-panel="unified"]',outlook),original:$('[data-future-graph-panel="original"]',outlook)};
  const originalPanel=originalFlowPanel();
  if(originalPanel&&graphPanels.original)graphPanels.original.appendChild(originalPanel);
  if(!originalPanel)$('.future-graph-switch',outlook)?.remove();
  let graphKey='unified';
  const futureGraphHash=()=>graphKey==='original'?'#future/original':'#future';
  const paintFutureGraph=(key,sync)=>{
    graphKey=originalPanel&&key==='original'?'original':'unified';
    Object.entries(graphPanels).forEach(([name,panel])=>{if(panel)panel.hidden=name!==graphKey;});
    outlook.querySelectorAll('[data-future-graph]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.futureGraph===graphKey)));
    if(sync)syncMidHash(futureGraphHash());
  };
  outlook.querySelectorAll('[data-future-graph]').forEach(button=>{button.onclick=()=>paintFutureGraph(button.dataset.futureGraph,true);});
  const copies={future:['미래 탐색','세 가지 시장 경로','상승·균형·스트레스에 맞는 서로 다른 과거 데이터로 만든 경로를 한 그래프에서 비교합니다.'],history:['과거 비교','과거 혁신 사이클은 어떻게 움직였나','과거 사례를 같은 시작점에 맞춰 비교합니다. 현재 전망값이나 사건 확률은 아닙니다.'],'cross-asset':['교차자산 비교','닷컴 조정 뒤 자산별 회복은 어떻게 달랐을까','NASDAQ·Realty Income·D.R. Horton 실측과 Bitcoin 민감도 경로를 시작값 100으로 맞춰 비교합니다.'],liquidity:['시장 자금 흐름','유동성이 늘고 줄어든 구간','Fed 순유동성과 NASDAQ·Bitcoin 수익률을 같은 주간축에서 참고용으로 비교합니다.']};
  const panels={future:outlook,history:historyPanel,'cross-asset':crossAsset,liquidity};
  const activateLab=key=>{const active=panels[key]?key:'future';Object.entries(panels).forEach(([name,panel])=>{if(panel)panel.hidden=name!==active;});labTabs.querySelectorAll('[data-lab-tab]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.labTab===active)));const copy=copies[active];$('#v52-page-eyebrow',root).textContent=copy[0];$('#v52-page-title',root).textContent=copy[1];$('#v52-page-lede',root).textContent=copy[2];};
  labTabs.querySelectorAll('[data-lab-tab]:not(:disabled)').forEach(button=>button.onclick=()=>{activateLab(button.dataset.labTab);syncMidHash(button.dataset.labTab==='future'?futureGraphHash():`#future/${button.dataset.labTab}`);});
  if(historyPanel){const analogHost=$('#ovchart',historyPanel);drawOverlay(analogHost,historyPanel._overlay,historyPanel._eras,historyPanel._eraStarts,'ALL');historyPanel.querySelectorAll('[data-analog-focus]').forEach(button=>button.onclick=()=>{analogHost.innerHTML='';drawOverlay(analogHost,historyPanel._overlay,historyPanel._eras,historyPanel._eraStarts,button.dataset.analogFocus);historyPanel.querySelectorAll('[data-analog-focus]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));});}
  if(crossAsset)bindCrossAsset(crossAsset,initialState.scenario);
  if(liquidity)bindLiquidity(liquidity);
  activateLab(initialState.lab||'future');paintRange(rangeKey);paintFutureGraph(initialState.futureGraph==='original'?'original':'unified',false);
}
function renderFlow(initialLookup){
  const initialState=initialLookup&&typeof initialLookup==='object'?initialLookup:{lookup:initialLookup};
  initialLookup=initialState.lookup||null;
  const candidate52=DATA.scenario_v5_2||null;
  const candidate52Eligible=candidate52&&['ok','degraded'].includes(candidate52.status)&&candidate52.runtime_gate?.display_eligible!==false;
  // Customer default: V5.2's three independently clustered scenario paths.
  // The legacy champion remains available only through its direct audit route;
  // a candidate failure must never silently replace the requested chart.
  const candidate52Requested=initialState.modelView!=='champion'&&!initialState.lookup&&!initialState.lookupOverlay;
  if(candidate52Requested&&candidate52Eligible){
    renderScenarioV52(candidate52,initialState);
    return;
  }
  if(candidate52Requested){
    const reason=(candidate52?.runtime_gate?.reasons||['세 가지 시나리오 데이터가 현재 표시 요건을 충족하지 못했습니다.']).join(' · ');
    renderFuturePathsLoadState(candidate52,reason);
    return;
  }
  const candidateData=DATA.scenario_v5||null,v5=candidateData&&['ok','degraded'].includes(candidateData.status)&&candidateData.runtime_gate?.display_eligible!==false?candidateData:null;
  const officialScenario=DATA.scenario,shadowScenario=DATA.scenario_v4_shadow;
  let sc=officialScenario,shadowActive=false;
  const structural=sc.structural_forecast?.status==='ok'?sc.structural_forecast:null;
  const methodCopy=sc.scenario_v5_candidate
    ?'굵은 선은 시나리오 조건부 weighted p50입니다. 가는 점선은 실제 모의 멤버 한 개이며 정확한 날짜 예측이 아닙니다.'
    :String(sc.method||'').startsWith('gbm-daily-252d')
    ?'굵은 선의 굴곡은 혁신사이클 DB, 진폭은 다중시대 조정 DB, 연도 종점과 경로 비중은 기존 조건부 분포에서 가져옵니다. fat tail과 돌발 이벤트를 직접 모형화하지 않습니다.'
    :'경로 확률은 감사된 수동 시나리오의 보관값이며 현재 시장 판단에는 별도 최신성 확인이 필요합니다.';
  const root=el('<div></div>');
  root.appendChild(el(`<div class="page-heading"><div>
    <p class="eyebrow" id="flow-page-eyebrow">${FLOW_LAB_COPY.future[0]}</p>
    <h1 id="flow-page-title">${FLOW_LAB_COPY.future[1]}</h1>
    <p class="page-lede" id="flow-page-lede">${FLOW_LAB_COPY.future[2]} 시나리오 기준 ${esc(sc.asof)} · 참고 의견이며 투자 자문이 아닙니다.</p>
  </div><button type="button" class="future-lookup-open" data-future-lookup-open>날짜·기간 조회 <span>↗</span></button></div>`));
  if(DATA.future_paths_error)root.appendChild(el(`<section class="scenario-v5-banner is-stale" role="alert" aria-label="미래 상세 데이터 로드 실패"><div><span>FUTURE PATHS FETCH FAILED</span><strong>기존 시장 전망만 표시 중</strong><small>${esc(DATA.future_paths_error)}</small></div><p>V5.2·교차자산·유동성 상세를 불러오지 못했습니다. 실패를 숨기지 않으며 연구 후보로 조용히 전환하지 않습니다.</p></section>`));
  if(v5&&sc.scenario_v5_candidate){const numerical=(v5.evidence_views||[]).filter(row=>row.used_numerically),references=(v5.evidence_views||[]).filter(row=>!row.used_numerically),shape=v5.conditional_distribution?.same_shape_diagnostics||{};
    root.appendChild(el(`<section class="scenario-v5-banner" aria-label="Scenario V5 current candidate banner"><div><span>EVIDENCE-CONDITIONED MARKET OUTLOOK · V5.1</span><strong>${esc(v5.banner)}</strong><small>${esc(v5.candidate_id)} · ${esc(v5.identity?.prior_engine)} · as_of ${esc(v5.asof)}</small></div><div class="scenario-v5-stats"><span><b>${numerical.length}</b> physical views used</span><span><b>${references.length}</b> reference/blocked</span><span><b>${num(v5.posterior_diagnostics?.effective_sample_size)}</b> posterior ESS</span><span><b>${shape.gate_pass?'PASS':'HIDDEN'}</b> member shape gate</span></div><p>내생·started-window 전망은 수치 입력에서 차단했습니다. 옵션은 위험중립 참고값이고, 이벤트 가격 점프는 승인 매핑이 없어 0입니다. ${esc(v5.display_contract?.continuation_disclosure||'')}</p></section>`));}
  const scenarioChange=scenarioChangePanel(true);if(scenarioChange)root.appendChild(scenarioChange);
  const legend=`<div class="band-inline">
    ${['S1','S2','S3'].map(k=>`<span><b style="background:${CHART_COL[k]}"></b>${k} ${sc.scenario_v5_candidate?'conditional weighted p50':'DB 조건부 구조 경로'} · ${sc.paths[k].prob}%</span>`).join('')}
    ${sc.scenario_v5_candidate?'<span><b class="baseline-swatch"></b>가는 점선 = 실제로 나온 경로 하나 (날짜별 값을 맞히는 선 아님)</span>':''}
    ${structural?'<span><b class="baseline-swatch"></b>굴곡 적용 전 GBM 중심 경로</span>':''}
    ${sc.fan?.quantiles?'<span><b class="fan-swatch"></b>조건부 구간 p10–p90 · 중앙값 p50</span>':''}
    ${sc.analog?.values?.length?'<span><b style="background:#706f68"></b>혁신사이클 대표 참조선 · 확률 아님</span>':''}</div>`;
  const focusControls=`<div class="flow-focus" role="group" aria-label="시나리오 경로 강조"><span>SPOTLIGHT</span>
    <button type="button" data-flow-focus="ALL" aria-pressed="true"><i></i>전체</button>
    ${['S1','S2','S3'].map(k=>`<button type="button" data-flow-focus="${k}" style="--focus-color:${CHART_COL[k]}" aria-pressed="false"><i></i>${esc(sc.paths[k].label)}</button>`).join('')}
    ${sc.analog?.values?.length?'<button type="button" data-flow-focus="ANALOG" style="--focus-color:#706f68" aria-pressed="false"><i></i>혁신사이클 참조</button>':''}</div>`;
  const shapeControls=structural?`<div class="flow-shape-controls" role="group" aria-label="구조 굴곡 비교"><span>PATH LAYERS</span><button type="button" data-flow-baseline aria-pressed="true"><i></i>굴곡 전 GBM 같이 보기</button><small>기본 표시 · 회색 고스트 선은 같은 종점의 비교 기준</small></div>`:'';
  const shadowControls=shadowScenario?.status==='shadow_only'?`<div class="flow-shadow-controls" role="group" aria-label="Scenario Graph V4 legacy diagnostic toggle"><span>SCENARIO GRAPH V4</span><button type="button" data-flow-v4-shadow aria-pressed="false"><i></i>Legacy actual-member diagnostic</button><small>default OFF · not RCFHS · not official probability or champion</small></div>`:'';
  const realism=sc.path_realism;
  const structureEvidence=structural?.evidence||{},episodeEvidence=structureEvidence.correction_episodes||{},eventEvidence=structureEvidence.physical_event||{},proximity=eventEvidence.proximity_context||{},calibration=structural?.calibration||{},selection=structureEvidence.innovation_cycle?.selection_sensitivity||{},gbm=structural?.reproducibility?.gbm_parameters||{},trackerEvidence=DATA.scenario_tracker||{},liquidityEvidence=DATA.liquidity||{},aiRegimeEvidence=DATA.ai_regime||{};
  const realismCards=structural?`<section class="path-realism structural-evidence" aria-labelledby="path-realism-title">
    <div><p class="eyebrow">DB-CONDITIONED PATH · MONTHLY RISK WINDOW</p><h3 id="path-realism-title">상승·회복 사이의 조정을 역사 DB로 복원했습니다</h3><p>굵은 선은 무작위 모의 표본이 아닙니다. 선택 혁신시대의 월별 굴곡을 연도별로 추출하고, 커밋된 조정 깊이 중앙값에 맞춘 구조 경로입니다. 회색 고스트 선은 굴곡 적용 전 GBM 중심 경로, 회색 점선은 혁신사이클 대표 참조선입니다.</p></div>
    <div class="structural-shape-warning" role="note"><strong>굴곡=역사 중앙 형태 가정</strong><span>발생 여부의 확률 진술이 아닙니다. 화면의 조정 모양을 S1/S2/S3에서 100% 발생하는 사건으로 읽지 마세요.</span></div>
    <div class="path-realism-grid structural-year-grid">${structural.years.map(row=>`<article><span>${row.year} · ${esc(row.start_date)}~${esc(row.end_date)}</span><strong>${esc(row.analog_risk_window.center_month)} 중심 월 단위 위험창</strong><small>${esc(row.analog_risk_window.start)}~${esc(row.analog_risk_window.end)} · S1 ${num(row.path_diagnostics.S1.max_drawdown_pct)}% · S2 ${num(row.path_diagnostics.S2.max_drawdown_pct)}% · S3 ${num(row.path_diagnostics.S3.max_drawdown_pct)}%</small></article>`).join('')}</div>
    <div class="calibration-invariance-note" role="note"><strong>시대 선택은 위치, base rate는 깊이를 정합니다</strong><span>시대를 교체하면 위험창 중심월은 움직이지만, 화면 낙폭은 모든 조합을 조정 base rate −${num(calibration.target_depth_pct)}%에 다시 맞춥니다. 아래 native 범위는 보정 전 민감도입니다.</span></div>
    <div class="structure-source-grid"><span><b>AI 조정 DB</b>${num(episodeEvidence.ai?.episodes)}회 · 중앙 ${num(episodeEvidence.ai?.median_depth_pct)}%</span><span><b>닷컴 조정 DB</b>${num(episodeEvidence.dotcom?.episodes)}회 · 중앙 ${num(episodeEvidence.dotcom?.median_depth_pct)}%</span><span><b>선택 3시대 원형 → 목표</b>${num(calibration.native_ensemble_origin_year_max_drawdown_pct)}% → −${num(calibration.target_depth_pct)}%</span><span><b>기하 detrend 잔차</b>${num(calibration.native_residual_origin_year_drawdown_pct)}% · 지수 ${num(calibration.residual_exponent_amplification_ratio)}×</span><span><b>화면 S1 낙폭</b>원형 ${num(calibration.native_shape_origin_year_s1_max_drawdown_pct)}% · 보정 ${num(calibration.calibrated_origin_year_s1_max_drawdown_pct)}%</span><span><b>공용 strength</b>S1 ${num(sc.paths.S1.prob)}% 의존 근사 · 시나리오별 대안 병기</span><span><b>시대 교체 native</b>${num(selection.alternative_count)}안 · ${num(selection.origin_year_native_s1_mdd_range_pct?.[0])}~${num(selection.origin_year_native_s1_mdd_range_pct?.[1])}%</span><span><b>시대 교체 calibrated</b>${num(selection.origin_year_calibrated_s1_mdd_range_pct?.[0])}~${num(selection.origin_year_calibrated_s1_mdd_range_pct?.[1])}% · 깊이 고정</span><span><b>선택 위상</b>M+${num(structureEvidence.innovation_cycle?.current_phase)} · ${esc((structureEvidence.innovation_cycle?.selected_eras||[]).join(' · '))}</span><span><b>GBM 추세 가정</b>연 μ ${signedDelta(Number(gbm.mu_annualized_252||0)*100,1,'%')} · 연 σ ${num(Number(gbm.sigma_annualized_252||0)*100)}%</span><span><b>AI 레짐</b>${esc(aiRegimeEvidence.status||'미산출')} · coverage ${num(Number(aiRegimeEvidence.coverage||0)*100)}% · 수치 제외</span></div>
    ${selection.alternatives?.length?`<details class="calibration-sensitivity"><summary>시대 교체별 native·calibrated 낙폭 비교</summary><div class="table-shell"><table><thead><tr><th>교체</th><th>Native · 보정 전</th><th>Calibrated · 화면</th><th>위험창 중심</th></tr></thead><tbody>${selection.alternatives.map(row=>`<tr><td>${esc(row.removed)} → ${esc(row.added)}</td><td>${num(row.origin_year_native_s1_mdd_pct)}%</td><td>${num(row.origin_year_calibrated_s1_mdd_pct)}%</td><td>${esc(row.risk_window_center_month)} · ${Number(row.center_shift_months)>0?'+':''}${num(row.center_shift_months)}개월</td></tr>`).join('')}</tbody></table></div><p>Native는 시대 선택의 원형 차이, calibrated는 같은 조정 base rate로 재수렴한 실제 화면 깊이입니다. 시대 선택 민감도를 사건확률이나 방향 확률로 사용하지 않습니다.</p></details>`:''}
    <div class="physical-event-separation"><span>PHYSICAL EVENT · 별도 확률 공간</span><strong>8–10월 −10% 종가 발생 ${num(eventEvidence.probability_pct)}%</strong><small>80% 구간 ${num(eventEvidence.ci80_pct?.[0])}–${num(eventEvidence.ci80_pct?.[1])}% · 임계까지 ${num(proximity.threshold_distance_pct)}% · 잔여 ${num(proximity.remaining_trading_sessions)}거래일</small>${proximity.status==='ok'?`<em>무드리프트 기계적 기준 ≈${num(proximity.driftless_mechanical_touch_pct)}% · 해석 보조일 뿐 등록 확률과 결합하지 않음</em>`:''}</div>
    <p class="model-scope"><strong>${esc(sc.paths.S1.prob)}%는 ‘2026년 말까지 ATH 돌파’ 조건부 경로 비중이며, 종점은 trailing 252거래일 μ의 추세 지속 가정을 상속합니다.</strong> 과거 DB의 해상도는 월 단위라 특정 9월 하락일이나 저점 거래일을 지정하지 않습니다. 2027년 조정창도 AI 버블 붕괴일이 아니라 선택 시대 중앙 위상의 되돌림 구간입니다.</p><small>as_of ${esc(sc.asof)} · 구조 경로 v${esc(structural.version)} · seed ${num(structural.reproducibility?.seed)} · ${num(structural.reproducibility?.n_paths)}경로 · 단일 가격이나 투자자문이 아님</small>
  </section>`:(realism?.S1?`<section class="path-realism" aria-labelledby="path-realism-title"><div><p class="eyebrow">PATH ILLUSTRATION · DATE IS NOT A FORECAST</p><h3 id="path-realism-title">상승 경로에도 조정은 남아 있습니다</h3><p>현재 스냅샷은 구조 경로가 없어 기존 조건부 중심선만 표시합니다.</p></div></section>`:'');
  const lookupTable=sc.quantile_table,lookupReady=lookupTable?.status==='ok'&&lookupTable.trading_days?.length;
  const quick=lookupReady?ForecastLookup.quickDates(sc.asof):{};
  if(lookupReady)quick.sixMonth=lookupTable.trading_days[Math.min(125,lookupTable.trading_days.length-1)];
  const sixMonthEnd=lookupReady?quick.sixMonth:sc.week_dates?.[Math.min(25,(sc.week_dates?.length||1)-1)];
  const fullHorizonEnd=lookupReady?lookupTable.trading_days.at(-1):sc.week_dates?.at(-1);
  const lookupWidget=lookupReady?`<section class="forecast-lookup" aria-labelledby="lookup-title">
    <div class="lookup-heading"><div><p class="eyebrow">CURRENT-ORIGIN LOOKUP</p><h3 id="lookup-title">현재 기준 미래 분포 조회</h3><p>${esc(sc.asof)}을 원점으로 만든 동일한 분포에서 선택 날짜의 단면을 조회합니다.</p></div><span>NO API · NO STORAGE</span></div>
    <div class="lookup-scope-note"><strong>무엇을 보여주나요?</strong><span>미래 날짜에 새로 만든 전망이 아니라, 현재 스냅샷의 불확실성이 기간에 따라 얼마나 벌어지는지를 보여줍니다. 기본 차트는 2026년이며 선택 날짜의 연도 차트로 전환됩니다.</span></div>
    <div class="lookup-controls"><label for="lookup-date">날짜 선택<input id="lookup-date" type="date" min="${esc(lookupTable.trading_days[0])}" max="${esc(lookupTable.trading_days.at(-1))}" value="${esc(initialLookup||quick.month)}"></label><button type="button" class="lookup-submit">분포 조회</button></div>
    <div class="lookup-mode-switch" role="group" aria-label="날짜 조회 차트 기준"><button type="button" data-lookup-mode="rebase" aria-pressed="true">선택일을 100으로 재기준</button><button type="button" data-lookup-mode="current" aria-pressed="false">현재 원점 유지</button></div>
    <div class="lookup-chips" aria-label="빠른 날짜">${[['week','1주 뒤'],['month','1개월'],['quarter','3개월'],['sixMonth','6개월'],['yearEnd','연말']].map(([key,label])=>`<button type="button" data-lookup-quick="${esc(quick[key])}">${label}</button>`).join('')}</div>
    <div class="lookup-natural"><label for="lookup-natural">한 줄 날짜 입력<input id="lookup-natural" type="text" maxlength="40" placeholder="8/30 · 8월 30일 · 3개월 뒤 · 연말" autocomplete="off"></label><button type="button" class="lookup-natural-submit">날짜 해석</button><small>정규식 규칙 파서 · LLM 호출 없음</small></div>
    <div class="lookup-result" aria-live="polite"><div class="lookup-empty"><strong>날짜를 선택하면 구간부터 표시합니다.</strong><span>없는 날짜를 보간하지 않고 실제 산출 거래일로 매핑합니다.</span></div></div>
    <div class="lookup-rebase-note" role="note" hidden><strong>재기준 그래프의 의미</strong><span>선택일 이후의 기존 분위수와 S1/S2/S3 DB 조건부 구조 경로를 각각 100으로 다시 표시합니다. 선택일에 새로 계산한 전망은 아니며, D일의 실제 가격·변동성은 D일 스냅샷에서 반영됩니다.</span><small></small></div>
  </section>`:'';
  const lookupOverlayMarkup=lookupReady?`<div class="future-lookup-layer" data-future-lookup-layer hidden aria-hidden="true"><button type="button" class="future-lookup-scrim" data-future-lookup-close aria-label="날짜·기간 조회 닫기"></button><section class="future-lookup-sheet" role="dialog" aria-modal="true" aria-labelledby="future-lookup-sheet-title"><header><div><span>FUTURE EXPLORER</span><h2 id="future-lookup-sheet-title">날짜·기간 조회</h2></div><button type="button" data-future-lookup-close>닫기</button></header>${lookupWidget}</section></div>`:'';
  const eventCalendar=Array.isArray(DATA.calendar_events)&&DATA.calendar_events.length?DATA.calendar_events:(Array.isArray(sc.event_calendar)?sc.event_calendar:[]);
  sc.calendar_events=eventCalendar;
  const eventYears=[...new Set(eventCalendar.map(event=>event.date.slice(0,4)))];
  const eventCounts={confirmed:eventCalendar.filter(event=>event.status!=='estimated').length,estimated:eventCalendar.filter(event=>event.status==='estimated').length};
  const evRibbon=eventCalendar.length?`<section class="market-event-calendar" aria-labelledby="market-event-title">
    <div class="market-event-head"><div><p class="eyebrow">MARKET CALENDAR · APPEND ONLY</p><h3 id="market-event-title">2027년까지 주요 일정</h3><p>확정·추정 분리 · 전망성 해석 제외</p></div><button type="button" class="event-summary-chip" data-event-summary-toggle data-badge-type="event-summary" aria-expanded="false"><strong>확정 ${eventCounts.confirmed} · 추정 ${eventCounts.estimated}</strong><span>일정 펼치기</span></button></div>
    <div class="market-event-details" data-event-details hidden>${eventYears.map(year=>`<div class="market-event-year"><div class="market-event-year-label"><strong>${esc(year)}</strong><span>${year==='2027'?'공식 일정 + 추정 분리':'기관·기업 공개 일정'}</span></div><div class="event-track">${eventCalendar.filter(event=>event.date.startsWith(year)).map(event=>{const meta=EVENT_KIND_META[event.kind]||EVENT_KIND_META.other;return `<article class="event-card event-${esc(event.kind)} ${event.status==='estimated'?'is-estimated':''}" tabindex="0"><div><time datetime="${esc(event.date)}">${esc(event.date.slice(5).replace('-','/'))}</time><span class="event-shape" aria-hidden="true">${meta[1]}</span></div><strong>${esc(event.title||event.label)}</strong><small>${event.status==='estimated'?'추정 · ':'확정 · '}${esc(event.time_et?`${event.time_et} ET · `:'')}${esc(event.ticker||meta[0])}</small><a href="${esc(event.source_url)}" target="_blank" rel="noopener">공식 근거 ↗</a></article>`;}).join('')}</div></div>`).join('')}
      <p class="market-event-note">확정은 기관·기업이 날짜를 공개한 일정, 추정은 과거 발표 월 패턴 또는 연준의 공식 잠정 일정입니다. 마커는 정보 제공용이며 이벤트와 분포 확률을 연결하지 않습니다.</p></div>
  </section>`:`<div class="event-track">${sc.events.map(([xi,label])=>`<div><time>${esc(sc.weeks[Math.max(0,Math.min(sc.weeks.length-1,Math.round(xi)))]||'')}</time><span>${esc(label)}</span></div>`).join('')}</div>`;
  const p1w=el(`<div class="chart-panel analysis-panel">
    <div class="panel-head"><h2 id="flow-horizon-title">${sc.scenario_v5_candidate?'2026년 Evidence-conditioned conditional p50 paths':'2026년 DB 조건부 구조 경로'}</h2>${legend}</div>
    ${focusControls}
    ${shapeControls}
    ${shadowControls}
    <div class="flow-origin-bar"><div><span>CURRENT ORIGIN</span><strong>${esc(sc.asof)}</strong><small>${sc.scenario_v5_candidate?'조건부 weighted p50, ESS fan, 실제 모의 멤버 진단을 분리해 봅니다.':'분포 원점은 고정하고 구조 경로만 연도별로 나눠 봅니다.'}</small></div><div class="flow-horizon-toggle" role="group" aria-label="미래 분포 표시 연도">${(structural?.years||[{year:Number(sc.asof.slice(0,4)),start_date:sc.asof,end_date:sc.model?.classification_date||sixMonthEnd},{year:Number(sc.asof.slice(0,4))+1,start_date:(sc.week_dates||[]).find(day=>String(day).startsWith(String(Number(sc.asof.slice(0,4))+1)))||'',end_date:fullHorizonEnd}]).map((row,index)=>`<button type="button" data-flow-year="${row.year}" aria-pressed="${index===0?'true':'false'}"><span>${index===0?'현재':'다음'}</span>${row.year}년<small>${esc(row.start_date)}~${esc(row.end_date)}</small><em>${sc.scenario_v5_candidate?'252거래일 사후 경로':(row.year===2027?'현 252거래일 지평 · 8월까지':'DB 조정창 포함')}</em></button>`).join('')}</div></div>
    <div class="chart-wrap"><div id="chart"></div></div>
    ${v5?scenarioV5ConditionalFanMarkup(v5):''}
    ${v5?scenarioV5TimingMarkup(v5):''}
    ${v5?scenarioV5EvidenceMarkup(v5):''}
    ${evRibbon}
    <div class="risk-legend"><span><i class="lo"></i>−10%선 누적 터치확률 저</span><span><i class="mid"></i>중</span><span><i class="hi"></i>고</span></div>
    ${sc.fan?.quantiles?`<div class="scenario-semantics"><span>미래 분포</span><strong>중앙값 p50 · 안쪽 p25–p75 · 바깥 p10–p90</strong><small>${esc(sc.fan.probability_space)} · ${esc(sc.fan.monitoring||'미산출')} monitoring</small></div>`:''}
    <p class="chart-note">${sc.scenario_v5_candidate?'굵은 선은 수천 번 돌린 결과의 한가운데이고, 가는 점선은 실제로 나온 경로 하나입니다. 색 띠는 그 분포의 폭이며 일정 표시가 가격을 움직이지는 않습니다.':'굵은 선은 과거 조정 모양을 입힌 경로이고, 모의 표본을 대표선으로 쓰지 않습니다.'} ${esc(methodCopy)}</p>
    ${realismCards?`<details class="future-method-appendix"><summary>분석 방법 부록</summary>${realismCards}</details>`:''}
  </div>`);
  const overlay=analogPanel();
  const crossAsset=crossAssetPanel();
  const aiRegime=aiRegimePanel();
  const liquidity=liquidityPanel();
  p1w.id='lab-future';p1w.setAttribute('role','tabpanel');p1w.setAttribute('aria-labelledby','lab-tab-future');
  if(overlay){overlay.id='lab-history';overlay.setAttribute('role','tabpanel');overlay.setAttribute('aria-labelledby','lab-tab-history');overlay.hidden=true;}
  if(crossAsset){crossAsset.id='lab-cross-asset';crossAsset.setAttribute('role','tabpanel');crossAsset.setAttribute('aria-labelledby','lab-tab-cross-asset');crossAsset.hidden=true;}
  if(aiRegime){aiRegime.id='lab-ai-regime';aiRegime.setAttribute('role','tabpanel');aiRegime.setAttribute('aria-label','AI 자본사이클 준비 상태');aiRegime.hidden=true;}
  if(liquidity){liquidity.id='lab-liquidity';liquidity.setAttribute('role','tabpanel');liquidity.setAttribute('aria-labelledby','lab-tab-liquidity');liquidity.hidden=true;}
  const labTabs=el(`<div class="lab-tabs" role="tablist" aria-label="시장 지도 분석 공간">
    <button type="button" id="lab-tab-future" role="tab" aria-selected="true" aria-controls="lab-future" data-lab-tab="future"><span>01</span> 미래 분포<small>${plainTerm('scenario_conditional')}</small></button>
    <button type="button" id="lab-tab-history" role="tab" aria-selected="false" aria-controls="lab-history" data-lab-tab="history" ${overlay?'':'disabled'}><span>02</span> 사이클 비교<small>${plainTerm('reference_only')}</small></button>
    <button type="button" id="lab-tab-cross-asset" role="tab" aria-selected="false" aria-controls="lab-cross-asset" data-lab-tab="cross-asset" ${crossAsset?'':'disabled'}><span>03</span> 교차자산 비교<small>${plainTerm('reference_only')}</small></button>
    <button type="button" id="lab-tab-liquidity" role="tab" aria-selected="false" aria-controls="lab-liquidity" data-lab-tab="liquidity" ${liquidity?'':'disabled'}><span>04</span> 유동성<small>${plainTerm('reference_only')}</small></button>
  </div>`);
  root.appendChild(labTabs);root.appendChild(p1w);if(overlay)root.appendChild(overlay);if(crossAsset)root.appendChild(crossAsset);if(aiRegime)root.appendChild(aiRegime);if(liquidity)root.appendChild(liquidity);
  mount(root);
  if(lookupOverlayMarkup)document.body.appendChild(el(lookupOverlayMarkup));
  let flowFocus='ALL',showBaseline=!sc.scenario_v5_candidate,lookupMarker=null,flowYear=Number(structural?.years?.[0]?.year||sc.asof.slice(0,4)),lookupMode=initialState.lookupMode==='current'?'current':'rebase';
  const flowHost=$('#chart',p1w),flowTitle=$('#flow-horizon-title',p1w);
  const lookupLayer=document.querySelector('[data-future-lookup-layer]'),lookupScope=lookupLayer||p1w,lookupOpen=$('[data-future-lookup-open]',root);
  const setLookupOverlay=open=>{if(!lookupLayer)return;lookupLayer.hidden=!open;lookupLayer.setAttribute('aria-hidden',String(!open));document.body.classList.toggle('future-lookup-open',open);if(open&&location.hash==='#future')history.replaceState(null,'','#future/lookup');if(!open&&location.hash==='#future/lookup')history.replaceState(null,'','#future');if(open)requestAnimationFrame(()=>$('#lookup-date',lookupLayer)?.focus());};
  if(lookupOpen)lookupOpen.onclick=()=>setLookupOverlay(true);else root.querySelector('[data-future-lookup-open]')?.setAttribute('hidden','');
  lookupLayer?.querySelectorAll('[data-future-lookup-close]').forEach(button=>button.onclick=()=>setLookupOverlay(false));
  if(lookupLayer)lookupLayer.onkeydown=event=>{if(event.key==='Escape')setLookupOverlay(false);};
  const eventToggle=$('[data-event-summary-toggle]',p1w),eventDetails=$('[data-event-details]',p1w);
  if(eventToggle&&eventDetails)eventToggle.onclick=()=>{const open=eventToggle.getAttribute('aria-expanded')!=='true';eventToggle.setAttribute('aria-expanded',String(open));eventDetails.hidden=!open;$('span',eventToggle).textContent=open?'일정 접기':'일정 펼치기';if(open)requestAnimationFrame(()=>enhanceChartScroll(eventDetails));};
  const syncFlowHorizon=()=>{p1w.querySelectorAll('[data-flow-year]').forEach(button=>{button.setAttribute('aria-pressed',String(Number(button.dataset.flowYear)===flowYear));button.disabled=lookupMode==='rebase'&&Boolean(lookupMarker);});const baselineButton=$('[data-flow-baseline]',p1w);if(baselineButton)baselineButton.disabled=lookupMode==='rebase'&&Boolean(lookupMarker);
    if(flowTitle)flowTitle.textContent=lookupMode==='rebase'&&lookupMarker?`${lookupMarker.slice(0,10)} = 100 재기준 경로`:(sc.scenario_v5_candidate?`${flowYear}년 Evidence-conditioned conditional p50 paths`:`${flowYear}년 DB 조건부 구조 경로${flowYear===2027?' · 8월까지':''}`);};
  const paintFlow=focus=>{flowFocus=focus;flowHost.innerHTML='';if(lookupMode==='rebase'&&lookupMarker)drawRebasedFlow(flowHost,sc,lookupMarker);else drawFlow(flowHost,sc,focus,lookupMarker,flowYear,false,showBaseline);
    p1w.querySelectorAll('[data-flow-focus]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.flowFocus===focus)));};
  p1w.querySelectorAll('[data-flow-focus]').forEach(b=>b.onclick=()=>paintFlow(b.dataset.flowFocus));
  const baselineButton=$('[data-flow-baseline]',p1w);if(baselineButton)baselineButton.onclick=()=>{showBaseline=!showBaseline;baselineButton.setAttribute('aria-pressed',String(showBaseline));baselineButton.lastChild.textContent=showBaseline?'굴곡 전 GBM 같이 보기':'굴곡 전 GBM 숨김';paintFlow(flowFocus);};
  const shadowButton=$('[data-flow-v4-shadow]',p1w);if(shadowButton)shadowButton.onclick=()=>{shadowActive=!shadowActive;sc=shadowActive?shadowScenario:officialScenario;shadowButton.setAttribute('aria-pressed',String(shadowActive));shadowButton.lastChild.textContent=shadowActive?'Legacy actual-member diagnostic active':'Legacy actual-member diagnostic';paintFlow(flowFocus);};
  p1w.querySelectorAll('[data-flow-year]').forEach(button=>button.onclick=()=>{flowYear=Number(button.dataset.flowYear);syncFlowHorizon();paintFlow(flowFocus);});
  syncFlowHorizon();paintFlow(flowFocus);
  const lookupResult=$('.lookup-result',lookupScope),lookupInput=$('#lookup-date',lookupScope),rebaseNote=$('.lookup-rebase-note',lookupScope);
  const syncLookupMode=()=>{lookupScope.querySelectorAll('[data-lookup-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.lookupMode===lookupMode)));if(rebaseNote)rebaseNote.hidden=!(lookupMode==='rebase'&&lookupMarker);syncFlowHorizon();};
  const runLookup=(requested,mode=lookupMode)=>{if(!lookupResult||!lookupInput)return;lookupMode=mode;lookupInput.value=requested||lookupInput.value;
    const mapped=ForecastLookup.mapDate(sc.quantile_table,lookupInput.value,sc.asof);
    lookupResult.innerHTML=mapped.ok?lookupCardMarkup(sc,mapped):lookupErrorMarkup(mapped);
    lookupMarker=mapped.ok?mapped.mapped:null;
    if(mapped.ok)flowYear=Number(mapped.mapped.slice(0,4));
    if(rebaseNote&&mapped.ok){const remaining=sc.quantile_table.trading_days.length-mapped.index-1,coverage=horizonCoverageForDay(sc,mapped.tradingDay);rebaseNote.querySelector('small').textContent=`남은 시뮬 구간 D+${remaining}거래일까지 · ${mapped.mapped} → ${sc.quantile_table.trading_days.at(-1)} · ${coverage.label} — ${coverage.detail} · as_of ${sc.asof}`;}
    syncLookupMode();
    paintFlow(flowFocus);
    if(mapped.ok)history.replaceState(null,'',`#future/lookup/${mapped.requested}/${lookupMode}`);
  };
  const lookupSubmit=$('.lookup-submit',p1w);if(lookupSubmit)lookupSubmit.onclick=()=>runLookup(lookupInput.value);
  lookupScope.querySelectorAll('[data-lookup-quick]').forEach(button=>button.onclick=()=>runLookup(button.dataset.lookupQuick));
  lookupScope.querySelectorAll('[data-lookup-mode]').forEach(button=>button.onclick=()=>{lookupMode=button.dataset.lookupMode;lookupMarker?runLookup(lookupInput.value,lookupMode):(syncLookupMode(),paintFlow(flowFocus));});
  if(lookupInput)lookupInput.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();runLookup(lookupInput.value);}};
  const naturalInput=$('#lookup-natural',lookupScope),naturalSubmit=$('.lookup-natural-submit',lookupScope);
  const runNatural=()=>{const parsed=ForecastLookup.parseQuery(naturalInput?.value,sc.asof);if(parsed.ok)runLookup(parsed.date);else{lookupResult.innerHTML=lookupErrorMarkup(parsed);lookupMarker=null;paintFlow(flowFocus);}};
  if(naturalSubmit)naturalSubmit.onclick=runNatural;
  if(naturalInput)naturalInput.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();runNatural();}};
  if(initialLookup)runLookup(initialLookup);
  if(initialState.lookupOverlay||initialLookup)setLookupOverlay(true);
  const activateLab=space=>{const available={future:p1w,history:overlay,'cross-asset':crossAsset,'ai-regime':aiRegime,liquidity},active=available[space]?space:'future',copy=FLOW_LAB_COPY[active]||FLOW_LAB_COPY.future;
    Object.entries(available).forEach(([key,panel])=>{if(panel)panel.hidden=key!==active;});
    $('#flow-page-eyebrow',root).textContent=copy[0];$('#flow-page-title',root).textContent=copy[1];$('#flow-page-lede',root).textContent=`${copy[2]} 시나리오 기준 ${sc.asof} · 참고 의견이며 투자 자문이 아닙니다.`;
    labTabs.querySelectorAll('[data-lab-tab]').forEach(b=>{const on=b.dataset.labTab===active;b.setAttribute('aria-selected',String(on));b.tabIndex=on?0:-1;});};
  const availableTabs=[...labTabs.querySelectorAll('[data-lab-tab]:not(:disabled)')];
  availableTabs.forEach((b,index)=>{b.onclick=()=>{activateLab(b.dataset.labTab);syncMidHash(b.dataset.labTab==='future'?'#future':`#future/${b.dataset.labTab}`);};b.onkeydown=event=>{let next=null;if(event.key==='ArrowLeft'||event.key==='ArrowUp')next=(index-1+availableTabs.length)%availableTabs.length;if(event.key==='ArrowRight'||event.key==='ArrowDown')next=(index+1)%availableTabs.length;if(event.key==='Home')next=0;if(event.key==='End')next=availableTabs.length-1;if(next!=null){event.preventDefault();activateLab(availableTabs[next].dataset.labTab);availableTabs[next].focus();}};});
  if(overlay){
    const analogHost=$('#ovchart',overlay),paintAnalog=focus=>{analogHost.innerHTML='';drawOverlay(analogHost,overlay._overlay,overlay._eras,overlay._eraStarts,focus);
      overlay.querySelectorAll('[data-analog-focus]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.analogFocus===focus)));};
    overlay.querySelectorAll('[data-analog-focus]').forEach(b=>b.onclick=()=>paintAnalog(b.dataset.analogFocus));
    paintAnalog('ALL');
  }
  activateLab(initialState.lab||'future');
  if(crossAsset)bindCrossAsset(crossAsset,initialState.scenario);
  if(liquidity)bindLiquidity(liquidity);
}
function analogPanel(){
  const model=DATA.era_analog;if(!model||model.status!=='ok'||!model.series?.length)return null;
  const ctx=model.context||{};const o=Object.fromEntries(model.series.map(s=>[s.id,s.log10_index.map(v=>v==null?null:Math.round(100*Math.pow(10,v)*10)/10)]));
  const starts=Object.fromEntries(model.series.map(s=>[s.id,s.overlay_start||s.anchor_month||ERA_START[s.id]]));
  const eras=Object.keys(ERA_META).filter(e=>o[e]&&o[e].length>1);
  if(eras.length<2)return null;
  const focusControls=`<div class="flow-focus analog-focus" role="group" aria-label="과거 혁신 사이클 강조"><span>SPOTLIGHT</span>
    <button type="button" data-analog-focus="ALL" aria-pressed="true"><i></i>전체</button>
    ${eras.map(e=>`<button type="button" data-analog-focus="${e}" style="--focus-color:${ERA_META[e][1]}" aria-pressed="false"><i></i>${ERA_META[e][0]}</button>`).join('')}</div>`;
  const rg=ctx.regime||{},br=ctx.breadth||{},cc=ctx.concentration||{};
  const forward=model.forward_reference||{},smallForward=forward.n>0&&forward.n<20;
  const forwardCases=Array.isArray(forward.cases)?forward.cases:[];
  const horizonCell=(row,key)=>hasNumeric(row?.[key])?signedDelta(Number(row[key])*100,1,'%'):'관측 없음';
  const forwardMarkup=smallForward?`<section class="analog-case-list" aria-label="유사 국면 이후 흐름"><div><div><p class="eyebrow">유사 구간 이후 흐름</p><h3>${num(forward.n)}개 사례</h3></div><span class="count-chip">기준 ${esc(model.run_asof||'미산출')}</span></div><div>${forwardCases.map((row,index)=>`<article><strong>${esc(row.date||`사례 ${index+1}`)}</strong><span>1M ${horizonCell(row,'fwd_1m')}</span><span>3M ${horizonCell(row,'fwd_3m')}</span><span>6M ${horizonCell(row,'fwd_6m')}</span><span>12M ${horizonCell(row,'fwd_12m')}</span></article>`).join('')||'<p>표시할 사례가 없습니다.</p>'}</div></section>`:'';
  const ctxItems=[
    rg.recession_flag!=null?['경기 국면',rg.recession_flag?'침체':'확장']:null,
    br.pct_above_200dma!=null?['시장 폭','200일선 '+br.pct_above_200dma+'%']:null,
    cc.ratio_pctile!=null?['대형주 집중',cc.ratio_pctile+'%ile']:null,
    ctx.perez_ai?['사이클 국면',esc(ctx.perez_ai.split(' — ')[0])+' (추정)']:null
  ].filter(Boolean).slice(0,4);
  const w=el(`<div class="chart-panel analysis-panel">
    <p class="eyebrow">START-ALIGNED · LOG SCALE</p>
    <div class="panel-head"><h2>과거 혁신 사이클 비교</h2><span class="count-chip">${eras.length}개 사이클</span></div>
    ${forwardMarkup}
    ${focusControls}
    <div class="chart-wrap"><div id="ovchart"></div></div>
    <p class="chart-note innovation-anchor-note">모든 선은 각 사이클 시작월을 100으로 맞췄습니다. 정점 정렬이 아니며, 다우는 1925-01 시작 후 1929-09 정점이 M+56에 표시됩니다.</p>
    <div class="context-grid">${ctxItems.map(([k,v])=>`<div><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('')}</div>
  </div>`);
  w._eras=eras;w._overlay=o;w._eraStarts=starts;
  return w;
}
function betaGateNote(row){
  if(row.status==='hysteresis_hold_1_of_2')return ' · 표본 1/2회 미달·이전 β 유지';
  return row.gate_proximity==='at_boundary'?' · gate 경계(n=156)':'';
}
function crossAssetPanel(){
  const model=DATA.cross_asset;
  if(!model||model.status==='blocked'||!model.forecast?.scenarios||!model.history?.series)return null;
  const summary=model.history.summary||{},diag=model.diagnostics||{},corr60=diag.corr_60d||{},beta=diag.downside_beta_5y||{},weekly=diag.weekly_52w||{},anchors=model.anchors||{};
  const sensitivity=model.forecast?.realty_income_sensitivity||{},rateSensitivity=sensitivity.beta_rate||{},creditSensitivity=sensitivity.beta_credit||{};
  const realtyContext=model.realty_income||{},eventRows=realtyContext.event_study?.events||[],eventById=Object.fromEntries(eventRows.map(row=>[row.event_id,row]));
  const dotcomEvent=eventById.dotcom_easing||{},tighteningEvent=eventById.tightening_2004_2006||{},acuteEvent=eventById.acute_crisis_2020||{};
  const hypothesis=realtyContext.condition_summary||{},conditionLabels={C1:'신용 스트레스 비확대',C2:'장기금리 하락',C3:'실질금리 완화',C4:'배당 유지·증가'};
  const evidenceText=item=>{const pairs=Object.entries(item.metrics||{}).filter(([,value])=>value!=null).slice(0,2);return pairs.length?pairs.map(([key,value])=>`${key} ${value}`).join(' · '):item.status||'근거 대기';};
  const eventPct=(row,key)=>hasNumeric(row?.returns_pct?.[key])?signedDelta(Number(row.returns_pct[key]),1,'%'):'관측 불가';
  const eventBp=(row,key)=>hasNumeric(row?.macro_change_bp?.[key])?signedDelta(Number(row.macro_change_bp[key]),0,'bp'):'관측 불가';
  const scenarios=model.forecast.scenarios,defaultScenario=model.forecast.default_scenario||Object.keys(scenarios)[0];
  const pctText=value=>hasNumeric(value)?signedDelta(Number(value),1,'%'):'산출 전';
  const annual=summary.annual||[],period=model.history.period||`${model.history.labels?.[0]||'시작'} to ${model.history.labels?.at(-1)||'종료'}`;
  const periodCaption=period.replace(' to ',' → ');
  const ci=(range,n)=>`(10–90%: ${hasNumeric(range?.[0])?Number(range[0]).toFixed(2):'–'}–${hasNumeric(range?.[1])?Number(range[1]).toFixed(2):'–'}, n=${num(n)})`;
  const peak=summary.nasdaq_from_dotcom_peak||{},weeklyCorr=weekly.corr||{},weeklyBeta=weekly.beta||{},yearFive=(summary.annual||[]).find(row=>Number(row.year)===5)||{};
  const w=el(`<div class="chart-panel analysis-panel cross-asset-panel">
    <p class="eyebrow">자산 비교 · 시작값 100</p>
    <div class="panel-head"><div><h2>닷컴 조정 뒤 5년 · NASDAQ · Bitcoin · Realty Income · D.R. Horton</h2><p>가격 단위가 달라도 방향과 회복 속도를 바로 비교할 수 있게 시작값을 100으로 맞췄습니다.</p></div><span class="count-chip">기준 ${esc(model.asof)}</span></div>
    <section class="plain-insight" aria-label="자산 비교 읽는 법"><article><span>NASDAQ</span><strong>실제 가격</strong><p>2001년 3월 이후 실제 움직임입니다.</p></article><article><span>Realty Income</span><strong>배당 포함 실제 수익</strong><p>수정종가를 사용해 배당 재투자 효과까지 한 선에 담았습니다.</p></article><article><span>D.R. Horton</span><strong>배당 포함 실제 수익</strong><p>같은 2001-03~2006-03의 주택건설주 실측 경로입니다.</p></article><article><span>Bitcoin</span><strong>가정 경로</strong><p>${esc(model.history.bitcoin?.reason||'2009년 이전 실측이 없어 현대 민감도를 적용한 참고 경로입니다.')}</p></article></section>
    <div class="cross-view-switch" role="group" aria-label="교차자산 보기">
      <button type="button" data-cross-view="scenario" aria-pressed="true">실측 + BTC 반사실</button>
      <button type="button" data-cross-view="history" aria-pressed="false">NASDAQ·O·DHI 실측</button>
    </div>
    <section data-cross-panel="scenario">
      <div class="flow-focus cross-focus" role="radiogroup" aria-label="Bitcoin 반사실 beta 민감도">
        <span>BTC SENSITIVITY</span>${Object.entries(scenarios).map(([id,scenario])=>`<button type="button" role="radio" data-cross-scenario="${id}" aria-checked="${id===defaultScenario}" aria-pressed="${id===defaultScenario}" tabindex="${id===defaultScenario?0:-1}"><i></i>${esc(scenario.label)}</button>`).join('')}
      </div>
      <div class="cross-scenario-copy" id="cross-scenario-copy"></div>
      <div class="chart-wrap"><div id="cross-chart"></div></div>
      <div class="cross-five-year-table" id="cross-five-year-table" aria-live="polite"></div>
    </section>
    <section data-cross-panel="history" hidden>
      <div class="chart-wrap"><div id="cross-history-chart"></div></div>
      <div class="history-score-grid">
        <div><span>NASDAQ 가격</span><strong>${pctText(summary.nasdaq_price_pct)}</strong><small>${esc(periodCaption)}</small></div>
        <div><span>Realty Income · 배당 포함</span><strong>${pctText(summary.realty_income_total_return_pct)}</strong><small>수정종가 · 배당 재투자 반영</small></div>
        <div><span>D.R. Horton · 배당 포함</span><strong>${pctText(summary.dr_horton_total_return_pct)}</strong><small>수정종가 · 같은 실측 기간</small></div>
        <div><span>NASDAQ 닷컴 정점 기준</span><strong>${pctText(peak.nasdaq_price_pct)}</strong><small>${esc(peak.start||'2000-03')} → ${esc(peak.end||model.history.labels?.at(-1)||'종료')} · 별도 anchor</small></div>
      </div>
      <details class="analog-limit annual-return-table"><summary>기준월부터 연차별 실측 수익률 보기</summary><div class="table-shell"><table><thead><tr><th>구간</th><th>NASDAQ</th><th>Realty Income · 배당 포함</th><th>D.R. Horton · 배당 포함</th></tr></thead><tbody>${annual.map(row=>`<tr><td><strong>${row.year}년차</strong><small>${esc(String(row.period||'').replace(' to ',' → '))}</small></td><td>${pctText(row.nasdaq_price_pct)}</td><td>${pctText(row.realty_income_total_return_pct)}</td><td>${pctText(row.dr_horton_total_return_pct)}</td></tr>`).join('')}</tbody></table></div></details>
    </section>
    <details class="scenario-v52-method cross-asset-details"><summary>Realty Income 조건과 세부 통계 보기</summary><section class="realty-thesis-grid" aria-label="Realty Income 조건부 가설 점검">
      <article class="realty-thesis-card history-card">
        <p class="eyebrow">HISTORICAL CONDITIONS · 인과 추정 아님</p>
        <h3>닷컴 때 왜 올랐나</h3>
        <p>한 가지 원인으로 단정하지 않고, 당시 함께 관측된 네 조건을 분리해서 봅니다.</p>
        <div class="realty-factor-grid">
          <div><span>1 · 금리 완화</span><strong>${eventBp(dotcomEvent,'dgs10')}</strong><small>DGS10 · ${esc(dotcomEvent.start||'2001-01-03')} → ${esc(dotcomEvent.end||'2003-06-25')}</small></div>
          <div><span>2 · 낮은 출발 밸류</span><strong>1998–99 약세 이후</strong><small>당시 정확한 yield spread는 원천 제약으로 미표시</small></div>
          <div><span>3 · 배당 방어</span><strong>${eventPct(dotcomEvent,'realty_income_total_return')}</strong><small>배당 포함 수익 · 가격만 ${eventPct(dotcomEvent,'realty_income_price')}</small></div>
          <div><span>4 · 완만한 붕괴</span><strong>NASDAQ ${eventPct(dotcomEvent,'nasdaq_price')}</strong><small>2020 급성 위기 O ${eventPct(acuteEvent,'realty_income_price')}</small></div>
        </div>
        <p class="realty-counterexample"><strong>반례도 함께 표시:</strong> 5년차(2005-03→2006-03) O 가격 ${hasNumeric(yearFive.realty_income_price_pct)?signedDelta(yearFive.realty_income_price_pct,1,'%'):'관측 불가'} · 2004–2006 긴축 이벤트 ${eventPct(tighteningEvent,'realty_income_price')}. 닷컴 구간 상승을 모든 기술주 조정기에 반복되는 법칙으로 취급하지 않습니다.</p>
      </article>
      <article class="realty-thesis-card current-card">
        <p class="eyebrow">CURRENT COMPARISON · ${esc(sensitivity.asof||model.asof)}</p>
        <h3>2026년은 같은 조건인가</h3>
        <div class="realty-table-shell"><table><tbody>
          <tr><th>TTM 배당수익률</th><td>${hasNumeric(sensitivity.dividend_yield_ttm_pct)?Number(sensitivity.dividend_yield_ttm_pct).toFixed(2)+'%':'관측 불가'}</td></tr>
          <tr><th>10Y 대비 spread</th><td>${hasNumeric(sensitivity.spread_vs_10y_pp)?signedDelta(sensitivity.spread_vs_10y_pp,2,' pp'):'관측 불가'}</td></tr>
          <tr><th>2000년 이후 spread 위치</th><td>${hasNumeric(sensitivity.spread_percentile_since_2000)?Number(sensitivity.spread_percentile_since_2000).toFixed(1)+'%ile':'표본 축적 중'}</td></tr>
          <tr><th>금리 100bp 민감도</th><td>${hasNumeric(rateSensitivity.used_effect_per_100bp_pct)?signedDelta(rateSensitivity.used_effect_per_100bp_pct,2,'%'):'0.00%'} <small>${esc(rateSensitivity.status||'미산출')}${betaGateNote(rateSensitivity)}</small></td></tr>
          <tr><th>신용 100bp 민감도</th><td>${hasNumeric(creditSensitivity.used_effect_per_100bp_pct)?signedDelta(creditSensitivity.used_effect_per_100bp_pct,2,'%'):'0.00%'} <small>${esc(creditSensitivity.status||'미산출')}${betaGateNote(creditSensitivity)}</small></td></tr>
          <tr><th>NASDAQ 하락꼬리 beta</th><td>${hasNumeric(beta.realty_income_to_nasdaq)?Number(beta.realty_income_to_nasdaq).toFixed(2):'관측 불가'} <small>최악 10% 일간</small></td></tr>
          <tr><th>지수 편입 차이</th><td>${realtyContext.index_membership?.current==='sp_500_member_since_2015_04'?'현재 S&P 500 편입 · 2015-04 이후':'검증 대기'}</td></tr>
        </tbody></table></div>
      </article>
      <article class="realty-thesis-card condition-card">
        <p class="eyebrow">LIVE CHECKLIST · 확률 아님</p>
        <div class="condition-score"><strong>${num(hypothesis.conditions_met||0)}</strong><span>/ ${num(hypothesis.conditions_total||4)}</span></div>
        <h3>조건 4개 중 ${num(hypothesis.conditions_met||0)}개 충족</h3>
        <div class="condition-list">${(hypothesis.conditions||[]).map(item=>`<div class="${item.met?'is-met':'is-open'}"><i aria-hidden="true"></i><span>${esc(conditionLabels[item.id]||item.id)}<small>${esc(evidenceText(item))} · ${esc(item.as_of||'기준일 대기')}</small></span><strong>${item.met?'충족':'미충족'}</strong></div>`).join('')}</div>
        <p>충족 개수는 O 상승 확률이나 기대수익률이 아니라, 사전 등록한 환경 조건의 현재 상태입니다.</p>
      </article>
    </section>
    <div class="cross-diagnostics">
      <div><span>60일 BTC↔NASDAQ</span><strong>${hasNumeric(corr60.bitcoin_nasdaq)?Number(corr60.bitcoin_nasdaq).toFixed(2):'산출 전'}</strong><small>일별 로그수익 상관</small></div>
      <div><span>60일 O↔NASDAQ</span><strong>${hasNumeric(corr60.realty_income_nasdaq)?Number(corr60.realty_income_nasdaq).toFixed(2):'산출 전'}</strong><small>배당 반영 수정종가</small></div>
      <div><span>하락꼬리 BTC beta</span><strong>${hasNumeric(beta.bitcoin_to_nasdaq)?Number(beta.bitcoin_to_nasdaq).toFixed(2):'산출 전'}</strong><small>${esc(ci(beta.bitcoin_ci_10_90,beta.observations))}</small></div>
      <div><span>하락꼬리 O beta</span><strong>${hasNumeric(beta.realty_income_to_nasdaq)?Number(beta.realty_income_to_nasdaq).toFixed(2):'산출 전'}</strong><small>${esc(ci(beta.realty_income_ci_10_90,beta.observations))}</small></div>
    </div>
    ${cohortResultsMarkup(DATA.o_entry_cohort)}
    ${scenarioTrackerMarkup(DATA.scenario_tracker)}
    </details>
    <p class="chart-note realty-fixed-warning"><strong>고정 해석:</strong> Realty Income 배당 포함 수익은 2001-03~2006-03 실측입니다. D.R. Horton도 같은 기간 실측이며, 반사실 계산은 Bitcoin 선에만 적용합니다. DHI의 당시 상승은 다음 기술주 조정기의 수혜를 보장하지 않습니다.</p>
    <p class="cross-condition-note">60일 상관은 전체 최근 구간의 동행성을, 하락꼬리 beta는 NASDAQ 하위 10% 거래일의 조건부 민감도를 봅니다. 서로 다른 질문이므로 같은 값처럼 비교하지 않습니다. 주간 금요일→금요일: BTC corr ${hasNumeric(weeklyCorr.bitcoin_nasdaq)?Number(weeklyCorr.bitcoin_nasdaq).toFixed(2):'–'} / beta ${hasNumeric(weeklyBeta.bitcoin_to_nasdaq)?Number(weeklyBeta.bitcoin_to_nasdaq).toFixed(2):'–'}, O corr ${hasNumeric(weeklyCorr.realty_income_nasdaq)?Number(weeklyCorr.realty_income_nasdaq).toFixed(2):'–'} / beta ${hasNumeric(weeklyBeta.realty_income_to_nasdaq)?Number(weeklyBeta.realty_income_to_nasdaq).toFixed(2):'–'}.</p>
    <p class="chart-note"><strong>해석:</strong> NASDAQ·Realty Income·D.R. Horton은 <b>2001-03 이후 실제로 있었던 수익</b>입니다(배당 포함). Bitcoin 선만 다릅니다 — 당시엔 없던 자산이라, 그 시절 NASDAQ 월수익에 오늘의 민감도를 기계적으로 곱해 본 <b>가정</b>입니다. 그때의 실제 가격도, 앞으로의 경로도 아닙니다.</p>
    ${DATA.multi_year_stress?.presentation_html||''}
    <details class="analog-limit"><summary>모델 영수증과 한계</summary><p>${esc((model.limitations||[]).join(' '))} 출처: ${esc((model.sources||[]).map(source=>source.label).join(' · '))}</p></details>
  </div>`);
  w._crossModel=model;w._defaultScenario=defaultScenario;
  return w;
}
function cohortResultsMarkup(model){
  if(!model||model.status!=='ok'||!Array.isArray(model.summary))return '';
  const rows=model.summary;
  const pick=(sample,cohort,horizon,basis='total_return_proxy')=>rows.find(row=>row.sample===sample&&row.cohort===cohort&&Number(row.horizon_months)===horizon&&row.basis===basis)||{};
  const value=(number,suffix='%')=>hasNumeric(number)?`${Number(number).toFixed(1)}${suffix}`:'관측 불가';
  const main=[3,6,12,24,36].map(horizon=>pick('dotcom_1998_2005','all_months',horizon));
  const oos=['oos_2008','oos_2020','oos_2022'].map(sample=>({sample,row:pick(sample,'all_months',12)}));
  const signals=['nasdaq_drawdown_10','nasdaq_drawdown_20','nasdaq_drawdown_30','nasdaq_drawdown_40','after_first_fed_cut','after_hy_oas_peak','after_10y_26w_reversal'];
  const signalLabel={nasdaq_drawdown_10:'NASDAQ −10% 이후',nasdaq_drawdown_20:'NASDAQ −20% 이후',nasdaq_drawdown_30:'NASDAQ −30% 이후',nasdaq_drawdown_40:'NASDAQ −40% 이후',after_first_fed_cut:'첫 Fed cut 이후',after_hy_oas_peak:'HY OAS 정점 후',after_10y_26w_reversal:'10Y 26주 추세 반전 후'};
  return `<section class="cohort-shell" aria-labelledby="o-cohort-title">
    <div class="panel-head"><div><p class="eyebrow">PREREGISTERED · REFERENCE ONLY</p><h3 id="o-cohort-title">O 월별 진입 cohort</h3><p>월말 신호 → 익월 첫 거래일 체결 · 왕복 비용 10bp · 보유 중 ex-date 배당만 재투자</p></div><span class="count-chip">as of ${esc(model.asof)}</span></div>
    <div class="cohort-guard"><strong>진입 시점·가격을 추천하지 않습니다.</strong><span>historical cohort 결과이며 현재 진입상태 규칙은 아직 등록하지 않았습니다.</span></div>
    <div class="cohort-headline">${oos.map(({sample,row})=>`<article><span>${esc(sample.replace('oos_',''))} OOS · 12개월</span><strong>${value(row.median_return_pct)}</strong><small>중앙 배당 포함 수익 · 적중 ${value(row.hit_rate_pct)} · 최악 ${value(row.worst_return_pct)} · 표본 n=${num(row.n||0)}</small></article>`).join('')}</div>
    <div class="table-shell cohort-table"><table><thead><tr><th>보유</th><th>표본</th><th>중앙 총수익</th><th>적중률</th><th>최악</th><th>중앙 MDD</th><th>최악 MDD</th><th>중앙 회복일</th></tr></thead><tbody>${main.map(row=>`<tr><td>${num(row.horizon_months)}개월</td><td>n=${num(row.n||0)}</td><td>${value(row.median_return_pct)}</td><td>${value(row.hit_rate_pct)}</td><td>${value(row.worst_return_pct)}</td><td>${value(row.median_max_drawdown_pct)}</td><td>${value(row.worst_max_drawdown_pct)}</td><td>${hasNumeric(row.median_recovery_days)?`${num(row.median_recovery_days)}일`:'관측 불가'}</td></tr>`).join('')}</tbody></table></div>
    <details class="analog-limit cohort-signals"><summary>닷컴 구간 신호별 12개월 cohort 보기</summary><div class="table-shell"><table><thead><tr><th>사전 등록 신호</th><th>표본</th><th>중앙 총수익</th><th>적중률</th><th>최악</th><th>미회복</th></tr></thead><tbody>${signals.map(signal=>{const row=pick('dotcom_1998_2005',signal,12);return `<tr><td>${esc(signalLabel[signal])}</td><td>n=${num(row.n||0)}</td><td>${value(row.median_return_pct)}</td><td>${value(row.hit_rate_pct)}</td><td>${value(row.worst_return_pct)}</td><td>${num(row.unrecovered_count||0)}</td></tr>`;}).join('')}</tbody></table></div></details>
    <p class="chart-note">이 숫자들은 <b>과거 사례를 모아 요약한 것</b>이지 앞으로의 확률이 아닙니다. 아직 기간이 안 끝난 사례는 계산에서 빼고 건수로만 남깁니다.</p>
  </section>`;
}
function scenarioTrackerMarkup(model){
  if(!model||model.status==='blocked')return `<section class="tracker-shell is-blocked"><div class="panel-head"><h3>Scenario Tracker</h3><span class="count-chip">원천 대기</span></div><p>주간 신호 스냅샷이 아직 없습니다. 기존 자산 전이 경로에는 임의 신호를 대입하지 않습니다.</p></section>`;
  const stateLabel={deleveraging_support:'디레버리징 지지',easing_rotation_support:'완화·순환 지지',neutral:'중립',source_unavailable:'원천 미확보'};
  stateLabel.rates_stay_high_support='고금리 지속 지지';
  const counts=model.summary?.counts||{};
  const monitor=DATA.source_monitoring?.defillama_stablecoins;
  const unavailableReason=signal=>signal.id==='S5'&&monitor?`D0 안정성 ${num(monitor.consecutive_successful_days)}/${num(monitor.required_successful_days)}일 · license ${esc(monitor.license_status)}`:esc(signal.reason||'원천 미확보');
  return `<section class="tracker-shell" aria-labelledby="tracker-title"><div class="panel-head"><div><p class="eyebrow">PREREGISTERED CHECKLIST · 확률 아님</p><h3 id="tracker-title">Scenario Tracker</h3></div><span class="count-chip">주간 기준 ${esc(model.asof)}</span></div>
    <div class="tracker-summary"><strong>${num(counts.deleveraging_support||0)} 디레버리징 · ${num(counts.easing_rotation_support||0)} 완화 · ${num(counts.neutral||0)} 중립</strong><span>${num(model.summary?.available)}/${num(model.summary?.total)} 신호 가동 · 가중 합산 없음</span></div>
    <div class="tracker-grid">${(model.signals||[]).map(signal=>`<article class="tracker-card state-${signal.state}"><div><span>${esc(signal.id)}</span><i aria-hidden="true"></i></div><strong>${esc(signal.name)}</strong><small>${esc(stateLabel[signal.state]||signal.state)}</small>${signal.state==='source_unavailable'?`<p>${unavailableReason(signal)}</p>`:`<p>${Object.entries(signal.metrics||{}).map(([key,value])=>`${esc(key.replaceAll('_',' '))} ${hasNumeric(value)?num(value):'–'}`).join(' · ')}</p>`}</article>`).join('')}</div>
    <div class="asset-diagnostic-grid"><div><span>BTC 반감기 위치</span><strong>+${num(model.asset_diagnostics?.bitcoin?.months_since_halving)}개월</strong><small>200일선 대비 ${signedDelta(model.asset_diagnostics?.bitcoin?.price_vs_200dma_pct,1,'%')}</small></div><div><span>O 배당–10Y spread</span><strong>${signedDelta(model.asset_diagnostics?.realty_income?.dividend_yield_spread_pp,2,' pp')}</strong><small>금리Δ–O 수익 52주 corr ${num(model.asset_diagnostics?.realty_income?.rate_change_o_return_corr_52w)}</small></div></div>
    <p class="tracker-warning">${esc(model.warning||'이 체크리스트는 사전 등록된 방향 규칙이며 확률이 아닙니다.')}</p></section>`;
}
function aiRegimePanel(){
  const model=DATA.ai_regime||{status:'blocked',coverage:0,coverage_threshold:.6,company_coverage:[],reason:'스냅샷 없음'};
  const coverage=hasNumeric(model.coverage)?Number(model.coverage):0,threshold=hasNumeric(model.coverage_threshold)?Number(model.coverage_threshold):.6;
  if(model.status==='blocked'||coverage<threshold){return el(`<div class="chart-panel analysis-panel ai-regime-panel">
    <p class="eyebrow">AI CAPITAL CYCLE · D2 COVERAGE GATE</p>
    <div class="panel-head"><div><h2>AI 자본사이클 레짐 지도</h2><p>Funding & Liquidity × AI Monetization Coverage</p></div><span class="count-chip">기준 ${esc(model.asof||'수집 전')}</span></div>
    <div class="coverage-block-card" role="status"><span>MAP WITHHELD</span><strong>데이터 커버리지 부족</strong><p>현재 ${Math.round(coverage*100)}% · 지도 허용 기준 ${Math.round(threshold*100)}%</p><div class="coverage-meter"><i style="width:${Math.min(100,coverage*100)}%"></i></div><small>불완전한 축 좌표를 그리지 않습니다. 확률·fan·가중치는 표시하지 않습니다.</small></div>
    <div class="company-coverage-grid">${(model.company_coverage||[]).map(row=>`<div><span>${esc(row.company)}</span><strong>${Math.round(Number(row.coverage||0)*100)}%</strong><small>filing segment 추출 대기</small></div>`).join('')}</div>
    <p class="chart-note">백필 값은 향후 <strong>reconstructed</strong> 라벨로 실시간 수집 구간과 분리합니다. coverage 60%를 넘기 전에는 사분면·trail·waterfall을 생성하지 않습니다.</p>
  </div>`);}
  return el(`<div class="chart-panel analysis-panel ai-regime-panel"><p class="eyebrow">AI CAPITAL CYCLE · D3 GATE</p><div class="panel-head"><div><h2>AI 자본사이클 레짐 지도</h2><p>커버리지 게이트는 통과했지만 검증된 좌표 스냅샷이 없습니다.</p></div><span class="count-chip">기준 ${esc(model.asof||'수집 전')}</span></div><div class="coverage-block-card" role="status"><span>MAP WITHHELD</span><strong>검증 스냅샷 대기</strong><p>D3 산출물을 확인하기 전에는 좌표·trail·fan을 표시하지 않습니다.</p></div></div>`);
}
function liquidityPanel(){
  const model=DATA.liquidity;
  if(!model||model.status==='blocked'||!model.series?.labels?.length)return el(`<div class="chart-panel analysis-panel liquidity-panel"><p class="eyebrow">LIQUIDITY TIDE MAP · REFERENCE ONLY</p><div class="panel-head"><div><h2>유동성 조류 지도</h2><p>주간 원천 수집이 완료되면 Fed 순유동성과 BTC·NASDAQ 민감도를 같은 축에 표시합니다.</p></div><span class="count-chip">원천 대기</span></div><div class="coverage-block-card" role="status"><span>DATA WITHHELD</span><strong>검증 스냅샷 없음</strong><p>외부 원천 실패 시 이전 스냅샷만 유지하며 임의 값을 채우지 않습니다.</p></div><p class="tracker-warning">유동성 확장이 곧 상승을 뜻하지 않습니다. 시차 상관은 국면 의존 진단입니다.</p></div>`);
  const zoneLabel={expansion:'확장',neutral:'중립',contraction:'수축'}[model.zone]||model.zone;
  const monitor=DATA.source_monitoring?.defillama_stablecoins||{};
  const stablecoinProgress=hasNumeric(monitor.consecutive_successful_days)?`${num(monitor.consecutive_successful_days)}/${num(monitor.required_successful_days||14)}일`:'원천 미확보';
  const lagRows=asset=>(model.lead_lag?.[asset]||[]).map(row=>`<tr><td>${row.lag_weeks}주</td><td>${row.correlation==null?`표본 축적 중 ${num(row.observations)}/${num(row.minimum_observations)}`:Number(row.correlation).toFixed(2)}</td><td>${num(row.observations)}</td></tr>`).join('');
  const w=el(`<div class="chart-panel analysis-panel liquidity-panel">
    <p class="eyebrow">시장 자금 흐름 · 참고 지표</p>
    <div class="panel-head"><div><h2>유동성이 늘고 줄어든 구간</h2><p>시장에 풀린 자금과 NASDAQ·Bitcoin의 실제 26주 수익률을 같은 주간축에서 봅니다.</p></div><span class="count-chip">기준 ${esc(model.asof)}</span></div>
    <section class="plain-insight" aria-label="유동성 그래프 읽는 법"><article><span>한 그래프 · 왼쪽 축</span><strong>Fed 순유동성 52주 z</strong><p>0은 최근 1년 평균, +는 평균보다 많고 −는 적다는 뜻입니다.</p></article><article><span>한 그래프 · 오른쪽 축</span><strong>26주 실제 수익률</strong><p>NASDAQ과 Bitcoin의 같은 주간 움직임을 유동성 선과 바로 겹쳐 봅니다.</p></article><article><span>주의</span><strong>축과 단위가 다릅니다</strong><p>겹쳐 움직여도 인과관계나 상승 보장은 아닙니다.</p></article></section>
    <div class="liquidity-zone zone-${esc(model.zone)}"><span>현재 구간</span><strong>${esc(zoneLabel)}</strong><small>최근 4주 Fed 순유동성 ${signedDelta(model.zone_metric?.value,2,'%')}</small></div>
    <div class="chart-wrap"><div id="liquidity-chart"></div></div>
    <details class="scenario-v52-method liquidity-details"><summary>데이터 출처와 시차 통계 보기</summary><div class="liquidity-source-grid"><div><span>실질 M2 전년비</span><strong>수집 전</strong><small>${esc(model.real_m2?.reason||'시점별 원본 자료가 필요합니다.')}</small></div><div><span>스테이블코인 공급</span><strong>${stablecoinProgress}</strong><small>원천 안정성 확인 중 · 자동 반영하지 않음</small></div><div><span>BTC ETF 자금 흐름</span><strong>수집 전</strong><small>독립 출처 두 곳의 교차검증이 필요합니다.</small></div></div>
    <details class="analog-limit liquidity-lag"><summary>0·4·8·12주 시차 상관 진단</summary><div class="lag-table-grid"><div><h3>NASDAQ</h3><div class="table-shell"><table><thead><tr><th>시차</th><th>상관 또는 게이트</th><th>n</th></tr></thead><tbody>${lagRows('nasdaq')}</tbody></table></div></div><div><h3>Bitcoin</h3><div class="table-shell"><table><thead><tr><th>시차</th><th>상관 또는 게이트</th><th>n</th></tr></thead><tbody>${lagRows('bitcoin')}</tbody></table></div></div></div></details>
    </details>
  </div>`);w._liquidityModel=model;return w;
}
function bindLiquidity(panel){
  const model=panel?._liquidityModel,host=$('#liquidity-chart',panel);
  if(!host||!model?.series?.labels?.length)return;
  drawLiquidity(host,model);
}
function drawLiquidity(host,model){
  const NS='http://www.w3.org/2000/svg',W=1160,H=390,ML=72,MR=72,MT=46,MB=48,PANEL=H-MT-MB,PW=W-ML-MR;
  const labels=model.series.labels,n=labels.length,z=model.series.fed_net_liquidity_z_52w,ndx=model.series.nasdaq_return_26w_pct,btc=model.series.bitcoin_return_26w_pct,zones=model.series.liquidity_zone;
  const X=i=>ML+PW*i/Math.max(1,n-1),svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width','100%');svg.setAttribute('role','img');svg.setAttribute('tabindex','0');svg.setAttribute('aria-label','유동성 조류 주간 차트. 좌우 화살표로 이동');
  const mk=(tag,attrs)=>{const node=document.createElementNS(NS,tag);for(const key in attrs)node.setAttribute(key,attrs[key]);return node;};
  const tx=(x,y,value,opts={})=>{const node=mk('text',{x,y,fill:opts.fill||'#5f5d57','font-size':opts.fs||12,'text-anchor':opts.anc||'start','font-weight':opts.w||500});node.textContent=value;return node;};
  const zoneColor={expansion:'#247d78',neutral:'#9a6700',contraction:'#c9002d'};
  zones.forEach((zone,index)=>svg.appendChild(mk('rect',{x:X(index),y:MT,width:PW/Math.max(1,n-1)+1,height:PANEL,fill:zoneColor[zone]||'#aaa',opacity:.045})));
  const scale=(values)=>{const nums=values.filter(hasNumeric).map(Number),rawLo=Math.min(...nums),rawHi=Math.max(...nums),pad=Math.max(.25,(rawHi-rawLo)*.12),lo=rawLo-pad,hi=rawHi+pad;return {lo,hi,y:value=>MT+PANEL*(1-(Number(value)-lo)/Math.max(.0001,hi-lo))};};
  const zScale=scale(z),returnScale=scale([...ndx,...btc]),yz=zScale.y,yr=returnScale.y;
  const liquiditySeries=[
    {values:z,color:'#6b4bc3',y:yz,top:MT,label:'Fed 순유동성 · 52주 z (왼쪽)',labelX:ML},
    {values:ndx,color:'#ff4f17',y:yr,top:MT,label:'NASDAQ · 26주 % (오른쪽)',labelX:ML+300},
    {values:btc,color:'#1f6feb',y:yr,top:MT,label:'BITCOIN · 26주 % (오른쪽)',labelX:ML+620}
  ];
  liquiditySeries.forEach(({values,color,y})=>{let path='';values.forEach((value,index)=>{if(hasNumeric(value))path+=(path?'L':'M')+X(index)+','+y(value)+' ';});svg.appendChild(mk('path',{d:path,fill:'none',stroke:color,'stroke-width':2.6,'stroke-linejoin':'round'}));});
  liquiditySeries.forEach(({color,top,label,labelX})=>{svg.appendChild(mk('line',{x1:labelX,y1:top-13,x2:labelX+20,y2:top-13,stroke:color,'stroke-width':3}));svg.appendChild(tx(labelX+27,top-9,label,{fill:color,w:750}));});
  Array.from({length:5},(_,i)=>i).forEach(i=>{const ratio=i/4,y=MT+PANEL*ratio,zValue=zScale.hi-(zScale.hi-zScale.lo)*ratio,returnValue=returnScale.hi-(returnScale.hi-returnScale.lo)*ratio;svg.appendChild(mk('line',{x1:ML,y1:y,x2:ML+PW,y2:y,stroke:'rgba(17,17,15,.12)'}));svg.appendChild(tx(ML-10,y+4,zValue.toFixed(1),{anc:'end',fill:'#6b4bc3',fs:11}));svg.appendChild(tx(ML+PW+10,y+4,`${returnValue.toFixed(0)}%`,{fill:'#76500b',fs:11}));});
  if(zScale.lo<0&&zScale.hi>0)svg.appendChild(mk('line',{x1:ML,y1:yz(0),x2:ML+PW,y2:yz(0),stroke:'#6b4bc3','stroke-dasharray':'3 5',opacity:.35}));
  svg.appendChild(mk('line',{x1:ML,y1:MT+PANEL,x2:ML+PW,y2:MT+PANEL,stroke:'rgba(17,17,15,.25)'}));
  [0,Math.floor((n-1)/2),n-1].forEach(index=>svg.appendChild(tx(X(index),H-12,labels[index].slice(0,7),{anc:'middle'})));
  const cursor=mk('line',{y1:MT,y2:MT+PANEL,stroke:'rgba(17,17,15,.52)','stroke-dasharray':'4 3'});svg.appendChild(cursor);const overlay=mk('rect',{x:ML,y:MT,width:PW,height:PANEL,fill:'transparent'});svg.appendChild(overlay);
  const readout=document.createElement('div');readout.className='flow-readout liquidity-readout';readout.setAttribute('role','status');readout.setAttribute('aria-live','polite');let selected=n-1;
  const paint=index=>{selected=Math.max(0,Math.min(n-1,index));cursor.setAttribute('x1',X(selected));cursor.setAttribute('x2',X(selected));readout.innerHTML=`<div class="flow-date"><span>SELECTED WEEK</span><strong>${esc(labels[selected])}</strong><small>${esc(({expansion:'확장',neutral:'중립',contraction:'수축'}[zones[selected]]||zones[selected]))} zone</small></div><div><span>Fed liquidity z</span><strong>${hasNumeric(z[selected])?Number(z[selected]).toFixed(2):'표본 축적 중'}</strong><small>52주 rolling</small></div><div><span>NASDAQ</span><strong>${hasNumeric(ndx[selected])?signedDelta(ndx[selected],1,'%'):'표본 축적 중'}</strong><small>26주 수익률</small></div><div><span>Bitcoin</span><strong>${hasNumeric(btc[selected])?signedDelta(btc[selected],1,'%'):'표본 축적 중'}</strong><small>26주 수익률</small></div>`;};
  const fromPointer=event=>{const rect=svg.getBoundingClientRect(),x=(event.clientX-rect.left)*(W/rect.width);return Math.round((x-ML)/(PW/Math.max(1,n-1)));};overlay.addEventListener('pointermove',event=>paint(fromPointer(event)));overlay.addEventListener('pointerdown',event=>{paint(fromPointer(event));svg.focus();});svg.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();paint(selected+(event.key==='ArrowLeft'?-1:1));}else if(event.key==='Home'){event.preventDefault();paint(0);}else if(event.key==='End'){event.preventDefault();paint(n-1);}});host.replaceChildren(svg,readout);paint(selected);
}
function crossFiveYearTableMarkup(model,scenario){
  const labels=model.forecast?.labels||[],years=[0,12,24,36,48,60].filter(month=>month<labels.length),paths={...(scenario.paths||{}),dr_horton_total_return:model.history?.series?.dr_horton_total_return||[]};
  const rowLabel=month=>month===0?'기준월':`${month/12}년 후`;
  return `<section class="cross-yearly-compare" aria-labelledby="cross-yearly-title"><div class="panel-head"><div><p class="eyebrow">OBSERVED BASELINE · BTC COUNTERFACTUAL</p><h3 id="cross-yearly-title">2001-03부터 2006-03까지 5개년 비교</h3><p>2001-03=100 · NASDAQ·Realty Income·D.R. Horton은 실측, Bitcoin만 선택 beta에 따른 반사실 값입니다.</p></div><span class="count-chip">${esc(scenario.label)}</span></div>
    <div class="cross-phase-strip"><span><b>OBSERVED</b>NASDAQ · Realty Income · D.R. Horton</span><span><b>SYNTHETIC</b>Bitcoin · 2009년 이전 실측 없음</span><span><b>NO PROBABILITY</b>확률·단일 가격 제시·기대수익 아님</span></div>
    <div class="table-shell"><table><thead><tr><th>경과</th><th>NASDAQ</th><th>Bitcoin 반사실</th><th>Realty Income · 배당 포함</th><th>D.R. Horton · 배당 포함</th></tr></thead><tbody>${years.map(month=>`<tr><td><strong>${rowLabel(month)}</strong><small>${esc(labels[month])}</small></td>${['nasdaq','bitcoin','realty_income_total_return','dr_horton_total_return'].map(key=>{const indexed=Number(paths[key]?.[month]),change=indexed-100;return `<td><strong style="color:${CROSS_META[key][1]}">${signedDelta(change,1,'%')}</strong><small>${month===0?'비교 기준 0%':'시작월 대비'}</small></td>`;}).join('')}</tr>`).join('')}</tbody></table></div>
    <p class="chart-note">BTC 산식: 직전값 × exp(beta × 해당 월 NASDAQ 로그수익). 하락월 beta ${Number(scenario.downside_beta).toFixed(2)} · 상승월 beta ${Number(scenario.upside_beta).toFixed(2)}. bootstrap 음영은 민감도 범위이지 신뢰구간이나 확률대가 아닙니다.</p></section>`;
}
function bindCrossAsset(panel,initialScenario){
  const model=panel._crossModel;let view='scenario',scenarioId=model.forecast.scenarios?.[initialScenario]?initialScenario:panel._defaultScenario;
  const scenarioHost=$('#cross-chart',panel),historyHost=$('#cross-history-chart',panel),copy=$('#cross-scenario-copy',panel),yearTable=$('#cross-five-year-table',panel);
  const paintScenario=()=>{const scenario=model.forecast.scenarios[scenarioId];
    copy.innerHTML=`<div><span>선택한 BTC 경우의 수</span><strong>${esc(scenario.label)}</strong><small>${esc(scenario.short)}</small></div><p><span>하락월 β ${Number(scenario.downside_beta).toFixed(2)}</span><span>상승월 β ${Number(scenario.upside_beta).toFixed(2)}</span><span>${esc(scenario.rule)}</span></p><p class="cross-attribution">NASDAQ·Realty Income·D.R. Horton은 모든 버튼에서 같은 실측값을 유지합니다.</p><p class="cross-interpretation">Bitcoin만 beta 민감도에 따라 달라지며, 당시 가격을 복원한 값이 아닙니다.</p>`;
    if(yearTable)yearTable.innerHTML=crossFiveYearTableMarkup(model,scenario);
    drawCrossAsset(scenarioHost,model,scenarioId);
    panel.querySelectorAll('[data-cross-scenario]').forEach(button=>{const active=button.dataset.crossScenario===scenarioId;button.setAttribute('aria-pressed',String(active));button.setAttribute('aria-checked',String(active));button.tabIndex=active?0:-1;});
  };
  const setView=next=>{view=next==='history'?'history':'scenario';
    panel.querySelectorAll('[data-cross-panel]').forEach(section=>section.hidden=section.dataset.crossPanel!==view);
    panel.querySelectorAll('[data-cross-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.crossView===view)));
    if(view==='history'&&!historyHost.childElementCount)drawCrossAssetHistory(historyHost,model);
  };
  const shockButtons=[...panel.querySelectorAll('[data-cross-scenario]')];
  shockButtons.forEach((button,index)=>{button.onclick=()=>{scenarioId=button.dataset.crossScenario;paintScenario();history.replaceState(null,'',`#lab=cross-asset&scenario=${encodeURIComponent(scenarioId)}`);};button.onkeydown=event=>{let next=null;if(event.key==='ArrowLeft'||event.key==='ArrowUp')next=(index-1+shockButtons.length)%shockButtons.length;if(event.key==='ArrowRight'||event.key==='ArrowDown')next=(index+1)%shockButtons.length;if(event.key==='Home')next=0;if(event.key==='End')next=shockButtons.length-1;if(next!=null){event.preventDefault();scenarioId=shockButtons[next].dataset.crossScenario;paintScenario();shockButtons[next].focus();}};});
  panel.querySelectorAll('[data-cross-view]').forEach(button=>button.onclick=()=>setView(button.dataset.crossView));
  paintScenario();setView(view);
}
function drawCrossAsset(host,model,scenarioId){
  const scenario=model.forecast.scenarios[scenarioId];
  const series={...scenario.paths,dr_horton_total_return:model.history.series.dr_horton_total_return};
  drawIndexedCompare(host,{labels:model.forecast.labels,series,
    bands:scenario.paths_band,keys:['nasdaq','bitcoin','realty_income_total_return','dr_horton_total_return'],title:`${scenario.label} · 2001-03~2006-03 실측/반사실 비교`,selected:0,history:true,valueMode:'return_from_100',
    tickIndexes:[0,12,24,36,48,60]});
}
function drawCrossAssetHistory(host,model){
  drawIndexedCompare(host,{labels:model.history.labels,series:model.history.series,
    keys:['nasdaq_price','realty_income_total_return','dr_horton_total_return'],title:`${model.history.period} 실측 비교`,selected:model.history.labels.length-1,history:true,valueMode:'return_from_100'});
}
function resolveEndpointLabels(items,minGap=16,top=12,bottom=438){
  if(!items.length)return [];
  const sorted=items.map(item=>({...item,labelY:Math.max(top,Math.min(bottom,item.y))})).sort((a,b)=>a.labelY-b.labelY);
  for(let i=1;i<sorted.length;i++)sorted[i].labelY=Math.max(sorted[i].labelY,sorted[i-1].labelY+minGap);
  if(sorted.at(-1).labelY>bottom){sorted.at(-1).labelY=bottom;for(let i=sorted.length-2;i>=0;i--)sorted[i].labelY=Math.min(sorted[i].labelY,sorted[i+1].labelY-minGap);}
  if(sorted[0].labelY<top){sorted[0].labelY=top;for(let i=1;i<sorted.length;i++)sorted[i].labelY=Math.max(sorted[i].labelY,sorted[i-1].labelY+minGap);}
  return sorted;
}
function drawIndexedCompare(host,config){
  const NS='http://www.w3.org/2000/svg',W=1160,H=450,ML=58,MR=132,MT=42,MB=42;
  const PW=W-ML-MR,PH=H-MT-MB,n=config.labels.length;
  const all=[...config.keys.flatMap(key=>config.series[key]||[]),...config.keys.flatMap(key=>[...(config.bands?.[key]?.p10||[]),...(config.bands?.[key]?.p90||[])])].filter(hasNumeric).map(Number);
  const lo=Math.floor((Math.min(...all)-8)/10)*10,hi=Math.ceil((Math.max(...all)+8)/10)*10;
  const X=i=>ML+PW*i/Math.max(1,n-1),Y=v=>MT+PH*(1-(v-lo)/Math.max(1,hi-lo));
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width','100%');
  svg.setAttribute('role','img');svg.setAttribute('tabindex','0');svg.setAttribute('aria-label',`${config.title}. 좌우 화살표로 시점 이동`);
  const mk=(tag,attrs)=>{const node=document.createElementNS(NS,tag);for(const key in attrs)node.setAttribute(key,attrs[key]);return node;};
  const tx=(x,y,value,opts={})=>{const node=mk('text',{x,y,fill:opts.fill||'#5f5d57','font-size':opts.fs||12,'text-anchor':opts.anc||'start','font-weight':opts.w||500,opacity:opts.opacity??1});node.textContent=value;return node;};
  const displayValue=value=>config.valueMode==='return_from_100'?signedDelta(Number(value)-100,1,'%'):num(value);
  const ticks=5;for(let i=0;i<=ticks;i++){const value=lo+(hi-lo)*i/ticks,y=Y(value);
    svg.appendChild(mk('line',{x1:ML,y1:y,x2:ML+PW,y2:y,stroke:value===100?'rgba(17,17,15,.28)':'rgba(17,17,15,.09)','stroke-width':value===100?1.4:1}));
    svg.appendChild(tx(ML-8,y+4,config.valueMode==='return_from_100'?signedDelta(value-100,0,'%'):Math.round(value),{anc:'end'}));}
  const labelIndexes=Array.isArray(config.tickIndexes)
    ?config.tickIndexes.filter(index=>index>=0&&index<n)
    :config.history
    ?config.labels.map((label,index)=>label.endsWith('-06')||index===0||index===n-1?index:null).filter(index=>index!=null)
    :[0,3,6,9,12].filter(index=>index<n);
  labelIndexes.forEach(index=>svg.appendChild(tx(X(index),MT+PH+24,config.history?config.labels[index].slice(0,4):config.labels[index],{anc:'middle'})));
  config.keys.forEach(key=>{const band=config.bands?.[key],meta=CROSS_META[key];if(!band)return;const points=band.p90.map((value,index)=>`${X(index)},${Y(value)}`).concat([...band.p10].reverse().map((value,reverseIndex)=>{const index=band.p10.length-1-reverseIndex;return `${X(index)},${Y(value)}`;}));svg.appendChild(mk('polygon',{points:points.join(' '),fill:meta[1],opacity:.11,stroke:'none'}));});
  const endpoints=[];config.keys.forEach(key=>{const values=config.series[key],meta=CROSS_META[key],dash=meta[2];let path='';
    values.forEach((value,index)=>{if(value!=null)path+=(path?'L':'M')+X(index)+','+Y(value)+' ';});
    svg.appendChild(mk('path',{d:path,fill:'none',stroke:meta[1],'stroke-width':key.includes('total_return')?2.4:3,'stroke-dasharray':dash,'stroke-linejoin':'round'}));
    const last=values.length-1,value=values[last];svg.appendChild(mk('circle',{cx:X(last),cy:Y(value),r:4,fill:meta[1],stroke:'#fff','stroke-width':1.8}));
    endpoints.push({key,y:Y(value),value,meta});
  });
  resolveEndpointLabels(endpoints,16,MT+8,MT+PH-8).forEach(item=>{svg.appendChild(mk('line',{x1:X(n-1)+5,y1:item.y,x2:X(n-1)+12,y2:item.labelY,stroke:item.meta[1],'stroke-width':1,opacity:.65}));svg.appendChild(tx(X(n-1)+15,item.labelY+4,`${item.meta[0]} ${displayValue(item.value)}`,{fill:item.meta[1],w:700}));});
  const cursor=mk('line',{stroke:'rgba(17,17,15,.5)','stroke-width':1.2,'stroke-dasharray':'4 3'});svg.appendChild(cursor);
  const markers=config.keys.map(key=>{const marker=mk('circle',{r:5,fill:CROSS_META[key][1],stroke:'#fff','stroke-width':2});svg.appendChild(marker);return marker;});
  const overlay=mk('rect',{x:ML,y:MT,width:PW,height:PH,fill:'transparent'});svg.appendChild(overlay);
  const readout=document.createElement('div');readout.className='flow-readout cross-asset-readout';readout.setAttribute('role','status');readout.setAttribute('aria-live','polite');readout.setAttribute('aria-atomic','true');readout.style.setProperty('--flow-count',String(config.keys.length+1));
  const tip=document.getElementById('tip'),finePointer=window.matchMedia('(pointer: fine)').matches;let selected=Math.max(0,Math.min(n-1,config.selected||0));
  const paint=index=>{selected=Math.max(0,Math.min(n-1,index));const x=X(selected);cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);cursor.setAttribute('y1',MT);cursor.setAttribute('y2',MT+PH);
    markers.forEach((marker,i)=>{const value=config.series[config.keys[i]][selected];marker.setAttribute('cx',x);marker.setAttribute('cy',Y(value));});
    readout.innerHTML=`<div class="flow-date"><span>SELECTED POINT</span><strong>${esc(config.labels[selected])}</strong><small>시작월 수익률 = 0%</small></div>${config.keys.map(key=>`<div><span>${esc(CROSS_META[key][0])}</span><strong style="color:${CROSS_META[key][1]}">${displayValue(config.series[key][selected])}</strong><small>시작월 대비</small></div>`).join('')}`;
    svg.setAttribute('aria-label',`${config.title}, 선택 ${config.labels[selected]}. 좌우 화살표로 이동`);
  };
  const fromPointer=event=>{const rect=svg.getBoundingClientRect(),mx=(event.clientX-rect.left)*(W/rect.width);return Math.max(0,Math.min(n-1,Math.round((mx-ML)/(PW/Math.max(1,n-1)))));};
  overlay.addEventListener('pointermove',event=>{const index=fromPointer(event);paint(index);if(finePointer){tip.style.display='block';tip.style.left=(event.clientX+14)+'px';tip.style.top=(event.clientY-10)+'px';tip.innerHTML=`<b>${esc(config.labels[index])} · 시작월 대비</b>`+config.keys.map(key=>`<span class="tip-series" style="--tip-series:${CROSS_META[key][1]}"><i aria-hidden="true"></i><span>${esc(CROSS_META[key][0])}</span><strong>${displayValue(config.series[key][index])}</strong></span>`).join('');}});
  overlay.addEventListener('pointerdown',event=>{paint(fromPointer(event));if(!finePointer)tip.style.display='none';svg.focus();});overlay.addEventListener('pointerleave',()=>{tip.style.display='none';});
  svg.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();paint(selected+(event.key==='ArrowLeft'?-1:1));}else if(event.key==='Home'){event.preventDefault();paint(0);}else if(event.key==='End'){event.preventDefault();paint(n-1);}});
  host.replaceChildren(svg,readout);paint(selected);
}
function drawOverlay(host,o,eras,starts=ERA_START,focus='ALL'){
  const NS='http://www.w3.org/2000/svg';
  const W=1160,H=430,ML=58,MR=120,MT=26,MB=34,CAP=60;
  const PW=W-ML-MR,PH=H-MT-MB;
  const lg=Math.log10,Y0=lg(55),Y1=lg(2100);
  const X=m=>ML+PW*m/CAP,Y=v=>MT+PH*(1-(lg(v)-Y0)/(Y1-Y0));
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width','100%');
  svg.setAttribute('role','img');svg.setAttribute('tabindex','0');svg.setAttribute('aria-label','과거 혁신 사이클 정규화 비교. 좌우 화살표로 기준 월 이동');
  const mk=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;};
  const tx=(x,y,s,ob={})=>{const e=mk('text',{x,y,fill:ob.fill||'rgba(17,17,15,.66)','font-size':ob.fs||12,'text-anchor':ob.anc||'start','font-weight':ob.w||400,opacity:ob.opacity??1});e.textContent=s;return e;};
  [100,200,400,800,1600].forEach(v=>{svg.appendChild(mk('line',{x1:ML,y1:Y(v),x2:ML+PW,y2:Y(v),stroke:v===100?'rgba(17,17,15,.22)':'rgba(17,17,15,.09)','stroke-width':1}));
    svg.appendChild(tx(ML-8,Y(v)+4,String(v),{anc:'end',fill:'rgba(17,17,15,.5)'}));});
  for(let m=0;m<=CAP;m+=12){svg.appendChild(tx(X(m),MT+PH+18,'M+'+m,{anc:'middle',fs:12,fill:m?'#5f5d57':'#34322e'}));}
  eras.forEach(e=>{const[label,color,sw,dash,alpha]=ERA_META[e],on=focus==='ALL'||focus===e;const vals=o[e].slice(0,CAP+1);let d='';
    vals.forEach((v,i)=>{d+=(i?'L':'M')+X(i)+','+Y(Math.max(v,60))+' ';});
    svg.appendChild(mk('path',{d,fill:'none',stroke:color,'stroke-width':on?Math.max(2.4,sw):1.1,'stroke-linejoin':'round',
      'stroke-dasharray':dash,opacity:on?alpha:.1}));
    if(e==='ai'){const last=vals[vals.length-1];const i=vals.length-1;
      svg.appendChild(mk('circle',{cx:X(i),cy:Y(last),r:on?3.8:2.5,fill:color,stroke:'#fff','stroke-width':1.5,opacity:on?1:.12}));
      svg.appendChild(tx(X(i)+8,Y(last)+4,`현재 ${monthAt(starts.ai,i)} · M+${i}`,{fill:'#34322e',fs:12,w:650,opacity:on?1:.12}));}});
  const xh=mk('line',{stroke:'rgba(17,17,15,.44)','stroke-width':1.2,'stroke-dasharray':'4 3',opacity:1});svg.appendChild(xh);
  const markers=eras.map(e=>{const marker=mk('circle',{r:4.8,fill:ERA_META[e][1],stroke:'#fff','stroke-width':1.8});svg.appendChild(marker);return marker;});
  const ov=mk('rect',{x:ML,y:MT,width:PW,height:PH,fill:'transparent'});svg.appendChild(ov);
  const tip=document.getElementById('tip'),finePointer=window.matchMedia('(pointer: fine)').matches;
  const readout=document.createElement('div');readout.className='flow-readout analog-readout';
  const visibleEras=focus==='ALL'?eras:eras.filter(e=>e===focus);
  const maxIndex=focus==='ALL'?CAP:Math.min(CAP,Math.max(0,(o[focus]?.length||1)-1));
  let cursorIndex=Math.min(maxIndex,Math.max(0,(o.ai?.length||1)-1));
  const paintCursor=index=>{
    cursorIndex=Math.max(0,Math.min(maxIndex,index));const x=X(cursorIndex);
    xh.setAttribute('x1',x);xh.setAttribute('x2',x);xh.setAttribute('y1',MT);xh.setAttribute('y2',MT+PH);
    eras.forEach((e,i)=>{const value=o[e][cursorIndex];if(value!=null){markers[i].setAttribute('cx',x);markers[i].setAttribute('cy',Y(Math.max(value,60)));markers[i].style.display='';markers[i].style.opacity=String(focus==='ALL'||focus===e?1:.1);}else markers[i].style.display='none';});
    const values=visibleEras.filter(e=>o[e][cursorIndex]!=null);
    readout.innerHTML=`<div class="flow-date"><span>SELECTED MONTH</span><strong>M+${cursorIndex}</strong><small>시작월 = 100 · 로그 비교</small></div>${values.map(e=>`<div><span>${esc(ERA_META[e][0])}</span><strong style="color:${ERA_META[e][1]}">${num(o[e][cursorIndex])}</strong><small>${esc(monthAt(starts[e],cursorIndex))}</small></div>`).join('')}`;
    svg.setAttribute('aria-label',`과거 혁신 사이클 비교, 선택 월 M+${cursorIndex}. 좌우 화살표로 이동`);
  };
  const indexFromPointer=event=>{const rect=svg.getBoundingClientRect(),viewX=(event.clientX-rect.left)*(W/rect.width);
    return Math.max(0,Math.min(maxIndex,Math.round((viewX-ML)/(PW/CAP))));};
  ov.addEventListener('pointermove',event=>{const index=indexFromPointer(event);paintCursor(index);if(finePointer){
    tip.style.display='block';tip.style.left=(event.clientX+14)+'px';tip.style.top=(event.clientY-10)+'px';
    tip.innerHTML=`<b>M+${index} · 시작월 대비</b>`+visibleEras.filter(e=>o[e][index]!=null).map(e=>
      `<span class="tip-series" style="--tip-series:${ERA_META[e][1]}"><i aria-hidden="true"></i><span>${esc(ERA_META[e][0])}<small>${esc(monthAt(starts[e],index))}</small></span><strong>${num(o[e][index])}</strong></span>`).join('');}});
  ov.addEventListener('pointerdown',event=>{paintCursor(indexFromPointer(event));if(!finePointer)tip.style.display='none';svg.focus();});
  ov.addEventListener('pointerleave',()=>{tip.style.display='none';});
  svg.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();paintCursor(cursorIndex+(event.key==='ArrowLeft'?-1:1));}
    else if(event.key==='Home'){event.preventDefault();paintCursor(0);}else if(event.key==='End'){event.preventDefault();paintCursor(maxIndex);}});
  host.replaceChildren(svg,readout);paintCursor(cursorIndex);
}
function flowHorizonEndIndex(sc,horizonDays=126){
  const fullLength=sc.week_dates?.length||sc.weeks?.length||0;if(fullLength<2)return Math.max(0,fullLength-1);
  const tradingDays=sc.quantile_table?.trading_days||[];
  if(horizonDays>=tradingDays.length||!tradingDays.length)return fullLength-1;
  const target=tradingDays[Math.max(0,Math.min(tradingDays.length-1,horizonDays-1))];let end=0;
  sc.week_dates.forEach((day,index)=>{if(day<=target)end=index;});
  return Math.max(1,Math.min(fullLength-1,end));
}
function flowDisplayPath(sc,key){
  const structural=sc?.structural_forecast?.paths?.[key]?.values;
  if(Array.isArray(structural)&&structural.length===sc?.week_dates?.length)return structural;
  return Array.isArray(sc?.paths?.[key]?.values)?sc.paths[key].values:[];
}
function flowYearRange(sc,year){
  const length=sc?.week_dates?.length||sc?.weeks?.length||0;
  const registered=(sc?.structural_forecast?.years||[]).find(row=>Number(row.year)===Number(year));
  if(registered)return {start:Math.max(0,Number(registered.start_index)),end:Math.min(length-1,Number(registered.end_index)),year:Number(year)};
  const indexes=(sc?.week_dates||[]).map((day,index)=>String(day).startsWith(`${year}-`)?index:-1).filter(index=>index>=0);
  if(indexes.length)return {start:indexes[0],end:indexes.at(-1),year:Number(year)};
  return {start:0,end:Math.max(0,length-1),year:Number(String(sc?.asof||'').slice(0,4)||year)};
}
function flowPathStats(values,dates=[]){
  let peak=null,maxDrawdown=0,downWeeks2027=0;
  (values||[]).forEach((raw,index)=>{const value=Number(raw);if(!Number.isFinite(value))return;
    if(peak==null||value>peak)peak=value;else maxDrawdown=Math.max(maxDrawdown,1-value/peak);
    if(index>0&&value<Number(values[index-1])&&String(dates[index]||'').startsWith('2027-'))downWeeks2027+=1;
  });
  return {maxDrawdownPct:Number((maxDrawdown*100).toFixed(1)),downWeeks2027};
}
function flowAxisTickIndexes(length,maxTicks=7){
  if(length<=maxTicks)return Array.from({length},(_,index)=>index);
  return [...new Set(Array.from({length:maxTicks},(_,index)=>Math.round(index*(length-1)/(maxTicks-1))))];
}
function flowEventLayout(events,endIndex,X,minX,maxX,laneCount=5){
  const laneEnds=Array(laneCount).fill(-Infinity);
  return (events||[]).filter(([index])=>index<=endIndex).map(([index,label,meta])=>{
    const eventX=X(index),half=Math.max(30,Math.min(82,String(label).length*6.2/2));
    const labelX=Math.max(minX+half,Math.min(maxX-half,eventX));
    let lane=laneEnds.findIndex(end=>labelX-half>=end+8);
    if(lane<0)lane=laneEnds.indexOf(Math.min(...laneEnds));
    laneEnds[lane]=labelX+half;
    return {index,label,eventX,labelX,lane,meta};
  });
}
function flowCalendarEventLabel(event){
  const parts=String(event.date||'').split('-'),md=parts.length===3?`${Number(parts[1])}/${Number(parts[2])}`:String(event.date||'');
  const title=String(event.title||event.label||'').replace(/\s*\([^)]*추정[^)]*\)\s*/g,' ').trim(),count=Number(event.clusterCount||1);
  if(event.kind==='earnings')return count>1?`${md} 빅테크 실적 ${count}건`:`${md} ${event.ticker||title.split(/\s+/)[0]||'기업'} 실적`;
  if(event.kind==='fomc')return `${md} ${/SEP/i.test(title)?'FOMC·SEP':'FOMC'}`;
  if(event.kind==='cpi')return `${md} CPI`;
  if(event.kind==='nfp')return `${md} 고용`;
  if(event.kind==='gdp'){const stage=title.match(/(속보|[23]차)/)?.[1];return `${md} GDP${stage?` ${stage}`:''}`;}
  return `${md} ${title.slice(0,14)||'주요 일정'}`;
}
function groupFlowCalendarEvents(events){
  const grouped=new Map();(events||[]).forEach((event,eventIndex)=>{const earnings=event.kind==='earnings',key=earnings?`${event.date}|earnings`:`${event.date}|${event.kind}|${eventIndex}`;
    if(!grouped.has(key))grouped.set(key,{...event,clusterCount:1});else grouped.get(key).clusterCount+=1;});
  return [...grouped.values()].sort((a,b)=>String(a.date).localeCompare(String(b.date))||String(a.kind).localeCompare(String(b.kind)));
}
function buildRebasedFlowModel(sc,lookupDate){
  const table=sc?.quantile_table||{},days=Array.isArray(table.trading_days)?table.trading_days:[];
  const startIndex=days.indexOf(lookupDate);
  if(startIndex<0||!Number.isFinite(Number(sc?.anchor))||Number(sc.anchor)<=0)return null;
  const calendarDays=days.slice(startIndex),remaining=Math.max(0,calendarDays.length-1);
  const offsets=[0];for(let offset=5;offset<=remaining;offset+=5)offsets.push(offset);
  if(offsets.at(-1)!==remaining)offsets.push(remaining);
  const quantileKeys=['p10','p25','p50','p75','p90'],series={};
  quantileKeys.forEach(key=>{const values=table.quantiles?.[key]||[],base=Number(values[startIndex]);series[key]=offsets.map(offset=>{
    const value=Number(values[startIndex+offset]);return offset===0?100:Number((value/base*100).toFixed(2));
  });});
  const dates=offsets.map(offset=>calendarDays[offset]);
  const pathDates=Array.isArray(sc.week_dates)?sc.week_dates:[],scenarioSeries={},scenarioBasisDates={};
  const nearestPathIndex=target=>{let nearest=0,best=Infinity;pathDates.forEach((day,index)=>{const distance=Math.abs(Date.parse(day)-Date.parse(target));if(distance<best){best=distance;nearest=index;}});return nearest;};
  ['S1','S2','S3'].forEach(key=>{const path=flowDisplayPath(sc,key);if(!pathDates.length||path.length!==pathDates.length)return;
    const basisIndex=nearestPathIndex(lookupDate),base=Number(path[basisIndex]);if(!Number.isFinite(base)||base<=0)return;
    scenarioBasisDates[key]=pathDates[basisIndex];scenarioSeries[key]=dates.map((day,index)=>{const value=Number(path[nearestPathIndex(day)]);return index===0?100:Number((value/base*100).toFixed(2));});
  });
  const events=(sc.calendar_events||sc.event_calendar||[]).filter(event=>event.date>=lookupDate&&event.date<=dates.at(-1)).map(event=>{
    let nearest=0,best=Infinity;dates.forEach((date,index)=>{const distance=Math.abs(Date.parse(date)-Date.parse(event.date));if(distance<best){best=distance;nearest=index;}});
    return {index:nearest,date:event.date,label:event.title||event.label||event.kind||'',status:event.status||'confirmed',kind:event.kind||event.category||'other'};
  });
  return {lookup_date:lookupDate,asof:sc.asof,remaining_trading_days:remaining,dates,offsets,series,scenario_series:scenarioSeries,scenario_basis_dates:scenarioBasisDates,events};
}
function rebaseRelativeLabel(offset,iso){
  const date=String(iso||'').slice(5).replace('-','/');
  if(offset===0)return `D · ${date}`;
  if(offset<15)return `D+${Math.max(1,Math.round(offset/5))}주 · ${date}`;
  return `D+${Math.max(1,Math.round(offset/21))}개월 · ${date}`;
}
function drawRebasedFlow(host,sc,lookupDate){
  const model=buildRebasedFlowModel(sc,lookupDate);if(!model)return drawFlow(host,sc,'ALL',lookupDate,Number(String(lookupDate).slice(0,4)),false);
  const NS='http://www.w3.org/2000/svg',W=1160,H=610,ML=68,MR=140,MT=145,MB=62;
  const scenarioKeys=['S1','S2','S3'];
  const values=[...['p10','p25','p50','p75','p90'].flatMap(key=>model.series[key]),...scenarioKeys.flatMap(key=>model.scenario_series[key]||[])].filter(Number.isFinite);
  const low=Math.min(...values,100),high=Math.max(...values,100),pad=Math.max(2,(high-low)*.09);
  const Y0=Math.floor((low-pad)/2)*2,Y1=Math.ceil((high+pad)/2)*2,PW=W-ML-MR,PH=H-MT-MB;
  const X=index=>ML+PW*index/Math.max(1,model.dates.length-1),Y=value=>MT+PH*(1-(value-Y0)/(Y1-Y0));
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width','100%');svg.setAttribute('role','img');svg.setAttribute('tabindex','0');
  svg.setAttribute('aria-label',`${sc.asof} 스냅샷의 분위수와 DB 조건부 구조 경로를 ${lookupDate} D=100으로 재기준한 경로, 남은 ${model.remaining_trading_days}거래일`);
  const mk=(tag,attrs)=>{const node=document.createElementNS(NS,tag);for(const key in attrs)node.setAttribute(key,attrs[key]);return node;};
  const tx=(x,y,value,opts={})=>{const node=mk('text',{x,y,fill:opts.fill||'#5f5d57','font-size':opts.fs||12,'text-anchor':opts.anc||'start','font-weight':opts.w||500});node.textContent=value;return node;};
  svg.appendChild(tx(ML,25,'D = 100 · CURRENT SNAPSHOT REINDEXED',{fill:'#174ea6',fs:13,w:800}));
  svg.appendChild(tx(ML,47,`선택일 ${lookupDate} · 마지막 산출일 ${model.dates.at(-1)} · 남은 ${model.remaining_trading_days}거래일 · 선택일 새 전망 아님`,{fill:'#5f6470',fs:12,w:620}));
  let legendX=ML;scenarioKeys.forEach(key=>{svg.appendChild(mk('line',{x1:legendX,y1:72,x2:legendX+18,y2:72,stroke:CHART_COL[key],'stroke-width':3}));svg.appendChild(tx(legendX+24,76,`${key} 구조 경로 ${sc.paths[key].prob}%`,{fill:CHART_LABEL_COL[key],fs:11,w:750}));legendX+=155;});
  svg.appendChild(mk('line',{x1:legendX,y1:72,x2:legendX+18,y2:72,stroke:'#174ea6','stroke-width':2,'stroke-dasharray':'4 3'}));svg.appendChild(tx(legendX+24,76,'분위수 p50 · p10–p90',{fill:'#174ea6',fs:11,w:750}));
  const gridStep=Math.max(2,Math.ceil(((Y1-Y0)/6)/2)*2);for(let value=Math.ceil(Y0/gridStep)*gridStep;value<=Y1;value+=gridStep){svg.appendChild(mk('line',{x1:ML,y1:Y(value),x2:ML+PW,y2:Y(value),stroke:'rgba(17,17,15,.09)','stroke-width':1}));svg.appendChild(tx(ML-10,Y(value)+4,String(value),{anc:'end'}));}
  const band=(upper,lower,fill,opacity)=>{let d='';upper.forEach((value,index)=>d+=(index?'L':'M')+X(index)+','+Y(value)+' ');for(let index=lower.length-1;index>=0;index--)d+='L'+X(index)+','+Y(lower[index])+' ';svg.appendChild(mk('path',{d:d+'Z',fill,opacity}));};
  band(model.series.p90,model.series.p10,'#1f6feb',.10);band(model.series.p75,model.series.p25,'#1f6feb',.18);
  let median='';model.series.p50.forEach((value,index)=>median+=(index?'L':'M')+X(index)+','+Y(value)+' ');svg.appendChild(mk('path',{d:median,fill:'none',stroke:'#174ea6','stroke-width':2,'stroke-linejoin':'round','stroke-dasharray':'4 3'}));
  const rightLabels=[];scenarioKeys.forEach(key=>{const path=model.scenario_series[key]||[];if(path.length!==model.dates.length)return;let d='';path.forEach((value,index)=>d+=(index?'L':'M')+X(index)+','+Y(value)+' ');svg.appendChild(mk('path',{d,fill:'none',stroke:CHART_COL[key],'stroke-width':key==='S1'?3:2.6,'stroke-linejoin':'round'}));
    const endValue=path.at(-1);svg.appendChild(mk('circle',{cx:X(path.length-1),cy:Y(endValue),r:4,fill:CHART_COL[key],stroke:'#fff','stroke-width':1.5}));rightLabels.push({key,y:Y(endValue),text:`${key} ${num(endValue)}`,color:CHART_LABEL_COL[key],opacity:1,weight:780,fontSize:11});});
  resolveEndpointLabels(rightLabels,18,MT+10,MT+PH-10).forEach(item=>{const labelX=ML+PW+18;svg.appendChild(mk('path',{d:`M${ML+PW+4},${item.y} L${ML+PW+10},${item.y} L${labelX-3},${item.labelY}`,fill:'none',stroke:item.color,'stroke-width':1,opacity:.7}));const label=tx(labelX,item.labelY+4,item.text,{fill:item.color,fs:item.fontSize,w:item.weight});label.setAttribute('paint-order','stroke');label.setAttribute('stroke','#fff');label.setAttribute('stroke-width','4');svg.appendChild(label);});
  svg.appendChild(mk('line',{x1:X(0),y1:MT-8,x2:X(0),y2:MT+PH,stroke:'#1f6feb','stroke-width':2,'stroke-dasharray':'5 3'}));svg.appendChild(mk('circle',{cx:X(0),cy:Y(100),r:5,fill:'#1f6feb',stroke:'#fff','stroke-width':2}));svg.appendChild(tx(X(0)+10,Y(100)-9,'D = 100',{fill:'#174ea6',w:800}));
  const rebasedEvents=groupFlowCalendarEvents(model.events).map(event=>[event.index,flowCalendarEventLabel(event),event]);
  flowEventLayout(rebasedEvents,model.dates.length-1,X,ML,ML+PW,3).forEach(({label,eventX,labelX,lane,meta})=>{const labelY=99+lane*14,circleY=labelY+5;
    svg.appendChild(mk('line',{x1:eventX,y1:circleY+3,x2:eventX,y2:MT-4,stroke:'rgba(17,17,15,.2)','stroke-width':1,'stroke-dasharray':meta?.status==='estimated'?'2 4':'none'}));
    if(Math.abs(labelX-eventX)>1)svg.appendChild(mk('line',{x1:labelX,y1:circleY,x2:eventX,y2:circleY,stroke:'rgba(17,17,15,.25)','stroke-width':1}));
    svg.appendChild(mk('circle',{cx:eventX,cy:circleY,r:2.1,fill:'#5f6470'}));const eventText=tx(labelX,labelY,label,{anc:'middle',fill:'#4f4d47',fs:9,w:700});eventText.setAttribute('paint-order','stroke');eventText.setAttribute('stroke','#fff');eventText.setAttribute('stroke-width','3');svg.appendChild(eventText);});
  flowAxisTickIndexes(model.dates.length,6).forEach(index=>{svg.appendChild(mk('line',{x1:X(index),y1:MT+PH,x2:X(index),y2:MT+PH+5,stroke:'rgba(17,17,15,.3)'}));svg.appendChild(tx(X(index),MT+PH+20,rebaseRelativeLabel(model.offsets[index],model.dates[index]),{anc:'middle',fill:index?'#5f5d57':'#174ea6',fs:11,w:index?600:800}));});
  const readout=document.createElement('div');readout.className='flow-readout rebase-readout';readout.style.setProperty('--flow-count','5');const last=model.dates.length-1;
  readout.innerHTML=`<div class="flow-date"><span>REBASED ORIGIN</span><strong>100</strong><small>${lookupDate} · 새 전망 아님</small></div>${scenarioKeys.map(key=>`<div><span>${key} · ${esc(sc.paths[key].label)}</span><strong style="color:${CHART_LABEL_COL[key]}">${num(model.scenario_series[key]?.[last])}</strong><small>${model.dates[last]} · DB 구조 경로</small></div>`).join('')}<div><span>조건부 구간</span><strong>${num(model.series.p10[last])}–${num(model.series.p90[last])}</strong><small>p10–p90 · 각각 D=100</small></div>`;
  host.replaceChildren(svg,readout);
}
function drawFlow(host,sc,focus='ALL',lookupDate=null,displayYear=2026,showSamples=false,showBaseline=true){
  const NS='http://www.w3.org/2000/svg';
  const W=1160,H=670,ML=58,MR=140,MT=176,MB=34,HCH=586;
  const range=flowYearRange(sc,displayYear),startIndex=range.start,endIndex=range.end,n=endIndex-startIndex+1;
  const weeks=sc.weeks.slice(startIndex,endIndex+1),weekDates=(sc.week_dates||[]).slice(startIndex,endIndex+1),riskValues=sc.risk.slice(startIndex,endIndex+1);
  const fanAll=sc.fan?.quantiles||{},fan=Object.fromEntries(Object.entries(fanAll).map(([key,values])=>[key,Array.isArray(values)?values.slice(startIndex,endIndex+1):values]));
  const displayPaths=Object.fromEntries(['S1','S2','S3'].map(key=>[key,flowDisplayPath(sc,key).slice(startIndex,endIndex+1)]));
  const actualMemberPaths=Object.fromEntries(['S1','S2','S3'].map(key=>[key,(sc.paths?.[key]?.actual_member_values||[]).slice(startIndex,endIndex+1)]));
  const baselinePaths=Object.fromEntries(['S1','S2','S3'].map(key=>[key,(sc.paths?.[key]?.values||[]).slice(startIndex,endIndex+1)]));
  const sampleValues=showSamples?['S1','S2','S3'].flatMap(key=>(sc.path_realism?.[key]?.sample_paths||[]).flatMap(row=>(row.values||[]).slice(startIndex,endIndex+1))):[];
  const analogValues=(sc.analog?.values||[]).slice(startIndex,endIndex+1).map(value=>Math.min(Number(value),Number(sc.analog?.clip||value))).filter(Number.isFinite);
  const chartValues=[sc.ath,sc.corr10,...Object.values(displayPaths).flat(),...Object.values(actualMemberPaths).flat(),...(showBaseline?Object.values(baselinePaths).flat():[]),...sampleValues,...analogValues,...(fan.p10||[]),...(fan.p90||[])].filter(Number.isFinite);
  const chartLow=Math.min(...chartValues),chartHigh=Math.max(...chartValues),chartPad=Math.max(500,(chartHigh-chartLow)*.08);
  const Y0=Math.floor((chartLow-chartPad)/500)*500,Y1=Math.ceil((chartHigh+chartPad)/500)*500;
  const PW=W-ML-MR,PH=HCH-MT-MB,X=index=>ML+PW*index/Math.max(1,n-1),Y=value=>MT+PH*(1-(value-Y0)/(Y1-Y0));
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width','100%');
  const horizonLabel=`${range.year}년 ${weekDates[0]}부터 ${weekDates.at(-1)}까지`;
  svg.setAttribute('role','img');svg.setAttribute('tabindex','0');svg.setAttribute('aria-label',`${sc.asof} 현재 기준 ${horizonLabel} DB 조건부 구조 경로와 혁신사이클 참조선. 좌우 화살표로 기준 주차 이동`);
  const mk=(tag,attrs)=>{const node=document.createElementNS(NS,tag);for(const key in attrs)node.setAttribute(key,attrs[key]);return node;};
  const tx=(x,y,value,opts={})=>{const node=mk('text',{x,y,fill:opts.fill||'rgba(17,17,15,.66)','font-size':opts.fs||12,'text-anchor':opts.anc||'start','font-weight':opts.w||400,opacity:opts.opacity??1});node.textContent=value;return node;};
  const gridStep=Math.max(500,Math.ceil(((Y1-Y0)/6)/500)*500);
  for(let value=Math.ceil(Y0/gridStep)*gridStep;value<=Y1;value+=gridStep){svg.appendChild(mk('line',{x1:ML,y1:Y(value),x2:ML+PW,y2:Y(value),stroke:'rgba(17,17,15,.09)','stroke-width':1}));svg.appendChild(tx(ML-8,Y(value)+4,(value/1000)+'k',{anc:'end',fill:'#5f5d57'}));}
  const yearMeta=(sc.structural_forecast?.years||[]).find(row=>Number(row.year)===Number(range.year)),riskWindow=yearMeta?.analog_risk_window;
  if(riskWindow){const nearestPosition=target=>{let found=0,best=Infinity;weekDates.forEach((day,index)=>{const distance=Math.abs(Date.parse(day)-Date.parse(target));if(distance<best){best=distance;found=index;}});return found;};
    const riskStart=nearestPosition(riskWindow.start),riskEnd=nearestPosition(riskWindow.end),left=Math.max(ML,X(riskStart)-8),right=Math.min(ML+PW,X(riskEnd)+8);
    svg.appendChild(mk('rect',{x:left,y:MT,width:Math.max(8,right-left),height:PH,fill:'#c86d1b',opacity:.055,'data-structural-risk-window':range.year}));
    svg.appendChild(tx((left+right)/2,MT+18,`${riskWindow.center_month} 중심 · DB 조정 위험창`,{anc:'middle',fill:'#8a4d13',fs:11,w:780}));}
  svg.appendChild(mk('line',{x1:ML,y1:Y(sc.ath),x2:ML+PW,y2:Y(sc.ath),stroke:'rgba(17,17,15,.3)','stroke-width':1,'stroke-dasharray':'5 4'}));
  svg.appendChild(mk('line',{x1:ML,y1:Y(sc.corr10),x2:ML+PW,y2:Y(sc.corr10),stroke:'rgba(255,128,102,.55)','stroke-width':1,'stroke-dasharray':'5 4'}));
  const calendarInView=(sc.calendar_events||[]).filter(event=>event.date>=weekDates[0]&&event.date<=weekDates.at(-1)).map(event=>{let index=0,best=Infinity;weekDates.forEach((day,position)=>{const distance=Math.abs(Date.parse(day)-Date.parse(event.date));if(distance<best){best=distance;index=position;}});return {...event,index};});
  if(calendarInView.length){const textEvents=groupFlowCalendarEvents(calendarInView).map(event=>[event.index,flowCalendarEventLabel(event),event]);
    flowEventLayout(textEvents,n-1,X,ML,ML+PW,5).forEach(({label,eventX,labelX,lane,meta})=>{const labelY=22+lane*27,circleY=labelY+9;
      svg.appendChild(mk('line',{x1:eventX,y1:circleY+3,x2:eventX,y2:MT-5,stroke:'rgba(17,17,15,.17)','stroke-width':1,'stroke-dasharray':meta?.status==='estimated'?'2 4':'none'}));
      if(Math.abs(labelX-eventX)>1)svg.appendChild(mk('line',{x1:labelX,y1:circleY,x2:eventX,y2:circleY,stroke:'rgba(17,17,15,.28)','stroke-width':1}));
      svg.appendChild(mk('circle',{cx:eventX,cy:circleY,r:2.4,fill:meta?.status==='estimated'?'#8a8174':'#4f4d47'}));const eventText=tx(labelX,labelY,label,{anc:'middle',fill:'#4f4d47',fs:11,w:700});eventText.setAttribute('paint-order','stroke');eventText.setAttribute('stroke','#fff');eventText.setAttribute('stroke-width','4');eventText.setAttribute('stroke-linejoin','round');svg.appendChild(eventText);});}
  else {const fallbackEvents=(sc.events||[]).filter(([index])=>index>=startIndex&&index<=endIndex).map(([index,label,lane])=>[index-startIndex,label,lane]);flowEventLayout(fallbackEvents,n-1,X,ML,ML+PW).forEach(({label,eventX,labelX,lane})=>{const labelY=22+lane*25,circleY=labelY+9;
    svg.appendChild(mk('line',{x1:eventX,y1:MT-5,x2:eventX,y2:MT+PH,stroke:'rgba(17,17,15,.13)','stroke-width':1,'stroke-dasharray':'2 4'}));
    if(Math.abs(labelX-eventX)>1)svg.appendChild(mk('line',{x1:labelX,y1:circleY,x2:eventX,y2:circleY,stroke:'rgba(17,17,15,.28)','stroke-width':1}));
    svg.appendChild(mk('circle',{cx:eventX,cy:circleY,r:2.4,fill:'rgba(17,17,15,.55)'}));svg.appendChild(tx(labelX,labelY,label,{anc:'middle',fill:'#4f4d47',fs:12,w:650}));});}
  if(fan?.p10?.length===n&&fan?.p90?.length===n){
    const band=(upper,lower,fill,opacity)=>{let d='';upper.forEach((value,index)=>d+=(index?'L':'M')+X(index)+','+Y(value)+' ');for(let index=lower.length-1;index>=0;index--)d+='L'+X(index)+','+Y(lower[index])+' ';svg.appendChild(mk('path',{d:d+'Z',fill,opacity}));};
    band(fan.p90,fan.p10,'#ff9d19',focus==='ALL'?.11:.025);if(fan.p25&&fan.p75)band(fan.p75,fan.p25,'#ff9d19',focus==='ALL'?.16:.04);
    if(fan.p50){let median='';fan.p50.forEach((value,index)=>median+=(index?'L':'M')+X(index)+','+Y(value)+' ');svg.appendChild(mk('path',{d:median,fill:'none',stroke:'#9a6700','stroke-width':1.4,'stroke-dasharray':'3 3',opacity:focus==='ALL'?.74:.12}));}
  }
  if(analogValues.length===n){const analogOn=focus==='ALL'||focus==='ANALOG';let analogPath='';analogValues.forEach((value,index)=>analogPath+=(index?'L':'M')+X(index)+','+Y(value)+' ');
    svg.appendChild(mk('path',{d:analogPath,fill:'none',stroke:'#706f68','stroke-width':analogOn?2:1.1,'stroke-dasharray':'6 5','stroke-linejoin':'round',opacity:analogOn?.78:.08,'data-reference-path':'innovation-cycle'}));
    const rawEnd=Number(sc.analog.values[Math.min(endIndex,sc.analog.values.length-1)]),shownEnd=analogValues.at(-1);const label=rawEnd>shownEnd?`혁신사이클 참조 ↗ +${Math.round((rawEnd/sc.anchor-1)*100)}%`:'혁신사이클 참조';
    const analogLabel=tx(X(n-1)-4,Y(shownEnd)-8,label,{anc:'end',fill:'#706f68',fs:11,w:700,opacity:analogOn?1:.1});analogLabel.setAttribute('paint-order','stroke');analogLabel.setAttribute('stroke','#fff');analogLabel.setAttribute('stroke-width','4');svg.appendChild(analogLabel);}
  if(showSamples)['S1','S2','S3'].forEach(key=>{const on=focus==='ALL'||focus===key;(sc.path_realism?.[key]?.sample_paths||[]).forEach((row,sampleIndex)=>{const values=(row.values||[]).slice(startIndex,endIndex+1);if(values.length!==n)return;let d='';values.forEach((value,index)=>d+=(index?'L':'M')+X(index)+','+Y(value)+' ');svg.appendChild(mk('path',{d,fill:'none',stroke:'#5f6470','stroke-width':Number(row.terminal_percentile)===50?1.25:1.0,'stroke-dasharray':sampleIndex===0?'3 3':'7 3',opacity:on?(Number(row.terminal_percentile)===50?.42:.28):.05,'data-sample-path':`${key}-${row.terminal_percentile}`}));});});
  if(showBaseline)['S1','S2','S3'].forEach(key=>{const values=baselinePaths[key],on=focus==='ALL'||focus===key;if(values.length!==n)return;let d='';values.forEach((value,index)=>d+=(index?'L':'M')+X(index)+','+Y(value)+' ');svg.appendChild(mk('path',{d,fill:'none',stroke:'#697078','stroke-width':1.45,'stroke-dasharray':'2 5','stroke-linecap':'round','stroke-linejoin':'round',opacity:on?.62:.08,'data-baseline-path':key}));});
  const visibleScenarioKeys=Number(range.year)>=2027&&sc.three_distinct_2027_paths===false?['S1']:['S1','S2','S3'];
  if(sc.scenario_v5_candidate&&Number(range.year)<2027&&sc.representative_lines_visible!==false)['S1','S2','S3'].forEach(key=>{const values=actualMemberPaths[key],on=focus==='ALL'||focus===key;if(values.length!==n)return;let d='';values.forEach((value,index)=>d+=(index?'L':'M')+X(index)+','+Y(value)+' ');svg.appendChild(mk('path',{d,fill:'none',stroke:CHART_COL[key],'stroke-width':1.15,'stroke-dasharray':'3 5','stroke-linejoin':'round',opacity:on?.55:.06,'data-actual-member':key}));});
  const rightLabels=[];(sc.representative_lines_visible===false?[]:visibleScenarioKeys).forEach(key=>{const path=sc.paths[key],values=displayPaths[key],color=CHART_COL[key],on=focus==='ALL'||focus===key;let d='';values.forEach((value,index)=>d+=(index?'L':'M')+X(index)+','+Y(value)+' ');
    svg.appendChild(mk('path',{d,fill:'none',stroke:color,'stroke-width':on?(key==='S1'?3:2.6):1.2,'stroke-linejoin':'round',opacity:on?1:.1,'data-primary-p50':key}));const endValue=values.at(-1);
    svg.appendChild(mk('circle',{cx:X(n-1),cy:Y(endValue),r:on?4:2.5,fill:color,stroke:'#0b1714','stroke-width':1.5,opacity:on?1:.12}));rightLabels.push({key,y:Y(endValue),text:`${num(endValue)} · ${path.prob}%`,color:CHART_LABEL_COL[key],opacity:on?1:.12,weight:750,fontSize:12});});
  rightLabels.push({key:'ath',y:Y(sc.ath),text:`ATH ${num(sc.ath)}`,color:'rgba(17,17,15,.62)',opacity:1,weight:650,fontSize:11});
  rightLabels.push({key:'corr10',y:Y(sc.corr10),text:`−10% ${num(sc.corr10)}`,color:'#c9002d',opacity:1,weight:650,fontSize:11});
  resolveEndpointLabels(rightLabels,21,MT+10,MT+PH-10).forEach(item=>{const labelX=ML+PW+19;
    svg.appendChild(mk('path',{d:`M${ML+PW+5},${item.y} L${ML+PW+12},${item.y} L${labelX-3},${item.labelY}`,fill:'none',stroke:item.color,'stroke-width':1,opacity:item.opacity*.72}));
    const label=tx(labelX,item.labelY+4,item.text,{fill:item.color,fs:item.fontSize,w:item.weight,opacity:item.opacity});label.setAttribute('paint-order','stroke');label.setAttribute('stroke','#fff');label.setAttribute('stroke-width','4');label.setAttribute('stroke-linejoin','round');svg.appendChild(label);});
  if(lookupDate&&weekDates.length===n&&lookupDate>=weekDates[0]&&lookupDate<=weekDates.at(-1)){let position=0;const next=weekDates.findIndex(day=>day>=lookupDate);
    if(next<0)position=n-1;else if(next===0||weekDates[next]===lookupDate)position=next;else{const left=ForecastLookup.parseIso(weekDates[next-1]),right=ForecastLookup.parseIso(weekDates[next]),target=ForecastLookup.parseIso(lookupDate);position=next-1+(target-left)/(right-left);}
    const markerX=X(position),labelX=Math.max(ML+50,Math.min(ML+PW-50,markerX));svg.appendChild(mk('line',{x1:markerX,y1:MT-4,x2:markerX,y2:MT+PH,stroke:'#1f6feb','stroke-width':2,'stroke-dasharray':'5 3'}));
    svg.appendChild(mk('line',{x1:labelX,y1:164,x2:markerX,y2:MT-5,stroke:'#8bb3e8','stroke-width':1}));svg.appendChild(mk('rect',{x:labelX-48,y:138,width:96,height:26,rx:13,fill:'#eaf2ff',stroke:'#8bb3e8'}));
    svg.appendChild(tx(labelX,155,'조회 · '+lookupDate.slice(5),{anc:'middle',fill:'#174ea6',fs:12,w:750}));svg.appendChild(mk('circle',{cx:markerX,cy:MT-4,r:4,fill:'#1f6feb',stroke:'#fff','stroke-width':1.5}));}
  if(startIndex===0){svg.appendChild(mk('circle',{cx:X(0),cy:Y(sc.anchor),r:4,fill:'#11110f',stroke:'#fff','stroke-width':1.5}));svg.appendChild(tx(X(0)-6,Y(sc.anchor)-10,num(Math.round(sc.anchor)),{fill:'#11110f',w:600}));}
  else ['S1','S2','S3'].forEach((key,labelIndex)=>{svg.appendChild(mk('circle',{cx:X(0),cy:Y(displayPaths[key][0]),r:3.5,fill:CHART_COL[key],stroke:'#fff','stroke-width':1.2}));if(labelIndex===0)svg.appendChild(tx(X(0)+8,MT+38,'연도 시작',{fill:'#5f5d57',fs:11,w:700}));});
  const tickIndexes=flowAxisTickIndexes(n,6);tickIndexes.forEach((index,tickPosition)=>{let label=weeks[index];
    if(tickPosition===0)label=startIndex===0?'현재 · '+label:`${String(range.year).slice(2)}년 시작 · ${label}`;
    svg.appendChild(mk('line',{x1:X(index),y1:MT+PH,x2:X(index),y2:MT+PH+5,stroke:'rgba(17,17,15,.28)'}));svg.appendChild(tx(X(index),MT+PH+18,label,{anc:'middle',fs:12,fill:index?'#5f5d57':'#174c49',w:index?500:750}));});
  const RY=HCH+8,RH=28;svg.appendChild(tx(ML-8,RY+19,'−10%선 누적 터치확률',{anc:'end',fill:'#5f5d57',fs:11}));
  let segmentStart=0;for(let index=1;index<=n;index++){if(index<n&&riskValues[index]===riskValues[segmentStart])continue;const end=index-1,risk=riskValues[segmentStart];
    const left=segmentStart===0?X(0)-2:(X(segmentStart-1)+X(segmentStart))/2,right=end===n-1?X(end)+2:(X(end)+X(end+1))/2,width=Math.max(1,right-left);
    const fill=risk==='고'?'rgba(201,0,45,.92)':(risk==='중'?'rgba(255,157,25,.48)':'rgba(36,125,120,.34)'),textColor=risk==='고'?'#fff':(risk==='중'?'#513300':'#174c49');svg.appendChild(mk('rect',{x:left,y:RY,width,height:RH,fill,stroke:'rgba(17,17,15,.1)'}));
    if(width>=28)svg.appendChild(tx(left+width/2,RY+18,risk,{anc:'middle',fs:12,fill:textColor,w:700}));segmentStart=index;}
  const xh=mk('line',{stroke:'rgba(17,17,15,.44)','stroke-width':1.2,'stroke-dasharray':'4 3',opacity:1});svg.appendChild(xh);
  const cursorMarkers=['S1','S2','S3'].map(key=>{const marker=mk('circle',{r:5.4,fill:CHART_COL[key],stroke:'#fff','stroke-width':2,opacity:sc.representative_lines_visible===false||!visibleScenarioKeys.includes(key)?0:1});svg.appendChild(marker);return marker;});
  const overlay=mk('rect',{x:ML,y:MT,width:PW,height:PH,fill:'transparent'});svg.appendChild(overlay);const tip=document.getElementById('tip'),finePointer=window.matchMedia('(pointer: fine)').matches;
  const readout=document.createElement('div');readout.className='flow-readout';readout.style.setProperty('--flow-count','4');let cursorIndex=0;
  const paintCursor=index=>{cursorIndex=Math.max(0,Math.min(n-1,index));const x=X(cursorIndex),week=weeks[cursorIndex],risk=riskValues[cursorIndex];xh.setAttribute('x1',x);xh.setAttribute('x2',x);xh.setAttribute('y1',MT);xh.setAttribute('y2',MT+PH);
    ['S1','S2','S3'].forEach((key,markerIndex)=>{cursorMarkers[markerIndex].setAttribute('cx',x);cursorMarkers[markerIndex].setAttribute('cy',Y(displayPaths[key][cursorIndex]));});
    readout.innerHTML=`<div class="flow-date"><span>SELECTED WEEK</span><strong>${esc(week)}</strong><small>−10%선 누적 터치확률 ${esc(risk)}</small></div>${visibleScenarioKeys.map(key=>`<div><span>${esc(sc.paths[key].label)}</span><strong style="color:${CHART_LABEL_COL[key]}">${num(displayPaths[key][cursorIndex])}</strong><small>${Number(range.year)>=2027&&sc.three_distinct_2027_paths===false?'common-model continuation':`시나리오 질량 ${sc.paths[key].prob}%`}</small></div>`).join('')}`;svg.setAttribute('aria-label',`${sc.asof} 현재 기준 ${horizonLabel}, 선택 주차 ${week}, −10%선 누적 터치확률 ${risk}. ${sc.continuation_disclosure||''}`);};
  const indexFromPointer=event=>{const rect=svg.getBoundingClientRect(),mouseX=(event.clientX-rect.left)*(W/rect.width);return Math.max(0,Math.min(n-1,Math.round((mouseX-ML)/(PW/Math.max(1,n-1)))));};
  overlay.addEventListener('pointermove',event=>{const index=indexFromPointer(event);paintCursor(index);if(finePointer){tip.style.display='block';tip.style.left=(event.clientX+14)+'px';tip.style.top=(event.clientY-10)+'px';tip.innerHTML=`<b>${weeks[index]}</b> · −10%선 누적 터치확률 ${riskValues[index]}<br>${visibleScenarioKeys.map(key=>`<span style="color:${CHART_COL[key]}">${esc(sc.paths[key].label)} ${num(displayPaths[key][index])}</span>`).join('<br>')}${analogValues[index]!=null?`<br><span style="color:#706f68">혁신사이클 참조 ${num(analogValues[index])} · 확률 아님</span>`:''}`;}});
  overlay.addEventListener('pointerdown',event=>{paintCursor(indexFromPointer(event));if(!finePointer)tip.style.display='none';svg.focus();});overlay.addEventListener('pointerleave',()=>{tip.style.display='none';});
  svg.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();paintCursor(cursorIndex+(event.key==='ArrowLeft'?-1:1));}else if(event.key==='Home'){event.preventDefault();paintCursor(0);}else if(event.key==='End'){event.preventDefault();paintCursor(n-1);}});
  host.replaceChildren(svg,readout);paintCursor(0);
}

// ── 예측 목록 ──
const QUESTION_PRESETS=[
  ['all','전체'],['review','우선 검토'],['moving','확률 이동'],['due','30일 내 판정'],['pinned','MY RADAR']
];
function researchPriority(q){
  const delta=latestDelta(q.id),days=q.deadline?dayDiff(generatedDay(),q.deadline):null;
  const dueScore=days!=null&&days>=0&&days<=30?Math.max(0,360-days*8):0;
  return dueScore+(delta==null?0:Math.abs(delta)*12)+(isQuestionPinned(q.id)?90:0)+(q.status==='active'?20:0);
}
function questionMatchesPreset(q,preset){
  const delta=latestDelta(q.id),days=q.deadline?dayDiff(generatedDay(),q.deadline):null;
  if(preset==='review')return researchPriority(q)>=90;
  if(preset==='moving')return delta!=null&&delta!==0;
  if(preset==='due')return q.status==='active'&&days!=null&&days>=0&&days<=30;
  if(preset==='pinned')return isQuestionPinned(q.id);
  return true;
}
function sortResearchQuestions(rows,sort){
  const direction=(a,b)=>{
    if(sort==='deadline')return String(a.deadline||'9999-12-31').localeCompare(String(b.deadline||'9999-12-31'));
    if(sort==='probability')return (hasNumeric(b.latest_prob)?Number(b.latest_prob):-1)-(hasNumeric(a.latest_prob)?Number(a.latest_prob):-1);
    if(sort==='movement')return Math.abs(latestDelta(b.id)||0)-Math.abs(latestDelta(a.id)||0);
    if(sort==='updated')return String(b.latest_ts||'').localeCompare(String(a.latest_ts||''));
    return researchPriority(b)-researchPriority(a);
  };
  return [...rows].sort((a,b)=>direction(a,b)||String(a.deadline||'').localeCompare(String(b.deadline||''))||a.title.localeCompare(b.title));
}
function renderQuestions(){
  const domains=[...new Set(DATA.questions.map(q=>q.domain))].sort();
  const themes=[...new Set(DATA.questions.flatMap(q=>q.drivers||[]))].sort();
  const saved={...UI_DEFAULTS.questionView,...UI_STATE.questionView};
  if(saved.domain&&!domains.includes(saved.domain))saved.domain='';
  if(saved.driver&&!themes.includes(saved.driver))saved.driver='';
  let activePreset=QUESTION_PRESETS.some(([id])=>id===saved.preset)?saved.preset:'all';
  let activeLayout=['table','cards'].includes(saved.layout)?saved.layout:'table';
  const root=el('<div></div>');
  appendContextTabs(root,'research','questions');
  root.appendChild(el(`<div class="page-heading"><div>
    <p class="eyebrow">예측 목록 · Question Registry</p>
    <h1>예측 질문과 모든 라운드를 탐색합니다</h1>
    <p class="page-lede">기한·임계값·판정기준이 정해진 예측만 등록됩니다. 행을 클릭하면 근거와 회차 이력을 볼 수 있습니다.</p>
  </div><div class="heading-stat" style="min-height:170px;justify-content:flex-end;display:flex;flex-direction:column">
    <span class="micro">등록 질문</span><strong style="color:var(--lime);font-family:var(--mono);font-size:clamp(28px,3vw,46px);margin:11px 0">${DATA.questions.length}</strong>
    <span class="micro" id="qcount">결과에 표시됨</span></div></div>`));
  const researchControls=el(`<div class="research-controls">
    <div class="research-presets" role="group" aria-label="예측 질문 빠른 필터">${QUESTION_PRESETS.map(([id,label])=>`<button type="button" data-question-preset="${id}" aria-pressed="${id===activePreset}">${label}</button>`).join('')}</div>
    <div class="research-display" role="group" aria-label="예측 목록 보기 방식">
      <button type="button" data-question-layout="table" aria-pressed="${activeLayout==='table'}" aria-label="표 보기">▤ <span>TABLE</span></button>
      <button type="button" data-question-layout="cards" aria-pressed="${activeLayout==='cards'}" aria-label="카드 보기">▦ <span>CARDS</span></button>
    </div>
    <label class="research-sort">정렬<select id="fso" aria-label="예측 질문 정렬">
      <option value="priority">검토 우선순위</option><option value="deadline">판정일</option><option value="probability">확률 높은 순</option>
      <option value="movement">변동 큰 순</option><option value="updated">최신 회차</option>
    </select></label>
  </div>`);
  root.appendChild(researchControls);
  const bar=el(`<div class="filter-bar">
    <label class="search-field"><span>⌕</span><input type="text" id="fq" placeholder="질문 검색…" aria-label="질문 검색"></label>
    <label>분야<select id="fd" aria-label="분야"><option value="">전체</option>${domains.map(d=>`<option value="${esc(d)}">${esc(humanDomain(d))}</option>`).join('')}</select></label>
    <label>테마<select id="fdr" aria-label="테마"><option value="">전체</option>${themes.map(d=>`<option value="${esc(d)}">${esc(humanDriver(d))}</option>`).join('')}</select></label>
    <label>상태<select id="fs" aria-label="상태"><option value="">진행+완료</option><option value="active">진행 중</option><option value="resolved">완료</option></select></label>
    <button type="button" class="calendar-action" id="freset">필터 초기화</button>
  </div>`);
  root.appendChild(bar);
  const insights=el('<div class="filter-insights" id="filter-insights" aria-live="polite"></div>');root.appendChild(insights);
  const cont=el('<div class="table-shell question-table-shell"><table id="qtbl"></table></div>');
  const cards=el('<div class="mobile-question-list" id="question-mobile-list" aria-live="polite"></div>');
  root.appendChild(cont);root.appendChild(cards);
  mount(root);
  $('#fd').value=saved.domain;$('#fdr').value=saved.driver;$('#fs').value=saved.status;$('#fso').value=saved.sort;
  const rememberResearchView=()=>{
    UI_STATE.questionView={preset:activePreset,sort:$('#fso').value,layout:activeLayout,domain:$('#fd').value,driver:$('#fdr').value,status:$('#fs').value};
    saveUIState();
  };
  const draw=()=>{
    root.classList.toggle('research-layout-cards',activeLayout==='cards');
    researchControls.querySelectorAll('[data-question-layout]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.questionLayout===activeLayout)));
    const d=$('#fd').value,dr=$('#fdr').value,st=$('#fs').value,q=$('#fq').value.toLowerCase(),sort=$('#fso').value;
    const rows=sortResearchQuestions(DATA.questions.filter(x=>(!d||x.domain===d)&&(!dr||(x.drivers||[]).includes(dr))&&(!st||x.status===st)&&
      (!q||x.title.toLowerCase().includes(q))&&questionMatchesPreset(x,activePreset)),sort);
    const qc=document.getElementById('qcount');if(qc)qc.textContent=`${rows.length}건 표시`;
    const probs=rows.map(x=>x.latest_prob).filter(Number.isFinite),med=median(probs);
    const rising=rows.filter(x=>(latestDelta(x.id)||0)>0).length,falling=rows.filter(x=>(latestDelta(x.id)||0)<0).length;
    const due30=rows.filter(x=>{const n=x.deadline?dayDiff(generatedDay(),x.deadline):null;return n!=null&&n>=0&&n<=30;}).length;
    insights.innerHTML=`<div><span>표시 질문</span><strong>${rows.length}</strong></div><div><span>확률 중앙값</span><strong>${med==null?'—':Math.round(med)+'%'}</strong></div><div><span>상승 / 하락</span><strong>${rising} / ${falling}</strong></div><div><span>30일 내 판정</span><strong>${due30}</strong></div>`;
    $('#qtbl').innerHTML=`<caption class="sr-only">필터를 적용한 예측 질문 목록 ${rows.length}건</caption><thead><tr><th scope="col">예측 질문</th><th scope="col">분야</th><th scope="col">테마</th><th scope="col" class="r">현재 확률</th><th scope="col" class="r">회차</th><th scope="col" class="r">상태</th><th scope="col" class="r">작업</th></tr></thead>
    <tbody>${rows.map(x=>`<tr tabindex="0" data-q="${esc(x.id)}">
      <td><b>${esc(x.title)}</b><small>${esc(x.id)}</small></td><td>${esc(humanDomain(x.domain))}</td>
      <td>${(x.drivers||[]).slice(0,2).map(dv=>`<button type="button" class="tag tag-button" data-filter-driver="${esc(dv)}">${esc(humanDriver(dv))}</button>`).join(' ')||'—'}</td>
      <td class="r"><span class="table-prob">${p1(x.latest_prob)}</span></td>
      <td class="r num">${Number(x.n_rounds)>0?x.n_rounds:'산출 전'}</td>
      <td class="r">${x.resolved?'<span class="status status-resolved">완료</span>':'<span class="status status-active">진행 중</span>'}</td>
      <td><div class="question-actions"><button type="button" class="question-action" data-pin-q="${esc(x.id)}" aria-label="개인 레이더에 고정">☆</button><button type="button" class="question-action compare" data-compare-q="${esc(x.id)}" aria-label="비교 선택" aria-pressed="false">⇄</button></div></td></tr>`).join('')}</tbody>`;
    cards.innerHTML=rows.map(x=>{const delta=latestDelta(x.id),clock=deadlineWindow(x);
      return `<article class="mobile-question-card" data-q="${esc(x.id)}">
        <div class="mobile-question-head"><span>${esc(humanDomain(x.domain))} · ${roundLabel(x.n_rounds)}</span>${x.resolved?'<span class="status status-resolved">완료</span>':'<span class="status status-active">진행 중</span>'}</div>
        <h2>${esc(x.title)}</h2><div class="mobile-question-id">${esc(x.id)}</div>
        <div class="mobile-question-facts">
          <div><span>현재 확률</span><strong>${p1(x.latest_prob)}</strong></div>
          <div><span>직전 대비</span><strong class="${delta>0?'edge-pos':delta<0?'edge-neg':''}">${delta==null?'첫 기준선':`${delta>0?'+':''}${delta}%p`}</strong></div>
          <div><span>판정 시계</span><strong>${esc(clock.short)}</strong></div>
        </div>
        <div class="mobile-question-tags">${(x.drivers||[]).slice(0,3).map(dv=>`<button type="button" class="tag tag-button" data-filter-driver="${esc(dv)}">${esc(humanDriver(dv))}</button>`).join(' ')||'<span class="tag">관찰 변수 없음</span>'}</div>
        <div class="mobile-question-actions"><button type="button" data-pin-q="${esc(x.id)}" aria-label="개인 레이더에 고정">☆</button><button type="button" data-compare-q="${esc(x.id)}" aria-label="비교 선택" aria-pressed="false">⇄</button><a href="#q/${esc(x.id)}">상세 근거 보기</a></div>
      </article>`;}).join('')||'<p class="empty">조건에 맞는 예측 질문이 없습니다.</p>';
    $('#qtbl').querySelectorAll('tr[data-q]').forEach(tr=>{const go=()=>location.hash='#q/'+tr.dataset.q;
      tr.onclick=e=>{if(!e.target.closest('button'))go();};tr.onkeydown=e=>{if(e.key==='Enter'&&e.target===tr)go();};});
    root.querySelectorAll('[data-filter-driver]').forEach(b=>b.onclick=e=>{e.stopPropagation();$('#fdr').value=b.dataset.filterDriver;draw();});
    syncQuestionActions(root);bindQuickPeek(root);
    rememberResearchView();
  };
  ['#fd','#fdr','#fs'].forEach(s=>bar.querySelector(s).onchange=draw);researchControls.querySelector('#fso').onchange=draw;bar.querySelector('#fq').oninput=draw;
  researchControls.querySelectorAll('[data-question-preset]').forEach(button=>button.onclick=()=>{
    activePreset=button.dataset.questionPreset;
    researchControls.querySelectorAll('[data-question-preset]').forEach(x=>x.setAttribute('aria-pressed',String(x===button)));
    draw();
  });
  researchControls.querySelectorAll('[data-question-layout]').forEach(button=>button.onclick=()=>{
    activeLayout=button.dataset.questionLayout;draw();
  });
  draw();
  bar.querySelector('#freset').onclick=()=>{
    ['#fd','#fdr','#fs','#fq'].forEach(s=>bar.querySelector(s).value='');activePreset='all';researchControls.querySelector('#fso').value='priority';
    researchControls.querySelectorAll('[data-question-preset]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.questionPreset==='all')));draw();
  };
}

// ── 예측 비교 작업공간 ──
const COMPARE_COLORS=['#ff4f17','#247d78','#c9002d'];
function renderCompare(arg=''){
  const ids=cleanCompareIds(String(arg||'').split(',').filter(Boolean));
  if(ids.length<2){
    const empty=el('<div><div class="page-heading"><div><p class="eyebrow">예측 비교 · Compare Lab</p><h1>비교할 질문을 두 개 이상 선택하세요</h1><p class="page-lede">예측 목록의 ⇄ 버튼으로 최대 세 개 질문을 선택할 수 있습니다.</p></div></div><p class="empty"><a class="back-button" href="#questions">예측 목록으로 이동</a></p></div>');mount(empty);return;
  }
  setCompareQuestions(ids);const qs=ids.map(id=>DATA.questions.find(q=>q.id===id)).filter(Boolean);
  const root=el('<div></div>');
  appendContextTabs(root,'research','compare');
  root.appendChild(el(`<div class="page-heading"><div><p class="eyebrow">예측 비교 · Compare Lab</p><h1>질문의 확률과 시간 구조를 나란히 봅니다</h1>
    <p class="page-lede">서로 다른 질문의 확률을 합산하지 않고, 변화 방향·판정 시점·회차 이력을 같은 틀에서 비교합니다.</p></div>
    <div class="heading-stat" style="min-height:170px;justify-content:flex-end;display:flex;flex-direction:column"><span class="micro">SELECTED</span><strong style="font-family:var(--mono);font-size:46px;margin:10px 0">${qs.length}</strong><button type="button" class="calendar-action" data-calendar-selected>선택 일정 저장</button></div></div>`));
  const grid=el(`<div class="compare-grid" style="--compare-count:${qs.length}">${qs.map((q,i)=>{const d=latestDelta(q.id),clock=deadlineWindow(q);
    const available=hasNumeric(q.latest_prob);
    return `<article class="compare-card" style="border-top:7px solid ${COMPARE_COLORS[i]}"><header><div><span class="radar-eyebrow">${esc(humanDomain(q.domain))} · ${roundLabel(q.n_rounds)}</span><h2>${esc(q.title)}</h2></div><button type="button" data-remove-compare-page="${esc(q.id)}" aria-label="비교에서 제거">×</button></header>
      <div class="compare-prob${available?'':' is-pending'}">${available?`<strong>${q.latest_prob}</strong><span>%</span>`:'<strong>산출 전</strong>'}</div>
      <div class="compare-facts"><div><span>직전 대비</span><strong class="${d>0?'edge-pos':d<0?'edge-neg':''}">${!available?'비교 이력 없음':d==null?'첫 기준선':`${d>0?'+':''}${d}%p`}</strong></div>
        <div><span>판정 시계</span><strong>${esc(clock.short)}</strong></div><div><span>관찰 변수</span><strong>${esc((q.drivers||[]).slice(0,2).map(humanDriver).join(' · ')||'—')}</strong></div></div>
      <footer><a href="#q/${esc(q.id)}">상세 근거 보기</a><button type="button" data-pin-q="${esc(q.id)}"><span data-pin-icon>☆</span> 레이더</button></footer></article>`;}).join('')}</div>`);
  root.appendChild(grid);
  const chart=el(`<div class="chart-panel analysis-panel"><div class="panel-head"><h2>예측 확률 회차 비교</h2><div class="band-inline">${qs.map((q,i)=>`<span><b style="background:${COMPARE_COLORS[i]}"></b>${esc(q.title.length>24?q.title.slice(0,24)+'…':q.title)}</span>`).join('')}</div></div><div class="chart-wrap"><div id="compare-history" class="compare-history-shell"></div></div><p class="chart-note">차트 위에서 마우스를 움직이거나 좌우 화살표로 날짜를 옮기면, 그 날짜까지 나온 <b>가장 최근 회차</b>를 보여줍니다. 질문끼리 확률을 더하거나 우열을 가리는 화면이 아닙니다.</p></div>`);
  root.appendChild(chart);mount(root);drawCompareHistory($('#compare-history',chart),qs);
  root.querySelectorAll('[data-remove-compare-page]').forEach(b=>b.onclick=()=>{const next=cleanCompareIds().filter(id=>id!==b.dataset.removeComparePage);setCompareQuestions(next);location.hash=next.length>=2?'#compare/'+next.join(','):'#questions';});
  root.querySelector('[data-calendar-selected]').onclick=()=>downloadQuestionCalendar(qs.map(q=>q.id));
}
function drawCompareHistory(host,questions){
  const series=questions.map(q=>({q,values:[...(DATA.forecast_history?.[q.id]||[])].sort((a,b)=>String(a.forecast_ts||'').localeCompare(String(b.forecast_ts||'')))})).filter(x=>x.values.length);
  if(!series.length){host.innerHTML='<p class="empty">비교할 회차 이력이 없습니다.</p>';return;}
  const dates=[...new Set(series.flatMap(s=>s.values.map(v=>(v.forecast_ts||'').slice(0,10))).filter(Boolean))].sort();
  let t0=Date.parse(dates[0]),t1=Date.parse(dates[dates.length-1]);if(t0===t1){t0-=86400000;t1+=86400000;}
  const NS='http://www.w3.org/2000/svg',W=1000,H=300,ML=48,MR=24,MT=24,MB=34,PW=W-ML-MR,PH=H-MT-MB;
  const X=d=>ML+PW*(Date.parse(d)-t0)/(t1-t0),Y=p=>MT+PH*(1-p/100);
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width','100%');svg.setAttribute('role','img');svg.setAttribute('tabindex','0');svg.setAttribute('aria-label','선택한 예측 질문의 회차별 확률 비교. 좌우 화살표로 기준 날짜 이동');
  const mk=(tag,attrs)=>{const node=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,v));return node;};
  const tx=(x,y,value,attrs={})=>{const node=mk('text',{x,y,fill:attrs.fill||'#5f5d57','font-size':attrs.fs||12,'text-anchor':attrs.anc||'start'});node.textContent=value;return node;};
  [0,25,50,75,100].forEach(v=>{svg.appendChild(mk('line',{x1:ML,y1:Y(v),x2:ML+PW,y2:Y(v),stroke:'rgba(17,17,15,.09)'}));svg.appendChild(tx(ML-7,Y(v)+3,v+'%',{anc:'end'}));});
  series.forEach((s,index)=>{let d='';s.values.forEach((v,i)=>{const date=(v.forecast_ts||'').slice(0,10);d+=(i?'L':'M')+X(date)+','+Y(v.probability)+' ';});
    const color=COMPARE_COLORS[index];svg.appendChild(mk('path',{d,fill:'none',stroke:color,'stroke-width':2.6,'stroke-linejoin':'round'}));
    s.values.forEach(v=>{const date=(v.forecast_ts||'').slice(0,10);svg.appendChild(mk('circle',{cx:X(date),cy:Y(v.probability),r:3.4,fill:color,stroke:'#fff','stroke-width':1.4}));});});
  svg.appendChild(tx(ML,MT+PH+20,dates[0],{fill:'rgba(17,17,15,.5)'}));
  if(dates.length>1)svg.appendChild(tx(ML+PW,MT+PH+20,dates[dates.length-1],{anc:'end',fill:'rgba(17,17,15,.5)'}));
  const cursor=mk('line',{x1:X(dates[dates.length-1]),y1:MT,x2:X(dates[dates.length-1]),y2:MT+PH,stroke:'#11110f','stroke-width':1.2,'stroke-dasharray':'4 3'});
  svg.appendChild(cursor);
  const markers=series.map((_,index)=>{const node=mk('circle',{r:5.5,fill:COMPARE_COLORS[index],stroke:'#fff','stroke-width':2});svg.appendChild(node);return node;});
  const overlay=mk('rect',{x:ML,y:MT,width:PW,height:PH,fill:'transparent',style:'cursor:crosshair'});svg.appendChild(overlay);
  const readout=document.createElement('div');readout.className='compare-readout';readout.style.setProperty('--compare-count',series.length);
  const valueAt=(s,date)=>{let value=null;s.values.forEach(v=>{const d=(v.forecast_ts||'').slice(0,10);if(d&&d<=date)value=v;});return value;};
  let cursorIndex=dates.length-1;
  const paintCursor=index=>{
    cursorIndex=Math.max(0,Math.min(dates.length-1,index));const date=dates[cursorIndex],x=X(date);
    cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);
    const values=series.map((s,i)=>{const value=valueAt(s,date);if(value){markers[i].setAttribute('cx',x);markers[i].setAttribute('cy',Y(value.probability));markers[i].style.display='';}else markers[i].style.display='none';return value;});
    readout.innerHTML=`<div class="compare-date"><span>AS OF</span><strong>${esc(date)}</strong></div>${series.map((s,i)=>{const value=values[i],record=(value?.forecast_ts||'').slice(0,10);
      return `<div><span>${esc(s.q.title.length>28?s.q.title.slice(0,28)+'…':s.q.title)}</span><strong style="color:${COMPARE_COLORS[i]}">${value?p1(value.probability):'기록 없음'}</strong><small>${value?`최근 회차 ${esc(record)}`:'선택 날짜 이전 기록 없음'}</small></div>`;}).join('')}`;
    svg.setAttribute('aria-label',`예측 확률 비교, 기준 날짜 ${date}. 좌우 화살표로 이동`);
  };
  const indexFromPointer=event=>{const rect=svg.getBoundingClientRect(),viewX=(event.clientX-rect.left)*(W/rect.width);
    return dates.reduce((best,date,index)=>Math.abs(X(date)-viewX)<Math.abs(X(dates[best])-viewX)?index:best,0);};
  overlay.addEventListener('pointermove',event=>paintCursor(indexFromPointer(event)));
  overlay.addEventListener('pointerdown',event=>{paintCursor(indexFromPointer(event));svg.focus();});
  svg.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();paintCursor(cursorIndex+(event.key==='ArrowLeft'?-1:1));}
    else if(event.key==='Home'){event.preventDefault();paintCursor(0);}else if(event.key==='End'){event.preventDefault();paintCursor(dates.length-1);}});
  host.replaceChildren(svg,readout);paintCursor(cursorIndex);
}

// ── 예측 상세 ──
const BODY_DICTIONARY=[
  '> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).',
  '> **P0 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트 통과 전).',
  '## [4] Premortem — 이 예측이 크게 틀렸다면','## [1] Outside View — base rate','## [2] Inside View — 보정',
  '## [0] 질문 검증','## [3] 분해 트리','## [5] 최종 출력','## [미검증] 항목','## 리서치 구성',
  '| 증거 | 방향 | 조정 |','| 증거 | 방향 | 평가 |','|---|---|---|','- **핵심 근거 3줄**:','- **관찰 지표 2개**:',
  '- **핵심 근거**:','- **관찰 지표**:','P1 참고 의견 — 자금 결정의 단독 근거 아님','P0 참고 의견 — 자금 결정의 단독 근거 아님',
  'P3 게이트 통과 전','참조 클래스:','최종 확률','required_snapshots','NOT FOUND',
  '확률','예측','근거','출처','판정','시나리오','시장','기준','해소','상승','하락','최종','질문','현재','발생','조정','리스크','참조','실적','전망','분기',
  'general(종합) + devil(데블스 애드버킷) 서브에이전트 2개 병렬 — 증거 부록:',
  '증거 부록(`_r1_evidence.md`)','| ↓ | −2%p |','| ↓ | −3%p |','| ↓ | −1%p |','| ↑ | +2%p |',
  'CME FedWatch','- **직전 대비**:','| ↓ | −4%p |','| base rate | 값 |','| ↑ | +1%p |','| ↑ | +3%p |','| ↑ | +4%p |'
];
function decodeForecastBody(text){return BODY_DICTIONARY.reduce((value,phrase,index)=>value.split(String.fromCharCode(0xE000+index)).join(phrase),text||'');}
function signedPoint(value){
  if(!hasNumeric(value))return '기록 없음';
  const rounded=Math.round(Number(value)*10)/10;
  return `${rounded>0?'+':''}${rounded}%p`;
}
function confidenceBand(round){
  return hasNumeric(round?.ci80_lo)&&hasNumeric(round?.ci80_hi)?`${Number(round.ci80_lo)}–${Number(round.ci80_hi)}%`:'기록 없음';
}
function reasoningText(round){
  const text=decodeForecastBody(round?.body).trim();
  if(text)return text;
  return round?.source_uri?'이전 회차 원문은 자기완결 화면의 용량을 위해 생략했습니다. 근거 문서 링크에서 원문을 확인할 수 있습니다.':'이 회차에는 저장된 근거 원문이 없습니다. 확률·신뢰구간·출처 수 등 구조화 기록은 위의 변화 요약에서 확인할 수 있습니다.';
}
function evidenceDeltaMarkup(current,previous){
  const method=current.method||current.model||'기록 없음';
  if(!previous)return `<section class="round-delta baseline" aria-label="첫 예측 회차">
    <div class="round-delta-head"><span>WHAT CHANGED</span><strong>첫 기준선</strong><p>이 회차가 이후 변화를 비교하는 기준입니다.</p></div>
    <div class="round-delta-grid">
      <div><span>예측 확률</span><strong>${p1(current.probability)}</strong><small>최초 기록</small></div>
      <div><span>80% 구간</span><strong>${confidenceBand(current)}</strong><small>현재 범위</small></div>
      <div><span>근거 출처</span><strong>${Number(current.sources_count)||0}</strong><small>등록 출처</small></div>
      <div><span>산출 방법</span><strong>${esc(method)}</strong><small>현재 회차</small></div>
    </div></section>`;
  const delta=Number(current.probability)-Number(previous.probability),magnitude=Math.abs(delta);
  const level=magnitude>=10?'큰 폭 재평가':magnitude>=5?'의미 있는 재평가':magnitude>0?'소폭 조정':'확률 유지';
  const direction=delta>0?'상향':delta<0?'하향':'유지';
  const currentSources=Number(current.sources_count)||0,previousSources=Number(previous.sources_count)||0,sourceDelta=currentSources-previousSources;
  const previousMethod=previous.method||previous.model||'기록 없음',methodChanged=previousMethod!==method;
  const sourceNote=methodChanged?`이전 기록 ${previousSources} · 집계 기준 상이`:`${previousSources} → ${currentSources}${sourceDelta?` · ${sourceDelta>0?'+':''}${sourceDelta}`:' · 유지'}`;
  return `<section class="round-delta${magnitude>=5?' is-material':''}" aria-label="이전 회차 대비 변화">
    <div class="round-delta-head"><span>WHAT CHANGED · R${previous.round} → R${current.round}</span><strong>${level}</strong><p>예측 확률을 ${direction} 조정했습니다. 아래 항목은 저장된 두 회차 기록의 직접 비교입니다.</p></div>
    <div class="round-delta-grid">
      <div><span>확률 변화</span><strong class="${delta>0?'edge-pos':delta<0?'edge-neg':''}">${signedPoint(delta)}</strong><small>${p1(previous.probability)} → ${p1(current.probability)}</small></div>
      <div><span>80% 구간</span><strong>${confidenceBand(current)}</strong><small>이전 ${confidenceBand(previous)}</small></div>
      <div><span>근거 출처</span><strong>${currentSources}</strong><small>${sourceNote}</small></div>
      <div><span>산출 방법</span><strong>${esc(method)}</strong><small>${methodChanged?`이전 ${esc(previousMethod)}`:'이전과 동일'}</small></div>
    </div></section>`;
}
function physicalEventContextMarkup(q){
  const context=q?.proximity_context||{};if(q?.probability_space!=='physical_event'||context.status!=='ok')return '';
  return `<section class="question-proximity" aria-label="사전등록 사건 임계 근접도"><div><span>THRESHOLD CONTEXT · 결합 금지</span><strong>임계까지 ${num(context.threshold_distance_pct)}%</strong></div><div><span>남은 판정 구간</span><strong>${num(context.remaining_trading_sessions)}거래일</strong></div><div><span>${esc(context.label||'무드리프트 기계적 기준')}</span><strong>≈${num(context.driftless_mechanical_touch_pct)}%</strong></div><p>임계 거리와 기간만으로 만든 해석 보조값입니다. 등록된 사건 확률이나 다른 확률공간과 합산하지 않습니다.</p></section>`;
}
function renderDetail(qid){
  const q=DATA.questions.find(x=>x.id===qid);const hist=DATA.forecast_history[qid]||[];const res=DATA.resolutions[qid]||[];
  const root=el('<div></div>');
  appendContextTabs(root,'research','questions');
  if(!q){root.appendChild(el('<p class="empty">해당 예측을 찾을 수 없습니다.</p>'));mount(root);return;}
  const back=el('<a class="back-button" href="#questions">← 예측 목록</a>');root.appendChild(back);
  const latest=hist.length?hist[hist.length-1].probability:(hasNumeric(q.latest_prob)?q.latest_prob:null),available=hasNumeric(latest);
  root.appendChild(el(`<div class="detail-hero">
    <div><h1>${esc(q.title)}</h1>
      <div class="meta">${esc(humanDomain(q.domain))} · ${q.resolved?'완료':'진행 중'} · 기한 ${esc(q.deadline||'수시')}</div>
      <div class="tag-list" style="justify-content:flex-start">${(q.drivers||[]).map(d=>`<span class="tag">${esc(humanDriver(d))}</span>`).join(' ')}</div>
      <div class="detail-actions"><button type="button" data-pin-q="${esc(q.id)}" aria-pressed="false"><span data-pin-icon>☆</span> MY RADAR</button><button type="button" data-compare-q="${esc(q.id)}" aria-pressed="false">⇄ 비교 선택</button>${q.deadline?`<button type="button" data-calendar-q="${esc(q.id)}">CAL 판정일 저장</button>`:''}</div>
    </div>
    <div class="prob-orb${available?'':' is-pending'}" style="--prob:${available?Number(latest):0}"><strong>${available?latest:'산출 전'}</strong>${available?'<span>%</span>':''}<small>최신 예측 확률</small></div>
  </div>`));
  const proximityMarkup=physicalEventContextMarkup(q);if(proximityMarkup)root.appendChild(el(proximityMarkup));
  const chartPanel=el(`<div class="chart-panel analysis-panel"><div class="panel-head"><h2>AI · 모델 · 시장 확률 추이</h2>
    <div class="band-inline"><span><b style="background:#ff4f17"></b>AI 예측</span><span><b style="background:#247d78"></b>모델 앙상블</span><span><b style="background:#706f68"></b>시장 반영</span></div></div>
    <div class="chart-wrap"><div id="hist"></div></div></div>`);
  root.appendChild(chartPanel);
  const layout=el(`<div class="detail-layout">
    <div class="round-sidebar"><p class="eyebrow">회차</p><div id="rnds"></div></div>
    <div class="reasoning-panel">
      <div class="reasoning-top" id="rtop"></div>
      <div class="model-line" id="rmodel"></div>
      <div class="round-delta-slot" id="round-delta"></div>
      <div class="reasoning-compare-tools" id="reason-compare-tools"></div>
      <div class="reasoning-compare" id="reason-compare" hidden></div>
      <pre class="reasoning-body" id="reason"></pre>
    </div></div>`);
  root.appendChild(layout);
  if(res.length){root.appendChild(el(`<div class="resolution-card">
    ${res.map(r=>`<div><span>결과</span><strong class="${r.outcome===1?'':'no'}">${r.outcome===1?'적중':'미발생'}</strong></div>
    <div><span>Brier</span><strong>${Number(r.brier).toFixed(3)}</strong></div>
    <p>예측 확률 ${r.probability}% · 확정일 ${esc(r.resolved_date)} · 0에 가까울수록 정확한 예측입니다.</p>`).join('')}</div>`));}
  mount(root);
  drawHistory($('#hist',chartPanel),hist,DATA.ml_runs.filter(r=>r.question_id===qid),DATA.market_runs.filter(r=>r.question_id===qid));
  const showReason=h=>{
    const roundIndex=hist.findIndex(item=>item===h||(h.forecast_id&&item.forecast_id===h.forecast_id)),previous=roundIndex>0?hist[roundIndex-1]:null;
    $('#rtop',layout).innerHTML=`<div><span>예측 확률</span><strong>${h.probability}%</strong></div>
      <div><span>회차</span><strong>${h.round}R</strong></div>
      <div><span>출처</span><strong>${h.sources_count||0}</strong></div>`;
    $('#rmodel',layout).textContent=`예측일 ${(h.forecast_ts||'').slice(0,10)} · ${h.round}회차 · ${h.method||h.model||'산출 방법 기록 없음'}`;
    $('#round-delta',layout).innerHTML=evidenceDeltaMarkup(h,previous);
    const reason=$('#reason',layout),compare=$('#reason-compare',layout),tools=$('#reason-compare-tools',layout);
    reason.textContent=reasoningText(h);reason.hidden=false;compare.hidden=true;compare.innerHTML='';
    tools.innerHTML=previous?`<button type="button" class="reasoning-compare-toggle" aria-expanded="false">⇄ 이전 회차와 근거 나란히 보기</button>`:'';
    const toggle=tools.querySelector('button');
    if(toggle)toggle.onclick=()=>{
      const open=toggle.getAttribute('aria-expanded')!=='true';toggle.setAttribute('aria-expanded',String(open));
      toggle.textContent=open?'현재 회차만 보기':'⇄ 이전 회차와 근거 나란히 보기';reason.hidden=open;compare.hidden=!open;
      if(open)compare.innerHTML=`<section><header><span>PREVIOUS · R${previous.round}</span><strong>${p1(previous.probability)}</strong></header><pre>${esc(reasoningText(previous))}</pre></section>
        <section><header><span>CURRENT · R${h.round}</span><strong>${p1(h.probability)}</strong></header><pre>${esc(reasoningText(h))}</pre></section>`;
    };
    layout.querySelectorAll('#rnds button').forEach(b=>b.classList.toggle('active',+b.dataset.r===h.round));
  };
  const rn=$('#rnds',layout);
  hist.forEach(h=>{const b=el(`<button type="button" data-r="${h.round}"><span>R${h.round}</span><b>${h.probability}%</b><small>${(h.forecast_ts||'').slice(5,10)}</small></button>`);
    b.onclick=()=>showReason(h);rn.appendChild(b);});
  if(hist.length)showReason(hist[hist.length-1]);
  else{$('#reason',layout).textContent='기록된 회차가 없습니다.';}
}
function drawHistory(host,hist,mlRuns,mktRuns){
  if(!hist.length){host.innerHTML='<span class="chart-note">기록 없음</span>';return;}
  const NS='http://www.w3.org/2000/svg';const W=980,H=250,ML=44,MR=20,MT=18,MB=30,PW=W-ML-MR,PH=H-MT-MB;
  const pts=hist.map(h=>({t:(h.forecast_ts||'').slice(0,10),p:h.probability}));
  const ds=pts.map(p=>p.t).concat(mlRuns.map(m=>m.run_ts.slice(0,10)),mktRuns.map(m=>m.run_ts.slice(0,10)));
  const t0=ds.reduce((a,b)=>a<b?a:b),t1=ds.reduce((a,b)=>a>b?a:b);
  const toX=t=>ML+PW*((Date.parse(t)-Date.parse(t0))/Math.max(1,Date.parse(t1)-Date.parse(t0)));
  const Y=p=>MT+PH*(1-p/100);
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width','100%');
  const mk=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;};
  const tx=(x,y,s,o={})=>{const e=mk('text',{x,y,fill:o.fill||'#5f5d57','font-size':o.fs||12,'text-anchor':o.anc||'start'});e.textContent=s;return e;};
  [0,25,50,75,100].forEach(v=>{svg.appendChild(mk('line',{x1:ML,y1:Y(v),x2:ML+PW,y2:Y(v),stroke:'rgba(17,17,15,.09)'}));svg.appendChild(tx(ML-6,Y(v)+3,v+'%',{anc:'end'}));});
  mlRuns.forEach(m=>svg.appendChild(mk('circle',{cx:toX(m.run_ts.slice(0,10)),cy:Y(Math.round(m.prob*100)),r:3.5,fill:'#247d78',opacity:.7})));
  mktRuns.forEach(m=>svg.appendChild(mk('circle',{cx:toX(m.run_ts.slice(0,10)),cy:Y(Math.round(m.prob*100)),r:3.5,fill:'#706f68',opacity:.75})));
  let d='';pts.forEach((p,i)=>d+=(i?'L':'M')+toX(p.t)+','+Y(p.p)+' ');
  svg.appendChild(mk('path',{d,fill:'none',stroke:'#ff4f17','stroke-width':2.4}));
  pts.forEach(p=>{svg.appendChild(mk('circle',{cx:toX(p.t),cy:Y(p.p),r:4.5,fill:'#ff4f17'}));svg.appendChild(tx(toX(p.t),Y(p.p)-9,p.p+'%',{anc:'middle',fill:'#11110f',fs:12}));});
  host.appendChild(svg);
}

// ── 시점 조회 ──


// ── 적중 이력 ──
function renderDecisionJournal(initial){
  const state=initial&&typeof initial==='object'?initial:{question:initial};
  const selectedQuestion=state.question||null;
  const histories=DATA.forecast_history||{},questions=DATA.questions||[],qMap=Object.fromEntries(questions.map(q=>[q.id,q]));
  const methodEvents=selectedQuestion?[]:(DATA.method_changes||[]).filter(item=>item.kind==='method');
  const events=[];
  Object.entries(histories).forEach(([qid,history])=>{
    if(selectedQuestion&&qid!==selectedQuestion)return;
    const sorted=[...(history||[])].sort((a,b)=>String(a.forecast_ts).localeCompare(String(b.forecast_ts)));
    for(let i=1;i<sorted.length;i++){
      const previous=sorted[i-1],current=sorted[i],delta=Number(current.probability)-Number(previous.probability);
      if(!Number.isFinite(delta)||delta===0)continue;
      events.push({qid,q:qMap[qid],previous,current,delta,date:String(current.forecast_ts||'').slice(0,10)});
    }
  });
  events.sort((a,b)=>b.date.localeCompare(a.date)||Math.abs(b.delta)-Math.abs(a.delta));
  const weekStart=raw=>{const d=new Date(`${raw}T12:00:00Z`),shift=(d.getUTCDay()+6)%7;d.setUTCDate(d.getUTCDate()-shift);return d.toISOString().slice(0,10);};
  const grouped=Object.groupBy?Object.groupBy(events,event=>weekStart(event.date)):events.reduce((out,event)=>{const key=weekStart(event.date);(out[key]||(out[key]=[])).push(event);return out;},{});
  const allDates=[...new Set(Object.values(histories).flat().map(h=>String(h.forecast_ts||'').slice(0,10)).filter(Boolean))].sort();
  const first=allDates[0]||generatedDay(),maxd=allDates.at(-1)||generatedDay();
  const root=el('<div class="decision-journal-page"></div>');
  appendContextTabs(root,'research','journal');
  root.appendChild(el(`<div class="page-heading"><div><p class="eyebrow">DECISION JOURNAL · IMMUTABLE HISTORY</p><h1>예측 변경 일지</h1><p class="page-lede">언제, 무엇이, 왜 바뀌었는지 지우지 않고 쌓는 기록입니다. 과거 판단을 현재 정보로 덮어쓰지 않습니다. 특정 날짜의 미래 분포는 <a href="#future/lookup">미래 탐색의 기간 조회 ↗</a>에서 봅니다.</p></div></div>`));
  root.appendChild(el(`<section class="journal-provenance" aria-label="불변 기록 안내"><div><span>APPEND-ONLY PROVENANCE</span><strong>사후 수정이 불가능한 원본에서 생성됩니다</strong><p>기존 예측은 지우지 않고 새 라운드만 추가합니다. 원본 해시는 원장 감사에서 다시 검증됩니다.</p></div><dl><div><dt>인덱스</dt><dd>${esc((DATA.trust?.index?.head||'검증 대기').slice(0,12))}</dd></div><div><dt>원장 감사</dt><dd>${esc((DATA.trust?.ledger_audit_at||'검증 대기').slice(0,10))}</dd></div></dl></section>`));
  if(methodEvents.length)root.appendChild(el(`<section class="method-change-feed" aria-label="방법론 변경 기록"><p class="eyebrow">METHOD CHANGE</p>${methodEvents.map(item=>{const base=DATA.meta?.public_repository_url||'';const href=item.report&&base?`${base}/blob/main/${item.report}`:'';return `<article><time>${esc(item.date)}</time><div><strong>${esc(item.title)}</strong><p>${esc(item.reason)}</p><small>snapshot ${esc(item.snapshot_id)}</small>${href?`<a href="${esc(href)}" target="_blank" rel="noopener">구현 보고서 ↗</a>`:''}</div></article>`;}).join('')}</section>`));
  const mode=el(`<div class="journal-mode" role="group" aria-label="일지 보기 방식"><button type="button" data-journal-mode="feed" aria-pressed="true">변경 일지</button><button type="button" data-journal-mode="replay" aria-pressed="false">그날로 돌아가기</button></div>`);
  root.appendChild(mode);
  const feed=el(`<section class="journal-feed-panel" data-journal-panel="feed"><div class="journal-feed-intro"><strong>${selectedQuestion?esc(qMap[selectedQuestion]?.title||selectedQuestion):'전체 질문'} · ${events.length}건의 판단 변경</strong><span>주 단위로 묶고 변화 폭이 큰 기록을 먼저 보여줍니다.</span></div><div class="decision-feed" role="feed" aria-label="예측 변경 기록">${events.length?Object.entries(grouped).sort((a,b)=>b[0].localeCompare(a[0])).map(([week,items])=>`<section class="journal-week"><h2>${esc(week)} 주간</h2>${items.map(event=>{const positive=event.delta>0,source=event.current.source_uri?`https://github.com/sung-jinpark/Jin-s-investing-prediction/blob/main/${event.current.source_uri}`:'';return `<article class="journal-event" tabindex="0" aria-label="${esc(event.q?.title||event.qid)} ${positive?'상향':'하향'} ${Math.abs(event.delta)} 퍼센트포인트"><time>${esc(event.date)}</time><div><a class="journal-question" href="#q/${esc(event.qid)}">${esc(event.q?.title||event.qid)}</a><p><span class="journal-prob">${event.previous.probability}%</span><i>→</i><span class="journal-prob">${event.current.probability}%</span><b class="${positive?'edge-pos':'edge-neg'}">${positive?'+':''}${event.delta}%p</b></p>${event.current.change_note?`<blockquote>${esc(event.current.change_note)}</blockquote>`:''}${source?`<a class="journal-source" href="${esc(source)}" target="_blank" rel="noopener">근거 문서 ↗</a>`:''}</div></article>`;}).join('')}</section>`).join(''):'<div class="journal-empty"><strong>표시할 확률 변경이 없습니다.</strong><p>첫 라운드만 있거나 확률이 그대로인 질문은 변경 이벤트로 만들지 않습니다.</p></div>'}</div></section>`);
  const replay=el(`<section class="journal-replay-panel" data-journal-panel="replay" hidden><div class="replay-controls"><label for="journal-date">기준일<input type="date" id="journal-date" min="${first}" max="${maxd}" value="${state.date||maxd}"></label><div class="replay-presets"><button type="button" data-replay-date="${first}">최초 기록</button><button type="button" data-replay-offset="-30">1개월 전</button><button type="button" data-replay-offset="-7">1주 전</button><button type="button" data-replay-date="${maxd}">최신</button></div></div><div id="journal-replay-summary" class="journal-replay-summary"></div><div class="table-shell"><table id="journal-replay-table"></table></div></section>`);
  root.append(feed,replay);mount(root);
  const rowsAt=D=>questions.filter(q=>!selectedQuestion||q.id===selectedQuestion).map(q=>{const hist=(histories[q.id]||[]).filter(h=>String(h.forecast_ts||'').slice(0,10)<=D);if(!hist.length)return null;const then=hist.at(-1),latest=(histories[q.id]||[]).at(-1)||then,ml=(DATA.ml_runs||[]).filter(m=>m.question_id===q.id&&String(m.run_ts||'').slice(0,10)<=D).at(-1),market=(DATA.market_runs||[]).filter(m=>m.question_id===q.id&&String(m.run_ts||'').slice(0,10)<=D).at(-1);return {q,then,latest,ml,market,delta:Number(latest.probability)-Number(then.probability)};}).filter(Boolean);
  const drawReplay=D=>{const rows=rowsAt(D),changed=rows.filter(row=>Math.abs(row.delta)>=1),average=rows.length?rows.reduce((sum,row)=>sum+Math.abs(row.delta),0)/rows.length:0,hasMl=rows.some(row=>row.ml),hasMarket=rows.some(row=>row.market);
    $('#journal-replay-summary',replay).innerHTML=`<strong>${esc(D)} 이후 ${changed.length}개 질문의 판단이 바뀌었습니다.</strong><span>평균 절대 변화 ${average.toFixed(1)}%p · 과거 시점 이후 정보는 당시 값에서 제외했습니다.</span>`;
    $('#journal-replay-table',replay).innerHTML=`<caption class="sr-only">${esc(D)} 당시와 현재 공식 확률 비교</caption><thead><tr><th>질문</th><th class="r">그날의 공식 확률</th>${hasMl?'<th class="r">그날의 모델 참고값</th>':''}${hasMarket?'<th class="r">그날의 시장 참고값</th>':''}<th class="r">현재 공식 확률</th><th class="r">변화</th></tr></thead><tbody>${rows.map(row=>`<tr><td><a href="#q/${esc(row.q.id)}">${esc(row.q.title)}</a></td><td class="r"><span class="table-prob">${row.then.probability}%</span></td>${hasMl?`<td class="r num">${row.ml?pct(row.ml.prob):'—'}</td>`:''}${hasMarket?`<td class="r num">${row.market?pct(row.market.prob):'—'}</td>`:''}<td class="r"><span class="table-prob">${row.latest.probability}%</span></td><td class="r num ${row.delta>0?'edge-pos':row.delta<0?'edge-neg':''}">${row.delta>0?'+':''}${row.delta.toFixed(0)}%p</td></tr>`).join('')}</tbody>`;
  };
  const setMode=next=>{const replayOn=next==='replay';feed.hidden=replayOn;replay.hidden=!replayOn;mode.querySelectorAll('[data-journal-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.journalMode===next)));if(replayOn)drawReplay($('#journal-date',replay).value);};
  mode.querySelectorAll('[data-journal-mode]').forEach(button=>button.onclick=()=>setMode(button.dataset.journalMode));
  $('#journal-date',replay).onchange=event=>{drawReplay(event.target.value);history.replaceState(null,'',`#records/journal/${event.target.value}`);};
  replay.querySelectorAll('[data-replay-date]').forEach(button=>button.onclick=()=>{const value=button.dataset.replayDate;$('#journal-date',replay).value=value;drawReplay(value);});
  replay.querySelectorAll('[data-replay-offset]').forEach(button=>button.onclick=()=>{const d=new Date(`${maxd}T12:00:00Z`);d.setUTCDate(d.getUTCDate()+Number(button.dataset.replayOffset));const value=Math.max(Date.parse(first),d.getTime())===Date.parse(first)?first:d.toISOString().slice(0,10);$('#journal-date',replay).value=value;drawReplay(value);});
  setMode(state.mode==='replay'?'replay':'feed');
}

function renderTrack(initial){
  const trackMode=initial?.trackMode==='performance'?'performance':initial?.trackMode==='operator'?'operator':'trust';
  const c=DATA.calibration,g=c.gate,gv2=c.gate_v2||{},clusters=DATA.clusters||[],unique=gv2.n_events??clusters.length;
  const ai=DATA.ai_regime||{status:'blocked',coverage:0,coverage_threshold:.6},aiCoverage=Number(ai.coverage||0),aiThreshold=Number(ai.coverage_threshold||.6);
  const root=el(`<div class="track-page" data-track-mode="${trackMode}"></div>`);
  if(trackMode==='performance')appendContextTabs(root,'research','performance');
  if(trackMode==='operator')root.appendChild(el(`<section class="trust-readiness" aria-label="AI 자본사이클 준비 상태"><div><span>AI 자본사이클</span><strong>${ai.status==='blocked'||aiCoverage<aiThreshold?'준비 중 · 판정 보류':'검증 지도 준비'}</strong></div><p>확보된 입력 ${Math.round(aiCoverage*100)}% · 자동 복귀 기준 ${Math.round(aiThreshold*100)}% (coverage≥${aiThreshold.toFixed(1)}).</p><a href="#future/ai-regime">상태 상세</a></section>`));
  const heading=trackMode==='performance'?['성과 검증 · Calibration','확정된 질문의 성과를 어떻게 검증하는가','확률과 실제 결과의 간격을 기록합니다. 고유 결과가 충분해지기 전에는 성능 판단을 유보합니다.']:trackMode==='operator'?['OPERATOR MODE · AUDIT','운영 상태와 모델 후보를 점검합니다','일반 화면에서 숨긴 원장 경고·모델 후보·정정 대기를 운영 목적으로 확인합니다.']:['데이터와 신뢰','데이터가 어디서 오고 어떻게 검증되는가','원천 수집부터 시점 검사, 변경 이력, 화면 표시까지 한눈에 확인합니다.'];
  root.appendChild(el(`<div class="page-heading"><div>
    <p class="eyebrow">${heading[0]}</p>
    <h1>${heading[1]}</h1>
    <p class="page-lede">${heading[2]}</p>
  </div></div>`));
  if(trackMode==='operator')root.appendChild(el(`<nav class="trust-mode-note" aria-label="데이터와 신뢰 보기"><span>운영자 모드</span><a href="?mode=standard#trust">일반 화면으로 돌아가기</a></nav>`));
  if(trackMode==='performance'){
  root.appendChild(el(`<div class="track-kpis">
    <div><span>예측 회차</span><strong>${g.n_resolved||0}</strong><small>투명성용 row 표본</small></div>
    <div><span>고유 결과</span><strong>${unique}</strong><small>게이트 후보 표본 단위</small></div>
    <div><span>대표 Brier</span><strong>${gv2.brier!=null?Number(gv2.brier).toFixed(3):'—'}</strong><small>시간가중 · 표시 전용</small></div>
    <div><span>95% CI 상한</span><strong>${gv2.bootstrap?.ci_hi!=null?Number(gv2.bootstrap.ci_hi).toFixed(3):'—'}</strong><small>cluster bootstrap</small></div>
  </div>`));
  if(unique<30)root.appendChild(el(`<p class="status-note">고유 결과 ${unique}건 · 예측 회차 ${g.n_resolved||0}건 — 반복 업데이트를 독립 표본으로 세지 않습니다. 고유 결과 30건 전에는 신뢰도 곡선과 모델 우열 판정을 숨깁니다.</p>`));
  const cv=c.curve||[];
  const grid=el('<div class="section-grid"></div>');
  if(cv.length&&unique>=30){grid.appendChild(el(`<div class="panel"><div class="panel-head"><h2>신뢰도 곡선</h2><span class="vintage-note">예측 대 실제</span></div>
    <div class="table-shell" style="border:0"><table style="min-width:0"><caption class="sr-only">확률대별 예측 캘리브레이션</caption><thead><tr><th scope="col">확률대</th><th scope="col" class="r">표본</th><th scope="col" class="r">평균 예측</th><th scope="col" class="r">실제 적중</th></tr></thead>
    <tbody>${cv.map(r=>`<tr><td class="num">${r.decile*10}–${r.decile*10+10}%</td><td class="r num">${r.n}</td>
      <td class="r num">${pct(r.avg_forecast)}</td><td class="r num">${pct(r.avg_outcome)}</td></tr>`).join('')}</tbody></table></div>
    <p class="chart-note">평균 예측 확률과 실제 적중률이 가까울수록 잘 보정된 예측입니다.</p></div>`));}
  else grid.appendChild(el(`<div class="panel insufficient-panel"><div class="panel-head"><h2>신뢰도 곡선</h2><span class="semantic-state">표본 부족</span></div><p>고유 결과가 30건에 도달하면 reliability curve와 Murphy decomposition을 공개합니다. 현재는 숫자를 과해석하지 않도록 의도적으로 숨겼습니다.</p></div>`));
  const ds=(c.domain_skill||[]).filter(r=>r.n>0);
  if(ds.length){grid.appendChild(el(`<div class="panel"><div class="panel-head"><h2>분야별 정확도</h2><span class="vintage-note">${ds.length}개 분야</span></div>
    <div class="deadline-list" style="border-top:1px solid var(--line)">${ds.map(r=>`<div style="padding:19px 0;display:grid;grid-template-columns:1fr auto;gap:6px;border-bottom:1px solid var(--line)">
      <span style="font-size:13px;font-weight:650">${esc(humanDomain(r.domain))}</span>
      <strong style="font-family:var(--mono);font-size:17px">${r.brier!=null?Number(r.brier).toFixed(3):'—'}</strong>
      <small style="grid-column:1/3;color:var(--muted);font-family:var(--mono);font-size:var(--type-micro)">표본 ${r.n}건</small></div>`).join('')}</div></div>`));}
  if(grid.children.length)root.appendChild(grid);
  }
  if(trackMode!=='performance'){
  const trust=DATA.trust||{sources:[]},arena=DATA.arena||[],corrections=DATA.corrections||[],receipt=(DATA.receipts||[])[0]||{};
  const ledgerRows=trust.ledgers||[],ledgerSummary=trust.ledger_summary||{},sourceRows=trust.sources||[],healthySources=sourceRows.filter(row=>row.status==='ok').length,totalLedgers=Math.max(1,ledgerRows.length);
  const trustTabs=[['status','데이터 상태','01'],['sources','출처와 방법','02'],['audit','감사 기록','03']];
  const trustPanels=Object.fromEntries(trustTabs.map(([key])=>[key,el(`<div id="lab-trust-${key}" role="tabpanel" aria-labelledby="lab-tab-trust-${key}"></div>`)]));
  const trustStatus=trustPanels.status,trustSources=trustPanels.sources,trustAudit=trustPanels.audit;
  trustStatus.appendChild(el(`<section class="trust-overview" aria-labelledby="trust-overview-title"><div class="trust-overview-head"><div><p class="eyebrow">DATA HEALTH</p><h2 id="trust-overview-title">현재 데이터 상태</h2></div><strong class="trust-health-state">${trust.status==='ok'?'정상':'확인 필요'}</strong></div><div class="trust-metrics"><article><span>확인된 출처</span><strong>${num(healthySources)} / ${num(sourceRows.length)}</strong><small>출처·사용 조건 확인</small></article><article><span>축적 중인 원장</span><strong>${num(ledgerSummary.accumulating||0)}</strong><small>새 기록이 들어오는 DB</small></article><article><span>검증 위반</span><strong>${num(ledgerSummary.violation||0)}</strong><small>0이면 구조 검사 통과</small></article><article><span>마지막 검사</span><strong>${esc(String(trust.ledger_audit_at||'미산출').slice(0,10))}</strong><small>전체 원장 기준</small></article></div><div class="trust-state-figure" aria-label="원장 상태 분포"><span class="is-good" style="width:${Number(ledgerSummary.accumulating||0)/totalLedgers*100}%">축적 ${num(ledgerSummary.accumulating||0)}</span><span class="is-warn" style="width:${Number(ledgerSummary.stalled||0)/totalLedgers*100}%">정체 ${num(ledgerSummary.stalled||0)}</span><span class="is-bad" style="width:${Number(ledgerSummary.violation||0)/totalLedgers*100}%">위반 ${num(ledgerSummary.violation||0)}</span><span class="is-plan" style="width:${Number(ledgerSummary.planned||0)/totalLedgers*100}%">계획 ${num(ledgerSummary.planned||0)}</span></div></section>`));
  trustSources.appendChild(el(`<section class="data-pipeline" aria-labelledby="data-pipeline-title"><div class="data-pipeline-head"><p class="eyebrow">DATA PIPELINE</p><h2 id="data-pipeline-title">공개 데이터가 그래프가 되기까지</h2></div><div><article><span>01</span><strong>공개 원천 수집</strong><p>기관 발표값과 시각을 함께 받습니다.</p></article><i aria-hidden="true">→</i><article><span>02</span><strong>시점·형식 검사</strong><p>예측 기준일 이후 정보와 오류값을 차단합니다.</p></article><i aria-hidden="true">→</i><article><span>03</span><strong>변경 이력 보관</strong><p>원본은 덮어쓰지 않고 새 기록으로 남깁니다.</p></article><i aria-hidden="true">→</i><article><span>04</span><strong>화면과 모델 분리</strong><p>참고 통계와 예측 입력을 명확히 구분합니다.</p></article></div></section>`));
  if(ledgerRows.length)trustStatus.appendChild(el(`<details class="trust-ledger-details"><summary><span><strong>원장별 상세 상태</strong><small>${num(ledgerRows.length)}개 DB · 필요할 때 펼쳐보기</small></span><b>위반 ${num(ledgerSummary.violation||0)}</b></summary><div class="ledger-status-grid">${ledgerRows.map(row=>{const points=row.growth_last_30d||[],growth=points.length>1?points.at(-1).count-points[0].count:0;return `<article class="ledger-state-${esc(row.status)}"><div><strong>${esc(row.id)}</strong><span data-badge-type="state">${esc(row.status)}</span></div><p>${row.file_count} files${row.row_count!=null?` · ${row.row_count} rows`:''}</p><small>latest ${esc(row.latest_date||'not started')} · 30일 +${growth}</small>${row.missing_trading_days?.length?`<em>누락 거래일 ${row.missing_trading_days.map(esc).join(', ')}</em>`:''}</article>`;}).join('')}</div><footer>검사 시각 ${esc(trust.ledger_audit_at||'미산출')} · 정체는 갱신 확인, 위반은 구조·불변성 확인이 필요합니다.</footer></details>`));
  if(trackMode==='operator')trustStatus.appendChild(el(`<section class="operator-due" aria-label="운영자 갱신 점검"><div><p class="eyebrow">OPERATOR DUE</p><h2>정체·계획 원장 점검</h2></div><strong>${num((ledgerSummary.stalled||0)+(ledgerSummary.planned||0))}건</strong><p>stalled ${num(ledgerSummary.stalled||0)} · planned ${num(ledgerSummary.planned||0)} · violation ${num(ledgerSummary.violation||0)}</p></section>`));
  const arenaMarkup=trackMode==='operator'?`<div class="panel model-arena"><div class="panel-head"><div><p class="eyebrow">MODEL ARENA</p><h2>기준선과 shadow 후보</h2></div><span class="semantic-state" data-badge-type="state">승격 비활성</span></div>
      <div class="arena-list">${arena.map(m=>`<article><div><strong>${esc(m.name)}</strong><span class="lifecycle ${esc(m.lifecycle)}" data-badge-type="state">${esc(m.lifecycle)}</span></div><p>${esc(m.target)}</p><small>${m.n_insufficient?'paired 표본 부족':esc(JSON.stringify(m.metrics))}</small><details><summary>한계 보기</summary><p>${esc(m.limitations||'미산출')}</p></details></article>`).join('')}</div>
    </div>`:'';
  trustSources.appendChild(el(`<section class="intelligence-stack" aria-label="출처와 방법 상세">
    <details class="trust-center"><summary><span><b>데이터 출처 상세</b><small>제공기관 · 최신 상태 · 이용 조건</small></span><em>${trust.status==='ok'?'정상':'확인 필요'}</em></summary>
      <div class="trust-grid">${(trust.sources||[]).length?(trust.sources||[]).map(s=>`<article><div><strong>${esc(s.name)}</strong><span class="source-state ${s.status}" data-badge-type="state">${esc(s.state_label||s.status)}</span></div><p>${esc(s.provider)} · ${esc(plainTerm(s.vintage_capability))}</p><small>SLA ${s.freshness_sla_hours??'—'}h · ${esc(s.license_status||'미산출')}</small></article>`).join(''):'<p class="empty-copy">등록된 출처가 없습니다.</p>'}</div>
      <div class="index-receipt"><span>데이터 지문</span><code>${esc((trust.index?.source_fingerprint||'미산출').slice(0,16))}</code><small>${esc(trust.index?.branch||'미산출')}</small></div>
    </details>
    <div class="audit-grid">
      <details class="panel semantics-card"><summary>확률 숫자 읽는 법</summary><p>${esc(DATA.probability_semantics?.guardrail||'미산출')}</p>${Object.entries(DATA.probability_semantics?.spaces||{}).map(([space,label])=>`<div><code>${esc(space)}</code><span>${esc(label)}</span></div>`).join('')}</details>
    </div>
  </section>`));
  trustAudit.appendChild(el(`<section class="trust-overview" aria-labelledby="trust-audit-title"><div class="trust-overview-head"><div><p class="eyebrow">AUDIT TRAIL</p><h2 id="trust-audit-title">무엇이 기록으로 남아 있는가</h2></div></div><div class="trust-metrics"><div><span>현재 전망 영수증</span><strong>${receipt.model?'있음':'미산출'}</strong><small>${esc(receipt.model||'모델 미기재')}</small></div><div><span>데이터 정정 이력</span><strong>${num(corrections.length)}건</strong><small>${corrections.length?'아래에서 항목별 사유 확인':'정정 기록 없음'}</small></div><div><span>모델 아레나</span><strong>${trackMode==='operator'?num(arena.length)+'개':'운영자 모드'}</strong><small>${trackMode==='operator'?'승격 비활성 · 후보 비교':'?mode=operator에서 열립니다'}</small></div></div></section>`));
  trustAudit.appendChild(el(`<section class="intelligence-stack" aria-label="감사 기록 상세">
    ${arenaMarkup}
    <div class="audit-grid">
      <details class="panel receipt-card"><summary>현재 전망에 쓰인 데이터</summary><dl><div><dt>모델</dt><dd>${esc(receipt.model||'미산출')}</dd></div><div><dt>데이터</dt><dd>${esc(receipt.dataset||'미산출')}</dd></div><div><dt>출처</dt><dd>${esc(receipt.source||'미산출')}</dd></div><div><dt>버전</dt><dd>${esc((receipt.commit||'미산출').slice(0,12))}</dd></div></dl><p>${esc(receipt.limitation||'미산출')}</p></details>
      <details class="panel correction-card"><summary>데이터 정정 이력 · ${corrections.length}건</summary>${corrections.length?corrections.map(row=>`<article><span class="semantic-state" data-badge-type="state">${esc(row.status==='pending'?'보정 대기':row.status)}</span><strong>${esc(row.field_name)} · ${esc(row.old_value||'미산출')}</strong><p>${esc(row.reason)}</p></article>`).join(''):'<p class="empty-copy">정정 기록이 없습니다.</p>'}</details>
    </div>
  </section>`));
  const trustNav=el(`<nav class="lab-tabs trust-tabs" role="tablist" aria-label="데이터와 신뢰 화면">${trustTabs.map(([key,label,code])=>`<button type="button" id="lab-tab-trust-${key}" role="tab" data-trust-tab="${key}" aria-selected="${key==='status'}" aria-controls="lab-trust-${key}"><span>${code}</span> ${label}</button>`).join('')}</nav>`);
  root.appendChild(trustNav);trustTabs.forEach(([key])=>root.appendChild(trustPanels[key]));
  const activateTrustTab=(key,sync)=>{
    const active=trustPanels[key]?key:'status';
    trustTabs.forEach(([name])=>{trustPanels[name].hidden=name!==active;});
    trustNav.querySelectorAll('[data-trust-tab]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.trustTab===active)));
    if(sync)syncMidHash(active==='status'?'#trust':'#trust/'+active);
  };
  trustNav.querySelectorAll('[data-trust-tab]').forEach(button=>{button.onclick=()=>activateTrustTab(button.dataset.trustTab,true);});
  activateTrustTab(initial?.trustTab||'status',false);
  }
  mount(root);
}

// ── 기간 조회 ──

// ── 시장 지표 바 ──
function renderHeaderStrip(){
  const sc=DATA.scenario||{},ctx=DATA.era_analog?.context||{},rg=ctx.regime||{},br=ctx.breadth||{};
  const anchor=sc.anchor,ath=sc.ath,corr=sc.corr10,vintage=scenarioVintage();
  const items=[];
  if(anchor!=null){const vsAth=ath?((anchor/ath-1)*100):null;
    items.push({k:'NASDAQ 종합',v:num(Math.round(anchor)),sub:vintage.status==='stale'?`보관값 · ${sc.asof}`:`${sc.asof} · 전고점 대비 ${vsAth>=0?'+':''}${vsAth.toFixed(1)}%`,cls:vintage.status==='stale'?'stale':vsAth!=null?(vsAth>=0?'up':'down'):''});}
  if(ath!=null)items.push({k:'전고점 ATH',v:num(Math.round(ath)),sub:'52주 기준'});
  if(corr!=null)items.push({k:'−10% 조정선',v:num(Math.round(corr)),sub:'지지 기준'});
  if(br.pct_above_200dma!=null)items.push({k:'시장 폭',v:br.pct_above_200dma+'%',sub:'200일선 상회'});
  if(rg.recession_flag!=null)items.push({k:'경기 국면',v:rg.recession_flag?'침체':'확장',sub:'NBER 기준',cls:rg.recession_flag?'down':'up'});
  else if(rg.hy_spread_pct!=null)items.push({k:'신용 스프레드',v:rg.hy_spread_pct.toFixed(2)+'%',sub:'HY OAS'});
  const strip=document.getElementById('mktstrip');
  if(!items.length){strip.style.display='none';return;}
  strip.innerHTML=items.map(it=>`<div><span>${esc(it.k)}</span>${it.sub?`<small>${esc(it.sub)}</small>`:''}<strong class="${it.cls||''}">${esc(it.v)}</strong></div>`).join('')+
    '<button type="button" class="command-trigger command-open" aria-label="빠른 이동 열기"><span>빠른 이동</span><kbd>⌘ K</kbd></button>';
  bindCommandTriggers();
  const railIndex=document.getElementById('rail-index');
  if(railIndex&&anchor!=null)railIndex.textContent='NASDAQ '+num(Math.round(anchor));
}

// ── 부트 ──
(async function(){
  DATA=await loadData();
  if(!DATA){app().innerHTML='<div class="loader-wrap">데이터를 불러오지 못했습니다.</div>';return;}
  document.body.classList.toggle('density-compact',UI_STATE.density==='compact');
  document.body.classList.toggle('motion-reduced',UI_STATE.motion==='reduced');
  try{if(sessionStorage.getItem('jin-focus')==='1'){document.body.classList.add('focus-mode');focusExit.hidden=false;}}catch(_){}
  const generated='갱신 '+DATA.meta.generated.replace('T',' ').slice(0,16)+' KST';
  document.getElementById('asof').textContent=generated;
  document.getElementById('drawer-asof').textContent=generated;
  const ph=document.getElementById('phase');if(ph&&DATA.meta.phase)ph.textContent=DATA.meta.phase;
  updateFreshnessBadges();updateUtilityButtons();renderCompareTray();
  renderHeaderStrip();
  route();
  rememberVisitSnapshot();
})();
