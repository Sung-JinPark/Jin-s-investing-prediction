"""Plot actual daily prices with explicitly chosen retrospective trend anchors.

Research illustration only. Source history is preserved and supplemental rows
carry provenance. Today's quote is a point, never a finalized daily candle.
"""
import copy
import csv
import datetime as dt
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np

ROOT = Path(__file__).resolve().parent
raw = json.loads((ROOT / "daily_raw.json").read_text(encoding="utf-8"))
quote = {
    "date": "2026-10-13", "time_kst": "10:06", "price": 1478000,
    "source": "Npay public stock page", "venue_label": "KRX",
    "source_url": "https://m.stock.naver.com/domestic/stock/000660/total",
    "page_low": 1476000, "status": "intraday_snapshot_not_final_close",
}
supplement = {
    "date": "2026-10-12", "open": 1640000, "high": 1653000,
    "low": 1605000, "close": 1605000, "volume": 3430409,
    "source_url": "https://stockanalysis.com/quote/krx/000660/history/",
    "reason": "Yahoo public HTML has a fully null row; public history table supplies this candle. Original null row retained in daily_raw.json.",
    "status": "explicit_supplement_secondary_history_not_certified_exchange_receipt",
}
rows = []
for row in raw:
    # This is the declared chart window. Preserve the entire source separately.
    if not "2025-11-26" <= row["date"] <= "2026-10-12":
        continue
    r = copy.deepcopy(row)
    r["source_url"] = "https://finance.yahoo.com/quote/000660.KS/history/"
    if r["date"] == supplement["date"]:
        if not all(r[k] is None for k in ("open", "high", "low", "close")):
            raise ValueError("Supplement is permitted only for the documented null row")
        r = copy.deepcopy(supplement)
    vals = [r[k] for k in ("open", "high", "low", "close")]
    if any(v is None or not math.isfinite(v) or v <= 0 for v in vals):
        raise ValueError(f"Invalid price row: {r}")
    if not (r["low"] <= min(r["open"], r["close"]) <= max(r["open"], r["close"]) <= r["high"]):
        raise ValueError(f"Invalid OHLC containment: {r}")
    rows.append(r)
dates = [r["date"] for r in rows] + [quote["date"]]
if dates != sorted(set(dates)):
    raise ValueError("Dates must be unique and sorted")
index = {d: i for i, d in enumerate(dates)}
n = index[quote["date"]]
lookup = {r["date"]: r for r in rows}

def make_line(name, a, b):
    ia, ib = index[a], index[b]
    ya, yb = lookup[a]["low"], lookup[b]["low"]
    slope = (yb - ya) / (ib - ia)
    values = ya + slope * (np.arange(n + 1) - ia)
    log_slope = (math.log(yb) - math.log(ya)) / (ib - ia)
    log_values = np.exp(math.log(ya) + log_slope * (np.arange(n + 1) - ia))
    breaks = [r["date"] for r in rows if index[r["date"]] > ib and r["close"] < values[index[r["date"]]]]
    log_breaks = [r["date"] for r in rows if index[r["date"]] > ib and r["close"] < log_values[index[r["date"]]]]
    return {"name": name, "anchor_a": {"date": a, "low": ya}, "anchor_b": {"date": b, "low": yb},
            "trading_intervals": ib - ia, "slope_KRW_per_session": slope,
            "at_intraday_date_linear": float(values[n]), "at_intraday_date_log": float(log_values[n]),
            "first_close_break_after_second_anchor_linear": breaks[0] if breaks else None,
            "first_close_break_after_second_anchor_log": log_breaks[0] if log_breaks else None,
            "values": values, "log_values": log_values}

main = make_line("July-September rebound", "2026-07-29", "2026-09-03")
alternate = make_line("August-September rebound", "2026-08-11", "2026-09-03")
long = make_line("November-March lower trend candidate", "2025-11-26", "2026-03-31")

def serial_line(line):
    return {k: v for k, v in line.items() if k not in ("values", "log_values")}

bands = [
    {"lo": 1486000, "hi": 1500000, "kind": "intraday_broken_prior_support", "label": "148.6~150만원", "anchors": ["2026-08-19"]},
    {"lo": 1420000, "hi": 1440000, "kind": "support_candidate", "label": "142~144만원", "anchors": ["2026-08-10", "2026-08-11", "2026-08-12"]},
    {"lo": 1373000, "hi": 1397000, "kind": "support_candidate", "label": "137.3~139.7만원", "anchors": ["2026-08-11", "2026-08-10"]},
    {"lo": 1287000, "hi": 1322000, "kind": "support_candidate", "label": "128.7~132.2만원", "anchors": ["2026-07-30"], "linear_long_trend_at_quote_date": long["at_intraday_date_linear"]},
    {"lo": 1246000, "hi": 1246000, "kind": "historical_low_not_guaranteed_floor", "label": "124.6만원", "anchors": ["2026-07-29"]},
]
analysis = {
    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    "purpose": "retrospective_display_analysis_no_official_forecast_or_probability_change",
    "chart_history_window": {"first": dates[0], "last_finalized": "2026-10-12"},
    "price_unit": "KRW_per_share", "price_column": "close_not_adj_close",
    "axes": "arithmetic price, uniformly spaced observed trading sessions",
    "quote": quote, "supplement": supplement, "lines": [serial_line(main), serial_line(alternate), serial_line(long)],
    "bands": bands,
    "limitations": [
        "Anchors selected retrospectively; no validated forecast or success probability.",
        "Long trend has two anchors and is a lower-confidence candidate; its value depends strongly on axis and anchor selection.",
        "Current public historical vintage, not archived original point-in-time publication receipts.",
        "Public provider OHLC/volume may differ by venue, session and update; no certified KRX daily receipt.",
        "June 10 Yahoo volume is 151; no volume inference or volume panel is used.",
        "Today's quote is a separately sourced timestamped point. No current candle is fabricated.",
        "Support bands group observed lows and closes; they do not guarantee a lower bound.",
    ],
}
(ROOT / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
(ROOT / "chart_history.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
with (ROOT / "chart_history.csv").open("w", newline="", encoding="utf-8-sig") as stream:
    writer = csv.DictWriter(stream, fieldnames=["date", "open", "high", "low", "close", "volume", "source_url"], extrasaction="ignore")
    writer.writeheader(); writer.writerows(rows)

plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False, "font.size": 10.5,
                     "figure.facecolor": "#f6f8fc", "axes.facecolor": "#ffffff", "savefig.facecolor": "#f6f8fc"})
fig = plt.figure(figsize=(15.5, 11.3))
grid = fig.add_gridspec(2, 1, height_ratios=[1.85, 1], hspace=.34)
ax = fig.add_subplot(grid[0]); context = fig.add_subplot(grid[1])
fig.subplots_adjust(left=.075, right=.82, top=.87, bottom=.11)
fig.text(.075, .965, "SK하이닉스 | 상승 빗각선 이탈 이후 하방 경계", fontsize=22, weight="bold", color="#182337")
fig.text(.075, .925, "확인 시세 1,478,000원 · 2026.10.13 10:06 KRX 장중  |  확정 일봉은 10.12까지", fontsize=12, color="#44546c")

def format_axis(axis, start, end, ticks):
    axis.set_xlim(start - 1.5, end + 1.7)
    axis.set_xticks([index[d] for d in ticks], [d[5:].replace("-", "/") for d in ticks])
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 10000:,.0f}"))
    axis.grid(axis="y", lw=.65, color="#e2e7ef")
    axis.set_axisbelow(True)
    axis.set_ylabel("주가 (만원)", color="#50627a")
    for spine in axis.spines.values():
        spine.set_visible(False)
    axis.tick_params(length=0, pad=8, colors="#50627a")

start = index["2026-07-27"]
for r in rows:
    x = index[r["date"]]
    if x < start: continue
    color = "#d16365" if r["close"] >= r["open"] else "#517cba"
    ax.plot([x, x], [r["low"], r["high"]], color=color, lw=.9, alpha=.7)
    ax.add_patch(Rectangle((x - .27, min(r["open"], r["close"])), .54, max(abs(r["close"] - r["open"]), 1800), facecolor=color, edgecolor="none", alpha=.43))
xs = np.arange(start, n)
ax.plot(xs, [rows[i]["close"] for i in xs], color="#253b58", lw=1.65, label="확정 종가", zorder=4)
ax.plot([n - 1, n], [lookup["2026-10-12"]["close"], quote["price"]], ls=":", color="#b13265", lw=2)
ax.scatter(n, quote["price"], s=78, color="#b13265", edgecolor="white", linewidth=1.5, zorder=8)
ax.plot(np.arange(index["2026-07-29"], n + 1), main["values"][index["2026-07-29"]:], color="#d67a13", lw=2.6, label="이탈한 상승선")
ax.plot(np.arange(index["2026-08-11"], n + 1), alternate["values"][index["2026-08-11"]:], color="#d67a13", lw=1.3, ls="--", alpha=.5)
ax.plot(np.arange(start, n + 1), long["values"][start:], color="#157865", lw=2.1, label="장기 하단 후보")

for i, band in enumerate(bands):
    lo, hi = band["lo"], band["hi"]
    center = (lo + hi) / 2
    color = "#ba7656" if i == 0 else "#557ba3"
    if hi > lo:
        ax.axhspan(lo, hi, color=color, alpha=.105, zorder=0)
    ax.axhline(center, color=color, lw=1, ls="--", alpha=.67)
    suffix = "장중 이탈 · 회복 여부 확인" if i == 0 else (["", "① 과거 종가·저가", "② 8월 바닥권", "③ 과거 저점 + 장기선", "④ 7월 최저가"][i])
    label_y = [1493000, 1441000, 1364000, 1305000, 1234000][i]
    ax.annotate(f"{band['label']}\n{suffix}", xy=(1.0, center), xycoords=ax.get_yaxis_transform(),
                xytext=(1.026, label_y), textcoords=ax.get_yaxis_transform(),
                ha="left", va="center", color=color, fontsize=10.2, weight="bold",
                arrowprops={"arrowstyle": "-", "color": color, "lw": .7}, annotation_clip=False)

for d, label, offset in [
    ("2026-07-29", "7/29 저가 124.6만", (12, -25)),
    ("2026-09-03", "9/3 저가 155.8만", (-100, -33)),
]:
    x, y = index[d], lookup[d]["low"]
    ax.scatter(x, y, s=40, facecolor="white", edgecolor="#d67a13", linewidth=1.8, zorder=7)
    ax.annotate(label, (x, y), xytext=offset, textcoords="offset points", fontsize=9.4, color="#9f5c12", arrowprops={"arrowstyle": "-", "color": "#d67a13", "lw": .8})
d = "2026-10-06"
ax.annotate("10/6 종가 이탈 (선형축)", (index[d], lookup[d]["close"]), xytext=(-142, 56), textcoords="offset points", fontsize=10.2, color="#a65a0b", weight="bold", arrowprops={"arrowstyle": "->", "color": "#d67a13", "lw": 1.2})
ax.annotate("장중 147.8만", (n, quote["price"]), xytext=(-91, 58), textcoords="offset points", fontsize=11.2, color="#b13265", weight="bold", bbox={"boxstyle": "round,pad=.3", "fc": "#fff5fa", "ec": "none"}, arrowprops={"arrowstyle": "->", "color": "#b13265", "lw": 1.1})
ax.text(1.018, main["values"][n], f"이탈 상승선 {main['values'][n] / 10000:.1f}만\n7/29 → 9/3 저점 연결\n연한 점선: 8/11 → 9/3", transform=ax.get_yaxis_transform(), color="#a85e0c", fontsize=10.1, weight="bold", ha="left", va="center")
ax.text(.015, .97, "최근 반등 구간 확대 · 같은 거래일 간격으로 저점 연결", transform=ax.transAxes, ha="left", va="top", fontsize=12, weight="bold", color="#253b58")
format_axis(ax, start, n, ["2026-07-29", "2026-08-11", "2026-08-25", "2026-09-03", "2026-09-15", "2026-09-29", "2026-10-13"])
ax.set_ylim(1180000, 2020000); ax.yaxis.set_major_locator(MultipleLocator(100000))

context.plot(np.arange(n), [r["close"] for r in rows], color="#253b58", lw=1.3)
context.fill_between(np.arange(n), [r["low"] for r in rows], [r["high"] for r in rows], color="#7088a7", alpha=.14)
context.plot(np.arange(n + 1), long["values"], color="#157865", lw=2.3)
context.plot(np.arange(index["2026-07-29"], n + 1), main["values"][index["2026-07-29"]:], color="#d67a13", lw=1.4, alpha=.85)
context.scatter(n, quote["price"], color="#b13265", s=35, zorder=5)
for d, label, offset in [
    ("2025-11-26", "11/26 저가 50.1만", (12, 20)),
    ("2026-03-31", "3/31 저가 80.6만", (8, -35)),
]:
    x, y = index[d], lookup[d]["low"]
    context.scatter(x, y, s=40, facecolor="white", edgecolor="#157865", linewidth=1.8, zorder=5)
    context.annotate(label, (x, y), xytext=offset, textcoords="offset points", fontsize=9.5, color="#157865", arrowprops={"arrowstyle": "-", "color": "#157865", "lw": .8})
context.text(1.018, .78, "장기선 · 두 점 기준 참고\n11/26 → 3/31 저점 연결\n선형축: 약 128.95만원\n로그축: 약 171.28만원\n\n128.7~132.2만원은\n과거 수평 가격대가 주된 근거", transform=context.transAxes, ha="left", va="top", color="#157865", fontsize=10.2, linespacing=1.55)
format_axis(context, 0, n, ["2025-11-26", "2026-01-02", "2026-03-03", "2026-04-30", "2026-06-25", "2026-08-11", "2026-10-13"])
context.set_ylim(340000, 3150000); context.yaxis.set_major_locator(MultipleLocator(500000))
context.set_title("장기 흐름 확인 · 수평 128.7만원 부근과 장기 하단 후보가 겹침", loc="left", fontsize=12, color="#253b58", weight="bold", pad=15)
fig.text(.075, .064, "계산 기준: 선형 가격축 · 거래일 간격 · 저가 앵커. 지지 구간은 과거 저가·종가를 묶은 참고 범위이며 바닥을 보장하지 않음.", fontsize=10.1, color="#4c5f78")
fig.text(.075, .034, "출처: Yahoo 공개 일별시세 + 10/12 StockAnalysis 보완 · 오늘 점: Npay 증권 10:06 KRX. 제공처별 시세·거래량 차이 가능.", fontsize=9.6, color="#6b7b90")
fig.savefig(ROOT / "sk_hynix_borders.png", dpi=170)
fig.savefig(ROOT / "sk_hynix_borders.svg")
plt.close(fig)
print(json.dumps({"quote": quote, "lines": analysis["lines"], "validated_finalized_candles": len(rows),
                  "png": str(ROOT / "sk_hynix_borders.png")}, ensure_ascii=True, indent=2))
