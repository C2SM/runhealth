import io

from runhealth import progress


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_a_redirected_stream_only_gets_the_closing_line():
    out = io.StringIO()
    with progress.Progress("parsing", 2, "parsed {n} log(s) in {t}", stream=out) as bar:
        bar.advance("a.log")
        bar.advance("b.log")
    assert out.getvalue().startswith("runhealth: parsed 2 log(s) in ")
    assert out.getvalue().count("\n") == 1


def test_a_terminal_gets_a_bar_that_fills_up():
    out = Tty()
    with progress.Progress("parsing", 4, stream=out) as bar:
        for _ in range(4):
            bar.advance("a.log")
    lines = out.getvalue().split("\r")
    assert "0/4" in lines[1] and progress.FILLED not in lines[1]
    assert "4/4" in lines[-2]
    assert lines[-2].count(progress.FILLED) == progress.MAX_BAR


def test_the_counter_can_be_formatted_as_megabytes():
    out = Tty()
    with progress.Progress("parsing", 8e6, counter=progress.megabytes, stream=out) as bar:
        bar.advance(n=4e6)
    assert "4/8 MB" in out.getvalue()


def test_a_stage_without_a_total_shows_what_it_has_done():
    out = Tty()
    with progress.Progress("reading", stream=out) as bar:
        bar.advance("a.log")
    assert "1" in out.getvalue().split("\r")[-2]


def test_wrap_counts_the_items_it_yields():
    out = io.StringIO()
    bar = progress.Progress("rendering", 3, "rendered {n} page(s) in {t}", stream=out)
    assert list(bar.wrap([1, 2, 3], str)) == [1, 2, 3]
    assert "rendered 3 page(s)" in out.getvalue()


def test_a_message_clears_the_bar_that_is_on_screen():
    out = Tty()
    with progress.Progress("parsing", 2, stream=out) as bar:
        bar.advance("a.log")
        progress.clear_active()
        assert out.getvalue().endswith("\r\x1b[K")
    assert progress._active is None


def test_the_item_is_shortened_to_the_room_that_is_left():
    assert progress._short("LOG.very-long-name.log", 8) == "LOG.ver…"
    assert progress._short("short.log", 40) == "short.log"
