"""
Per-brand memory, so a brand is never asked the same question twice.

Stores, per brand:
  layouts       file signature -> confirmed source type and column mapping
  lines         reviewer-confirmed meaning for a kind of bank or card line
  coa           reviewer-confirmed category for an account name
  fingerprints  lines already ingested, so overlapping exports are not double counted

Line memory matches exactly on a line's stable words: words that recur across
the upload or are already known. One-off reference IDs drop out, so
"FACEBK *RU98B3XQ" and "FACEBK *K2W7P0LM" share a key, while two invoices that
differ only by company name do not. If remembered answers disagree for one key,
memory stays silent and the line goes back to a person.

Built by Avinash Rayudu.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from classify_lines import norm_text

MIN_CONTENT_TOKENS = 2


def raw_tokens(text, kickoff) -> set:
    """Words of a normalized line, minus anything holding a digit (dates, amounts, reference numbers)."""
    t = norm_text(text, kickoff)
    return {w for w in t.split() if len(w) > 1 and not re.search(r"0", w)}


def line_key_tokens(src: str, amount: float, text: str, kickoff, stable=None) -> frozenset:
    """
    Memory key for a line: its stable words plus source and direction. A word is stable when it
    recurs across lines of the upload or is already known to memory; one-off words are almost
    always reference IDs, so they are left out. Returns an empty key when too little is left.
    """
    toks = raw_tokens(text, kickoff)
    if stable is not None:
        toks = {w for w in toks if w in stable}
    if len(toks) < MIN_CONTENT_TOKENS:
        return frozenset()
    toks.add(f"__{src}_{'POS' if amount > 0 else 'NEG'}")
    return frozenset(toks)


def fingerprint(src, row) -> str:
    bal = row.get("balance")
    bal = "" if bal is None or bal != bal else f"{bal:.2f}"
    acct = row.get("account", "")
    return f"{src}|{acct}|{row['date']}|{row['amount']:.2f}|{str(row['description']).strip()}|{bal}"


class BrandMemory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = {"layouts": {}, "lines": [], "coa": {}, "fingerprints": {}, "confirmed_no_export": []}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
        self.data.setdefault("confirmed_no_export", [])
        self._index = None

    # layouts
    def layout(self, signature):
        return self.data["layouts"].get(signature)

    def remember_layout(self, signature, source_type, fields, decided_by):
        self.data["layouts"][signature] = {"source_type": source_type, "fields": fields, "decided_by": decided_by}

    # lines
    def _build(self):
        self._index = [(frozenset(e["tokens"]), e["label"]) for e in self.data["lines"]]

    def recall_line(self, tokens: frozenset):
        """Exact match on the stable-word key. Conflicting answers for one key return None."""
        if self._index is None:
            self._build()
        if not tokens:
            return None
        hits = {label for toks, label in self._index if toks == tokens}
        return next(iter(hits)) if len(hits) == 1 else None

    def vocabulary(self) -> set:
        return {t for e in self.data["lines"] for t in e["tokens"]}

    def remember_line(self, tokens: frozenset, label: str):
        self.data["lines"].append({"tokens": sorted(tokens), "label": label})
        self._index = None

    def confirm_no_export(self, tokens: frozenset):
        """A reviewer confirmed this kind of deposit is real customer money with no export available."""
        k = "|".join(sorted(tokens))
        if k and k not in self.data["confirmed_no_export"]:
            self.data["confirmed_no_export"].append(k)

    def is_confirmed_no_export(self, key: str) -> bool:
        return bool(key) and key in self.data["confirmed_no_export"]

    # chart of accounts
    @staticmethod
    def coa_key(name, typ):
        return f"{str(name).strip().lower()}|{str(typ).strip().lower()}"

    def recall_coa(self, name, typ):
        return self.data["coa"].get(self.coa_key(name, typ))

    def remember_coa(self, name, typ, label):
        self.data["coa"][self.coa_key(name, typ)] = label

    # duplicates across uploads
    def seen_counts(self, src) -> Counter:
        return Counter(self.data["fingerprints"].get(src, {}))

    def add_fingerprints(self, src, fps):
        c = Counter(self.data["fingerprints"].get(src, {}))
        c.update(fps)
        self.data["fingerprints"][src] = dict(c)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True, default=str))
