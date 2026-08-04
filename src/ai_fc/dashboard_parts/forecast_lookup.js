(function(root){
  'use strict';
  const DAY_MS=86400000;
  const isoPattern=/^\d{4}-\d{2}-\d{2}$/;
  const parseIso=value=>isoPattern.test(String(value||''))?new Date(String(value)+'T12:00:00Z'):null;
  const toIso=value=>value.toISOString().slice(0,10);
  const addDays=(value,days)=>{const parsed=parseIso(value);if(!parsed)return null;parsed.setUTCDate(parsed.getUTCDate()+days);return toIso(parsed);};
  const addMonths=(value,months)=>{const parsed=parseIso(value);if(!parsed)return null;const day=parsed.getUTCDate();parsed.setUTCDate(1);parsed.setUTCMonth(parsed.getUTCMonth()+months);const last=new Date(Date.UTC(parsed.getUTCFullYear(),parsed.getUTCMonth()+1,0,12));parsed.setUTCDate(Math.min(day,last.getUTCDate()));return toIso(parsed);};
  const dayDiff=(left,right)=>Math.round((parseIso(right)-parseIso(left))/DAY_MS);
  function quickDates(asof){
    const parsed=parseIso(asof);if(!parsed)return {};
    return {week:addDays(asof,7),month:addMonths(asof,1),quarter:addMonths(asof,3),yearEnd:`${parsed.getUTCFullYear()}-12-31`};
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
  root.ForecastLookup={addDays,addMonths,dayDiff,quickDates,mapDate,parseIso,toIso};
})(typeof window==='undefined'?globalThis:window);
