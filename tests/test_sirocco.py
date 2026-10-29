import copy
from datetime import datetime
from pathlib import Path

from runhealth import health, report, sirocco, summary
from runhealth.report import RunView

CONFIG = """\
name: demo
start_date: &start '2020-01-01T00:00:00'
stop_date: &stop '2020-03-01T00:00:00'
cycles:
  - monthly:
      cycling: {start_date: *start, stop_date: *stop, period: P1M}
      tasks:
        - icon:
            inputs:
              restart_in:
                - restart: {when: {after: *start}, target_cycle: {lag: -P1M}}
tasks:
  - ROOT: {computer: santis, account: acc}
  - icon: {plugin: icon, nodes: 4, walltime: '01:00:00'}
"""
STATE = """\
completed_tasks:
- icon: {coordinates: {date: '2020-01-01T00:00:00+00:00'}, jobid: '11'}
front:
- - icon: {coordinates: {date: '2020-02-01T00:00:00+00:00'}, jobid: '12'}
"""
LOG = (
    "─┤ 2026-10-27 12:17:48 ├─\n"
    "Starting workflow at \n/scratch/demo_\nrun ...\n"
    "[INFO]  \x1b[38;2;1;2;3m●\x1b[0m icon__date_2020-01-01T00-00-00 (11) SUBMITTED to rank 0\n"
    "─┤ 2026-10-27 13:00:00 ├─\n"
    "[INFO]  ● icon__date_2020-01-01T00-00-00 (11) COMPLETED\n"
    "[INFO]  ● icon__date_2020-02-01T00-00-00 (12) FAILED\n"
)


def workflow(tmp_path: Path, config: bool = True) -> Path:
    root = tmp_path / "demo"
    (root / "run").mkdir(parents=True)
    if config:
        (root / "sirocco.resolved.yaml").write_text(CONFIG)
    (root / "run" / "state.yaml").write_text(STATE)
    (root / "sirocco.log").write_text(LOG)
    for date, job in (("2020-01-01", 11), ("2020-02-01", 12)):
        task = root / "run" / f"icon__date_{date}T00-00-00"
        task.mkdir()
        (task / f"run_script.{job}.o").write_text("x\n")
    return root


def test_period_steps_by_calendar_months():
    step = sirocco.parse_period("P1M")
    assert step(datetime(2020, 1, 31)) == datetime(2020, 2, 29)
    assert sirocco.parse_period("PT6H")(datetime(2020, 1, 1)) == datetime(2020, 1, 1, 6)
    assert sirocco.parse_period("1M") is None


def test_a_task_directory_is_a_chunk_of_its_workflow(tmp_path):
    root = workflow(tmp_path)
    cache = {}
    first = sirocco.chunk_of(root / "run/icon__date_2020-01-01T00-00-00/run_script.11.o", cache)
    second = sirocco.chunk_of(root / "run/icon__date_2020-02-01T00-00-00/run_script.12.o", cache)
    assert first.workflow is second.workflow and first.workflow.name == "demo"
    assert first.label == "icon · 2020-01-01 → 02-01 · chunk 1/2 · cold start"
    assert second.label == "icon · 2020-02-01 → 03-01 · chunk 2/2 · restart"
    assert second.workflow_job() == "12"
    assert [e.what for e in second.events()] == ["FAILED"]
    assert first.workflow.status() == "failed"
    assert first.workflow.task_config("icon")["computer"] == "santis"


def test_a_copy_without_configuration_keeps_what_state_and_log_say(tmp_path):
    root = workflow(tmp_path, config=False)
    c = sirocco.chunk_of(root / "run/icon__date_2020-02-01T00-00-00/run_script.12.o", {})
    # The name comes from the original root in the log, whose path wraps across lines.
    assert c.workflow.name == "demo_run"
    assert c.index == 1 and c.count is None and c.restart
    assert "chunk 2 · restart" in c.label


def test_a_log_outside_a_workflow_is_no_chunk(tmp_path):
    (tmp_path / "LOG.x.1.o").write_text("x\n")
    assert sirocco.chunk_of(tmp_path / "LOG.x.1.o", {}) is None


def test_the_report_groups_and_links_the_chunks(tmp_path, parsed, assessed):
    root = workflow(tmp_path)
    cache = {}
    views = []
    for date, job in (("2020-01-01", 11), ("2020-02-01", 12)):
        v = RunView(log=copy.copy(parsed["icon_success"]), assessment=assessed["icon_success"])
        v.log.path = str(root / f"run/icon__date_{date}T00-00-00/run_script.{job}.o")
        v.log.fields = {**v.log.fields, "job_id": str(job)}
        v.page = f"run_script.{job}.html"
        v.chunk = sirocco.chunk_of(v.log.path, cache)
        views.append(v)
    page = report.render_run(views[1], siblings=views)
    assert "<h1>icon · 2020-02-01 → 03-01 · chunk 2/2 · restart</h1>" in page
    assert 'href="run_script.11.html" title="icon' in page
    assert "Sirocco workflow" in page
    index = report.render_index(views, ["host:/x"], None, "t")
    assert 'class="wf"' in index and "2 of 2 chunk(s) in the report" in index
    assert summary.run(views[0])["sirocco"]["chunk"] == 1


def test_the_workflow_records_how_a_job_ended(tmp_path):
    root = workflow(tmp_path)
    cache = {}
    first = sirocco.chunk_of(root / "run/icon__date_2020-01-01T00-00-00/run_script.11.o", cache)
    second = sirocco.chunk_of(root / "run/icon__date_2020-02-01T00-00-00/run_script.12.o", cache)
    assert first.job_state("11") == "COMPLETED"
    assert second.job_state("12") == "FAILED"
    assert first.job_state("99") == ""


def test_the_workflow_settles_a_log_without_verdict_when_slurm_cannot(parsed):
    log = copy.copy(parsed["icon_success"])
    log.outcome = None
    assert health.assess(log, now=1e12).status == "INCOMPLETE"
    a = health.assess(log, now=1e12, workflow_state="COMPLETED")
    assert a.status == "SUCCESS"
    assert a.checks[0].headline == "Sirocco recorded the task as completed"
    assert health.assess(log, now=1e12, workflow_state="CANCELED").status == "FAILED"
    # SLURM accounting, when it has a record, outranks the workflow.
    acct = {"state": "FAILED", "exit_code": "1:0"}
    a = health.assess(log, now=1e12, accounting=acct, workflow_state="COMPLETED")
    assert a.status == "FAILED"
