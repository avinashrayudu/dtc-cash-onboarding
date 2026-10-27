"""
Column profiling and mapping.

For every column the profiler measures what the values look like. The mapper
then scores each (standard field, column) pair on two kinds of evidence:
  header evidence  how close the header text is to names used for that field
  value evidence   whether the values are the right kind (dates, money, IDs, text)
A column is only accepted when both agree. Value evidence alone can never map a
column, because a money column is a money column whether it is "fees" or "net".

Built by Avinash Rayudu.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from parse import clean, date_parts, looks_decimal_comma, numeric_rate, parse_money
from schemas import SCHEMAS

ACCEPT = 0.55          # field-level acceptance score
HEADER_W, VALUE_W = 0.65, 0.35


def norm_header(h: str) -> str:
    h = h.lower().replace("#", " number ").replace("&", " and ")
    h = re.sub(r"\(.*?\)", lambda m: " " + m.group(0)[1:-1] + " ", h)
    h = re.sub(r"[^a-z0-9]+", " ", h)
    return re.sub(r"\s+", " ", h).strip()


@dataclass
class Profile:
    n: int
    filled: float
    date_rate: float
    num_rate: float
    decimal_share: float
    int_like: float
    text_rate: float
    avg_len: float
    distinct: float
    n_distinct: int
    neg_share: float
    decimal_comma: bool


def profile_column(values) -> Profile:
    vals = [clean(v) for v in values]
    non = [v for v in vals if v]
    n = len(vals)
    if not non:
        return Profile(n, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, False)
    sample = non[:400]
    dc = looks_decimal_comma(sample)
    nums = [parse_money(v, dc) for v in sample]
    num_ok = [x for x in nums if x is not None]
    dates = [date_parts(v) for v in sample]
    date_rate = sum(1 for d in dates if d is not None) / len(sample)
    num_rate = len(num_ok) / len(sample)
    if date_rate > 0.8:
        num_rate = 0.0
    dec = sum(1 for v in sample if re.search(r"[.,]\d{1,2}\)?-?$", v)) / len(sample)
    int_like = sum(1 for v in sample if re.fullmatch(r"-?\d+", v)) / len(sample)
    text_rate = sum(1 for v, x, d in zip(sample, nums, dates) if x is None and d is None) / len(sample)
    distinct_vals = set(non)
    neg = sum(1 for x in num_ok if x < 0) / max(1, len(num_ok))
    return Profile(n=n, filled=len(non) / n, date_rate=date_rate, num_rate=num_rate, decimal_share=dec,
                   int_like=int_like, text_rate=text_rate, avg_len=sum(map(len, sample)) / len(sample),
                   distinct=len(distinct_vals) / len(non), n_distinct=len(distinct_vals), neg_share=neg,
                   decimal_comma=dc)


def header_score(syns, header: str) -> float:
    h = norm_header(header)
    if not h:
        return 0.0
    ht = set(h.split())
    best = 0.0
    for s in syns:
        if h == s:
            return 1.0
        st = set(s.split())
        jac = len(ht & st) / len(ht | st)
        contain = 0.8 if st <= ht else 0.0
        if contain and len(ht) > len(st) + 2:
            contain = 0.65
        r = difflib.SequenceMatcher(None, h, s).ratio()
        sim = r * 0.9 if r > 0.8 else r * 0.4
        best = max(best, jac, contain, sim)
    return best


def value_fit(kind: str, p: Profile) -> float:
    if p.filled == 0:
        return 0.0
    if kind == "date":
        return p.date_rate
    if kind == "money":
        return p.num_rate * (0.55 + 0.45 * p.decimal_share) * (1.0 - 0.5 * (p.int_like > 0.9 and p.avg_len > 7))
    if kind == "int":
        return p.int_like
    if kind == "id":
        return min(1.0, 0.4 + 0.6 * p.distinct) * (1.0 if p.date_rate < 0.5 else 0.2) * \
               (0.6 if p.num_rate > 0.9 and p.decimal_share > 0.5 else 1.0)
    if kind == "text":
        return p.text_rate * min(1.0, p.avg_len / 8.0) * (0.5 + 0.5 * min(1.0, p.n_distinct / 5.0))
    if kind == "any":
        return p.filled
    if kind == "enum":
        return p.text_rate * (1.0 if p.n_distinct <= 25 else 0.4)
    return 0.0


@dataclass
class Mapping:
    source_type: str
    fields: dict          # field -> header
    scores: dict          # field -> score
    missing_required: list
    confidence: float

    def as_dict(self):
        return {"source_type": self.source_type, "fields": self.fields,
                "scores": {k: round(v, 3) for k, v in self.scores.items()},
                "missing_required": self.missing_required, "confidence": round(self.confidence, 3)}


def map_columns(table, source_type: str, profiles=None) -> Mapping:
    schema = SCHEMAS[source_type]
    profiles = profiles or [profile_column(table.column(j)) for j in range(len(table.header))]
    cands = []
    for f, spec in schema["fields"].items():
        for j, h in enumerate(table.header):
            hs = header_score(spec["syn"], h)
            if hs < 0.3:
                continue
            vs = value_fit(spec["kind"], profiles[j])
            score = HEADER_W * hs + VALUE_W * vs
            if vs < 0.25:
                score *= 0.5
            cands.append((score, hs, f, j))
    cands.sort(key=lambda x: (-x[0], -x[1]))
    used_f, used_c = set(), set()
    fields, scores = {}, {}
    for score, hs, f, j in cands:
        if f in used_f or j in used_c or score < 0.3:
            continue
        used_f.add(f)
        used_c.add(j)
        fields[f] = table.header[j]
        scores[f] = score
    # drop weak mappings
    for f in list(fields):
        if scores[f] < ACCEPT:
            del fields[f]
    req = [f for f, s in schema["fields"].items() if s["required"]]
    missing = [f for f in req if f not in fields]
    if "one_of" in schema:
        if not any(all(x in fields for x in group) for group in schema["one_of"]):
            missing.append("|".join("+".join(g) for g in schema["one_of"]))
    req_scores = [scores[f] for f in req if f in fields]
    if "one_of" in schema:
        for group in schema["one_of"]:
            if all(x in fields for x in group):
                req_scores.append(min(scores[x] for x in group))
                break
    conf = 0.0 if missing else (min(req_scores) if req_scores else 0.0)
    return Mapping(source_type, fields, scores, missing, conf)
