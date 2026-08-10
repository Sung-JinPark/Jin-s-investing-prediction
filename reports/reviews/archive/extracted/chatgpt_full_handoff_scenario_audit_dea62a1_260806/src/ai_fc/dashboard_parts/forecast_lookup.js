(function(root){
  'use strict';
  const DAY_MS=86400000;
  const isoPattern=/^\d{4}-\d{2}-\d{2}$/;
  const toIso=value=>value.toISOString().slice(0,10);
  const parseIso=value=>{const raw=String(value||'');if(!isoPattern.test(raw))return null;const parsed=new Date(raw+'T12:00:00Z');return toIso(parsed)===raw?parsed:null;};
  const addDays=(value,days)=>{const parsed=parseIso(value);if(!parsed)return null;parsed.setUTCDate(parsed.getUTCDate()+days);return toIso(parsed);};
  const addMonths=(value,months)=>{const parsed=parseIso(value);if(!parsed)return null;const day=parsed.getUTCDate();parsed.setUTCDate(1);parsed.setUTCMonth(parsed.getUTCMonth()+months);const last=new Date(Date.UTC(parsed.getUTCFullYear(),parsed.getUTCMonth()+1,0,12));parsed.setUTCDate(Math.min(day,last.getUTCDate()));return toIso(parsed);};
  const dayDiff=(left,right)=>Math.round((parseIso(right)-parseIso(left))/DAY_MS);
  function quickDates(asof){
    const parsed=parseIso(asof);if(!parsed)return {};
    return {week:addDays(asof,7),month:addMonths(asof,1),quarter:addMonths(asof,3),yearEnd:`${parsed.getUTCFullYear()}-12-31`};
  }
  function monthDay(asof,month,day){
    const base=parseIso(asof);if(!base||month<1||month>12||day<1||day>31)return null;
    let year=base.getUTCFullYear(),candidate=new Date(Date.UTC(year,month-1,day,12));
    if(candidate.getUTCMonth()!==month-1||candidate.getUTCDate()!==day)return null;
    if(toIso(candidate)<=asof){year+=1;candidate=new Date(Date.UTC(year,month-1,day,12));}
    return candidate.getUTCMonth()===month-1&&candidate.getUTCDate()===day?toIso(candidate):null;
  }
  function parseQuery(raw,asof){
    const value=String(raw||'').trim();if(!value)return {ok:false,reason:'parse_failed'};
    if(isoPattern.test(value)&&parseIso(value))return {ok:true,date:value,kind:'iso'};
    if(value==='연말')return {ok:true,date:`${parseIso(asof).getUTCFullYear()}-12-31`,kind:'year_end'};
    let match=value.match(/^(\d{1,2})\s*\/\s*(\d{1,2})$/)||value.match(/^(\d{1,2})\s*월\s*(\d{1,2})\s*일$/);
    if(match){const resolved=monthDay(asof,Number(match[1]),Number(match[2]));return resolved?{ok:true,date:resolved,kind:'month_day'}:{ok:false,reason:'parse_failed'};}
    match=value.match(/^(\d{1,2})\s*개월\s*뒤$/);if(match)return {ok:true,date:addMonths(asof,Number(match[1])),kind:'relative_month'};
    match=value.match(/^(\d{1,2})\s*주\s*뒤$/);if(match)return {ok:true,date:addDays(asof,Number(match[1])*7),kind:'relative_week'};
    return {ok:false,reason:'parse_failed'};
  }
  function mapDate(table,requested,asof){
    const days=table?.trading_days||[];
    if(!parseIso(requested))return {ok:false,reason:'invalid'};
    if(!days.length||table?.status==='blocked')return {ok:false,reason:'blocked'};
    if(requested<=asof)return {ok:false,reason:'before_asof',asof};
    if(requested>days[days.length-1])return {ok:false,reason:'out_of_range',max:days[days.length-1]};
    const exact=days.indexOf(requested);
    if(exact>=0)return {ok:true,index:exact,requested,mapped:requested,mapping:'exact',tradingDay:exact+1};
    let prior=-1;
    for(let index=0;index<days.length&&days[index]<requested;index++)prior=index;
    const index=prior>=0?prior:0;
    return {ok:true,index,requested,mapped:days[index],mapping:prior>=0?'previous':'next',tradingDay:index+1};
  }
  root.ForecastLookup={addDays,addMonths,dayDiff,quickDates,mapDate,parseQuery,parseIso,toIso};
})(typeof window==='undefined'?globalThis:window);
