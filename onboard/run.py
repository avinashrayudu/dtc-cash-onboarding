"""
Command line entry point.

  python onboard/run.py data/raw/fernwood-goods upload_1
      onboards one upload, writes out/<brand>/upload_1/{ledger.csv, review_queue.csv, result.json}

  python onboard/run.py data/raw/fernwood-goods upload_1 --commit
      same, and records the upload in the brand's memory (layouts and ingested lines)

Built by Avinash Rayudu.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from memory import BrandMemory                 # noqa: E402
from pipeline import ROOT, Models, onboard_upload   # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Onboard one upload of a brand's exports.")
    ap.add_argument("brand_dir")
    ap.add_argument("upload")
    ap.add_argument("--out", default=str(ROOT / "out"))
    ap.add_argument("--commit", action="store_true", help="record this upload in the brand's memory")
    a = ap.parse_args()
    brand_dir = Path(a.brand_dir)
    slug = brand_dir.name
    mem = BrandMemory(Path(a.out) / "memory" / f"{slug}.json")
    r = onboard_upload(brand_dir, a.upload, mem, Models.load(), Path(a.out) / slug, commit=a.commit)
    if a.commit:
        mem.save()
    print(f"{r['brand']} {a.upload}: {r['status']}  ({r['open_review_items']} review items, {r['seconds']}s)")
    for c in r["checks"]:
        print(f"  [{c['status']:>4}] {c['name']}: {c['detail']}")
    print(f"outputs in {Path(a.out) / slug / a.upload}")


if __name__ == "__main__":
    main()
