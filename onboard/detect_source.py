"""
Works out what kind of file this is before mapping it.

Every schema is tried. Each gets a fit score from its column mapping, a small
bonus for telltale header words, and value evidence where headers are not
enough to tell sources apart (a bank export and a card export can share the
exact same three headers; their sign patterns do not).

Built by Avinash Rayudu.
"""
from __future__ import annotations

from dataclasses import dataclass

from map_columns import Mapping, map_columns, norm_header, profile_column
from parse import clean, parse_money
from schemas import COA_TYPE_WORDS, SCHEMAS

DETECT_ACCEPT = 0.6
MARGIN = 0.15


@dataclass
class Detection:
    source_type: str
    confidence: float
    scores: dict
    mapping: Mapping
    reason: str

    def as_dict(self):
        return {"source_type": self.source_type, "confidence": round(self.confidence, 3),
                "scores": {k: round(v, 3) for k, v in sorted(self.scores.items(), key=lambda x: -x[1])},
                "reason": self.reason}


def _minority_sign_share(table, header, decimal_comma=False):
    if header not in table.header:
        return None
    j = table.header.index(header)
    vals = [parse_money(v, decimal_comma) for v in table.column(j)]
    vals = [v for v in vals if v is not None and v != 0]
    if len(vals) < 10:
        return None
    neg = sum(1 for v in vals if v < 0) / len(vals)
    return min(neg, 1 - neg)


def detect(table) -> Detection:
    profiles = [profile_column(table.column(j)) for j in range(len(table.header))]
    htext = " " + " ".join(norm_header(h) for h in table.header) + " "
    results, scores = {}, {}
    for st, schema in SCHEMAS.items():
        m = map_columns(table, st, profiles)
        results[st] = m
        req = [f for f, s in schema["fields"].items() if s["required"]]
        n_req = len(req) + (1 if "one_of" in schema else 0)
        if m.missing_required:
            hit = n_req - len(m.missing_required)
            fit = 0.5 * (hit / n_req) * (sum(m.scores[f] for f in m.fields if f in req) / max(1, hit))
        else:
            fit = m.confidence * 0.6 + 0.4 * (sum(m.scores.values()) / len(m.scores))
        toks = schema.get("tokens", [])
        bonus = 0.3 * sum(1 for t in toks if f" {t} " in htext) / max(1, len(toks))
        scores[st] = fit + bonus

    # value evidence: bank vs card
    for st in ("bank", "card"):
        m = results[st]
        amt_h = m.fields.get("amount")
        if amt_h is None:
            continue
        dc = profiles[table.header.index(amt_h)].decimal_comma
        ms = _minority_sign_share(table, amt_h, dc)
        dir_h = m.fields.get("direction") if st == "bank" else None
        if dir_h:      # unsigned amounts with a DR/CR column: the direction column carries the sign
            vals = [clean(v).upper() for v in table.column(table.header.index(dir_h)) if clean(v)]
            neg = {"DR", "DEBIT", "D", "DBIT"}
            pos = {"CR", "CREDIT", "C", "CRDT"}
            known = [v for v in vals if v in neg | pos]
            if vals and len(known) / len(vals) >= 0.9:
                share = sum(1 for v in known if v in neg) / len(known)
                ms = min(share, 1 - share)
                scores["card"] -= 0.4     # card exports do not carry a DR/CR column
        if ms is None:
            continue
        desc_h = m.fields.get("description")
        varied = desc_h is not None and profiles[table.header.index(desc_h)].n_distinct >= 15
        if not varied:
            scores[st] -= 0.4      # real bank and card memos vary; a short list of labels is something else
        if st == "bank":
            scores[st] += 0.35 if ms > 0.15 else (-0.25 if ms < 0.08 else 0.0)
            if "balance" in m.fields:
                scores[st] += 0.15
        else:
            scores[st] += 0.35 if ms < 0.08 else (-0.35 if ms > 0.15 else 0.0)
    if "debit" in results["bank"].fields and "credit" in results["bank"].fields and not results["bank"].missing_required:
        scores["bank"] += 0.3
    # value evidence: chart of accounts types
    m = results["coa"]
    if "type" in m.fields:
        j = table.header.index(m.fields["type"])
        vals = [clean(v).lower() for v in table.column(j) if clean(v)]
        if vals:
            share = sum(1 for v in vals if v in COA_TYPE_WORDS) / len(vals)
            scores["coa"] += 0.4 * share - (0.3 if share < 0.3 else 0.0)

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    top, top_s = ranked[0]
    second_s = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = top_s - second_s
    conf = min(1.0, top_s) if margin >= MARGIN else min(1.0, top_s) * (margin / MARGIN)
    reason = f"top={top} ({top_s:.2f}) next={ranked[1][0]} ({second_s:.2f})"
    return Detection(top, conf, scores, results[top], reason)
