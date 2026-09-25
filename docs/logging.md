# Improving log quality

`runhealth` reports what a log contains. A few inexpensive changes to a job
script substantially increase the amount of information available.

## 1. Add a wall-clock timestamp to every line

Without timestamps there is no silence detection, which is the most informative
single signal, no phase timeline and no progress rate; `runhealth` reports this
limitation rather than estimating the missing values. Any line-buffered filter
is sufficient:

```bash
pipe=job_$$.pipe
mkfifo $pipe
trap "rm -f $pipe" EXIT
python3 -u -c 'import sys,datetime
for line in sys.stdin:
    print(datetime.datetime.now().isoformat(timespec="milliseconds"), line, sep=": ", end="", flush=True)' < $pipe &
exec > $pipe 2>&1
```

ICON provides `utils/timewarp`, which performs exactly this task.

The timestamp is also what allows the report to show the submitted **run
script**: without a stamp on every line, `runhealth` cannot distinguish the
script's own echo of itself from the actual output of the run.

## 2. Enable the counters of the MPI library

On Cray MPICH, `MPICH_OFI_CXI_COUNTER_REPORT=3` and `FI_LOG_LEVEL=warn` add no
measurable overhead and replace the observation that a run was slow with the
specific finding that the fabric dropped 640k flow-control messages within one
minute.

Also recommended: `srun -l` for rank labels, and the timers of the model
itself.

## 3. Leave diagnostics next to the log

A log shows that a job went quiet, but not why. A job script can write the
output of standard tools into a directory `diag.<job name>.<job id>/` beside its
log, and `runhealth` reads it when it is present. Every part is optional:

| Path | Written by | Used for |
| --- | --- | --- |
| `gpu/<node>.csv` | `nvidia-smi --query-gpu=timestamp,index,utilization.gpu,memory.used,power.draw,temperature.gpu,clocks_event_reasons.active,ecc.errors.uncorrected.volatile.total --format=csv -l 60`, once per node | GPU health and GPU activity |
| `<node>/gdb_rank<N>.txt` | `gdb -p <pid> -batch -ex 'thread apply all bt'` during a hang | Hang backtraces |
| `<node>/proc_rank<N>.txt` | `/proc/<pid>/status`, followed by `wchan: $(cat /proc/<pid>/wchan)` | process states in Hang backtraces |
| `<node>/dmesg.txt` | `dmesg -T \| tail -n 500` | Kernel messages |

The GPU monitor runs for the whole job and costs nothing measurable; the
columns are found by their header, so a different selection works as well. The
per-rank dumps are typically collected by a hang watchdog: a background loop in
the job script that treats a log which has not grown for a given time as a
hang, runs the collection on every node with `srun --overlap`, and then ends
the model step with SIGABRT, so that Python (with `PYTHONFAULTHANDLER=1`) and
the compiler runtime print tracebacks into the log. If the script declares its
timeouts as `watchdog_timeout=${watchdog_timeout:=1800}` and
`watchdog_init_timeout=${watchdog_init_timeout:=7200}` and reports with lines
beginning `WATCHDOG: `, the `watchdog` profile reads both, see
[Profiles](profiles.md).
