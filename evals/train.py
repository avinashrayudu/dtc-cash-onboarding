"""
Trains the line model and the chart-of-accounts model on the 7 training brands,
picks each abstain threshold with leave-one-brand-out cross-validation, and
freezes everything into models/ with a SHA-256 of each model file.

Threshold rule, decided before looking at any development or holdout brand:
the smallest threshold whose accepted predictions reach 99% precision on brands
the model did not train on. Lower thresholds auto-label more lines; this is the
lowest one that still meets the precision bar.

Built by Avinash Rayudu.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, brands, labeled_accounts, labeled_lines   # noqa: E402

from classify_lines import choose_threshold, coa_features, line_features, make_model   # noqa: E402

TARGET_PRECISION = 0.99


def build_sets():
    lines, accts = [], []
    for slug, split, raw, truth in brands("train"):
        df, kickoff = labeled_lines(raw, truth)
        df = df[~df["is_duplicate"].astype(bool)].copy()
        df["text"] = [line_features(s, a, d, kickoff) for s, a, d in zip(df["src"], df["amount"], df["description"])]
        df["brand"] = slug
        lines.append(df)
        a = labeled_accounts(raw, truth)
        a = a.drop_duplicates(subset=["name", "type"])
        a["text"] = [coa_features(n, t) for n, t in zip(a["name"], a["type"])]
        a["brand"] = slug
        accts.append(a)
    return pd.concat(lines, ignore_index=True), pd.concat(accts, ignore_index=True)


def lobo(df, make):
    conf, correct = [], []
    per = {}
    for b in sorted(df["brand"].unique()):
        tr, te = df[df["brand"] != b], df[df["brand"] == b]
        m = make()
        m.fit(tr["text"], tr["label"])
        p = m.predict_proba(te["text"])
        idx = p.argmax(axis=1)
        pred = m.classes_[idx]
        c = p[np.arange(len(idx)), idx]
        ok = pred == te["label"].values
        conf.extend(c.tolist())
        correct.extend(ok.tolist())
        per[b] = {"n": int(len(te)), "accuracy_no_abstain": round(float(ok.mean()), 4)}
    return np.array(conf), np.array(correct), per


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    out = ROOT / "models"
    out.mkdir(exist_ok=True)
    lines, accts = build_sets()
    print(f"training lines: {len(lines)} from {lines['brand'].nunique()} brands, "
          f"{lines['label'].nunique()} labels; accounts: {len(accts)}")

    conf, correct, per = lobo(lines, make_model)
    th_line, curve_line = choose_threshold(conf, correct, TARGET_PRECISION)
    print(f"line model, leave-one-brand-out: accuracy without abstaining {correct.mean():.4f}; "
          f"threshold for {TARGET_PRECISION:.0%} precision = {th_line}")
    conf_a, correct_a, per_a = lobo(accts, lambda: make_model(C=10.0))
    th_coa, curve_coa = choose_threshold(conf_a, correct_a, TARGET_PRECISION)
    print(f"account model, leave-one-brand-out: accuracy without abstaining {correct_a.mean():.4f}; "
          f"threshold = {th_coa}")

    lm = make_model()
    lm.fit(lines["text"], lines["label"])
    am = make_model(C=10.0)
    am.fit(accts["text"], accts["label"])
    joblib.dump(lm, out / "line_model.joblib")
    joblib.dump(am, out / "coa_model.joblib")
    pick = lambda curve, t: next((r for r in curve if r[0] == t), None)
    frozen = {
        "line_threshold": th_line, "coa_threshold": th_coa, "target_precision": TARGET_PRECISION,
        "trained_on": sorted(lines["brand"].unique().tolist()),
        "n_training_lines": int(len(lines)), "n_training_accounts": int(len(accts)),
        "cv_line": {"accuracy_no_abstain": round(float(correct.mean()), 4), "per_brand": per,
                    "at_threshold": pick(curve_line, th_line)},
        "cv_coa": {"accuracy_no_abstain": round(float(correct_a.mean()), 4), "per_brand": per_a,
                   "at_threshold": pick(curve_coa, th_coa)},
        "curve_line": curve_line, "curve_coa": curve_coa,
        "sha256": {"line_model.joblib": sha(out / "line_model.joblib"), "coa_model.joblib": sha(out / "coa_model.joblib")},
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "frozen.json").write_text(json.dumps(frozen, indent=2))
    print(f"saved models/ (line sha {frozen['sha256']['line_model.joblib'][:12]}, "
          f"coa sha {frozen['sha256']['coa_model.joblib'][:12]})")


if __name__ == "__main__":
    main()
