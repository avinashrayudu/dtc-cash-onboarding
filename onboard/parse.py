"""
Value parsing: money and dates, the way they actually show up in exports.

Money:  "1234.56", "1,234.56", "$1,234.56", "-$1,234.56", "(1,234.56)", "1234.56-",
        "CA$12.00", "1.234,56" (decimal comma, detected per column).
Dates:  "2026-07-01", "07/01/2026", "7/1/2026", "01/07/2026" (day first), "01-07-2026", "Jul 1, 2026",
        "2026-07-01 14:22:11 -0400", "07/01/2026 2:22 PM", "Jul 1, 2026 12:00:00 PM PDT".
        Slash dates are ambiguous; the column-level parser resolves month-first vs day-first.

Built by Avinash Rayudu.
"""
from __future__ import annotations

import re
from datetime import date

_MONEY_STRIP = re.compile(r"[\s$€£]|USD|CAD|EUR|GBP|CA\$|US\$|A\$", re.I)
_DEC_COMMA = re.compile(r"^-?\(?\d{1,3}(\.\d{3})*,\d{1,2}\)?-?$|^-?\(?\d+,\d{1,2}\)?-?$")
_DEC_POINT = re.compile(r"^-?\(?\d{1,3}(,\d{3})*(\.\d+)?\)?-?$|^-?\(?\d+(\.\d+)?\)?-?$")

MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                                           "oct", "nov", "dec"])}
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
_SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})(?:\D|$)")
_DOT = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\D|$)")
_DASH = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})(?:\D|$)")
_MON = re.compile(r"^([A-Za-z]{3})[A-Za-z]*\.? (\d{1,2}),? (\d{4})")
_DMON = re.compile(r"^(\d{1,2})[ -]([A-Za-z]{3})[A-Za-z]*[ -](\d{2,4})")


def clean(s) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    if s.lower() in ("nan", "none", "null"):
        return ""
    return s


def looks_decimal_comma(values) -> bool:
    """True when a column's numbers use a comma as the decimal mark."""
    vals = [_MONEY_STRIP.sub("", clean(v)) for v in values]
    vals = [v for v in vals if v]
    if not vals:
        return False
    comma = sum(1 for v in vals if _DEC_COMMA.match(v) and not _DEC_POINT.match(v))
    point = sum(1 for v in vals if _DEC_POINT.match(v) and ("." in v))
    return comma > point and comma >= 0.3 * len(vals)


def parse_money(s, decimal_comma: bool = False):
    s = clean(s)
    if not s:
        return None
    neg = False
    s = _MONEY_STRIP.sub("", s)
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.endswith("-"):
        neg, s = True, s[:-1]
    if s.startswith("-"):
        neg, s = (not neg), s[1:]
    if s.startswith("+"):
        s = s[1:]
    if decimal_comma:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?|\.\d+", s):
        return None
    v = float(s)
    return round(-v if neg else v, 2)


def _year(y: str) -> int:
    y = int(y)
    return y + 2000 if y < 100 else y


def date_parts(s):
    """Returns (kind, a, b, year) for slash/dot dates or a date for unambiguous forms, else None."""
    s = clean(s)
    if not s:
        return None
    m = _ISO.match(s)
    if m:
        return ("date", date(int(m[1]), int(m[2]), int(m[3])))
    m = _SLASH.match(s)
    if m:
        return ("ab", int(m[1]), int(m[2]), _year(m[3]))
    m = _DOT.match(s)
    if m:
        return ("ab_dayfirst", int(m[1]), int(m[2]), _year(m[3]))
    m = _DASH.match(s)
    if m:
        return ("ab", int(m[1]), int(m[2]), _year(m[3]))
    m = _MON.match(s)
    if m and m[1].lower() in MONTHS:
        return ("date", date(int(m[3]), MONTHS[m[1].lower()], int(m[2])))
    m = _DMON.match(s)
    if m and m[2].lower() in MONTHS:
        return ("date", date(_year(m[3]), MONTHS[m[2].lower()], int(m[1])))
    return None


def _mk(y, mth, d):
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def parse_date_column(values, prefer_day_first=None):
    """
    Parses a whole column at once so month-first vs day-first is decided with
    evidence from every row. Returns (dates, info) where dates holds date or None.
    """
    parts = [date_parts(v) for v in values]
    n = sum(1 for p in parts if p is not None)
    info = {"parse_rate": n / max(1, len(values)), "order": None, "ambiguous": False}
    ab = [p for p in parts if p and p[0] == "ab"]
    order = "mdy"
    if ab:
        first_gt12 = any(p[1] > 12 for p in ab)
        second_gt12 = any(p[2] > 12 for p in ab)
        if first_gt12 and not second_gt12:
            order = "dmy"
        elif second_gt12 and not first_gt12:
            order = "mdy"
        else:
            # every value fits both readings: pick the reading whose dates move in order
            def mono(o):
                ds = [(_mk(p[3], p[1], p[2]) if o == "mdy" else _mk(p[3], p[2], p[1])) for p in ab]
                ds = [d for d in ds if d]
                if len(ds) < 3:
                    return 0.0
                up = sum(1 for a, b in zip(ds, ds[1:]) if b >= a)
                dn = sum(1 for a, b in zip(ds, ds[1:]) if b <= a)
                return max(up, dn) / (len(ds) - 1)
            m_mdy, m_dmy = mono("mdy"), mono("dmy")
            if abs(m_mdy - m_dmy) > 0.02:
                order = "mdy" if m_mdy > m_dmy else "dmy"
            else:
                order = "dmy" if prefer_day_first else "mdy"
                info["ambiguous"] = True
    info["order"] = order
    out = []
    for p in parts:
        if p is None:
            out.append(None)
        elif p[0] == "date":
            out.append(p[1])
        elif p[0] == "ab":
            out.append(_mk(p[3], p[1], p[2]) if order == "mdy" else _mk(p[3], p[2], p[1]))
        elif p[0] == "ab_dayfirst":
            out.append(_mk(p[3], p[2], p[1]))
    return out, info


def numeric_rate(values, decimal_comma=False) -> float:
    vals = [v for v in values if clean(v)]
    if not vals:
        return 0.0
    return sum(1 for v in vals if parse_money(v, decimal_comma) is not None) / len(vals)
