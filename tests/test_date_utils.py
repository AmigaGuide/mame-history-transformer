import pytest

from mht.utils.date_utils import parse_date_string

@pytest.mark.parametrize("raw,expected", [
    # Year-only & fuzzy years
    ("1985",               "1985-XX-XX"),
    ("198?",               "198X-XX-XX"),
    ("19??",               "19XX-XX-XX"),

    # Year + month (numeric)
    ("1991-7",             "1991-07-XX"),
    ("1991/07",            "1991-07-XX"),

    # Month name + year (with/without dot/space)
    ("July 1991",          "1991-07-XX"),
    ("jul.2012",           "2012-07-XX"),
    ("oct.1988",           "1988-10-XX"),

    # Day MonthName Year (UK)
    ("6 Dec 2007",         "2007-12-06"),
    ("6th December 2007",  "2007-12-06"),

    # MonthName Day Year (US-ish with month name)
    ("December 6, 2007",   "2007-12-06"),
    ("feb.20, 2013",       "2013-02-20"),
    ("Apr, 26, 1989",      "1989-04-26"),
    ("sept.27, 2005",      "2005-09-27"),
    ("jul.1, 1991;",       "1991-07-01"),  # trailing punctuation stripped

    # Unknown day with month name
    ("aug.??, 1995",       "1995-08-XX"),

    # Unknown month+day with year
    ("??? ??, 1995",       "1995-XX-XX"),
    ("???. ??, 1995",      "1995-XX-XX"),

    # Full numeric dates (validated; UK bias for ambiguity)
    ("1988-12-13",         "1988-12-13"),   # ISO
    ("13/12/1988",         "1988-12-13"),   # D/M/Y
    ("12/13/1988",         "1988-12-13"),   # M/D/Y (disambiguated since 13>12)
    ("03/04/1991",         "1991-04-03"),   # ambiguous -> UK bias (D/M/Y)
])
def test_parse_accepts_and_normalises(raw, expected):
    assert parse_date_string(raw) == expected


@pytest.mark.parametrize("raw", [
    None,
    "",
    "  ",
    "July",                 # month-only
    "Fri, 6 Dec 2007",      # weekday present
    "1991/1992",            # range / two years
    "Q3 1992",              # quarter
    "Spring 1995",          # season
    "1988-02-30",           # invalid calendar date
    "SLPS-00341",           # catalogue-ish noise
])
def test_parse_rejects_and_returns_none(raw):
    assert parse_date_string(raw) is None
