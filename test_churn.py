"""Tests for churn.py.

The first group checks each measure on a few customers small enough to work out by hand.
The second group checks the shipped data and that README.md quotes it correctly.

    pytest
"""
import csv
import io
import os
import re

import pandas as pd
import pytest

import churn as c
import make_data

HERE = os.path.dirname(os.path.abspath(__file__))


def frame(rows):
    """rows: (id, segment, signup, churn or '', offer or '', price)"""
    text = "customer_id,segment,signup_month,churn_month,offer,monthly_price\n" + "\n".join(
        ",".join(str(x) for x in r) for r in rows)
    path = io.StringIO(text)
    return c.load(path)


def ix(s):
    y, m = s.split("-")
    return int(y) * 12 + int(m) - 1


SMALL = [
    ("A", "X", "2023-12", "", "", 40),
    ("B", "X", "2023-12", "2024-02", "", 40),
    ("C", "Y", "2024-01", "2024-02", "", 40),
    ("D", "Y", "2024-02", "", "", 40),
]


# ---- the measures, on hand-checked examples ----------------------------------------------

def test_month_labels_round_trip():
    assert c.label(ix("2024-01")) == "2024-01"
    assert c.label(ix("2025-12")) == "2025-12"
    assert ix("2025-01") - ix("2024-12") == 1


def test_a_new_signup_is_not_at_risk_in_its_first_month():
    t = c.monthly(frame(SMALL), first=ix("2024-01"), last=ix("2024-02")).set_index("month")
    assert t.loc["2024-01", "active"] == 2          # A and B. C signed up this month.
    assert t.loc["2024-01", "churned"] == 0
    assert t.loc["2024-02", "active"] == 3          # A, B and C. D signed up this month.
    assert t.loc["2024-02", "churned"] == 2
    assert t.loc["2024-02", "rate"] == pytest.approx(2 / 3)


def test_someone_who_left_is_not_counted_afterwards():
    t = c.monthly(frame(SMALL), first=ix("2024-03"), last=ix("2024-03"))
    assert t.iloc[0]["active"] == 2                 # A and D
    assert t.iloc[0]["churned"] == 0


def test_monthly_by_group():
    t = c.monthly(frame(SMALL), "segment", first=ix("2024-02"), last=ix("2024-02")).set_index("segment")
    assert t.loc["X", "rate"] == pytest.approx(1 / 2)
    assert t.loc["Y", "rate"] == pytest.approx(1 / 1)


def test_pooled_adds_customers_not_rates():
    t = c.monthly(frame(SMALL), first=ix("2024-01"), last=ix("2024-02"))
    assert c.pooled(t, [ix("2024-01"), ix("2024-02")]) == pytest.approx(2 / 5)   # not (0 + 2/3) / 2


def test_shares():
    t = c.monthly(frame(SMALL), "segment", first=ix("2024-02"), last=ix("2024-02"))
    s = c.shares(t, [ix("2024-02")], "segment")
    assert s["X"] == pytest.approx(2 / 3) and s["Y"] == pytest.approx(1 / 3)


def two_period_example():
    # Period 1 (2024-02): X has 4 customers and loses 1, Y has 2 and loses 1.
    # Period 2 (2024-04): X has 3 and loses 0, Y has 5 and loses 2.
    rows = [(f"x{i}", "X", "2024-01", "2024-02" if i == 0 else "", "", 40) for i in range(4)]
    rows += [(f"y{i}", "Y", "2024-01", "2024-02" if i == 0 else "", "", 40) for i in range(2)]
    rows += [(f"z{i}", "Y", "2024-03", "2024-04" if i < 2 else "", "", 40) for i in range(4)]
    return frame(rows)


def test_decompose_by_hand():
    df = two_period_example()
    parts, a0, a1 = c.decompose(df, [ix("2024-02")], [ix("2024-04")])
    assert a0 == pytest.approx(2 / 6) and a1 == pytest.approx(2 / 8)
    assert parts.loc["X", "rate_early"] == pytest.approx(1 / 4) and parts.loc["X", "rate_late"] == 0
    assert parts.loc["Y", "rate_early"] == pytest.approx(1 / 2) and parts.loc["Y", "rate_late"] == pytest.approx(2 / 5)
    assert parts.loc["X", "share_early"] == pytest.approx(4 / 6) and parts.loc["X", "share_late"] == pytest.approx(3 / 8)
    # X's own rate fell by 0.25 at an average share of (4/6 + 3/8) / 2
    assert parts.loc["X", "rate_part"] == pytest.approx(-0.25 * (4 / 6 + 3 / 8) / 2)


def test_decompose_parts_add_up_exactly():
    df = two_period_example()
    parts, a0, a1 = c.decompose(df, [ix("2024-02")], [ix("2024-04")])
    assert parts["rate_part"].sum() + parts["mix_part"].sum() == pytest.approx(a1 - a0, abs=1e-12)


def test_mix_alone_moves_the_total():
    # Nobody's rate changes: X always loses 1 in 2, Y never loses anyone. Only the mix moves.
    rows = [("x0", "X", "2024-01", "2024-02", "", 40), ("x1", "X", "2024-01", "", "", 40)]
    rows += [(f"y{i}", "Y", "2024-01", "", "", 40) for i in range(2)]
    rows += [("x2", "X", "2024-03", "2024-04", "", 40)]
    rows += [(f"w{i}", "Y", "2024-03", "", "", 40) for i in range(6)]
    df = frame(rows)
    parts, a0, a1 = c.decompose(df, [ix("2024-02")], [ix("2024-04")])
    assert parts.loc["X", "rate_early"] == parts.loc["X", "rate_late"] == 0.5
    assert a0 == pytest.approx(1 / 4) and a1 == pytest.approx(1 / 10)
    assert parts["rate_part"].abs().sum() == pytest.approx(0)
    assert parts["mix_part"].sum() == pytest.approx(a1 - a0)


def test_standardized_ignores_a_change_in_mix():
    rows = [("x0", "X", "2024-01", "2024-02", "", 40), ("x1", "X", "2024-01", "", "", 40)]
    rows += [(f"y{i}", "Y", "2024-01", "", "", 40) for i in range(2)]
    rows += [("x2", "X", "2024-03", "2024-04", "", 40)]
    rows += [(f"w{i}", "Y", "2024-03", "", "", 40) for i in range(6)]
    s = c.standardized(frame(rows), [ix("2024-02")]).set_index("month")
    assert s.loc["2024-02", "rate"] == pytest.approx(0.25)
    assert s.loc["2024-04", "rate"] == pytest.approx(0.25)     # reported is 0.10


def test_standardized_equals_reported_with_one_group():
    rows = [(r[0], "Only", *r[2:]) for r in SMALL]
    df = frame(rows)
    s = c.standardized(df, [ix("2024-02")], "segment")
    t = c.monthly(df)
    assert list(s["rate"]) == pytest.approx(list(t["rate"]))


COHORT = [
    ("a", "X", "2024-01", "2024-02", "", 40),     # left in month 1
    ("b", "X", "2024-01", "2024-04", "", 40),     # left in month 3
    ("c", "X", "2024-01", "", "", 40),            # still here
    ("d", "X", "2024-05", "", "", 40),            # signed up too late to follow for 3 months
]


def test_retention_by_hand():
    r, n = c.retention(frame(COHORT), 3, end=ix("2024-06"))
    assert n == 3
    assert list(r) == pytest.approx([1.0, 2 / 3, 2 / 3, 1 / 3])


def test_retention_leaves_out_customers_it_cannot_follow():
    r, n = c.retention(frame(COHORT), 1, end=ix("2024-06"))
    assert n == 4 and r[1] == pytest.approx(3 / 4)


def test_retention_with_nobody_to_follow():
    r, n = c.retention(frame(COHORT), 12, end=ix("2024-06"))
    assert n == 0 and len(r) == 0


def test_timing_by_hand():
    h = c.hazard_by_tenure(frame(COHORT), 3, end=ix("2024-06")).set_index("tenure")
    assert h.loc[1, "at_risk"] == 4 and h.loc[1, "churned"] == 1
    assert h.loc[2, "at_risk"] == 2 and h.loc[2, "churned"] == 0      # d has only been seen for one month
    assert h.loc[3, "at_risk"] == 2 and h.loc[3, "rate"] == pytest.approx(1 / 2)


def test_revenue_by_hand():
    rows = [
        ("a", "X", "2024-01", "2024-05", "Half", 40),   # left in month 4: paid 3 months at half price = 60
        ("b", "X", "2024-01", "", "Half", 40),          # stayed: 3 at 20 + 6 at 40 = 300
        ("c", "X", "2024-01", "", "", 40),              # no offer, stayed: 9 at 40 = 360
        ("d", "X", "2024-09", "", "", 40),              # cannot be followed for 9 months
    ]
    df = frame(rows)
    value, n = c.revenue_per_signup(df, 9, end=ix("2024-12"))
    assert n == 3 and value == pytest.approx((60 + 300 + 360) / 3)
    value, n = c.revenue_per_signup(df[df["offer"] != ""], 9, end=ix("2024-12"))
    assert n == 2 and value == pytest.approx(180)


def test_summary_runs_on_a_plain_file():
    text = c.summary(two_period_example())
    assert "10 customers" in text and "All customers" in text


# ---- the shipped data and the write-up ---------------------------------------------------

@pytest.fixture(scope="module")
def df():
    return c.load(os.path.join(HERE, "data", "customers.csv"))


@pytest.fixture(scope="module")
def f(df):
    return c.facts(df)


def test_data_file_is_what_the_generator_makes():
    with open(os.path.join(HERE, "data", "customers.csv"), newline="", encoding="utf-8") as fh:
        on_disk = [tuple(r) for r in csv.reader(fh)][1:]
    assert on_disk == make_data.build()


def test_nobody_leaves_before_or_in_the_month_they_sign_up(df):
    left = df[df["left"].notna()]
    assert (left["left"] > left["signup"]).all()
    assert df["customer_id"].is_unique


def test_the_story_is_in_the_data(f):
    assert abs(f["overall_late"] - f["overall_early"]) < 0.002          # the total barely moves
    assert f["self_late"] - f["self_early"] > 0.015                      # self-serve gets worse
    assert f["sales_late"] < f["sales_early"] / 2                        # sales-led gets better
    assert f["keep_offer"] < f["keep_before"] / 1.8                      # offer customers do not stay
    assert f["haz_offer_4"] > 0.3 and f["haz_offer_13"] < 0.02
    assert f["part_self_rate"] + f["part_sales_rate"] + f["part_mix"] == pytest.approx(f["overall_late"] - f["overall_early"], abs=1e-12)


def test_customers_from_before_2024_did_not_get_worse(f):
    assert f["old_rate_late"] <= f["old_rate_early"]


def test_readme_quotes_the_data(f):
    text = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()

    def has(s):
        assert s in text, s

    has(f"{f['customers']:,} customers")
    has(f"was {f['overall_early']:.1%}. Over the last six months of 2025 it was {f['overall_late']:.1%}")
    has(f"from {f['active_first']:,} to {f['active_last']:,}")
    has(f"at {f['overall_min']:.1%}")
    has(f"| Self-serve | {f['self_early']:.1%} | {f['self_late']:.1%} |")
    has(f"| Sales-led | {f['sales_early']:.1%} | {f['sales_late']:.1%} |")
    has(f"{f['self_share_early']:.0%} of customers at the start and {f['self_share_late']:.0%} at the end")
    has(f"added {f['part_self_rate'] * 100:.2f} points")
    has(f"took off {-f['part_sales_rate'] * 100:.2f}")
    has(f"took off {-f['part_mix'] * 100:.2f}")
    has(f"to about {f['overall_early'] + f['part_self_rate']:.1%}")
    has(f"signed up in 2024, {f['keep_before']:.0%} were still paying")
    has(f"took the offer, {f['keep_offer']:.0%} were still paying")
    has(f"{f['keep_full']:.0%}, on a small group of {f['n_full']}")
    has(f"{f['haz_offer_13']:.1%} a month")
    has(f"and {f['haz_offer_4']:.0%} leave")
    has(f"an ordinary {f['haz_before_4']:.1%}")
    has(f"from about {f['signups_before']:.0f} a month to about {f['signups_after']:.0f}")
    has(f"from {f['self_before_dip']:.1%} in late 2024 to {f['self_dip']:.1%}")
    has(f"is {f['std_late']:.1%}, against the {f['overall_late']:.1%}")
    has(f"paid ${f['rev_offer']:.0f} on average. A 2024 signup paid ${f['rev_before']:.0f}")
    has(f"${round(f['cohort_rev_after'], -2):,.0f}")
    has(f"${round(f['cohort_rev_before'], -2):,.0f}")
    has(f"{f['self_share_late']:.0%} of customers and {f['self_revenue_share']:.0%} of monthly revenue")
    has(f"about ${round(f['sales_avg_price'], -1):.0f} a month")
    tests = len(re.findall(r"^def test_", open(os.path.join(HERE, "test_churn.py"), encoding="utf-8").read(), re.M))
    has(f"{tests} tests")
