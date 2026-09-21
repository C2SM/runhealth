# Troubleshooting

**"no logs matched"**
: Directories are scanned for `LOG.*.o`, `slurm-*.out`, `*.log` and `*.out` in
  that order, using the first pattern that matches. Use `--glob` for any other
  naming scheme, and `--list` to see which files would be read. Empty files are
  skipped.

**Everything is `INCOMPLETE`**
: No profile recognized the success line. Check `runhealth --list-profiles`,
  then add an [`outcome` rule](#profile-outcome) to a profile of your own.

**No throughput, no timeline, no figures**
: Either the log has no timestamps (the run page states which of the three line
  shapes was found), or no profile matched. `--profile slurm` provides the
  minimum: outcome, silence, wall time and errors. See
  [Improving log quality](logging.md).

**A rule in a profile never matches**
: There are three common causes: a `contains:` literal that does not appear in
  *every* matching line; a pattern anchored with `^` that is in fact indented
  in the log; or a rule that should have been marked `preamble: true` because
  it appears only in the echoed job script. See the
  [profile reference](#profile-contains).

**A healthy run is graded `warning`**
: Identify the check responsible for the grade. Load imbalance and slow output
  intervals are observations rather than failures, and are reported to draw
  attention. All thresholds are
  [adjustable per profile](#profile-thresholds).

**`--open` opens nothing, or the wrong application**
: It asks the shell to open a `file://` path, which requires a browser
  registered for that scheme. A plain SSH session has none, WSL requires
  Windows interoperability to be enabled, and a minimal desktop may pass the
  file to an editor instead. Use [`--serve`](usage.md#sharing-a-report)
  instead: given both flags, `--open` directs the browser to the served
  address, and otherwise `http://127.0.0.1:8000/` can be opened manually.

**The wall clock is implausible**
: A file holding several job attempts, resulting from a resubmission that
  appends to the same file name, is analyzed as its **last** attempt, and the
  report states this at the bottom of the page.

## Limitations

- Without line timestamps there is no silence detection, no phase timeline and
  no progress rate.
- Throughput needs a profile that names a progress line. The generic profile
  reports outcome, silence and errors only.
- Load imbalance is read from the timer table of the model itself. A code that
  does not print such a table receives no imbalance analysis.
- `runhealth` reads logs. It does not read the output files of the model, and
  it makes no statement about the scientific correctness of the results.
