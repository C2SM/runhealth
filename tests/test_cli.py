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


def test_is_remote_detects_rsync_style_specs():
    assert cli.is_remote("santis:/scratch/e1000/run")
    assert cli.is_remote("user@host:relative/path")
    assert not cli.is_remote("/local/path")
    assert not cli.is_remote(".")


def _fake_ssh(tmp_path) -> Path:
    # A colon before the first slash is enough to make sync_remote shell out
    # over ssh, so tests fake the remote shell rather than needing a real
    # host: a wrapper that drops the hostname argument and runs the rest
    # (rsync's own --server invocation) right here.
    rsh = tmp_path / "fake-ssh"
    rsh.write_text('#!/bin/sh\nshift\nexec "$@"\n')
    rsh.chmod(0o755)
    return rsh


def test_sync_remote_pulls_matching_files_non_recursively(tmp_path, monkeypatch):
    monkeypatch.setenv("RSYNC_RSH", str(_fake_ssh(tmp_path)))
    remote = tmp_path / "remote"
    (remote / "sub").mkdir(parents=True)
    (remote / "LOG.demo.1.o").write_text("x\n")
    (remote / "notes.txt").write_text("y\n")
    (remote / "sub" / "LOG.deep.1.o").write_text("z\n")

    local = cli.sync_remote(f"fakehost:{remote}", None, tmp_path / "staging")

    assert local is not None
    assert sorted(p.name for p in local.iterdir()) == ["LOG.demo.1.o"]


def test_sync_remote_falls_back_to_a_single_file(tmp_path, monkeypatch):
    monkeypatch.setenv("RSYNC_RSH", str(_fake_ssh(tmp_path)))
    remote_file = tmp_path / "LOG.demo.1.o"
    remote_file.write_text("x\n")

    local = cli.sync_remote(f"fakehost:{remote_file}", None, tmp_path / "staging")

    assert local is not None
    assert (local / "LOG.demo.1.o").read_text() == "x\n"


def test_end_to_end_from_a_remote_spec(tmp_path, monkeypatch):
    monkeypatch.setenv("RSYNC_RSH", str(_fake_ssh(tmp_path)))
    out = tmp_path / "report"
    rc = cli.main([f"fakehost:{FIXTURES}", "--glob", "*.log", "-o", str(out), "--no-squeue"])
    assert rc == 0
    assert (out / "index.html").is_file()
    assert (out / "icon_hang.html").is_file()


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
    # Figures are inlined, so the page stands alone with no image directory.
    assert not (out / "images").exists()
    assert "<svg" in (out / "icon_hang.html").read_text()


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
    # Markdown cannot inline a figure, so those get written as files.
    assert list((out / "images").glob("*.svg"))


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


def test_publish_without_a_destination_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("RUNHEALTH_PUBLISH", raising=False)
    rc = cli.main(
        [str(FIXTURES / "icon_hang.log"), "-o", str(tmp_path / "r"), "--no-squeue", "--publish"]
    )
    assert rc == 2
    assert not (tmp_path / "r").exists()  # refused before any work


def test_publish_copies_the_report(tmp_path):
    out, web = tmp_path / "report", tmp_path / "web"
    web.mkdir()
    rc = cli.main(
        [
            str(FIXTURES / "icon_hang.log"),
            "-o",
            str(out),
            "--no-squeue",
            "--publish",
            str(web),
            "--publish-url",
            "https://example.invalid/runs",
        ]
    )
    assert rc == 0
    assert (web / "index.html").is_file()
    assert (web / "icon_hang.html").is_file()


def test_publish_reads_its_destination_from_the_environment(tmp_path, monkeypatch):
    out, web = tmp_path / "report", tmp_path / "web"
    web.mkdir()
    monkeypatch.setenv("RUNHEALTH_PUBLISH", str(web))
    rc = cli.main([str(FIXTURES / "icon_hang.log"), "-o", str(out), "--no-squeue", "--publish"])
    assert rc == 0
    assert (web / "index.html").is_file()


def test_serve_binds_to_the_loopback_interface_only(tmp_path):
    out = tmp_path / "report"
    out.mkdir()
    server = cli.make_server(out, 0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
