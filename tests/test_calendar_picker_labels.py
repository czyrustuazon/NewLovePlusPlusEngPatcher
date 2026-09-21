"""Birthday picker １月/１日 must be calendar names/numbers, not durations."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from patch_textresource import load_translations, local_translate  # noqa: E402

TRANSLATIONS = ROOT / "assets" / "textresource" / "translations.json"

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _fw(n: int) -> str:
    return str(n).translate(str.maketrans("0123456789", "０１２３４５６７８９"))


def test_translations_json_uses_calendar_month_names():
    mapping = load_translations(TRANSLATIONS)
    for i, name in enumerate(_MONTHS, start=1):
        assert mapping[_fw(i) + "月"] == name
        assert "month(s)" not in mapping[_fw(i) + "月"]


def test_translations_json_uses_plain_day_numbers():
    mapping = load_translations(TRANSLATIONS)
    for i in range(1, 10):
        assert mapping[_fw(i) + "日"] == str(i)
    for i in range(10, 32):
        assert mapping[_fw(i) + "日"] == f"{i // 10} {i % 10}"
        assert "day(s)" not in mapping[_fw(i) + "日"]


def test_local_translate_calendar_months_and_days():
    assert local_translate("１月") == "January"
    assert local_translate("１２月") == "December"
    assert local_translate("１日") == "1"
    assert local_translate("３１日") == "3 1"
    assert local_translate("13月") == "13 month(s)"
