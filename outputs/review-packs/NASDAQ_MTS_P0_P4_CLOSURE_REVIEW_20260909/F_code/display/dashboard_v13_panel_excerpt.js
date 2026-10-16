/* 발췌 — src/ai_fc/dashboard_parts/dashboard.js 의 V13-VOL 패널 전체 구간.
   완결성 비평 S2-2. 검토관이 표시 정직성(홀드아웃 실패 셀 제거·역할 문구 철회·
   모바일 기본 지평)을 코드에서 직접 확인할 수 있게 동봉한다. */

/* ── V13-VOL 변동성 이벤트 기준율 패널 (docs/design/v13_vol_live_card_display_design_260908.md) ──
   X1 이름충돌 6항: ①명칭 '기준율'(예측 아님) ②출처 배지 상시 ③지평 단위 영업일(≈달력일) ④caveat lead 상시
   ⑤vix-25-90d 와의 역할 관계 + 괴리 표시만 ⑥결합·평균 산식 0. 숫자는 서버(read-model 가드)가 live 일 때만 싣는다.
   SVG 없음(표만) — 숨김 패널 rAF 함정 비적용. */
function timeseriesV13TabEnabled(v13){
  const tier=v13?.publication?.display_tier;
  if(tier==='t3_live_card')return true;
  if(tier==='t2_hidden_panel'){try{return new URLSearchParams(location.search).get('review')==='v13vol';}catch(_){return false;}}
  return false;
}
const V13_CELL_LABELS={vix25:'VIX 25 이상 터치',vix30:'VIX 30 이상 터치',rv:'실현변동성 > 16.9%(연율)'};
const V13_GUIDE_EVENT={vix25:'25를 터치한',vix30:'30을 터치한',rv:'16.9%(연율)를 넘은'};
const V13_GUIDE_ORDER=['vix25_h63','vix25_h21','vix25_h5','vix30_h63','vix30_h21','vix30_h5','rv_h63','rv_h21','rv_h5'];
const v13Pct=p=>(p==null?'—':`${Math.round(Number(p)*100)}%`);
function renderTimeseriesV13VolPanel(v13){
  v13=v13||{};
  const pub=v13.publication||{},gate=v13.gate||{},tier=pub.display_tier||'t0_internal';
  const live=v13.numbers_visible===true&&v13.status==='live';
  const holdoutPass=pub.holdout_status==='pass',holdoutFail=pub.holdout_status==='fail',holdoutPartial=pub.holdout_status==='partial';
  const passN=(v13.holdout_pass_cells||[]).length,cellN=passN+(v13.holdout_fail_cells||[]).length;
  const holdoutLabel=holdoutPass?'홀드아웃(2015~2018) 통과'
    :holdoutFail?'<b>홀드아웃 실패</b>'
    :holdoutPartial?`<b>홀드아웃 부분 통과</b>(${cellN}셀 중 ${passN}셀만 통과 — 나머지는 표시하지 않습니다)`
    :(pub.holdout_caveat_bold?'<b>홀드아웃 미검증</b>':'홀드아웃 미검증');
  const badge=`<span class="timeseries-chip v13-source-badge" title="${esc(plainTerm('persistence_hint'))}">수치모델 · <abbr title="${esc(plainTerm('persistence_hint'))}">당일 수준 지속(PB)</abbr></span>`;
  const caveat=`<p class="ts-lead v13-caveat">설계창(2007~2014) 스킬 · ${holdoutLabel} · <b>참고 의견 — 매매 신호가 아닙니다.</b> 아래 숫자는 예측이 아니라 <abbr title="${esc(plainTerm('base_rate_hint'))}">기준율</abbr>입니다.</p>`;
  const preview=tier==='t2_hidden_panel'?`<p class="ts-lead">심사용 미리보기(T2 숨김 패널) — 공개 표시가 아닙니다.</p>`:'';
  const refId=v13.reference_question?.id||'vix-25-90d';
  /* 대응 셀이 홀드아웃에서 떨어지면 그 숫자는 표에서 내려간다 — 그런데도 '공급원입니다'를
     그대로 두면 독자가 남아 있는 다른 지평의 기준율을 이 질문 값으로 읽는다. 역할 문구는
     대응 셀의 홀드아웃 결과를 따라간다. */
  const refCellName=v13.reference_question?.cell||'vix25_h63';
  const refCellFailed=(v13.holdout_fail_cells||[]).indexOf(refCellName)>=0;
  const roleLine=refCellFailed
    ?`<p class="v13-role">역할: 등록 질문 <b>${esc(refId)}</b>(AI 예측 · 90달력일)에 대응하는 셀(63영업일)은 <b>홀드아웃(2015~2018)을 통과하지 못해 base rate를 공급하지 않습니다.</b> 위 숫자는 지평·사건이 다른 기준율이며 이 질문에 대입하지 않습니다.</p>`
    :`<p class="v13-role">역할: 등록 질문 <b>${esc(refId)}</b>(AI 예측 · 90달력일)의 <abbr title="${esc(plainTerm('base_rate_hint'))}">base rate(outside view)</abbr> 공급원입니다. 두 값은 정의(≥25 vs >25.00)·지평(63영업일 vs 90달력일)·산출(수치모델 vs LLM)이 달라 <b>합치거나 평균내지 않습니다</b>.</p>`;
  const head=`<div class="admin-card-head"><h2>변동성 이벤트 기준율</h2>${badge}</div>`;
  if(!live){
    const reasons=(gate.reasons||[]).slice(0,5);
    const title=v13.status==='absent'?'아직 발행되지 않았습니다':v13.status==='internal'?'내부 산출물 — 표시 승격(V13-D4) 전':holdoutFail?'홀드아웃(2015~2018) 실패 — 숫자를 표시하지 않습니다':'검증 조건이 성립하지 않아 숫자를 숨깁니다';
    return `<div class="ts-panel"><section class="ts-card v13-vol-card">${head}${caveat}${preview}<section class="timeseries-pending"><div class="timeseries-pending-mark" aria-hidden="true">∿</div><div><span>${v13.status==='absent'?'NOT PUBLISHED':'HOLD'}</span><h2>${title}</h2><p>계약 무장·계수 핀·설계 게이트·거래일 신선도 네 조건이 전부 성립할 때만 기준율을 표시합니다. 마지막 값을 재사용하지 않습니다.</p>${reasons.length?`<ul class="timeseries-hold-reasons">${reasons.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>`:''}</div></section>${roleLine}</section></div>`;
  }
  const cells=v13.cells||{},inputs=v13.inputs||{},fresh=v13.freshness||{};
  const hs=['5','21','63'],hNote={'5':'(≈1주)','21':'(≈1개월)','63':'(≈90달력일)'};
  const rowFor=(prefix,label)=>`<tr><th scope="row">${label}</th>${hs.map(h=>{const c=cells[`${prefix}_h${h}`];if(!c)return `<td data-h="${h}">—</td>`;const weak=c.reliability==='weak',thin=c.episode_sample==='thin',band=c.band80||[];
    return `<td data-h="${h}"${weak||thin?' class="is-weak"':''}><b>기준율 ${v13Pct(c.p)}</b><small>[80%: ${v13Pct(band[0])}–${v13Pct(band[1])}]</small><small>기후 ${v13Pct(c.clim_base_rate)}</small>${weak?`<i title="${esc(plainTerm('v13_weak_hint'))}">▲ 보정 약함</i>`:''}${thin?`<i title="${esc(plainTerm('v13_thin_hint'))}">▲ 국면 표본 얇음</i>`:''}</td>`;}).join('')}</tr>`;
  /* 모바일은 지평 한 칸만 보여준다. 기본 63 을 그대로 두면 홀드아웃에서 63 이 전부 떨어진 지금
     휴대폰 사용자는 대시 세 개만 보게 된다 — 숫자가 있는 지평으로 열되 순서(63→21→5)는 지킨다. */
  const defaultH=hs.slice().reverse().find(h=>['vix25','vix30','rv'].some(p=>cells[`${p}_h${h}`]))||'63';
  const table=`<table class="v13-vol-table" data-active-h="${defaultH}"><thead><tr><th scope="col">사건</th>${hs.map(h=>`<th scope="col" data-h="${h}">${h}<abbr title="${esc(plainTerm('business_day_hint'))}">영업일</abbr><small>${hNote[h]}</small></th>`).join('')}</tr></thead><tbody>${rowFor('vix25',V13_CELL_LABELS.vix25)}${rowFor('vix30',V13_CELL_LABELS.vix30)}${rowFor('rv',V13_CELL_LABELS.rv)}</tbody></table>`;
  const hTabs=`<nav class="lab-tabs v13-h-tabs" role="tablist" aria-label="지평 선택(모바일)">${hs.map(h=>`<button type="button" role="tab" data-v13-h-tab="${h}" aria-selected="${String(h===defaultH)}">${h}영업일</button>`).join('')}</nav>`;
  /* 괴리 칩 — 표시만. LLM 확률과 어떤 산술 결합도 하지 않는다. latest_prob 는 퍼센트 정수. */
  const q=(DATA.questions||[]).find(x=>x.id===refId);
  const llm=q&&hasNumeric(q.latest_prob)?Number(q.latest_prob):null;
  const model63=cells.vix25_h63?Math.round(Number(cells.vix25_h63.p)*100):null;
  const thr=Number(v13.reference_question?.divergence_threshold_pp||15);
  const diverge=(llm!=null&&model63!=null)?(model63-llm):null;
  const divChip=diverge==null?'':`<span class="ts-gate-chip ${Math.abs(diverge)>=thr?'warn':'pass'}" title="${esc(refId)} 최신 AI 예측 ${llm}% vs 63영업일 기준율 ${model63}% — 임계 ${thr}%p. 괴리는 표시만 하며 자동 재예측·조정은 없습니다.">AI 예측 ${llm}% 대비 ${diverge>=0?'+':''}${diverge}%p${Math.abs(diverge)>=thr?' · 괴리 — 표시만(자동 조정 없음)':''}</span>`;
  const gateStrip=`<section class="timeseries-gate-strip" aria-label="V13 게이트 상태">`
    +`<span class="ts-gate-chip ${gate.design_gate_pass?'pass':'hold'}" title="설계창(2007~2014) 기후 대비 9/9 양방향 CI90>0 · 건전 y-block 귀무 ≤0.033 · 당일 수준 기준선(PB)이 champion">설계창 게이트 ${gate.design_gate_pass?'통과':'보류'}</span>`
    +`<span class="ts-gate-chip ${gate.freshness_pass?'pass':'hold'}" title="NYSE 거래일 달력 기준 누락 세션 ${fresh.missing_sessions??'—'}/${fresh.max_missing_sessions??1}">신선도 ${gate.freshness_pass?'OK':'경고'} · 기준일 ${esc(String(v13.as_of||''))} (미국 거래일 종가)</span>`
    +`<span class="ts-gate-chip ${holdoutPass?'pass':holdoutFail?'hold':'warn'}" title="홀드아웃(2015~2018)은 사용자 승인 뒤 1회만 채점합니다. 기후 대비 통과여도 라벨 블록순열(건전 귀무) 통과율이 0.10을 넘으면 실패입니다.">홀드아웃 ${holdoutPass?'통과':holdoutFail?'실패':holdoutPartial?`부분 통과 ${passN}/${cellN}`:'미검증'}</span>`
    +`<span class="ts-gate-chip pass" title="입력: VIX 종가 ${Number(inputs.vix_close||0).toFixed(1)} · 실현변동성(21일, 연율) ${(Number(inputs.rv21_ann||0)*100).toFixed(1)}%">VIX ${Number(inputs.vix_close||0).toFixed(1)} · RV21 ${(Number(inputs.rv21_ann||0)*100).toFixed(1)}%</span>`
    +divChip+`</section>`;
  /* 읽는 법은 화면에 실제로 실린 셀을 인용한다 — 홀드아웃에서 떨어져 숨긴 셀을 예로 들면
     없는 숫자를 설명하는 문장이 된다. */
  const guideName=cells[refCellName]?refCellName:V13_GUIDE_ORDER.find(k=>cells[k]);
  const gm=guideName?guideName.match(/^(vix25|vix30|rv)_h(\d+)$/):null;
  const band80Note=`[80%] 대역은 <abbr title="${esc(plainTerm('band80_coef_hint'))}">계수 불확실성</abbr>이지 보정 구간이 아닙니다.`;
  const guide=gm
    ?`<p class="v13-role">읽는 법: "기준율 ${v13Pct(cells[guideName].p)}"는 ${gm[1]==='rv'?'과거 같은 실현변동성 수준에서':'과거 같은 VIX 수준에서'} ${gm[2]}영업일 안에 ${V13_GUIDE_EVENT[gm[1]]} 비율이 기후(무조건 빈도)와 얼마나 다른지 보여주는 <abbr title="${esc(plainTerm('base_rate_hint'))}">outside view</abbr>입니다. ${band80Note}</p>`
    :`<p class="v13-role">읽는 법: 표시 조건을 만족한 셀이 없어 인용할 기준율이 없습니다. ${band80Note}</p>`;
  return `<div class="ts-panel"><section class="ts-card v13-vol-card">${head}${caveat}${preview}${gateStrip}${hTabs}${table}${guide}${roleLine}</section></div>`;
}
function bindTimeseriesV13VolInteractions(root){
  const nav=root.querySelector('.v13-h-tabs'),table=root.querySelector('.v13-vol-table');
  if(!nav||!table)return;
  const activate=button=>{table.dataset.activeH=button.dataset.v13HTab;nav.querySelectorAll('[data-v13-h-tab]').forEach(b=>b.setAttribute('aria-selected',String(b===button)));};
  nav.querySelectorAll('[data-v13-h-tab]').forEach(button=>{button.onclick=()=>activate(button);});
  bindTablistKeys(nav,'[data-v13-h-tab]',activate);
}
/* 공용 탭 바인더 — V8 HOLD 경로에는 바인더가 없었다(T3 에서 V8 이 HOLD 여도 V13 탭은 살아야 한다). */
