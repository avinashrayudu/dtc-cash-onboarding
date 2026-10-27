"""Parsing and reading: the layer every number depends on."""
from datetime import date

from parse import looks_decimal_comma, parse_date_column, parse_money
from readers import read_any


def test_money_formats():
    cases = {"1234.56": 1234.56, "1,234.56": 1234.56, "$1,234.56": 1234.56, "-$1,234.56": -1234.56,
             "(1,234.56)": -1234.56, "1234.56-": -1234.56, "CA$12.00": 12.0, "": None, "n/a": None}
    for raw, want in cases.items():
        assert parse_money(raw) == want, raw


def test_decimal_comma_column():
    assert looks_decimal_comma(["1.234,56", "12,00", "-3,50"])
    assert not looks_decimal_comma(["1,234.56", "12.00"])
    assert parse_money("1.234,56", decimal_comma=True) == 1234.56


def test_date_column_resolves_day_first_from_evidence():
    d, info = parse_date_column(["01/07/2026", "15/07/2026", "31/08/2026"])
    assert d[1] == date(2026, 7, 15) and info["order"] == "dmy" and not info["ambiguous"]
    d, info = parse_date_column(["07/01/2026", "07/15/2026"])
    assert d[1] == date(2026, 7, 15) and info["order"] == "mdy"


def test_date_column_flags_true_ambiguity():
    _, info = parse_date_column(["01/07/2026", "02/07/2026", "03/07/2026"])
    assert info["ambiguous"]


def test_mixed_date_styles():
    vals = ["Jul 1, 2026 12:00:00 PM PDT", "2026-07-01 14:22:11 -0400", "2026-07-01"]
    d, _ = parse_date_column(vals)
    assert all(x == date(2026, 7, 1) for x in d)


def test_header_found_below_summary_preamble(tmp_path):
    p = tmp_path / "stmt.csv"
    p.write_text('Description,,Summary Amt.\nBeginning balance as of 07/01/2026,,"1,000.00"\n\n'
                 'Date,Description,Amount,Running Bal.\n'
                 '07/01/2026,SHOPIFY DES:TRANSFER,"100.00","1,100.00"\n'
                 '07/02/2026,GUSTO DES:NET,"-50.00","1,050.00"\n'
                 '07/03/2026,RENT,"-25.00","1,025.00"\n')
    t = read_any(p)
    assert t.header == ["Date", "Description", "Amount", "Running Bal."]
    assert len(t.rows) == 3 and t.rows[0][1].startswith("SHOPIFY")


def test_tab_separated_and_signature(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("settlement-id\tdeposit-date\ttotal-amount\tamount\n1\t2026-07-10\t10.00\t\n1\t\t\t10.00\n")
    t = read_any(p)
    assert t.delimiter == "\t" and t.header[0] == "settlement-id"
    p2 = tmp_path / "s2.txt"
    p2.write_text("settlement-id\tdeposit-date\ttotal-amount\tamount\n2\t2026-07-24\t20.00\t\n")
    assert read_any(p2).signature() == t.signature()
