#!/bin/bash
# Check one model job with runhealth once it has ended, whatever the outcome:
#   sbatch --dependency=afterany:<jobid> runhealth.sbatch <jobid> <log directory> [report directory]
# Add the --account and --partition your site requires.
#SBATCH --job-name=runhealth
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=00:15:00
#SBATCH --output=runhealth.%j.out

set -euo pipefail

job=${1:?usage: runhealth.sbatch <jobid> <log directory> [report directory]}
logs=${2:?usage: runhealth.sbatch <jobid> <log directory> [report directory]}
report=${3:-$logs/runhealth/$job}
# The command that starts runhealth, e.g. "uv run --project $HOME/runhealth runhealth".
RUNHEALTH=${RUNHEALTH:-runhealth}

# Exit code 3 marks a failed run, so this job fails with it and an afterok
# dependency on it holds back whatever should only follow a healthy run.
$RUNHEALTH "$logs" --job-id "$job" --fail-on fail -o "$report" ${RUNHEALTH_PUBLISH:+--publish}
