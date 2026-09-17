# Improving log quality

`runhealth` reports what a log contains. Two low-cost changes to a job script
substantially increase the amount of information available.

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

ICON ships `utils/timewarp`, which does exactly this.

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
