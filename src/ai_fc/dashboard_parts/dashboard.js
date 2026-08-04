"use strict";
async function loadData(){
  if(window.__DATA__) return window.__DATA__;
  if(window.__DATA_URL__){ const r = await fetch(window.__DATA_URL__); return await r.json(); }
  return null;
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
function el(html){const t=document.createElement('template');t.innerHTML=html.trim();return t.content.firstChild;}
function mount(root){
  cleanupExperienceLayer();closeQuickPeek();
  root.classList.add('view-enter');app().innerHTML='';app().appendChild(root);
  requestAnimationFrame(()=>{root.classList.add('is-ready');bindDynamicMotion(root);bindExperienceLayer(root);syncQuestionActions(root);});
}
function bindDynamicMotion(root){
  const fine=window.matchMedia('(pointer: fine)').matches;
  if(!motionAllowed()||!fine)return;
  const stage=root.querySelector('.overview-stage'),mosaic=root.querySelector('.signal-mosaic');
  if(stage&&mosaic){
    const cells=[...mosaic.querySelectorAll('i')];let frame=0,lastEvent=null;
    const paint=()=>{
      frame=0;if(!lastEvent)return;const r=stage.getBoundingClientRect();
      const nx=Math.max(-1,Math.min(1,((lastEvent.clientX-r.left)/r.width-.5)*2));
      const ny=Math.max(-1,Math.min(1,((lastEvent.clientY-r.top)/r.height-.5)*2));
      stage.style.setProperty('--pointer-x',((nx+1)*50)+'%');stage.style.setProperty('--pointer-y',((ny+1)*50)+'%');
      cells.forEach((cell,i)=>{const depth=Number(cell.dataset.depth)||5;
        cell.style.transform=`translate3d(${(nx*depth).toFixed(2)}px,${(ny*depth).toFixed(2)}px,0) rotate(${((i%2?1:-1)*nx*depth*.5).toFixed(2)}deg)`;});
    };
    stage.addEventListener('pointermove',e=>{lastEvent=e;if(!frame)frame=requestAnimationFrame(paint);});
    stage.addEventListener('pointerleave',()=>{lastEvent=null;if(frame)cancelAnimationFrame(frame);frame=0;cells.forEach(c=>c.style.transform='');});
  }
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
  mobileMore.setAttribute('aria-expanded',String(open));
  mobileMore.classList.toggle('active',open||['asof','track'].includes(document.body.dataset.view));
  drawer.setAttribute('aria-hidden',String(!open));
  drawerBackdrop.setAttribute('aria-hidden',String(!open));
  document.querySelector('.content-shell').inert=open;
  document.querySelector('.product-rail').inert=open;
  document.querySelector('.mobile-header').inert=open;
  document.getElementById('mobile-bottom-nav').inert=open;
  if(open)menuClose.focus();else if(restoreFocus)(drawerReturnFocus?.focus?drawerReturnFocus:menuOpen).focus();
}
menuOpen.addEventListener('click',()=>setDrawer(true));
mobileMore.addEventListener('click',()=>setDrawer(!document.body.classList.contains('drawer-open')));
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
      .filter(([k,v])=>/^#(overview|flow|ask|questions|asof|track|q\/|compare\/)/.test(k)&&typeof v==='string'&&v.trim())
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
function currentNoteKey(){return location.hash||'#overview';}
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
function vintageReceipt(){
  const v=scenarioVintage();
  const copy=v.status==='stale'
    ?`마지막 유효 시장 기준은 <strong>${esc(v.asof)}</strong>입니다. ${v.fallback?'자동 스냅샷이 없어 감사용 과거 시나리오를 표시합니다.':`확정 거래일 ${v.businessDays}일이 지나 현재 판단에는 사용하지 않습니다.`}`
    :v.status==='aging'
      ?`시장 시나리오는 <strong>${esc(v.asof)}</strong> 확정 종가 기준입니다. 다음 자동 갱신 전까지 최신 종가와 차이가 날 수 있습니다.`
      :`시장 시나리오는 <strong>${esc(v.asof)}</strong> 확정 종가로 자동 생성됐습니다. 질문별 LLM 확률과는 분리된 모델 경로입니다.`;
  return `<div class="data-vintage is-${v.status}" role="${v.status==='stale'?'alert':'note'}"><span>SCENARIO VINTAGE</span><p>${copy}</p><b>${v.status.toUpperCase()}</b></div>`;
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
function changeRadarData(){
  const today=generatedDay(),items=(DATA?.questions||[]).filter(q=>q.status==='active').map(q=>{
    const hist=DATA.forecast_history?.[q.id]||[],latest=hist[hist.length-1],prev=hist[hist.length-2];
    const delta=latest&&prev?latest.probability-prev.probability:null,days=q.deadline?dayDiff(today,q.deadline):null;
    return {q,delta,days,latest:latest?.probability??q.latest_prob,newRound:hist.length===1};
  });
  const moves=items.filter(x=>x.delta!=null&&x.delta!==0).sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta));
  return {
    moves,newItems:items.filter(x=>x.newRound),
    rising:moves.filter(x=>x.delta>0).length,falling:moves.filter(x=>x.delta<0).length,
    due:items.filter(x=>x.days!=null&&x.days>=0&&x.days<=14).sort((a,b)=>a.days-b.days)
  };
}
function changeRadarPanel(){
  const r=changeRadarData(),items=r.moves.slice(0,4);
  const lead=items[0],headline=lead?`${lead.q.title} ${lead.delta>0?'상승':'하락'}`:'큰 확률 변화 없음';
  return el(`<section class="change-radar" id="change-radar" aria-labelledby="change-radar-title">
    <div class="radar-copy"><span class="radar-eyebrow">WHAT CHANGED · LATEST ROUNDS</span><h2 id="change-radar-title">${esc(headline)}</h2>
      <p>직전 예측 회차와 최신 회차를 비교한 변화입니다. 새로운 예측을 만들지 않고 기존 기록의 이동만 보여줍니다.</p>
      <div class="radar-stats"><div><span>상승</span><strong class="up">${r.rising}</strong></div><div><span>하락</span><strong class="down">${r.falling}</strong></div><div><span>14일 내 판정</span><strong>${r.due.length}</strong></div></div>
    </div><div class="radar-list">${items.length?items.map(x=>`<button type="button" class="radar-item" data-open-q="${esc(x.q.id)}">
      <i class="${x.delta>0?'up':'down'}">${x.delta>0?'+':''}${x.delta}%p</i><span>${esc(x.q.title)}<small>${esc(humanDomain(x.q.domain))} · ${x.days==null?'수시 판정':x.days<0?'판정 시점 경과':`D-${x.days}`}</small></span><strong>${p1(x.latest)}</strong></button>`).join(''):
      '<p class="empty">직전 회차 대비 변한 활성 질문이 없습니다.</p>'}</div></section>`);
}
function isQuestionPinned(qid){return UI_STATE.pins.some(x=>x.hash==='#q/'+qid);}
function toggleQuestionPin(qid){
  const q=DATA?.questions?.find(x=>x.id===qid);if(!q)return;
  const hash='#q/'+qid,on=isQuestionPinned(qid),d={hash,title:q.title,type:'question'};
  UI_STATE.pins=on?UI_STATE.pins.filter(x=>x.hash!==hash):[d,...UI_STATE.pins.filter(x=>x.hash!==hash&&descriptorExists(x))].slice(0,8);
  saveUIState();syncQuestionActions();renderCompareTray();
  const old=document.getElementById('my-radar');if(old)old.replaceWith(myRadarPanel());
  showToast(on?'개인 레이더에서 제거했습니다.':'개인 레이더에 추가했습니다.');
  if(!commandLayer.hidden)renderCommandResults(commandInput.value);
}
function myRadarQuestions(){
  return UI_STATE.pins.filter(x=>x.type==='question').map(x=>DATA?.questions?.find(q=>'#q/'+q.id===x.hash)).filter(Boolean);
}
function myRadarPanel(){
  const qs=myRadarQuestions();
  return el(`<section class="my-radar" id="my-radar" aria-labelledby="my-radar-title"><div class="panel-head"><div><h2 id="my-radar-title">MY RADAR</h2><p>이 기기에 고정한 질문을 빠르게 다시 봅니다.</p></div><a class="text-button" href="#questions">질문 찾기</a></div>
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
function decisionQueueCard(items){
  const visitLabel=VISIT_SEEN_AT?'LAST VISIT 이후':'LATEST ROUNDS';
  return `<aside class="decision-queue-card" aria-labelledby="decision-queue-title">
    <div class="decision-queue-head"><div><span>${visitLabel}</span><h2 id="decision-queue-title">지금 다시 볼 질문</h2><small>변화 · 판정 임박 · MY RADAR</small></div><b>${items.length}</b></div>
    ${items.length?`<div class="decision-queue-items">${items.map(x=>`<button type="button" class="decision-queue-item" data-open-q="${esc(x.q.id)}">
      <span>${esc(x.q.title)}<small>${esc(x.reasons.join(' · '))}</small></span><strong class="${hasNumeric(x.q.latest_prob)?'':'pending-value'}">${p1(x.q.latest_prob)}</strong></button>`).join('')}</div>`:
      '<p class="decision-queue-empty">새로 확인할 큰 변화나 임박한 판정이 없습니다.</p>'}
  </aside>`;
}
function linkedSignalStrip(upProb,decisionItems){
  const pins=myRadarQuestions().length;
  const valid=Number.isFinite(upProb);
  const signals=[
    ['market','시장 상승 경로',valid?upProb+'%':'STALE','var(--orange)',valid?'연말 시나리오의 상승 두 경로 합계입니다. 질문별 확률과는 합산하지 않습니다.':'시나리오 기준일이 오래되어 현재 신호로 사용하지 않습니다. 시장 맵에서 마지막 유효 스냅샷은 확인할 수 있습니다.'],
    ['changed','확률 이동',decisionItems.filter(x=>x.signals.includes('changed')).length,'var(--crimson)','직전 회차보다 움직인 질문만 강조합니다. 변화 폭은 방향 신호가 아니라 재검토 신호입니다.'],
    ['due','14일 내 판정',decisionItems.filter(x=>x.signals.includes('due')).length,'var(--amber)','14일 안에 결과를 확인할 질문만 강조합니다. 판정 기준과 출처는 상세 화면에서 확인할 수 있습니다.'],
    ['pinned','MY RADAR',pins,'var(--teal)',pins?'이 기기에 고정한 질문만 강조합니다. 개인 작업공간 정보는 외부로 전송되지 않습니다.':'아직 고정한 질문이 없습니다. 카드의 ☆ 버튼으로 개인 레이더를 만들 수 있습니다.']
  ];
  return `<div class="linked-signal-console">
    <div class="linked-signal-strip" role="group" aria-label="홈 질문 강조 기준">${signals.map(([id,label,value,color,copy],index)=>`<button type="button" class="linked-signal" data-home-signal="${id}" data-signal-label="${esc(label)}" data-signal-copy="${esc(copy)}" aria-pressed="${index===0}" style="--signal-color:${color}">
      <span><i></i>${label}</span><strong>${value}</strong></button>`).join('')}</div>
    <div class="signal-lens-readout" aria-live="polite"><span>ACTIVE LENS</span><strong>${signals[0][1]}</strong><p>${signals[0][4]}</p></div>
  </div>`;
}
function homeFeatureQuestions(decisionItems){
  const chosen=decisionItems.map(x=>x.q).filter(q=>hasNumeric(q.latest_prob)),fallback=featureQs();
  const available=(DATA?.questions||[]).filter(q=>q.status==='active'&&hasNumeric(q.latest_prob));
  return [...new Map([...chosen,...fallback,...available].map(q=>[q.id,q])).values()].slice(0,3);
}
function bindHomeSignals(root){
  const controls=[...root.querySelectorAll('[data-home-signal]')],cards=[...root.querySelectorAll('[data-home-signals]')];
  controls.forEach(control=>control.addEventListener('click',()=>{
    const signal=control.dataset.homeSignal;
    controls.forEach(x=>x.setAttribute('aria-pressed',String(x===control)));
    cards.forEach(card=>{
      const match=signal==='market'||String(card.dataset.homeSignals||'').split(' ').includes(signal);
      card.classList.toggle('is-signal-match',signal!=='market'&&match);
      card.classList.toggle('is-signal-muted',!match);
    });
    const readout=root.querySelector('.signal-lens-readout');
    if(readout)readout.innerHTML=`<span>ACTIVE LENS</span><strong>${esc(control.dataset.signalLabel)}</strong><p>${esc(control.dataset.signalCopy)}</p>`;
  }));
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
  setCompareQuestions(on?ids.filter(id=>id!==qid):[...ids,qid]);
  showToast(on?'비교 선택에서 제외했습니다.':'비교 선택에 추가했습니다.');
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
  compareTray.hidden=!ids.length;
  const collapsed=location.hash.startsWith('#compare/')||UI_STATE.compareCollapsed;
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
  const events=qs.map(q=>`BEGIN:VEVENT\r\nUID:${icsEscape(q.id)}@jin-investing\r\nDTSTAMP:${stamp}\r\nDTSTART;VALUE=DATE:${q.deadline.replaceAll('-','')}\r\nDTEND;VALUE=DATE:${addIsoDays(q.deadline,1).replaceAll('-','')}\r\nSUMMARY:${icsEscape('[예측 판정] '+q.title)}\r\nDESCRIPTION:${icsEscape(`현재 확률 ${p1(q.latest_prob)} · ${humanDomain(q.domain)} · ${roundLabel(q.n_rounds)}`)}\r\nURL:${icsEscape(base+'#q/'+q.id)}\r\nEND:VEVENT`).join('\r\n');
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
  const hash=location.hash||'#overview';
  if(hash.startsWith('#q/')){
    const id=hash.slice(3),q=DATA?.questions?.find(x=>x.id===id);
    return q?{hash,title:q.title,type:'question'}:null;
  }
  if(hash.startsWith('#compare/'))return {hash,title:'예측 질문 비교',type:'route'};
  const r=COMMAND_ROUTES.find(x=>x.hash===hash);
  return r?{hash,title:r.title,type:'route'}:null;
}
function descriptorExists(item){
  if(!item?.hash)return false;
  if(item.hash.startsWith('#q/'))return !!DATA?.questions?.some(q=>'#q/'+q.id===item.hash);
  if(item.hash.startsWith('#compare/'))return item.hash.slice(9).split(',').filter(id=>DATA?.questions?.some(q=>q.id===id)).length>=2;
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
  if(url.href.length>200){url.hash='#overview';}
  return url.href.slice(0,200);
}
function honestSharePayload(){
  const descriptor=currentDescriptor(),screenTitle=document.querySelector('main h1')?.textContent.trim()||descriptor?.title||document.title;
  const asof=DATA?.scenario?.asof||String(DATA?.meta?.generated||'').slice(0,10)||'등록 스냅샷';
  const primary=document.querySelector('.lookup-metrics .lookup-primary strong')?.textContent.trim(),median=document.querySelector('.lookup-metrics>div:nth-child(2) strong')?.textContent.trim();
  const distribution=primary?`10–90% 구간 ${primary}${median?` · 중앙값 ${median}`:''} (모델 조건부)\n`:'';
  const url=canonicalShareUrl();
  return {title:`${screenTitle} — Jin's Investing Prediction`,url,text:`${distribution}${screenTitle} — Jin's Investing Prediction\n시장 기준 ${asof} · 조건부 시나리오이며 목표가·투자자문이 아닙니다.\n${url}`};
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
      '<button type="button" data-util-route="#questions">고정한 질문이 없습니다<span>＋</span></button>'}</div></section>
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
  const q=e.target.closest('[data-open-q]');if(q){setUtility(false,false);location.hash='#q/'+q.dataset.openQ;return;}
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
  const open=e.target.closest('[data-open-q]');if(open){e.preventDefault();location.hash='#q/'+open.dataset.openQ;return;}
  const pin=e.target.closest('[data-pin-q]');if(pin){e.preventDefault();e.stopPropagation();toggleQuestionPin(pin.dataset.pinQ);return;}
  const compare=e.target.closest('[data-compare-q]');if(compare){e.preventDefault();e.stopPropagation();toggleCompareQuestion(compare.dataset.compareQ);return;}
  const calendar=e.target.closest('[data-calendar-q]');if(calendar){e.preventDefault();e.stopPropagation();downloadQuestionCalendar([calendar.dataset.calendarQ]);return;}
  if(e.target.closest('[data-calendar-all]')){e.preventDefault();downloadQuestionCalendar();return;}
});
compareItems.addEventListener('click',e=>{const b=e.target.closest('[data-remove-compare]');if(b)toggleCompareQuestion(b.dataset.removeCompare);});
compareClear.addEventListener('click',()=>setCompareQuestions([]));
compareOpen.addEventListener('click',()=>{const ids=cleanCompareIds();if(ids.length>=2)location.hash='#compare/'+ids.join(',');});
compareToggle.addEventListener('click',toggleCompareTray);
document.getElementById('briefing-scrim').addEventListener('click',()=>setBriefing(false));
briefingClose.addEventListener('click',()=>setBriefing(false));
briefingPrev.addEventListener('click',()=>stepBriefing(-1));briefingNext.addEventListener('click',()=>stepBriefing(1));
briefingContent.addEventListener('click',e=>{const b=e.target.closest('[data-brief-q]');if(!b)return;setBriefing(false,false);location.hash='#q/'+b.dataset.briefQ;});

// keyboard-first quick navigation
const commandLayer=document.getElementById('command-layer'),commandInput=document.getElementById('command-input');
const commandResults=document.getElementById('command-results'),commandScrim=document.getElementById('command-scrim');
let commandReturnFocus=null;
const COMMAND_ROUTES=[
  {hash:'#overview',code:'01',title:'오늘의 판단',hint:'시장 판단과 핵심 예측'},
  {hash:'#flow',code:'02',title:'시장 맵',hint:'시나리오 경로와 위험 구간'},
  {hash:'#questions',code:'03',title:'예측 연구',hint:'모든 질문과 라운드'},
  {hash:'#ask',code:'04A',title:'기간 조회',hint:'시점 리플레이의 기간별 전망'},
  {hash:'#asof',code:'04B',title:'예측 변경 일지',hint:'변경 근거와 과거 시점 비교'},
  {hash:'#track',code:'05',title:'트랙레코드',hint:'Brier와 캘리브레이션'}
];
function commandCatalog(){
  const actions=[
    {id:'briefing',code:'B',title:'3단계 시장 브리핑',hint:'현재 데이터를 큰 장면으로 빠르게 읽기',group:'작업',search:'briefing tour story 브리핑',run:()=>setBriefing(true)},
    {id:'pin-current',code:isCurrentPinned()?'★':'☆',title:isCurrentPinned()?'현재 화면 고정 해제':'현재 화면 고정',hint:'브라우저에 즐겨찾기 저장',group:'작업',search:'pin favorite 고정',run:toggleCurrentPin},
    {id:'share-current',code:'↗',title:'현재 화면 공유',hint:'기기 공유 또는 링크 복사',group:'작업',search:'share copy link 공유',run:()=>shareCurrentView(true)},
    ...(cleanCompareIds().length>=2?[{id:'compare-selected',code:'⇄',title:'선택한 예측 비교',hint:`${cleanCompareIds().length}개 질문 나란히 보기`,group:'작업',search:'compare 비교',run:()=>location.hash='#compare/'+cleanCompareIds().join(',')}]:[]),
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
  const qs=(DATA?.questions||[]).map(q=>({id:'q-'+q.id,hash:'#q/'+q.id,code:(hasNumeric(q.latest_prob)?q.latest_prob+'%':'대기'),title:q.title,hint:`${humanDomain(q.domain)} · ${q.status==='active'?'진행 중':'완료'}`,group:'예측 질문',search:[q.title,q.id,q.domain,humanDomain(q.domain),...(q.drivers||[]),(q.drivers||[]).map(humanDriver)].join(' ').toLowerCase()}));
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
function miniSparkline(q,i){
  let values=(DATA.forecast_history[q.id]||[]).map(h=>Number(h.probability)).filter(Number.isFinite);
  if(!values.length&&q.latest_prob!=null)values=[Number(q.latest_prob)];
  if(values.length===1)values=[values[0],values[0]];
  if(!values.length)values=[0,0];
  const W=180,H=34,P=3,min=Math.min(...values),max=Math.max(...values),span=Math.max(8,max-min);
  const pts=values.map((v,j)=>`${P+(W-P*2)*(j/Math.max(1,values.length-1))},${P+(H-P*2)*(1-(v-(min-span*.18))/(span*1.36))}`);
  const line='M'+pts.join(' L'),last=pts[pts.length-1].split(','),gid='spark-'+String(q.id).replace(/[^a-z0-9]/gi,'-');
  const col=[CHART_COL.S1,CHART_COL.S2,'#706f68'][i%3];
  return `<div class="card-spark" aria-label="예측 회차 추이"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop stop-color="${col}" stop-opacity=".2"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
    <path d="${line} L${last[0]},${H} L${P},${H} Z" fill="url(#${gid})"/><path d="${line}" fill="none" stroke="${col}" stroke-width="1.7" vector-effect="non-scaling-stroke"/>
    <circle cx="${last[0]}" cy="${last[1]}" r="2.6" fill="${col}"/></svg><span>${values.length>2?'HISTORY':'LATEST'}</span></div>`;
}
function signalMosaic(prob){
  const safe=Math.max(0,Math.min(100,Number(prob)||0)),active=Math.round(safe/100*16);
  const cells=Array.from({length:16},(_,i)=>{
    const depth=4+(i%4)*3+(Math.floor(i/4)%2)*2;
    return `<i class="${i<active?'is-on':''}" data-depth="${depth}" style="opacity:${i<active?1:.38}"></i>`;
  }).join('');
  return `<div class="signal-mosaic" role="img" aria-label="상승 경로 신호 ${safe}%">${cells}<b>${safe}<small>%</small></b></div>`;
}

const VIEWS={overview:renderOverview,flow:renderFlow,ask:renderAsk,questions:renderQuestions,asof:renderAsofTimeMachine,track:renderTrack,q:renderDetail,compare:renderCompare};
function contextTabs(group,current){
  const groups={
    research:[['questions','질문 목록'],['compare','비교 작업공간']],
    replay:[['ask','기간 조회'],['asof','AS-OF 타임머신']],
    track:[['track','요약과 Calibration']]
  };
  const items=(groups[group]||[]).filter(([id])=>id!=='compare'||cleanCompareIds().length>=2);
  if(items.length<2)return '';
  return `<nav class="context-tabs" aria-label="${group==='replay'?'시점 리플레이':'예측 연구'} 세부 화면">${items.map(([id,label])=>{const href=id==='compare'?'#compare/'+cleanCompareIds().join(','):'#'+id;
    return `<a href="${href}" ${id===current?'aria-current="page"':''}>${label}</a>`;}).join('')}</nav>`;
}
function appendContextTabs(root,group,current){const html=contextTabs(group,current);if(html)root.appendChild(el(html));}
function route(){
  const rawHash=location.hash||'#overview',lookupMatch=rawHash.match(/^#lookup=(\d{4}-\d{2}-\d{2})$/),asofMatch=rawHash.match(/^#asof=(\d{4}-\d{2}-\d{2})$/),labParams=rawHash.startsWith('#lab=')?new URLSearchParams(rawHash.slice(1)):null;
  const h=lookupMatch||labParams?'flow':(asofMatch?'asof':rawHash.slice(1));const [v,pathArg]=h.split('/');const arg=lookupMatch?{lookup:lookupMatch[1]}:(asofMatch?{mode:'replay',date:asofMatch[1]}:(labParams?{lab:labParams.get('lab'),scenario:labParams.get('scenario')}:pathArg));
  closeQuickPeek();if(!briefingLayer.hidden)setBriefing(false,false);if(!shareLayer.hidden)setShare(false,false);
  const navView=(v==='q'||v==='compare')?'questions':(v==='ask'?'asof':v);
  document.body.dataset.view=navView;
  document.querySelectorAll('.view-nav a[data-v]').forEach(a=>{const on=a.dataset.v===navView;a.classList.toggle('active',on);
    if(on)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  document.querySelectorAll('.mobile-bottom-nav a[data-v]').forEach(a=>{const on=a.dataset.v===navView;a.classList.toggle('active',on);
    if(on)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  mobileMore.classList.toggle('active',['asof','track'].includes(navView));
  (VIEWS[v]||renderOverview)(arg);
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
  const m=DATA.meta,sc=DATA.scenario;
  const upProb=sc.paths.S1.prob+sc.paths.S2.prob, rangeProb=sc.paths.S3.prob;
  const vintage=scenarioVintage();
  const thesis=vintage.status==='stale'
    ?{lead:'시장 시나리오 갱신이 필요합니다.',accent:`마지막 유효 기준은 ${vintage.asof}입니다.`}
    :marketThesis(upProb,rangeProb);
  const decisionItems=selectDecisionItems({minAbsoluteDelta:1,limit:5});
  const root=el('<div class="overview-page"></div>');
  const stage=el(`<section class="overview-stage" aria-labelledby="market-thesis"><div class="stage-inner">
    <div class="overview-hero">
      <div class="overview-copy">
        <p class="eyebrow">${vintage.status==='stale'?'보관된 시장 시나리오':'현재 시장 판단'} · ${esc(sc.asof)}</p>
        <h1 id="market-thesis">${esc(thesis.lead)}<em>${esc(thesis.accent)}</em></h1>
        <p class="overview-deck">${vintage.status==='stale'?'아래 시장 경로는 마지막 유효 스냅샷으로만 표시합니다. 최신 질문별 예측은 별도 기준이며 두 확률 체계는 서로 합산하지 않습니다.':'연말 시나리오와 최신 질문별 예측을 함께 표시합니다. 두 확률 체계는 서로 합산하지 않으며 참고 의견으로만 제공합니다.'}</p>
        <div class="overview-actions"><button type="button" class="briefing-launch" data-action="briefing"><span>▶</span>3 STEP BRIEFING</button><small>← → 키로 30초 시장 요약 보기</small></div>
      </div>
      ${decisionQueueCard(decisionItems.slice(0,3))}
    </div>
    ${linkedSignalStrip(vintage.status==='stale'?null:upProb,decisionItems)}
  </div></section>`);
  const fq=homeFeatureQuestions(decisionItems);
  const fg=el('<div class="feature-grid forecast-grid"></div>');
  fq.forEach((q,i)=>{
    const decision=decisionItems.find(x=>x.q.id===q.id);
    const signals=['market',...(decision?.signals||[])].join(' ');
    const available=hasNumeric(q.latest_prob),d=latestDelta(q.id);
    const dtxt=!available?'예측 대기':d==null?'첫 예측':(d>=0?'▲ +'+d+'%p':'▼ '+d+'%p'),dcls=d==null?'':(d>=0?'up':'down');
    const c=el(`<article class="forecast-card forecast-module tone-${i}" data-q="${esc(q.id)}" data-home-signals="${esc(signals)}" role="group" aria-label="${esc(q.title)}">
      <div class="card-actions"><button type="button" class="question-action" data-pin-q="${esc(q.id)}" aria-label="개인 레이더에 고정">☆</button><button type="button" class="question-action compare" data-compare-q="${esc(q.id)}" aria-label="비교 선택" aria-pressed="false">⇄</button></div>
      <div class="card-kicker"><span>${esc(humanDomain(q.domain))}${decision?.newSince?'<b class="new-round-badge">NEW ROUND</b>':''}</span><span>${roundLabel(q.n_rounds)}</span></div>
      <div class="probability-row${available?'':' is-pending'}">${available?`<strong>${q.latest_prob}</strong><span>%</span>`:'<strong>산출 전</strong>'}</div>
      ${miniSparkline(q,i)}
      <div class="probability-track"><span style="width:${available?Math.min(100,q.latest_prob):0}%"></span></div>
      <p>${esc(q.title)}</p>
      <div class="card-foot"><span class="${dcls}">${dtxt}</span><span>${esc(q.deadline||'수시')}</span><a href="#q/${esc(q.id)}" aria-label="${esc(q.title)} 상세 보기">↗</a></div>
    </article>`);
    const journalHop=document.createElement('button');journalHop.type='button';journalHop.className='journal-hop';journalHop.textContent='변경 일지';journalHop.setAttribute('aria-label',`${q.title} 변경 일지 보기`);journalHop.onclick=event=>{event.stopPropagation();location.hash='#asof/'+q.id;};
    c.querySelector('.card-foot')?.insertBefore(journalHop,c.querySelector('.card-foot a'));
    c.onclick=e=>{if(!e.target.closest('button,a'))location.hash='#q/'+q.id;};
    fg.appendChild(c);
  });
  $('.stage-inner',stage).appendChild(fg);
  bindHomeSignals(stage);
  root.appendChild(stage);

  const lowerInner=el('<div class="overview-lower-inner"></div>');
  lowerInner.appendChild(el(vintageReceipt()));
  const scenarioChange=scenarioChangePanel(false);if(scenarioChange)lowerInner.appendChild(scenarioChange);
  const lower=el('<div class="section-grid overview-lower"></div>');
  lower.appendChild(el(`<div class="panel">
    <div class="panel-head"><h2>연말 시나리오 분포</h2><span class="vintage-note">기준 ${esc(sc.asof)}</span></div>
    ${scenarioBars()}</div>`));
  const up=upcoming(3);
  const dl=el(`<div class="panel"><div class="panel-head"><h2>다가오는 판정일</h2><div style="display:flex;align-items:center;gap:7px"><span class="vintage-note">${up.length}건</span><button type="button" class="calendar-action" data-calendar-all>CAL 저장</button></div></div>
    <div class="deadline-list">${up.map(u=>`<button type="button" data-q="${esc(u.id)}">
      <time>${esc(u.deadline||'수시')}</time><span>${esc(u.title)}</span><strong>${p1(u.latest_prob)}</strong></button>`).join('')||'<p class="empty">예정된 판정이 없습니다.</p>'}</div></div>`);
  dl.querySelectorAll('button[data-q]').forEach(b=>b.onclick=()=>location.hash='#q/'+b.dataset.q);
  lower.appendChild(dl);
  lowerInner.appendChild(lower);
  root.appendChild(lowerInner);
  mount(root);
}
function upcoming(limit=6){
  const today=DATA.meta.generated.slice(0,10);
  return DATA.questions.filter(q=>q.status==='active'&&q.deadline&&q.deadline>=today)
    .sort((a,b)=>a.deadline<b.deadline?-1:1).slice(0,limit);
}
function scenarioBars(){
  const s=DATA.scenario.paths;
  return '<div class="scenario-bars">'+['S1','S2','S3'].map(k=>{const p=s[k];
    return `<div class="scenario-row">
      <div><b>${esc(p.label)}</b><small>종점 ${num(p.end)}</small></div>
      <div class="bar"><span style="width:${p.prob}%;background:${CHART_COL[k]}"></span></div>
      <strong style="color:${CHART_LABEL_COL[k]}">${p.prob}%</strong></div>`;
  }).join('')+`</div><div class="band-grid">
    <div><span>현재 지수</span><strong>${num(Math.round(DATA.scenario.anchor))}</strong></div>
    <div><span>전고점</span><strong>${num(DATA.scenario.ath)}</strong></div>
    <div><span>−10% 조정선</span><strong>${num(DATA.scenario.corr10)}</strong></div></div>`;
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
  bitcoin:['Bitcoin','#1f6feb',''],
  realty_income:['Realty Income','#247d78',''],
  nasdaq_price:['NASDAQ 가격','#ff4f17',''],
  realty_income_price:['O 가격','#247d78',''],
  realty_income_total_return:['O 총수익 proxy','#9a6700','7 4']
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
function lookupCardMarkup(sc,mapped){
  const table=sc.quantile_table,index=mapped.index,q=table.quantiles,model=sc.model||{};
  const scenarioNames={S1:'S1 상승·ATH 돌파',S2:'S2 상승·ATH 미달',S3:'S3 조정·횡보'};
  const shortNote=mapped.tradingDay<=5?'<p class="lookup-short-note">단기 구간일수록 모델 가정 민감도가 큽니다.</p>':'';
  const eventQuestions=(DATA.questions||[]).filter(question=>question.deadline===mapped.requested&&question.probability_space==='physical_event'&&hasNumeric(question.latest_prob));
  const physicalEvents=eventQuestions.length?`<section class="lookup-physical-events" aria-label="별도 physical event 확률"><header><span>PHYSICAL EVENT · 별도 확률 공간</span><strong>시나리오 분포와 결합 금지</strong></header>${eventQuestions.map(question=>`<article><div><small>${esc(question.id)}</small><a href="#q/${esc(question.id)}">${esc(question.title)}</a></div><strong>p=${(Number(question.latest_prob)/100).toFixed(2)}</strong><small>${esc(question.probability_space)} · ${esc(String(question.latest_ts||'').slice(0,10)||'기준 미상')} 기준</small></article>`).join('')}</section>`:'';
  return `<article class="lookup-card" data-lookup-date="${esc(mapped.mapped)}">
    <header><p class="eyebrow">DATE DISTRIBUTION · MODEL CONDITIONAL</p><h3>${esc(lookupDateLabel(mapped))}</h3></header>
    <div class="lookup-metrics">
      <div class="lookup-primary"><span>10–90% 구간</span><strong>${num(q.p10[index])} – ${num(q.p90[index])}</strong></div>
      <div><span>25–75% 구간</span><strong>${num(q.p25[index])} – ${num(q.p75[index])}</strong></div>
      <div><span>중앙값</span><strong>${num(q.p50[index])}</strong></div>
      <div><span>현재가(${num(Math.round(sc.anchor))}) 상회</span><strong>${table.prob_above_anchor[index]}%</strong><small>모델 조건부 확률</small></div>
      <div><span>ATH 상회</span><strong>${table.prob_above_ath[index]}%</strong><small>모델 조건부 확률</small></div>
    </div>
    ${shortNote}
    <details class="lookup-scenarios"><summary>S1/S2/S3 조건부 중앙값 보기</summary><div>${['S1','S2','S3'].map(key=>`<p><span>${scenarioNames[key]}</span><strong>${num(table.per_scenario_p50[key][index])}</strong><small>${num(table.per_scenario_counts?.[key]||0)}경로</small></p>`).join('')}</div></details>
    ${physicalEvents}
    <p class="lookup-warning">⚠ GBM 고정 가정의 조건부 분포입니다. 목표가·사건확률·투자자문이 아닙니다.</p>
    <footer>as_of ${esc(sc.asof)} 스냅샷 · seed ${esc(model.seed)} · ${num(model.n_paths)}경로 · ${esc(table.probability_space)}</footer>
  </article>`;
}
function renderFlow(initialLookup){
  const initialState=initialLookup&&typeof initialLookup==='object'?initialLookup:{lookup:initialLookup};
  initialLookup=initialState.lookup||null;
  const sc=DATA.scenario;
  const methodCopy=String(sc.method||'').startsWith('gbm-daily-252d')
    ?'경로 확률은 확정 일봉 252거래일의 GBM 분류 결과이며 fat tail과 돌발 이벤트를 직접 모형화하지 않습니다.'
    :'경로 확률은 감사된 수동 시나리오의 보관값이며 현재 시장 판단에는 별도 최신성 확인이 필요합니다.';
  const root=el('<div></div>');
  root.appendChild(el(`<div class="page-heading"><div>
    <p class="eyebrow">시장 전망 · Scenario Map</p>
    <h1>향후 12개월 시장 경로를 분포로 읽는다</h1>
    <p class="page-lede">나스닥 종합 기준 조건부 시나리오 3경로와 과거 혁신 사이클 비교입니다. 시나리오 기준 ${esc(sc.asof)} · 참고 의견이며 투자 자문이 아닙니다.</p>
  </div></div>`));
  root.appendChild(el(vintageReceipt()));
  const scenarioChange=scenarioChangePanel(true);if(scenarioChange)root.appendChild(scenarioChange);
  const legend=`<div class="band-inline">
    ${['S1','S2','S3'].map(k=>`<span><b style="background:${CHART_COL[k]}"></b>${esc(sc.paths[k].label)} ${sc.paths[k].prob}%</span>`).join('')}
    ${sc.fan?.quantiles?'<span><b class="fan-swatch"></b>조건부 구간 p10–p90 · 중앙값 p50</span>':''}</div>`;
  const focusControls=`<div class="flow-focus" role="group" aria-label="시나리오 경로 강조"><span>SPOTLIGHT</span>
    <button type="button" data-flow-focus="ALL" aria-pressed="true"><i></i>전체</button>
    ${['S1','S2','S3'].map(k=>`<button type="button" data-flow-focus="${k}" style="--focus-color:${CHART_COL[k]}" aria-pressed="false"><i></i>${esc(sc.paths[k].label)}</button>`).join('')}</div>`;
  const lookupTable=sc.quantile_table,lookupReady=lookupTable?.status==='ok'&&lookupTable.trading_days?.length;
  const quick=lookupReady?ForecastLookup.quickDates(sc.asof):{};
  if(lookupReady)quick.sixMonth=lookupTable.trading_days[Math.min(125,lookupTable.trading_days.length-1)];
  const sixMonthEnd=lookupReady?quick.sixMonth:sc.week_dates?.[Math.min(25,(sc.week_dates?.length||1)-1)];
  const fullHorizonEnd=lookupReady?lookupTable.trading_days.at(-1):sc.week_dates?.at(-1);
  const lookupWidget=lookupReady?`<section class="forecast-lookup" aria-labelledby="lookup-title">
    <div class="lookup-heading"><div><p class="eyebrow">CURRENT-ORIGIN LOOKUP</p><h3 id="lookup-title">현재 기준 미래 분포 조회</h3><p>${esc(sc.asof)}을 원점으로 만든 동일한 분포에서 선택 날짜의 단면을 조회합니다.</p></div><span>NO API · NO STORAGE</span></div>
    <div class="lookup-scope-note"><strong>무엇을 보여주나요?</strong><span>미래 날짜에 새로 만든 전망이 아니라, 현재 스냅샷의 불확실성이 기간에 따라 얼마나 벌어지는지를 보여줍니다. 기본 차트는 6개월이며 이후 날짜를 조회하면 2027년 전체 보기로 전환됩니다.</span></div>
    <div class="lookup-controls"><label for="lookup-date">날짜 선택<input id="lookup-date" type="date" min="${esc(lookupTable.trading_days[0])}" max="${esc(lookupTable.trading_days.at(-1))}" value="${esc(initialLookup||quick.month)}"></label><button type="button" class="lookup-submit">분포 조회</button></div>
    <div class="lookup-chips" aria-label="빠른 날짜">${[['week','1주 뒤'],['month','1개월'],['quarter','3개월'],['sixMonth','6개월'],['yearEnd','연말']].map(([key,label])=>`<button type="button" data-lookup-quick="${esc(quick[key])}">${label}</button>`).join('')}</div>
    <div class="lookup-natural"><label for="lookup-natural">한 줄 날짜 입력<input id="lookup-natural" type="text" maxlength="40" placeholder="8/30 · 8월 30일 · 3개월 뒤 · 연말" autocomplete="off"></label><button type="button" class="lookup-natural-submit">날짜 해석</button><small>정규식 규칙 파서 · LLM 호출 없음</small></div>
    <div class="lookup-result" aria-live="polite"><div class="lookup-empty"><strong>날짜를 선택하면 구간부터 표시합니다.</strong><span>없는 날짜를 보간하지 않고 실제 산출 거래일로 매핑합니다.</span></div></div>
  </section>`:'';
  const evRibbon=`<div class="event-track">${sc.events.map(([xi,label])=>`<div><time>${esc(sc.weeks[Math.max(0,Math.min(sc.weeks.length-1,Math.round(xi)))]||'')}</time><span>${esc(label)}</span></div>`).join('')}</div>`;
  const p1w=el(`<div class="chart-panel analysis-panel">
    <div class="panel-head"><h2 id="flow-horizon-title">현재 기준 6개월 조건부 분포</h2>${legend}</div>
    ${focusControls}
    <div class="flow-origin-bar"><div><span>CURRENT ORIGIN</span><strong>${esc(sc.asof)}</strong><small>모든 날짜는 이 기준일에서 출발한 한 번의 조건부 분포입니다.</small></div><div class="flow-horizon-toggle" role="group" aria-label="미래 분포 표시 기간"><button type="button" data-flow-horizon="126" aria-pressed="true"><span>기본</span>6개월<small>${esc(sixMonthEnd||'')}</small></button><button type="button" data-flow-horizon="252" aria-pressed="false"><span>확장</span>2027년까지<small>${esc(fullHorizonEnd||'')}</small></button></div></div>
    ${lookupWidget}
    <div class="chart-wrap"><div id="chart" style="min-width:1000px"></div></div>
    ${evRibbon}
    <div class="risk-legend"><span><i class="lo"></i>변동성 저</span><span><i class="mid"></i>중</span><span><i class="hi"></i>고</span></div>
    ${sc.fan?.quantiles?`<div class="scenario-semantics"><span>미래 분포</span><strong>중앙값 p50 · 안쪽 p25–p75 · 바깥 p10–p90</strong><small>${esc(sc.fan.probability_space)} · ${esc(sc.fan.monitoring||'미산출')} monitoring</small></div>`:''}
    <p class="chart-note">경로는 대표 시나리오 예시입니다. 차트를 움직이거나 터치하고, 포커스한 뒤 좌우 화살표로 주차를 탐색할 수 있습니다. ${esc(methodCopy)}</p>
  </div>`);
  const overlay=analogPanel();
  const crossAsset=crossAssetPanel();
  const aiRegime=aiRegimePanel();
  const liquidity=liquidityPanel();
  p1w.id='lab-future';p1w.setAttribute('role','tabpanel');p1w.setAttribute('aria-labelledby','lab-tab-future');
  if(overlay){overlay.id='lab-history';overlay.setAttribute('role','tabpanel');overlay.setAttribute('aria-labelledby','lab-tab-history');overlay.hidden=true;}
  if(crossAsset){crossAsset.id='lab-cross-asset';crossAsset.setAttribute('role','tabpanel');crossAsset.setAttribute('aria-labelledby','lab-tab-cross-asset');crossAsset.hidden=true;}
  if(aiRegime){aiRegime.id='lab-ai-regime';aiRegime.setAttribute('role','tabpanel');aiRegime.setAttribute('aria-labelledby','lab-tab-ai-regime');aiRegime.hidden=true;}
  if(liquidity){liquidity.id='lab-liquidity';liquidity.setAttribute('role','tabpanel');liquidity.setAttribute('aria-labelledby','lab-tab-liquidity');liquidity.hidden=true;}
  const labTabs=el(`<div class="lab-tabs" role="tablist" aria-label="시장 지도 분석 공간">
    <button type="button" id="lab-tab-future" role="tab" aria-selected="true" aria-controls="lab-future" data-lab-tab="future"><span>01</span> 미래 분포<small>scenario-conditional</small></button>
    <button type="button" id="lab-tab-history" role="tab" aria-selected="false" aria-controls="lab-history" data-lab-tab="history" ${overlay?'':'disabled'}><span>02</span> 사이클 비교<small>reference-only</small></button>
    <button type="button" id="lab-tab-cross-asset" role="tab" aria-selected="false" aria-controls="lab-cross-asset" data-lab-tab="cross-asset" ${crossAsset?'':'disabled'}><span>03</span> 자산 전이<small>scenario-conditional</small></button>
    <button type="button" id="lab-tab-ai-regime" role="tab" aria-selected="false" aria-controls="lab-ai-regime" data-lab-tab="ai-regime" ${aiRegime?'':'disabled'}><span>04</span> 자본사이클<small>reference-only</small></button>
    <button type="button" id="lab-tab-liquidity" role="tab" aria-selected="false" aria-controls="lab-liquidity" data-lab-tab="liquidity" ${liquidity?'':'disabled'}><span>05</span> 유동성<small>reference-only</small></button>
  </div>`);
  root.appendChild(labTabs);root.appendChild(p1w);if(overlay)root.appendChild(overlay);if(crossAsset)root.appendChild(crossAsset);if(aiRegime)root.appendChild(aiRegime);if(liquidity)root.appendChild(liquidity);
  mount(root);
  let flowFocus='ALL',lookupMarker=null,flowHorizon=126;
  const flowHost=$('#chart',p1w),flowTitle=$('#flow-horizon-title',p1w);
  const syncFlowHorizon=()=>{p1w.querySelectorAll('[data-flow-horizon]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.flowHorizon)===flowHorizon)));
    if(flowTitle)flowTitle.textContent=flowHorizon===126?'현재 기준 6개월 조건부 분포':`현재 기준 전체 조건부 분포 · ${fullHorizonEnd||'2027년'}`;};
  const paintFlow=focus=>{flowFocus=focus;flowHost.innerHTML='';drawFlow(flowHost,sc,focus,lookupMarker,flowHorizon);
    p1w.querySelectorAll('[data-flow-focus]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.flowFocus===focus)));};
  p1w.querySelectorAll('[data-flow-focus]').forEach(b=>b.onclick=()=>paintFlow(b.dataset.flowFocus));
  p1w.querySelectorAll('[data-flow-horizon]').forEach(button=>button.onclick=()=>{flowHorizon=Number(button.dataset.flowHorizon);syncFlowHorizon();paintFlow(flowFocus);});
  syncFlowHorizon();paintFlow(flowFocus);
  const lookupResult=$('.lookup-result',p1w),lookupInput=$('#lookup-date',p1w);
  const runLookup=requested=>{if(!lookupResult||!lookupInput)return;lookupInput.value=requested||lookupInput.value;
    const mapped=ForecastLookup.mapDate(sc.quantile_table,lookupInput.value,sc.asof);
    lookupResult.innerHTML=mapped.ok?lookupCardMarkup(sc,mapped):lookupErrorMarkup(mapped);
    lookupMarker=mapped.ok?mapped.mapped:null;
    if(mapped.ok&&mapped.index>=126){flowHorizon=252;syncFlowHorizon();}
    paintFlow(flowFocus);
    if(mapped.ok)history.replaceState(null,'',`#lookup=${mapped.requested}`);
  };
  const lookupSubmit=$('.lookup-submit',p1w);if(lookupSubmit)lookupSubmit.onclick=()=>runLookup(lookupInput.value);
  p1w.querySelectorAll('[data-lookup-quick]').forEach(button=>button.onclick=()=>runLookup(button.dataset.lookupQuick));
  if(lookupInput)lookupInput.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();runLookup(lookupInput.value);}};
  const naturalInput=$('#lookup-natural',p1w),naturalSubmit=$('.lookup-natural-submit',p1w);
  const runNatural=()=>{const parsed=ForecastLookup.parseQuery(naturalInput?.value,sc.asof);if(parsed.ok)runLookup(parsed.date);else{lookupResult.innerHTML=lookupErrorMarkup(parsed);lookupMarker=null;paintFlow(flowFocus);}};
  if(naturalSubmit)naturalSubmit.onclick=runNatural;
  if(naturalInput)naturalInput.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();runNatural();}};
  if(initialLookup)runLookup(initialLookup);
  const activateLab=space=>{const available={future:p1w,history:overlay,'cross-asset':crossAsset,'ai-regime':aiRegime,liquidity},active=available[space]?space:'future';
    Object.entries(available).forEach(([key,panel])=>{if(panel)panel.hidden=key!==active;});
    labTabs.querySelectorAll('[data-lab-tab]').forEach(b=>{const on=b.dataset.labTab===active;b.setAttribute('aria-selected',String(on));b.tabIndex=on?0:-1;});};
  const availableTabs=[...labTabs.querySelectorAll('[data-lab-tab]:not(:disabled)')];
  availableTabs.forEach((b,index)=>{b.onclick=()=>{activateLab(b.dataset.labTab);history.replaceState(null,'',b.dataset.labTab==='future'?'#flow':`#lab=${b.dataset.labTab}`);};b.onkeydown=event=>{let next=null;if(event.key==='ArrowLeft'||event.key==='ArrowUp')next=(index-1+availableTabs.length)%availableTabs.length;if(event.key==='ArrowRight'||event.key==='ArrowDown')next=(index+1)%availableTabs.length;if(event.key==='Home')next=0;if(event.key==='End')next=availableTabs.length-1;if(next!=null){event.preventDefault();activateLab(availableTabs[next].dataset.labTab);availableTabs[next].focus();}};});
  if(overlay){
    const analogHost=$('#ovchart',overlay),paintAnalog=focus=>{analogHost.innerHTML='';drawOverlay(analogHost,overlay._overlay,overlay._eras,focus);
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
  const eras=Object.keys(ERA_META).filter(e=>o[e]&&o[e].length>1);
  if(eras.length<2)return null;
  const focusControls=`<div class="flow-focus analog-focus" role="group" aria-label="과거 혁신 사이클 강조"><span>SPOTLIGHT</span>
    <button type="button" data-analog-focus="ALL" aria-pressed="true"><i></i>전체</button>
    ${eras.map(e=>`<button type="button" data-analog-focus="${e}" style="--focus-color:${ERA_META[e][1]}" aria-pressed="false"><i></i>${ERA_META[e][0]}</button>`).join('')}</div>`;
  const rg=ctx.regime||{},br=ctx.breadth||{},cc=ctx.concentration||{};
  const ctxItems=[
    rg.recession_flag!=null?['경기 국면',rg.recession_flag?'침체':'확장']:null,
    br.pct_above_200dma!=null?['시장 폭','200일선 '+br.pct_above_200dma+'%']:null,
    cc.ratio_pctile!=null?['대형주 집중',cc.ratio_pctile+'%ile']:null,
    ctx.perez_ai?['사이클 국면',esc(ctx.perez_ai.split(' — ')[0])+' (추정)']:null
  ].filter(Boolean).slice(0,4);
  const w=el(`<div class="chart-panel analysis-panel">
    <p class="eyebrow">과거 혁신 사이클 비교 · Analog Overlay</p>
    <div class="panel-head"><h2>5년 build-up · 시작월 = 100 · 로그 스케일</h2><span class="count-chip">${eras.length}개 사이클</span></div>
    <div class="reference-banner"><strong>REFERENCE ONLY · 확률 아님</strong><span>${esc(model.unit)} · anchor 기준 상대 개월</span></div>
    ${focusControls}
    <div class="chart-wrap"><div id="ovchart" style="min-width:1240px"></div></div>
    <div class="context-grid">${ctxItems.map(([k,v])=>`<div><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('')}</div>
    <p class="chart-note"><strong>연도 표기는 버블 정점이 아니라 비교 시작점입니다.</strong> 크립토는 2019년 회복 시작을 M+0으로 두며, 주요 강세 구간은 2020~2021년, 이 사이클의 정점은 2021-11(M+34)입니다. 과거 곡선은 결과를 아는 hindsight 자료입니다. 질문 확률·시나리오 확률과 산술 결합하지 않습니다.</p>
    <details class="analog-limit"><summary>Anchor 민감도와 한계</summary><p>${esc(model.anchor_sensitivity?.reason||'미산출')} ${esc((model.limitations||[]).join(' '))}</p></details>
  </div>`);
  w._eras=eras;w._overlay=o;
  return w;
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
  const periodCaption=period.replace(' to ',' → '),weights=model.forecast.weights||{};
  const weightText=weights.status&&weights.display&&weights.reason?`${weights.display} — ${weights.reason}`:'가중치 미산출 — 충격 유형별 캘리브레이션 부족';
  const ci=(range,n)=>`(10–90%: ${hasNumeric(range?.[0])?Number(range[0]).toFixed(2):'–'}–${hasNumeric(range?.[1])?Number(range[1]).toFixed(2):'–'}, n=${num(n)})`;
  const peak=summary.nasdaq_from_dotcom_peak||{},weeklyCorr=weekly.corr||{},weeklyBeta=weekly.beta||{},year2005=(summary.annual||[]).find(row=>Number(row.year)===2005)||{};
  const w=el(`<div class="chart-panel analysis-panel cross-asset-panel">
    <p class="eyebrow">AI 충격 교차자산 지도 · Cross-asset Transmission</p>
    <div class="panel-head"><div><h2>Bitcoin · NASDAQ · Realty Income</h2><p>현재값 또는 비교 시작값을 100으로 맞춘 상대 경로</p></div><span class="count-chip">시장 기준 ${esc(model.asof)}</span></div>
    <div class="reference-banner scenario-banner"><strong>CONDITIONAL PATH · 목표가격 아님</strong><span>${esc(model.forecast.semantics)}</span></div>
    <div class="cross-anchor-strip" aria-label="비교 기준 현물 가격">
      <div><span>NASDAQ</span><strong>${num(anchors.nasdaq)}</strong></div>
      <div><span>BITCOIN</span><strong>$${num(anchors.bitcoin)}</strong></div>
      <div><span>REALTY INCOME</span><strong>$${hasNumeric(anchors.realty_income)?Number(anchors.realty_income).toFixed(2):'산출 전'}</strong></div>
      <small>${esc(model.asof)} 공통 확정 거래일 · 미래선은 위 현물값을 100으로 정규화 · 지수 100을 실제 가격으로 환산하지 마세요.</small>
    </div>
    <div class="cross-view-switch" role="group" aria-label="교차자산 보기">
      <button type="button" data-cross-view="scenario" aria-pressed="true">AI 충격 12개월</button>
      <button type="button" data-cross-view="history" aria-pressed="false">실측 ${esc(periodCaption)}</button>
    </div>
    <section data-cross-panel="scenario">
      <div class="flow-focus cross-focus" role="radiogroup" aria-label="교차자산 충격 가정">
        <span>SHOCK TYPE</span>${Object.entries(scenarios).map(([id,scenario])=>`<button type="button" role="radio" data-cross-scenario="${id}" aria-checked="${id===defaultScenario}" aria-pressed="${id===defaultScenario}" tabindex="${id===defaultScenario?0:-1}"><i></i>${esc(scenario.label)}</button>`).join('')}
      </div>
      <div class="cross-weight-badge" aria-label="시나리오 가중치 상태">${esc(weightText)}</div>
      <div class="cross-scenario-copy" id="cross-scenario-copy"></div>
      <div class="chart-wrap"><div id="cross-chart" style="min-width:980px"></div></div>
    </section>
    <section data-cross-panel="history" hidden>
      <div class="reference-banner history-gap"><strong>BTC DATA GAP · 정상 결측</strong><span>${esc(model.history.bitcoin?.reason||'2001–2005 Bitcoin 가격은 존재하지 않습니다.')}</span></div>
      <div class="chart-wrap"><div id="cross-history-chart" style="min-width:980px"></div></div>
      <div class="history-score-grid">
        <div><span>NASDAQ 가격</span><strong>${pctText(summary.nasdaq_price_pct)}</strong><small>${esc(periodCaption)}</small></div>
        <div><span>O 가격</span><strong>${pctText(summary.realty_income_price_pct)}</strong><small>현금배당 제외</small></div>
        <div><span>O 총수익 proxy</span><strong>${pctText(summary.realty_income_total_return_pct)}</strong><small>수정종가 · 배당재투자 효과</small></div>
        <div><span>NASDAQ 닷컴 정점 기준</span><strong>${pctText(peak.nasdaq_price_pct)}</strong><small>${esc(peak.start||'2000-03')} → ${esc(peak.end||model.history.labels?.at(-1)||'종료')} · 별도 anchor</small></div>
      </div>
      <details class="analog-limit annual-return-table"><summary>연도별 실측 수익률 보기</summary><div class="table-shell"><table><thead><tr><th>연도</th><th>NASDAQ 가격</th><th>O 가격</th><th>O 총수익 proxy</th></tr></thead><tbody>${annual.map(row=>`<tr><td>${row.year}</td><td>${pctText(row.nasdaq_price_pct)}</td><td>${pctText(row.realty_income_price_pct)}</td><td>${pctText(row.realty_income_total_return_pct)}</td></tr>`).join('')}</tbody></table></div></details>
    </section>
    <section class="realty-thesis-grid" aria-label="Realty Income 조건부 가설 점검">
      <article class="realty-thesis-card history-card">
        <p class="eyebrow">HISTORICAL CONDITIONS · 인과 추정 아님</p>
        <h3>닷컴 때 왜 올랐나</h3>
        <p>한 가지 원인으로 단정하지 않고, 당시 함께 관측된 네 조건을 분리해서 봅니다.</p>
        <div class="realty-factor-grid">
          <div><span>1 · 금리 완화</span><strong>${eventBp(dotcomEvent,'dgs10')}</strong><small>DGS10 · ${esc(dotcomEvent.start||'2001-01-03')} → ${esc(dotcomEvent.end||'2003-06-25')}</small></div>
          <div><span>2 · 낮은 출발 밸류</span><strong>1998–99 약세 이후</strong><small>당시 정확한 yield spread는 원천 제약으로 미표시</small></div>
          <div><span>3 · 배당 방어</span><strong>${eventPct(dotcomEvent,'realty_income_total_return')}</strong><small>O 가격 ${eventPct(dotcomEvent,'realty_income_price')} · 총수익 proxy</small></div>
          <div><span>4 · 완만한 붕괴</span><strong>NASDAQ ${eventPct(dotcomEvent,'nasdaq_price')}</strong><small>2020 급성 위기 O ${eventPct(acuteEvent,'realty_income_price')}</small></div>
        </div>
        <p class="realty-counterexample"><strong>반례도 함께 표시:</strong> 2005년 O 가격 ${hasNumeric(year2005.realty_income_price_pct)?signedDelta(year2005.realty_income_price_pct,1,'%'):'관측 불가'} · 2004–2006 긴축 이벤트 ${eventPct(tighteningEvent,'realty_income_price')}. 닷컴 구간 상승을 모든 기술주 조정기에 반복되는 법칙으로 취급하지 않습니다.</p>
      </article>
      <article class="realty-thesis-card current-card">
        <p class="eyebrow">CURRENT COMPARISON · ${esc(sensitivity.asof||model.asof)}</p>
        <h3>2026년은 같은 조건인가</h3>
        <div class="realty-table-shell"><table><tbody>
          <tr><th>TTM 배당수익률</th><td>${hasNumeric(sensitivity.dividend_yield_ttm_pct)?Number(sensitivity.dividend_yield_ttm_pct).toFixed(2)+'%':'관측 불가'}</td></tr>
          <tr><th>10Y 대비 spread</th><td>${hasNumeric(sensitivity.spread_vs_10y_pp)?signedDelta(sensitivity.spread_vs_10y_pp,2,' pp'):'관측 불가'}</td></tr>
          <tr><th>2000년 이후 spread 위치</th><td>${hasNumeric(sensitivity.spread_percentile_since_2000)?Number(sensitivity.spread_percentile_since_2000).toFixed(1)+'%ile':'표본 축적 중'}</td></tr>
          <tr><th>금리 100bp 민감도</th><td>${hasNumeric(rateSensitivity.measured_effect_per_100bp_pct)?signedDelta(rateSensitivity.measured_effect_per_100bp_pct,2,'%'):'추정 불가'} <small>${esc(rateSensitivity.status||'미산출')}</small></td></tr>
          <tr><th>신용 100bp 민감도</th><td>${hasNumeric(creditSensitivity.used_effect_per_100bp_pct)?signedDelta(creditSensitivity.used_effect_per_100bp_pct,2,'%'):'0.00%'} <small>${esc(creditSensitivity.status||'미산출')}${creditSensitivity.gate_proximity==='at_boundary'?' · gate 경계(n=156)':''}</small></td></tr>
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
    ${scenarioTrackerMarkup(DATA.scenario_tracker)}
    <p class="chart-note realty-fixed-warning"><strong>고정 해석:</strong> O 미래선은 가격 경로이며 배당 미포함. 닷컴형 상승은 조건부 결과였다.</p>
    <p class="cross-condition-note">60일 상관은 전체 최근 구간의 동행성을, 하락꼬리 beta는 NASDAQ 하위 10% 거래일의 조건부 민감도를 봅니다. 서로 다른 질문이므로 같은 값처럼 비교하지 않습니다. 주간 금요일→금요일: BTC corr ${hasNumeric(weeklyCorr.bitcoin_nasdaq)?Number(weeklyCorr.bitcoin_nasdaq).toFixed(2):'–'} / beta ${hasNumeric(weeklyBeta.bitcoin_to_nasdaq)?Number(weeklyBeta.bitcoin_to_nasdaq).toFixed(2):'–'}, O corr ${hasNumeric(weeklyCorr.realty_income_nasdaq)?Number(weeklyCorr.realty_income_nasdaq).toFixed(2):'–'} / beta ${hasNumeric(weeklyBeta.realty_income_to_nasdaq)?Number(weeklyBeta.realty_income_to_nasdaq).toFixed(2):'–'}.</p>
    <p class="chart-note"><strong>해석:</strong> 동반 디레버리징에서는 세 자산이 함께 하락할 수 있습니다. 금리 하락과 달러 유동성 재확대가 뒤따르는 경우에만 Bitcoin과 Realty Income의 차별 반등 경로가 열립니다. O 미래선은 주가 경로로 현금배당을 포함하지 않습니다.</p>
    <details class="analog-limit"><summary>모델 영수증과 한계</summary><p>${esc((model.limitations||[]).join(' '))} 출처: ${esc((model.sources||[]).map(source=>source.label).join(' · '))}</p></details>
  </div>`);
  w._crossModel=model;w._defaultScenario=defaultScenario;
  return w;
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
    <div class="reference-banner"><strong>REFERENCE ONLY</strong><span>SEC entity-wide facts 수집 완료 · segment revenue 분리 전 D3 차단</span></div>
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
    <p class="eyebrow">LIQUIDITY TIDE MAP · REFERENCE ONLY</p>
    <div class="panel-head"><div><h2>유동성 조류 지도</h2><p>Fed 순유동성과 BTC·NASDAQ 민감도를 같은 주간축에서 진단</p></div><span class="count-chip">주간 기준 ${esc(model.asof)}</span></div>
    <div class="liquidity-zone zone-${esc(model.zone)}"><span>CURRENT ZONE</span><strong>${esc(zoneLabel)}</strong><small>Fed 순유동성 4주 변화 ${signedDelta(model.zone_metric?.value,2,'%')}</small></div>
    <div class="chart-wrap"><div id="liquidity-chart" style="min-width:980px"></div></div>
    <div class="liquidity-source-grid"><div><span>실질 M2 YoY</span><strong>원천 미확보</strong><small>${esc(model.real_m2?.reason||'ALFRED vintage 필요')}</small></div><div><span>Stablecoin supply</span><strong>${stablecoinProgress}</strong><small>D0 스키마 관측 · license ${esc(monitor.license_status||'review_required')} · 자동 활성화 안 함</small></div><div><span>BTC ETF flow</span><strong>원천 미확보</strong><small>2개 원천 교차검증·라이선스 게이트</small></div></div>
    <details class="analog-limit liquidity-lag"><summary>0·4·8·12주 시차 상관 진단</summary><div class="lag-table-grid"><div><h3>NASDAQ</h3><div class="table-shell"><table><thead><tr><th>시차</th><th>상관 또는 게이트</th><th>n</th></tr></thead><tbody>${lagRows('nasdaq')}</tbody></table></div></div><div><h3>Bitcoin</h3><div class="table-shell"><table><thead><tr><th>시차</th><th>상관 또는 게이트</th><th>n</th></tr></thead><tbody>${lagRows('bitcoin')}</tbody></table></div></div></div></details>
    <p class="tracker-warning">${esc(model.warning||'유동성 확장이 곧 상승을 뜻하지 않습니다. 시차 상관은 국면 의존 진단입니다.')}</p>
  </div>`);w._liquidityModel=model;return w;
}
function bindLiquidity(panel){drawLiquidity($('#liquidity-chart',panel),panel._liquidityModel);}
function drawLiquidity(host,model){
  const NS='http://www.w3.org/2000/svg',W=1160,H=510,ML=58,MR=28,MT=34,MB=42,GAP=38,PANEL=170,PW=W-ML-MR;
  const labels=model.series.labels,n=labels.length,z=model.series.fed_net_liquidity_z_52w,ndx=model.series.nasdaq_return_26w_pct,btc=model.series.bitcoin_return_26w_pct,zones=model.series.liquidity_zone;
  const X=i=>ML+PW*i/Math.max(1,n-1),svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width','100%');svg.setAttribute('role','img');svg.setAttribute('tabindex','0');svg.setAttribute('aria-label','유동성 조류 주간 차트. 좌우 화살표로 이동');
  const mk=(tag,attrs)=>{const node=document.createElementNS(NS,tag);for(const key in attrs)node.setAttribute(key,attrs[key]);return node;};
  const tx=(x,y,value,opts={})=>{const node=mk('text',{x,y,fill:opts.fill||'#5f5d57','font-size':opts.fs||12,'text-anchor':opts.anc||'start','font-weight':opts.w||500});node.textContent=value;return node;};
  const panelTop=[MT,MT+PANEL+GAP],zoneColor={expansion:'#247d78',neutral:'#9a6700',contraction:'#c9002d'};
  zones.forEach((zone,index)=>svg.appendChild(mk('rect',{x:X(index),y:panelTop[0],width:PW/Math.max(1,n-1)+1,height:PANEL*2+GAP,fill:zoneColor[zone]||'#aaa',opacity:.045})));
  const scale=(values,top)=>{const nums=values.filter(hasNumeric).map(Number),lo=Math.min(...nums),hi=Math.max(...nums),pad=Math.max(1,(hi-lo)*.12);return value=>top+PANEL*(1-(Number(value)-(lo-pad))/Math.max(1,(hi+pad)-(lo-pad)));};
  const yz=scale(z,panelTop[0]),yr=scale([...ndx,...btc],panelTop[1]);
  const liquiditySeries=[
    {values:z,color:'#6b4bc3',y:yz,top:panelTop[0],label:'Fed 순유동성 · 52주 z',labelX:ML},
    {values:ndx,color:'#ff4f17',y:yr,top:panelTop[1],label:'NASDAQ · 26주 수익률',labelX:ML},
    {values:btc,color:'#1f6feb',y:yr,top:panelTop[1],label:'BITCOIN · 26주 수익률',labelX:ML+235}
  ];
  liquiditySeries.forEach(({values,color,y})=>{let path='';values.forEach((value,index)=>{if(hasNumeric(value))path+=(path?'L':'M')+X(index)+','+y(value)+' ';});svg.appendChild(mk('path',{d:path,fill:'none',stroke:color,'stroke-width':2.6,'stroke-linejoin':'round'}));});
  liquiditySeries.forEach(({color,top,label,labelX})=>{svg.appendChild(mk('line',{x1:labelX,y1:top-13,x2:labelX+20,y2:top-13,stroke:color,'stroke-width':3}));svg.appendChild(tx(labelX+27,top-9,label,{fill:color,w:750}));});
  panelTop.forEach(top=>svg.appendChild(mk('line',{x1:ML,y1:top+PANEL,x2:ML+PW,y2:top+PANEL,stroke:'rgba(17,17,15,.18)'})));
  [0,Math.floor((n-1)/2),n-1].forEach(index=>svg.appendChild(tx(X(index),H-12,labels[index].slice(0,7),{anc:'middle'})));
  const cursor=mk('line',{y1:panelTop[0],y2:panelTop[1]+PANEL,stroke:'rgba(17,17,15,.52)','stroke-dasharray':'4 3'});svg.appendChild(cursor);const overlay=mk('rect',{x:ML,y:panelTop[0],width:PW,height:panelTop[1]+PANEL-panelTop[0],fill:'transparent'});svg.appendChild(overlay);
  const readout=document.createElement('div');readout.className='flow-readout liquidity-readout';readout.setAttribute('role','status');readout.setAttribute('aria-live','polite');let selected=n-1;
  const paint=index=>{selected=Math.max(0,Math.min(n-1,index));cursor.setAttribute('x1',X(selected));cursor.setAttribute('x2',X(selected));readout.innerHTML=`<div class="flow-date"><span>SELECTED WEEK</span><strong>${esc(labels[selected])}</strong><small>${esc(({expansion:'확장',neutral:'중립',contraction:'수축'}[zones[selected]]||zones[selected]))} zone</small></div><div><span>Fed liquidity z</span><strong>${hasNumeric(z[selected])?Number(z[selected]).toFixed(2):'표본 축적 중'}</strong><small>52주 rolling</small></div><div><span>NASDAQ</span><strong>${hasNumeric(ndx[selected])?signedDelta(ndx[selected],1,'%'):'표본 축적 중'}</strong><small>26주 수익률</small></div><div><span>Bitcoin</span><strong>${hasNumeric(btc[selected])?signedDelta(btc[selected],1,'%'):'표본 축적 중'}</strong><small>26주 수익률</small></div>`;};
  const fromPointer=event=>{const rect=svg.getBoundingClientRect(),x=(event.clientX-rect.left)*(W/rect.width);return Math.round((x-ML)/(PW/Math.max(1,n-1)));};overlay.addEventListener('pointermove',event=>paint(fromPointer(event)));overlay.addEventListener('pointerdown',event=>{paint(fromPointer(event));svg.focus();});svg.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();paint(selected+(event.key==='ArrowLeft'?-1:1));}else if(event.key==='Home'){event.preventDefault();paint(0);}else if(event.key==='End'){event.preventDefault();paint(n-1);}});host.replaceChildren(svg,readout);paint(selected);
}
function bindCrossAsset(panel,initialScenario){
  const model=panel._crossModel;let view='scenario',scenarioId=model.forecast.scenarios?.[initialScenario]?initialScenario:panel._defaultScenario;
  const scenarioHost=$('#cross-chart',panel),historyHost=$('#cross-history-chart',panel),copy=$('#cross-scenario-copy',panel);
  const paintScenario=()=>{const scenario=model.forecast.scenarios[scenarioId],macro=scenario.macro_assumptions||{},last=values=>Array.isArray(values)&&values.length?values.at(-1):null;
    const macroChips=`<span>Δ10Y ${hasNumeric(last(macro.delta_10y_bp))?signedDelta(last(macro.delta_10y_bp),0,'bp'):'미산출'}</span><span>ΔHY ${hasNumeric(last(macro.delta_hy_bp))?signedDelta(last(macro.delta_hy_bp),0,'bp'):'미산출'}</span><span>사전 등록 가정</span>`;
    const attribution=scenario.realty_income_attribution||{},m3=3;
    const attributionText=`M+3 O 기여 · 시장 ${signedDelta(Number(attribution.market_beta?.[m3]||0),1)} · 금리 ${signedDelta(Number(attribution.rate?.[m3]||0),1)} · 크레딧 ${signedDelta(Number(attribution.credit?.[m3]||0),1)}`;
    const shared=scenario.path_linkage?.bitcoin==='shared_with_deleveraging_by_design'?'<em class="shared-path-badge">BTC 경로 공유 · 설계상 동일</em>':'';
    copy.innerHTML=`<div><span>선택 가정</span><strong>${esc(scenario.label)}</strong><small>${esc(scenario.short)}</small>${shared}</div><p>${macroChips}${scenario.assumptions.map(item=>`<span>${esc(item)}</span>`).join('')}</p><p class="cross-attribution">${esc(attributionText)}</p><p class="cross-interpretation">${esc(scenario.realty_income_interpretation||'')}</p>`;
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
  drawIndexedCompare(host,{labels:model.forecast.labels,series:scenario.paths,
    bands:scenario.paths_band,keys:['nasdaq','bitcoin','realty_income'],title:`${scenario.label} 조건부 12개월 경로`,selected:0});
}
function drawCrossAssetHistory(host,model){
  drawIndexedCompare(host,{labels:model.history.labels,series:model.history.series,
    keys:['nasdaq_price','realty_income_price','realty_income_total_return'],title:`${model.history.period} 실측 비교`,selected:model.history.labels.length-1,history:true});
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
  const ticks=5;for(let i=0;i<=ticks;i++){const value=lo+(hi-lo)*i/ticks,y=Y(value);
    svg.appendChild(mk('line',{x1:ML,y1:y,x2:ML+PW,y2:y,stroke:value===100?'rgba(17,17,15,.28)':'rgba(17,17,15,.09)','stroke-width':value===100?1.4:1}));
    svg.appendChild(tx(ML-8,y+4,Math.round(value),{anc:'end'}));}
  const labelIndexes=config.history
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
  resolveEndpointLabels(endpoints,16,MT+8,MT+PH-8).forEach(item=>{svg.appendChild(mk('line',{x1:X(n-1)+5,y1:item.y,x2:X(n-1)+12,y2:item.labelY,stroke:item.meta[1],'stroke-width':1,opacity:.65}));svg.appendChild(tx(X(n-1)+15,item.labelY+4,`${item.meta[0]} ${num(item.value)}`,{fill:item.meta[1],w:700}));});
  const cursor=mk('line',{stroke:'rgba(17,17,15,.5)','stroke-width':1.2,'stroke-dasharray':'4 3'});svg.appendChild(cursor);
  const markers=config.keys.map(key=>{const marker=mk('circle',{r:5,fill:CROSS_META[key][1],stroke:'#fff','stroke-width':2});svg.appendChild(marker);return marker;});
  const overlay=mk('rect',{x:ML,y:MT,width:PW,height:PH,fill:'transparent'});svg.appendChild(overlay);
  const readout=document.createElement('div');readout.className='flow-readout cross-asset-readout';readout.setAttribute('role','status');readout.setAttribute('aria-live','polite');readout.setAttribute('aria-atomic','true');readout.style.setProperty('--flow-count',String(config.keys.length+1));
  const tip=document.getElementById('tip'),finePointer=window.matchMedia('(pointer: fine)').matches;let selected=Math.max(0,Math.min(n-1,config.selected||0));
  const paint=index=>{selected=Math.max(0,Math.min(n-1,index));const x=X(selected);cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);cursor.setAttribute('y1',MT);cursor.setAttribute('y2',MT+PH);
    markers.forEach((marker,i)=>{const value=config.series[config.keys[i]][selected];marker.setAttribute('cx',x);marker.setAttribute('cy',Y(value));});
    readout.innerHTML=`<div class="flow-date"><span>SELECTED POINT</span><strong>${esc(config.labels[selected])}</strong><small>비교 기준 = 100</small></div>${config.keys.map(key=>`<div><span>${esc(CROSS_META[key][0])}</span><strong style="color:${CROSS_META[key][1]}">${num(config.series[key][selected])}</strong><small>${signedDelta(config.series[key][selected]-100,1,' pt')}</small></div>`).join('')}`;
    svg.setAttribute('aria-label',`${config.title}, 선택 ${config.labels[selected]}. 좌우 화살표로 이동`);
  };
  const fromPointer=event=>{const rect=svg.getBoundingClientRect(),mx=(event.clientX-rect.left)*(W/rect.width);return Math.max(0,Math.min(n-1,Math.round((mx-ML)/(PW/Math.max(1,n-1)))));};
  overlay.addEventListener('pointermove',event=>{const index=fromPointer(event);paint(index);if(finePointer){tip.style.display='block';tip.style.left=(event.clientX+14)+'px';tip.style.top=(event.clientY-10)+'px';tip.innerHTML=`<b>${esc(config.labels[index])} · 기준 100</b>`+config.keys.map(key=>`<span class="tip-series" style="--tip-series:${CROSS_META[key][1]}"><i aria-hidden="true"></i><span>${esc(CROSS_META[key][0])}</span><strong>${num(config.series[key][index])}</strong></span>`).join('');}});
  overlay.addEventListener('pointerdown',event=>{paint(fromPointer(event));if(!finePointer)tip.style.display='none';svg.focus();});overlay.addEventListener('pointerleave',()=>{tip.style.display='none';});
  svg.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();paint(selected+(event.key==='ArrowLeft'?-1:1));}else if(event.key==='Home'){event.preventDefault();paint(0);}else if(event.key==='End'){event.preventDefault();paint(n-1);}});
  host.replaceChildren(svg,readout);paint(selected);
}
function drawOverlay(host,o,eras,focus='ALL'){
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
      svg.appendChild(tx(X(i)+8,Y(last)+4,`현재 ${monthAt(ERA_START.ai,i)} · M+${i}`,{fill:'#34322e',fs:12,w:650,opacity:on?1:.12}));}});
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
    readout.innerHTML=`<div class="flow-date"><span>SELECTED MONTH</span><strong>M+${cursorIndex}</strong><small>시작월 = 100 · 로그 비교</small></div>${values.map(e=>`<div><span>${esc(ERA_META[e][0])}</span><strong style="color:${ERA_META[e][1]}">${num(o[e][cursorIndex])}</strong><small>${esc(monthAt(ERA_START[e],cursorIndex))}</small></div>`).join('')}`;
    svg.setAttribute('aria-label',`과거 혁신 사이클 비교, 선택 월 M+${cursorIndex}. 좌우 화살표로 이동`);
  };
  const indexFromPointer=event=>{const rect=svg.getBoundingClientRect(),viewX=(event.clientX-rect.left)*(W/rect.width);
    return Math.max(0,Math.min(maxIndex,Math.round((viewX-ML)/(PW/CAP))));};
  ov.addEventListener('pointermove',event=>{const index=indexFromPointer(event);paintCursor(index);if(finePointer){
    tip.style.display='block';tip.style.left=(event.clientX+14)+'px';tip.style.top=(event.clientY-10)+'px';
    tip.innerHTML=`<b>M+${index} · 시작월 대비</b>`+visibleEras.filter(e=>o[e][index]!=null).map(e=>
      `<span class="tip-series" style="--tip-series:${ERA_META[e][1]}"><i aria-hidden="true"></i><span>${esc(ERA_META[e][0])}<small>${esc(monthAt(ERA_START[e],index))}</small></span><strong>${num(o[e][index])}</strong></span>`).join('');}});
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
function flowAxisTickIndexes(length,maxTicks=7){
  if(length<=maxTicks)return Array.from({length},(_,index)=>index);
  return [...new Set(Array.from({length:maxTicks},(_,index)=>Math.round(index*(length-1)/(maxTicks-1))))];
}
function drawFlow(host,sc,focus='ALL',lookupDate=null,horizonDays=126){
  const NS='http://www.w3.org/2000/svg';
  const W=1160,H=590,ML=58,MR=140,MT=96,MB=30,HCH=506;
  const endIndex=flowHorizonEndIndex(sc,horizonDays),n=endIndex+1,weeks=sc.weeks.slice(0,n),weekDates=(sc.week_dates||[]).slice(0,n),riskValues=sc.risk.slice(0,n);
  const fanAll=sc.fan?.quantiles||{},fan=Object.fromEntries(Object.entries(fanAll).map(([key,values])=>[key,Array.isArray(values)?values.slice(0,n):values]));
  const chartValues=[sc.ath,sc.corr10,...['S1','S2','S3'].flatMap(key=>(sc.paths[key]?.values||[]).slice(0,n)),...(fan.p10||[]),...(fan.p90||[])].filter(Number.isFinite);
  const chartLow=Math.min(...chartValues),chartHigh=Math.max(...chartValues),chartPad=Math.max(500,(chartHigh-chartLow)*.08);
  const Y0=Math.floor((chartLow-chartPad)/500)*500,Y1=Math.ceil((chartHigh+chartPad)/500)*500;
  const PW=W-ML-MR,PH=HCH-MT-MB,X=index=>ML+PW*index/Math.max(1,n-1),Y=value=>MT+PH*(1-(value-Y0)/(Y1-Y0));
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width','100%');
  const horizonLabel=horizonDays===126?'6개월':'전체 252거래일';
  svg.setAttribute('role','img');svg.setAttribute('tabindex','0');svg.setAttribute('aria-label',`${sc.asof} 현재 기준 ${horizonLabel} 조건부 시나리오. 좌우 화살표로 기준 주차 이동`);
  const mk=(tag,attrs)=>{const node=document.createElementNS(NS,tag);for(const key in attrs)node.setAttribute(key,attrs[key]);return node;};
  const tx=(x,y,value,opts={})=>{const node=mk('text',{x,y,fill:opts.fill||'rgba(17,17,15,.66)','font-size':opts.fs||12,'text-anchor':opts.anc||'start','font-weight':opts.w||400,opacity:opts.opacity??1});node.textContent=value;return node;};
  const gridStep=Math.max(500,Math.ceil(((Y1-Y0)/6)/500)*500);
  for(let value=Math.ceil(Y0/gridStep)*gridStep;value<=Y1;value+=gridStep){svg.appendChild(mk('line',{x1:ML,y1:Y(value),x2:ML+PW,y2:Y(value),stroke:'rgba(17,17,15,.09)','stroke-width':1}));svg.appendChild(tx(ML-8,Y(value)+4,(value/1000)+'k',{anc:'end',fill:'#5f5d57'}));}
  svg.appendChild(mk('line',{x1:ML,y1:Y(sc.ath),x2:ML+PW,y2:Y(sc.ath),stroke:'rgba(17,17,15,.3)','stroke-width':1,'stroke-dasharray':'5 4'}));
  svg.appendChild(tx(ML+PW+6,Y(sc.ath)+4,'전고점 '+num(sc.ath),{fill:'rgba(17,17,15,.6)'}));
  svg.appendChild(mk('line',{x1:ML,y1:Y(sc.corr10),x2:ML+PW,y2:Y(sc.corr10),stroke:'rgba(255,128,102,.55)','stroke-width':1,'stroke-dasharray':'5 4'}));
  svg.appendChild(tx(ML+PW+6,Y(sc.corr10)+4,'−10% '+num(sc.corr10),{fill:'#c9002d'}));
  (sc.events||[]).filter(([index])=>index<=endIndex).forEach(([index,label,row])=>{const x=X(index),laneY=row===0?18:43;
    svg.appendChild(mk('line',{x1:x,y1:MT-5,x2:x,y2:MT+PH,stroke:'rgba(17,17,15,.13)','stroke-width':1,'stroke-dasharray':'2 4'}));
    svg.appendChild(mk('circle',{cx:x,cy:laneY+10,r:2.2,fill:'rgba(17,17,15,.55)'}));svg.appendChild(tx(x,laneY+5,label,{anc:'middle',fill:'#4f4d47',fs:12,w:600}));});
  if(fan?.p10?.length===n&&fan?.p90?.length===n){
    const band=(upper,lower,fill,opacity)=>{let d='';upper.forEach((value,index)=>d+=(index?'L':'M')+X(index)+','+Y(value)+' ');for(let index=lower.length-1;index>=0;index--)d+='L'+X(index)+','+Y(lower[index])+' ';svg.appendChild(mk('path',{d:d+'Z',fill,opacity}));};
    band(fan.p90,fan.p10,'#ff9d19',focus==='ALL'?.11:.025);if(fan.p25&&fan.p75)band(fan.p75,fan.p25,'#ff9d19',focus==='ALL'?.16:.04);
    if(fan.p50){let median='';fan.p50.forEach((value,index)=>median+=(index?'L':'M')+X(index)+','+Y(value)+' ');svg.appendChild(mk('path',{d:median,fill:'none',stroke:'#9a6700','stroke-width':1.4,'stroke-dasharray':'3 3',opacity:focus==='ALL'?.74:.12}));}
  }
  ['S1','S2','S3'].forEach(key=>{const path=sc.paths[key],values=path.values.slice(0,n),color=CHART_COL[key],on=focus==='ALL'||focus===key;let d='';values.forEach((value,index)=>d+=(index?'L':'M')+X(index)+','+Y(value)+' ');
    svg.appendChild(mk('path',{d,fill:'none',stroke:color,'stroke-width':on?(key==='S1'?3:2.6):1.2,'stroke-linejoin':'round',opacity:on?1:.1}));const endValue=values.at(-1);
    svg.appendChild(mk('circle',{cx:X(n-1),cy:Y(endValue),r:on?4:2.5,fill:color,stroke:'#0b1714','stroke-width':1.5,opacity:on?1:.12}));svg.appendChild(tx(X(n-1)+8,Y(endValue)+4,`${num(endValue)} · ${path.prob}%`,{fill:CHART_LABEL_COL[key],fs:12,w:700,opacity:on?1:.12}));});
  if(lookupDate&&weekDates.length===n&&lookupDate<=weekDates.at(-1)){let position=0;const next=weekDates.findIndex(day=>day>=lookupDate);
    if(next<0)position=n-1;else if(next===0||weekDates[next]===lookupDate)position=next;else{const left=ForecastLookup.parseIso(weekDates[next-1]),right=ForecastLookup.parseIso(weekDates[next]),target=ForecastLookup.parseIso(lookupDate);position=next-1+(target-left)/(right-left);}
    const markerX=X(position),labelX=Math.max(ML+44,Math.min(ML+PW-44,markerX));svg.appendChild(mk('line',{x1:markerX,y1:MT-4,x2:markerX,y2:MT+PH,stroke:'#1f6feb','stroke-width':2,'stroke-dasharray':'5 3'}));
    svg.appendChild(mk('line',{x1:labelX,y1:78,x2:markerX,y2:MT-5,stroke:'#8bb3e8','stroke-width':1}));svg.appendChild(mk('rect',{x:labelX-42,y:58,width:84,height:22,rx:11,fill:'#eaf2ff',stroke:'#8bb3e8'}));
    svg.appendChild(tx(labelX,73,'조회 '+lookupDate.slice(5),{anc:'middle',fill:'#174ea6',fs:12,w:750}));svg.appendChild(mk('circle',{cx:markerX,cy:MT-4,r:4,fill:'#1f6feb',stroke:'#fff','stroke-width':1.5}));}
  svg.appendChild(mk('circle',{cx:X(0),cy:Y(sc.anchor),r:4,fill:'#11110f',stroke:'#fff','stroke-width':1.5}));svg.appendChild(tx(X(0)-6,Y(sc.anchor)-10,num(Math.round(sc.anchor)),{fill:'#11110f',w:600}));
  const tickIndexes=flowAxisTickIndexes(n,7);let priorTickYear='';tickIndexes.forEach((index,tickPosition)=>{const iso=weekDates[index]||'',year=iso.slice(0,4),yearChanged=year&&year!==priorTickYear;let label=weeks[index];
    if(tickPosition===0)label='현재 · '+label;else if(yearChanged)label=year.slice(2)+'년 · '+label;priorTickYear=year||priorTickYear;
    svg.appendChild(mk('line',{x1:X(index),y1:MT+PH,x2:X(index),y2:MT+PH+5,stroke:'rgba(17,17,15,.28)'}));svg.appendChild(tx(X(index),MT+PH+18,label,{anc:'middle',fs:12,fill:index?'#5f5d57':'#174c49',w:index?500:750}));});
  const RY=HCH+8,RH=28;svg.appendChild(tx(ML-8,RY+19,'변동성',{anc:'end',fill:'#5f5d57',fs:12}));
  let segmentStart=0;for(let index=1;index<=n;index++){if(index<n&&riskValues[index]===riskValues[segmentStart])continue;const end=index-1,risk=riskValues[segmentStart];
    const left=segmentStart===0?X(0)-2:(X(segmentStart-1)+X(segmentStart))/2,right=end===n-1?X(end)+2:(X(end)+X(end+1))/2,width=Math.max(1,right-left);
    const fill=risk==='고'?'rgba(201,0,45,.92)':(risk==='중'?'rgba(255,157,25,.48)':'rgba(36,125,120,.34)'),textColor=risk==='고'?'#fff':(risk==='중'?'#513300':'#174c49');svg.appendChild(mk('rect',{x:left,y:RY,width,height:RH,fill,stroke:'rgba(17,17,15,.1)'}));
    if(width>=28)svg.appendChild(tx(left+width/2,RY+18,risk,{anc:'middle',fs:12,fill:textColor,w:700}));segmentStart=index;}
  const xh=mk('line',{stroke:'rgba(17,17,15,.44)','stroke-width':1.2,'stroke-dasharray':'4 3',opacity:1});svg.appendChild(xh);
  const cursorMarkers=['S1','S2','S3'].map(key=>{const marker=mk('circle',{r:5.4,fill:CHART_COL[key],stroke:'#fff','stroke-width':2});svg.appendChild(marker);return marker;});
  const overlay=mk('rect',{x:ML,y:MT,width:PW,height:PH,fill:'transparent'});svg.appendChild(overlay);const tip=document.getElementById('tip'),finePointer=window.matchMedia('(pointer: fine)').matches;
  const readout=document.createElement('div');readout.className='flow-readout';readout.style.setProperty('--flow-count','4');let cursorIndex=0;
  const paintCursor=index=>{cursorIndex=Math.max(0,Math.min(n-1,index));const x=X(cursorIndex),week=weeks[cursorIndex],risk=riskValues[cursorIndex];xh.setAttribute('x1',x);xh.setAttribute('x2',x);xh.setAttribute('y1',MT);xh.setAttribute('y2',MT+PH);
    ['S1','S2','S3'].forEach((key,markerIndex)=>{cursorMarkers[markerIndex].setAttribute('cx',x);cursorMarkers[markerIndex].setAttribute('cy',Y(sc.paths[key].values[cursorIndex]));});
    readout.innerHTML=`<div class="flow-date"><span>SELECTED WEEK</span><strong>${esc(week)}</strong><small>변동성 ${esc(risk)}</small></div>${['S1','S2','S3'].map(key=>`<div><span>${esc(sc.paths[key].label)}</span><strong style="color:${CHART_LABEL_COL[key]}">${num(sc.paths[key].values[cursorIndex])}</strong><small>경로 가중치 ${sc.paths[key].prob}%</small></div>`).join('')}`;svg.setAttribute('aria-label',`${sc.asof} 현재 기준 ${horizonLabel}, 선택 주차 ${week}, 변동성 ${risk}. 좌우 화살표로 이동`);};
  const indexFromPointer=event=>{const rect=svg.getBoundingClientRect(),mouseX=(event.clientX-rect.left)*(W/rect.width);return Math.max(0,Math.min(n-1,Math.round((mouseX-ML)/(PW/Math.max(1,n-1)))));};
  overlay.addEventListener('pointermove',event=>{const index=indexFromPointer(event);paintCursor(index);if(finePointer){tip.style.display='block';tip.style.left=(event.clientX+14)+'px';tip.style.top=(event.clientY-10)+'px';tip.innerHTML=`<b>${weeks[index]}</b> · 변동성 ${riskValues[index]}<br><span style="color:${CHART_COL.S1}">${esc(sc.paths.S1.label)} ${num(sc.paths.S1.values[index])}</span><br><span style="color:${CHART_COL.S2}">${esc(sc.paths.S2.label)} ${num(sc.paths.S2.values[index])}</span><br><span style="color:${CHART_COL.S3}">${esc(sc.paths.S3.label)} ${num(sc.paths.S3.values[index])}</span>`;}});
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
  const chart=el(`<div class="chart-panel analysis-panel"><div class="panel-head"><h2>예측 확률 회차 비교</h2><div class="band-inline">${qs.map((q,i)=>`<span><b style="background:${COMPARE_COLORS[i]}"></b>${esc(q.title.length>24?q.title.slice(0,24)+'…':q.title)}</span>`).join('')}</div></div><div class="chart-wrap"><div id="compare-history" class="compare-history-shell"></div></div><p class="chart-note">커서 값은 선택 날짜 이전의 최신 회차입니다. 차트 위를 움직이거나 좌우 화살표로 날짜를 이동하세요. 질문 간 확률의 합이나 상대 성과를 뜻하지 않습니다.</p></div>`);
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
  return decodeForecastBody(round?.body).trim()||'이 회차에는 저장된 근거 원문이 없습니다. 확률·신뢰구간·출처 수 등 구조화 기록은 위의 변화 요약에서 확인할 수 있습니다.';
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
function renderAsof(){
  const dates=[...DATA.questions.map(q=>q.latest_ts).filter(Boolean),...DATA.ml_runs.map(m=>m.run_ts)].map(s=>s.slice(0,10));
  const maxd=dates.reduce((a,b)=>a>b?a:b,'2026-07-08');
  const root=el('<div></div>');
  root.appendChild(el(`<div class="page-heading"><div>
    <p class="eyebrow">시점 조회 · As-of Rebuild</p>
    <h1>특정 날짜의 예측 상태를 재구성합니다</h1>
    <p class="page-lede">선택 날짜 이후 데이터는 배제하고, 그 시점에 알 수 있던 최신 예측만 표시합니다.</p>
  </div>
    <label class="asof-control">기준일<input type="date" id="ad" value="${maxd}" max="${maxd}"><span style="margin-top:10px">이 날짜까지의 최신 예측</span></label>
  </div>`));
  const cont=el('<div class="table-shell"><table id="atbl"></table></div>');
  root.appendChild(cont);
  mount(root);
  const draw=()=>{const D=$('#ad').value;
    const rows=DATA.questions.map(q=>{const hist=(DATA.forecast_history[q.id]||[]).filter(h=>(h.forecast_ts||'')<=D+' 23:59');
      if(!hist.length)return null;const h=hist[hist.length-1];
      const ml=DATA.ml_runs.filter(m=>m.question_id===q.id&&m.run_ts.slice(0,10)<=D).slice(-1)[0];
      const mk=DATA.market_runs.filter(m=>m.question_id===q.id&&m.run_ts.slice(0,10)<=D).slice(-1)[0];return {q,h,ml,mk};}).filter(Boolean);
    $('#atbl').innerHTML=`<caption class="sr-only">${esc(D)} 기준 예측 상태</caption><thead><tr><th scope="col">예측 질문</th><th scope="col" class="r">AI 예측</th><th scope="col" class="r">모델 앙상블</th><th scope="col" class="r">시장 반영</th><th scope="col" class="r">AI−시장 edge</th><th scope="col" class="r">예측일</th></tr></thead>
    <tbody>${rows.map(({q,h,ml,mk})=>{const edge=mk!=null?(h.probability-Math.round(mk.prob*100)):null;
      const ecls=edge==null?'':(edge>=0?'edge-pos':'edge-neg');
      return `<tr tabindex="0" data-q="${esc(q.id)}"><td><b>${esc(q.title)}</b></td>
      <td class="r"><span class="table-prob">${h.probability}%</span></td>
      <td class="r num">${ml?pct(ml.prob):'—'}</td><td class="r num">${mk?pct(mk.prob):'—'}</td>
      <td class="r num ${ecls}">${edge==null?'—':(edge>=0?'+':'')+edge+'%p'}</td>
      <td class="r num">${(h.forecast_ts||'').slice(0,10)}</td></tr>`;}).join('')}</tbody>`;
    $('#atbl').querySelectorAll('tr[data-q]').forEach(tr=>{const go=()=>location.hash='#q/'+tr.dataset.q;tr.onclick=go;tr.onkeydown=e=>{if(e.key==='Enter')go();};});};
  root.querySelector('#ad').onchange=draw;draw();
}

function renderAsofTimeMachine(){
  const dates=[...new Set([
    ...Object.values(DATA.forecast_history||{}).flat().map(h=>(h.forecast_ts||'').slice(0,10)),
    ...(DATA.ml_runs||[]).map(m=>(m.run_ts||'').slice(0,10)),
    ...(DATA.market_runs||[]).map(m=>(m.run_ts||'').slice(0,10)),
    ...(DATA.asof_index||[]).map(item=>(item.asof||'').slice(0,10))
  ].filter(Boolean))].sort();
  if(!dates.length)dates.push(generatedDay());
  const first=dates[0],maxd=dates[dates.length-1];
  const root=el('<div></div>');
  appendContextTabs(root,'replay','asof');
  root.appendChild(el(`<div class="page-heading"><div>
    <p class="eyebrow">시점 조회 · As-of Time Machine</p>
    <h1>그날의 판단과 지금의 판단을 나란히 봅니다</h1>
    <p class="page-lede">선택한 날짜 이후의 정보는 배제한 뒤, 당시 최신 예측이 현재까지 얼마나 움직였는지 비교합니다.</p>
  </div></div>`));
  const machine=el(`<section class="time-machine" aria-labelledby="time-machine-title">
    <div class="time-machine-head"><div><span class="radar-eyebrow">AS-OF REBUILD · ${dates.length} DATA DATES</span><h2 id="time-machine-title">예측 변화 타임머신</h2></div>
      <div><output id="tm-output" for="tm-range">${maxd}</output><label class="time-machine-date">직접 선택 <input type="date" id="tm-date" min="${first}" max="${maxd}" value="${maxd}"></label></div></div>
    <div class="time-scrubber"><button type="button" id="tm-prev" aria-label="이전 데이터 날짜">←</button><input type="range" id="tm-range" min="0" max="${dates.length-1}" value="${dates.length-1}" step="1" aria-label="데이터 날짜 이동"><button type="button" id="tm-next" aria-label="다음 데이터 날짜">→</button></div>
    <div class="time-summary" id="tm-summary"></div><div class="time-movers" id="tm-movers"></div>
  </section>`);
  root.appendChild(machine);
  const table=el('<div class="table-shell"><table id="tm-table"></table></div>');
  root.appendChild(table);mount(root);
  const rowsAt=D=>DATA.questions.map(q=>{
    const hist=(DATA.forecast_history?.[q.id]||[]).filter(h=>(h.forecast_ts||'').slice(0,10)<=D);
    if(!hist.length)return null;
    const h=hist[hist.length-1],latest=(DATA.forecast_history?.[q.id]||[]).slice(-1)[0]||h;
    const ml=(DATA.ml_runs||[]).filter(m=>m.question_id===q.id&&(m.run_ts||'').slice(0,10)<=D).slice(-1)[0];
    const mk=(DATA.market_runs||[]).filter(m=>m.question_id===q.id&&(m.run_ts||'').slice(0,10)<=D).slice(-1)[0];
    return {q,h,latest,ml,mk,change:Number(latest.probability)-Number(h.probability)};
  }).filter(Boolean);
  const draw=D=>{
    const rows=rowsAt(D),changed=rows.filter(x=>Math.abs(x.change)>=1),rising=rows.filter(x=>x.change>0).length,falling=rows.filter(x=>x.change<0).length;
    const avg=rows.length?rows.reduce((sum,x)=>sum+Math.abs(x.change),0)/rows.length:0;
    $('#tm-output',machine).textContent=D;
    $('#tm-summary',machine).innerHTML=`<div><span>현재까지 변경</span><strong>${changed.length} / ${rows.length}</strong></div><div><span>평균 절대 변화</span><strong>${avg.toFixed(1)}%p</strong></div><div><span>방향 분포</span><strong>↑ ${rising} · ↓ ${falling}</strong></div>`;
    const movers=[...rows].sort((a,b)=>Math.abs(b.change)-Math.abs(a.change)).slice(0,3);
    $('#tm-movers',machine).innerHTML=movers.map(x=>`<button type="button" data-q="${esc(x.q.id)}"><span>${esc(x.q.title)}</span><strong class="${x.change>0?'edge-pos':x.change<0?'edge-neg':''}">${x.change>0?'+':''}${x.change.toFixed(0)}%p</strong></button>`).join('')||'<p class="empty">이 시점에 비교할 예측이 없습니다.</p>';
    $('#tm-table',table).innerHTML=`<caption class="sr-only">${esc(D)} 당시와 현재의 예측 비교</caption><thead><tr><th scope="col">예측 질문</th><th scope="col">분류</th><th scope="col" class="r">당시 AI</th><th scope="col" class="r">모델 앙상블</th><th scope="col" class="r">시장 반영</th><th scope="col" class="r">현재까지 Δ</th><th scope="col" class="r">당시 예측일</th></tr></thead>
      <tbody>${rows.map(({q,h,ml,mk,change})=>`<tr tabindex="0" data-q="${esc(q.id)}"><td><b>${esc(q.title)}</b></td><td>${esc(humanDomain(q.domain))}</td>
        <td class="r"><span class="table-prob">${h.probability}%</span></td><td class="r num">${ml?pct(ml.prob):'—'}</td><td class="r num">${mk?pct(mk.prob):'—'}</td>
        <td class="r num ${change>0?'edge-pos':change<0?'edge-neg':''}">${change>0?'+':''}${change.toFixed(0)}%p</td><td class="r num">${(h.forecast_ts||'').slice(0,10)}</td></tr>`).join('')}</tbody>`;
    root.querySelectorAll('[data-q]').forEach(node=>{const go=()=>location.hash='#q/'+node.dataset.q;node.onclick=go;node.onkeydown=e=>{if(e.key==='Enter')go();};});
    const i=Math.max(0,dates.findLastIndex(date=>date<=D));$('#tm-range',machine).value=String(i);
    $('#tm-prev',machine).disabled=i<=0;$('#tm-next',machine).disabled=i>=dates.length-1;
  };
  const selectIndex=i=>{const safe=Math.max(0,Math.min(dates.length-1,i)),D=dates[safe];$('#tm-range',machine).value=String(safe);$('#tm-date',machine).value=D;draw(D);};
  $('#tm-range',machine).oninput=e=>selectIndex(+e.target.value);
  $('#tm-date',machine).onchange=e=>draw(e.target.value||maxd);
  $('#tm-prev',machine).onclick=()=>selectIndex(+$(`#tm-range`,machine).value-1);
  $('#tm-next',machine).onclick=()=>selectIndex(+$(`#tm-range`,machine).value+1);
  draw(maxd);
}

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
  appendContextTabs(root,'replay','asof');
  root.appendChild(el(`<div class="page-heading"><div><p class="eyebrow">DECISION JOURNAL · IMMUTABLE HISTORY</p><h1>예측 변경 일지</h1><p class="page-lede">언제, 무엇이, 왜 바뀌었는지 지우지 않고 쌓는 기록입니다. 과거 판단을 현재 정보로 덮어쓰지 않습니다.</p></div></div>`));
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
  $('#journal-date',replay).onchange=event=>{drawReplay(event.target.value);history.replaceState(null,'',`#asof=${event.target.value}`);};
  replay.querySelectorAll('[data-replay-date]').forEach(button=>button.onclick=()=>{const value=button.dataset.replayDate;$('#journal-date',replay).value=value;drawReplay(value);});
  replay.querySelectorAll('[data-replay-offset]').forEach(button=>button.onclick=()=>{const d=new Date(`${maxd}T12:00:00Z`);d.setUTCDate(d.getUTCDate()+Number(button.dataset.replayOffset));const value=Math.max(Date.parse(first),d.getTime())===Date.parse(first)?first:d.toISOString().slice(0,10);$('#journal-date',replay).value=value;drawReplay(value);});
  setMode(state.mode==='replay'?'replay':'feed');
}
VIEWS.asof=renderDecisionJournal;

function renderTrack(){
  const c=DATA.calibration,g=c.gate,gv2=c.gate_v2||{},clusters=DATA.clusters||[],unique=gv2.n_events??clusters.length;
  const root=el('<div></div>');
  root.appendChild(el(`<div class="page-heading"><div>
    <p class="eyebrow">적중 이력 · Calibration</p>
    <h1>확정된 예측의 정확도를 검증합니다</h1>
    <p class="page-lede">예측 확률과 실제 결과의 간격을 기록합니다. 표본이 충분해지기 전에는 성능 판단을 유보합니다.</p>
  </div></div>`));
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
  const trust=DATA.trust||{sources:[]},arena=DATA.arena||[],corrections=DATA.corrections||[],receipt=(DATA.receipts||[])[0]||{};
  const ledgerRows=trust.ledgers||[],ledgerSummary=trust.ledger_summary||{};
  if(ledgerRows.length)root.appendChild(el(`<section class="ledger-status-panel" aria-labelledby="ledger-status-title"><div class="panel-head"><div><p class="eyebrow">LEDGER ACCUMULATION</p><h2 id="ledger-status-title">데이터 원장이 실제로 쌓이고 있는가</h2></div><span class="semantic-state">위반 ${ledgerSummary.violation||0}</span></div><div class="ledger-status-grid">${ledgerRows.map(row=>{const points=row.growth_last_30d||[],growth=points.length>1?points.at(-1).count-points[0].count:0;return `<article class="ledger-state-${esc(row.status)}"><div><strong>${esc(row.id)}</strong><span>${esc(row.status)}</span></div><p>${row.file_count} files${row.row_count!=null?` · ${row.row_count} rows`:''}</p><small>latest ${esc(row.latest_date||'not started')} · 30일 +${growth}</small>${row.missing_trading_days?.length?`<em>누락 거래일 ${row.missing_trading_days.map(esc).join(', ')}</em>`:''}</article>`;}).join('')}</div><footer>감사 시각 ${esc(trust.ledger_audit_at||'미산출')} · stalled는 운영 경고, violation은 불변성·스키마 위반입니다.</footer></section>`));
  root.appendChild(el(`<section class="intelligence-stack" aria-label="검증 상세">
    <details class="trust-center" open><summary><span><b>Trust Center</b><small>출처 · 신선도 · 빈티지 · 계약</small></span><em>${trust.status==='ok'?'정상':'확인 필요'}</em></summary>
      <div class="trust-grid">${(trust.sources||[]).length?(trust.sources||[]).map(s=>`<article><div><strong>${esc(s.name)}</strong><span class="source-state ${s.status}">${esc(s.state_label||s.status)}</span></div><p>${esc(s.provider)} · ${esc(s.vintage_capability)} vintage</p><small>SLA ${s.freshness_sla_hours??'—'}h · ${esc(s.license_status||'미산출')}</small></article>`).join(''):'<p class="empty-copy">등록된 출처가 없습니다.</p>'}</div>
      <div class="index-receipt"><span>INDEX RECEIPT</span><code>${esc((trust.index?.source_fingerprint||'미산출').slice(0,16))}</code><small>${esc(trust.index?.branch||'미산출')}</small></div>
    </details>
    <div class="panel model-arena"><div class="panel-head"><div><p class="eyebrow">MODEL ARENA</p><h2>기준선과 shadow 후보</h2></div><span class="semantic-state">승격 비활성</span></div>
      <div class="arena-list">${arena.map(m=>`<article><div><strong>${esc(m.name)}</strong><span class="lifecycle ${esc(m.lifecycle)}">${esc(m.lifecycle)}</span></div><p>${esc(m.target)}</p><small>${m.n_insufficient?'paired 표본 부족':esc(JSON.stringify(m.metrics))}</small><details><summary>한계 보기</summary><p>${esc(m.limitations||'미산출')}</p></details></article>`).join('')}</div>
    </div>
    <div class="audit-grid">
      <details class="panel receipt-card"><summary>MODEL RECEIPT · 현재 시나리오</summary><dl><div><dt>모델</dt><dd>${esc(receipt.model||'미산출')}</dd></div><div><dt>데이터</dt><dd>${esc(receipt.dataset||'미산출')}</dd></div><div><dt>출처</dt><dd>${esc(receipt.source||'미산출')}</dd></div><div><dt>커밋</dt><dd>${esc((receipt.commit||'미산출').slice(0,12))}</dd></div></dl><p>${esc(receipt.limitation||'미산출')}</p></details>
      <details class="panel correction-card"><summary>정정 원장 · ${corrections.length}건</summary>${corrections.length?corrections.map(row=>`<article><span class="semantic-state">${esc(row.status==='pending'?'보정 대기':row.status)}</span><strong>${esc(row.field_name)} · ${esc(row.old_value||'미산출')}</strong><p>${esc(row.reason)}</p></article>`).join(''):'<p class="empty-copy">정정 기록이 없습니다.</p>'}</details>
      <details class="panel semantics-card"><summary>확률 시맨틱 범례</summary><p>${esc(DATA.probability_semantics?.guardrail||'미산출')}</p>${Object.entries(DATA.probability_semantics?.spaces||{}).map(([space,label])=>`<div><code>${esc(space)}</code><span>${esc(label)}</span></div>`).join('')}</details>
    </div>
  </section>`));
  mount(root);
}

// ── 기간 조회 ──
function weekDate(label,asof=DATA?.scenario?.asof){
  const [m,d]=label.split('/').map(Number),base=new Date(`${asof}T00:00:00`),year=base.getFullYear();
  return new Date(year,m-1,d);
}
function nearestWeekIndex(sc,target){
  let best=0,distance=Infinity;
  sc.weeks.forEach((week,index)=>{const delta=Math.abs(weekDate(week,sc.asof)-target);if(delta<distance){distance=delta;best=index;}});
  return best;
}
function askPresets(sc){
  const start=new Date(`${sc.asof}T00:00:00`),year=start.getFullYear(),rows=[],seen=new Set();
  for(let month=start.getMonth();month<12;month++){
    const target=new Date(year,month+1,0);
    if(target<=start)continue;
    const index=nearestWeekIndex(sc,target);
    if(index<=0||seen.has(index))continue;
    seen.add(index);
    rows.push([month===11?'연말 12/31':`${month+1}월말`,index]);
  }
  return rows;
}
function bizDates(s,e){const out=[];let d=new Date(s);while(d<=e){const w=d.getDay();if(w!==0&&w!==6)out.push(new Date(d));d.setDate(d.getDate()+1);}return out;}
function interpAt(vals,wdts,t){
  if(t<=wdts[0])return vals[0];
  for(let i=0;i<wdts.length-1;i++){if(t>=wdts[i]&&t<=wdts[i+1]){const f=(t-wdts[i])/(wdts[i+1]-wdts[i]);return vals[i]+f*(vals[i+1]-vals[i]);}}
  return vals[vals.length-1];
}
function drawDaily(host,sc,endIdx){
  const NS='http://www.w3.org/2000/svg';
  const wdts=sc.weeks.map(w=>weekDate(w));
  const dates=bizDates(wdts[0],wdts[endIdx]);
  const keys=['S1','S2','S3'];
  const ser={};keys.forEach(k=>ser[k]=dates.map(t=>interpAt(sc.paths[k].values,wdts,t)));
  const all=[].concat(...keys.map(k=>ser[k]));
  let ymin=Math.min(...all),ymax=Math.max(...all);const pad=(ymax-ymin)*0.08||100;ymin-=pad;ymax+=pad;
  const W=1000,H=380,ML=52,MR=118,MT=20,MB=32,PW=W-ML-MR,PH=H-MT-MB;
  const t0=+dates[0],t1=+dates[dates.length-1];
  const X=t=>ML+PW*((+t-t0)/Math.max(1,t1-t0)),Y=v=>MT+PH*(1-(v-ymin)/(ymax-ymin));
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width','100%');
  const mk=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;};
  const tx=(x,y,s,o={})=>{const e=mk('text',{x,y,fill:o.fill||'#5f5d57','font-size':o.fs||12,'text-anchor':o.anc||'start','font-weight':o.w||400});e.textContent=s;return e;};
  for(let g=0;g<=4;g++){const v=ymin+(ymax-ymin)*g/4;svg.appendChild(mk('line',{x1:ML,y1:Y(v),x2:ML+PW,y2:Y(v),stroke:'rgba(17,17,15,.09)'}));
    svg.appendChild(tx(ML-8,Y(v)+4,(Math.round(v/10)*10).toLocaleString(),{anc:'end',fill:'rgba(17,17,15,.5)'}));}
  if(sc.ath<=ymax&&sc.ath>=ymin){svg.appendChild(mk('line',{x1:ML,y1:Y(sc.ath),x2:ML+PW,y2:Y(sc.ath),stroke:'rgba(17,17,15,.3)','stroke-width':1,'stroke-dasharray':'5 4'}));
    svg.appendChild(tx(ML+PW+6,Y(sc.ath)+4,'전고점',{fill:'rgba(17,17,15,.6)'}));}
  const up=dates.map((t,i)=>Math.max(ser.S1[i],ser.S2[i],ser.S3[i]));
  const dn=dates.map((t,i)=>Math.min(ser.S1[i],ser.S2[i],ser.S3[i]));
  let dband='';up.forEach((v,i)=>dband+=(i?'L':'M')+X(dates[i])+','+Y(v)+' ');
  for(let i=dn.length-1;i>=0;i--)dband+='L'+X(dates[i])+','+Y(dn[i])+' ';
  svg.appendChild(mk('path',{d:dband+'Z',fill:'#ff4f17',opacity:.08}));
  keys.forEach(k=>{const col=CHART_COL[k];let d='';ser[k].forEach((v,i)=>d+=(i?'L':'M')+X(dates[i])+','+Y(v)+' ');
    svg.appendChild(mk('path',{d,fill:'none',stroke:col,'stroke-width':k==='S1'?2.6:1.8,'stroke-linejoin':'round',opacity:k==='S1'?1:.9}));
    const ev=ser[k][ser[k].length-1];
    svg.appendChild(mk('circle',{cx:X(dates[dates.length-1]),cy:Y(ev),r:3.4,fill:col,stroke:'#0b1714','stroke-width':1.5}));
    svg.appendChild(tx(X(dates[dates.length-1])+8,Y(ev)+4,`${num(Math.round(ev))} ${sc.paths[k].prob}%`,{fill:CHART_LABEL_COL[k],fs:12,w:700}));});
  svg.appendChild(mk('circle',{cx:X(dates[0]),cy:Y(ser.S1[0]),r:4,fill:'#11110f',stroke:'#fff','stroke-width':1.5}));
  svg.appendChild(tx(X(dates[0])-4,Y(ser.S1[0])-9,num(Math.round(sc.anchor)),{fill:'#11110f',w:600,anc:'start'}));
  let lastM=-1;dates.forEach(t=>{const m=t.getMonth();if(m!==lastM){lastM=m;
    svg.appendChild(mk('line',{x1:X(t),y1:MT,x2:X(t),y2:MT+PH,stroke:'rgba(17,17,15,.08)'}));
    svg.appendChild(tx(X(t),MT+PH+16,(m+1)+'월',{anc:'middle',fs:12,fill:'#5f5d57'}));}});
  const xh=mk('line',{stroke:'rgba(17,17,15,.38)','stroke-width':1,opacity:0});svg.appendChild(xh);
  const ov=mk('rect',{x:ML,y:MT,width:PW,height:PH,fill:'transparent'});svg.appendChild(ov);
  const tip=document.getElementById('tip');
  ov.addEventListener('mousemove',e=>{const r=svg.getBoundingClientRect();const mx=(e.clientX-r.left)*(W/r.width);
    let bi=0,bd=1e15;dates.forEach((t,i)=>{const dd=Math.abs(X(t)-mx);if(dd<bd){bd=dd;bi=i;}});
    xh.setAttribute('x1',X(dates[bi]));xh.setAttribute('x2',X(dates[bi]));xh.setAttribute('y1',MT);xh.setAttribute('y2',MT+PH);xh.setAttribute('opacity',.4);
    tip.style.display='block';tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY-10)+'px';
    const dd=dates[bi];
    tip.innerHTML=`<b>${(dd.getMonth()+1)}/${dd.getDate()}</b><br>
      <span style="color:${CHART_COL.S1}">기본 ${num(Math.round(ser.S1[bi]))}</span><br>
      <span style="color:${CHART_COL.S2}">중립 ${num(Math.round(ser.S2[bi]))}</span><br>
      <span style="color:${CHART_COL.S3}">조정 ${num(Math.round(ser.S3[bi]))}</span>`;});
  ov.addEventListener('mouseleave',()=>{tip.style.display='none';xh.setAttribute('opacity',0);});
  host.appendChild(svg);
}
function renderAsk(){
  const sc=DATA.scenario;const now=DATA.meta.generated.slice(0,10);
  const endIndex=sc.weeks.length-1,endDate=`${sc.asof.slice(0,4)}-12-31`;
  const root=el('<div></div>');
  appendContextTabs(root,'replay','ask');
  root.appendChild(el(`<div class="page-heading"><div>
    <p class="eyebrow">기간 조회 · Range Projection</p>
    <h1>현시점에서 기간별 일별 전망을 그립니다</h1>
    <p class="page-lede">시나리오 기준 ${esc(sc.asof)} · 질문 데이터 기준 ${esc(now)}. 기간을 고르면 3경로의 일별 궤적과 예상 범위를 보여줍니다. 참고 의견이며 투자 자문이 아닙니다.</p>
  </div></div>`));
  root.appendChild(el(vintageReceipt()));
  const presets=askPresets(sc);
  const bar=el(`<div class="query-bar">
    <div class="preset-list">${presets.map(([l,i])=>`<button type="button" class="ask-p" data-i="${i}">${l}</button>`).join('')}</div>
    <label>종료일<input type="date" id="ad" min="${esc(sc.asof)}" max="${endDate}" value="${endDate}"></label>
    <button type="button" class="calendar-action" id="ask-calendar">현재 기간 일정 저장</button>
  </div>`);
  const out=el('<div id="ans"></div>');
  root.appendChild(bar);root.appendChild(out);
  mount(root);
  const answer=i=>{
    const wk=sc.weeks[i],anchor=sc.anchor,lv=k=>sc.paths[k].values[i];
    const vals=['S1','S2','S3'].map(lv),lo=Math.min(...vals),hi=Math.max(...vals);
    const sign=v=>{const x=(v/anchor-1)*100;return (x>=0?'+':'')+x.toFixed(1)+'%';};
    const wd=weekDate(wk,sc.asof);
    const inWin=DATA.questions.filter(q=>q.deadline&&q.deadline>=now&&new Date(q.deadline)<=wd).sort((a,b)=>a.deadline<b.deadline?-1:1);
    const evs=sc.events.filter(([xi])=>xi<=i+0.5&&xi>=0.5).map(([,l])=>l);
    const legend=`<div class="band-inline">${['S1','S2','S3'].map(k=>`<span><b style="background:${CHART_COL[k]}"></b>${esc(['기본','중립','조정'][['S1','S2','S3'].indexOf(k)])} ${sc.paths[k].prob}%</span>`).join('')}</div>`;
    out.innerHTML=`
    <div class="range-returns">
      <div><span>기본 (S1) · ${wk}</span><strong style="color:${CHART_LABEL_COL.S1}">${sign(lv('S1'))}</strong><small>${num(Math.round(lv('S1')))}</small></div>
      <div><span>중립 (S2) · ${wk}</span><strong style="color:${CHART_LABEL_COL.S2}">${sign(lv('S2'))}</strong><small>${num(Math.round(lv('S2')))}</small></div>
      <div><span>조정 (S3) · ${wk}</span><strong style="color:${CHART_LABEL_COL.S3}">${sign(lv('S3'))}</strong><small>${num(Math.round(lv('S3')))}</small></div>
    </div>
    <div class="chart-panel analysis-panel"><div class="panel-head"><h2>현재 → ${wk} · 일별 전망</h2>${legend}</div>
      <div class="chart-wrap"><div id="dchart" style="min-width:640px"></div></div>
      <p class="chart-note">${wk} 예상 범위 ${num(lo)}–${num(hi)} · 경로는 시나리오별 대표값(확률 가중 평균 아님)입니다.</p>
    </div>
    <div class="section-grid">
      <div class="panel"><div class="panel-head" style="margin-bottom:18px"><h2 style="font-size:clamp(20px,2vw,28px)">이 기간 주요 일정</h2></div>
        <div class="tag-list" style="justify-content:flex-start">${evs.length?evs.map(e=>`<span class="tag">${esc(e)}</span>`).join(' '):'<span class="empty" style="padding:0">해당 없음</span>'}</div></div>
      <div class="panel"><div class="panel-head" style="margin-bottom:18px"><h2 style="font-size:clamp(20px,2vw,28px)">확정 예정 예측</h2><span class="vintage-note">${inWin.length}건</span></div>
        <div class="deadline-list" style="border-top:1px solid var(--line)">${inWin.length?inWin.map(q=>`<button type="button" data-q="${esc(q.id)}"><time>${esc(q.deadline)}</time><span>${esc(q.title)}</span><strong>${p1(q.latest_prob)}</strong></button>`).join(''):'<p class="empty">이 기간 확정 예정 예측이 없습니다.</p>'}</div></div>
    </div>`;
    drawDaily($('#dchart',out),sc,i);
    out.querySelectorAll('button[data-q]').forEach(b=>b.onclick=()=>location.hash='#q/'+b.dataset.q);
    $('#ask-calendar',bar).onclick=()=>downloadQuestionCalendar(inWin.map(q=>q.id));
    bar.querySelectorAll('.ask-p').forEach(c=>c.classList.toggle('on',+c.dataset.i===i));
  };
  bar.querySelectorAll('.ask-p').forEach(c=>c.onclick=()=>{$('#ad',bar).value='';answer(+c.dataset.i);});
  $('#ad',bar).onchange=e=>answer(nearestWeekIndex(sc,new Date(`${e.target.value}T00:00:00`)));
  answer(endIndex);
}

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
