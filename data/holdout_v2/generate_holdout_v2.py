"""
Holdout v2. Written after the second freeze (evals/FREEZE_v2.json, committed on its
own before this file existed). Nothing under onboard/ or models/ changes after
that freeze; evals/run_holdout_v2.py refuses to run if anything did.

Why a second holdout: the first one exposed four bugs, which I fixed after seeing
it, so the current code had no blind number. This set is that number.

Three brands, each mixing formats the pipeline has not seen:

  harbor-and-hive   bank export with "Withdrawals" / "Deposits" columns and
                    year-first dates (2026/10/07), a new terse memo style, an
                    Amazon reserve, and a card export that splits charges and
                    payments into Debit and Credit columns. I knew when writing
                    this that the card schema has one amount column; real card
                    exports do this, so it is in the test.
  vale-street-tea   newest-first bank export with ISO dates and plain-English
                    memos, transaction-level Shopify payouts, order totals
                    repeated on every line item, a credit line, a direct
                    wholesale customer, and a chart of accounts with no numbers.
  fieldnote-paper   fintech export with both accounts and no running balance,
                    dates written "Oct 7, 2026", short coded memos, and a card
                    export with unpadded dates.

All three use a chart of accounts with names written for this set.

Built by Avinash Rayudu. All brands, names and numbers are invented.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent
sys.path.insert(0, str(DATA))
sys.path.insert(0, str(DATA / "holdout"))

from generate_brands import fill_defaults, soft, write_brand                      # noqa: E402
from render import (RenderedFile, _bank_truth, _bank_window, card_desc, disp, in_window, money, render_amazon,  # noqa: E402
                    render_bank, render_card, render_coa, render_faire, render_orders, rnd_digits)
from generate_holdout import render_payouts_h                                    # noqa: E402
from render import render_payouts                                                # noqa: E402
from sim import CARD_UPLOAD_1_START, UPLOAD_1, UPLOAD_2                          # noqa: E402
from datetime import timedelta                                                   # noqa: E402

ROOT = DATA.parent

COA_V2 = {
    "bank_account": (["Checking - Main", "Operating Account 2231", "Reserve Savings", "Cash at Bank"], "Bank"),
    "credit_card_account": (["Corporate Card Payable", "Visa Business Card", "Amex Liability"], "Credit Card"),
    "loan_account": (["Revolving Credit Facility", "Working Capital Loan"], "Long Term Liabilities"),
    "sales_tax_payable": (["Sales & Use Tax Payable", "Tax Collected Payable"], "Other Current Liabilities"),
    "revenue_dtc": (["E-commerce Sales", "Website Revenue", "Shopify Sales Income"], "Income"),
    "revenue_marketplace": (["Amazon Sales", "Marketplace Revenue"], "Income"),
    "revenue_wholesale": (["Retail Partner Sales", "Wholesale Income", "B2B Revenue"], "Income"),
    "refunds_returns": (["Customer Returns", "Refunds & Allowances"], "Income"),
    "cogs_product": (["Inventory Purchases", "Cost of Product Sold", "Raw Goods"], "Cost of Goods Sold"),
    "cogs_freight_duty": (["Import Freight", "Customs & Duty", "Landed Cost - Freight"], "Cost of Goods Sold"),
    "fulfillment_3pl": (["Warehouse & Pick-Pack", "3PL Fees", "Outbound Fulfillment"], "Cost of Goods Sold"),
    "merchant_fees": (["Payment Processing", "Merchant Account Fees", "Shopify Payments Fees"], "Expenses"),
    "advertising": (["Digital Advertising", "Paid Social", "Search Ads", "Marketing Spend"], "Expenses"),
    "payroll": (["Payroll Expense", "Salaries & Wages", "Payroll Taxes - Employer"], "Expenses"),
    "software": (["SaaS Subscriptions", "Apps & Software", "Technology"], "Expenses"),
    "rent": (["Office & Studio Rent", "Rent Expense", "Facility Lease"], "Expenses"),
    "travel_meals": (["Business Travel", "Meals", "Travel & Meals"], "Expenses"),
    "shipping_supplies": (["Packaging Supplies", "Postage & Labels", "Shipping Materials Expense"], "Expenses"),
    "interest_expense": (["Interest on Credit Facility", "Loan Interest"], "Other Expense"),
    "other_opex": (["Professional Fees", "Insurance Expense", "Office Supplies", "Dues & Subscriptions",
                    "Bank Service Charges"], "Expenses"),
}

HOLDOUT_V2_BRANDS = [
    dict(slug="harbor-and-hive", name="Harbor & Hive", split="holdout_v2", seed=2121, currency="USD",
         annual_rev=5.8e6, shares=dict(shopify=0.70, amazon=0.15, faire=0.15), aov=84, tax_rate=0.0625,
         payroll_provider="Paylocity", suppliers=["Saltmeadow Apiaries", "Corbel Glass Co"],
         forwarder="Tidemark Freight", threepl="Anchorline Fulfillment", landlord="Pier Nine Partners LLC",
         tax_agency="MA DOR", card_issuer="Northbridge", lender=None,
         faire_retailers=["Beacon Hill Pantry", "Coastline Mercantile", "Two Rivers Market"],
         ad_platforms=[("meta", 0.58, 3500.0), ("google", 0.32, 2000.0), ("pinterest", 0.10, 800.0)],
         card_software=soft(["klaviyo", "shopify_sub", "gorgias", "gsuite"], [3, 9, 15, 22]),
         travel_merchants=["delta", "uber", "bluedoor"], supply_merchants=["uline", "stamps"],
         amazon_reserve=True,
         bank_style="H", bank_layout="L8", card_layout="K5", card_date="mdy", orders_layout="O1",
         payouts_layout="P1b", amazon_layout="A2", faire_layout="F2", coa_layout="C2",
         coa_added_upload2=dict(number=6990, name="Farmers Market Fees", type="Expenses", label="other_opex")),
    dict(slug="vale-street-tea", name="Vale Street Tea", split="holdout_v2", seed=2222, currency="USD",
         annual_rev=3.9e6, shares=dict(shopify=0.65, amazon=0.20), aov=47, tax_rate=0.08,
         payroll_provider="Gusto", suppliers=["Highmist Tea Gardens", "Wren Tin & Can"],
         forwarder="Orchard Line Logistics", threepl="Keel Fulfillment", landlord="Vale Street Realty",
         tax_agency="PA DEPT OF REVENUE", card_issuer="Larchmont", lender="Bramble Capital",
         direct_retailers=["Cedar & Sage Grocers", "Old Mill Market"],
         ad_platforms=[("meta", 0.65, 2500.0), ("google", 0.35, 1500.0)],
         card_software=soft(["klaviyo", "shopify_sub", "canva", "notion"], [4, 10, 16, 23]),
         travel_merchants=["lyft", "corner"], supply_merchants=["papermart", "pirateship"],
         bank_style="I", bank_layout="L1", bank_date="iso", card_layout="K1", card_date="iso",
         orders_layout="O3", payouts_layout="P2", amazon_layout="A1", coa_layout="C3",
         coa_added_upload2=dict(number=0, name="Marketing:Sampling Events", type="Expenses", label="advertising")),
    dict(slug="fieldnote-paper", name="Fieldnote Paper Co", split="holdout_v2", seed=2323, currency="USD",
         annual_rev=2.4e6, shares=dict(shopify=0.75, faire=0.25), aov=39, tax_rate=0.07,
         payroll_provider="Justworks", suppliers=["Mulberry Mill Paper", "Inkline Printworks"],
         forwarder="Cobble Freight", threepl="Paperweight Logistics", landlord="Foundry Row LLC",
         tax_agency="MN DEPT OF REVENUE", card_issuer="Pinecone", lender=None,
         faire_retailers=["Stationery Loft", "Northern Lights Books", "The Desk Drawer"],
         ad_platforms=[("meta", 0.55, 1200.0), ("google", 0.25, 800.0), ("pinterest", 0.20, 600.0)],
         card_software=soft(["klaviyo", "shopify_sub", "slack"], [6, 13, 20]),
         travel_merchants=["uber", "sq_coffee"], supply_merchants=["uline", "boxco"],
         bank_style="J", bank_layout="L3", bank_date="mon_d_y", savings_in_export=True, card_layout="K2",
         card_date="mdy_nopad", card_member="J OKAFOR", orders_layout="O1", payouts_layout="P1",
         faire_layout="F1", coa_layout="C1",
         coa_added_upload2=dict(number=6995, name="Pop-up Shop Costs", type="Expenses", label="other_opex")),
]


# --------------------------------------------------------------------------- memo styles written for this set
def memo_v2(style, line, spec, rng):
    lab, cp, amt = line["label"], line["cp"], line["amount"]
    d = line["date"]
    CP = disp(cp).upper()
    det = line["detail"] if isinstance(line["detail"], dict) else {}
    part, acct = det.get("part"), line.get("account", "operating")
    sav4, op4 = spec["savings_last4"], spec["operating_last4"]
    if style == "H":     # terse, truncated, core-banking style
        m = {
            "processor_payout": f"ACH DEP SHOPIFY {rnd_digits(rng, 6)}",
            "marketplace_payout": f"ACH DEP AMZN MKTP US {rnd_digits(rng, 6)}",
            "wholesale_payout": f"ACH DEP FAIRE WHSL {rnd_digits(rng, 6)}",
            "payroll": f"ACH WD {CP[:12]} {'NET' if part == 'net' else 'TAX'}",
            "inventory_purchase": f"WIRE WD {CP[:16]}",
            "bank_fee": "SVC CHG WIRE",
            "freight_duty": "ACH WD CBP DUTY" if cp == "customs" else f"ACH WD {CP[:16]}",
            "rent": f"ACH WD {CP[:16]}", "fulfillment_3pl": f"ACH WD {CP[:16]}",
            "software_opex": "ACH WD INTUIT QBO", "sales_tax": f"ACH WD {CP[:16]}",
            "card_payment": f"ACH WD {CP[:10]} CARD PMT", "vendor_refund": f"ACH DEP {CP[:16]}",
            "own_account_transfer": (f"XFER {'TO' if amt < 0 else 'FR'} SAV {sav4}" if acct == "operating"
                                     else f"XFER {'TO' if amt < 0 else 'FR'} CHK {op4}"),
            "interest_income": "INT EARNED",
        }
        return m[lab]
    if style == "I":     # plain English, lower case
        m = {
            "processor_payout": "shopify payout",
            "marketplace_payout": "amazon seller payout",
            "wholesale_receipt": f"payment received from {disp(cp).lower()}",
            "payroll": f"{disp(cp).lower()} {'payroll' if part == 'net' else 'payroll taxes'}",
            "inventory_purchase": f"wire to {disp(cp).lower()}",
            "bank_fee": "wire transfer fee",
            "freight_duty": "us customs duty payment" if cp == "customs" else f"payment to {disp(cp).lower()}",
            "rent": f"rent to {disp(cp).lower()}", "fulfillment_3pl": f"payment to {disp(cp).lower()}",
            "software_opex": "quickbooks subscription", "sales_tax": f"sales tax to {disp(cp).lower()}",
            "card_payment": f"{disp(cp).lower()} card payment", "vendor_refund": f"refund from {disp(cp).lower()}",
            "financing_draw": f"loan funds from {disp(cp).lower()}",
            "financing_repayment": f"loan payment to {disp(cp).lower()}",
            "interest_expense": f"loan interest {disp(cp).lower()}",
            "own_account_transfer": f"transfer {'to' if amt < 0 else 'from'} savings",
            "interest_income": "interest",
        }
        return m[lab]
    if style == "J":     # short coded memos
        code = rnd_digits(rng, 4)
        m = {
            "processor_payout": f"SHPFY PAYOUT {code}",
            "wholesale_payout": f"FAIRE.COM {code}",
            "payroll": f"{disp(cp)[:8].upper()} PR {'NET' if part == 'net' else 'TX'} {code}",
            "inventory_purchase": f"INTL WIRE {disp(cp)[:14].upper()}",
            "bank_fee": "INTL WIRE FEE",
            "freight_duty": "CBP DUTY" if cp == "customs" else f"PMT {disp(cp)[:14].upper()}",
            "rent": f"PMT {disp(cp)[:14].upper()}", "fulfillment_3pl": f"PMT {disp(cp)[:14].upper()}",
            "software_opex": "INTUIT QB", "sales_tax": f"PMT {disp(cp)[:14].upper()}",
            "card_payment": f"{disp(cp)[:10].upper()} AUTOPAY", "vendor_refund": f"RFND {disp(cp)[:14].upper()}",
            "own_account_transfer": f"BOOK XFER {'OUT' if amt < 0 else 'IN'}",
            "interest_income": "INTEREST",
        }
        return m[lab]
    raise ValueError(style)


def _memos(sim):
    if "bank_memos" not in sim.extra:
        mrng = np.random.default_rng(sim.spec["seed"] + 4242)
        sim.extra["bank_memos"] = [memo_v2(sim.spec["bank_style"], r, sim.spec, mrng)
                                   for r in sim.bank.to_dict("records")]


def render_bank_v2(sim, upload, rng):
    spec = sim.spec
    _memos(sim)
    if spec["bank_layout"] != "L8":
        return render_bank(sim, upload, rng)          # existing layout, new memo style from _memos
    w = _bank_window(upload)
    bal = {"operating": sim.extra["opening_operating"], "savings": sim.extra["opening_savings"]}
    lines = []
    for k, r in enumerate(sim.bank.to_dict("records")):
        bal[r["account"]] = round(bal[r["account"]] + r["amount"], 2)
        r["balance"], r["memo"] = bal[r["account"]], sim.extra["bank_memos"][k]
        if r["account"] == "operating" and in_window(r["date"], w):
            r["is_duplicate"] = upload == 2 and r["date"] < UPLOAD_2[0]
            lines.append(r)
    header = ["Posted Date", "Check Number", "Transaction Description", "Withdrawals", "Deposits", "Balance"]
    rows = [[l["date"].strftime("%Y/%m/%d"), "", l["memo"],
             money(-l["amount"], "comma") if l["amount"] < 0 else "",
             money(l["amount"], "comma") if l["amount"] > 0 else "", money(l["balance"], "comma")] for l in lines]
    cmap = {"date": "Posted Date", "description": "Transaction Description", "debit": "Withdrawals",
            "credit": "Deposits", "balance": "Balance"}
    return [RenderedFile(f"checking_history_{upload}.csv", "csv", "bank", cmap, header, rows,
                         row_truth=_bank_truth(lines), meta={"order": "oldest_first", "date_format": "y/m/d"})]


def render_card_v2(sim, upload, rng):
    spec = sim.spec
    if spec["card_layout"] != "K5":
        return render_card(sim, upload, rng)
    w = (CARD_UPLOAD_1_START, UPLOAD_1[1]) if upload == 1 else (UPLOAD_2[0] - timedelta(days=5), UPLOAD_2[1])
    if "card_desc" not in sim.extra:
        crng = np.random.default_rng(spec["seed"] + 5151)
        sim.extra["card_desc"] = ["ONLINE PAYMENT - THANK YOU" if l == "card_payment_received" else card_desc(c, crng)
                                  for l, c in zip(sim.card["label"], sim.card["cp"])]
    allc = sim.card.copy()
    allc["desc"] = sim.extra["card_desc"]
    lines = allc[[in_window(d, w) for d in allc["date"]]].to_dict("records")
    header = ["Transaction Date", "Posted Date", "Card No.", "Description", "Category", "Debit", "Credit"]
    cat = {"ad_spend": "Other Services", "software_opex": "Internet", "travel_other": "Airfare",
           "shipping_supplies": "Merchandise", "card_payment_received": "Payment/Credit"}
    rows = []
    for l in lines:
        charge = l["amount"]       # > 0 is a charge, < 0 is the payment received
        rows.append([l["date"].strftime("%Y-%m-%d"), (l["date"] + timedelta(days=1)).strftime("%Y-%m-%d"),
                     spec["card_last5"][-4:], l["desc"], cat[l["label"]],
                     money(charge) if charge > 0 else "", money(-charge) if charge < 0 else ""])
    truth = [dict(label=l["label"], amount=round(l["amount"], 2), date=l["date"].isoformat(),
                  is_duplicate=bool(upload == 2 and l["date"] < UPLOAD_2[0])) for l in lines]
    cmap = {"date": "Transaction Date", "description": "Description", "debit": "Debit", "credit": "Credit"}
    return [RenderedFile(f"card_transactions_{upload}.csv", "csv", "card", cmap, header, rows, row_truth=truth,
                         meta={"charge_sign": "Debit column positive, payments in Credit column"})]


def render_payouts_v2(sim, upload, rng):
    return render_payouts_h(sim, upload, rng) if sim.spec["payouts_layout"] == "P2" else render_payouts(sim, upload, rng)


RENDERERS_V2 = [render_bank_v2, render_card_v2, render_orders, render_payouts_v2, render_amazon, render_faire,
                render_coa]


def main():
    raw_root = HERE / "raw"
    truth_root = ROOT / "evals" / "ground_truth_holdout_v2"
    raw_root.mkdir(parents=True, exist_ok=True)
    truth_root.mkdir(parents=True, exist_ok=True)
    for i, spec in enumerate(HOLDOUT_V2_BRANDS):
        spec = fill_defaults(dict(spec), 30 + i)
        m = write_brand(spec, raw_root, truth_root, coa_pools=COA_V2, renderers=RENDERERS_V2)
        n = sum(v["n_rows"] for v in m["files"].values())
        print(f"  {spec['slug']:<20} split={spec['split']:<10} files={len(m['files']):>2} rows={n:>6}")


if __name__ == "__main__":
    main()
