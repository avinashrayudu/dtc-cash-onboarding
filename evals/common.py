"""
Shared helpers for training and evaluation. This is the only code that reads
ground truth; nothing under onboard/ imports it.

Built by Avinash Rayudu.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "onboard"))

from map_columns import Mapping        # noqa: E402
from readers import read_any           # noqa: E402
from transform import TRANSFORMS       # noqa: E402

SPLITS = {"train": ROOT / "data" / "raw", "dev": ROOT / "data" / "raw", "holdout": ROOT / "data" / "holdout" / "raw"}
TRUTH = {"train": ROOT / "evals" / "ground_truth", "dev": ROOT / "evals" / "ground_truth",
         "holdout": ROOT / "evals" / "ground_truth_holdout"}


def brands(split=None):
    """Yields (slug, split, raw_dir, truth_dir)."""
    seen = []
    for sp in ("train", "dev", "holdout"):
        troot = TRUTH[sp]
        if not troot.exists():
            continue
        for man in sorted(troot.glob("*/manifest.json")):
            m = json.loads(man.read_text())
            if m["split"] != sp or (split and sp not in ([split] if isinstance(split, str) else split)):
                continue
            if m["slug"] in seen:
                continue
            seen.append(m["slug"])
            yield m["slug"], sp, SPLITS[sp] / m["slug"], man.parent


def manifest(truth_dir):
    return json.loads((Path(truth_dir) / "manifest.json").read_text())


def truth_rows(truth_dir, key):
    p = Path(truth_dir) / "rows" / (key + ".csv")
    return pd.read_csv(p) if p.exists() else None


def labeled_lines(raw_dir, truth_dir):
    """Parses bank and card files with the TRUE mapping and attaches true labels (training data)."""
    kickoff = yaml.safe_load((Path(raw_dir) / "brand.yaml").read_text())
    m = manifest(truth_dir)
    out = []
    for key, info in m["files"].items():
        st = info["source_type"]
        if st not in ("bank", "card"):
            continue
        tab = read_any(Path(raw_dir) / key)
        mp = Mapping(st, info["column_map"], {}, [], 1.0)
        if st == "bank":
            df, _ = TRANSFORMS[st](tab, mp, kickoff)
        else:
            df, _ = TRANSFORMS[st](tab, mp)
            df["amount"] = df["charge"]
        tr = truth_rows(truth_dir, key)
        df = df.merge(tr[["label", "is_duplicate"]], left_on="row", right_index=True, how="left")
        df["src"] = "BANK" if st == "bank" else "CARD"
        df["key"] = key
        out.append(df[["key", "row", "src", "date", "amount", "description", "label", "is_duplicate"]])
    return pd.concat(out, ignore_index=True), kickoff


def labeled_accounts(raw_dir, truth_dir):
    m = manifest(truth_dir)
    out = []
    for key, info in m["files"].items():
        if info["source_type"] != "coa":
            continue
        tab = read_any(Path(raw_dir) / key)
        df, _ = TRANSFORMS["coa"](tab, Mapping("coa", info["column_map"], {}, [], 1.0))
        tr = truth_rows(truth_dir, key)
        df = df.merge(tr[["label"]], left_on="row", right_index=True, how="left")
        df["key"] = key
        out.append(df)
    return pd.concat(out, ignore_index=True)
