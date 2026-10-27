"""Memory behavior, the end-to-end workflow, and guarantees about what the pipeline can see."""
import json
import re
from pathlib import Path

import yaml

from common import ROOT, brands
from llm_fallback import build_prompt, parse_reply
from memory import BrandMemory, line_key_tokens, raw_tokens
from readers import read_any

KICK = {"brand": "Quillon Coffee Roasters", "own_accounts": {"operating_last4": "1234", "savings_last4": "9876"}}


def _stable(*texts):
    from collections import Counter
    c = Counter()
    for t in texts:
        c.update(raw_tokens(t, KICK))
    return {t for t, n in c.items() if n >= 2}


def test_reference_ids_do_not_split_one_kind_of_line():
    a, b = "FACEBK *RU98B3XQ fb.me/ads CA", "FACEBK *K2W7P0LM fb.me/ads CA"
    st = _stable(a, b)
    assert line_key_tokens("CARD", 50, a, KICK, st) == line_key_tokens("CARD", 50, b, KICK, st)


def test_different_vendors_with_same_boilerplate_do_not_collide():
    freight = "ORIG CO NAME:SALTBOX FREIGHT ORIG ID:9814493820 CO ENTRY DESCR:INVOICE SEC:CCD"
    threepl = "ORIG CO NAME:BUNDLE & SHIP ORIG ID:6455442398 CO ENTRY DESCR:INVOICE SEC:CCD"
    st = _stable(freight, freight.replace("9814493820", "9090854378"), threepl, threepl.replace("6455", "2046"))
    m = BrandMemory(Path("/nonexistent/x.json"))
    m.remember_line(line_key_tokens("BANK", -10, threepl, KICK, st), "fulfillment_3pl")
    assert m.recall_line(line_key_tokens("BANK", -10, freight, KICK, st)) is None


def test_conflicting_memory_stays_silent():
    m = BrandMemory(Path("/nonexistent/x.json"))
    k = frozenset({"ACME", "INVOICE", "__BANK_NEG"})
    m.remember_line(k, "rent")
    m.remember_line(k, "software_opex")
    assert m.recall_line(k) is None


def test_pipeline_never_reads_ground_truth():
    for p in (ROOT / "onboard").glob("*.py"):
        src = p.read_text()
        assert "ground_truth" not in src and "truth_rows" not in src, p.name


def test_llm_prompt_holds_shapes_not_values():
    raw = [b for b in brands("dev") if b[0] == "quillon-coffee"][0][2]
    t = read_any(raw / "upload_1" / "bank_operating_1.csv")
    prompt = build_prompt(t)
    memo = t.rows[0][2]
    assert memo not in prompt
    cols = json.loads(prompt.split("COLUMNS: ", 1)[1].split("\n", 1)[0])
    for c in cols:                                          # shapes only: every digit is a 9, no real amounts
        assert all(not re.search(r"[0-8]", s) for s in c["shapes"]), c
    good = json.dumps({"source_type": "bank", "fields": {"date": "Posting Date", "description": "Description",
                                                         "amount": "Amount", "balance": "Balance"},
                       "confidence": 0.9})
    m = parse_reply(good, t)
    assert m is not None and m.fields["amount"] == "Amount"
    bad = json.dumps({"source_type": "bank", "fields": {"date": "Description", "description": "Posting Date",
                                                        "amount": "Amount"}, "confidence": 0.9})
    assert parse_reply(bad, t) is None                      # value checks reject swapped columns
    assert parse_reply("not json", t) is None


def test_end_to_end_review_then_memory(tmp_path):
    """A dev brand: first pass needs review, after the simulated review it is accepted, and upload 2 asks less."""
    from pipeline import Models, onboard_upload
    from resolve import resolve
    slug, split, raw, truth = [b for b in brands("dev") if b[0] == "quillon-coffee"][0]
    kick = yaml.safe_load((raw / "brand.yaml").read_text())
    mem = BrandMemory(tmp_path / "m.json")
    models = Models.load()
    r1 = onboard_upload(raw, "upload_1", mem, models)
    assert r1["open_review_items"] > 0
    resolve(r1, raw, truth, mem, kick)
    r2 = onboard_upload(raw, "upload_1", mem, models, commit=True)
    assert r2["status"] == "accepted"
    r3 = onboard_upload(raw, "upload_2", mem, models)
    assert r3["open_review_items"] < r1["open_review_items"]
    assert r3["counts"]["duplicates_skipped"] > 0
    assert all(f["method"] == "memory" for f in r3["files"])
