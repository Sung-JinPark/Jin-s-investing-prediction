"""Overlay the attachment's yellow correction boxes, with explicit transformations."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Rectangle
import numpy as np

ROOT = Path(__file__).resolve().parent
STUDY = ROOT.parent
PRICE = STUDY / "prices/prices.csv"
FONT = Path("C:/Windows/Fonts/malgun.ttf")
if FONT.exists():
    font_manager.fontManager.addfont(str(FONT))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(FONT)).get_name()
plt.rcParams.update({"font.size": 11, "axes.unicode_minus": False,
                     "axes.spines.right": False, "axes.spines.top": False,
                     "figure.facecolor": "#ffffff", "axes.labelcolor": "#43515e",
                     "text.color": "#182c3a", "svg.fonttype": "none"})
SPECS = {
    "KOSPI": {"label": "코스피", "color": "#2458ae", "start": "2026-02-26",
              "trough": "2026-03-31", "exit": "2026-04-21", "peak": "2026-06-22",
              "visible_start": "2025-07-01", "attachment_end": "2026-10-14"},
    "SSE_A": {"label": "상해 A주", "color": "#d15c39", "start": "2007-05-29",
              "trough": "2007-07-05", "exit": "2007-07-26", "peak": "2007-10-16",
              "visible_start": "2006-12-01"},
}
ATTACHMENTS = [
    "C:/Users/91ssj/AppData/Local/Temp/codex-clipboard-e2001a52-b398-4d23-ba9d-1cb3120759ec.png",
    "C:/Users/91ssj/AppData/Local/Temp/codex-clipboard-11a904a2-2274-4eb1-8dfc-ce69c3b70acb.png",
    "C:/Users/91ssj/AppData/Local/Temp/codex-clipboard-827bae96-81eb-4ac7-a1dc-972d4c72fa8c.png",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(fig, name):
    for suffix in ("png", "svg"):
        fig.savefig(ROOT / f"{name}.{suffix}", dpi=175, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main():
    ROOT.mkdir(exist_ok=True)
    baseline = ROOT / "previous_studies_before.json"
    if not baseline.exists():
        hashes = {p.relative_to(STUDY).as_posix(): sha(p) for p in STUDY.rglob("*")
                  if p.is_file() and ROOT not in p.parents and "__pycache__" not in p.parts}
        baseline.write_text(json.dumps({"captured_at_utc": datetime.now(timezone.utc).isoformat(),
                                       "sha256": hashes}, indent=2) + "\n", encoding="utf-8")
    frozen = list(csv.DictReader(PRICE.open(encoding="utf-8")))
    data, anchors = {}, {}
    for symbol, spec in SPECS.items():
        rows = sorted([r for r in frozen if r["symbol"] == symbol], key=lambda r: r["date"])
        dates = [r["date"] for r in rows]
        values = np.array([float(r["close"]) for r in rows])
        i0, ix, it, ip = [dates.index(spec[k]) for k in ("start", "exit", "trough", "peak")]
        if not (np.all(values[i0+1:ix] < values[i0]) and values[ix] >= values[i0]):
            raise ValueError("Selected right box boundary is not the first closing recovery")
        if i0+np.argmin(values[i0:ix+1]) != it:
            raise ValueError("Selected low does not match the box minimum")
        span = ix-i0
        data[symbol] = {"rows": rows, "dates": dates, "p": values,
                        "x": np.arange(len(rows))-i0, "y": values/values[i0]*100,
                        "i0": i0, "ix": ix, "it": it, "ip": ip, "span": span}
        anchors[symbol] = {"index_id": symbol, "label_ko": spec["label"],
                           "box_start": spec["start"], "box_start_close": float(values[i0]),
                           "box_low": spec["trough"], "box_low_close": float(values[it]),
                           "box_first_closing_recovery": spec["exit"],
                           "recovery_close": float(values[ix]), "actual_return_intervals": span,
                           "observed_peak": spec["peak"], "peak_close": float(values[ip]),
                           "return_unit": "fraction", "box_drawdown_fraction": float(values[it]/values[i0]-1)}
    ratio = data["KOSPI"]["span"] / data["SSE_A"]["span"]
    cutoff_x = int(data["KOSPI"]["x"][-1])
    transformed = []
    for mode in ("box_width_matched", "actual_trading_days"):
        for symbol, d in data.items():
            scale = ratio if mode == "box_width_matched" and symbol == "SSE_A" else 1.0
            keep = np.array([date >= SPECS[symbol]["visible_start"] for date in d["dates"]])
            keep &= d["x"]*scale <= cutoff_x
            for index in np.flatnonzero(keep):
                transformed.append({"mode": mode, "symbol": symbol, "date": d["dates"][index],
                                    "close_index_points": float(d["p"][index]),
                                    "actual_sessions_from_box_start": int(d["x"][index]),
                                    "x_comparison_axis": float(d["x"][index]*scale),
                                    "start_close_100": float(d["y"][index]),
                                    "time_scale": scale,
                                    "beyond_attachment_date": symbol == "KOSPI" and d["dates"][index] > SPECS[symbol]["attachment_end"]})
    with (ROOT/"overlay_series.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(transformed[0]))
        writer.writeheader()
        writer.writerows(transformed)

    def lines(ax, mode, annotate=True):
        for symbol in ("SSE_A", "KOSPI"):
            spec, d = SPECS[symbol], data[symbol]
            records = [r for r in transformed if r["mode"] == mode and r["symbol"] == symbol]
            solid = [r for r in records if not r["beyond_attachment_date"]]
            ax.plot([r["x_comparison_axis"] for r in solid], [r["start_close_100"] for r in solid],
                    lw=2.1, color=spec["color"], label=f"{spec['label']}  |  박스 시작 {spec['start']}", zorder=4)
            extra = [r for r in records if r["beyond_attachment_date"]]
            if extra:
                extension = solid[-1:] + extra
                ax.plot([r["x_comparison_axis"] for r in extension], [r["start_close_100"] for r in extension],
                        color=spec["color"], lw=1.7, ls=(0,(3,2)), zorder=4)
                ax.scatter([extra[-1]["x_comparison_axis"]], [extra[-1]["start_close_100"]],
                           s=40, facecolor="white", edgecolor=spec["color"], lw=1.5, zorder=6)
                if annotate:
                    ax.annotate("10/15 추가 관측", (extra[-1]["x_comparison_axis"],extra[-1]["start_close_100"]),
                                xytext=(-77,-19),textcoords="offset points",fontsize=9,color=spec["color"])
            scale = ratio if mode == "box_width_matched" and symbol == "SSE_A" else 1
            for idx in (d["i0"], d["it"], d["ix"], d["ip"]):
                ax.scatter(d["x"][idx]*scale, d["y"][idx], s=27, color=spec["color"], zorder=5)
            if annotate:
                peak_x = d["x"][d["ip"]]*scale
                peak_y = d["y"][d["ip"]]
                offset = (-130, 21) if symbol == "KOSPI" else (22, 38)
                ax.annotate(f"{spec['label']} 종가 고점\n{spec['peak']} · {d['p'][d['ip']]:,.2f}",
                            (peak_x, peak_y), xytext=offset, textcoords="offset points",
                            color=spec["color"], fontsize=10, ha="left", va="center",
                            arrowprops={"arrowstyle":"-", "color":spec["color"], "lw":.9})
                last = solid[-1]
                label_offset = (-120,-7) if symbol == "KOSPI" else (7,15)
                ax.annotate(f"{spec['label']} {last['date']}",
                            (last["x_comparison_axis"],last["start_close_100"]),
                            xytext=label_offset,textcoords="offset points",fontsize=9,color=spec["color"],
                            arrowprops={"arrowstyle":"-","color":spec["color"],"lw":.7} if symbol=="KOSPI" else None)
        ax.axhline(100, color="#7f8a91", lw=.8, ls=(0,(4,4)), alpha=.6)
        ax.grid(axis="y", color="#d6dde2", alpha=.55, lw=.7)
        ax.set_ylabel("노란 박스 시작 종가 = 100")

    def box(ax, mode):
        width = data["KOSPI"]["span"] if mode == "box_width_matched" else data["SSE_A"]["span"]
        ax.add_patch(Rectangle((0,78),width,25, facecolor="#fff1a3", edgecolor="#e2bb00",
                              lw=2.4, alpha=.7,zorder=1))
        ax.text(width/2,75,"첨부 이미지의 노란 박스",ha="center",va="top",fontsize=10,color="#8a6d00")

    for mode, name, title, subtitle in [
        ("box_width_matched", "overlay_box_matched", "첨부 이미지의 노란 박스를 기준으로 중첩",
         "박스 시작과 돌파를 일치 · 상해 A주 시간축 × 37/42 = 0.881 · 가격은 시작 종가만 100으로 환산"),
        ("actual_trading_days", "overlay_actual_days", "같은 노란 박스에서 출발 · 실제 거래일 간격 유지",
         "시간축 보정 없음 · 코스피 박스 37거래일, 상해 A주 박스 42거래일 · 가격은 시작 종가 = 100"),
    ]:
        fig, ax = plt.subplots(figsize=(13,7.5))
        fig.subplots_adjust(left=.08,right=.97,bottom=.17,top=.83)
        box(ax,mode)
        lines(ax,mode)
        ax.set_xlim(-160,cutoff_x+8)
        ax.set_ylim(38,160)
        ax.set_xticks(np.arange(-150,151,25))
        ax.set_xlabel("박스 시작 이후 비교축  ·  코스피 거래일 기준" if mode=="box_width_matched"
                      else "노란 박스 시작일 이후 실제 거래일 수")
        ax.legend(loc="upper left",frameon=False,fontsize=11)
        fig.suptitle(title,x=.08,y=.965,ha="left",fontsize=21,fontweight="bold")
        fig.text(.08,.905,subtitle,fontsize=11,color="#51606c")
        fig.text(.08,.065,"실선: 코스피 2026.10.14까지 · 파란 끝 점선/빈 점: 10.15 추가 관측 종가 · 상해는 동일 비교축 범위의 역사 관측만 표시",fontsize=9,color="#5f6d76")
        fig.text(.08,.035,"박스 경계: 조정 전 최고 종가 → 그 종가의 첫 회복일 · 곡선은 각 시장의 실제 관측 종가",fontsize=9,color="#5f6d76")
        save(fig,name)

    fig, ax = plt.subplots(figsize=(12,6.1))
    fig.subplots_adjust(left=.09,right=.97,bottom=.19,top=.81)
    lines(ax,"box_width_matched",annotate=False)
    ax.add_patch(Rectangle((0,78),37,25,facecolor="#fff2a9",edgecolor="#dfb800",lw=2,alpha=.55,zorder=1))
    for symbol,d in data.items():
        scale = ratio if symbol == "SSE_A" else 1
        spec = SPECS[symbol]
        x,y = d["x"][d["it"]]*scale,d["y"][d["it"]]
        ax.annotate(f"{spec['trough']}  {anchors[symbol]['box_drawdown_fraction']:.2%}",
                    (x,y),xytext=(-92,17 if symbol=="SSE_A" else -27),textcoords="offset points",
                    fontsize=11,color=spec["color"],arrowprops={"arrowstyle":"-","color":spec["color"]})
    ax.set_xlim(-3,42)
    ax.set_ylim(75,108)
    ax.set_xlabel("박스 시작 = 0 · 박스 돌파 = 37  /  중국 시간축 11.90% 압축")
    ax.legend(loc="upper left",frameon=False)
    fig.suptitle("사용자가 표시한 조정 구간 확대",x=.09,y=.96,ha="left",fontsize=21,fontweight="bold")
    fig.text(.09,.875,"코스피 2026.02.26~04.21  ↔  상해 A주 2007.05.29~07.26",fontsize=12,color="#51606c")
    fig.text(.09,.06,"가격의 저점까지 강제로 맞추지 않음 · 두 시장의 실제 조정 깊이 차이를 유지",fontsize=10,color="#5f6d76")
    save(fig,"overlay_box_zoom")

    bounds = {}
    for mode in ("box_width_matched","actual_trading_days"):
        bounds[mode]={symbol:{"first_date":(r:=[r for r in transformed if r['mode']==mode and r['symbol']==symbol])[0]['date'],
                              "last_date":r[-1]['date'],"last_x":r[-1]['x_comparison_axis']}
                      for symbol in SPECS}
    receipt = {"created_at_utc":datetime.now(timezone.utc).isoformat(),"price_cutoff":"2026-10-15",
        "image_comparison_cutoff":"2026-10-14","research_only":True,"probability_outputs":[],
        "source_csv_relative_to_study":"prices/prices.csv","source_sha256":sha(PRICE),
        "attachments":[{"path":p,"sha256":sha(Path(p))} for p in ATTACHMENTS],"anchors":anchors,
        "attachment_index":"SSE_A, 000002.SS; attachment intraday high 6429.68 differs from Composite 6124.04",
        "boundary_rule":"Hand-drawn boxes interpreted as the completed closing-price correction, not exact pixel tracing",
        "time_transforms":{"actual_trading_days":{"KOSPI":1.0,"SSE_A":1.0},
                           "box_width_matched":{"KOSPI":1.0,"SSE_A":ratio}},
        "vertical_transform":"Each index divided by its own box-start close times100; no independent trough/peak fitting",
        "window_bounds":bounds,"extra_Korean_point":"October15 is an observed close, dashed to distinguish from the October14 image cutoff",
        "future_Korean_path":None,"no_outcome_optimization":True,"no_official_model_changes":True}
    (ROOT/"chart_contract.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    old=json.loads(baseline.read_text(encoding="utf-8"))["sha256"]
    changed=[name for name,h in old.items() if not (STUDY/name).is_file() or sha(STUDY/name)!=h]
    if changed:
        raise ValueError(f"Previous study changed: {changed}")
    validation={"status":"passed","previous_files_checked":len(old),"previous_files_changed":changed,
                "box_boundaries_first_recovery_verified":True,"KOSPI_span":data["KOSPI"]["span"],
                "SSE_A_span":data["SSE_A"]["span"],"SSE_A_time_scale":ratio,
                "price_source_sha256":sha(PRICE),"transformed_rows":len(transformed),
                "Korean_future_points":0,"probability_outputs":[]}
    (ROOT/"validation.json").write_text(json.dumps(validation,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"passed","charts":3,"SSE_A_scale":ratio,"bounds":bounds},ensure_ascii=False))


if __name__=="__main__":
    main()
