"""
Simulated reviewer.

In real onboarding a person works the review queue. To measure the workflow on
synthetic brands, this module plays that person: it answers each review item
from ground truth and writes the answer into the brand's memory, exactly as a
reviewer's click would. It is the only part of the workflow that reads ground
truth, and it is never used on real data.

Built by Avinash Rayudu.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "onboard"))
sys.path.insert(0, str(ROOT / "evals"))

from common import manifest, truth_rows          # noqa: E402
from readers import read_any                     # noqa: E402


PAYOUTS = ("processor_payout", "marketplace_payout", "wholesale_payout")


def resolve(result: dict, brand_dir: Path, truth_dir: Path, memory, kickoff: dict) -> dict:
    """Answers every open review item from ground truth. Returns counts by kind."""
    upload = result["upload"]
    man = manifest(truth_dir)
    frames = result["_frames"]
    lookup = {}
    for src, df in (("BANK", frames["bank"]), ("CARD", frames["card"])):
        if df is None or df.empty:
            continue
        for r in df.to_dict("records"):
            lookup[(r["file"], int(r["row"]))] = (src, r)
    done = {"file": 0, "line": 0, "account": 0, "unresolved": 0}
    truth_cache = {}

    def tr(file):
        key = f"{upload}/{file}"
        if key not in truth_cache:
            truth_cache[key] = truth_rows(truth_dir, key)
        return truth_cache[key]

    for item in frames["review"]:
        kind, file = item["kind"], item["file"]
        key = f"{upload}/{file}"
        if kind == "file":
            info = man["files"].get(key)
            if not info:
                done["unresolved"] += 1
                continue
            sig = read_any(Path(brand_dir) / upload / file).signature()
            memory.remember_layout(sig, info["source_type"], info["column_map"], "reviewer")
            done["file"] += 1
        elif kind == "line":
            t = tr(file)
            hit = lookup.get((file, int(item["row"])))
            if t is None or hit is None:
                done["unresolved"] += 1
                continue
            src, r = hit
            label = t.loc[int(item["row"]), "label"]
            key = frozenset(r["mem_key"].split("|")) if r.get("mem_key") else frozenset()
            if key:
                memory.remember_line(key, label)
                cp = str(t.loc[int(item["row"])].get("counterparty", "")).lower()
                has_importer = any(x in cp for x in ("shopify", "amazon", "faire"))
                if "no payout export" in item["what"] and label in PAYOUTS and not has_importer:
                    # real customer money from a source this pipeline cannot import yet (e.g. PayPal):
                    # confirm it as a logged exception. For Shopify, Amazon or Faire a person asks for the file.
                    memory.confirm_no_export(key)
                done["line"] += 1
            else:
                done["unresolved"] += 1     # nothing stable to remember; the answer applies to this line only
        elif kind == "account":
            t = tr(file)
            coa = frames["coa"]
            row = coa[(coa["file"] == file) & (coa["row"] == int(item["row"]))]
            if t is None or row.empty:
                done["unresolved"] += 1
                continue
            r = row.iloc[0]
            memory.remember_coa(r["name"], r["type"], t.loc[int(item["row"]), "label"])
            done["account"] += 1
    return done
