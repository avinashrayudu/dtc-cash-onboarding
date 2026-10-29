"""
Runs holdout v2 once, blind, and keeps the result untouched.

  python evals/run_holdout_v2.py

Refuses to run if any onboard/*.py or model file differs from evals/FREEZE_v2.json,
and refuses to overwrite evals/results/holdout_v2_blind/ once it exists. Same
workflow and scoring as run_evals.py: first pass measured before any review,
then the simulated review, then the final status.

Built by Avinash Rayudu.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, brands                                         # noqa: E402
from freeze import check                                                # noqa: E402
import run_evals as R                                                   # noqa: E402

DEST = ROOT / "evals" / "results" / "holdout_v2_blind"


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def main():
    same, changed = check(ROOT / "evals" / "FREEZE_v2.json")
    if not same:
        sys.exit(f"code or models changed since FREEZE_v2.json ({changed}); a blind run is no longer possible")
    if DEST.exists():
        sys.exit(f"{DEST.relative_to(ROOT)} already exists; holdout v2 runs once")
    t0 = time.time()
    R.OUT.mkdir(exist_ok=True)
    (R.OUT / "memory").mkdir(exist_ok=True)
    models = R.Models.load()
    results = [R.run_brand(slug, split, raw, truth, models) for slug, split, raw, truth in brands("holdout_v2")]
    agg = R.aggregate(results, "holdout_v2")
    DEST.mkdir(parents=True)
    out = {"ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "freeze": {"file": "evals/FREEZE_v2.json", "matches": True},
           "aggregate": agg, "brands": results, "runtime_seconds": round(time.time() - t0, 1)}
    (DEST / "results.json").write_text(json.dumps(out, indent=1, default=str))

    md = ["# Holdout v2, blind run", "",
          f"Run once on {out['ran_at']} against the code and models recorded in `evals/FREEZE_v2.json`. "
          "Nothing in this folder is edited after the run.", "",
          "| brand | upload | first-pass status | failed checks | auto-labeled | precision | wrong labels | "
          "review items | final status |",
          "|---|---|---|---|---|---|---|---|---|"]
    for b in results:
        for up in R.UPLOADS:
            u = b["uploads"][up]
            fp, lm = u["first_pass"], u["first_pass"]["lines"]
            md.append(f"| {b['slug']} | {up} | {fp['status']} | {', '.join(fp['failed_checks']) or '-'} | "
                      f"{pct(lm.get('coverage'))} | {pct(lm.get('precision'))} | {lm.get('errors', 'n/a')} | {fp['review_items']} | "
                      f"{u['final']['status']}"
                      + (f" ({', '.join(u['final']['failed_checks'])})" if u['final']['failed_checks'] else "") + " |")
    md += ["", "## All three brands", "", "| upload | lines | auto-labeled | precision | wrong labels | "
           "review items per brand | blocked on first pass | accepted after review |", "|---|---|---|---|---|---|---|---|"]
    for up in R.UPLOADS:
        x = agg[up]
        md.append(f"| {up} | {x['lines']} | {pct(x['coverage'])} | {pct(x['precision'])} | {x['label_errors']} | "
                  f"{x['review_items_per_brand']} | {x['brands_blocked_first_pass']} | "
                  f"{x['brands_accepted_after_review']}/{agg['brands']} |")
    (DEST / "summary.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    print(f"\nwrote {DEST.relative_to(ROOT)} in {out['runtime_seconds']}s")


if __name__ == "__main__":
    main()
