"""Churn measures for a table of subscriptions.

Works on any CSV with these columns:

    customer_id, segment, signup_month (YYYY-MM), churn_month (YYYY-MM or blank)

and optionally `offer` and `monthly_price`. Everything is counted in whole months.
A customer who signs up in March is first at risk in April.

    python churn.py                     # the summary, then every number the write-up uses
    python churn.py my_customers.csv    # the summary for your own file
"""
import sys

import pandas as pd

DEFAULT = "data/customers.csv"


def to_index(s):
    """'2024-03' -> months since year 0, so months can be subtracted."""
    parts = s.str.split("-", expand=True).astype(float)
    return (parts[0] * 12 + parts[1] - 1).astype("Int64")


def label(index):
    return f"{int(index) // 12}-{int(index) % 12 + 1:02d}"


def load(path=DEFAULT):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df["signup"] = to_index(df["signup_month"])
    has_left = df["churn_month"] != ""
    df["left"] = pd.array([pd.NA] * len(df), dtype="Int64")
    df.loc[has_left, "left"] = to_index(df.loc[has_left, "churn_month"])
    if "monthly_price" in df:
        df["monthly_price"] = df["monthly_price"].astype(float)
    if "offer" not in df:
        df["offer"] = ""
    return df


def window(df):
    """First and last month the data can speak for: first churn seen to last month seen."""
    last = int(max(df["signup"].max(), df["left"].max()))
    first = int(df["left"].min())
    return first, last


def monthly(df, by=None, first=None, last=None):
    """One row per month (and per group): customers at the start, how many left, the rate."""
    lo, hi = window(df)
    first, last = lo if first is None else first, hi if last is None else last
    rows = []
    groups = [(None, df)] if by is None else list(df.groupby(by))
    for key, g in groups:
        for m in range(first, last + 1):
            at_start = (g["signup"] < m) & (g["left"].isna() | (g["left"] >= m))
            left = (g["left"] == m)
            n, c = int(at_start.sum()), int((at_start & left).sum())
            row = {"month": label(m), "index": m, "active": n, "churned": c, "rate": c / n if n else float("nan")}
            if by is not None:
                row[by] = key
            rows.append(row)
    return pd.DataFrame(rows)


def pooled(table, months, by=None):
    """Churn over several months taken together: everyone who left / everyone who could have."""
    t = table[table["index"].isin(months)]
    if by is None:
        return t["churned"].sum() / t["active"].sum()
    g = t.groupby(by)[["churned", "active"]].sum()
    return g["churned"] / g["active"]


def shares(table, months, by):
    t = table[table["index"].isin(months)].groupby(by)["active"].sum()
    return t / t.sum()


def decompose(df, early, late, by="segment"):
    """Split the change in overall churn between two periods into two parts per group.

    rate part: the group's own churn changed (weighted by its average share)
    mix part:  the group became a bigger or smaller share (weighted by its average churn,
               measured against the average of the two overall rates so the parts add up)
    The parts sum exactly to the change in the overall rate.
    """
    t = monthly(df, by)
    r0, r1 = pooled(t, early, by), pooled(t, late, by)
    w0, w1 = shares(t, early, by), shares(t, late, by)
    overall = monthly(df)
    a0, a1 = pooled(overall, early), pooled(overall, late)
    mid = (a0 + a1) / 2
    out = pd.DataFrame({
        "share_early": w0, "share_late": w1, "rate_early": r0, "rate_late": r1,
        "rate_part": (r1 - r0) * (w0 + w1) / 2,
        "mix_part": (w1 - w0) * ((r0 + r1) / 2 - mid),
    })
    return out, a0, a1


def standardized(df, base_months, by="segment"):
    """Overall churn each month if the mix of groups had stayed as it was in base_months."""
    t = monthly(df, by)
    w = shares(t, base_months, by)
    wide = t.pivot(index="index", columns=by, values="rate")
    fixed = (wide * w).sum(axis=1)
    return pd.DataFrame({"index": wide.index, "month": [label(i) for i in wide.index], "rate": fixed.values})


def retention(df, horizon, end=None):
    """Share of a group of signups still paying k months after signing up, k = 0..horizon.

    Only uses customers who signed up early enough to be watched for the whole horizon,
    so every point on the curve is based on the same people.
    """
    end = window(df)[1] if end is None else end
    g = df[(df["signup"] + horizon <= end)]
    n = len(g)
    if n == 0:
        return pd.Series(dtype=float), 0
    life = (g["left"] - g["signup"]).astype("Float64")   # months survived before leaving
    alive = [1.0 if k == 0 else float((life.isna() | (life > k)).sum()) / n for k in range(horizon + 1)]
    return pd.Series(alive, index=range(horizon + 1)), n


def hazard_by_tenure(df, max_tenure, end=None):
    """Of customers who reached month k of their life, the share who left in it."""
    end = window(df)[1] if end is None else end
    life = (df["left"] - df["signup"]).astype("Float64")
    seen = end - df["signup"]                           # months we can watch this customer
    rows = []
    for k in range(1, max_tenure + 1):
        at_risk = (seen >= k) & (life.isna() | (life >= k))
        left = at_risk & (life == k)
        n = int(at_risk.sum())
        rows.append({"tenure": k, "at_risk": n, "churned": int(left.sum()), "rate": left.sum() / n if n else float("nan")})
    return pd.DataFrame(rows)


def revenue_per_signup(df, horizon, discount_months=3, discount=0.5, end=None):
    """Average revenue collected in the first `horizon` months, for signups watched that long.

    Billing rule: a customer is billed for each month after the signup month, and leaving
    in month k means month k was not paid. Anyone on an offer pays `discount` less for
    the first `discount_months` bills.
    """
    end = window(df)[1] if end is None else end
    g = df[df["signup"] + horizon <= end]
    life = (g["left"] - g["signup"]).astype("Float64")
    paid = (life - 1).where(life.notna() & (life <= horizon), horizon).astype(float)
    full = g["monthly_price"] * paid
    cut = g["monthly_price"] * discount * paid.clip(upper=discount_months)
    revenue = full - cut.where(g["offer"] != "", 0.0)
    return float(revenue.mean()), len(g)


def facts(df):
    """Every number quoted in the write-up, in one place."""
    first, last = window(df)
    early = list(range(first, first + 6))
    late = list(range(last - 5, last + 1))
    overall = monthly(df)
    seg = monthly(df, "segment")
    parts, a0, a1 = decompose(df, early, late)
    std = standardized(df, early)
    offer_start = int(df.loc[df["offer"] != "", "signup"].min())
    ss = df[df["segment"] == "Self-serve"]
    before = ss[(ss["signup"] >= first) & (ss["signup"] < offer_start)]
    full = ss[(ss["signup"] >= offer_start) & (ss["offer"] == "")]
    offer = ss[ss["offer"] != ""]
    old = ss[ss["signup"] < first]
    h = 9
    f = {
        "customers": len(df),
        "first": label(first), "last": label(last), "offer_start": label(offer_start),
        "overall_early": a0, "overall_late": a1,
        "overall_min": overall["rate"].min(), "overall_max": overall["rate"].max(),
        "self_early": parts.loc["Self-serve", "rate_early"], "self_late": parts.loc["Self-serve", "rate_late"],
        "sales_early": parts.loc["Sales-led", "rate_early"], "sales_late": parts.loc["Sales-led", "rate_late"],
        "self_share_early": parts.loc["Self-serve", "share_early"], "self_share_late": parts.loc["Self-serve", "share_late"],
        "part_self_rate": parts.loc["Self-serve", "rate_part"], "part_sales_rate": parts.loc["Sales-led", "rate_part"],
        "part_mix": parts["mix_part"].sum(),
        "std_late": std[std["index"].isin(late)]["rate"].mean(),
        "keep_before": retention(before, h)[0][h], "keep_full": retention(full, h)[0][h], "keep_offer": retention(offer, h)[0][h],
        "keep_offer_3": retention(offer, h)[0][3], "keep_offer_6": retention(offer, h)[0][6], "keep_before_6": retention(before, h)[0][6],
        "n_before": retention(before, h)[1], "n_full": retention(full, h)[1], "n_offer": retention(offer, h)[1],
        "haz_offer_4": hazard_by_tenure(offer, 8).set_index("tenure").loc[4, "rate"],
        "haz_offer_13": hazard_by_tenure(offer, 8).set_index("tenure").loc[1:3, "churned"].sum() / hazard_by_tenure(offer, 8).set_index("tenure").loc[1:3, "at_risk"].sum(),
        "haz_before_4": hazard_by_tenure(before, 8).set_index("tenure").loc[4, "rate"],
        "rev_before": revenue_per_signup(before, h)[0], "rev_offer": revenue_per_signup(offer, h)[0], "rev_full": revenue_per_signup(full, h)[0],
        "signups_before": len(before) / (offer_start - first),
        "signups_after": (len(full) + len(offer)) / (last - offer_start + 1),
        "signups_offer_share": len(offer) / (len(full) + len(offer)),
        "old_rate_early": pooled(monthly(old), early), "old_rate_late": pooled(monthly(old), late),
        "n_full_month": len(full) / (last - offer_start + 1), "n_offer_month": len(offer) / (last - offer_start + 1),
        "active_first": int(overall.iloc[0]["active"]), "active_last": int(overall.iloc[-1]["active"]),
    }
    f["cohort_rev_before"] = f["signups_before"] * f["rev_before"]
    f["cohort_rev_after"] = f["n_full_month"] * f["rev_full"] + f["n_offer_month"] * f["rev_offer"]
    here = df[(df["signup"] < last) & (df["left"].isna() | (df["left"] >= last))]
    f["self_revenue_share"] = here.loc[here["segment"] == "Self-serve", "monthly_price"].sum() / here["monthly_price"].sum()
    f["sales_avg_price"] = df.loc[df["segment"] == "Sales-led", "monthly_price"].mean()
    q = seg[(seg["segment"] == "Self-serve")].set_index("index")["rate"]
    f["self_dip"] = q.loc[offer_start + 1: offer_start + 3].mean()      # Feb to Apr 2025
    f["self_before_dip"] = q.loc[offer_start - 6: offer_start - 1].mean()
    ov = overall.set_index("index")["rate"]
    f["overall_dip"] = ov.loc[offer_start + 1: offer_start + 3].mean()
    return f


def summary(df, by="segment"):
    """A plain-text rundown for any file: first six months against last six, by group."""
    first, last = window(df)
    span = min(6, (last - first + 1) // 2)
    early, late = list(range(first, first + span)), list(range(last - span + 1, last + 1))
    parts, a0, a1 = decompose(df, early, late, by)
    std = standardized(df, early, by)
    lines = [f"{len(df):,} customers, {label(first)} to {label(last)}",
             f"Comparing the first {span} months with the last {span}", "",
             f"{'':24s}{'early':>9s}{'late':>9s}{'share early':>13s}{'share late':>12s}"]
    for key, r in parts.iterrows():
        lines.append(f"{str(key):24s}{r['rate_early']:>9.2%}{r['rate_late']:>9.2%}{r['share_early']:>13.0%}{r['share_late']:>12.0%}")
    lines += [f"{'All customers':24s}{a0:>9.2%}{a1:>9.2%}", "",
              f"Change in the overall rate: {(a1 - a0) * 100:+.2f} points, made up of"]
    for key, r in parts.iterrows():
        lines.append(f"  {str(key)} churn changing: {r['rate_part'] * 100:+.2f}")
    lines.append(f"  the mix of customers changing: {parts['mix_part'].sum() * 100:+.2f}")
    lines.append(f"Overall rate in the late period if the mix had not changed: {std[std['index'].isin(late)]['rate'].mean():.2%}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(summary(load(sys.argv[1])))
    else:
        data = load(DEFAULT)
        print(summary(data), "\n")
        for k, v in facts(data).items():
            print(f"{k:22s} {v:.4f}" if isinstance(v, float) else f"{k:22s} {v}")
