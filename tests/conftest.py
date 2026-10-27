import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in ("onboard", "evals", "review"):
    sys.path.insert(0, str(ROOT / p))
