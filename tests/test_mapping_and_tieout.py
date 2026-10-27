"""Detection, mapping and the tie-out gate."""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import tieout as T
from common import ROOT, brands, manifest
from detect_source import detect
from readers import read_any


def test_every_dev_file_is_recognized_and_mapped():
    """Development brands: every file's type and every truth field must come out right."""
    for slug, split, raw, truth in brands("dev"):
        man = manifest(truth)
        for key, info in man["files"].items():
            if not key.startswith("upload_1/"):
                continue
            d = detect(read_any(Path(raw) / key))
            assert d.source_type == info["source_type"], (slug, key, d.reason)
            for f, h in info["column_map"].items():
                assert d.mapping.fields.get(f) == h, (slug, key, f)


def _lines(rows):
    return pd.DataFrame(rows, columns=["date", "amount", "account"])


def test_match_records_is_one_to_one_and_respects_window():
    exp = pd.DataFrame({"date": [date(2026, 7, 1), date(2026, 7, 2)], "amount": [100.0, 100.0]})
    bank = _lines([(date(2026, 7, 2), 100.0, "operating"), (date(2026, 7, 9), 100.0, "operating")])
    m = T.match_records(exp, bank, 3)
    assert len(m) == 1 and list(m.values()) == [0]


def test_orders_to_payouts_finds_lag_and_flags_overcount():
    days = [date(2026, 7, 1) + timedelta(days=i) for i in range(40)]
    orders = pd.DataFrame({"date": days, "charges": [1000.0 + i for i in range(40)]})
    pay = {}
    for d, c in zip(orders["date"], orders["charges"]):
        p = T.bdays_after(d, 2)
        pay[p] = pay.get(p, 0) + c
    payouts = pd.DataFrame({"date": list(pay), "charges": list(pay.values())})
    ok = T.orders_to_payouts(orders, payouts)
    assert ok.status == "pass" and "lag 2" in ok.detail
    doubled = orders.assign(charges=orders["charges"] * 1.6)    # line-item totals summed by mistake
    assert T.orders_to_payouts(doubled, payouts).status == "fail"


def test_card_statement_close_day_inferred():
    rows = []
    for d in pd.date_range("2026-06-29", "2026-08-28"):
        rows.append(dict(date=d.date(), charge=100.0))
    ch = pd.DataFrame(rows)
    jul = ch[(ch["date"] > date(2026, 6, 28)) & (ch["date"] <= date(2026, 7, 28))]["charge"].sum()
    pays = pd.DataFrame([dict(date=date(2026, 8, 22), charge=-jul)])
    card = pd.concat([ch, pays], ignore_index=True)
    c = T.card_statement_balance(card)
    assert c.status == "pass" and "day 28" in c.detail


def test_deposits_without_source_names_missing_export():
    bank = pd.DataFrame([dict(date=date(2026, 7, 1), amount=500.0, label="marketplace_payout", method="model",
                              is_duplicate=False)])
    c = T.deposits_without_source(bank, {"payouts"})
    assert c.status == "fail" and "amazon" in c.detail
