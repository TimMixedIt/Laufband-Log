"""Parser für die Kurzbefehl-Daten (braucht aiohttp wegen main.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "laufband_log", "app"))
from main import parse_lines, parse_num, parse_ts  # noqa: E402

assert parse_num("98") == 98 and parse_num("98,5") == 98.5 and parse_num("98.5") == 98.5
assert parse_num("1.234") == 1234 and parse_num("1.234,5") == 1234.5 and parse_num("98 Schläge/min") == 98
assert parse_ts("2026-11-06T18:30:00+01:00") == 1793986200 == parse_ts("2026-11-06T17:30:00Z")
assert parse_ts("1793986200") == 1793986200
assert parse_lines("a;1\n\n b;2 \n", 2) == [["a", "1"], [" b", "2 "]]
try:
    parse_lines("nur-ein-feld", 2)
    raise AssertionError("hätte fehlschlagen müssen")
except ValueError:
    pass
print("PARSER OK")
