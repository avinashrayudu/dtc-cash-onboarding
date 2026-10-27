"""
Onboards one upload for one brand, end to end.

  1. read every file, recognize it (memory first, then detection), map its columns
  2. build standard tables; drop lines already ingested from an earlier upload
  3. run the tie-outs; matched lines are labeled by proof
  4. label the remaining lines (memory, then the model); abstain below the threshold
  5. map the chart of accounts the same way
  6. decide the brand's status: blocked (a tie-out failed), open items, or accepted
  7. write the ledger, the review queue and a JSON summary

Built by Avinash Rayudu.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import joblib
import pandas as pd
import yaml

import tieout as T
from classify_lines import CUSTOMER_RECEIPTS, NOT_SPEND, coa_features, line_features, predict
from detect_source import DETECT_ACCEPT, detect
from map_columns import ACCEPT, Mapping
from memory import BrandMemory, fingerprint, line_key_tokens, raw_tokens
from readers import read_any
from transform import TRANSFORMS

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Models:
    line_model: object
    coa_model: object
    line_threshold: float
    coa_threshold: float

    @classmethod
    def load(cls, folder=ROOT / "models"):
        fz = json.loads((Path(folder) / "frozen.json").read_text())
        return cls(joblib.load(Path(folder) / "line_model.joblib"), joblib.load(Path(folder) / "coa_model.joblib"),
                   fz["line_threshold"], fz["coa_threshold"])


def _review(kind, file, row, what, detail, amount=None, guess=None, confidence=None):
    return {"kind": kind, "file": file, "row": row, "what": what, "detail": detail, "amount": amount,
            "guess": guess, "confidence": None if confidence is None else round(float(confidence), 3)}


def onboard_upload(brand_dir: Path, upload: str, memory: BrandMemory, models: Models, out_dir: Path = None,
                   faults: dict = None, commit: bool = False, use_memory_lines: bool = True, llm=None) -> dict:
    t0 = time.time()
    faults = faults or {}
    brand_dir = Path(brand_dir)
    kickoff = yaml.safe_load((brand_dir / "brand.yaml").read_text())
    files = sorted(p for p in (brand_dir / upload).iterdir() if p.is_file() and not p.name.startswith("."))
    if faults.get("drop_files"):
        files = [p for p in files if p.name not in set(faults["drop_files"])]
    review, file_log = [], []
    tables = {k: [] for k in ("bank", "card", "orders", "payouts", "amazon", "faire", "coa")}
    bank_infos = []

    # ---- 1-2: recognize, map, transform
    for path in files:
        entry = {"file": path.name}
        try:
            tab = read_any(path)
        except Exception as e:     # unreadable file: a person has to look
            review.append(_review("file", path.name, None, "file could not be read", str(e)))
            entry.update(status="unreadable")
            file_log.append(entry)
            continue
        sig = tab.signature()
        mem = memory.layout(sig)
        if mem and all(h in tab.header for h in mem["fields"].values()):
            mapping = Mapping(mem["source_type"], dict(mem["fields"]), {f: 1.0 for f in mem["fields"]}, [], 1.0)
            entry.update(method="memory", source_type=mapping.source_type, confidence=1.0)
        else:
            det = detect(tab)
            mapping = det.mapping
            entry.update(method="detected", source_type=det.source_type, confidence=round(det.confidence, 3),
                         detection=det.reason, field_scores={k: round(v, 3) for k, v in mapping.scores.items()})
            if (det.confidence < DETECT_ACCEPT or mapping.confidence < ACCEPT or mapping.missing_required) and llm:
                from llm_fallback import suggest_mapping
                sug = suggest_mapping(tab, llm)
                if sug is not None:
                    mapping = sug
                    entry.update(method="llm suggestion, value-checked", source_type=sug.source_type,
                                 confidence=round(sug.confidence, 3))
                    det.confidence = max(det.confidence, DETECT_ACCEPT)
            if det.confidence < DETECT_ACCEPT or mapping.confidence < ACCEPT or mapping.missing_required:
                review.append(_review("file", path.name, None, "confirm file type and columns",
                                      f"best guess {det.source_type} (confidence {det.confidence:.2f}); "
                                      f"missing {mapping.missing_required}", guess=det.source_type,
                                      confidence=det.confidence))
                entry.update(status="needs review")
                file_log.append(entry)
                continue
        entry.update(signature=sig, fields=mapping.fields, rows=len(tab.rows), header_line=tab.header_line)
        st = mapping.source_type
        try:
            fn = TRANSFORMS[st]
            if st == "bank":
                df, info = fn(tab, mapping, kickoff, faults)
                bank_infos.append(info)
            else:
                df, info = fn(tab, mapping, faults)
        except Exception as e:
            review.append(_review("file", path.name, None, "mapping did not produce usable rows", repr(e),
                                  guess=st))
            entry.update(status="transform failed")
            file_log.append(entry)
            continue
        entry.update(status="ok", info=info)
        file_log.append(entry)
        df = df.copy()
        df["file"] = path.name
        key = {"orders_list": "orders", "sales_daily": "orders", "amazon_flat": "amazon",
               "amazon_range": "amazon"}.get(st, st)
        tables[key].append(df)

    cat = lambda k: pd.concat(tables[k], ignore_index=True) if tables[k] else pd.DataFrame()
    bank, card = cat("bank"), cat("card")
    orders, payouts, amazon, faire, coa = cat("orders"), cat("payouts"), cat("amazon"), cat("faire"), cat("coa")
    sources_present = {k for k in ("payouts", "amazon", "faire") if len(tables[k])}

    # ---- duplicates from earlier uploads
    new_fps = {"bank": [], "card": []}
    for src, df in (("bank", bank), ("card", card)):
        if df.empty:
            continue
        if src == "card":
            df["amount"] = df["charge"]
            df["account"] = "card"
            df["balance"] = None
        seen = memory.seen_counts(src)
        dup = []
        for r in df.to_dict("records"):
            fp = fingerprint(src, r)
            if seen.get(fp, 0) > 0:
                seen[fp] -= 1
                dup.append(True)
            else:
                dup.append(False)
                new_fps[src].append(fp)
        df["is_duplicate"] = dup
        for c in ("label", "method"):
            df[c] = None
        df["confidence"] = float("nan")
        df["confirmed_no_export"] = False

    checks = [T.bank_present(bank, len(files)), T.rows_read(file_log)]
    nb = bank[~bank["is_duplicate"]] if not bank.empty else bank
    nc = card[~card["is_duplicate"]] if not card.empty else card

    # ---- sign convention without a balance column: let the payouts decide
    sign_note = None
    if not nb.empty and bank_infos and all(i["sign_source"] == "convention" for i in bank_infos):
        ref = payouts.rename(columns={"net": "amount"}) if not payouts.empty else (amazon if not amazon.empty else faire)
        if ref is not None and not ref.empty:
            fwd = len(T.match_records(ref[ref["amount"] > 0], nb, 3, 1))
            rev = len(T.match_records(ref[ref["amount"] > 0], nb, 3, -1))
            if rev > fwd:
                bank["amount"] = -bank["amount"]
                nb = bank[~bank["is_duplicate"]]
                sign_note = f"bank amounts were exported with outflows positive; corrected using {rev} payout matches"
            else:
                sign_note = f"sign convention confirmed by {fwd} payout matches"

    # ---- 3: tie-outs with evidence labels
    taken = set()

    def label_evidence(mapping_idx, df_lines, label):
        for _, li in mapping_idx.items():
            df_lines.at[li, "label"] = label
            df_lines.at[li, "method"] = "tie-out"
            df_lines.at[li, "confidence"] = 1.0
            taken.add(li)

    if not nb.empty:
        for name, src, lab, tol in (("shopify_payouts_to_bank", payouts.rename(columns={"net": "amount"})
                                     if not payouts.empty else pd.DataFrame(), "processor_payout", 3),
                                    ("amazon_to_bank", amazon, "marketplace_payout", 5),
                                    ("faire_to_bank", faire, "wholesale_payout", 3)):
            if src.empty:
                continue
            chk, m = T.source_to_bank(name, src, nb, tol, taken)
            checks.append(chk)
            label_evidence(m, bank, lab)
        if not nc.empty:
            chk, m = T.card_payments_to_bank(nc, nb, taken)
            checks.append(chk)
            for ci, bi in m.items():
                bank.at[bi, "label"], bank.at[bi, "method"], bank.at[bi, "confidence"] = "card_payment", "tie-out", 1.0
                card.at[ci, "label"], card.at[ci, "method"], card.at[ci, "confidence"] = \
                    "card_payment_received", "tie-out", 1.0
                taken.add(bi)
        m = T.own_transfer_pairs(bank[(~bank["is_duplicate"]) & (bank["method"].isna())])
        for si, oi in m.items():
            for li in (si, oi):
                if bank.at[li, "method"] is None:
                    bank.at[li, "label"], bank.at[li, "method"], bank.at[li, "confidence"] = \
                        "own_account_transfer", "tie-out", 1.0
        for info in bank_infos:
            checks.append(T.balance_continuity(info))
    if not orders.empty and not payouts.empty:
        checks.append(T.orders_to_payouts(orders, payouts))
    if not nc.empty:
        checks.append(T.card_statement_balance(nc))

    # ---- 4: label the rest: memory, then the model, else review
    from collections import Counter
    df_count = Counter()
    for df in (bank, card):
        if not df.empty:
            for d in df.loc[~df["is_duplicate"], "description"]:
                df_count.update(raw_tokens(d, kickoff))
    stable = {t for t, c in df_count.items() if c >= 2} | memory.vocabulary()
    for src, df in (("BANK", bank), ("CARD", card)):
        if not df.empty:
            df["mem_key"] = ["|".join(sorted(line_key_tokens(src, a, d, kickoff, stable)))
                             for a, d in zip(df["amount"], df["description"])]
    for src, df in (("BANK", bank), ("CARD", card)):
        if df.empty:
            continue
        todo = df[(~df["is_duplicate"]) & (df["method"].isna())]
        if todo.empty:
            continue
        texts = [line_features(src, a, d, kickoff) for a, d in zip(todo["amount"], todo["description"])]
        labels, conf = predict(models.line_model, texts)
        for (idx, r), lab, c in zip(todo.iterrows(), labels, conf):
            key = frozenset(r["mem_key"].split("|")) if r["mem_key"] else frozenset()
            rem = memory.recall_line(key) if use_memory_lines else None
            if rem:
                df.at[idx, "label"], df.at[idx, "method"], df.at[idx, "confidence"] = rem, "memory", 1.0
                if memory.is_confirmed_no_export(r["mem_key"]):
                    df.at[idx, "confirmed_no_export"] = True
            elif c >= models.line_threshold:
                df.at[idx, "label"], df.at[idx, "method"], df.at[idx, "confidence"] = lab, "model", float(c)
            else:
                df.at[idx, "method"], df.at[idx, "confidence"] = "review", float(c)
                review.append(_review("line", r["file"], int(r["row"]), "what is this line?",
                                      str(r["description"])[:90], amount=float(r["amount"]), guess=lab,
                                      confidence=c))

    # ---- 5: chart of accounts
    coa_out = []
    if not coa.empty:
        texts = [coa_features(n, t) for n, t in zip(coa["name"], coa["type"])]
        labels, conf = predict(models.coa_model, texts)
        for r, lab, c in zip(coa.to_dict("records"), labels, conf):
            rem = memory.recall_coa(r["name"], r["type"])
            if rem:
                coa_out.append({**r, "label": rem, "method": "memory", "confidence": 1.0})
            elif c >= models.coa_threshold:
                coa_out.append({**r, "label": lab, "method": "model", "confidence": round(float(c), 3)})
            else:
                coa_out.append({**r, "label": None, "method": "review", "confidence": round(float(c), 3)})
                review.append(_review("account", r["file"], int(r["row"]), "which category is this account?",
                                      f"{r['name']} ({r['type']})", guess=lab, confidence=c))
    coa_df = pd.DataFrame(coa_out)

    if not bank.empty:
        nbl = bank[(~bank["is_duplicate"]) & bank["label"].notna()]
        chk = T.unpaired_transfers(nbl)
        checks.append(chk)
        if chk.status == "fail":
            for idx, r in nbl[(nbl["label"] == "own_account_transfer") & (nbl["method"] != "tie-out")].iterrows():
                _send_to_review(bank, idx, r, review, "called a transfer between own accounts, but the other "
                                "half is not in the export")
        chk = T.deposits_without_source(nbl, sources_present)
        checks.append(chk)
        if chk.status == "fail":
            lab_src = ("processor_payout", "marketplace_payout", "wholesale_payout")
            for idx, r in nbl[nbl["label"].isin(lab_src) & (nbl["method"] != "tie-out") &
                              (~nbl["confirmed_no_export"].astype(bool))].iterrows():
                _send_to_review(bank, idx, r, review, "looks like a payout, but no payout export accounts for it")

    # ---- 6: status
    failed = [c.name for c in checks if c.status == "fail"]
    open_items = len(review)
    if failed:
        status = "blocked"
    elif open_items:
        status = "ties out, items open"
    else:
        status = "accepted"

    # ---- money summary
    summary = money_summary(bank, card)
    result = {
        "brand": kickoff["brand"], "upload": upload, "status": status, "failed_checks": failed,
        "open_review_items": open_items, "files": file_log, "checks": [c.as_dict() for c in checks],
        "sign_note": sign_note, "summary": summary,
        "counts": {
            "bank_lines": int(len(bank)), "card_lines": int(len(card)),
            "duplicates_skipped": int((bank["is_duplicate"].sum() if not bank.empty else 0) +
                                      (card["is_duplicate"].sum() if not card.empty else 0)),
            "by_method": _by_method(bank, card), "accounts": int(len(coa_df)),
            "accounts_by_method": coa_df["method"].value_counts().to_dict() if not coa_df.empty else {},
            "review_by_kind": pd.Series([r["kind"] for r in review]).value_counts().to_dict() if review else {},
        },
        "seconds": round(time.time() - t0, 2),
    }
    if out_dir is not None:
        od = Path(out_dir) / upload
        od.mkdir(parents=True, exist_ok=True)
        ledger = pd.concat([x.assign(source=s) for s, x in (("bank", bank), ("card", card)) if not x.empty],
                           ignore_index=True) if (not bank.empty or not card.empty) else pd.DataFrame()
        if not ledger.empty:
            cols = ["source", "file", "row", "date", "account", "description", "amount", "label", "method",
                    "confidence", "is_duplicate"]
            ledger[cols].to_csv(od / "ledger.csv", index=False)
        pd.DataFrame(review, columns=["kind", "file", "row", "what", "detail", "amount", "guess",
                                      "confidence"]).to_csv(od / "review_queue.csv", index=False)
        if not coa_df.empty:
            coa_df.to_csv(od / "chart_of_accounts_map.csv", index=False)
        (od / "result.json").write_text(json.dumps(result, indent=2, default=str))
    if commit:
        for src, fps in new_fps.items():
            memory.add_fingerprints(src, fps)
        if not failed:
            for e in file_log:
                if e.get("method") == "detected" and e.get("status") == "ok":
                    memory.remember_layout(e["signature"], e["source_type"], e["fields"], "auto, tie-outs passed")
    result["_frames"] = {"bank": bank, "card": card, "coa": coa_df, "review": review}
    return result


def _send_to_review(df, idx, r, review, why):
    review.append(_review("line", r["file"], int(r["row"]), why, str(r["description"])[:90],
                          amount=float(r["amount"]), guess=r["label"], confidence=r["confidence"]))
    df.at[idx, "label"], df.at[idx, "method"] = None, "review"


def _by_method(bank, card):
    out = {}
    for src, df in (("bank", bank), ("card", card)):
        if df.empty:
            continue
        d = df[~df["is_duplicate"]]
        out[src] = d["method"].fillna("none").value_counts().to_dict()
    return out


def money_summary(bank: pd.DataFrame, card: pd.DataFrame) -> dict:
    """Confirmed receipts by channel, pending amounts, and what a naive sum of the files would say."""
    out = {}
    if not bank.empty:
        nb = bank[~bank["is_duplicate"]]
        op = nb[nb["account"] != "savings"]
        ch = {"processor_payout": "dtc", "marketplace_payout": "marketplace", "wholesale_payout": "wholesale",
              "wholesale_receipt": "wholesale"}
        rec = {}
        for lab, c in ch.items():
            rec[c] = round(rec.get(c, 0.0) + float(op.loc[op["label"] == lab, "amount"].sum()), 2)
        out["customer_receipts"] = rec
        out["customer_receipts_total"] = round(sum(rec.values()), 2)
        pend = op[op["method"] == "review"]
        out["pending_review_inflows"] = round(float(pend.loc[pend["amount"] > 0, "amount"].sum()), 2)
        out["pending_review_outflows"] = round(float(-pend.loc[pend["amount"] < 0, "amount"].sum()), 2)
        out["naive_receipts_all_deposits"] = round(float(bank.loc[bank["amount"] > 0, "amount"].sum()), 2)
        # what a naive "add up every deposit" includes that is not customer money
        pos = bank[bank["amount"] > 0]
        brk = {"duplicate rows from overlapping exports": float(pos.loc[pos["is_duplicate"], "amount"].sum())}
        live = pos[~pos["is_duplicate"]]
        brk["savings-account side of own transfers"] = float(live.loc[live["account"] == "savings", "amount"].sum())
        lv = live[live["account"] != "savings"]
        for lab, name in (("own_account_transfer", "transfers in from own accounts"),
                          ("financing_draw", "loan and credit line draws"), ("vendor_refund", "vendor refunds"),
                          ("interest_income", "interest earned")):
            brk[name] = float(lv.loc[lv["label"] == lab, "amount"].sum())
        brk["still in review"] = float(lv.loc[lv["method"] == "review", "amount"].sum())
        out["naive_receipts_breakdown"] = {k: round(v, 2) for k, v in brk.items() if abs(v) > 0.005}
        spend = op[(op["amount"] < 0) & (~op["label"].isin(NOT_SPEND)) & (op["label"].notna())]
        out["bank_spend"] = round(float(-spend["amount"].sum()), 2)
        out["naive_bank_withdrawals"] = round(float(-bank.loc[bank["amount"] < 0, "amount"].sum()), 2)
        out["window"] = [str(nb["date"].min()), str(nb["date"].max())] if not nb.empty else None
    if not card.empty:
        nc = card[~card["is_duplicate"]]
        out["card_spend"] = round(float(nc.loc[(nc["charge"] > 0) & nc["label"].notna(), "charge"].sum()), 2)
        out["naive_card_charges"] = round(float(card.loc[card["charge"] > 0, "charge"].sum()), 2)
    if "bank_spend" in out:
        out["operating_spend"] = round(out["bank_spend"] + out.get("card_spend", 0.0), 2)
        out["naive_spend"] = round(out["naive_bank_withdrawals"] + out.get("naive_card_charges", 0.0), 2)
    return out
