import json
from pathlib import Path

from runhealth import cli, summary

FIXTURES = Path(__file__).parent / "fixtures"


def _summary(tmp_path, *logs, fmt="html"):
    out = tmp_path / "report"
    paths = [str(FIXTURES / log) for log in logs]
    assert cli.main([*paths, "-o", str(out), "-f", fmt, "--no-squeue"]) == 0
    return json.loads((out / summary.SUMMARY_FILE).read_text())


def test_summary_lists_every_run_with_its_verdict(tmp_path):
    data = _summary(tmp_path, "icon_hang.log", "icon_success.log")
    assert data["schema_version"] == summary.SCHEMA_VERSION
    assert data["grade"] == "fail"
    runs = {r["name"]: r for r in data["runs"]}
    hang, ok = runs["icon_hang.log"], runs["icon_success.log"]
    assert (hang["status"], hang["grade"], hang["job_id"]) == ("FAILED", "fail", "4243")
    assert hang["page"] == "icon_hang.html" and Path(hang["log"]).is_absolute()
    assert ok["stats"]["nodes"] == 2 and ok["model_start"] == "2020-01-01T00:00:00"
    assert {"key", "title", "level", "headline"} == set(hang["checks"][0])
    assert any(c["level"] == "fail" for c in hang["checks"])


def test_markdown_summary_links_no_pages(tmp_path):
    data = _summary(tmp_path, "icon_success.log", fmt="md")
    assert data["runs"][0]["page"] is None
