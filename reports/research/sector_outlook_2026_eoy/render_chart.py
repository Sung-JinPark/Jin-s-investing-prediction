"""Render the declared scenario assumptions; never labels a band as a CI."""
from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt

ROOT = Path(__file__).resolve().parent
data = json.loads((ROOT / "scenario_results.json").read_text(encoding="utf-8"))
rows = data["assets"]
plt.rcParams.update({"font.family":"Malgun Gothic", "axes.unicode_minus":False, "font.size":11,
                     "figure.facecolor":"#f7f9fc","axes.facecolor":"#f7f9fc"})
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.2, 5.9), gridspec_kw={"width_ratios":[1.1, 1.0]})
fig.suptitle("2026년 연말 수익률 가정과 불확실성", fontsize=19, weight="bold", x=.06, ha="left", y=.97)
fig.text(.06,.895,"10월 9일 → 12월 31일 · USD · 검증된 수익률 예측이나 신뢰구간이 아닌 가정 계산",fontsize=10,color="#4b5563")
names=[r["id"]+"  "+r["name"] for r in rows]
for y,r in enumerate(rows):
    color="#176c85" if r["priority"] else "#6b7280"
    lo,mid,hi=[r[k]*100 for k in ("weighted_assumption_low","weighted_assumption_mid","weighted_assumption_high")]
    ax1.plot([lo,hi],[y,y],color=color,lw=5,alpha=.23,solid_capstyle="round")
    ax1.scatter(mid,y,color=color,s=60,zorder=3)
    ax1.annotate(f"{mid:.1f}%",(mid,y),xytext=(0,11),textcoords="offset points",ha="center",color=color,fontweight="bold")
ax1.set_yticks(range(len(rows)),names)
ax1.invert_yaxis(); ax1.set_ylim(len(rows)-.55,-.75)
ax1.axvline(0,color="#aeb7c5",lw=1)
ax1.set_xlim(-6,12); ax1.set_xlabel("가정 가중 수익률 (%)")
ax1.set_title("중간값은 비슷하고 가정 범위는 크게 겹침",fontsize=12,pad=18)
ax1.grid(axis="x",color="#dde3eb",lw=.6)
states=[("bear","하락 가정","#b95246"),("base","기준 가정","#566f83"),("bull","상승 가정","#178065")]
for offset,(state,label,color) in zip((-.21,0,.21),states):
    ax2.scatter([r["cases"][state]["mid"]*100 for r in rows],[y+offset for y in range(len(rows))],
                color=color,s=48,label=label,zorder=3)
ax2.set_yticks(range(len(rows)),[r["id"] for r in rows]);ax2.invert_yaxis();ax2.set_ylim(len(rows)-.55,-.75)
ax2.axvline(0,color="#aeb7c5",lw=1);ax2.set_xlim(-28,28)
ax2.set_xlabel("각 상황의 가정 수익률 (%)");ax2.set_title("하락 상황에서는 손실도 큼",fontsize=12,pad=18)
ax2.grid(axis="x",color="#dde3eb",lw=.6);ax2.legend(loc="lower right",frameon=False,fontsize=9)
for ax in (ax1,ax2):
    for spine in ax.spines.values():spine.set_visible(False)
    ax.tick_params(axis="both",length=0,pad=8)
fig.text(.06,.045,"가중치: 상승 0.30 · 기준 0.45 · 하락 0.25. 배당은 미확정 가정이며 펀드 보수 추정치를 반영.",fontsize=9,color="#4b5563")
fig.text(.06,.012,"범위는 이익능력·평가배수·배당 가정을 바꾼 값. GRID는 글로벌 주식 ETF, XLC는 통신서비스 전체의 대용치.",fontsize=9,color="#4b5563")
fig.subplots_adjust(left=.22,right=.98,top=.78,bottom=.18,wspace=.32)
fig.savefig(ROOT/"scenario_comparison.png",dpi=160)
fig.savefig(ROOT/"scenario_comparison.svg")
plt.close(fig)
print("scenario_comparison.png and .svg saved")
