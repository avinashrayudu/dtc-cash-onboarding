"""
Freezes the onboarding code and models before the holdout brands exist.

  python evals/freeze.py           writes evals/FREEZE.json (hashes of every onboard/*.py and model file)
  python evals/freeze.py --check   compares the current code and models with the freeze

run_evals.py prints the check result, so any change made after the freeze shows up
next to the holdout numbers.

Built by Avinash Rayudu.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FREEZE = ROOT / "evals" / "FREEZE.json"


def current():
    files = sorted((ROOT / "onboard").glob("*.py")) + sorted((ROOT / "models").glob("*.joblib"))
    h = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    combined = hashlib.sha256("".join(f"{k}:{v}" for k, v in sorted(h.items())).encode()).hexdigest()
    return h, combined


def check():
    if not FREEZE.exists():
        return None, []
    fz = json.loads(FREEZE.read_text())
    h, combined = current()
    changed = sorted(k for k in set(h) | set(fz["files"]) if h.get(k) != fz["files"].get(k))
    return combined == fz["combined"], changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        same, changed = check()
        print("no freeze recorded" if same is None else ("matches freeze" if same else f"changed: {changed}"))
        sys.exit(0 if same else 1)
    h, combined = current()
    FREEZE.write_text(json.dumps({"frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                  "combined": combined, "files": h}, indent=2))
    print(f"frozen {len(h)} files, combined sha256 {combined[:16]}")


if __name__ == "__main__":
    main()
