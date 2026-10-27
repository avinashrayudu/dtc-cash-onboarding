"""
Runs the full onboarding workflow on every brand and measures it.

For each brand: upload 1 (first pass) -> simulated review -> upload 1 (final,
committed to memory) -> upload 2 (first pass) -> simulated review -> upload 2
(final). Memory starts empty for every brand. Everything is measured on the
FIRST pass of each upload, before any review, because that is what the model and
the rules do on their own.

Reported by split:
  train    the 7 brands the model trained on (in-sample, shown for completeness only)
  dev      3 brands the model never trained on, used while building the rules
  holdout  3 brands written after the model and rules were frozen

Also runs fault injection: deliberately wrong mappings and missing files, applied
to upload 1 after its first review (when the clean files pass), to measure how
often the tie-out gate blocks a brand that should be blocked.

Usage:
  python evals/run_evals.py            full run, writes evals/results/ and reports/
  python evals/run_evals.py --quick    skip fault injection

Built by Avinash Rayudu.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, brands, manifest, truth_rows   # noqa: E402

sys.path.insert(0, str(ROOT / "review"))
from memory import BrandMemory                          # noqa: E402
from pipeline import Models, onboard_upload             # noqa: E402
from resolve import resolve                             # noqa: E402

OUT = ROOT / "out"
RES = ROOT / "evals" / "results"
UPLOADS = ("upload_1", "upload_2")


# --------------------------------------------------------------------------- scoring helpers
def score_files(result, man):
    rows = []
    for f in result["files"]:
        key = f"{result['upload']}/{f['file']}"
        t = man["files"].get(key)
        if not t:
            continue
        auto = f.get("status") == "ok"
        type_ok = f.get("source_type") == t["source_type"]
        fields = f.get("fields") or {}
        nf = len(t["column_map"])
        fok = sum(1 for k, h in t["column_map"].items() if fields.get(k) == h) if auto else 0
        rows.append(dict(file=f["file"], truth=t["source_type"], got=f.get("source_type"), method=f.get("method"),
                         auto=auto, type_ok=type_ok, fields_total=nf, fields_ok=fok,
                         wrong_auto=auto and (not type_ok or fok < nf)))
    return rows


def score_lines(result, truth_dir, man):
    """Starts from every true bank and card row, so lines in files the pipeline could not map count as unlabeled."""
    pred = {}
    for src, df in (("bank", result["_frames"]["bank"]), ("card", result["_frames"]["card"])):
        if df is None or df.empty:
            continue
        for r in df.itertuples():
            pred[(r.file, int(r.row))] = r
    out = []
    up = result["upload"]
    for key, info in man["files"].items():
        if not key.startswith(up + "/") or info["source_type"] not in ("bank", "card"):
            continue
        file = key.split("/", 1)[1]
        t = truth_rows(truth_dir, key)
        for i, tl in t.iterrows():
            r = pred.get((file, int(i)))
            out.append(dict(src=info["source_type"], file=file, row=int(i), truth=tl["label"],
                            truth_dup=bool(tl["is_duplicate"]),
                            pred_dup=bool(r.is_duplicate) if r is not None else False,
                            label=r.label if r is not None else None,
                            method=r.method if r is not None else "file not mapped",
                            amount=r.amount if r is not None else tl["amount"]))
    return pd.DataFrame(out)


def score_accounts(result, truth_dir, man):
    coa = result["_frames"]["coa"]
    pred = {} if coa is None or coa.empty else {(r.file, int(r.row)): r for r in coa.itertuples()}
    out = []
    up = result["upload"]
    for key, info in man["files"].items():
        if not key.startswith(up + "/") or info["source_type"] != "coa":
            continue
        file = key.split("/", 1)[1]
        for i, tl in truth_rows(truth_dir, key).iterrows():
            r = pred.get((file, int(i)))
            out.append(dict(file=file, row=int(i), truth=tl["label"], label=r.label if r is not None else None,
                            method=r.method if r is not None else "file not mapped"))
    return pd.DataFrame(out)


def line_metrics(df):
    if df.empty:
        return {}
    d = df[~df["truth_dup"]]
    lab = d[d["label"].notna()]
    out = {"lines": int(len(d)), "auto_labeled": int(len(lab)),
           "coverage": round(len(lab) / max(1, len(d)), 4),
           "precision": round(float((lab["label"] == lab["truth"]).mean()), 4) if len(lab) else None,
           "errors": int((lab["label"] != lab["truth"]).sum()), "to_review": int((d["method"] == "review").sum()),
           "in_unmapped_files": int((d["method"] == "file not mapped").sum())}
    by = {}
    for m, g in lab.groupby("method"):
        by[m] = {"n": int(len(g)), "precision": round(float((g["label"] == g["truth"]).mean()), 4)}
    out["by_method"] = by
    tp = int(((df["pred_dup"]) & (df["truth_dup"])).sum())
    fp = int(((df["pred_dup"]) & (~df["truth_dup"])).sum())
    fn = int(((~df["pred_dup"]) & (df["truth_dup"])).sum())
    out["duplicates"] = {"truth": int(df["truth_dup"].sum()), "caught": tp, "false_flags": fp, "missed": fn}
    return out


def acct_metrics(df):
    if df.empty:
        return {}
    lab = df[df["label"].notna()]
    return {"accounts": int(len(df)), "auto_labeled": int(len(lab)), "coverage": round(len(lab) / len(df), 4),
            "precision": round(float((lab["label"] == lab["truth"]).mean()), 4) if len(lab) else None,
            "errors": int((lab["label"] != lab["truth"]).sum()), "to_review": int((df["method"] == "review").sum())}


def receipts_truth(truth_dir, upload):
    rec = json.loads((Path(truth_dir) / "receipts.json").read_text())[upload]["customer_receipts"]
    return round(sum(rec.values()), 2), rec


# --------------------------------------------------------------------------- one brand
def run_brand(slug, split, raw, truth, models, write=True):
    kick = yaml.safe_load((raw / "brand.yaml").read_text())
    mem_path = OUT / "memory" / f"{slug}.json"
    if mem_path.exists():
        mem_path.unlink()
    mem = BrandMemory(mem_path)
    man = manifest(truth)
    br = {"slug": slug, "brand": kick["brand"], "split": split, "uploads": {}}
    for up in UPLOADS:
        r1 = onboard_upload(raw, up, mem, models, OUT / slug / "first_pass" if write else None)
        files = score_files(r1, man)
        lines = score_lines(r1, truth, man)
        accts = score_accounts(r1, truth, man)
        done = resolve(r1, raw, truth, mem, kick)
        if up == "upload_1":     # reviewed-but-uncommitted memory, the baseline for fault injection
            (OUT / "memory" / f"_reviewed_{slug}.json").write_text(json.dumps(mem.data))
        r2 = onboard_upload(raw, up, mem, models, OUT / slug if write else None, commit=True)
        mem.save()
        lines2 = score_lines(r2, truth, man)
        t_total, t_by = receipts_truth(truth, up)
        s2 = r2["summary"]
        br["uploads"][up] = {
            "first_pass": {"status": r1["status"], "failed_checks": r1["failed_checks"],
                           "review_items": r1["open_review_items"], "review_by_kind": r1["counts"]["review_by_kind"],
                           "seconds": r1["seconds"], "checks": r1["checks"], "files": files,
                           "lines": line_metrics(lines), "accounts": acct_metrics(accts)},
            "reviewer_answers": done,
            "final": {"status": r2["status"], "failed_checks": r2["failed_checks"],
                      "review_items": r2["open_review_items"], "checks": r2["checks"],
                      "lines": line_metrics(lines2), "summary": s2},
            "receipts": {"truth_total": t_total, "truth_by_channel": t_by,
                         "pipeline_total": s2.get("customer_receipts_total"),
                         "pipeline_by_channel": s2.get("customer_receipts"),
                         "pipeline_error_pct": round(100 * (s2.get("customer_receipts_total", 0) - t_total) /
                                                     t_total, 3) if t_total else None,
                         "naive_all_deposits": s2.get("naive_receipts_all_deposits"),
                         "naive_overstatement_pct": round(100 * (s2.get("naive_receipts_all_deposits", 0) - t_total)
                                                          / t_total, 1) if t_total else None,
                         "operating_spend": s2.get("operating_spend"), "naive_spend": s2.get("naive_spend")},
            "files_detail": r2["files"],
        }
    return br


# --------------------------------------------------------------------------- faults
FAULTS = [
    ("sum_order_rows", {"sum_order_rows": True}, "order totals summed across line-item rows"),
    ("subtotal_as_total", {"subtotal_as_total": True}, "order subtotal mapped as the order total"),
    ("swap_day_month", {"swap_day_month": True}, "bank dates read day-first instead of month-first"),
    ("drop_payouts", {"drop_types": ["payouts"]}, "Shopify payouts export missing"),
    ("drop_amazon", {"drop_types": ["amazon_flat", "amazon_range"]}, "Amazon settlement export missing"),
    ("drop_faire", {"drop_types": ["faire"]}, "Faire export missing"),
    ("flip_bank_sign", {"flip_bank_sign": True}, "bank amounts exported with outflows positive"),
]


def applicable(fault, man):
    types = {v["source_type"] for k, v in man["files"].items() if k.startswith("upload_1/")}
    metas = [v.get("meta", {}) for k, v in man["files"].items() if k.startswith("upload_1/")]
    if fault == "sum_order_rows":   # only a real error when the export repeats order totals on every line
        return any(v["source_type"] == "orders_list" and v.get("meta", {}).get("totals") == "repeated_per_line"
                   for k, v in man["files"].items() if k.startswith("upload_1/")) and "payouts" in types
    if fault == "subtotal_as_total":
        return "orders_list" in types and "payouts" in types
    if fault == "swap_day_month":
        return any(m.get("date_format") in ("mdy", "mdy_nopad") for v, m in
                   ((v, v.get("meta", {})) for k, v in man["files"].items() if k.startswith("upload_1/")
                    and v["source_type"] == "bank"))
    if fault == "drop_payouts":
        return "payouts" in types
    if fault == "drop_amazon":
        return bool({"amazon_flat", "amazon_range"} & types)
    if fault == "drop_faire":
        return "faire" in types
    return True


def run_faults(models, split_filter):
    rows = []
    for slug, split, raw, truth in brands(split_filter):
        man = manifest(truth)
        snap = OUT / "memory" / f"_reviewed_{slug}.json"
        tmp = OUT / "memory" / f"_fault_{slug}.json"
        fresh = lambda: (tmp.write_text(snap.read_text()), BrandMemory(tmp))[1]
        base = onboard_upload(raw, "upload_1", fresh(), models, None)
        base_failed = set(base["failed_checks"])
        for name, fault, desc in FAULTS:
            if not applicable(name, man):
                continue
            fault = dict(fault)
            if "drop_types" in fault:     # drop by true source type, whatever the brand named the file
                types = fault.pop("drop_types")
                fault["drop_files"] = [k.split("/", 1)[1] for k, v in man["files"].items()
                                       if k.startswith("upload_1/") and v["source_type"] in types]
            mem = fresh()
            r = onboard_upload(raw, "upload_1", mem, models, None, faults=fault)
            new_fail = sorted(set(r["failed_checks"]) - base_failed)
            caught = bool(new_fail)                 # a check failed that passes on the clean files
            held = (not caught and r["status"] != "accepted" and
                    r["open_review_items"] > base["open_review_items"])
            repaired = name == "flip_bank_sign" and bool(r.get("sign_note")) and "corrected" in r["sign_note"]
            rows.append(dict(brand=slug, split=split, fault=name, description=desc, status=r["status"],
                             new_failed_checks=new_fail, baseline_failed=sorted(base_failed),
                             baseline_status=base["status"], blocked=caught, held_for_review=held,
                             repaired=repaired, silently_accepted=r["status"] == "accepted" and not repaired))
        if tmp.exists():
            tmp.unlink()
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- aggregation
def aggregate(results, split):
    rs = [b for b in results if b["split"] == split]
    if not rs:
        return None
    agg = {"brands": len(rs)}
    for up in UPLOADS:
        L = {"lines": 0, "auto": 0, "errors": 0, "review": 0, "by_method": {}}
        A = {"accounts": 0, "auto": 0, "errors": 0}
        F = {"files": 0, "auto": 0, "wrong_auto": 0, "fields_total": 0, "fields_ok": 0, "from_memory": 0}
        items, blocked_first, accepted_final, dups = 0, 0, 0, {"truth": 0, "caught": 0, "false_flags": 0}
        err, naive = [], []
        for b in rs:
            u = b["uploads"][up]
            fp = u["first_pass"]
            lm = fp["lines"]
            L["lines"] += lm["lines"]
            L["auto"] += lm["auto_labeled"]
            L["errors"] += lm["errors"]
            L["review"] += lm["to_review"]
            for m, v in lm["by_method"].items():
                x = L["by_method"].setdefault(m, {"n": 0, "correct": 0})
                x["n"] += v["n"]
                x["correct"] += round(v["n"] * v["precision"])
            am = fp["accounts"]
            if am:
                A["accounts"] += am["accounts"]
                A["auto"] += am["auto_labeled"]
                A["errors"] += am["errors"]
            for f in fp["files"]:
                F["files"] += 1
                F["auto"] += f["auto"]
                F["wrong_auto"] += f["wrong_auto"]
                F["fields_total"] += f["fields_total"]
                F["fields_ok"] += f["fields_ok"]
                F["from_memory"] += f["method"] == "memory"
            items += fp["review_items"]
            blocked_first += fp["status"] == "blocked"
            accepted_final += u["final"]["status"] == "accepted"
            for k in dups:
                dups[k] += lm["duplicates"][k]
            if u["receipts"]["pipeline_error_pct"] is not None:
                err.append(abs(u["receipts"]["pipeline_error_pct"]))
                naive.append(u["receipts"]["naive_overstatement_pct"])
        agg[up] = {
            "lines": L["lines"], "auto_labeled": L["auto"], "coverage": round(L["auto"] / max(1, L["lines"]), 4),
            "precision": round(1 - L["errors"] / max(1, L["auto"]), 4), "label_errors": L["errors"],
            "lines_to_review": L["review"],
            "by_method": {m: {"n": v["n"], "precision": round(v["correct"] / max(1, v["n"]), 4)}
                          for m, v in L["by_method"].items()},
            "accounts": A["accounts"], "accounts_auto": A["auto"], "account_errors": A["errors"],
            "files": F["files"], "files_auto": F["auto"], "files_from_memory": F["from_memory"],
            "files_wrong_but_accepted": F["wrong_auto"],
            "fields_correct": f"{F['fields_ok']}/{F['fields_total']}",
            "review_items_total": items, "review_items_per_brand": round(items / len(rs), 1),
            "brands_blocked_first_pass": blocked_first, "brands_accepted_after_review": accepted_final,
            "duplicates": dups,
            "receipts_abs_error_pct_max": round(max(err), 3) if err else None,
            "naive_overstatement_pct_range": [min(naive), max(naive)] if naive else None,
        }
    return agg


def model_fingerprint():
    fz = json.loads((ROOT / "models" / "frozen.json").read_text())
    now = {k: hashlib.sha256((ROOT / "models" / k).read_bytes()).hexdigest() for k in fz["sha256"]}
    return fz, all(now[k] == fz["sha256"][k] for k in now), now


def fmt_pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def print_summary(results, aggs, faults_df, fz, same):
    print("\n" + "=" * 92)
    print("dtc-cash-onboarding evaluation (synthetic data)")
    print(f"model trained on {len(fz['trained_on'])} brands; line threshold {fz['line_threshold']}, "
          f"account threshold {fz['coa_threshold']}; model files match training record: {same}")
    from freeze import check
    fsame, changed = check()
    if fsame is None:
        print("no pre-holdout freeze recorded")
    elif fsame:
        print("code and models match the pre-holdout freeze (holdout results below are blind)")
    else:
        print(f"CHANGED AFTER THE PRE-HOLDOUT FREEZE: {', '.join(changed)}")
        print("holdout numbers below are therefore NOT blind; the blind run is in evals/results/holdout_v1_frozen/")
    print("=" * 92)
    hdr = f"{'brand':<22}{'split':<8}{'upload':<9}{'1st pass':<23}{'items':>6}{'cover':>8}{'prec':>8}" \
          f"{'final':>11}{'rcpt err':>10}{'naive':>8}"
    print(hdr)
    print("-" * len(hdr))
    for b in results:
        for up in UPLOADS:
            u = b["uploads"][up]
            fp, lm = u["first_pass"], u["first_pass"]["lines"]
            st = fp["status"] + (f" ({','.join(c.replace('_to_bank', '') for c in fp['failed_checks'])})"
                                 if fp["failed_checks"] else "")
            print(f"{b['slug'][:21]:<22}{b['split']:<8}{up:<9}{st[:22]:<23}{fp['review_items']:>6}"
                  f"{fmt_pct(lm['coverage']):>8}{fmt_pct(lm['precision']):>8}{u['final']['status'][:10]:>11}"
                  f"{u['receipts']['pipeline_error_pct']:>9.2f}%{u['receipts']['naive_overstatement_pct']:>7.1f}%")
            if u["final"]["status"] != "accepted":
                print(f"{'':<39}final blocked by: {', '.join(u['final']['failed_checks']) or 'open items'}")
    for split in ("train", "dev", "holdout"):
        a = aggs.get(split)
        if not a:
            continue
        tag = {"train": "TRAIN (in-sample, not a real test)", "dev": "DEV (never trained on)",
               "holdout": "HOLDOUT (written after freeze)"}[split]
        print(f"\n{tag}: {a['brands']} brands")
        for up in UPLOADS:
            x = a[up]
            print(f"  {up}: lines {x['lines']}, auto-labeled {fmt_pct(x['coverage'])} at precision "
                  f"{fmt_pct(x['precision'])} ({x['label_errors']} wrong), {x['lines_to_review']} lines to review; "
                  f"files auto {x['files_auto']}/{x['files']} (memory {x['files_from_memory']}), "
                  f"wrong-but-accepted files {x['files_wrong_but_accepted']}; review items/brand "
                  f"{x['review_items_per_brand']}; blocked {x['brands_blocked_first_pass']}; accepted after review "
                  f"{x['brands_accepted_after_review']}/{a['brands']}; duplicates caught "
                  f"{x['duplicates']['caught']}/{x['duplicates']['truth']} (false flags "
                  f"{x['duplicates']['false_flags']})")
            bm = ", ".join(f"{m} {v['n']} @ {fmt_pct(v['precision'])}" for m, v in x["by_method"].items())
            print(f"           by method: {bm}")
    if faults_df is not None and not faults_df.empty:
        print("\nFault injection (upload 1 after its first review): runs where the fault made a tie-out "
              "fail that passes on the clean files")
        for (fault, desc), g in faults_df.groupby(["fault", "description"], sort=False):
            for split, h in g.groupby("split"):
                if fault == "flip_bank_sign":
                    print(f"  {desc:<50} {split:<8} repaired {int(h['repaired'].sum())}/{len(h)}, "
                          f"blocked {int(h['blocked'].sum())}/{len(h)}")
                else:
                    extra = f", held for review {int(h['held_for_review'].sum())}" if h["held_for_review"].any() else ""
                    print(f"  {desc:<50} {split:<8} blocked {int(h['blocked'].sum())}/{len(h)}{extra}, "
                          f"silently accepted {int(h['silently_accepted'].sum())}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--splits", default="train,dev,holdout")
    a = ap.parse_args()
    t0 = time.time()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / "memory").mkdir()
    RES.mkdir(parents=True, exist_ok=True)
    models = Models.load()
    fz, same, _ = model_fingerprint()
    splits = a.splits.split(",")
    results = [run_brand(slug, split, raw, truth, models) for slug, split, raw, truth in brands(splits)]
    aggs = {s: aggregate(results, s) for s in ("train", "dev", "holdout")}
    faults_df = None if a.quick else run_faults(models, splits)
    print_summary(results, aggs, faults_df, fz, same)
    from freeze import check
    fsame, changed = check()
    out = {"freeze": {"matches": fsame, "changed_after_freeze": changed},
           "model": {k: fz[k] for k in ("line_threshold", "coa_threshold", "target_precision", "trained_on",
                                        "n_training_lines", "n_training_accounts", "cv_line", "cv_coa",
                                        "sha256", "trained_at")},
           "model_files_match_freeze": same, "aggregate": aggs, "brands": results,
           "faults": None if faults_df is None else faults_df.to_dict("records"),
           "runtime_seconds": round(time.time() - t0, 1)}
    (RES / "results.json").write_text(json.dumps(out, indent=1, default=str))
    sys.path.insert(0, str(ROOT / "review"))
    from report import write_reports
    write_reports(out)
    print(f"\nwrote evals/results/results.json, evals/results/results.md and reports/ in {out['runtime_seconds']}s")


if __name__ == "__main__":
    main()
