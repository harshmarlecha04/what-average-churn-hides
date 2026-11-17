"""Draws the six charts in charts/. Blue marks the thing to look at, gray is context.

    python charts.py

Set CHART_FONT_DIR to a folder of .ttf files to use your own typeface.
"""
import glob
import logging
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter

import churn as c

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "charts")
INK, MUTED, GRID, BLUE, GRAY = "#000000", "#5f5f5f", "#e4e4e4", "#1433ff", "#9a9a9a"
MONTH_NAMES = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

for path in glob.glob(os.path.join(os.environ.get("CHART_FONT_DIR", ""), "*.ttf")) if os.environ.get("CHART_FONT_DIR") else []:
    font_manager.fontManager.addfont(path)
plt.rcParams.update({
    "font.family": ["Geist", "Inter", "Arial", "DejaVu Sans"],
    "font.size": 10.5, "text.color": INK, "axes.labelcolor": MUTED,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": GRID,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
})
pct = FuncFormatter(lambda v, _: f"{v:.0%}")


def nice(index):
    return f"{MONTH_NAMES[int(index) % 12]} {int(index) // 12}"


def frame(title, subtitle, height=4.4):
    fig, ax = plt.subplots(figsize=(8, height), dpi=200)
    fig.subplots_adjust(left=0.07, right=0.80, top=0.80, bottom=0.11)
    fig.text(0.07, 0.945, title, fontsize=14, fontweight=500, ha="left", va="top")
    fig.text(0.07, 0.875, subtitle, fontsize=10, color=MUTED, ha="left", va="top")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#bdbdbd")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, labelsize=9.5)
    return fig, ax


def months_axis(ax, idx):
    ticks = [i for i in idx if i % 12 in (0, 6)]
    ax.set_xticks(ticks, [nice(i) for i in ticks])
    ax.set_xlim(min(idx) - 0.4, max(idx) + 0.4)


def end_label(ax, x, y, text, color=INK, dy=0, weight=400):
    ax.annotate(text, (x, y), xytext=(8, dy), textcoords="offset points", va="center", ha="left", fontsize=9.5, color=color, fontweight=weight, annotation_clip=False)


def save(fig, name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    fig.savefig(path)
    plt.close(fig)
    return path


def chart_overall(df, f):
    t = c.monthly(df)
    fig, ax = frame("Monthly churn, all customers", f"Share of customers who left each month. {f['overall_early']:.1%} in the first six months, {f['overall_late']:.1%} in the last six.")
    ax.plot(t["index"], t["rate"], color=INK, linewidth=2, solid_capstyle="round")
    ax.set_ylim(0, 0.07)
    ax.yaxis.set_major_formatter(pct)
    months_axis(ax, list(t["index"]))
    end_label(ax, t["index"].iloc[-1], t["rate"].iloc[-1], f"{t['rate'].iloc[-1]:.1%}", weight=500)
    return save(fig, "1-overall.png")


def chart_segments(df, f):
    t = c.monthly(df)
    s = c.monthly(df, "segment").pivot(index="index", columns="segment", values="rate")
    fig, ax = frame("The same churn, split by how the customer buys", "Self-serve customers pay by card each month. Sales-led customers sign a contract.")
    ax.plot(s.index, s["Sales-led"], color=GRAY, linewidth=2, label="Sales-led")
    ax.plot(t["index"], t["rate"], color=INK, linewidth=1.2, label="All customers")
    ax.plot(s.index, s["Self-serve"], color=BLUE, linewidth=2.2, label="Self-serve")
    ax.set_ylim(0, 0.07)
    ax.yaxis.set_major_formatter(pct)
    months_axis(ax, list(s.index))
    x = s.index[-1]
    end_label(ax, x, s["Self-serve"].iloc[-1], f"Self-serve {s['Self-serve'].iloc[-1]:.1%}", weight=500)
    end_label(ax, x, t["rate"].iloc[-1], f"All customers {t['rate'].iloc[-1]:.1%}")
    end_label(ax, x, s["Sales-led"].iloc[-1], f"Sales-led {s['Sales-led'].iloc[-1]:.1%}")
    year, month = f["offer_start"].split("-")
    start = int(year) * 12 + int(month) - 1
    ax.axvline(start, color="#bdbdbd", linewidth=0.8)
    ax.text(start + 0.3, 0.002, "Half-price offer starts", fontsize=9, color=MUTED, va="bottom")
    ax.legend(loc="upper left", frameon=False, fontsize=9, ncols=3, handlelength=1.4, columnspacing=1.4, borderaxespad=0.2)
    return save(fig, "2-by-segment.png")


def chart_parts(df, f):
    rows = [
        ("Self-serve churn rose", f["part_self_rate"], BLUE),
        ("Sales-led churn fell", f["part_sales_rate"], GRAY),
        ("More of the base is sales-led", f["part_mix"], GRAY),
        ("What the dashboard shows", f["overall_late"] - f["overall_early"], INK),
    ]
    fig, ax = frame("Three changes that cancel out", "Change in overall monthly churn, first six months to last six, in percentage points.", height=3.6)
    fig.subplots_adjust(left=0.30, right=0.93, top=0.74, bottom=0.08)
    ax.grid(False)
    ax.spines["bottom"].set_visible(False)
    for i, (name, v, color) in enumerate(rows):
        y = len(rows) - 1 - i
        ax.barh(y, v * 100, height=0.46, color=color)
        text = f"{v * 100:+.2f}" if abs(v * 100) >= 0.005 else "0.00"
        ax.text(v * 100 + (0.03 if v >= 0 else -0.03), y, text, va="center", ha="left" if v >= 0 else "right", fontsize=10, fontweight=500)
    ax.axvline(0, color=INK, linewidth=0.8)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows][::-1], fontsize=10, color=INK)
    ax.set_xticks([])
    ax.set_xlim(-0.95, 1.3)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    return save(fig, "3-what-cancelled.png")


def self_serve_groups(df):
    first, _ = c.window(df)
    ss = df[df["segment"] == "Self-serve"]
    start = int(ss.loc[ss["offer"] != "", "signup"].min())
    return {
        "before": ss[(ss["signup"] >= first) & (ss["signup"] < start)],
        "full": ss[(ss["signup"] >= start) & (ss["offer"] == "")],
        "offer": ss[ss["offer"] != ""],
    }


def chart_cohorts(df, f, horizon=9):
    g = self_serve_groups(df)
    fig, ax = frame("Self-serve customers still paying, by when they signed up", f"Only customers who could be followed for {horizon} months, so every point counts the same people.")
    curves = [("before", "Signed up in 2024", GRAY, 2), ("full", "2025, full price", "#4d4d4d", 1.4), ("offer", "2025, on the offer", BLUE, 2.2)]
    ends = {}
    for key, name, color, width in curves:
        r, n = c.retention(g[key], horizon)
        ax.plot(r.index, r.values, color=color, linewidth=width, label=name)
        ends[key] = (name, r.iloc[-1])
    nudge = 7 if abs(ends["full"][1] - ends["before"][1]) < 0.05 else 0
    hi, lo = ("full", "before") if ends["full"][1] >= ends["before"][1] else ("before", "full")
    end_label(ax, horizon, ends[hi][1], f"{ends[hi][0]} {ends[hi][1]:.0%}", dy=nudge)
    end_label(ax, horizon, ends[lo][1], f"{ends[lo][0]} {ends[lo][1]:.0%}", dy=-nudge)
    end_label(ax, horizon, ends["offer"][1], f"{ends['offer'][0]} {ends['offer'][1]:.0%}", weight=500)
    ax.set_ylim(0, 1.02)
    ax.yaxis.set_major_formatter(pct)
    ax.set_xticks(range(horizon + 1))
    ax.set_xlim(-0.2, horizon + 0.2)
    ax.set_xlabel("Months since signing up", fontsize=9.5)
    fig.subplots_adjust(bottom=0.15, right=0.74)
    ax.legend(loc="lower left", frameon=False, fontsize=9, handlelength=1.4)
    return save(fig, "4-cohorts.png")


def chart_hazard(df, f, max_tenure=8):
    g = self_serve_groups(df)
    a = c.hazard_by_tenure(g["before"], max_tenure)
    b = c.hazard_by_tenure(g["offer"], max_tenure)
    fig, ax = frame("When self-serve customers leave", "Of customers who reached each month of their subscription, the share who left in it.")
    ax.plot(a["tenure"], a["rate"], color=GRAY, linewidth=2, marker="o", markersize=5, markeredgecolor="white", markeredgewidth=1.2, label="Signed up in 2024")
    ax.plot(b["tenure"], b["rate"], color=BLUE, linewidth=2.2, marker="o", markersize=5.5, markeredgecolor="white", markeredgewidth=1.2, label="2025, on the offer")
    peak = b.set_index("tenure").loc[4, "rate"]
    ax.annotate(f"{peak:.0%} leave in month 4,\nthe first month at full price", (4, peak), xytext=(14, -4), textcoords="offset points", fontsize=9.5, va="center")
    end_label(ax, max_tenure, b["rate"].iloc[-1], f"On the offer {b['rate'].iloc[-1]:.0%}", weight=500)
    end_label(ax, max_tenure, a["rate"].iloc[-1], f"Signed up in 2024 {a['rate'].iloc[-1]:.0%}")
    ax.set_ylim(0, 0.42)
    ax.yaxis.set_major_formatter(pct)
    ax.set_xticks(range(1, max_tenure + 1))
    ax.set_xlim(0.7, max_tenure + 0.3)
    ax.set_xlabel("Month of subscription", fontsize=9.5)
    fig.subplots_adjust(bottom=0.15, right=0.76)
    ax.legend(loc="upper left", frameon=False, fontsize=9, handlelength=1.4)
    return save(fig, "5-when-they-leave.png")


def chart_standardized(df, f):
    first, _ = c.window(df)
    t = c.monthly(df)
    s = c.standardized(df, list(range(first, first + 6)))
    fig, ax = frame("Churn if the customer mix had stayed put", "Same monthly rates for each kind of customer, weighted by the mix of early 2024.")
    ax.plot(t["index"], t["rate"], color=INK, linewidth=1.6, label="As reported")
    ax.plot(s["index"], s["rate"], color=BLUE, linewidth=2.2, label="Mix held at early 2024")
    ax.set_ylim(0, 0.07)
    ax.yaxis.set_major_formatter(pct)
    months_axis(ax, list(t["index"]))
    x = t["index"].iloc[-1]
    end_label(ax, x, s["rate"].iloc[-1], f"Mix held {s['rate'].iloc[-1]:.1%}", weight=500)
    end_label(ax, x, t["rate"].iloc[-1], f"As reported {t['rate'].iloc[-1]:.1%}")
    ax.legend(loc="upper left", frameon=False, fontsize=9, ncols=2, handlelength=1.4, borderaxespad=0.2)
    return save(fig, "6-mix-held.png")


def main(path=c.DEFAULT):
    df = c.load(os.path.join(HERE, path) if not os.path.isabs(path) else path)
    f = c.facts(df)
    for fn in (chart_overall, chart_segments, chart_parts, chart_cohorts, chart_hazard, chart_standardized):
        print(fn(df, f))


if __name__ == "__main__":
    main()
