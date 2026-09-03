import pytest

from runhealth.tables import TableReader, parse_duration, parse_number

RULED = """  -----------   -------   ----------
  name          # calls   total avg (s)
  -----------   -------   ----------

  total         8         10.200
   L child      100       8.200
      L grand   100       2.100
  ----------------------------------
"""

TRAILING = """Counter        Samples          Min         Mean          Max
rh:nacks             8            5           25           85
hni_rx_paused        8         1000        20000       400000
"""


@pytest.mark.parametrize(
    "text,want",
    [
        ("0.05847s", 0.05847),
        ("16m43s", 1003),
        ("02m46s", 166),
        ("01h02m", 3720),
        ("1d02h", 93600),
        ("12.5", 12.5),
    ],
)
def test_parse_duration(text, want):
    assert parse_duration(text) == pytest.approx(want)


def test_parse_duration_rejects_rubbish():
    assert parse_duration("later") is None
    assert parse_duration("") is None


def test_parse_number():
    assert parse_number("1.5e3") == 1500
    assert parse_number("[7]") is None


def read(text: str, spec: dict):
    reader = TableReader("t", spec)
    for line in text.splitlines():
        if not reader.feed(line):
            break
    return reader.table


def test_ruled_table_columns_and_nesting():
    table = read(RULED, {"kind": "ruled", "nesting": r"^(\s*)L ", "durations": ["total avg (s)"]})
    assert table.columns == ["name", "# calls", "total avg (s)"]
    assert [r.label for r in table.rows] == ["total", "child", "grand"]
    assert [r.depth for r in table.rows] == [0, 1, 2]
    assert table.rows[0].values["total avg (s)"] == pytest.approx(10.2)


def test_ruled_table_stops_at_the_closing_rule():
    table = read(RULED + "something else entirely\n", {"kind": "ruled"})
    assert len(table.rows) == 3


def test_ruled_table_gives_up_without_a_rule():
    table = read("\n".join(f"line {i}" for i in range(40)), {"kind": "ruled"})
    assert not table.rows


def test_trailing_numbers_table():
    reader = TableReader("t", {"kind": "trailing-numbers", "include_start": True})
    for line in TRAILING.splitlines():
        reader.feed(line)
    table = reader.table
    assert table.columns == ["Counter", "Samples", "Min", "Mean", "Max"]
    assert table.rows[0].label == "rh:nacks"
    assert table.rows[1].values["Max"] == 400000


def test_repeated_headers_are_disambiguated():
    reader = TableReader("t", {"kind": "trailing-numbers", "include_start": True})
    reader.feed("Counter   Min   (/s)   Mean   (/s)")
    reader.feed("thing       1    2.0      3    4.0")
    assert reader.table.columns == ["Counter", "Min", "(/s)", "Mean", "Mean (/s)"]
    assert reader.table.rows[0].values["Mean (/s)"] == 4.0


def test_rank_tags_are_read_as_numbers():
    text = (
        "  --------   --------\n"
        "  name       max rank\n"
        "  --------   --------\n"
        "\n"
        "  total      [17]\n"
        "  ---------------------\n"
    )
    table = read(text, {"kind": "ruled"})
    assert table.rows[0].values["max rank"] == 17
