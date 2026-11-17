"""Makes data/customers.csv: 24 months of subscriptions at a made-up software company.

Nothing here is real. I built the data so that one thing goes wrong in a way the
headline churn number does not show, and the write-up is about how to find it.
What I planted is spelled out in PLANTED below, so nobody has to guess.

    python make_data.py
"""
import csv
import os

import numpy as np

SEED = 11
FIRST = (2024, 1)          # month 0
MONTHS = 24                # Jan 2024 to Dec 2025
OFFER_STARTS = 12          # Jan 2025
SELF_PRICE = 39.0
OFFER_NAME = "Half price for 3 months"

PLANTED = """
1. Two kinds of customer. Self-serve customers pay $39 a month by card and leave
   more often. Sales-led customers sign a contract, pay about ten times as much,
   and leave less often.
2. The company moves upmarket. Sales-led signups grow from about 120 to about 480
   a month, and sales-led churn falls from 2.4% to 0.8% a month.
3. In January 2025 self-serve gets an offer: half price for the first three months.
   Signups jump. People on the offer almost never leave while it lasts, then a
   third of them leave in month four when the price doubles.
4. Everyone else behaves the same in 2025 as in 2024.
"""

# monthly chance of leaving
def hazard(segment, tenure, month, offer):
    if segment == "Sales-led":
        base = 0.024 + (0.008 - 0.024) * month / (MONTHS - 1)
        return base * (1.5 if tenure <= 3 else 1.0)
    if offer:
        return 0.015 if tenure <= 3 else 0.36 if tenure == 4 else 0.20 if tenure == 5 else 0.09
    return 0.065 if tenure <= 3 else 0.042 if tenure <= 12 else 0.030


def label(index):
    y, m = divmod(FIRST[0] * 12 + FIRST[1] - 1 + index, 12)
    return f"{y}-{m + 1:02d}"


def build(seed=SEED):
    rng = np.random.default_rng(seed)
    rows = []

    def add(segment, signup, offer):
        left = None
        for month in range(max(signup + 1, 0), MONTHS):
            if rng.random() < hazard(segment, month - signup, month, offer):
                left = month
                break
        price = SELF_PRICE if segment == "Self-serve" else float(round(rng.lognormal(6.0, 0.35) / 10) * 10)
        rows.append((segment, signup, offer, price, left))

    # customers who were already there on 1 January 2024
    for segment, n in (("Self-serve", 3600), ("Sales-led", 2200)):
        for _ in range(n):
            add(segment, -int(rng.integers(1, 49)), False)

    for month in range(MONTHS):
        offer_on = month >= OFFER_STARTS
        for _ in range(int(rng.poisson(100 if offer_on else 220))):
            add("Self-serve", month, False)
        if offer_on:
            for _ in range(int(rng.poisson(320))):
                add("Self-serve", month, True)
        for _ in range(int(rng.poisson(120 + (480 - 120) * month / (MONTHS - 1)))):
            add("Sales-led", month, False)

    order = rng.permutation(len(rows))
    out = []
    for i, k in enumerate(order):
        segment, signup, offer, price, left = rows[k]
        out.append((f"C{i + 1:05d}", segment, label(signup), OFFER_NAME if offer else "", f"{price:.2f}", "" if left is None else label(left)))
    return out


def main(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "customers.csv")):
    rows = build()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["customer_id", "segment", "signup_month", "offer", "monthly_price", "churn_month"])
        w.writerows(rows)
    print(f"{len(rows):,} customers written to {path}")


if __name__ == "__main__":
    main()
