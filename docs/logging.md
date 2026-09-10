# Get more out of your logs

`runhealth` reports what a log contains. Two inexpensive changes to a job
script make it contain considerably more.

## 1. Stamp every line with the wall clock

Without a timestamp there is no silence detection, which is the single most
valuable signal, no phase timeline and no progress rate, and `runhealth`
states this rather than guessing. Any line-buffered filter is sufficient:

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

## 2. Turn on the MPI stack's counters

On Cray MPICH, `MPICH_OFI_CXI_COUNTER_REPORT=3` and `FI_LOG_LEVEL=warn` cost
nothing and turn "the run was slow" into "the fabric dropped 640k flow-control
messages in one minute".

Also worth enabling: `srun -l` for rank labels, and the model's own timers.
