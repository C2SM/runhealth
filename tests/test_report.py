from runhealth import plots, report
from runhealth.report import RunView


def views(parsed, assessed, names):
    out = []
    for n in names:
        v = RunView(log=parsed[n], assessment=assessed[n])
        v.page = f"{n}.html"
        out.append(v)
    return out


def test_run_page_contains_the_verdict(parsed, assessed):
    v = views(parsed, assessed, ["icon_hang"])[0]
    html = report.render_run(v)
    assert "<!doctype html>" in html
    assert "coupling frame" in html
    assert "Silence" in html and "Outcome" in html
    assert "@media print" in html


def test_run_page_escapes_log_text(parsed, assessed):
    log = parsed["icon_success"]
    log.errors.clear()
    from runhealth.extract import GroupStat

    log.errors["x"] = GroupStat(label="x", total=1, sample="<script>alert(1)</script>")
    from runhealth import health

    v = RunView(log=log, assessment=health.assess(log))
    html = report.render_run(v)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_index_lists_every_run(parsed, assessed):
    names = ["icon_success", "icon_hang", "slurm_generic"]
    html = report.render_index(views(parsed, assessed, names), ["/tmp"], None, "Test")
    for n in names:
        assert f"{n}.html" in html
    assert "Test" in html


def test_markdown_output(parsed, assessed):
    md = report.render_markdown(
        views(parsed, assessed, ["icon_success", "icon_hang"]), ["/tmp"], "Test"
    )
    assert md.startswith("# Test")
    assert "| health |" in md
    assert "Silence" in md


def test_pdf_without_weasyprint_explains_itself(tmp_path, parsed, assessed):
    page = tmp_path / "index.html"
    page.write_text(report.render_run(views(parsed, assessed, ["icon_success"])[0]))
    message = report.to_pdf(page, tmp_path / "out.pdf")
    assert "Wrote" in message


def test_figures_are_drawn_for_a_rich_log(tmp_path, parsed, assessed):
    figs = plots.render_run(
        parsed["icon_success"], assessed["icon_success"], tmp_path, "demo", dpi=60
    )
    keys = {f.key for f in figs}
    assert {"timeline", "timers"} <= keys
    for f in figs:
        assert (tmp_path / f.href).is_file()


def test_figures_degrade_instead_of_failing(tmp_path, parsed, assessed):
    figs = plots.render_run(parsed["empty"], assessed["empty"], tmp_path, "empty", dpi=60)
    assert figs == []
    assert not parsed["empty"].notes


def test_index_figure_needs_more_than_one_run(tmp_path, parsed, assessed):
    pairs = [(parsed[n], assessed[n]) for n in ("icon_success", "icon_hang")]
    fig = plots.render_index(pairs, tmp_path / "images" / "overview.png", dpi=60)
    assert fig is not None
    assert (tmp_path / fig.href).is_file()
