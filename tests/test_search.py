import json

from runhealth import report, search
from runhealth.extract import RunLog
from runhealth.health import assess
from runhealth.report import RunView


def views(parsed, assessed, names):
    out = []
    for n in names:
        v = RunView(log=parsed[n], assessment=assessed[n], page=f"{n}.html")
        out.append(v)
    return out


def loaded(text: str) -> dict:
    """The payload as a browser reading the written script would see it."""
    body = text.strip().removeprefix("window.RUNHEALTH_SEARCH=").removesuffix(";")
    return json.loads(body.replace("<\\/", "</"))


def test_the_index_carries_every_run_script(tmp_path, parsed, assessed):
    names = ["icon_success", "icon_hang", "slurm_generic"]
    search.write(views(parsed, assessed, names), tmp_path)
    data = loaded((tmp_path / "search.js").read_text())
    assert {r["page"] for r in data["runs"]} == {f"{n}.html" for n in names}
    for run in data["runs"]:
        assert "#SBATCH" in run["script"]
        assert run["name"] and run["grade"] and run["status"]


def test_a_run_is_described_by_more_than_its_name(tmp_path, parsed, assessed):
    search.write(views(parsed, assessed, ["icon_success"]), tmp_path)
    run = loaded((tmp_path / "search.js").read_text())["runs"][0]
    fields = dict(run["fields"])
    assert fields["Node list"] == "nid[000001-000002]"
    assert fields["Revision"].startswith("icon-")
    assert any(c[1] == "Outcome" for c in run["checks"])


def test_a_closing_tag_cannot_end_the_element_that_loads_the_index(tmp_path, assessed, parsed):
    log = RunLog(path="/runs/odd.log", name="odd.log", runscript="echo '</script>'")
    v = RunView(log=log, assessment=assess(log), page="odd.html")
    search.write([v], tmp_path)
    text = (tmp_path / "search.js").read_text()
    assert "</script>" not in text
    assert loaded(text)["runs"][0]["script"] == "echo '</script>'"


def test_the_header_searches_the_whole_report(parsed, assessed):
    page = report.render_run(views(parsed, assessed, ["icon_success"])[0])
    index = report.render_index(views(parsed, assessed, ["icon_success"]), ["/tmp"], None, "Test")
    for html in (page, index):
        assert '<div class="search">' in html
        assert 'aria-label="Search runs and run scripts"' in html
        assert "search.js" in html  # loaded only once a reader asks for it


def test_a_script_line_can_be_linked_to(parsed, assessed):
    html = report.render_run(views(parsed, assessed, ["icon_success"])[0])
    assert '<b id="SL1" data-n="1">' in html
    assert "#script-L" in html  # the page opens the script where a search matched


def test_the_raw_log_page_looks_for_the_index_one_level_up(tmp_path, parsed, assessed):
    view = views(parsed, assessed, ["icon_success"])[0]
    view.log_href = report.copy_log(view.log, tmp_path, max_bytes=1 << 20)
    html = (tmp_path / view.log_href).read_text()
    assert 'data-base="../"' in html


def test_a_run_without_a_script_still_lands_in_the_index(tmp_path, parsed, assessed):
    search.write(views(parsed, assessed, ["icon_no_timestamps"]), tmp_path)
    run = loaded((tmp_path / "search.js").read_text())["runs"][0]
    assert run["script"] == ""
    assert run["file"] == "icon_no_timestamps.log"
