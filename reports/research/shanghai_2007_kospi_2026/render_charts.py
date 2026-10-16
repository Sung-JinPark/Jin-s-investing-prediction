"""Render sourced observations and explicitly hypothetical arithmetic separately."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
from matplotlib import font_manager
from matplotlib.ticker import PercentFormatter
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location("pa",ROOT/"prices/analytics.py")
PA=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(PA)
FONT=Path("C:/Windows/Fonts/malgun.ttf")
if FONT.exists():
    font_manager.fontManager.addfont(str(FONT))
    plt.rcParams["font.family"]=font_manager.FontProperties(fname=str(FONT)).get_name()
plt.rcParams.update({"font.size":11,"axes.unicode_minus":False,"axes.spines.top":False,
                     "axes.spines.right":False,"figure.facecolor":"white","axes.facecolor":"white",
                     "axes.titleweight":"bold","savefig.facecolor":"white"})
COLORS={"SSE_COMPOSITE":"#bd642a","SSE_A":"#888888","KOSPI":"#2164b3"}
LABELS={"SSE_COMPOSITE":"상해종합 2006~2007","SSE_A":"상해 A주 2006~2007","KOSPI":"코스피 2025~2026"}


def save(fig,name):
    out=ROOT/"charts";out.mkdir(exist_ok=True)
    fig.savefig(out/(name+".png"),dpi=160,bbox_inches="tight")
    fig.savefig(out/(name+".svg"),bbox_inches="tight")
    plt.close(fig)


def primary(data,results):
    fig,axes=plt.subplots(2,1,figsize=(12,8.8),sharex=True,gridspec_kw={"height_ratios":[1.65,1]},layout="constrained")
    for symbol in ("SSE_A","SSE_COMPOSITE","KOSPI"):
        historical=symbol.startswith("SSE")
        series=PA.select(data[symbol],dt.date(2006 if historical else 2025,1,1),dt.date(2007 if historical else 2026,10,15))
        dates=[PA.calendar_shift(r["date"]) if historical else r["date"] for r in series]
        values=np.array([r["close"] for r in series])
        style=":" if symbol=="SSE_A" else "-"
        axes[0].plot(dates,values/values[0]*100,label=LABELS[symbol],color=COLORS[symbol],lw=2 if symbol!="SSE_A" else 1.3,ls=style)
        if symbol!="SSE_A":
            dd=values/np.maximum.accumulate(values)-1
            axes[1].plot(dates,dd,color=COLORS[symbol],lw=1.8)
    axes[0].set_title("달력을 고정하면 두 시장은 서로 다른 국면에 있다",loc="left",fontsize=17,pad=16)
    axes[0].set_ylabel("각 시작일 종가 = 100")
    axes[0].legend(loc="upper left",frameon=False,ncol=1)
    w=results["primary"]["SSE_COMPOSITE"]["weekly_returns"]
    axes[0].text(.98,.04,f"주간 수익률 상관  {w['pearson']:.3f}\nSpearman  {w['spearman']:.3f}  ·  {w['n_return_pairs']}쌍",transform=axes[0].transAxes,ha="right",va="bottom",color="#333333",fontsize=12)
    axes[1].set_ylabel("기간 중 고점 대비 낙폭")
    axes[1].yaxis.set_major_formatter(PercentFormatter(1,decimals=0))
    axes[1].set_ylim(-.46,.025)
    axes[1].xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y.%m"))
    axes[1].set_xlabel("표시 달력은 2025~2026년 · 중국 관측일에 정확히 19년을 더함")
    for ax in axes:ax.grid(axis="y",alpha=.18)
    fig.supxlabel("상해: 2006.01.04~2007.10.15  |  코스피: 2025.01.02~2026.10.15  |  종가·현지통화 가격지수",fontsize=10)
    save(fig,"fixed_calendar_comparison")


def outcomes(data):
    fig,axes=plt.subplots(2,1,figsize=(12,8.8),layout="constrained")
    for ax,symbol,start,end,title in [
        (axes[0],"SSE_COMPOSITE",dt.date(2006,1,1),dt.date(2008,12,31),"상해종합 실제 경로와 사후 하락 결과"),
        (axes[1],"KOSPI",dt.date(2025,1,1),dt.date(2026,10,15),"코스피 실제 경로는 2026년 10월 15일에서 멈춘다")]:
        series=PA.select(data[symbol],start,end)
        x=[r["date"] for r in series];y=[r["close"] for r in series]
        ax.plot(x,y,color=COLORS[symbol],lw=1.8)
        peak=max(series,key=lambda r:r["close"])
        ax.scatter([peak["date"]],[peak["close"]],color=COLORS[symbol],s=22)
        ax.annotate(f"종가 고점 {peak['close']:,.2f}\n{peak['date']}",xy=(peak["date"],peak["close"]),xytext=(10,-48),textcoords="offset points",fontsize=10)
        last=series[-1]
        ax.text(.99,.04,f"마지막 종가 {last['close']:,.2f}\n고점 대비 {(last['close']/peak['close']-1):.1%}",transform=ax.transAxes,ha="right",va="bottom",fontsize=11)
        ax.set_title(title,loc="left",fontsize=15)
        ax.set_ylabel("지수 포인트")
        ax.grid(axis="y",alpha=.18)
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y.%m"))
        if symbol=="SSE_COMPOSITE":
            ax.axvspan(dt.date(2007,10,16),end,color="#eeeeee",zorder=0)
            ax.text(.02,.9,"회색 영역은 사후 관찰 · 한국의 미래 경로가 아님",transform=ax.transAxes,fontsize=10,color="#555555")
    fig.supxlabel("두 패널은 각각의 실제 달력 · 고점끼리 맞춘 미래 투영을 하지 않음",fontsize=10)
    save(fig,"observed_paths")


def valuation():
    j=json.loads((ROOT/"supporting_analysis.json").read_text(encoding="utf-8"))
    grid=np.array([r["price_return_fraction"] for r in j["sensitivity"]]).reshape(5,5)
    fig,ax=plt.subplots(figsize=(9,6.8),layout="constrained")
    im=ax.imshow(grid,cmap="RdBu",vmin=-.7,vmax=.7,aspect="auto",origin="lower")
    labels=["-40%","-20%","0%","+20%","+40%"]
    ax.set_xticks(range(5),labels);ax.set_yticks(range(5),labels)
    for i in range(5):
        for k in range(5):
            ax.text(k,i,f"{grid[i,k]:+.0%}",ha="center",va="center",fontsize=14,color="white" if abs(grid[i,k])>.4 else "#202020")
    ax.set_xlabel("PER 변화 가정",labelpad=12);ax.set_ylabel("EPS 변화 가정",labelpad=12)
    ax.set_title("이익이 늘어도 평가배수가 낮아지면 주가는 하락할 수 있다",loc="left",fontsize=15,pad=15)
    fig.colorbar(im,ax=ax,format=PercentFormatter(1),label="가격 변화 산술")
    fig.supxlabel("가격 변화 = (1 + EPS 변화) × (1 + PER 변화) - 1\n모든 입력은 설명용 가정 · 6개월 또는 12개월의 예측값과 발생 확률이 아님",fontsize=11)
    save(fig,"valuation_sensitivity")


def fundamentals():
    fig,axes=plt.subplots(1,2,figsize=(12,5.8),layout="constrained")
    ax=axes[0]
    ax.plot([2005,2006,2007],[16.33,33.30,59.24],marker="o",lw=2.2,color=COLORS["SSE_COMPOSITE"])
    for x,y in zip([2005,2006,2007],[16.33,33.30,59.24]):ax.annotate(f"{y:.2f}배",(x,y),xytext=(0,10),textcoords="offset points",ha="center")
    ax.set_title("상해 시장 평균 PER 확대",loc="left",fontsize=14)
    ax.set_xticks([2005,2006,2007]);ax.set_ylim(0,70)
    ax.set_ylabel("전년 연간 이익 기준 배수")
    ax.text(.02,-.20,"연말 관측 · SSE 정의는 TTM 또는 forward PER와 다름",transform=ax.transAxes,fontsize=10)
    ax=axes[1];x=np.arange(2);width=.34
    ax.bar(x-width/2,[2.5415,3.333],width,label="비교 표본 전체",color=COLORS["KOSPI"])
    ax.bar(x+width/2,[.7561,1.1968],width,label="삼성전자·SK하이닉스 제외",color="#9bb9d8")
    ax.set_xticks(x,["영업이익","순이익"]);ax.yaxis.set_major_formatter(PercentFormatter(1,decimals=0))
    ax.set_title("한국 2026년 상반기 이익 증가",loc="left",fontsize=14)
    ax.set_ylabel("전년 동기 대비 증가율");ax.legend(frameon=False,loc="upper left")
    ax.set_ylim(0,4.2)
    ax.text(.02,-.20,"연결 634개사 · 금융업 등 제외 · 지수 EPS 성장률이 아님",transform=ax.transAxes,fontsize=10)
    for axes_i in axes:axes_i.grid(axis="y",alpha=.18)
    fig.supxlabel("중국과 한국 패널은 서로 다른 지표 · 높이를 직접 비교하지 않음",fontsize=10)
    save(fig,"fundamentals")


def main():
    data=PA.load_prices();results=json.loads((ROOT/"prices/analytics.json").read_text(encoding="utf-8"))
    primary(data,results);outcomes(data);valuation();fundamentals()
    print("Rendered 4 PNG and 4 SVG figures")


if __name__=="__main__":main()
