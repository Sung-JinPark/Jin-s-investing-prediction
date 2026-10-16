"""Phase-anchored observed paths; no Korean future path or time optimization."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

ROOT=Path(__file__).resolve().parent
font=Path("C:/Windows/Fonts/malgun.ttf")
if font.exists():
    font_manager.fontManager.addfont(str(font))
    plt.rcParams['font.family']=font_manager.FontProperties(fname=str(font)).get_name()
plt.rcParams.update({'font.size':11,'axes.unicode_minus':False,'axes.spines.right':False,'axes.spines.top':False,'figure.facecolor':'white'})
COLORS={'KOSPI':'#2164b3','SSE_COMPOSITE':'#bd642a'}


def main():
    j=json.loads((ROOT/'prices/phase_analysis.json').read_text(encoding='utf-8'))
    support=json.loads((ROOT/'phase_support.json').read_text(encoding='utf-8'))
    prices=list(csv.DictReader((ROOT.parent/'prices/prices.csv').open(encoding='utf-8')))
    out=ROOT/'charts';out.mkdir(exist_ok=True)
    fig,axes=plt.subplots(3,1,figsize=(12,12),layout='constrained')
    for sym in ['SSE_COMPOSITE','KOSPI']:
        anchor=j['anchors'][sym]
        run=[r for r in prices if r['symbol']==sym and anchor['rise_start_date']<=r['date']<=anchor['observed_peak_date']]
        correction=j['prepeak_excursions'][sym]['largest_completed']
        mid=[r for r in prices if r['symbol']==sym and correction['peak_date']<=r['date']<=correction['first_recovery_date']]
        post=[r for r in prices if r['symbol']==sym and r['date']>=anchor['observed_peak_date']][:78]
        for ax,rows,label in [(axes[0],run,'상승 시작'),(axes[1],mid,'중간 조정 시작'),(axes[2],post,'관측 종가 고점')]:
            values=np.array([float(r['close']) for r in rows]);y=values/values[0]*100
            name=('코스피' if sym=='KOSPI' else '상해종합')+f"  {rows[0]['date']} 시작"
            ax.plot(np.arange(len(rows)),y,label=name,lw=2,color=COLORS[sym])
            ax.scatter([len(rows)-1],[y[-1]],color=COLORS[sym],s=20)
            ax.set_xlabel(label+' 이후 실제 거래일 수');ax.set_ylabel('출발 종가 = 100');ax.grid(axis='y',alpha=.2)
    titles=['상승 출발점 정렬  ·  한국의 상승은 더 짧고 빨랐다',
            '중간 조정 정렬  ·  하락 깊이와 회복 기간은 비교적 비슷했다',
            '고점 이후 정렬  ·  같은 77거래일에 한국의 낙폭이 더 깊다']
    for ax,title in zip(axes,titles):ax.set_title(title,loc='left',fontsize=15);ax.legend(frameon=False,loc='upper left')
    axes[0].set_ylim(0,660);axes[1].set_ylim(75,110);axes[2].set_ylim(50,106)
    c=support['postpeak_equal_age_correlation']
    axes[2].text(.98,.94,f"종가 경로 상관 {c['closing_level_pearson']:.2f}\n일별 수익률 상관 {c['daily_log_return_pearson']:.2f}",transform=axes[2].transAxes,ha='right',va='top',fontsize=11)
    fig.supxlabel('국면 출발점을 0일로 고정 · 기간을 늘이거나 줄이지 않음 · 한국 관측은 2026.10.15에서 종료',fontsize=10)
    for ext in ['png','svg']:fig.savefig(out/('phase_anchors.'+ext),dpi=155,bbox_inches='tight')
    plt.close(fig)
    review=json.loads((ROOT/'review/initial_review_metrics.json').read_text(encoding='utf-8'))
    seq={r['label']:r for r in review['anchor_sequences']}
    selected=[('CN_MID_RALLY_2007','상해 2007년 중간 조정','#2e8057'),
              ('CN_EARLY_POST_PEAK','상해 2007년 말~2008년 초','#bd642a'),
              ('CN_DEEP_BEAR_2008','상해 2008년 4~6월','#8a6a9f'),
              ('KOREA_OBSERVED_CURRENT','현재 코스피','#2164b3')]
    fig,ax=plt.subplots(figsize=(12,6.7),layout='constrained')
    for key,label,color in selected:
        r=seq[key];p0=r['peak']['close']
        ys=[r['peak']['close'],r['first_or_designated_trough']['close'],r['rebound_peak']['close'],r['first_close_below_designated_trough_after_rebound']['close']]
        ax.plot(range(4),np.array(ys)/p0*100,marker='o',lw=2,label=label,color=color)
        ax.annotate(r['first_close_below_designated_trough_after_rebound']['date'],(3,ys[-1]/p0*100),xytext=(12,0),textcoords='offset points',va='center',color=color,fontsize=11)
    ax.set_xticks(range(4),['구간 관측 고점','첫 저점 또는 지정 저점','반등 고점','전저점 첫 이탈'])
    ax.set_xlim(-.1,3.9);ax.set_ylim(45,105);ax.set_ylabel('각 구간 관측 고점 = 100')
    ax.set_title('같은 반등 실패의 모양도 회복력과 이후 결과는 다르다',loc='left',fontsize=16)
    ax.grid(axis='y',alpha=.2);ax.legend(frameon=False,loc='lower left',ncol=2)
    fig.supxlabel('사건별 요약 · 중간 거래일과 실제 기간 간격 생략 · 미래 경로 그림이 아님\n상해 2007년 7월 이탈은 이후 전고 회복, 2008년 사례는 추가 하락',fontsize=10)
    for ext in ['png','svg']:fig.savefig(out/('phase_sequence.'+ext),dpi=155,bbox_inches='tight')
    plt.close(fig)
    print('Rendered 2 phase figures in PNG/SVG')


if __name__=='__main__':main()
