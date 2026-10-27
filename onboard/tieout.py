"""
Tie-outs: the gate that decides whether a brand's mapped data is accepted.

A mapping is not "done" when the columns line up. It is done when independent
records of the same money agree:
  Shopify payouts          ->  bank deposits
  Shopify orders           ->  Shopify payout charges (finds the brand's payout lag)
  Amazon settlements       ->  bank deposits
  Faire payouts            ->  bank deposits
  card payment rows        ->  bank card payments
  card statement balance   ->  sum of card charges (finds the statement close day)
  bank running balance     ->  bank amounts (also proves the sign convention)
Every match is also evidence: a deposit that equals a payout to the cent, within
a few days, is labeled by proof rather than by a model.

Built by Avinash Rayudu.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

MATCH_RATE_PASS = 0.98
ORDERS_DIFF_PASS = 0.005


@dataclass
class Check:
    name: str
    status: str             # pass | fail | n/a
    value: object = None
    threshold: object = None
    detail: str = ""
    unmatched: list = field(default_factory=list)

    def as_dict(self):
        return {"name": self.name, "status": self.status, "value": self.value, "threshold": self.threshold,
                "detail": self.detail, "unmatched": self.unmatched[:25]}


def bdays_after(d: date, n: int) -> date:
    out, k = d, 0
    while k < n:
        out += timedelta(days=1)
        if out.weekday() < 5:
            k += 1
    return out


def match_records(expected: pd.DataFrame, lines: pd.DataFrame, tol_days: int, sign: int = 1, taken=None):
    """
    Greedy one-to-one match of expected (date, amount) records to ledger lines whose amount
    equals sign * expected amount to the cent, within tol_days. Returns {exp_idx: line_idx}.
    """
    taken = set() if taken is None else set(taken)
    by_amt = {}
    for idx, d, a in zip(lines.index, lines["date"], lines["amount"]):
        by_amt.setdefault(round(a * 100), []).append((idx, d))
    out = {}
    for ei, d, a in sorted(zip(expected.index, expected["date"], expected["amount"]), key=lambda x: x[1]):
        cands = by_amt.get(round(sign * a * 100), [])
        best = None
        for li, ld in cands:
            if li in taken:
                continue
            gap = abs((ld - d).days)
            if gap <= tol_days and (best is None or gap < best[1]):
                best = (li, gap)
        if best:
            out[ei] = best[0]
            taken.add(best[0])
    return out


def source_to_bank(name, src: pd.DataFrame, bank: pd.DataFrame, tol_days: int, taken):
    """src: date, amount (positive = money into the bank)."""
    exp = src[src["amount"] > 0]
    if exp.empty:
        return Check(name, "n/a", detail="no records"), {}
    m = match_records(exp, bank[bank["account"] != "savings"], tol_days, 1, taken)
    rate = len(m) / len(exp)
    unmatched = [f"{r.date} {r.amount:,.2f}" for r in exp.itertuples() if r.Index not in m]
    st = "pass" if rate >= MATCH_RATE_PASS else "fail"
    return Check(name, st, round(rate, 4), MATCH_RATE_PASS, f"{len(m)}/{len(exp)} records found in the bank "
                 f"within {tol_days} days", unmatched), m


def orders_to_payouts(orders: pd.DataFrame, payouts: pd.DataFrame):
    """Compares order charges to payout charges, trying 1-3 business-day lags; keeps the best lag."""
    if orders.empty or payouts.empty:
        return Check("orders_to_payouts", "n/a", detail="no orders or payouts")
    daily = orders.groupby("date")["charges"].sum()
    lo, hi = min(daily.index), max(daily.index)
    best = None
    for lag in (1, 2, 3):
        contrib = {}
        d = lo - timedelta(days=10)
        while d <= hi + timedelta(days=10):
            contrib.setdefault(bdays_after(d, lag), []).append(d)
            d += timedelta(days=1)
        ok_dates = {p for p, ds in contrib.items() if all(lo <= x <= hi for x in ds)}
        exp = {}
        for d0, v in daily.items():
            p = bdays_after(d0, lag)
            if p in ok_dates:
                exp[p] = exp.get(p, 0.0) + v
        pay = payouts[payouts["date"].isin(ok_dates)].groupby("date")["charges"].sum()
        common = sorted(set(exp) & set(pay.index))
        if len(common) < 5:
            continue
        e = sum(exp[p] for p in common)
        a = float(sum(abs(pay[p]) for p in common))
        diff = abs(e - a) / a if a else 1.0
        if best is None or diff < best[0]:
            best = (diff, lag, len(common), e, a)
    if best is None:
        return Check("orders_to_payouts", "n/a", detail="not enough overlapping payout days")
    diff, lag, n, e, a = best
    st = "pass" if diff <= ORDERS_DIFF_PASS else "fail"
    return Check("orders_to_payouts", st, round(diff, 5), ORDERS_DIFF_PASS,
                 f"orders {e:,.2f} vs payout charges {a:,.2f} over {n} payout days; payout lag {lag} business days")


def card_payments_to_bank(card: pd.DataFrame, bank: pd.DataFrame, taken):
    pays = card[(card["charge"] < 0)].copy()
    if pays.empty:
        return Check("card_payments_to_bank", "n/a", detail="no payment rows"), {}
    exp = pd.DataFrame({"date": pays["date"], "amount": -pays["charge"]}, index=pays.index)
    out_lines = bank[(bank["amount"] < 0) & (bank["account"] != "savings")]
    m = match_records(exp, out_lines, 4, -1, taken)
    rate = len(m) / len(exp)
    unmatched = [f"{r.date} {r.amount:,.2f}" for r in exp.itertuples() if r.Index not in m]
    st = "pass" if rate >= MATCH_RATE_PASS else "fail"
    return Check("card_payments_to_bank", st, round(rate, 4), MATCH_RATE_PASS,
                 f"{len(m)}/{len(exp)} card payments found as bank debits", unmatched), m


def card_statement_balance(card: pd.DataFrame):
    """Finds the statement close day for which every fully covered payment equals that statement's charges."""
    pays = card[card["charge"] < 0]
    charges = card[card["charge"] > 0]
    if pays.empty or charges.empty:
        return Check("card_statement_balance", "n/a", detail="no payments or charges")
    first = card["date"].min()
    best = None
    for close_day in range(1, 29):
        ok = tot = 0
        for p in pays.itertuples():
            # the statement being paid closed in the month before the payment, on close_day
            y, mth = (p.date.year, p.date.month - 1) if p.date.month > 1 else (p.date.year - 1, 12)
            close = date(y, mth, close_day)
            if (p.date - close).days < 10:
                continue
            py, pm = (y, mth - 1) if mth > 1 else (y - 1, 12)
            prev = date(py, pm, close_day)
            if prev < first - timedelta(days=1):
                continue
            tot += 1
            s = charges[(charges["date"] > prev) & (charges["date"] <= close)]["charge"].sum()
            if abs(s + p.charge) < 1.0:
                ok += 1
        if tot and (best is None or ok / tot > best[0] or (ok / tot == best[0] and tot > best[2])):
            best = (ok / tot, close_day, tot, ok)
    if best is None:
        return Check("card_statement_balance", "n/a", detail="no statement fully inside the file")
    rate, day, tot, ok = best
    st = "pass" if rate == 1.0 else "fail"
    return Check("card_statement_balance", st, round(rate, 4), 1.0,
                 f"{ok}/{tot} statements equal the sum of their charges; statements close on day {day}")


def own_transfer_pairs(bank: pd.DataFrame):
    """Pairs operating and savings lines on the same day with opposite amounts (evidence only)."""
    sav = bank[bank["account"] == "savings"]
    op = bank[bank["account"] != "savings"]
    if sav.empty:
        return {}
    exp = pd.DataFrame({"date": sav["date"], "amount": sav["amount"]}, index=sav.index)
    return match_records(exp, op, 1, -1)


def unpaired_transfers(bank: pd.DataFrame):
    """After labeling: any line called an own-account transfer must have its other half in the export."""
    if not (bank["account"] == "savings").any():
        return Check("own_account_transfers", "n/a", detail="only one account in the export")
    t = bank[(bank["label"] == "own_account_transfer")]
    paired = int((t["method"] == "tie-out").sum())
    loose = t[t["method"] != "tie-out"]
    st = "pass" if loose.empty else "fail"
    return Check("own_account_transfers", st, int(len(loose)), 0,
                 f"{paired} transfer lines paired across accounts; {len(loose)} transfer lines without a pair",
                 [f"{r.date} {r.amount:,.2f} {r.account}" for r in loose.itertuples()])


def balance_continuity(info: dict):
    v = info.get("balance_consistency")
    if v is None:
        return Check("bank_balance_continuity", "n/a", detail="no running balance column")
    st = "pass" if v >= 0.99 else "fail"
    return Check("bank_balance_continuity", st, v, 0.99,
                 f"running balance agrees with amounts on {v:.1%} of rows; sign from {info.get('sign_source')}, "
                 f"rows {info.get('row_order')}")


def deposits_without_source(bank: pd.DataFrame, sources_present: set):
    """Payout deposits the model labeled but no export accounts for: usually a missing file."""
    lab_to_src = {"processor_payout": "payouts", "marketplace_payout": "amazon", "wholesale_payout": "faire"}
    rows = bank[(bank["label"].isin(lab_to_src)) & (bank["method"] != "tie-out") & (~bank["is_duplicate"])]
    confirmed = rows[rows["confirmed_no_export"].fillna(False).astype(bool)] if "confirmed_no_export" in rows \
        else rows.iloc[0:0]
    flagged = rows.drop(confirmed.index)
    if flagged.empty:
        extra = (f"; {len(confirmed)} deposits ({confirmed['amount'].sum():,.2f}) confirmed by a reviewer "
                 f"without an export") if len(confirmed) else ""
        return Check("deposits_without_source", "pass", 0, 0, "every payout deposit is backed by an export" + extra)
    by = flagged.groupby("label")["amount"].agg(["count", "sum"])
    det = "; ".join(f"{k}: {int(r['count'])} deposits, {r['sum']:,.2f}" for k, r in by.iterrows())
    missing = sorted({lab_to_src[l] for l in flagged["label"].unique() if lab_to_src[l] not in sources_present})
    hint = f" (no {', '.join(missing)} export uploaded)" if missing else " (exports present but records missing)"
    return Check("deposits_without_source", "fail", int(len(flagged)), 0, det + hint,
                 [f"{r.date} {r.amount:,.2f} {r.label}" for r in flagged.itertuples()])


def bank_present(bank: pd.DataFrame, n_files: int):
    if n_files == 0:
        return Check("bank_rows_present", "n/a", detail="no files")
    if bank.empty:
        return Check("bank_rows_present", "fail", 0, ">0", "no readable bank statement rows: nothing to tie the "
                     "other exports to, so nothing can be accepted")
    return Check("bank_rows_present", "pass", int(len(bank)), ">0", f"{len(bank)} bank rows read")


def rows_read(file_log: list):
    """A mapping that silently drops rows is wrong even when what is left looks fine."""
    bad, checked = [], 0
    for e in file_log:
        info = e.get("info") or {}
        n, dropped = info.get("rows_in_file"), info.get("dropped_rows")
        if n is None or dropped is None or n == 0:
            continue
        checked += 1
        if dropped > max(2, 0.05 * n):
            bad.append(f"{e['file']}: {dropped} of {n} rows unreadable")
    if not checked:
        return Check("rows_read", "n/a", detail="no row-level files")
    return Check("rows_read", "fail" if bad else "pass", len(bad), 0,
                 "; ".join(bad) if bad else f"{checked} files read with at most a footer row skipped", bad)
