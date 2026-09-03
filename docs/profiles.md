# Profiles

A profile is a YAML file describing what a code prints. Profiles compose:
`slurm` (always applied) plus `icon` plus `cray-mpich` describe an ICON run on a
Cray machine, and each is detected from the content of the log itself.

```bash
runhealth --list-profiles
# cray-mpich     Cray MPICH / Slingshot: CXI counters, libfabric warnings
# icon           ICON atmosphere/ocean model: progress, timer report, coupling
# slurm          SLURM batch job metadata, step failures and cancellations. (always applied)
```

| Profile | Detects | Contributes |
| --- | --- | --- |
| `slurm` | always | `#SBATCH` directives, the SLURM environment, `srun` step failures, cancellations, wall-clock limits |
| `icon` | ICON output or a generated ICON runscript | time steps and SYPD, the timer report, coupling and I/O phases, `WARNING PE` families, the success/failure protocol |
| `cray-mpich` | Slingshot or libfabric output | the CXI counter summary, libfabric flow-control warnings, MPICH aborts |

## Adding your own

Drop a YAML file in a directory and point `runhealth` at it:

```bash
runhealth /path/to/logs --profile-dir ./my-profiles
export RUNHEALTH_PROFILE_DIR=$HOME/.runhealth   # or set it once
```

Here is a complete profile for a solver that prints
`iteration 42, residual 1.0e-6`:

```yaml
name: mysolver
description: "Iterative solver: progress and convergence"
detect:
  - 'mysolver v[0-9]'

settings:
  progress_label: iterations
  progress_series: iteration

series:
  iteration:
    re: 'iteration (\d+), residual (\S+)'
    fields: [step, residual]
    cast: {step: int}
    role: progress

markers:
  solve_start: {re: 'entering solve', label: solve}

outcome:
  - {re: '^converged in (\d+) iterations', level: ok}
  - {re: '^diverged after (\d+) iterations', level: fail}
```

That is enough for throughput, a progress-rate plot, phase timing, stall
detection against the typical iteration time, and a verdict. `--profile
mysolver` pins it; without that flag it is detected automatically.

The full schema, covering timer tables, message families and thresholds, is in
the [profile reference](profile-reference.md).

```{toctree}
:maxdepth: 2
:hidden:

profile-reference
```
