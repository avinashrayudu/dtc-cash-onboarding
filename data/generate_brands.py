"""
Generates the 10 development brands.

Writes, for each brand:
  data/raw/<brand>/brand.yaml          what an implementation lead learns on the kickoff call
  data/raw/<brand>/upload_1/*          the first batch of exports (Jul 1 to Aug 31, 2026)
  data/raw/<brand>/upload_2/*          the next batch (Sep 1 to Oct 25, 2026; bank and card overlap upload 1)
  evals/ground_truth/<brand>/...       the truth, used only by the simulated reviewer and the evals

Brands 1-7 are the training split. Brands 8-10 are a development split the
classifier never trains on. All brands, names and numbers are invented.

Built by Avinash Rayudu.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from sim import simulate, UPLOAD_1, UPLOAD_2, RECEIPT_LABELS   # noqa: E402
from render import RENDERERS, write_file                       # noqa: E402

ROOT = HERE.parent

COA_POOLS = {
    "bank_account": (["Operating Checking", "Business Checking", "Checking", "Savings", "High Yield Savings",
                      "Money Market", "Operating Account", "Reserve Savings", "Cash - Operating", "Cash - Savings"],
                     "Bank"),
    "credit_card_account": (["Business Credit Card", "Card Payable", "Corporate Card", "Company Card",
                             "Credit Card - Business"], "Credit Card"),
    "loan_account": (["Line of Credit", "Revolving Credit Facility", "Loan Payable", "Working Capital Loan",
                      "Notes Payable"], "Long Term Liabilities"),
    "sales_tax_payable": (["Sales Tax Payable", "Sales Tax Agency Payable", "Sales Tax Liability",
                           "Tax Payable - Sales"], "Other Current Liabilities"),
    "revenue_dtc": (["Shopify Sales", "Sales - Website", "DTC Revenue", "Online Store Sales", "E-commerce Sales",
                     "Sales:Shopify", "Revenue - Direct to Consumer"], "Income"),
    "revenue_marketplace": (["Amazon Sales", "Sales - Amazon", "Marketplace Revenue", "Sales:Amazon",
                             "Revenue - Amazon FBA"], "Income"),
    "revenue_wholesale": (["Wholesale Sales", "Sales - Wholesale", "Faire Sales", "Revenue - Retail Partners",
                           "B2B Sales"], "Income"),
    "refunds_returns": (["Refunds & Returns", "Sales Returns and Allowances", "Customer Refunds", "Returns"],
                        "Income"),
    "cogs_product": (["Cost of Goods Sold", "COGS - Product", "Product Cost", "Inventory Cost",
                      "Cost of Sales - Materials"], "Cost of Goods Sold"),
    "cogs_freight_duty": (["Freight In", "Inbound Freight & Duties", "Customs & Duties", "COGS - Freight",
                           "Import Duties"], "Cost of Goods Sold"),
    "fulfillment_3pl": (["Fulfillment Fees", "3PL Fees", "Warehousing & Fulfillment", "Pick and Pack",
                         "Outbound Shipping & Fulfillment"], "Cost of Goods Sold"),
    "merchant_fees": (["Merchant Fees", "Payment Processing Fees", "Shopify Payments Fees",
                       "Credit Card Processing", "Marketplace Fees"], "Expenses"),
    "advertising": (["Advertising", "Paid Social", "Marketing:Meta Ads", "Marketing:Google Ads",
                     "Digital Advertising", "Ads - Facebook/IG", "Paid Search", "Marketing - Paid Media"], "Expenses"),
    "payroll": (["Payroll Wages", "Salaries & Wages", "Payroll Taxes", "Employee Benefits", "Payroll:Wages",
                 "Payroll:Employer Taxes", "Contract Labor"], "Expenses"),
    "software": (["Software & Subscriptions", "SaaS Tools", "Software:Klaviyo", "Technology Expense",
                  "Subscriptions", "Apps & Software"], "Expenses"),
    "rent": (["Rent", "Office Rent", "Rent or Lease", "Studio Rent", "Occupancy"], "Expenses"),
    "travel_meals": (["Travel", "Meals & Entertainment", "Travel & Meals", "Business Travel", "Meals"], "Expenses"),
    "shipping_supplies": (["Shipping Supplies", "Packaging", "Postage & Delivery", "Packaging Materials",
                           "Shipping & Packaging"], "Expenses"),
    "interest_expense": (["Interest Expense", "Loan Interest", "Interest Paid", "Finance Charges"], "Other Expense"),
    "other_opex": (["Office Supplies", "Professional Fees", "Bank Charges", "Insurance", "Legal & Accounting",
                    "Miscellaneous Expense", "Repairs & Maintenance", "Utilities"], "Expenses"),
}

SOFTWARE = {"klaviyo": 690, "shopify_sub": 399, "canva": 119.99, "slack": 87.50, "gorgias": 300,
            "notion": 96, "recharge": 99, "gsuite": 144, "figma": 45, "triplewhale": 279}


def soft(keys, days):
    return [(k, d, SOFTWARE[k]) for k, d in zip(keys, days)]


BRANDS = [
    dict(slug="fernwood-goods", name="Fernwood Goods", split="train", seed=101, currency="USD", annual_rev=8.4e6,
         shares=dict(shopify=0.80, amazon=0.08, faire=0.12), aov=118, tax_rate=0.08875,
         payroll_provider="Gusto", suppliers=["Kestrel Knitworks Ltd", "Halden Textile Co"],
         forwarder="Harborline Freight", threepl="ShipNest 3PL", landlord="Navy Street Holdings",
         tax_agency="NYS DTF", card_issuer="Summit", lender=None,
         faire_retailers=["Greenpoint Provisions", "Larkspur General Store", "The Willow Shop"],
         ad_platforms=[("meta", 0.62, 5000.0), ("google", 0.30, 2500.0), ("tiktok", 0.08, 1000.0)],
         card_software=soft(["klaviyo", "shopify_sub", "gorgias", "slack"], [3, 7, 12, 19]),
         travel_merchants=["uber", "delta", "bluedoor"], supply_merchants=["uline", "pirateship"],
         bank_style="A", bank_layout="L1", bank_date="mdy", card_layout="K2", card_date="mdy",
         card_member="A RIVERA", orders_layout="O1", payouts_layout="P1", amazon_layout="A1", amazon_reserve=True,
         faire_layout="F1", coa_layout="C1",
         coa_added_upload2=dict(number=6910, name="Trade Show Expenses", type="Expenses", label="other_opex")),
    dict(slug="lark-and-pine", name="Lark & Pine Candle Co", split="train", seed=202, currency="USD",
         annual_rev=3.2e6, shares=dict(shopify=0.70, faire=0.30), aov=64, tax_rate=0.06625,
         payroll_provider="ADP", suppliers=["Pinecrest Wax Supply", "Ostrava Glassworks"],
         forwarder="Bluewake Logistics", threepl="Packriver Fulfillment", landlord="Gowanus Lofts LLC",
         tax_agency="NJ DIV OF TAXATION", card_issuer="Meridian", lender="Kettle Lending",
         faire_retailers=["Hudson Mercantile", "Fieldhouse Goods", "Carver & Main", "Bluebell Boutique"],
         ad_platforms=[("meta", 0.70, 2000.0), ("google", 0.30, 1000.0)],
         card_software=soft(["klaviyo", "shopify_sub", "canva"], [2, 9, 21]),
         travel_merchants=["lyft", "corner"], supply_merchants=["papermart", "boxco", "uline"],
         bank_style="B", bank_layout="L2", bank_date="mdy", card_layout="K1", card_date="mdy",
         orders_layout="O3", payouts_layout="P1b", faire_layout="F2", coa_layout="C2",
         coa_added_upload2=dict(number=6920, name="Photography", type="Expenses", label="other_opex")),
    dict(slug="tidewater-swim", name="Tidewater Swim", split="train", seed=303, currency="USD", annual_rev=5.1e6,
         shares=dict(shopify=0.85, amazon=0.15), aov=96, tax_rate=0.0725,
         payroll_provider="Rippling", suppliers=["Baywater Swim Mfg"],
         forwarder="Meridian Cargo", threepl="Boxline Logistics", landlord="Red Hook Studios",
         tax_agency="CA CDTFA", card_issuer="Keystone", lender=None, meta_direct_debit=True,
         ad_platforms=[("meta", 0.55, 4000.0), ("google", 0.30, 2000.0), ("tiktok", 0.15, 1500.0)],
         card_software=soft(["klaviyo", "shopify_sub", "notion", "triplewhale"], [4, 8, 14, 25]),
         travel_merchants=["uber", "jetblue", "marriott"], supply_merchants=["stamps", "uline"],
         bank_style="C", bank_layout="L3", bank_date="iso", savings_in_export=True, card_layout="K3",
         card_date="mdy", orders_layout="O2", orders_money="paren", payouts_layout="P1", amazon_layout="A2",
         coa_layout="C3",
         coa_added_upload2=dict(number=0, name="Marketing:Influencer Fees", type="Expenses", label="advertising")),
    dict(slug="copperleaf-tea", name="Copperleaf Tea", split="train", seed=404, currency="USD", annual_rev=2.6e6,
         shares=dict(shopify=0.60, amazon=0.25, faire=0.15), aov=52, tax_rate=0.0625,
         payroll_provider="Justworks", suppliers=["Grayson Tea Estates", "Vellum Paper Mills"],
         forwarder="Crestway Forwarding", threepl="Fulcrum Fulfillment", landlord="Bushwick Works LLC",
         tax_agency="TX COMPTROLLER", card_issuer="Ashford", lender=None,
         faire_retailers=["Oak Hollow Market", "Wharf Street Supply"],
         direct_retailers=["Mapleton Gifts", "Hollow Pine Grocers"],
         ad_platforms=[("meta", 0.60, 1500.0), ("google", 0.40, 1000.0)],
         card_software=soft(["klaviyo", "shopify_sub", "gsuite"], [5, 11, 17]),
         travel_merchants=["uber", "sq_coffee"], supply_merchants=["uline", "stamps"],
         bank_style="D", bank_layout="L4", bank_date="mdy_nopad", savings_in_export=True, card_layout="K1",
         card_date="mdy", orders_layout="O1", payouts_layout="P1b", amazon_layout="A1", faire_layout="F1",
         coa_layout="C1",
         coa_added_upload2=dict(number=6930, name="Insurance - Product Liability", type="Expenses",
                                label="other_opex")),
    dict(slug="north-arc-outdoor", name="North Arc Outdoor", split="train", seed=505, currency="USD",
         annual_rev=6.3e6, shares=dict(shopify=0.90, amazon=0.10), aov=142, tax_rate=0.08875,
         payroll_provider="Gusto", suppliers=["Corvid Outdoor Gear Ltd", "Lindqvist Fibers"],
         forwarder="Tidelink Freight", threepl="Dockside 3PL", landlord="Sunset Park Realty",
         tax_agency="NYS DTF", card_issuer="Granite", lender="Ridgeway Capital",
         ad_platforms=[("meta", 0.58, 5000.0), ("google", 0.42, 3000.0)],
         card_software=soft(["klaviyo", "shopify_sub", "figma", "slack", "gorgias"], [1, 6, 13, 20, 26]),
         travel_merchants=["delta", "uber", "marriott", "corner"], supply_merchants=["uline", "boxco"],
         bank_style="A", bank_layout="L1", bank_date="mdy", card_layout="K3", card_date="mdy",
         orders_layout="O3", payouts_layout="P1", amazon_layout="A2", amazon_ads_in_settlement=True,
         coa_layout="C2",
         coa_added_upload2=dict(number=6940, name="Sponsorships", type="Expenses", label="advertising")),
    dict(slug="marigold-skin", name="Marigold Skin", split="train", seed=606, currency="USD", annual_rev=4.4e6,
         shares=dict(shopify=0.75, faire=0.25), aov=72, tax_rate=0.07,
         payroll_provider="Paychex", suppliers=["Sorrel Cosmetics Lab", "Altamira Packaging Co"],
         forwarder="Northstar Shipping", threepl="Parcelworks", landlord="Dumbo Commons LLC",
         tax_agency="NJ DIV OF TAXATION", card_issuer="Summit", lender=None,
         faire_retailers=["Bluebell Boutique", "Carver & Main", "Larkspur General Store"],
         ad_platforms=[("meta", 0.65, 3000.0), ("google", 0.20, 1500.0), ("pinterest", 0.15, 800.0)],
         card_software=soft(["klaviyo", "shopify_sub", "recharge", "canva"], [3, 10, 16, 24]),
         travel_merchants=["lyft", "bluedoor", "jetblue"], supply_merchants=["papermart", "pirateship"],
         bank_style="B", bank_layout="L2", bank_date="mdy", card_layout="K2", card_date="mdy",
         card_member="J OKAFOR", orders_layout="O2", payouts_layout="P1", faire_layout="F1", coa_layout="C3",
         coa_added_upload2=dict(number=0, name="Lab Testing", type="Expenses", label="other_opex")),
    dict(slug="bramble-pet", name="Bramble Pet Supply", split="train", seed=707, currency="USD", annual_rev=3.8e6,
         shares=dict(shopify=0.70, amazon=0.30), aov=58, tax_rate=0.06,
         payroll_provider="ADP", suppliers=["Hexton Pet Products"],
         forwarder="Pallas Logistics", threepl="Crateway Fulfillment", landlord="Liberty Ave Partners",
         tax_agency="PA DEPT OF REVENUE", card_issuer="Keystone", lender="Summit Bridge Finance",
         meta_direct_debit=True,
         ad_platforms=[("meta", 0.50, 2500.0), ("google", 0.50, 2000.0)],
         card_software=soft(["klaviyo", "shopify_sub", "recharge"], [2, 8, 15]),
         travel_merchants=["uber", "corner"], supply_merchants=["uline", "stamps", "boxco"],
         bank_style="D", bank_layout="L4", bank_date="mdy_nopad", savings_in_export=True, card_layout="K2",
         card_date="mdy", card_member="M CHEN", orders_layout="O1", payouts_layout="P1", amazon_layout="A1",
         amazon_reserve=True, coa_layout="C2",
         coa_added_upload2=dict(number=6950, name="Product Samples", type="Expenses", label="other_opex")),
    # ---- development split: never used for training
    dict(slug="quillon-coffee", name="Quillon Coffee Roasters", split="dev", seed=808, currency="USD",
         annual_rev=3.0e6, shares=dict(shopify=0.65, amazon=0.15, faire=0.20), aov=46, tax_rate=0.04,
         payroll_provider="Gusto", suppliers=["Mirabel Coffee Imports", "Tamsin Ceramics"],
         forwarder="Saltbox Freight", threepl="Bundle & Ship", landlord="Greenpoint Terminal LLC",
         tax_agency="GA DEPT OF REVENUE", card_issuer="Meridian", lender=None,
         faire_retailers=["Fieldhouse Goods", "Oak Hollow Market"],
         direct_retailers=["Corner Larder", "Westgate Market Co"],
         ad_platforms=[("meta", 0.70, 1500.0), ("google", 0.30, 1000.0)],
         card_software=soft(["klaviyo", "shopify_sub", "recharge", "gsuite"], [4, 9, 18, 27]),
         travel_merchants=["uber", "sq_coffee", "delta"], supply_merchants=["uline", "papermart"],
         bank_style="A", bank_layout="L1", bank_date="mdy", card_layout="K1", card_date="mdy",
         orders_layout="O1", payouts_layout="P1b", amazon_layout="A2", faire_layout="F2", coa_layout="C3",
         coa_added_upload2=dict(number=0, name="Green Coffee Freight", type="Cost of Goods Sold",
                                label="cogs_freight_duty")),
    dict(slug="saltmarsh-apparel", name="Saltmarsh Apparel", split="dev", seed=909, currency="CAD",
         annual_rev=4.0e6, shares=dict(shopify=0.85, faire=0.15), aov=104, tax_rate=0.13,
         payroll_provider="Wagepoint", suppliers=["Duskwood Leather", "Ironleaf Home Goods"],
         forwarder="Kingsbridge Cargo", threepl="Relay Fulfillment", landlord="Harbor Point Realty",
         tax_agency="RECEIVER GENERAL", card_issuer="Ashford", lender="Arbor Credit",
         faire_retailers=["Mapleton Gifts", "The Willow Shop"],
         ad_platforms=[("meta", 0.60, 3000.0), ("google", 0.25, 1500.0), ("tiktok", 0.15, 1000.0)],
         card_software=soft(["klaviyo", "shopify_sub", "gorgias"], [6, 12, 22]),
         travel_merchants=["uber", "marriott"], supply_merchants=["uline", "boxco"],
         bank_style="B", bank_layout="L2", bank_date="dmy", card_layout="K3", card_date="dmy",
         orders_layout="O3", payouts_layout="P1", faire_layout="F1", coa_layout="C1",
         coa_added_upload2=dict(number=4300, name="Pop-up Shop Sales", type="Income", label="revenue_dtc")),
    dict(slug="hollis-home", name="Hollis Home", split="dev", seed=1010, currency="USD", annual_rev=5.5e6,
         shares=dict(shopify=0.75, amazon=0.25), aov=88, tax_rate=0.07,
         payroll_provider="Rippling", suppliers=["Ironleaf Home Goods", "Tamsin Ceramics"],
         forwarder="Orchard Line Freight", threepl="Corbel Warehousing", landlord="Atlantic Yard Properties",
         tax_agency="MA DOR", card_issuer="Granite", lender=None, meta_direct_debit=True,
         ad_platforms=[("meta", 0.50, 3000.0), ("google", 0.35, 2000.0), ("pinterest", 0.15, 1000.0)],
         card_software=soft(["klaviyo", "shopify_sub", "notion", "figma"], [3, 9, 15, 23]),
         travel_merchants=["lyft", "jetblue", "bluedoor"], supply_merchants=["stamps", "pirateship"],
         bank_style="C", bank_layout="L3", bank_date="iso", savings_in_export=True, card_layout="K2",
         card_date="mdy", card_member="S PATEL", orders_layout="O2", payouts_layout="P1", amazon_layout="A1",
         amazon_reserve=True, amazon_ads_in_settlement=True, coa_layout="C2",
         coa_added_upload2=dict(number=6960, name="Showroom Expenses", type="Expenses", label="other_opex")),
]


def fill_defaults(spec, idx):
    rng = np.random.default_rng(spec["seed"] + 7)
    spec.setdefault("sku_prefix", "".join(w[0] for w in spec["name"].split() if w[0].isalpha())[:3].upper())
    spec.setdefault("order_prefix", "#")
    spec.setdefault("order_start", int(1001 + idx * 2000))
    spec.setdefault("payout_prefix", "")
    spec.setdefault("amazon_sid_base", int(14_000_000_000 + spec["seed"] * 1000))
    spec.setdefault("faire_prefix", f"F{spec['seed']}")
    spec.setdefault("operating_last4", "".join(str(int(x)) for x in rng.integers(0, 10, 4)))
    spec.setdefault("savings_last4", "".join(str(int(x)) for x in rng.integers(0, 10, 4)))
    spec.setdefault("card_last5", "".join(str(int(x)) for x in rng.integers(0, 10, 5)))
    spec.setdefault("card_member", "OWNER")
    spec.setdefault("savings_in_export", False)
    spec.setdefault("direct_retailers", [])
    spec.setdefault("faire_retailers", [])
    return spec


def kickoff_yaml(spec):
    """What the implementation lead captures on the kickoff call. The pipeline may read this."""
    return {
        "brand": spec["name"],
        "currency": spec["currency"],
        "own_accounts": {"operating_last4": spec["operating_last4"], "savings_last4": spec["savings_last4"],
                         "card_last5": spec["card_last5"]},
        "note": "Synthetic brand. Captured on the kickoff call: name, currency, own account numbers.",
    }


def write_brand(spec, raw_root: Path, truth_root: Path, coa_pools=COA_POOLS, renderers=RENDERERS, post_sim=None):
    sim = simulate(spec, coa_pools)
    if post_sim:
        post_sim(sim)
    rng = np.random.default_rng(spec["seed"] + 99)
    braw = raw_root / spec["slug"]
    btruth = truth_root / spec["slug"]
    for p in (braw, btruth):
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True)
    (braw / "brand.yaml").write_text(yaml.safe_dump(kickoff_yaml(spec), sort_keys=False))
    manifest = {"brand": spec["name"], "slug": spec["slug"], "split": spec["split"], "currency": spec["currency"],
                "files": {}}
    for upload in (1, 2):
        up = braw / f"upload_{upload}"
        up.mkdir()
        (btruth / "rows" / f"upload_{upload}").mkdir(parents=True)
        for fn in renderers:
            for rf in fn(sim, upload, rng):
                write_file(rf, up)
                key = f"upload_{upload}/{rf.name}"
                manifest["files"][key] = {"source_type": rf.source_type, "column_map": rf.column_map,
                                          "meta": rf.meta, "n_rows": len(rf.rows)}
                if rf.row_truth is not None:
                    pd.DataFrame(rf.row_truth).to_csv(btruth / "rows" / f"upload_{upload}" / f"{rf.name}.csv",
                                                      index=False)
    # true customer receipts and true spend per upload, from the bank truth (duplicates removed)
    rec = {}
    for upload, w in ((1, UPLOAD_1), (2, UPLOAD_2)):
        b = sim.bank[[w[0] <= d <= w[1] for d in sim.bank["date"]]]
        b = b[b["account"] == "operating"]
        byc = {}
        for lab, ch in RECEIPT_LABELS.items():
            byc[ch] = byc.get(ch, 0.0) + float(b.loc[b["label"] == lab, "amount"].sum())
        rec[f"upload_{upload}"] = {"customer_receipts": {k: round(v, 2) for k, v in byc.items()},
                                   "window": [w[0].isoformat(), w[1].isoformat()]}
    (btruth / "receipts.json").write_text(json.dumps(rec, indent=2))
    (btruth / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


def main():
    raw_root = ROOT / "data" / "raw"
    truth_root = ROOT / "evals" / "ground_truth"
    raw_root.mkdir(parents=True, exist_ok=True)
    truth_root.mkdir(parents=True, exist_ok=True)
    for i, spec in enumerate(BRANDS):
        spec = fill_defaults(dict(spec), i)
        m = write_brand(spec, raw_root, truth_root)
        n = sum(v["n_rows"] for v in m["files"].values())
        print(f"  {spec['slug']:<20} split={spec['split']:<5} files={len(m['files']):>2} rows={n:>6}")


if __name__ == "__main__":
    main()
