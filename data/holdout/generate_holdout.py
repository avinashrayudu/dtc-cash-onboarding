"""
Holdout brands. Written after the onboarding code and models were frozen
(see evals/FREEZE.json); nothing under onboard/ or models/ was changed afterwards.

Three brands with formats the pipeline has not seen during development:

  lumen-and-oak        EUR brand. Semicolon bank export with decimal commas and
                       day-month-year dates with dashes, SEPA-style memos, a
                       semicolon card export, new account names.
  copper-kettle        US brand. Shopify payouts exported one row per transaction
                       instead of one row per payout, PayPal deposits with no PayPal
                       export, a neobank memo style, dates written "Oct 3, 2026".
  northwind-ceramics   US brand. Bank amounts all positive with the direction in a
                       separate DR/CR column, new memo style, capitalized report headers.

The quirk categories were chosen during planning; the exact headers, memo
formats, vendor names and account names below were written after the freeze.

Built by Avinash Rayudu. All brands, names and numbers are invented.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent
sys.path.insert(0, str(DATA))

from generate_brands import fill_defaults, soft, write_brand            # noqa: E402
from render import (CARD_PAYMENT_DESC, RenderedFile, _bank_truth, _bank_window, card_desc, disp, fmt_date,
                    in_window, money, render_amazon, render_faire, render_orders, render_payouts, rnd_digits,
                    render_card, render_coa)                                  # noqa: E402
from sim import UPLOAD_1, UPLOAD_2, CARD_UPLOAD_1_START, daterange, next_bday   # noqa: E402

ROOT = DATA.parent

HOLDOUT_COA = {
    "bank_account": (["ABN Current Account", "Operating Cash", "Main Checking 0412", "Reserve Account",
                      "Business Savings Acct"], "Bank"),
    "credit_card_account": (["Company Credit Card", "Card Liability", "Business Visa"], "Credit Card"),
    "loan_account": (["LOC Payable", "Term Loan"], "Long Term Liabilities"),
    "sales_tax_payable": (["VAT Payable", "Sales Tax Owed", "State Sales Tax Payable"], "Other Current Liabilities"),
    "revenue_dtc": (["Sales - Online Store (Shopify)", "Webshop Revenue", "Direct Sales"], "Income"),
    "revenue_marketplace": (["Amazon Marketplace Income", "Marketplace Sales - AMZ"], "Income"),
    "revenue_wholesale": (["Wholesale Revenue - Faire", "Trade Accounts Revenue", "Stockist Sales"], "Income"),
    "refunds_returns": (["Returns & Refunds Issued", "Sales Refunds"], "Income"),
    "cogs_product": (["Purchases - Finished Goods", "Product COGS", "Materials & Components"], "Cost of Goods Sold"),
    "cogs_freight_duty": (["Inbound Shipping", "Duties & Tariffs", "Freight & Customs"], "Cost of Goods Sold"),
    "fulfillment_3pl": (["3PL & Warehousing", "Fulfilment Costs", "Order Fulfillment"], "Cost of Goods Sold"),
    "merchant_fees": (["Stripe/Shopify Fees", "Card Processing Charges", "Payment Gateway Fees"], "Expenses"),
    "advertising": (["Facebook & Instagram Ads", "Google Shopping Ads", "Performance Marketing",
                     "Paid Acquisition"], "Expenses"),
    "payroll": (["Wages & Salaries", "Employer Payroll Taxes", "Staff Costs", "Gross Wages"], "Expenses"),
    "software": (["Software Subscriptions", "Tech Stack", "Cloud & SaaS"], "Expenses"),
    "rent": (["Lease Expense", "Warehouse & Studio Lease", "Premises Rent"], "Expenses"),
    "travel_meals": (["Travel Expense", "Meals & Client Entertainment", "Trips & Lodging"], "Expenses"),
    "shipping_supplies": (["Packaging & Postage", "Mailers & Boxes", "Shipping Materials"], "Expenses"),
    "interest_expense": (["Interest - LOC", "Bank Interest Expense"], "Other Expense"),
    "other_opex": (["General & Administrative", "Accounting Fees", "Business Insurance", "Office Expenses",
                    "Licenses & Permits"], "Expenses"),
}

HOLDOUT_BRANDS = [
    dict(slug="lumen-and-oak", name="Lumen & Oak", split="holdout", seed=1111, currency="EUR", annual_rev=3.4e6,
         shares=dict(shopify=0.85, faire=0.15), aov=58, tax_rate=0.21,
         payroll_provider="Nmbrs", suppliers=["Veldhoven Glas BV", "Aurelia Scents SRL"],
         forwarder="Rijnmond Cargo", threepl="Polderpack Fulfilment", landlord="Westerdok Vastgoed",
         tax_agency="BELASTINGDIENST", card_issuer="Lindeberg", lender=None,
         faire_retailers=["Maison Verde", "Het Kleine Huis", "Atelier Nord"],
         ad_platforms=[("meta", 0.65, 2000.0), ("google", 0.35, 1000.0)],
         card_software=soft(["klaviyo", "shopify_sub", "canva"], [3, 8, 19]),
         travel_merchants=["uber", "marriott"], supply_merchants=["boxco", "papermart"],
         bank_style="E", bank_layout="L5", card_layout="K4", orders_layout="O1", payouts_layout="P1",
         faire_layout="F1", coa_layout="C1",
         coa_added_upload2=dict(number=6970, name="Trade Fair Costs", type="Expenses", label="other_opex")),
    dict(slug="copper-kettle", name="Copper Kettle Kitchen", split="holdout", seed=1212, currency="USD",
         annual_rev=4.6e6, shares=dict(shopify=0.80, amazon=0.20), aov=74, tax_rate=0.0725,
         payroll_provider="OnPay", suppliers=["Brightwater Cookware Co", "Sable Iron Works"],
         forwarder="Quayside Freight Partners", threepl="Stackhouse Fulfillment", landlord="Fulton Mill LLC",
         tax_agency="OH DEPT OF TAXATION", card_issuer="Beacon", lender="Fennec Capital",
         direct_retailers=["Pantry & Pine"],
         ad_platforms=[("meta", 0.55, 3000.0), ("google", 0.30, 2000.0), ("tiktok", 0.15, 1000.0)],
         card_software=soft(["klaviyo", "shopify_sub", "gorgias", "triplewhale"], [2, 7, 14, 21]),
         travel_merchants=["lyft", "delta", "corner"], supply_merchants=["uline", "stamps"],
         bank_style="F", bank_layout="L7", bank_date="mon_d_y", card_layout="K1", card_date="mdy",
         orders_layout="O3", payouts_layout="P2", amazon_layout="A1", coa_layout="C3", paypal=True,
         coa_added_upload2=dict(number=0, name="Influencer Seeding", type="Expenses", label="advertising")),
    dict(slug="northwind-ceramics", name="Northwind Ceramics", split="holdout", seed=1313, currency="USD",
         annual_rev=2.9e6, shares=dict(shopify=0.70, amazon=0.10, faire=0.20), aov=66, tax_rate=0.065,
         payroll_provider="Paycor", suppliers=["Kilnworks Pottery Ltd"],
         forwarder="Granite Bay Logistics", threepl="Hearthstone 3PL", landlord="Riverside Arts Bldg LLC",
         tax_agency="WA DEPT OF REVENUE", card_issuer="Cascade", lender=None,
         faire_retailers=["Saltgrass Goods", "Juniper & Co"],
         ad_platforms=[("meta", 0.60, 1500.0), ("google", 0.25, 1000.0), ("pinterest", 0.15, 600.0)],
         card_software=soft(["klaviyo", "shopify_sub", "notion"], [5, 10, 20]),
         travel_merchants=["uber", "sq_coffee"], supply_merchants=["uline", "pirateship"],
         bank_style="G", bank_layout="L6", bank_date="mdy", savings_in_export=True, card_layout="K2",
         card_date="mdy", card_member="R LINDQVIST", orders_layout="O2b", payouts_layout="P1b",
         amazon_layout="A2", faire_layout="F2", coa_layout="C2",
         coa_added_upload2=dict(number=6980, name="Kiln Repairs", type="Expenses", label="other_opex")),
]


# --------------------------------------------------------------------------- new memo styles
def memo_h(style, line, spec, rng):
    lab, cp, amt = line["label"], line["cp"], line["amount"]
    d = line["date"]
    CP = disp(cp).upper()
    det = line["detail"] if isinstance(line["detail"], dict) else {}
    part, acct = det.get("part"), line.get("account", "operating")
    sav4 = spec["savings_last4"]
    if style == "E":   # SEPA style, English
        ref = f"REF {rnd_digits(rng, 12)}"
        m = {
            "processor_payout": f"SEPA CREDIT TRANSFER SHOPIFY INTERNATIONAL LTD {ref}",
            "wholesale_payout": f"SEPA CREDIT TRANSFER FAIRE WHOLESALE INC {ref}",
            "payroll": f"SEPA DIRECT DEBIT {CP} {'SALARIES' if part == 'net' else 'PAYROLL TAXES'} {d:%m-%Y}",
            "inventory_purchase": f"SEPA TRANSFER TO {CP} INVOICE {rnd_digits(rng, 5)}",
            "bank_fee": "TRANSACTION COSTS",
            "freight_duty": "CUSTOMS IMPORT DUTY " + rnd_digits(rng, 8) if cp == "customs" else f"SEPA TRANSFER TO {CP}",
            "rent": f"SEPA TRANSFER TO {CP} RENT {d:%m-%Y}",
            "fulfillment_3pl": f"SEPA DIRECT DEBIT {CP} {ref}",
            "software_opex": f"SEPA DIRECT DEBIT INTUIT {ref}",
            "sales_tax": f"{CP} BTW {d:%m-%Y}",
            "card_payment": f"{CP} CARD SETTLEMENT {d:%m-%Y}",
            "vendor_refund": f"SEPA CREDIT TRANSFER {CP} CREDIT NOTE {rnd_digits(rng, 4)}",
            "own_account_transfer": f"TRANSFER {'TO' if amt < 0 else 'FROM'} SAVINGS NL..{sav4}",
            "interest_income": "INTEREST",
        }
        return m[lab]
    if style == "F":   # US neobank
        m = {
            "processor_payout": "Deposit from PAYPAL TRANSFER" if cp == "paypal" else "Deposit from SHOPIFY",
            "marketplace_payout": "Deposit from AMAZON.COM SVCS",
            "wholesale_receipt": f"Deposit from {CP}",
            "payroll": f"{disp(cp)} {'payroll run' if part == 'net' else 'tax remittance'}",
            "inventory_purchase": f"Outgoing wire: {disp(cp)}",
            "bank_fee": "Outgoing wire fee",
            "freight_duty": "ACH payment to U.S. CUSTOMS & BORDER PROTECTION" if cp == "customs"
            else f"ACH payment to {disp(cp)}",
            "rent": f"ACH payment to {disp(cp)}", "fulfillment_3pl": f"ACH payment to {disp(cp)}",
            "software_opex": "ACH payment to Intuit QuickBooks", "sales_tax": f"ACH payment to {disp(cp)}",
            "card_payment": f"{disp(cp)} credit card autopay",
            "vendor_refund": f"Refund from {disp(cp)}",
            "financing_draw": f"Loan disbursement from {disp(cp)}",
            "financing_repayment": f"Loan repayment to {disp(cp)}",
            "interest_expense": f"Interest charge {disp(cp)}",
            "own_account_transfer": f"Internal transfer {'to' if amt < 0 else 'from'} reserve account",
            "interest_income": "Interest paid",
        }
        return m[lab]
    if style == "G":   # DR/CR bank
        m = {
            "processor_payout": "ACH CREDIT - SHOPIFY PAYMENTS", "marketplace_payout": "ACH CREDIT - AMAZON SELLER",
            "wholesale_payout": "ACH CREDIT - FAIRE",
            "payroll": f"ACH DEBIT - {CP} {'PAYROLL' if part == 'net' else 'TAXES'}",
            "inventory_purchase": f"INTL WIRE OUT - {CP}", "bank_fee": "WIRE FEE",
            "freight_duty": "ACH DEBIT - US CUSTOMS" if cp == "customs" else f"ACH DEBIT - {CP}",
            "rent": f"ACH DEBIT - {CP}", "fulfillment_3pl": f"ACH DEBIT - {CP}",
            "software_opex": "ACH DEBIT - INTUIT", "sales_tax": f"ACH DEBIT - {CP}",
            "card_payment": f"ACH DEBIT - {CP} CARD", "vendor_refund": f"ACH CREDIT - {CP}",
            "own_account_transfer": (f"TRANSFER {'TO' if amt < 0 else 'FROM'} SAVINGS x{sav4}" if acct == "operating"
                                     else f"TRANSFER {'TO' if amt < 0 else 'FROM'} CHECKING x{spec['operating_last4']}"),
            "interest_income": "INTEREST CREDIT",
        }
        return m[lab]
    raise ValueError(style)


def render_bank_h(sim, upload, rng):
    spec = sim.spec
    w = _bank_window(upload)
    accounts = ["operating", "savings"] if spec.get("savings_in_export") else ["operating"]
    bal = {"operating": sim.extra["opening_operating"], "savings": sim.extra["opening_savings"]}
    if "bank_memos" not in sim.extra:
        mrng = np.random.default_rng(spec["seed"] + 4242)
        sim.extra["bank_memos"] = [memo_h(spec["bank_style"], r, spec, mrng) for r in sim.bank.to_dict("records")]
    lines = []
    for k, r in enumerate(sim.bank.to_dict("records")):
        bal[r["account"]] = round(bal[r["account"]] + r["amount"], 2)
        r["balance"], r["memo"] = bal[r["account"]], sim.extra["bank_memos"][k]
        if r["account"] in accounts and in_window(r["date"], w):
            r["is_duplicate"] = upload == 2 and r["date"] < UPLOAD_2[0]
            lines.append(r)
    lay = spec["bank_layout"]
    eu = lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if lay == "L5":   # semicolon, decimal comma, dd-mm-yyyy
        header = ["Booking date", "Value date", "Counterparty", "Description", "Amount", "Currency",
                  "Balance after booking"]
        rows = [[l["date"].strftime("%d-%m-%Y"), l["date"].strftime("%d-%m-%Y"), disp(l["cp"]).upper()[:30],
                 l["memo"], eu(l["amount"]), "EUR", eu(l["balance"])] for l in lines]
        cmap = {"date": "Booking date", "description": "Description", "amount": "Amount",
                "balance": "Balance after booking"}
        return [RenderedFile(f"rekening_{upload}.csv", "csv", "bank", cmap, header, rows, delimiter=";",
                             row_truth=_bank_truth(lines), meta={"date_format": "dd-mm-yyyy"})]
    if lay == "L6":   # unsigned amounts, DR/CR column, both accounts
        header = ["Date", "Account", "Transaction Type", "Description", "Amount", "Balance"]
        rows = [[fmt_date(l["date"], "mdy"), ("CHK" if l["account"] == "operating" else "SAV") + " x" +
                 (spec["operating_last4"] if l["account"] == "operating" else spec["savings_last4"]),
                 "CR" if l["amount"] > 0 else "DR", l["memo"], money(abs(l["amount"])), money(l["balance"])]
                for l in lines]
        cmap = {"date": "Date", "description": "Description", "amount": "Amount", "balance": "Balance",
                "account": "Account"}
        return [RenderedFile(f"history_{upload}.csv", "csv", "bank", cmap, header, rows, row_truth=_bank_truth(lines),
                             meta={"date_format": "mdy", "amounts": "unsigned, direction in Transaction Type"})]
    if lay == "L7":   # neobank: written dates, counterparty column
        header = ["Date", "Counterparty", "Memo", "Amount", "Running Balance", "Category"]
        rows = [[fmt_date(l["date"], "mon_d_y"), disp(l["cp"]), l["memo"], money(l["amount"]), money(l["balance"]),
                 ""] for l in lines]
        cmap = {"date": "Date", "description": "Memo", "amount": "Amount", "balance": "Running Balance"}
        return [RenderedFile(f"account_activity_{upload}.csv", "csv", "bank", cmap, header, rows,
                             row_truth=_bank_truth(lines), meta={"date_format": "mon_d_y"})]
    raise ValueError(lay)


def render_card_h(sim, upload, rng):
    spec = sim.spec
    if spec["card_layout"] != "K4":
        return render_card(sim, upload, rng)
    w = (CARD_UPLOAD_1_START, UPLOAD_1[1]) if upload == 1 else (UPLOAD_2[0] - timedelta(days=5), UPLOAD_2[1])
    if "card_desc" not in sim.extra:
        crng = np.random.default_rng(spec["seed"] + 5151)
        sim.extra["card_desc"] = ["PAYMENT RECEIVED THANK YOU" if l == "card_payment_received" else card_desc(c, crng)
                                  for l, c in zip(sim.card["label"], sim.card["cp"])]
    allc = sim.card.copy()
    allc["desc"] = sim.extra["card_desc"]
    lines = allc[[in_window(d, w) for d in allc["date"]]].to_dict("records")
    eu = lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    cat = {"ad_spend": "Marketing", "software_opex": "Software", "travel_other": "Travel",
           "shipping_supplies": "Supplies", "card_payment_received": "Payment"}
    header = ["Transaction date", "Merchant", "Category", "Amount (EUR)"]
    rows = [[l["date"].strftime("%d-%m-%Y"), l["desc"], cat[l["label"]], eu(l["amount"])] for l in lines]
    truth = [dict(label=l["label"], amount=round(l["amount"], 2), date=l["date"].isoformat(),
                  is_duplicate=bool(upload == 2 and l["date"] < UPLOAD_2[0])) for l in lines]
    cmap = {"date": "Transaction date", "description": "Merchant", "amount": "Amount (EUR)"}
    return [RenderedFile(f"creditcard_{upload}.csv", "csv", "card", cmap, header, rows, delimiter=";",
                         row_truth=truth, meta={"charge_sign": "positive", "date_format": "dd-mm-yyyy"})]


def render_orders_h(sim, upload, rng):
    if sim.spec["orders_layout"] != "O2b":
        return render_orders(sim, upload, rng)
    sim.spec["orders_layout"] = "O2"
    out = render_orders(sim, upload, rng)
    sim.spec["orders_layout"] = "O2b"
    for rf in out:
        rf.header = ["Date", "Orders", "Gross Sales", "Discounts", "Returns", "Net Sales", "Shipping", "Taxes",
                     "Total Sales"]
        rf.column_map = {"day": "Date", "orders": "Orders", "gross_sales": "Gross Sales", "discounts": "Discounts",
                         "returns": "Returns", "net_sales": "Net Sales", "shipping": "Shipping", "taxes": "Taxes",
                         "total_sales": "Total Sales"}
        rf.name = f"sales_report_{upload}.csv"
    return out


def render_payouts_h(sim, upload, rng):
    spec = sim.spec
    if spec["payouts_layout"] != "P2":
        return render_payouts(sim, upload, rng)
    w = UPLOAD_1 if upload == 1 else UPLOAD_2
    pid = dict(zip(sim.payouts["payout_date"], sim.payouts["payout_id"]))
    rows = []
    o = sim.orders[[in_window(d, w) for d in sim.orders["payout_date"]]]
    for r in o.itertuples():
        rows.append((r.created_at.date(), ["", "charge", r.order_id, "visa", "paid", r.payout_date.isoformat(),
                                           pid[r.payout_date], money(r.total), money(r.fee), money(r.total - r.fee)]))
    rf = sim.refunds[[in_window(d, w) for d in sim.refunds["payout_date"]]]
    for r in rf.itertuples():
        amt = r.amount if r.kind == "refund" else r.amount + 15.0
        rows.append((r.refund_date, ["", r.kind, r.order_id, "visa", "paid", r.payout_date.isoformat(),
                                     pid[r.payout_date], money(-amt), "0.00", money(-amt)]))
    rows.sort(key=lambda x: x[0])
    body = []
    for d, row in rows:
        row[0] = d.isoformat()
        body.append(row)
    header = ["Transaction Date", "Type", "Order", "Card Brand", "Payout Status", "Payout Date", "Payout ID",
              "Amount", "Fee", "Net"]
    cmap = {"payout_date": "Payout Date", "net": "Net", "charges": "Amount", "payout_id": "Payout ID",
            "status": "Payout Status"}
    return [RenderedFile(f"payment_transactions_{upload}.csv", "csv", "payouts", cmap, header, body,
                         meta={"grain": "one row per transaction, not per payout"})]


def add_paypal(sim):
    if not sim.spec.get("paypal"):
        return
    rng = np.random.default_rng(sim.spec["seed"] + 77)
    rows = []
    for d in daterange(date(2026, 6, 2), date(2026, 10, 25)):
        if d.weekday() == 1:
            rows.append(dict(date=d, account="operating", amount=round(float(rng.uniform(0.8, 1.2)) *
                                                                       sim.spec["annual_rev"] * 0.06 / 52, 2),
                             label="processor_payout", cp="paypal", detail={}))
    b = pd.concat([sim.bank, pd.DataFrame(rows)], ignore_index=True)
    sim.bank = b.sort_values("date", kind="stable").reset_index(drop=True)


RENDERERS_H = [render_bank_h, render_card_h, render_orders_h, render_payouts_h, render_amazon, render_faire,
               render_coa]


def main():
    raw_root = HERE / "raw"
    truth_root = ROOT / "evals" / "ground_truth_holdout"
    raw_root.mkdir(parents=True, exist_ok=True)
    truth_root.mkdir(parents=True, exist_ok=True)
    for i, spec in enumerate(HOLDOUT_BRANDS):
        spec = fill_defaults(dict(spec), 20 + i)
        m = write_brand(spec, raw_root, truth_root, coa_pools=HOLDOUT_COA, renderers=RENDERERS_H, post_sim=add_paypal)
        n = sum(v["n_rows"] for v in m["files"].values())
        print(f"  {spec['slug']:<20} split={spec['split']:<7} files={len(m['files']):>2} rows={n:>6}")


if __name__ == "__main__":
    main()
