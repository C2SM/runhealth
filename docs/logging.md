# Get more out of your logs

`runhealth` reports what a log contains. Two cheap changes to a job script make
it contain much more.

## 1. Stamp every line with the wall clock

Without it there is no silence detection, the single most valuable signal, no
phase timeline and no progress rate, and `runhealth` says so rather than
guessing. Any line-buffered filter will do:

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

## 2. Turn on the MPI stack's counters

On Cray MPICH, `MPICH_OFI_CXI_COUNTER_REPORT=3` and `FI_LOG_LEVEL=warn` cost
nothing and turn "the run was slow" into "the fabric dropped 640k flow-control
messages in one minute".

Also worth having: `srun -l` for rank labels, and your model's timers switched
on.
