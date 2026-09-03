import json
from pathlib import Path

from runhealth import cli

FIXTURES = Path(__file__).parent / "fixtures"


def test_discover_prefers_one_naming_shape(tmp_path):
    (tmp_path / "LOG.demo.1.o").write_text("x\n")
    (tmp_path / "notes.log").write_text("y\n")
    names = [f.name for f in cli.discover([tmp_path], None)]
    assert names == ["LOG.demo.1.o"]


def test_discover_honours_an_explicit_pattern(tmp_path):
    (tmp_path / "LOG.demo.1.o").write_text("x\n")
    (tmp_path / "notes.log").write_text("y\n")
    names = [f.name for f in cli.discover([tmp_path], "*.log")]
    assert names == ["notes.log"]


def test_discover_skips_empty_files(tmp_path):
    (tmp_path / "a.log").write_text("")
    assert cli.discover([tmp_path], "*.log") == []


def test_parse_since():
    assert cli.parse_since("7d") == 7 * 86400
    assert cli.parse_since("90m") == 5400
    assert cli.parse_since("soon") is None


def test_end_to_end_html(tmp_path):
    out = tmp_path / "report"
    rc = cli.main([str(FIXTURES), "--glob", "*.log", "-o", str(out), "--no-squeue"])
    assert rc == 0
    index = out / "index.html"
    assert index.is_file()
    text = index.read_text()
    assert "icon_hang.html" in text and "icon_success.html" in text
    assert (out / "icon_hang.html").is_file()
    assert list((out / "images").glob("*.png"))


def test_cache_is_reused(tmp_path):
    out = tmp_path / "report"
    args = [str(FIXTURES / "icon_success.log"), "-o", str(out), "--no-squeue", "--no-plots"]
    cli.main(args)
    cached = list((out / ".cache").glob("*.json"))
    assert cached
    blob = json.loads(cached[0].read_text())
    assert blob["version"] == cli.CACHE_VERSION
    assert blob["state"]["fields"]["job_id"] == "4242"
    cli.main(args)  # second pass must not raise on the cached state


def test_markdown_end_to_end(tmp_path):
    out = tmp_path / "md"
    cli.main([str(FIXTURES / "icon_hang.log"), "-o", str(out), "-f", "md", "--no-squeue"])
    text = (out / "report.md").read_text()
    assert "Silence" in text
    assert "![" in text  # figures are referenced


def test_no_matching_logs_returns_failure(tmp_path):
    assert cli.main([str(tmp_path), "-o", str(tmp_path / "r"), "--no-squeue"]) == 1


def test_explicit_profile_limits_the_analysis(tmp_path):
    out = tmp_path / "report"
    cli.main(
        [
            str(FIXTURES / "icon_success.log"),
            "-o",
            str(out),
            "--profile",
            "slurm",
            "--no-squeue",
            "--no-plots",
        ]
    )
    text = (out / "icon_success.html").read_text()
    assert "Throughput" not in text
    assert "Outcome" in text


def test_list_profiles(capsys):
    assert cli.main(["--list-profiles"]) == 0
    assert "icon" in capsys.readouterr().out


def test_stall_override_reaches_the_assessment(tmp_path):
    out = tmp_path / "report"
    cli.main(
        [
            str(FIXTURES / "icon_success.log"),
            "-o",
            str(out),
            "--no-squeue",
            "--no-plots",
            "--no-cache",
            "--stall-seconds",
            "1",
        ]
    )
    text = (out / "icon_success.html").read_text()
    assert "of silence" in text
