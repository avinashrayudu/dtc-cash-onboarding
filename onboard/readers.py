"""
Reads whatever file a brand sends: CSV, tab-separated .txt, semicolon CSV or .xlsx.

Finds the real header row (exports often start with summary or definition lines),
keeps the original row positions so every output line can be traced back to the
file, and leaves footer rows for the transform step to discard.

Built by Avinash Rayudu.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from parse import clean, date_parts, parse_money


@dataclass
class RawTable:
    path: Path
    header: list
    rows: list                 # list of lists of strings; rows[i] is data row i
    header_line: int           # 0-based line where the header was found
    delimiter: str
    preamble: list = field(default_factory=list)

    @property
    def name(self):
        return self.path.name

    def column(self, j):
        return [r[j] if j < len(r) else "" for r in self.rows]

    def signature(self) -> str:
        """Layout fingerprint: same exporter, same columns -> same signature."""
        norm = "|".join(re.sub(r"[^a-z0-9]+", " ", h.lower()).strip() for h in self.header)
        return hashlib.sha1(norm.encode()).hexdigest()[:16]


def _sniff_delimiter(text: str) -> str:
    lines = [l for l in text.splitlines()[:60] if l.strip()]
    best, best_score = ",", -1
    for d in (",", "\t", ";", "|"):
        counts = []
        for l in lines:
            try:
                counts.append(len(next(csv.reader([l], delimiter=d))))
            except Exception:
                counts.append(1)
        if not counts:
            continue
        common = max(set(counts), key=counts.count)
        score = counts.count(common) * (common if common > 1 else 0)
        if score > best_score:
            best, best_score = d, score
    return best


def _cell_kind(v: str) -> str:
    v = clean(v)
    if not v:
        return "empty"
    if parse_money(v) is not None or parse_money(v, True) is not None:
        return "num"
    if date_parts(v) is not None:
        return "date"
    return "text"


def _find_header(grid: list) -> int:
    """The header is the first wide, all-text row whose following rows share its width and hold data."""
    widths = [sum(1 for c in r if clean(c)) for r in grid]
    best_i, best_score = 0, -1e9
    for i, r in enumerate(grid[:40]):
        filled = [c for c in r if clean(c)]
        if len(filled) < 2:
            continue
        kinds = [_cell_kind(c) for c in filled]
        text_share = kinds.count("text") / len(kinds)
        nxt = grid[i + 1:i + 8]
        if not nxt:
            continue
        same_len = sum(1 for x in nxt if len(x) == len(r)) / len(nxt)
        data_like = 0.0
        for x in nxt:
            xk = [_cell_kind(c) for c in x if clean(c)]
            if xk:
                data_like += (xk.count("num") + xk.count("date")) / len(xk)
        data_like /= len(nxt)
        score = 2.0 * text_share + 1.5 * same_len + 1.0 * data_like + 0.02 * len(filled)
        if text_share < 0.75:
            score -= 3
        if score > best_score:
            best_i, best_score = i, score
    return best_i


def read_any(path: Path) -> RawTable:
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        grid = []
        for row in ws.iter_rows(values_only=True):
            grid.append(["" if v is None else _xl_str(v) for v in row])
        wb.close()
        delim = "xlsx"
    else:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        delim = _sniff_delimiter(text)
        grid = list(csv.reader(io.StringIO(text), delimiter=delim))
    grid = [r for r in grid]
    h = _find_header(grid)
    header = [clean(c) for c in grid[h]]
    while header and not header[-1]:
        header.pop()
    width = len(header)
    rows = []
    for r in grid[h + 1:]:
        if not any(clean(c) for c in r):
            continue
        r = list(r) + [""] * (width - len(r))
        rows.append([clean(c) for c in r[:width]])
    pre = [",".join(map(str, r)) for r in grid[:h]]
    return RawTable(path=path, header=header, rows=rows, header_line=h, delimiter=delim, preamble=pre)


def _xl_str(v):
    import datetime as _dt
    if isinstance(v, _dt.datetime):
        return v.date().isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    if isinstance(v, float):
        return f"{v:.2f}" if abs(v - round(v)) > 1e-9 else str(int(round(v)))
    return str(v)
