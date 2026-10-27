"""
Simulates the true money movements for one synthetic consumer brand.

Everything here is invented. The simulation produces the "truth": every order,
payout, settlement, bank line and card line, each tagged with what the money
actually is. The renderers in render.py then turn that truth into messy exports
the way real platforms and banks write them.

Built by Avinash Rayudu.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

SIM_START = date(2026, 6, 1)      # warm-up so June orders and card charges exist
ORDER_START = date(2026, 6, 20)
WIN_START = date(2026, 7, 1)
WIN_END = date(2026, 10, 25)
UPLOAD_1 = (date(2026, 7, 1), date(2026, 8, 31))
UPLOAD_2 = (date(2026, 9, 1), date(2026, 10, 25))
BANK_OVERLAP_DAYS = 7              # upload 2 bank export re-includes the last week of upload 1
CARD_UPLOAD_1_START = date(2026, 6, 29)   # card exports follow statement cycles


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def is_bday(d: date) -> bool:
    return d.weekday() < 5


def bdays_after(d: date, n: int) -> date:
    out = d
    k = 0
    while k < n:
        out += timedelta(days=1)
        if is_bday(out):
            k += 1
    return out


def next_bday(d: date) -> date:
    while not is_bday(d):
        d += timedelta(days=1)
    return d


@dataclass
class BrandSim:
    spec: dict
    orders: pd.DataFrame = None          # one row per order (with line items list)
    order_items: pd.DataFrame = None     # one row per line item
    refunds: pd.DataFrame = None
    payouts: pd.DataFrame = None
    amazon_rows: pd.DataFrame = None
    amazon_settlements: pd.DataFrame = None
    faire_orders: pd.DataFrame = None
    bank: pd.DataFrame = None
    card: pd.DataFrame = None
    coa: pd.DataFrame = None
    receipts_truth: pd.DataFrame = None
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- shopify
def sim_shopify(spec, rng):
    share = spec["shares"].get("shopify", 0)
    aov = spec["aov"]
    daily = spec["annual_rev"] * share / 365.0 / aov
    n_sku = 10
    sku_prices = np.round(rng.uniform(0.45, 1.05, n_sku) * aov, 0) - 0.01
    skus = [f"{spec['sku_prefix']}-{1000 + i * 7}" for i in range(n_sku)]
    rows, items = [], []
    order_no = spec.get("order_start", 1001)
    for d in daterange(ORDER_START, WIN_END):
        wk = [0.92, 0.95, 0.97, 1.0, 1.05, 1.15, 1.12][d.weekday()]
        trend = 1.0 + 0.0015 * (d - ORDER_START).days
        n = rng.poisson(daily * wk * trend)
        for _ in range(n):
            k = rng.choice([1, 2, 3], p=[0.62, 0.29, 0.09])
            idx = rng.choice(n_sku, size=k)
            qty = [int(rng.choice([1, 1, 1, 2])) for _ in idx]
            subtotal = round(float(sum(sku_prices[i] * q for i, q in zip(idx, qty))), 2)
            disc = 0.0
            if rng.random() < 0.24:
                disc = round(subtotal * float(rng.choice([0.10, 0.15, 0.20])), 2)
            ship = 0.0 if subtotal >= 75 else 7.95
            tax = round((subtotal - disc) * spec["tax_rate"], 2)
            total = round(subtotal - disc + ship + tax, 2)
            secs = int(rng.integers(0, 86400))
            created = pd.Timestamp(d) + pd.Timedelta(seconds=secs)
            oid = f"{spec.get('order_prefix', '#')}{order_no}"
            order_no += 1
            rows.append(dict(order_id=oid, created_at=created, day=d, subtotal=subtotal,
                             discount=disc, shipping=ship, tax=tax, total=total,
                             fee=round(total * 0.029 + 0.30, 2)))
            for i, q in zip(idx, qty):
                items.append(dict(order_id=oid, sku=skus[i], name=f"Item {skus[i]}",
                                  qty=q, price=float(sku_prices[i])))
    orders = pd.DataFrame(rows)
    order_items = pd.DataFrame(items)

    # refunds and chargebacks
    ref = []
    for r in orders.itertuples():
        u = rng.random()
        if u < 0.055:
            rd = r.day + timedelta(days=int(rng.integers(4, 26)))
            amt = r.total if rng.random() < 0.7 else round(min(r.total, r.subtotal * 0.5), 2)
            ref.append(dict(order_id=r.order_id, refund_date=rd, amount=round(amt, 2), kind="refund"))
        elif u < 0.057:
            rd = r.day + timedelta(days=int(rng.integers(20, 40)))
            ref.append(dict(order_id=r.order_id, refund_date=rd, amount=r.total, kind="chargeback"))
    refunds = pd.DataFrame(ref, columns=["order_id", "refund_date", "amount", "kind"])

    # payouts: charges settle 2 business days after the order day
    orders["payout_date"] = [bdays_after(d, 2) for d in orders["day"]]
    refunds["payout_date"] = [bdays_after(d, 2) for d in refunds["refund_date"]]
    pay = {}
    for r in orders.itertuples():
        p = pay.setdefault(r.payout_date, dict(charges=0.0, refunds=0.0, fees=0.0, adjustments=0.0, n=0))
        p["charges"] += r.total
        p["fees"] += r.fee
        p["n"] += 1
    for r in refunds.itertuples():
        p = pay.setdefault(r.payout_date, dict(charges=0.0, refunds=0.0, fees=0.0, adjustments=0.0, n=0))
        if r.kind == "refund":
            p["refunds"] += r.amount
        else:
            p["adjustments"] -= r.amount + 15.0   # chargeback plus dispute fee
    prow = []
    for i, (pd_, p) in enumerate(sorted(pay.items())):
        charges = round(p["charges"], 2)
        refs = round(p["refunds"], 2)
        fees = round(p["fees"], 2)
        adj = round(p["adjustments"], 2)
        net = round(charges - refs - fees + adj, 2)
        prow.append(dict(payout_id=f"{spec['payout_prefix']}{70000 + i * 13}", payout_date=pd_,
                         charges=charges, refunds=refs, fees=fees, adjustments=adj, net=net))
    payouts = pd.DataFrame(prow)
    return orders, order_items, refunds, payouts


# --------------------------------------------------------------------------- amazon
def sim_amazon(spec, rng):
    share = spec["shares"].get("amazon", 0)
    if share <= 0:
        return None, None
    aov = spec.get("amazon_aov", 54.0)
    daily = spec["annual_rev"] * share / 365.0 / aov
    fba = spec.get("fba_fee", 5.05)
    starts = [date(2026, 6, 25) + timedelta(days=14 * k) for k in range(9)]
    rows, setts = [], []
    reserve_carry = 0.0
    oc = 0
    for k, s in enumerate(starts):
        e = s + timedelta(days=13)
        deposit = e + timedelta(days=2)
        if deposit > WIN_END:
            break
        sid = f"{spec['amazon_sid_base'] + k * 97}"
        det = []
        for d in daterange(s, e):
            for _ in range(rng.poisson(daily)):
                oc += 1
                oid = f"11{rng.integers(1, 9)}-{rng.integers(1000000, 9999999)}-{rng.integers(1000000, 9999999)}"
                units = int(rng.choice([1, 1, 1, 2]))
                price = round(float(aov * rng.uniform(0.8, 1.2)), 2)
                principal = round(price * units, 2)
                det.append(("Order", oid, "ItemPrice", "Principal", principal, d))
                det.append(("Order", oid, "ItemFees", "Commission", round(-0.15 * principal, 2), d))
                det.append(("Order", oid, "ItemFees", "FBAPerUnitFulfillmentFee", round(-fba * units, 2), d))
                if rng.random() < 0.03:
                    rd = min(d + timedelta(days=int(rng.integers(2, 9))), e)
                    det.append(("Refund", oid, "ItemPrice", "Principal", -principal, rd))
                    det.append(("Refund", oid, "ItemFees", "Commission", round(0.12 * principal, 2), rd))
        if s.day <= 14 or k == 0:
            det.append(("other-transaction", "", "other-transaction", "Subscription Fee", -39.99, s))
        if spec.get("amazon_ads_in_settlement"):
            det.append(("other-transaction", "", "other-transaction", "Cost of Advertising",
                        round(-float(rng.uniform(300, 900)), 2), e))
        if spec.get("amazon_reserve") and k in (2, 5):
            hold = round(float(rng.uniform(800, 2500)), 2)
            det.append(("other-transaction", "", "other-transaction", "Current Reserve Amount", -hold, e))
            reserve_carry = hold
        elif spec.get("amazon_reserve") and reserve_carry and k in (3, 6):
            det.append(("other-transaction", "", "other-transaction", "Previous Reserve Amount Balance",
                        reserve_carry, s))
            reserve_carry = 0.0
        total = round(sum(x[4] for x in det), 2)
        setts.append(dict(settlement_id=sid, start=s, end=e, deposit_date=deposit, total=total))
        for t in det:
            rows.append(dict(settlement_id=sid, transaction_type=t[0], order_id=t[1], amount_type=t[2],
                             amount_description=t[3], amount=t[4], posted_date=t[5]))
    return pd.DataFrame(rows), pd.DataFrame(setts)


# --------------------------------------------------------------------------- faire
def sim_faire(spec, rng):
    share = spec["shares"].get("faire", 0)
    if share <= 0:
        return None
    avg = 850.0
    weekly = spec["annual_rev"] * share / 52.0 / avg
    rows = []
    n = 0
    retailers = spec["faire_retailers"]
    for d in daterange(date(2026, 6, 10), WIN_END):
        if d.weekday() != 0:
            continue
        for _ in range(rng.poisson(weekly)):
            od = d + timedelta(days=int(rng.integers(0, 7)))
            ship = od + timedelta(days=int(rng.integers(2, 9)))
            payout = bdays_after(ship, 2)
            whole = round(float(rng.uniform(300, 2200)), 2)
            first = rng.random() < 0.3
            comm = round(whole * (0.25 if first else 0.15), 2)
            n += 1
            rows.append(dict(order_number=f"{spec['faire_prefix']}{n:05d}",
                             retailer=retailers[int(rng.integers(0, len(retailers)))],
                             order_date=od, ship_date=ship, payout_date=payout,
                             wholesale_total=whole, commission=comm,
                             payout_amount=round(whole - comm, 2)))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- card
def sim_card(spec, rng):
    """Card charges from SIM_START plus monthly payment rows. amount > 0 means a charge."""
    rev = spec["annual_rev"]
    ad_daily = rev * spec.get("ad_rate", 0.17) / 365.0
    platforms = spec["ad_platforms"]          # list of (name_key, share, threshold)
    acc = {p[0]: 0.0 for p in platforms}
    rows = []
    for d in daterange(SIM_START, WIN_END):
        wk = [0.95, 0.97, 1.0, 1.0, 1.03, 1.05, 1.0][d.weekday()]
        for key, sh, thr in platforms:
            if key == "meta" and spec.get("meta_direct_debit"):
                continue
            acc[key] += ad_daily * sh * wk * float(rng.uniform(0.85, 1.15))
            while acc[key] >= thr:
                rows.append(dict(date=d, amount=float(thr), label="ad_spend", cp=key))
                acc[key] -= thr
            if d.day == 1 and acc[key] > 50:
                rows.append(dict(date=d, amount=round(acc[key], 2), label="ad_spend", cp=key))
                acc[key] = 0.0
        for key, day, amt in spec["card_software"]:
            if d.day == day:
                rows.append(dict(date=d, amount=float(amt), label="software_opex", cp=key))
        if rng.random() < spec.get("travel_rate", 0.22):
            key = spec["travel_merchants"][int(rng.integers(0, len(spec["travel_merchants"])))]
            rows.append(dict(date=d, amount=round(float(rng.uniform(14, 420)), 2), label="travel_other", cp=key))
        if rng.random() < 0.10:
            key = spec["supply_merchants"][int(rng.integers(0, len(spec["supply_merchants"])))]
            rows.append(dict(date=d, amount=round(float(rng.uniform(60, 1400)), 2), label="shipping_supplies", cp=key))
    card = pd.DataFrame(rows)
    card["amount"] = card["amount"].round(2)
    # statements close on the 28th, autopay on the 22nd of the following month
    pays = []
    for (y, m) in [(2026, 6), (2026, 7), (2026, 8), (2026, 9)]:
        close = date(y, m, 28)
        prev_close = date(y, m - 1, 28) if m > 6 else SIM_START - timedelta(days=1)
        mask = (card["date"] > prev_close) & (card["date"] <= close)
        bal = round(float(card.loc[mask, "amount"].sum()), 2)
        pdate = date(y, m + 1, 22)
        pays.append(dict(date=pdate, amount=-bal, label="card_payment_received", cp="payment",
                         statement_close=close))
    card = pd.concat([card, pd.DataFrame(pays)], ignore_index=True)
    card = card.sort_values(["date", "amount"], kind="stable").reset_index(drop=True)
    return card, pd.DataFrame(pays)


# --------------------------------------------------------------------------- bank
def sim_bank(spec, rng, sim: BrandSim, card_pays: pd.DataFrame):
    rev = spec["annual_rev"]
    sched = []   # (date, amount, label, cp, detail)

    def add(d, amt, label, cp, detail=None):
        sched.append(dict(date=d, amount=round(float(amt), 2), label=label, cp=cp, detail=detail or {}))

    for r in sim.payouts.itertuples():
        add(r.payout_date, r.net, "processor_payout", "shopify", {"payout_id": r.payout_id})
    if sim.amazon_settlements is not None:
        for r in sim.amazon_settlements.itertuples():
            add(r.deposit_date, r.total, "marketplace_payout", "amazon", {"settlement_id": r.settlement_id})
    if sim.faire_orders is not None:
        for pdate, g in sim.faire_orders.groupby("payout_date"):
            add(pdate, round(g["payout_amount"].sum(), 2), "wholesale_payout", "faire")
    # direct wholesale receipts
    for name in spec.get("direct_retailers", []):
        for d in daterange(date(2026, 7, 1), WIN_END):
            if rng.random() < 0.045 and is_bday(d):
                add(d, round(float(rng.uniform(1200, 9500)), 2), "wholesale_receipt", name)
    # payroll
    d = date(2026, 7, 3)
    per_run = rev * spec.get("payroll_rate", 0.15) / 26.0
    while d <= WIN_END:
        amt = per_run * float(rng.uniform(0.97, 1.03))
        add(d, -0.76 * amt, "payroll", spec["payroll_provider"], {"part": "net"})
        add(d, -0.24 * amt, "payroll", spec["payroll_provider"], {"part": "tax"})
        d += timedelta(days=14)
    # inventory purchase orders: deposits and balances, with wire fees
    inv_annual = rev * 0.30
    pos = spec.get("po_plan", [(date(2026, 7, 8), date(2026, 8, 12), 0.22),
                               (date(2026, 8, 5), date(2026, 9, 22), 0.42),
                               (date(2026, 10, 6), None, 0.25)])
    for i, (dep_d, bal_d, frac) in enumerate(pos):
        po_amt = inv_annual * frac
        sup = spec["suppliers"][i % len(spec["suppliers"])]
        add(next_bday(dep_d), -0.30 * po_amt, "inventory_purchase", sup, {"po": i})
        add(next_bday(dep_d), -float(spec.get("wire_fee", 35)), "bank_fee", "wire_fee")
        if bal_d:
            add(next_bday(bal_d), -0.70 * po_amt, "inventory_purchase", sup, {"po": i})
            add(next_bday(bal_d), -float(spec.get("wire_fee", 35)), "bank_fee", "wire_fee")
            arr = next_bday(bal_d + timedelta(days=24))
            if arr <= WIN_END:
                add(arr, -0.09 * po_amt, "freight_duty", spec["forwarder"])
                add(next_bday(arr + timedelta(days=3)), -0.05 * po_amt, "freight_duty", "customs")
    # monthly items
    for m in (7, 8, 9, 10):
        add(next_bday(date(2026, m, 1)), -rev * 0.014 / 12, "rent", spec["landlord"])
        add(next_bday(date(2026, m, 10)), -rev * 0.075 / 12 * float(rng.uniform(0.9, 1.1)),
            "fulfillment_3pl", spec["threepl"])
        add(next_bday(date(2026, m, 15)), -float(spec.get("qb_fee", 275)), "software_opex", "intuit")
        # sales tax on prior month's Shopify tax collected
        pm = m - 1
        tax = sim.orders.loc[[x.month == pm for x in sim.orders["day"]], "tax"].sum()
        if tax > 0:
            add(next_bday(date(2026, m, 20)), -tax, "sales_tax", spec["tax_agency"])
    # card autopay from the card statements
    for r in card_pays.itertuples():
        add(r.date, r.amount, "card_payment", spec["card_issuer"])   # amount already negative
    # meta direct debit
    if spec.get("meta_direct_debit"):
        thr = 3500.0
        accm = 0.0
        daily = rev * spec.get("ad_rate", 0.17) * 0.6 / 365.0
        for d in daterange(WIN_START, WIN_END):
            accm += daily * float(rng.uniform(0.85, 1.15))
            while accm >= thr:
                add(d, -thr, "ad_spend", "meta")
                accm -= thr
    # vendor refunds
    for k in range(spec.get("vendor_refunds", 2)):
        d = date(2026, 7, 14) + timedelta(days=int(rng.integers(0, 90)))
        add(next_bday(d), float(rng.uniform(180, 2400)), "vendor_refund",
            [spec["threepl"], spec["suppliers"][0]][k % 2])
    # financing: line of credit draw and repayment
    if spec.get("lender"):
        draw = rev * 0.04
        add(date(2026, 9, 15), draw, "financing_draw", spec["lender"])
        for d in [date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)]:
            add(d, -draw / 6.0, "financing_repayment", spec["lender"])
        add(date(2026, 10, 1), -draw * 0.11 / 12 * 0.5, "interest_expense", spec["lender"])

    # walk the days, adding own-account sweeps so the operating balance stays sane
    sched = sorted(sched, key=lambda x: (x["date"], -x["amount"]))
    opening = rev * 0.08
    sav_open = rev * 0.05
    op, sav = opening, sav_open
    out = []
    by_day = {}
    for s in sched:
        by_day.setdefault(s["date"], []).append(s)
    for d in daterange(SIM_START, WIN_END):
        todays = by_day.get(d, [])
        need = -sum(x["amount"] for x in todays if x["amount"] < 0)
        if is_bday(d):
            if op - need < rev * 0.03 and sav > 1000:
                amt = round(min(sav - 500, need + rev * 0.04 - op), -3)
                if amt > 0:
                    out.append(dict(date=d, account="operating", amount=amt, label="own_account_transfer",
                                    cp="savings", detail={"dir": "from"}))
                    out.append(dict(date=d, account="savings", amount=-amt, label="own_account_transfer",
                                    cp="operating", detail={"dir": "to"}))
                    op += amt
                    sav -= amt
            elif d.weekday() == 0 and op > rev * 0.10:
                amt = round((op - rev * 0.07) * 0.8, -3)
                if amt > 0:
                    out.append(dict(date=d, account="operating", amount=-amt, label="own_account_transfer",
                                    cp="savings", detail={"dir": "to"}))
                    out.append(dict(date=d, account="savings", amount=amt, label="own_account_transfer",
                                    cp="operating", detail={"dir": "from"}))
                    op -= amt
                    sav += amt
        for x in todays:
            out.append(dict(date=d, account="operating", **{k: x[k] for k in ("amount", "label", "cp", "detail")}))
            op += x["amount"]
        if d.day == 28:
            ii = round(sav * 0.0258 / 12, 2)
            out.append(dict(date=d, account="savings", amount=ii, label="interest_income", cp="bank", detail={}))
            sav += ii
    bank = pd.DataFrame(out)
    bank["amount"] = bank["amount"].round(2)
    bank = bank[bank["amount"] != 0].reset_index(drop=True)
    sim.extra["opening_operating"] = round(opening, 2)
    sim.extra["opening_savings"] = round(sav_open, 2)
    return bank


# --------------------------------------------------------------------------- chart of accounts
COA_CATEGORIES = [
    "bank_account", "credit_card_account", "loan_account", "sales_tax_payable",
    "revenue_dtc", "revenue_marketplace", "revenue_wholesale", "refunds_returns",
    "cogs_product", "cogs_freight_duty", "fulfillment_3pl", "merchant_fees",
    "advertising", "payroll", "software", "rent", "travel_meals",
    "shipping_supplies", "interest_expense", "other_opex",
]


def sim_coa(spec, rng, pools):
    """pools: category -> (list of names, account type). Picks names per brand."""
    rows = []
    numbering = spec.get("coa_numbering", "plain")
    base = {"bank_account": 1000, "credit_card_account": 2000, "loan_account": 2600,
            "sales_tax_payable": 2200, "revenue_dtc": 4000, "revenue_marketplace": 4100,
            "revenue_wholesale": 4200, "refunds_returns": 4900, "cogs_product": 5000,
            "cogs_freight_duty": 5100, "fulfillment_3pl": 5200, "merchant_fees": 5300,
            "advertising": 6000, "payroll": 6100, "software": 6200, "rent": 6300,
            "travel_meals": 6400, "shipping_supplies": 6500, "interest_expense": 7000,
            "other_opex": 6900}
    for cat in COA_CATEGORIES:
        if cat == "revenue_marketplace" and spec["shares"].get("amazon", 0) <= 0:
            continue
        if cat == "loan_account" and not spec.get("lender"):
            continue
        names, atype = pools[cat]
        k = 2 if cat in ("advertising", "payroll", "software", "other_opex", "bank_account") else 1
        picks = rng.choice(len(names), size=min(k, len(names)), replace=False)
        for j, p in enumerate(picks):
            num = base[cat] + j * 10
            rows.append(dict(number=num, name=names[p], type=atype, label=cat))
    df = pd.DataFrame(rows)
    df = df.sample(frac=1.0, random_state=int(rng.integers(0, 1_000_000))).sort_values("number")
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------- run
def simulate(spec: dict, coa_pools: dict) -> BrandSim:
    rng = np.random.default_rng(spec["seed"])
    sim = BrandSim(spec=spec)
    sim.orders, sim.order_items, sim.refunds, sim.payouts = sim_shopify(spec, rng)
    sim.amazon_rows, sim.amazon_settlements = sim_amazon(spec, rng)
    sim.faire_orders = sim_faire(spec, rng)
    sim.card, card_pays = sim_card(spec, rng)
    sim.bank = sim_bank(spec, rng, sim, card_pays)
    sim.coa = sim_coa(spec, rng, coa_pools)
    sim.extra["card_statements"] = card_pays
    return sim


RECEIPT_LABELS = {"processor_payout": "dtc", "marketplace_payout": "marketplace",
                  "wholesale_payout": "wholesale", "wholesale_receipt": "wholesale"}
