"""
Optional language-model fallback for files the rules cannot recognize. Off by default.

Design rules:
  * The model never sees a row of data. It sees headers and a value *shape* per
    column ("9999-99-99", "-9999.99", "Xxxxx Xxxxx"), plus what the profiler measured.
  * Its answer is a suggestion. The suggested mapping is re-scored with the same
    value checks the rules use, and anything that fails is dropped.
  * A file mapped this way still has to pass the tie-outs like any other file, and
    its layout is not saved to memory automatically.

To use it, pass a client with a `complete(prompt: str) -> str` method, or set
LLM_PROVIDER=anthropic and LLM_MODEL=<model name> with ANTHROPIC_API_KEY in the
environment and call `client_from_env()`.

This path is not used in the evaluation; every reported number comes from the
rules, the model in models/ and the tie-outs.

Built by Avinash Rayudu.
"""
from __future__ import annotations

import json
import os
import re

from map_columns import ACCEPT, Mapping, profile_column, value_fit
from schemas import SCHEMAS


def shape(v: str) -> str:
    s = re.sub(r"[A-Z]", "X", str(v))
    s = re.sub(r"[a-z]", "x", s)
    s = re.sub(r"\d", "9", s)
    s = re.sub(r"x{4,}", "xxxx", s)
    s = re.sub(r"X{4,}", "XXXX", s)
    s = re.sub(r"9{5,}", "99999", s)
    return s[:40]


def build_prompt(table) -> str:
    cols = []
    for j, h in enumerate(table.header):
        vals = [v for v in table.column(j) if v][:200]
        p = profile_column(vals)
        shapes = sorted({shape(v) for v in vals[:50]})[:3]
        cols.append({"header": h, "shapes": shapes, "date_rate": round(p.date_rate, 2),
                     "numeric_rate": round(p.num_rate, 2), "negative_share": round(p.neg_share, 2),
                     "distinct_share": round(p.distinct, 2)})
    schema = {st: list(s["fields"]) for st, s in SCHEMAS.items()}
    return (
        "You map financial export files for consumer brands to a standard schema.\n"
        "Here are the file's columns. You see header text and value shapes only, never values.\n"
        f"COLUMNS: {json.dumps(cols)}\n"
        f"SCHEMAS (source_type -> fields): {json.dumps(schema)}\n"
        'Reply with JSON only: {"source_type": "...", "fields": {"<field>": "<exact header>"}, '
        '"confidence": 0.0-1.0}. Use only headers that appear above. If unsure, return '
        '{"source_type": null}.'
    )


def parse_reply(reply: str, table):
    """Validates a reply against the file and the schema, re-scoring every field on its values."""
    m = re.search(r"\{.*\}", reply or "", re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    st = obj.get("source_type")
    if st not in SCHEMAS:
        return None
    schema = SCHEMAS[st]
    fields, scores = {}, {}
    for f, h in (obj.get("fields") or {}).items():
        if f not in schema["fields"] or h not in table.header or h in fields.values():
            continue
        vs = value_fit(schema["fields"][f]["kind"], profile_column(table.column(table.header.index(h))))
        if vs >= 0.5:
            fields[f] = h
            scores[f] = vs
    req = [f for f, s in schema["fields"].items() if s["required"]]
    missing = [f for f in req if f not in fields]
    if "one_of" in schema and not any(all(x in fields for x in g) for g in schema["one_of"]):
        missing.append("one_of")
    if missing:
        return None
    conf = min(float(obj.get("confidence", 0) or 0), min(scores.values()))
    if conf < ACCEPT:
        return None
    return Mapping(st, fields, scores, [], conf)


def suggest_mapping(table, client):
    try:
        return parse_reply(client.complete(build_prompt(table)), table)
    except Exception:
        return None


class _AnthropicClient:
    def __init__(self, model: str):
        import anthropic   # imported only when this optional path is used
        self.client = anthropic.Anthropic()
        self.model = model

    def complete(self, prompt: str) -> str:
        msg = self.client.messages.create(model=self.model, max_tokens=800,
                                          messages=[{"role": "user", "content": prompt}])
        return "".join(getattr(b, "text", "") for b in msg.content)


def client_from_env():
    provider = os.environ.get("LLM_PROVIDER")
    model = os.environ.get("LLM_MODEL")
    if provider == "anthropic" and model:
        return _AnthropicClient(model)
    return None
