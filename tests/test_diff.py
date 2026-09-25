from runhealth.diff import compare, run_kind
from runhealth.extract import RunLog


def test_runs_are_grouped_by_the_job_name(parsed):
    # Three fixtures are the same experiment submitted again.
    assert run_kind(parsed["icon_success"]) == "demo"
    assert run_kind(parsed["icon_hang"]) == "demo"
    assert run_kind(parsed["slurm_generic"]) != "demo"


def test_a_log_without_slurm_metadata_falls_back_to_its_name():
    assert run_kind(RunLog(path="/runs/LOG.jcp_r2b10.863100.o")) == "jcp_r2b10"
    # Nothing that looks like a job id, so the name is kept whole.
    assert run_kind(RunLog(path="/runs/nightly.log")) == "nightly"


def test_a_changed_directive_is_counted_and_marked():
    old = "\n".join(["#!/bin/bash", "#SBATCH --nodes=2", "srun ./icon"])
    new = "\n".join(["#!/bin/bash", "#SBATCH --nodes=8", "srun ./icon"])
    d = compare(old, new)
    assert (d.added, d.removed) == (1, 1)
    assert d.changed and d.summary == "+1 −1"
    assert '<tr class="del">' in d.rows and "--nodes=2" in d.rows
    assert '<tr class="add">' in d.rows and "--nodes=8" in d.rows
    # The context around the change is carried along, and highlighted.
    assert '<tr class="ctx">' in d.rows and 'class="sy-cmd"' in d.rows


def test_an_unchanged_script_produces_no_rows():
    d = compare("#!/bin/bash\nsrun ./icon", "#!/bin/bash\nsrun ./icon")
    assert (d.added, d.removed) == (0, 0)
    assert not d.changed and d.summary == "no change" and d.rows == ""


def test_distant_changes_are_split_into_hunks():
    old = "\n".join(["a"] + [f"line {i}" for i in range(20)] + ["z"])
    new = "\n".join(["A"] + [f"line {i}" for i in range(20)] + ["Z"])
    d = compare(old, new)
    assert d.rows.count('<tr class="hunk">') == 2
    # Only the two ends and their context, not the twenty lines between them.
    assert d.rows.count("<tr") <= 12


def test_the_script_is_escaped_before_it_is_shown():
    d = compare("echo ok", "echo '<script>alert(1)</script>'")
    assert "<script>alert(1)" not in d.rows
    assert "&lt;script&gt;" in d.rows
