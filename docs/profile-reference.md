# Profile reference

The complete schema of a profile file. A profile tells `runhealth` what a code
prints, and the core never hard-codes a model: everything code-specific is
defined here. For a minimal example and for how profiles are selected, start
with [Profiles](profiles.md).

The file name is irrelevant; the `name:` field identifies the profile. The
bundled profiles in `src/runhealth/profiles/` are worth reading as worked
examples: `slurm.yaml`, `icon.yaml`, `cray-mpich.yaml`.

## Composition

Several profiles can apply to one log. Each contributes its own rules and
settings, in order of `priority` (lowest first, so that a later profile can
override a setting). The `slurm` profile has `always: true` and applies to
every log; every other profile is selected by its `detect` patterns, or pinned
with `--profile a,b`.

Concerns should be kept separate. The fabric counters printed by a Cray machine
are unrelated to the model running on it, which is why they are defined in
`cray-mpich.yaml` rather than in `icon.yaml`.

## Skeleton

```yaml
name: mymodel
description: "What this profile covers"
priority: 10          # applied after lower numbers
always: false         # true only for a profile that must apply to every log

detect: [ ... ]       # any match selects this profile
attempt_boundary: [ ] # patterns marking a new job attempt in the same file

settings: { ... }     # names and column mappings the analysis uses
thresholds: { ... }   # numbers the checks compare against

fields: { ... }       # one value per run
keyvalues: { ... }    # many key/value pairs into one dictionary
series: { ... }       # repeated events, in order
markers: { ... }      # phase boundaries on the timeline
groups: { ... }       # high-cardinality messages, counted not stored
tables: { ... }       # structured blocks
outcome: [ ... ]      # the run's verdict
```

## Rules

Every entry in `fields`, `keyvalues`, `series`, `markers`, `groups` and
`outcome` is a rule. A rule is either a bare regex string or a mapping:

```yaml
model_version:
  re: '^\s*version: (\S+)'   # required (tables use `start:` instead)
  contains: 'version:'       # literal prefilter, see below
  ignorecase: false
  preamble: false            # see "The job script preamble"
```

Patterns are Python regular expressions, matched with `re.search` against the
line *after* the timestamp and rank prefix have been removed. Anchor a pattern
with `^` to refer to the start of the message.

(profile-contains)=

### `contains` and why it matters

Rules are applied to every line of the file, and a file can hold a million
lines. Before running a regular expression, `runhealth` checks whether a
literal substring is present, which is much cheaper. It derives that literal
from the pattern itself and falls back to always running the regular expression
whenever the pattern contains an alternation or a quantifier that could make
the literal optional.

Specify `contains:` explicitly when the derivation fails but a literal is known
to appear. For a pattern such as `'Constructing the .* coupling frame'`, the
hint `coupling frame` saves considerable time. The literal must appear in
**every** line the pattern matches, otherwise those lines are silently skipped.

## Detection

```yaml
detect:
  - 'master_control: start model initialization'
  - 'Timer report, ranks'
  - '# ICON run script'
```

Any match within the first 8 MB of the log selects the profile. Include a
pattern that survives an early crash: a job that dies during MPI startup prints
none of the model's own output, but the run script echoed at the top of the
file is still present.

## The job script preamble

Many run scripts echo a copy of themselves before their output begins to be
timestamped. That copy contains every string the script can ever print,
including both its success and its failure message, so rules must not fire
there. In a timestamped log, `runhealth` treats everything before the first
timestamp as preamble and applies only rules marked `preamble: true` to it,
which is how `#SBATCH` directives are read.

Two consequences for profile authors:

- Anchor an `outcome` pattern with `^` so that it matches the printed line and
  not the `echo "..."` that produced it.
- Mark a rule `preamble: true` when it should match only within the job script.

## Sections

### `fields`: one value per run

```yaml
fields:
  model_version: {re: '^\s*version: (\S+)', contains: 'version:'}
  node_count:    {re: '^SLURM_JOB_NUM_NODES=(\d+)', cast: int}
  final_status:  {re: '^Status: (.+)', keep: last}
```

`group` picks the capture group (default 1), `cast` is `int` or `float`, and
`keep` is `first` (default) or `last`.

### `keyvalues`: a dictionary

The pattern must capture two groups: the key and the value.

```yaml
keyvalues:
  sbatch:
    re: '^\s*#SBATCH\s+--([A-Za-z0-9_-]+)=?\s*(.*)$'
    contains: '#SBATCH'
    preamble: true
  slurm_env:
    re: '^(SLURM[A-Z_0-9]*)=(.*)$'
    contains: SLURM
```

`sbatch` is special: its `time` entry is read as the requested wall-clock limit,
which the wall-time check and the attempt-boundary detection both rely on.

### `series`: repeated events

```yaml
series:
  timestep:
    re: 'Time step:\s+(\d+) model time (\d\S* \S+)'
    contains: 'Time step:'
    fields: [step, model_time]
    cast: {step: int}
    role: progress
```

`fields` names the capture groups. Each event also carries the wall clock of its
line.

`role` marks what the series is for:

- `progress`: the throughput signal. Wall time between consecutive events
  gives the progress rate; if a captured field named by
  `settings.model_time_field` parses as a date, the simulated-time rate is
  computed as well.
- `io`: output and checkpoint events, ticked on the timeline.

### `markers`: phases

```yaml
markers:
  model_init:
    re: 'master_control: start model initialization'
    label: model init
  first_step:
    re: 'Time step:\s+1 model time'
    label: time loop
```

Markers divide the wall clock into phases. **The label names the interval that
starts at the marker**, not the marker itself, which is why `first_step` is
labeled `time loop`. Only the first occurrence is kept unless `all: true` is
set.

### `groups`: messages that must not be stored

A file can contain hundreds of thousands of copies of a single warning.
`groups` counts them instead of storing them.

```yaml
groups:
  icon_warning:
    re: 'WARNING PE:\s+(\d+)\s+(\S+)'
    contains: 'WARNING PE:'
    key: 2              # capture group to group by (0 = the whole match)
    node: 5             # capture group holding a node name, if any
    label: ICON warnings
    claim: true         # keep these lines out of the generic error scan
```

Counts are kept per key, per node and per minute of the run. `claim: true`
tells the core that this family is already accounted for, so that the same
lines are not additionally collected as anonymous errors.

### `tables`: structured blocks

Two shapes are supported.

**`ruled`**: columns delimited by a rule row of dash sequences, with a header
row beside it. The rule row defines exact column spans, so a name containing
spaces never has to be guessed.

```yaml
tables:
  timers:
    start: 'Timer report, ranks (\d+)-(\d+)'
    contains: 'Timer report, ranks'
    kind: ruled
    nesting: '^(\s*)L '        # indentation to tree depth
    durations: [t_min, t_avg, t_max]   # columns holding 16m43s-style values
```

**`trailing-numbers`**: no rule rows; each row is a label followed by a fixed
number of numeric fields, so a label containing spaces still works.

```yaml
  cxi_counters:
    start: '^MPICH Slingshot CXI Counter Summary:'
    kind: trailing-numbers
  cxi_ratios:
    start: '^Computed Ratios'
    kind: trailing-numbers
    include_start: true        # the start line is itself the header row
```

The block ends at a closing rule row or a blank line. A table opened by a
rank-labeled line accepts only lines from that same rank, so interleaved output
from other ranks does not corrupt it.

(profile-outcome)=

### `outcome`: the verdict

```yaml
outcome:
  - {re: '^Script FAILED: (.+)', contains: 'Script FAILED', level: fail}
  - {re: '^Script run successfully: (.+)', level: ok}
```

`level` is `ok`, `fail` or `info`. The **last** match in the file takes
precedence, since the actual verdict is written at the end. Capture group 1
becomes the text shown in the report.

### `attempt_boundary`

```yaml
attempt_boundary:
  - '^end_of_job_script'
```

A resubmitted job can append to the same file. `runhealth` already detects this
from a sequence of unstamped lines, or from a pause longer than the scheduler
could have allowed, and analyzes only the last attempt. A profile can add a
precise marker of its own. Boundary rules are ignored until a sufficient part
of an attempt has been seen, so the first preamble never triggers one.

## `settings`

Names and column mappings used by the analysis. All entries are optional.

| Key | Meaning |
| --- | --- |
| `progress_label` | what the progress unit is called, e.g. `time steps` |
| `throughput_label` | what the rate is called, e.g. `SYPD` |
| `progress_series` | which series is the progress signal (otherwise the first with `role: progress`) |
| `model_time_field` | the field in that series holding a simulated date |
| `timer_table` | which table holds the timers |
| `timer_root` | the label of its overall timer, e.g. `total` |
| `timer_columns` | map of `total`, `min`, `max`, `min_rank`, `max_rank`, `calls`, `pes` to column names |
| `io_timers` | timer labels that are output rather than computation |
| `counter_table`, `ratio_table` | network counter blocks |
| `counter_columns` | map of `samples`, `min`, `mean`, `max` to column names |
| `counter_watch` | counter names worth reporting |
| `congestion_groups` | message groups that indicate fabric congestion |
| `congestion_keys` | the keys within those groups that actually indicate congestion |

(profile-thresholds)=

## `thresholds`

Every number a check compares against. The defaults are defined in
`slurm.yaml`; a profile or a site can override any of them.

| Key | Default | Meaning |
| --- | --- | --- |
| `stall_seconds` | 300 | silence inside the main loop that fails a run |
| `setup_stall_seconds` | 1200 | silence during setup that warns |
| `gap_warn_factor` | 5 | in-loop pause, as a multiple of the typical interval |
| `walltime_warn` | 0.9 | fraction of the requested limit that warns |
| `outlier_factor` | 3 | progress interval counted as an outlier |
| `imbalance_warn` | 1.25 | ratio of slowest to fastest rank that is worth reporting |
| `imbalance_fail` | 2.0 | ... and that is considered severe |
| `drift_warn` | 0.2 | slowdown between first and last quarter |
| `timer_share_floor` | 0.05 | ignore timers below this share of the run |
| `group_warn` | 1000 | message family large enough to warrant a warning ... |
| `group_share_warn` | 0.2 | ... if it is also this fraction of the whole log |
| `node_share_warn` | 0.25 | one node's share of a family that makes it suspect |

## Testing a profile

```bash
runhealth mylog.out --profile mymodel -o /tmp/check --no-plots
runhealth --list-profiles
```

If a rule never fires, the common causes are a `contains:` literal that does
not appear in every matching line, a pattern anchored with `^` that is in fact
indented, or a rule that should have been marked `preamble: true`.
