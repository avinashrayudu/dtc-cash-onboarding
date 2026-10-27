"""
Classifies what each bank or card line actually is.

Lines are normalized first: the brand's own name and account numbers are
replaced with placeholder tokens, digits are collapsed, and the source (bank or
card), direction and size bucket are added as tokens. A logistic regression over
character and word n-grams then predicts the cash meaning. If the top
probability is below the frozen threshold, the line is not guessed; it goes to
the review queue.

The same machinery maps chart-of-accounts names to standard categories.

Built by Avinash Rayudu.
"""
from __future__ import annotations

import math
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

BANK_LABELS = ["processor_payout", "marketplace_payout", "wholesale_payout", "wholesale_receipt",
               "own_account_transfer", "financing_draw", "financing_repayment", "vendor_refund", "interest_income",
               "payroll", "inventory_purchase", "freight_duty", "fulfillment_3pl", "card_payment", "ad_spend",
               "software_opex", "rent", "sales_tax", "interest_expense", "bank_fee"]
CARD_LABELS = ["ad_spend", "software_opex", "travel_other", "shipping_supplies", "card_payment_received"]
CUSTOMER_RECEIPTS = {"processor_payout", "marketplace_payout", "wholesale_payout", "wholesale_receipt"}
NOT_SPEND = {"own_account_transfer", "card_payment", "financing_repayment", "card_payment_received"}


def norm_text(text: str, kickoff: dict) -> str:
    s = str(text).upper()
    brand = (kickoff or {}).get("brand", "")
    if brand:
        s = s.replace(brand.upper(), " OWNBRAND ")
    own = (kickoff or {}).get("own_accounts", {}) or {}
    for k in ("operating_last4", "savings_last4", "card_last5"):
        v = str(own.get(k, "") or "")
        if v:
            s = s.replace(v, " OWNACCT ")
    s = s.replace("••", " ").replace("...", " ")
    s = re.sub(r"\d", "0", s)
    s = re.sub(r"0{3,}", "000", s)
    s = re.sub(r"[^A-Z0 *&./:-]+", " ", s)
    s = re.sub(r"[:/.-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def amount_bucket(a: float) -> str:
    a = abs(a)
    if a < 1:
        return "AMT_0"
    return f"AMT_{min(6, int(math.log10(a)))}"


def line_features(src: str, amount: float, text: str, kickoff: dict) -> str:
    sign = "POS" if amount > 0 else "NEG"
    return f"SRC_{src} SIGN_{sign} {amount_bucket(amount)} {src}_{sign} {norm_text(text, kickoff)}"


def coa_features(name: str, typ: str) -> str:
    t = re.sub(r"[^a-z]+", "_", str(typ).lower()).strip("_")
    n = re.sub(r"\d", "0", str(name).lower())
    n = re.sub(r"[^a-z0 &:/-]+", " ", n).replace(":", " : ")
    return f"type_{t} {n}"


def make_model(C=6.0):
    feats = FeatureUnion([
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)),
        ("word", TfidfVectorizer(analyzer="word", token_pattern=r"\S+", ngram_range=(1, 2), min_df=1,
                                 sublinear_tf=True)),
    ])
    return Pipeline([("feats", feats), ("clf", LogisticRegression(C=C, max_iter=4000))])


def predict(model, texts):
    """Returns (labels, top probabilities)."""
    if len(texts) == 0:
        return [], np.array([])
    proba = model.predict_proba(texts)
    idx = proba.argmax(axis=1)
    return [model.classes_[i] for i in idx], proba[np.arange(len(idx)), idx]


def choose_threshold(conf, correct, target=0.99, grid=None):
    """Smallest threshold whose accepted predictions reach the target precision, to keep coverage high."""
    grid = grid if grid is not None else [round(x, 2) for x in np.arange(0.30, 1.0, 0.01)]
    conf, correct = np.asarray(conf), np.asarray(correct)
    rows = []
    chosen = None
    for t in grid:
        acc = conf >= t
        if acc.sum() == 0:
            continue
        prec = correct[acc].mean()
        cov = acc.mean()
        rows.append((t, float(prec), float(cov), int(acc.sum())))
        if chosen is None and prec >= target:
            chosen = t
    return (chosen if chosen is not None else 0.99), rows
