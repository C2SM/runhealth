from pathlib import Path

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
    figs = plots.render_run(parsed["icon_success"], assessed["icon_success"], tmp_path, "demo")
    keys = {f.key for f in figs}
    assert {"timeline", "timers"} <= keys
    for f in figs:
        assert f.svg.startswith("<svg") and f.svg.endswith("</svg>")
        assert not f.href  # nothing on disk unless a standalone file is asked for


def test_standalone_files_are_written_for_markdown(tmp_path, parsed, assessed):
    figs = plots.render_run(
        parsed["icon_success"], assessed["icon_success"], tmp_path, "demo", standalone=True
    )
    assert figs
    for f in figs:
        path = tmp_path / f.href
        assert path.is_file()
        text = path.read_text()
        assert text.startswith("<svg xmlns=")
        assert "--s0:" in text  # its own palette travels with it


def test_figures_degrade_instead_of_failing(tmp_path, parsed, assessed):
    figs = plots.render_run(parsed["empty"], assessed["empty"], tmp_path, "empty")
    assert figs == []
    assert not parsed["empty"].notes


def test_figure_marks_carry_their_own_tooltip(parsed, assessed):
    figs = {
        f.key: f
        for f in plots.render_run(parsed["icon_hang"], assessed["icon_hang"], Path("."), "h")
    }
    timeline = figs["timeline"]
    assert 'data-tip="' in timeline.svg
    # A tooltip is also an accessible name, so a keyboard reaches the same fact.
    assert 'tabindex="0"' in timeline.svg and "aria-label=" in timeline.svg
    # The silence marks name the log line to jump to.
    assert "data-line=" in timeline.svg


def test_index_figure_needs_more_than_one_run(tmp_path, parsed, assessed):
    triples = [(parsed[n], assessed[n], f"{n}.html") for n in ("icon_success", "icon_hang")]
    fig = plots.render_index(triples, tmp_path)
    assert fig is not None
    assert "icon_hang.html" in fig.svg  # bars link to their run
    one = plots.render_index(triples[:1], tmp_path)
    assert one is None


def test_theme_switch_offers_three_labelled_icons(parsed, assessed):
    html = report.render_run(views(parsed, assessed, ["icon_success"])[0])
    for mode in ("system", "light", "dark"):
        assert f'data-theme-set="{mode}"' in html
    # Icon-only buttons need an accessible name, and an icon is not an emoji.
    assert html.count('aria-label="') >= 3
    assert '<svg class="ico"' in html


def test_pages_carry_a_sticky_nav_and_a_table_of_contents(tmp_path, parsed, assessed):
    view = views(parsed, assessed, ["icon_success"])[0]
    view.figures = plots.render_run(view.log, view.assessment, tmp_path, "s")
    html = report.render_run(view)
    assert '<header class="nav">' in html
    assert "position: sticky" in html
    assert '<nav id="toc">' in html
    assert 'href="#checks"' in html and 'href="#figures"' in html
    assert 'href="#fig-timeline"' in html  # figures are listed individually
    assert '<a class="skip" href="#main">' in html


def test_the_index_lists_its_own_sections(parsed, assessed):
    html = report.render_index(
        views(parsed, assessed, ["icon_success", "icon_hang"]), ["/tmp"], None, "Test"
    )
    assert 'href="#runs"' in html


def test_a_single_section_needs_no_table_of_contents():
    toc = report.Toc()
    toc.add("only", "Only")
    assert toc.render() == ""


def test_the_source_bar_leads_with_the_path_and_its_actions(tmp_path, parsed, assessed):
    view = views(parsed, assessed, ["icon_success"])[0]
    view.source = "santis:/scratch/run/LOG.demo.1.o"
    view.log_href = report.copy_log(view.log, tmp_path, max_bytes=1 << 20)
    html = report.render_run(view)
    assert '<div class="source">' in html
    assert 'class="src-path"' in html and "santis:/scratch/run/LOG.demo.1.o" in html
    assert "data-open-script" in html and "run script" in html
    assert "raw log" in html


def test_a_badge_paints_its_dot_in_the_grade_colour(parsed, assessed):
    html = report.render_run(views(parsed, assessed, ["icon_hang"])[0])
    # currentColor here would resolve to the dot's own colour, which is the
    # colour the letter is knocked out in, leaving the letter invisible.
    assert "background: currentColor" not in html
    for grade in ("ok", "info", "warn", "fail"):
        assert f".badge.g-{grade} .mark {{ background: var(--{grade}); }}" in html


def test_the_index_shows_a_dash_for_a_job_without_an_id(parsed, assessed):
    html = report.render_index(
        views(parsed, assessed, ["slurm_generic"]), ["here:/tmp"], None, "Test"
    )
    # The entity has to survive, rather than being escaped into its own text.
    assert "&amp;ndash;" not in html
    assert "&ndash;" in html


def test_a_path_chip_separates_the_machine_from_the_path():
    chip = report.path_chip("santis:/scratch/e1000/LOG.demo.1.o")
    assert '<span class="host">santis</span>' in chip
    assert '<span class="p">/scratch/e1000/LOG.demo.1.o</span>' in chip
    assert 'data-copy="santis:/scratch/e1000/LOG.demo.1.o"' in chip


def test_a_path_chip_leaves_a_plain_path_whole():
    # A colon only counts as a machine before the first slash, as rsync reads it.
    chip = report.path_chip("/scratch/odd:name/LOG.o")
    assert 'class="host"' not in chip
    assert '<span class="p">/scratch/odd:name/LOG.o</span>' in chip


def test_paths_can_be_copied(tmp_path, parsed, assessed):
    view = views(parsed, assessed, ["icon_success"])[0]
    view.source = "santis:/scratch/run/LOG.demo.1.o"
    html = report.render_run(view)
    # The header path, and the one in the provenance table.
    assert html.count('class="copy"') >= 2
    assert 'data-copy="santis:/scratch/run/LOG.demo.1.o"' in html
    assert 'aria-label="Copy the path"' in html


def test_the_index_formats_each_source_it_read(parsed, assessed):
    html = report.render_index(
        views(parsed, assessed, ["icon_success", "icon_hang"]),
        ["santis:/scratch/e1000/run"],
        None,
        "Test",
    )
    assert '<span class="host">santis</span>' in html
    assert '<span class="p">/scratch/e1000/run</span>' in html
    assert 'data-copy="santis:/scratch/e1000/run"' in html


def test_the_run_script_modal_can_be_saved_and_is_highlighted(parsed, assessed):
    view = views(parsed, assessed, ["icon_success"])[0]
    html = report.render_run(view)
    assert '<dialog class="script-modal"' in html
    assert 'data-download-script="icon_success.run.sh"' in html
    assert '<span class="sy-dir">#SBATCH --nodes=2</span>' in html
    # A column with one scrolling row, so the script scrolls and the head stays.
    assert "dialog.script-modal[open] { display: flex" in html


def test_a_log_without_a_run_script_offers_no_modal(parsed, assessed):
    html = report.render_run(views(parsed, assessed, ["icon_no_timestamps"])[0])
    assert "<dialog" not in html
    assert "<button type=\"button\" class=\"src-btn key\" data-open-script>" not in html


def test_checks_can_be_filtered_by_grade(parsed, assessed):
    html = report.render_run(views(parsed, assessed, ["icon_hang"])[0])
    assert '<div class="filters" data-target=".check"' in html
    assert 'class="check l-fail" data-grade="fail"' in html


def test_one_grade_of_check_needs_no_filter():
    assert report._grade_filters({"ok": 4}, ".check", "Filter") == ""
    assert '<button data-grade="fail">' in report._grade_filters(
        {"ok": 1, "fail": 2}, ".check", "Filter"
    )


def test_the_table_of_contents_tracks_live_geometry(parsed, assessed):
    html = report.render_run(views(parsed, assessed, ["icon_success"])[0])
    # Remembered intersections went stale when a jump to an anchor carried a
    # heading past the reading line without ever crossing it, which left the
    # section the reader had just left still marked.
    assert "getBoundingClientRect().top - LINE" in html
    assert "'scroll', onScroll" in html


def test_the_summary_anchor_clamps_to_the_top_of_the_page(parsed, assessed):
    html = report.render_run(views(parsed, assessed, ["icon_success"])[0])
    assert 'href="#summary"' in html
    # Bigger than everything above the title in any layout, so the offset
    # clamps to zero instead of leaving it under the sticky header.
    assert "scroll-margin-top: calc(var(--nav-h) + 100px)" in html


def test_embedded_log_is_addressable_by_line(tmp_path, parsed, assessed):
    log = parsed["icon_hang"]
    href = report.copy_log(log, tmp_path, max_bytes=1 << 20)
    assert href.endswith(".html")
    text = (tmp_path / href).read_text()
    assert '<b id="L1"' in text and 'class="blk"' in text
