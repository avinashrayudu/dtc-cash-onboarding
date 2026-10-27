"""
Renders a simulated brand into the files a brand would actually hand over.

Each renderer returns a list of RenderedFile objects. A RenderedFile carries the
file body plus its truth: which source type it is, which header holds which
standard field, and (for bank, card and chart-of-accounts files) the true
meaning of every data row. Truth is written to evals/ground_truth and the
onboarding pipeline never reads it.

Built by Avinash Rayudu. All data is synthetic.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from sim import (UPLOAD_1, UPLOAD_2, BANK_OVERLAP_DAYS, CARD_UPLOAD_1_START, WIN_END, BrandSim)


@dataclass
class RenderedFile:
    name: str
    kind: str                 # "csv" | "tsv" | "xlsx" | "text"
    source_type: str
    column_map: dict          # standard field -> header text
    header: list = None
    rows: list = None         # list of lists (data body only)
    preamble: list = None     # raw lines before the header
    footer: list = None       # raw rows after the data body
    row_truth: list = None    # per data row dict
    meta: dict = field(default_factory=dict)
    delimiter: str = ","


# --------------------------------------------------------------------------- helpers
def fmt_date(d, style):
    if isinstance(d, pd.Timestamp):
        d = d.date()
    if style == "mdy":
        return d.strftime("%m/%d/%Y")
    if style == "mdy_nopad":
        return f"{d.month}/{d.day}/{d.year}"
    if style == "dmy":
        return d.strftime("%d/%m/%Y")
    if style == "iso":
        return d.isoformat()
    if style == "mon_d_y":
        return d.strftime("%b %-d, %Y")
    raise ValueError(style)


def money(x, style="plain"):
    if style == "plain":
        return f"{x:.2f}"
    if style == "comma":
        return f"{x:,.2f}"
    if style == "dollar":
        return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"
    if style == "paren":
        return f"({abs(x):,.2f})" if x < 0 else f"{x:,.2f}"
    raise ValueError(style)


def rnd_digits(rng, n):
    return "".join(str(int(v)) for v in rng.integers(0, 10, n))


def rnd_alnum(rng, n):
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(chars[int(v)] for v in rng.integers(0, len(chars), n))


def in_window(d, w):
    if isinstance(d, pd.Timestamp):
        d = d.date()
    return w[0] <= d <= w[1]


CP_DISPLAY = {
    "shopify": "Shopify", "amazon": "Amazon.com Services", "faire": "Faire Wholesale",
    "customs": "US Customs CBP", "intuit": "Intuit", "savings": "Savings", "operating": "Operating",
    "wire_fee": "Wire fee", "bank": "Bank", "meta": "Facebook Ads",
}


def disp(cp):
    return CP_DISPLAY.get(cp, cp)


# --------------------------------------------------------------------------- bank memo styles
def bank_memo(style, line, spec, rng):
    lab, cp, amt = line["label"], line["cp"], line["amount"]
    d = line["date"]
    yymmdd = d.strftime("%y%m%d")
    BR = spec["name"].upper()
    CP = disp(cp).upper()
    sav4 = spec["savings_last4"]
    op4 = spec["operating_last4"]
    part = line["detail"].get("part") if isinstance(line["detail"], dict) else None
    direction = line["detail"].get("dir") if isinstance(line["detail"], dict) else None
    acct = line.get("account", "operating")

    if style == "A":
        ach = lambda co, descr: (f"ORIG CO NAME:{co} ORIG ID:{rnd_digits(rng, 10)} DESC DATE:{yymmdd} "
                                 f"CO ENTRY DESCR:{descr} SEC:CCD TRACE#:{rnd_digits(rng, 15)} "
                                 f"EED:{yymmdd} IND ID:{rnd_alnum(rng, 8)} IND NAME:{BR}")
        if lab == "processor_payout":
            return ach("SHOPIFY", "TRANSFER")
        if lab == "marketplace_payout":
            return ach("AMAZON.COM SVCS", "PAYMENTS")
        if lab == "wholesale_payout":
            return ach("FAIRE WHOLESALE", "PAYOUT")
        if lab == "wholesale_receipt":
            return ach(CP, "PAYABLES")
        if lab == "payroll":
            return ach(CP, "NET PAY" if part == "net" else "TAX PAYMT")
        if lab == "inventory_purchase":
            return (f"FEDWIRE DEBIT VIA: CITIBANK NA/{rnd_digits(rng, 9)} A/C: {CP} "
                    f"REF: PO{rnd_digits(rng, 4)} IMAD: {d.strftime('%m%d')}B1Q8152C{rnd_digits(rng, 6)}")
        if lab == "bank_fee":
            return "FEDWIRE OUTGOING FEE"
        if lab in ("freight_duty", "rent", "fulfillment_3pl", "software_opex", "sales_tax", "vendor_refund"):
            descr = {"freight_duty": "ACH PMT" if cp == "customs" else "INVOICE", "rent": "RENT",
                     "fulfillment_3pl": "INVOICE", "software_opex": "QBOOKS ONL",
                     "sales_tax": "SALES TAX", "vendor_refund": "REFUND"}[lab]
            return ach(CP, descr)
        if lab == "card_payment":
            return ach(f"{CP} CARD", "AUTOPAY")
        if lab == "ad_spend":
            return ach("FACEBK ADS", "FBADS")
        if lab == "financing_draw":
            return ach(CP, "ADVANCE")
        if lab == "financing_repayment":
            return ach(CP, "LOAN PMT")
        if lab == "interest_expense":
            return ach(CP, "INTEREST")
        if lab == "own_account_transfer":
            other = sav4 if acct == "operating" else op4
            word = "to" if amt < 0 else "from"
            kind = "SAV" if acct == "operating" else "CHK"
            return f"Online Transfer {word} {kind} ...{other} transaction#: {rnd_digits(rng, 11)}"
        if lab == "interest_income":
            return "INTEREST PAYMENT"
    if style == "B":
        des = lambda co, d_: (f"{co} DES:{d_} ID:{rnd_alnum(rng, 10)} INDN:{BR} "
                              f"CO ID:{rnd_digits(rng, 10)} CCD")
        if lab == "processor_payout":
            return des("SHOPIFY", "TRANSFER")
        if lab == "marketplace_payout":
            return des("AMAZON.COM SVCS", "PAYMENTS")
        if lab == "wholesale_payout":
            return des("FAIRE WHOLESALE", "PAYOUT")
        if lab == "wholesale_receipt":
            return des(CP, "PAYMENT")
        if lab == "payroll":
            return des(CP, "NET " + rnd_digits(rng, 6) if part == "net" else "TAX " + rnd_digits(rng, 6))
        if lab == "inventory_purchase":
            return (f"WIRE TYPE:INTL OUT DATE:{yymmdd} TIME:{rng.integers(9, 17)}{rnd_digits(rng, 2)} ET "
                    f"TRN:{d.strftime('%Y%m%d')}{rnd_digits(rng, 8)} FX:USD BNF:{CP} ID:{rnd_digits(rng, 10)}")
        if lab == "bank_fee":
            return "WIRE TRANSFER FEE"
        if lab == "freight_duty":
            return des(CP, "ACH PMT" if cp == "customs" else "BILL PAY")
        if lab in ("rent", "fulfillment_3pl", "software_opex", "sales_tax", "vendor_refund"):
            dd = {"rent": "RENT", "fulfillment_3pl": "BILL PAY", "software_opex": "QB ONLINE",
                  "sales_tax": "TAX PAYMNT", "vendor_refund": "REFUND"}[lab]
            return des(CP, dd)
        if lab == "card_payment":
            return des(f"{CP} CARD", "EPAYMENT")
        if lab == "ad_spend":
            return des("FACEBK", "ADS")
        if lab == "financing_draw":
            return des(CP, "LOAN PROC")
        if lab == "financing_repayment":
            return des(CP, "LOAN PMT")
        if lab == "interest_expense":
            return des(CP, "INTEREST")
        if lab == "own_account_transfer":
            word = "to" if amt < 0 else "from"
            return f"Online Banking transfer {word} SAV {sav4} Confirmation# {rnd_digits(rng, 10)}"
        if lab == "interest_income":
            return "Interest Earned"
    if style == "C":
        name = disp(cp)
        if lab == "processor_payout":
            return "Shopify payout"
        if lab == "marketplace_payout":
            return "Amazon.com Services - settlement"
        if lab == "wholesale_payout":
            return "Faire Wholesale Inc"
        if lab == "wholesale_receipt":
            return f"{name}"
        if lab == "payroll":
            return f"{name} - {'payroll' if part == 'net' else 'payroll taxes'}"
        if lab == "inventory_purchase":
            return f"Wire to {name}"
        if lab == "bank_fee":
            return "International wire fee"
        if lab in ("freight_duty", "rent", "fulfillment_3pl", "software_opex", "sales_tax"):
            return f"{name}"
        if lab == "vendor_refund":
            return f"{name} - refund"
        if lab == "card_payment":
            return f"{name} card payment"
        if lab == "ad_spend":
            return "Facebook Ads"
        if lab == "financing_draw":
            return f"{name} loan advance"
        if lab == "financing_repayment":
            return f"{name} loan payment"
        if lab == "interest_expense":
            return f"{name} interest"
        if lab == "own_account_transfer":
            if acct == "operating":
                return f"Transfer {'to' if amt < 0 else 'from'} Savings ••{sav4}"
            return f"Transfer {'to' if amt < 0 else 'from'} Operating ••{op4}"
        if lab == "interest_income":
            return "Interest earned"
    if style == "D":
        mmdd = d.strftime("%m%d")
        if lab == "processor_payout":
            return f"ACH DEPOSIT SHOPIFY INC {mmdd}"
        if lab == "marketplace_payout":
            return f"ACH DEPOSIT AMAZON PAYMENTS {mmdd}"
        if lab == "wholesale_payout":
            return f"ACH DEPOSIT FAIRE WHOLESALE {mmdd}"
        if lab == "wholesale_receipt":
            return f"ACH CREDIT {CP}"
        if lab == "payroll":
            return f"ACH DEBIT {CP} {'PAYROLL' if part == 'net' else 'PAYROLL TAX'}"
        if lab == "inventory_purchase":
            return f"WIRE OUT {CP}"
        if lab == "bank_fee":
            return "WIRE OUT FEE"
        if lab in ("freight_duty", "rent", "fulfillment_3pl", "software_opex", "sales_tax"):
            return f"ACH DEBIT {CP}"
        if lab == "vendor_refund":
            return f"ACH CREDIT {CP} REFUND"
        if lab == "card_payment":
            return f"ACH DEBIT {CP} CARD PMT"
        if lab == "ad_spend":
            return "ACH DEBIT FACEBK ADS"
        if lab == "financing_draw":
            return f"ACH CREDIT {CP} ADVANCE"
        if lab == "financing_repayment":
            return f"ACH DEBIT {CP} LOAN"
        if lab == "interest_expense":
            return f"ACH DEBIT {CP} INT"
        if lab == "own_account_transfer":
            if acct == "operating":
                return f"XFER {'TO' if amt < 0 else 'FROM'} SHARE 01"
            return f"XFER {'TO' if amt < 0 else 'FROM'} CHECKING 10"
        if lab == "interest_income":
            return "DIVIDEND"
    raise ValueError(f"no memo for {style} {lab}")


# --------------------------------------------------------------------------- bank renderer
def _bank_window(upload):
    if upload == 1:
        return UPLOAD_1
    return (UPLOAD_2[0] - timedelta(days=BANK_OVERLAP_DAYS), UPLOAD_2[1])


def render_bank(sim: BrandSim, upload: int, rng) -> list:
    spec = sim.spec
    layout = spec["bank_layout"]
    style = spec["bank_style"]
    w = _bank_window(upload)
    bank = sim.bank.copy()
    accounts = ["operating", "savings"] if spec.get("savings_in_export") else ["operating"]
    # running balances per account over the whole simulation
    bal = {"operating": sim.extra["opening_operating"], "savings": sim.extra["opening_savings"]}
    if "bank_memos" not in sim.extra:      # one description per transaction, the same in every export
        mrng = np.random.default_rng(spec["seed"] + 4242)
        sim.extra["bank_memos"] = [bank_memo(style, r, spec, mrng) for r in bank.to_dict("records")]
    lines = []
    for k, r in enumerate(bank.to_dict("records")):
        bal[r["account"]] = round(bal[r["account"]] + r["amount"], 2)
        r["balance"] = bal[r["account"]]
        r["memo"] = sim.extra["bank_memos"][k]
        if r["account"] in accounts and in_window(r["date"], w):
            lines.append(r)
    for ln in lines:
        ln["is_duplicate"] = upload == 2 and ln["date"] < UPLOAD_2[0]
    cur = spec["currency"]
    df = spec.get("bank_date", "mdy")

    if layout == "L1":   # newest first, signed amount, DEBIT/CREDIT details, balance
        header = ["Details", "Posting Date", "Description", "Amount", "Type", "Balance", "Check or Slip #"]
        ordered = list(reversed(lines))
        rows = []
        for ln in ordered:
            typ = "ACH_CREDIT" if ln["amount"] > 0 else "ACH_DEBIT"
            if ln["label"] in ("inventory_purchase",):
                typ = "WIRE_OUTGOING"
            if ln["label"] == "own_account_transfer":
                typ = "ACCT_XFER"
            if ln["label"] == "bank_fee":
                typ = "FEE_TRANSACTION"
            rows.append(["CREDIT" if ln["amount"] > 0 else "DEBIT", fmt_date(ln["date"], df), ln["memo"],
                         money(ln["amount"]), typ, money(ln["balance"]), ""])
        cmap = {"date": "Posting Date", "description": "Description", "amount": "Amount", "balance": "Balance"}
        return [RenderedFile(f"bank_operating_{upload}.csv", "csv", "bank", cmap, header, rows,
                             row_truth=_bank_truth(ordered), meta={"order": "newest_first", "date_format": df})]
    if layout == "L2":   # summary preamble, quoted comma amounts, oldest first
        header = ["Date", "Description", "Amount", "Running Bal."]
        start_bal = round(lines[0]["balance"] - lines[0]["amount"], 2) if lines else 0
        credits = round(sum(l["amount"] for l in lines if l["amount"] > 0), 2)
        debits = round(sum(l["amount"] for l in lines if l["amount"] < 0), 2)
        pre = [f"Description,,Summary Amt.",
               f"Beginning balance as of {fmt_date(w[0], df)},,\"{money(start_bal, 'comma')}\"",
               f"Total credits,,\"{money(credits, 'comma')}\"",
               f"Total debits,,\"{money(debits, 'comma')}\"",
               f"Ending balance as of {fmt_date(w[1], df)},,\"{money(lines[-1]['balance'], 'comma')}\"",
               ""]
        rows = [[fmt_date(l["date"], df), l["memo"], money(l["amount"], "comma"), money(l["balance"], "comma")]
                for l in lines]
        cmap = {"date": "Date", "description": "Description", "amount": "Amount", "balance": "Running Bal."}
        return [RenderedFile(f"stmt_{upload}.csv", "csv", "bank", cmap, header, rows, preamble=pre,
                             row_truth=_bank_truth(lines), meta={"order": "oldest_first", "date_format": df})]
    if layout == "L3":   # fintech export, both accounts, no balance, ISO date
        header = ["Date (UTC)", "Description", "Amount", "Status", "Source Account", "Bank Description",
                  "Reference", "Note", "Last Four Digits", "Name on Card", "Category"]
        rows = []
        for l in lines:
            acc = f"{'Operating' if l['account'] == 'operating' else 'Savings'} ••" + \
                  (spec["operating_last4"] if l["account"] == "operating" else spec["savings_last4"])
            rows.append([fmt_date(l["date"], df), l["memo"], money(l["amount"]), "Sent" if l["amount"] < 0 else "Received",
                         acc, l["memo"].upper()[:40], "", "", "", "", ""])
        cmap = {"date": "Date (UTC)", "description": "Description", "amount": "Amount", "account": "Source Account"}
        return [RenderedFile(f"transactions_{upload}.csv", "csv", "bank", cmap, header, rows,
                             row_truth=_bank_truth(lines), meta={"order": "oldest_first", "date_format": df})]
    if layout == "L4":   # credit union: debit/credit split, two account numbers, footer
        header = ["Account Number", "Post Date", "Check", "Description", "Debit", "Credit", "Status", "Balance"]
        rows = []
        for l in lines:
            acc = ("10" + spec["operating_last4"]) if l["account"] == "operating" else ("01" + spec["savings_last4"])
            deb = money(-l["amount"]) if l["amount"] < 0 else ""
            cre = money(l["amount"]) if l["amount"] > 0 else ""
            rows.append([acc, fmt_date(l["date"], df), "", l["memo"], deb, cre, "Posted", money(l["balance"])])
        footer = [["", "", "", "Total", money(-sum(l["amount"] for l in lines if l["amount"] < 0)),
                   money(sum(l["amount"] for l in lines if l["amount"] > 0)), "", ""]]
        cmap = {"date": "Post Date", "description": "Description", "debit": "Debit", "credit": "Credit",
                "balance": "Balance", "account": "Account Number"}
        return [RenderedFile(f"export_{upload}.csv", "csv", "bank", cmap, header, rows, footer=footer,
                             row_truth=_bank_truth(lines), meta={"order": "oldest_first", "date_format": df})]
    raise ValueError(layout)


def _bank_truth(lines):
    return [dict(label=l["label"], account=l["account"], amount=l["amount"], date=l["date"].isoformat(),
                 is_duplicate=bool(l["is_duplicate"]), counterparty=disp(l["cp"])) for l in lines]


# --------------------------------------------------------------------------- card renderer
CARD_DESC = {
    "meta": ["FACEBK *{a8}", "FACEBK *{a8} fb.me/ads CA"],
    "google": ["GOOGLE *ADS{d10}", "GOOGLE *ADS{d10} cc@google.com CA"],
    "tiktok": ["TIKTOK ADS {d8}", "TIKTOK.COM ADS"],
    "pinterest": ["PINTEREST *ADS", "PINTEREST ADS {d6}"],
    "klaviyo": ["KLAVIYO INC.", "KLAVIYO INC. BOSTON MA"],
    "shopify_sub": ["SHOPIFY* {d9}", "SHOPIFY* {d9} SHOPIFY.COM ON"],
    "canva": ["CANVA* {d8}"], "slack": ["SLACK T0{a7}"], "gorgias": ["GORGIAS.IO"],
    "notion": ["NOTION LABS, INC."], "recharge": ["RECHARGE PAYMENTS"], "gsuite": ["GOOGLE *GSUITE_{a6}"],
    "figma": ["FIGMA MONTHLY"], "triplewhale": ["TRIPLE WHALE"],
    "uber": ["UBER *TRIP", "UBER *TRIP HELP.UBER.COM"], "lyft": ["LYFT *RIDE {a3}"],
    "delta": ["DELTA AIR {d10}"], "jetblue": ["JETBLUE {d10}"], "marriott": ["MARRIOTT BROOKLYN"],
    "bluedoor": ["BLUE DOOR CAFE"], "corner": ["CORNER BISTRO NYC"], "sq_coffee": ["SQ *NORTHSIDE COFFEE"],
    "uline": ["ULINE *S{d7}"], "stamps": ["STAMPS.COM"], "pirateship": ["PIRATE SHIP"],
    "papermart": ["PAPER MART INC"], "boxco": ["BOXCO PACKAGING"],
}
CARD_PAYMENT_DESC = {"K1": "AUTOMATIC PAYMENT - THANK YOU", "K2": "AUTOPAY PAYMENT RECEIVED - THANK YOU",
                     "K3": "PAYMENT - THANK YOU"}


def card_desc(cp, rng):
    pats = CARD_DESC[cp]
    p = pats[int(rng.integers(0, len(pats)))]
    return p.format(a8=rnd_alnum(rng, 8), d10=rnd_digits(rng, 10), d8=rnd_digits(rng, 8), d9=rnd_digits(rng, 9),
                    a7=rnd_alnum(rng, 7), a6=rnd_alnum(rng, 6), d6=rnd_digits(rng, 6), d7=rnd_digits(rng, 7),
                    a3=rnd_alnum(rng, 3))


def render_card(sim: BrandSim, upload: int, rng) -> list:
    spec = sim.spec
    layout = spec["card_layout"]
    w = (CARD_UPLOAD_1_START, UPLOAD_1[1]) if upload == 1 else (UPLOAD_2[0] - timedelta(days=5), UPLOAD_2[1])
    if "card_desc" not in sim.extra:
        crng = np.random.default_rng(spec["seed"] + 5151)
        sim.extra["card_desc"] = [CARD_PAYMENT_DESC[layout] if l == "card_payment_received" else card_desc(c, crng)
                                  for l, c in zip(sim.card["label"], sim.card["cp"])]
    allc = sim.card.copy()
    allc["desc"] = sim.extra["card_desc"]
    allc["ref"] = [rnd_digits(np.random.default_rng(spec["seed"] * 7 + i), 23) for i in range(len(allc))]
    card = allc[[in_window(d, w) for d in allc["date"]]].copy()
    lines = card.to_dict("records")
    for l in lines:
        l["is_duplicate"] = upload == 2 and l["date"] < UPLOAD_2[0]
    df = spec.get("card_date", "mdy")
    truth = [dict(label=l["label"], amount=round(l["amount"], 2), date=l["date"].isoformat(),
                  is_duplicate=bool(l["is_duplicate"])) for l in lines]
    cat = {"ad_spend": "Advertising", "software_opex": "Bills & Utilities", "travel_other": "Travel",
           "shipping_supplies": "Shopping", "card_payment_received": ""}
    if layout == "K1":   # charges negative, Type column
        header = ["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo"]
        rows = [[fmt_date(l["date"], df), fmt_date(l["date"] + timedelta(days=1), df), l["desc"], cat[l["label"]],
                 "Payment" if l["label"] == "card_payment_received" else "Sale", money(-l["amount"]), ""]
                for l in lines]
        cmap = {"date": "Transaction Date", "description": "Description", "amount": "Amount", "txn_type": "Type"}
        return [RenderedFile(f"card_activity_{upload}.csv", "csv", "card", cmap, header, rows, row_truth=truth,
                             meta={"charge_sign": "negative", "date_format": df})]
    if layout == "K2":   # charges positive, card member column
        header = ["Date", "Description", "Card Member", "Account #", "Amount"]
        member = spec["card_member"]
        rows = [[fmt_date(l["date"], df), l["desc"], member, "-" + spec["card_last5"], money(l["amount"])]
                for l in lines]
        cmap = {"date": "Date", "description": "Description", "amount": "Amount"}
        return [RenderedFile(f"activity_{upload}.csv", "csv", "card", cmap, header, rows, row_truth=truth,
                             meta={"charge_sign": "positive", "date_format": df})]
    if layout == "K3":   # charges negative, payee/address, footer total
        header = ["Posted Date", "Reference Number", "Payee", "Address", "Amount"]
        rows = [[fmt_date(l["date"], df), l["ref"], l["desc"], "", money(-l["amount"])] for l in lines]
        footer = [["", "", "Total", "", money(-sum(l["amount"] for l in lines))]]
        cmap = {"date": "Posted Date", "description": "Payee", "amount": "Amount"}
        return [RenderedFile(f"card_{upload}.csv", "csv", "card", cmap, header, rows, footer=footer, row_truth=truth,
                             meta={"charge_sign": "negative", "date_format": df})]
    raise ValueError(layout)


# --------------------------------------------------------------------------- shopify orders
def render_orders(sim: BrandSim, upload: int, rng) -> list:
    spec = sim.spec
    w = UPLOAD_1 if upload == 1 else UPLOAD_2
    layout = spec["orders_layout"]
    o = sim.orders[[in_window(d, w) for d in sim.orders["day"]]]
    items = {}
    for it in sim.order_items.to_dict("records"):
        items.setdefault(it["order_id"], []).append(it)
    refunds = sim.refunds[sim.refunds["kind"] == "refund"]
    ref_by = refunds[[d <= w[1] for d in refunds["refund_date"]]].groupby("order_id")["amount"].sum().to_dict()
    cur = spec["currency"]
    if layout == "O1":   # line items, order fields on first row only
        header = ["Name", "Email", "Financial Status", "Paid at", "Fulfillment Status", "Fulfilled at",
                  "Accepts Marketing", "Currency", "Subtotal", "Shipping", "Taxes", "Total", "Discount Code",
                  "Discount Amount", "Shipping Method", "Created at", "Lineitem quantity", "Lineitem name",
                  "Lineitem price", "Lineitem sku", "Refunded Amount"]
        rows = []
        for r in o.itertuples():
            ts = r.created_at.strftime("%Y-%m-%d %H:%M:%S") + " -0400"
            for j, it in enumerate(items[r.order_id]):
                if j == 0:
                    ref = ref_by.get(r.order_id, 0.0)
                    status = "refunded" if ref >= r.total - 0.01 else ("partially_refunded" if ref > 0 else "paid")
                    rows.append([r.order_id, f"c{rnd_digits(rng, 6)}@example.com", status, ts, "fulfilled", ts,
                                 "yes" if rng.random() < 0.6 else "no", cur, money(r.subtotal), money(r.shipping),
                                 money(r.tax), money(r.total), "WELCOME10" if r.discount else "", money(r.discount),
                                 "Standard", ts, str(it["qty"]), it["name"], money(it["price"]), it["sku"], money(ref)])
                else:
                    rows.append([r.order_id, "", "", "", "", "", "", "", "", "", "", "", "", "", "", ts,
                                 str(it["qty"]), it["name"], money(it["price"]), it["sku"], ""])
        cmap = {"order_id": "Name", "created_at": "Created at", "total": "Total", "subtotal": "Subtotal",
                "shipping": "Shipping", "taxes": "Taxes", "discount": "Discount Amount", "currency": "Currency"}
        return [RenderedFile(f"orders_export_{upload}.csv", "csv", "orders_list", cmap, header, rows,
                             meta={"totals": "first_row_only"})]
    if layout == "O3":   # third-party app export, order totals repeated on every line
        header = ["Order ID", "Order Date", "Customer", "SKU", "Product", "Qty", "Unit Price", "Order Subtotal",
                  "Order Discount", "Order Shipping", "Order Tax", "Order Total"]
        rows = []
        for r in o.itertuples():
            ts = r.created_at.strftime("%m/%d/%Y %-I:%M %p")
            for it in items[r.order_id]:
                rows.append([r.order_id, ts, f"Customer {rnd_digits(rng, 5)}", it["sku"], it["name"], str(it["qty"]),
                             money(it["price"]), money(r.subtotal), money(r.discount), money(r.shipping), money(r.tax),
                             money(r.total)])
        cmap = {"order_id": "Order ID", "created_at": "Order Date", "total": "Order Total",
                "subtotal": "Order Subtotal", "shipping": "Order Shipping", "taxes": "Order Tax",
                "discount": "Order Discount"}
        return [RenderedFile(f"order_lines_{upload}.csv", "csv", "orders_list", cmap, header, rows,
                             meta={"totals": "repeated_per_line"})]
    if layout == "O2":   # daily sales report
        header = ["Day", "Orders", "Gross sales", "Discounts", "Returns", "Net sales", "Shipping", "Taxes", "Total sales"]
        style = spec.get("orders_money", "plain")
        rows = []
        days = sorted(set(o["day"]))
        ref_day = refunds.groupby("refund_date")["amount"].sum().to_dict()
        for d in days:
            g = o[o["day"] == d]
            gross = round(g["subtotal"].sum(), 2)
            disc = -round(g["discount"].sum(), 2)
            ret = -round(ref_day.get(d, 0.0), 2)
            net = round(gross + disc + ret, 2)
            shipv = round(g["shipping"].sum(), 2)
            taxv = round(g["tax"].sum(), 2)
            rows.append([d.isoformat(), str(len(g)), money(gross, style), money(disc, style), money(ret, style),
                         money(net, style), money(shipv, style), money(taxv, style),
                         money(round(net + shipv + taxv, 2), style)])
        cmap = {"day": "Day", "orders": "Orders", "gross_sales": "Gross sales", "discounts": "Discounts",
                "returns": "Returns", "net_sales": "Net sales", "shipping": "Shipping", "taxes": "Taxes",
                "total_sales": "Total sales"}
        return [RenderedFile(f"sales_over_time_{upload}.csv", "csv", "sales_daily", cmap, header, rows)]
    raise ValueError(layout)


# --------------------------------------------------------------------------- shopify payouts
def render_payouts(sim: BrandSim, upload: int, rng) -> list:
    spec = sim.spec
    w = UPLOAD_1 if upload == 1 else UPLOAD_2
    p = sim.payouts[[in_window(d, w) for d in sim.payouts["payout_date"]]]
    layout = spec["payouts_layout"]
    cur = spec["currency"]
    if layout == "P1":
        header = ["Payout Date", "Status", "Charges", "Refunds", "Adjustments", "Reserved Funds", "Fees",
                  "Retried Amount", "Total", "Currency"]
        rows = [[r.payout_date.isoformat(), "paid", money(r.charges), money(-r.refunds), money(r.adjustments),
                 "0.00", money(-r.fees), "0.00", money(r.net), cur] for r in p.itertuples()]
        cmap = {"payout_date": "Payout Date", "charges": "Charges", "refunds": "Refunds",
                "adjustments": "Adjustments", "fees": "Fees", "net": "Total", "currency": "Currency",
                "status": "Status"}
        return [RenderedFile(f"payouts_{upload}.csv", "csv", "payouts", cmap, header, rows)]
    if layout == "P1b":   # alternate export: positive fees and refunds, dollar signs
        header = ["Date", "Payout ID", "Status", "Gross", "Refunds", "Fees", "Adjustments", "Net"]
        rows = [[fmt_date(r.payout_date, spec.get("payout_date", "mdy")), r.payout_id, "Deposited",
                 money(r.charges, "dollar"), money(r.refunds, "dollar"), money(r.fees, "dollar"),
                 money(r.adjustments, "dollar"), money(r.net, "dollar")] for r in p.itertuples()]
        cmap = {"payout_date": "Date", "payout_id": "Payout ID", "charges": "Gross", "refunds": "Refunds",
                "fees": "Fees", "adjustments": "Adjustments", "net": "Net", "status": "Status"}
        return [RenderedFile(f"shopify_payments_{upload}.csv", "csv", "payouts", cmap, header, rows)]
    raise ValueError(layout)


# --------------------------------------------------------------------------- amazon
def render_amazon(sim: BrandSim, upload: int, rng) -> list:
    spec = sim.spec
    if sim.amazon_settlements is None:
        return []
    w = UPLOAD_1 if upload == 1 else UPLOAD_2
    layout = spec["amazon_layout"]
    cur = spec["currency"]
    out = []
    if layout == "A1":   # one flat file per settlement, summary row first, tab separated
        header = ["settlement-id", "settlement-start-date", "settlement-end-date", "deposit-date", "total-amount",
                  "currency", "transaction-type", "order-id", "merchant-order-id", "adjustment-id", "shipment-id",
                  "marketplace-name", "amount-type", "amount-description", "amount", "fulfillment-id", "posted-date",
                  "posted-date-time", "order-item-code", "merchant-order-item-id", "merchant-adjustment-item-id",
                  "sku", "quantity-purchased", "promotion-id"]
        fmt = lambda d: d.strftime("%Y-%m-%d") + " 07:00:00 UTC"
        for s in sim.amazon_settlements.itertuples():
            if not in_window(s.deposit_date, w):
                continue
            det = sim.amazon_rows[sim.amazon_rows["settlement_id"] == s.settlement_id]
            rows = [[s.settlement_id, fmt(s.start), fmt(s.end), fmt(s.deposit_date), money(s.total), cur]
                    + [""] * 18]
            for r in det.itertuples():
                rows.append([s.settlement_id, "", "", "", "", "", r.transaction_type, r.order_id, "", "", "",
                             "Amazon.com", r.amount_type, r.amount_description, money(r.amount), "AFN",
                             r.posted_date.isoformat(), r.posted_date.isoformat() + " 12:00:00 UTC", "", "", "",
                             "", "", ""])
            cmap = {"settlement_id": "settlement-id", "settlement_start": "settlement-start-date",
                    "settlement_end": "settlement-end-date", "deposit_date": "deposit-date",
                    "total_amount": "total-amount", "transaction_type": "transaction-type",
                    "amount_type": "amount-type", "amount_description": "amount-description",
                    "amount": "amount", "posted_date": "posted-date", "order_id": "order-id",
                    "currency": "currency"}
            out.append(RenderedFile(f"settlement_{s.settlement_id}.txt", "tsv", "amazon_flat", cmap, header, rows,
                                    delimiter="\t"))
        return out
    if layout == "A2":   # date range report with preamble lines and Transfer rows
        header = ["date/time", "settlement id", "type", "order id", "sku", "description", "quantity",
                  "marketplace", "account type", "fulfillment", "order city", "order state", "order postal",
                  "tax collection model", "product sales", "product sales tax", "shipping credits",
                  "shipping credits tax", "gift wrap credits", "giftwrap credits tax", "Regulatory Fee",
                  "Tax On Regulatory Fee", "promotional rebates", "promotional rebates tax",
                  "marketplace withheld tax", "selling fees", "fba fees", "other transaction fees", "other", "total"]
        pre = ['"Includes Amazon Marketplace, Fulfillment by Amazon (FBA), and Amazon Webstore transactions"',
               '"All amounts in USD, unless specified"',
               '"Definitions:"',
               '"Sales tax collected: Includes sales tax collected from buyers for product sales, shipping, and gift wrap."',
               '"Selling fees: Includes variable closing fees and referral fees."',
               '"Other transaction fees: Includes sales tax collection fees."',
               '"Other: Includes non-order transaction amounts. For more details, see the ""Type"" and ""Description"" columns for each order ID."']
        rows = []
        dt = lambda d: d.strftime("%b %-d, %Y") + " 12:00:00 PM PDT"
        for s in sim.amazon_settlements.itertuples():
            det = sim.amazon_rows[sim.amazon_rows["settlement_id"] == s.settlement_id]
            for oid, g in det.groupby(["order_id", "transaction_type"], sort=False):
                order_id, ttype = oid
                d = g["posted_date"].max()
                if not in_window(d, w):
                    continue
                if ttype == "other-transaction":
                    for r in g.itertuples():
                        typ = "Service Fee" if r.amount_description == "Subscription Fee" else "Adjustment"
                        rows.append([dt(d), s.settlement_id, typ, "", "", r.amount_description, "", "", "", "",
                                     "", "", "", "", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
                                     "0", money(r.amount), money(r.amount)])
                    continue
                ps = g.loc[g["amount_description"] == "Principal", "amount"].sum()
                sf = g.loc[g["amount_description"] == "Commission", "amount"].sum()
                ff = g.loc[g["amount_description"] == "FBAPerUnitFulfillmentFee", "amount"].sum()
                tot = round(ps + sf + ff, 2)
                rows.append([dt(d), s.settlement_id, "Order" if ttype == "Order" else "Refund", order_id,
                             f"{spec['sku_prefix']}-A1", "Item", "1", "amazon.com", "Standard Orders", "Amazon",
                             "BROOKLYN", "NY", "11201", "MarketplaceFacilitator", money(ps), "0", "0", "0", "0", "0",
                             "0", "0", "0", "0", "0", money(sf), money(ff), "0", "0", money(tot)])
            if in_window(s.deposit_date, w):
                rows.append([dt(s.deposit_date), s.settlement_id, "Transfer", "", "",
                             f"To account ending in: {spec['operating_last4'][-3:]}", "", "", "", "", "", "", "", "",
                             "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
                             money(-s.total), money(-s.total)])
        rows.sort(key=lambda r: pd.to_datetime(r[0].replace(" PDT", ""), format="%b %d, %Y %I:%M:%S %p"))
        cmap = {"date_time": "date/time", "settlement_id": "settlement id", "type": "type", "order_id": "order id",
                "description": "description", "product_sales": "product sales", "selling_fees": "selling fees",
                "fba_fees": "fba fees", "other": "other", "total": "total"}
        out.append(RenderedFile(f"amazon_date_range_{upload}.csv", "csv", "amazon_range", cmap, header, rows,
                                preamble=pre))
        return out
    raise ValueError(layout)


# --------------------------------------------------------------------------- faire
def render_faire(sim: BrandSim, upload: int, rng) -> list:
    spec = sim.spec
    if sim.faire_orders is None:
        return []
    w = UPLOAD_1 if upload == 1 else UPLOAD_2
    f = sim.faire_orders[[in_window(d, w) for d in sim.faire_orders["payout_date"]]]
    layout = spec["faire_layout"]
    if layout == "F1":
        header = ["Order Number", "Retailer", "Order Date", "Ship Date", "Payout Date", "Wholesale Total",
                  "Commission", "Payout"]
        rows = [[r.order_number, r.retailer, r.order_date.isoformat(), r.ship_date.isoformat(),
                 r.payout_date.isoformat(), money(r.wholesale_total), money(r.commission), money(r.payout_amount)]
                for r in f.itertuples()]
        cmap = {"order_number": "Order Number", "retailer": "Retailer", "order_date": "Order Date",
                "ship_date": "Ship Date", "payout_date": "Payout Date", "wholesale_total": "Wholesale Total",
                "commission": "Commission", "payout_amount": "Payout"}
        return [RenderedFile(f"faire_orders_{upload}.csv", "csv", "faire", cmap, header, rows)]
    if layout == "F2":
        header = ["Order #", "Store Name", "Date Placed", "Date Shipped", "Paid Out On", "Order Value",
                  "Faire Fee", "Net Payout"]
        df = spec.get("faire_date", "mon_d_y")
        rows = [[r.order_number, r.retailer, fmt_date(r.order_date, df), fmt_date(r.ship_date, df),
                 fmt_date(r.payout_date, df), money(r.wholesale_total, "dollar"), money(r.commission, "dollar"),
                 money(r.payout_amount, "dollar")] for r in f.itertuples()]
        cmap = {"order_number": "Order #", "retailer": "Store Name", "order_date": "Date Placed",
                "ship_date": "Date Shipped", "payout_date": "Paid Out On", "wholesale_total": "Order Value",
                "commission": "Faire Fee", "payout_amount": "Net Payout"}
        return [RenderedFile(f"faire_payouts_{upload}.xlsx", "xlsx", "faire", cmap, header, rows)]
    raise ValueError(layout)


# --------------------------------------------------------------------------- chart of accounts
def render_coa(sim: BrandSim, upload: int, rng) -> list:
    spec = sim.spec
    coa = sim.coa.copy()
    if upload == 2:
        extra = spec["coa_added_upload2"]
        coa = pd.concat([coa, pd.DataFrame([extra])], ignore_index=True)
    layout = spec["coa_layout"]
    truth = [dict(label=l) for l in coa["label"]]
    if layout == "C1":
        header = ["Account #", "Account", "Type", "Detail Type", "Description", "Balance"]
        rows = [[str(r.number), r.name, r.type, "", "", ""] for r in coa.itertuples()]
        cmap = {"number": "Account #", "name": "Account", "type": "Type"}
        return [RenderedFile(f"account_list_{upload}.csv", "csv", "coa", cmap, header, rows, row_truth=truth)]
    if layout == "C2":
        header = ["Number", "Name", "Account Type"]
        rows = [[str(r.number), r.name, r.type] for r in coa.itertuples()]
        cmap = {"number": "Number", "name": "Name", "type": "Account Type"}
        return [RenderedFile(f"chart_of_accounts_{upload}.xlsx", "xlsx", "coa", cmap, header, rows, row_truth=truth)]
    if layout == "C3":   # no numbers, parent:child names
        header = ["Full name", "Type"]
        rows = [[r.name, r.type] for r in coa.itertuples()]
        cmap = {"name": "Full name", "type": "Type"}
        return [RenderedFile(f"accounts_{upload}.csv", "csv", "coa", cmap, header, rows, row_truth=truth)]
    raise ValueError(layout)


RENDERERS = [render_bank, render_card, render_orders, render_payouts, render_amazon, render_faire, render_coa]


# --------------------------------------------------------------------------- writing
def write_file(rf: RenderedFile, folder):
    import openpyxl
    path = folder / rf.name
    if rf.kind == "xlsx":
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        for line in (rf.preamble or []):
            ws.append([line])
        ws.append(rf.header)
        for r in rf.rows:
            ws.append(r)
        for r in (rf.footer or []):
            ws.append(r)
        wb.save(path)
        return path
    buf = io.StringIO()
    for line in (rf.preamble or []):
        buf.write(line + "\n")
    wr = csv.writer(buf, delimiter=rf.delimiter, lineterminator="\n")
    wr.writerow(rf.header)
    for r in rf.rows:
        wr.writerow(r)
    for r in (rf.footer or []):
        wr.writerow(r)
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path
