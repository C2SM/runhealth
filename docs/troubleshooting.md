# Troubleshooting

**"no logs matched"**
: Directories are scanned for `LOG.*.o`, `slurm-*.out`, `*.log` and `*.out` in
  that order, taking the first shape that matches. Use `--glob` for anything
  else, and `--list` to see what would be read. Empty files are skipped.

**Everything is `INCOMPLETE`**
: No profile recognised your success line. Check `runhealth --list-profiles`,
  then add an [`outcome` rule](#profile-outcome) in a
  profile of your own.

**No throughput, no timeline, no figures**
: Either the log has no timestamps (the run page says which of the three line
  shapes was found), or no profile matched. `--profile slurm` shows you the
  floor: outcome, silence, wall time and errors. See
  [Get more out of your logs](logging.md).

**A rule in my profile never fires**
: Three usual causes: a `contains:` literal that does not appear in *every*
  matching line; a pattern anchored with `^` that is actually indented in the
  log; or a rule that should have been marked `preamble: true` because it only
  appears in the echoed job script. See the
  [profile reference](#profile-contains).

**A healthy run is graded `warning`**
: Look at which check did it. Load imbalance and slow output intervals are
  observations, not failures; they are meant to draw the eye. Thresholds are all
  [adjustable per profile](#profile-thresholds).

**The wall clock looks impossible**
: A file holding several job attempts, from a resubmission appending to the same
  name, is analysed as its **last** attempt, and the report says so at the
  bottom of the page.

## Limitations

- Without line timestamps there is no silence detection, no phase timeline and
  no progress rate.
- Throughput needs a profile that names a progress line. The generic profile
  reports outcome, silence and errors only.
- Load imbalance is read from the model's own timer table. A code that does not
  print one gets no imbalance analysis.
- `runhealth` reads logs. It does not read the model's output files, and it says
  nothing about whether the science is right.
