"""
Turns a mapped file into a standard table.

Each transform keeps the original row number so any number in the output can be
traced to a line in the brand's file. Rows whose date does not parse (summary
footers, blank separators) are dropped and counted, not silently lost.

Built by Avinash Rayudu.
"""
from __future__ import annotations

import re

import pandas as pd

from parse import clean, looks_decimal_comma, parse_date_column, parse_money

PAYMENT_RE = re.compile(r"\b(PAYMENT|THANK YOU|AUTOPAY|AUTOMATIC PAYMENT|PAYMNT)\b", re.I)


def _col(table, header):
    return table.column(table.header.index(header))


def _money_col(table, header):
    vals = _col(table, header)
    dc = looks_decimal_comma([v for v in vals if clean(v)][:400])
    return [parse_money(v, dc) for v in vals], dc


def _dates(table, header, prefer_day_first=None):
    return parse_date_column(_col(table, header), prefer_day_first)


# --------------------------------------------------------------------------- bank
def bank_table(table, mapping, kickoff, faults=None):
    faults = faults or {}
    f = mapping.fields
    dates, dinfo = _dates(table, f["date"])
    if faults.get("swap_day_month") and dinfo["order"] == "mdy":
        dates, dinfo = parse_date_column(_col(table, f["date"]), prefer_day_first=True)
        dates = [None if d is None else (d.replace(month=d.day, day=d.month) if d.day <= 12 else None)
                 for d in dates]
    desc = _col(table, f["description"])
    if "amount" in f:
        amt, dc = _money_col(table, f["amount"])
    else:
        deb, _ = _money_col(table, f["debit"])
        cre, _ = _money_col(table, f["credit"])
        amt = [None if (d is None and c is None) else round(abs(c or 0) - abs(d or 0), 2) for d, c in zip(deb, cre)]
    direction_used = False
    if "direction" in f:     # unsigned amounts with the direction in its own column (DR/CR, DEBIT/CREDIT)
        dirs = [clean(v).upper() for v in _col(table, f["direction"])]
        vocab = {"DR": -1, "DEBIT": -1, "D": -1, "DBIT": -1, "CR": 1, "CREDIT": 1, "C": 1, "CRDT": 1}
        known = [d for d in dirs if d]
        if known and sum(1 for d in known if d in vocab) / len(known) >= 0.9:
            amt = [None if a is None else (abs(a) * vocab.get(d, 1)) for a, d in zip(amt, dirs)]
            direction_used = True
    bal = _money_col(table, f["balance"])[0] if "balance" in f else [None] * len(amt)
    acct_raw = _col(table, f["account"]) if "account" in f else ["" for _ in amt]
    acct = _resolve_accounts(acct_raw, kickoff)
    rows = []
    for i, (d, s, a, b, ac) in enumerate(zip(dates, desc, amt, bal, acct)):
        if d is None or a is None:
            continue
        rows.append(dict(row=i, date=d, description=s, amount=a, balance=b, account=ac))
    df = pd.DataFrame(rows, columns=["row", "date", "description", "amount", "balance", "account"])
    info = {"dropped_rows": len(table.rows) - len(df), "date_order": dinfo["order"],
            "date_ambiguous": dinfo["ambiguous"], "sign_source": "convention", "balance_consistency": None,
            "row_order": None, "rows_in_file": len(table.rows), "direction_column_used": direction_used}
    if "balance" in f and df["balance"].notna().mean() > 0.9:
        best = None
        for order in ("asc", "desc"):
            for sign in (1, -1):
                ok = tot = 0
                for _, g in df.groupby("account", sort=False):
                    g = g if order == "asc" else g.iloc[::-1]
                    b = g["balance"].tolist()
                    a = g["amount"].tolist()
                    for k in range(1, len(g)):
                        tot += 1
                        if abs((b[k] - b[k - 1]) - sign * a[k]) < 0.015:
                            ok += 1
                rate = ok / max(1, tot)
                if best is None or rate > best[0]:
                    best = (rate, order, sign)
        rate, order, sign = best
        info["balance_consistency"] = round(rate, 4)
        info["row_order"] = "oldest_first" if order == "asc" else "newest_first"
        if rate > 0.9:
            info["sign_source"] = "balance"
            if sign == -1:
                df["amount"] = -df["amount"]
    if faults.get("flip_bank_sign"):
        df["amount"] = -df["amount"]
        info["sign_source"] = "convention"
        info["balance_consistency"] = None
    return df, info


def _resolve_accounts(raw, kickoff):
    own = (kickoff or {}).get("own_accounts", {})
    sav4, op4 = str(own.get("savings_last4", "")), str(own.get("operating_last4", ""))
    out = []
    counts = pd.Series([clean(v) for v in raw]).value_counts()
    top = counts.index[0] if len(counts) else ""
    for v in raw:
        v = clean(v)
        if not v:
            out.append("operating")
        elif sav4 and v.endswith(sav4) or re.search(r"sav|saving|share 0?1|reserve", v, re.I):
            out.append("savings")
        elif op4 and v.endswith(op4) or v == top or re.search(r"oper|check|chk", v, re.I):
            out.append("operating")
        else:
            out.append("other")
    return out


# --------------------------------------------------------------------------- card
def card_table(table, mapping, faults=None):
    f = mapping.fields
    dates, dinfo = _dates(table, f["date"])
    desc = _col(table, f["description"])
    amt, _ = _money_col(table, f["amount"])
    typ = _col(table, f["txn_type"]) if "txn_type" in f else [""] * len(amt)
    rows = []
    for i, (d, s, a, t) in enumerate(zip(dates, desc, amt, typ)):
        if d is None or a is None:
            continue
        pay = bool(PAYMENT_RE.search(s)) or "payment" in clean(t).lower()
        rows.append(dict(row=i, date=d, description=s, raw_amount=a, looks_like_payment=pay))
    df = pd.DataFrame(rows, columns=["row", "date", "description", "raw_amount", "looks_like_payment"])
    non_pay = df.loc[~df["looks_like_payment"], "raw_amount"]
    charge_sign = 1 if (non_pay > 0).mean() >= 0.5 else -1
    df["charge"] = df["raw_amount"] * charge_sign      # > 0 means money spent on the card
    info = {"dropped_rows": len(table.rows) - len(df), "rows_in_file": len(table.rows),
            "charge_sign": "positive" if charge_sign == 1 else "negative",
            "date_order": dinfo["order"], "date_ambiguous": dinfo["ambiguous"]}
    return df, info


# --------------------------------------------------------------------------- shopify orders
def orders_table(table, mapping, faults=None):
    faults = faults or {}
    f = mapping.fields
    ids = _col(table, f["order_id"])
    dates, _ = _dates(table, f["created_at"])
    total_h = f["subtotal"] if faults.get("subtotal_as_total") and "subtotal" in f else f["total"]
    tot, _ = _money_col(table, total_h)
    per = {}
    for oid, d, t in zip(ids, dates, tot):
        if not oid or d is None:
            continue
        o = per.setdefault(oid, {"order_id": oid, "date": d, "total": None, "lines": 0})
        o["lines"] += 1
        if t is not None:
            if faults.get("sum_order_rows"):
                o["total"] = (o["total"] or 0) + t
            elif o["total"] is None:
                o["total"] = t          # first non-blank total; later line rows repeat it or leave it blank
    df = pd.DataFrame(list(per.values()), columns=["order_id", "date", "total", "lines"])
    df = df[df["total"].notna()]
    repeated = 0
    if len(df):
        nonblank = sum(1 for oid, t in zip(ids, tot) if oid and t is not None)
        repeated = nonblank - len(df)
    info = {"orders": len(df), "line_rows": len(ids), "repeated_totals_skipped": int(repeated)}
    return df.rename(columns={"total": "charges"})[["date", "charges"]], info


def sales_daily_table(table, mapping, faults=None):
    f = mapping.fields
    dates, _ = _dates(table, f["day"])
    get = lambda k: _money_col(table, f[k])[0] if k in f else [0.0] * len(dates)
    gross, disc, ship, tax = get("gross_sales"), get("discounts"), get("shipping"), get("taxes")
    rows = []
    for d, g, di, s, t in zip(dates, gross, disc, ship, tax):
        if d is None or g is None:
            continue
        rows.append(dict(date=d, charges=round(g - abs(di or 0) + (s or 0) + (t or 0), 2)))
    df = pd.DataFrame(rows, columns=["date", "charges"])
    return df, {"days": len(df)}


# --------------------------------------------------------------------------- payouts
def payouts_table(table, mapping, faults=None):
    f = mapping.fields
    dates, _ = _dates(table, f["payout_date"])
    net, _ = _money_col(table, f["net"])
    ch, _ = _money_col(table, f["charges"])
    pid = _col(table, f["payout_id"]) if "payout_id" in f else [""] * len(net)
    rows = [dict(row=i, date=d, net=n, charges=c, payout_id=p) for i, (d, n, c, p) in
            enumerate(zip(dates, net, ch, pid)) if d is not None and n is not None]
    df = pd.DataFrame(rows, columns=["row", "date", "net", "charges", "payout_id"])
    grain = "payout"
    if len(df) and df["date"].nunique() < 0.6 * len(df):
        # one row per transaction: roll up to one row per payout (payout ID if present, else payout date)
        key = "payout_id" if (df["payout_id"].astype(str).str.len() > 0).all() else "date"
        df = df.groupby(key, as_index=False).agg(
            row=("row", "min"), date=("date", "first"), net=("net", "sum"),
            charges=("charges", lambda x: x[x > 0].sum()), payout_id=("payout_id", "first"))
        df["net"] = df["net"].round(2)
        df["charges"] = df["charges"].round(2)
        grain = f"transaction rows rolled up by {key}"
    return df[["row", "date", "net", "charges", "payout_id"]], {"payouts": len(df), "grain": grain,
                                                                 "rows_in_file": len(table.rows),
                                                                 "dropped_rows": len(table.rows) - len(rows)}


# --------------------------------------------------------------------------- amazon
def amazon_flat_table(table, mapping, faults=None):
    f = mapping.fields
    sid = _col(table, f["settlement_id"])
    dep, _ = _dates(table, f["deposit_date"])
    tot, _ = _money_col(table, f["total_amount"])
    amt, _ = _money_col(table, f["amount"])
    sett, detail = {}, {}
    for s, d, t, a in zip(sid, dep, tot, amt):
        if not s:
            continue
        if t is not None and d is not None:
            sett[s] = dict(settlement_id=s, date=d, amount=t)
        elif a is not None:
            detail[s] = detail.get(s, 0.0) + a
    df = pd.DataFrame(list(sett.values()), columns=["settlement_id", "date", "amount"])
    internal = {s: (round(detail.get(s, 0.0), 2), v["amount"]) for s, v in sett.items()}
    ok = sum(1 for a, b in internal.values() if abs(a - b) < 0.02)
    return df, {"settlements": len(df), "detail_ties_to_total": f"{ok}/{len(internal)}"}


def amazon_range_table(table, mapping, faults=None):
    f = mapping.fields
    dates, _ = _dates(table, f["date_time"])
    typ = _col(table, f["type"])
    tot, _ = _money_col(table, f["total"])
    sid = _col(table, f["settlement_id"])
    rows = [dict(settlement_id=s, date=d, amount=round(-t, 2)) for d, ty, t, s in zip(dates, typ, tot, sid)
            if d is not None and t is not None and clean(ty).lower() == "transfer"]
    df = pd.DataFrame(rows, columns=["settlement_id", "date", "amount"])
    return df, {"transfers": len(df), "rows": len(typ)}


# --------------------------------------------------------------------------- faire
def faire_table(table, mapping, faults=None):
    f = mapping.fields
    dates, _ = _dates(table, f["payout_date"])
    pay, _ = _money_col(table, f["payout_amount"])
    whole = _money_col(table, f["wholesale_total"])[0] if "wholesale_total" in f else None
    comm = _money_col(table, f["commission"])[0] if "commission" in f else None
    rows = [dict(date=d, amount=p) for d, p in zip(dates, pay) if d is not None and p is not None]
    df = pd.DataFrame(rows, columns=["date", "amount"]).groupby("date", as_index=False)["amount"].sum()
    df["amount"] = df["amount"].round(2)
    internal = None
    if whole and comm:
        pairs = [(w, c, p) for w, c, p in zip(whole, comm, pay) if None not in (w, c, p)]
        internal = f"{sum(1 for w, c, p in pairs if abs(abs(w) - abs(c) - abs(p)) < 0.02)}/{len(pairs)}"
    return df, {"payout_days": len(df), "order_rows": len(rows), "net_equals_gross_minus_fee": internal}


# --------------------------------------------------------------------------- chart of accounts
def coa_table(table, mapping, faults=None):
    f = mapping.fields
    names = _col(table, f["name"])
    types = _col(table, f["type"])
    nums = _col(table, f["number"]) if "number" in f else [""] * len(names)
    rows = [dict(row=i, number=n, name=a, type=t) for i, (n, a, t) in enumerate(zip(nums, names, types)) if clean(a)]
    return pd.DataFrame(rows, columns=["row", "number", "name", "type"]), {"accounts": len(rows)}


TRANSFORMS = {"bank": bank_table, "card": card_table, "orders_list": orders_table, "sales_daily": sales_daily_table,
              "payouts": payouts_table, "amazon_flat": amazon_flat_table, "amazon_range": amazon_range_table,
              "faire": faire_table, "coa": coa_table}
