#!/usr/bin/env bash
# We are removing 'set -e' for debugging so the script doesn't exit prematurely
set -uo pipefail

MODE="${MODE:-nonpq}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${HOME}/.pqbench_venv"
PY="${VENV_DIR}/bin/python"
PROC="${REPO_DIR}/processor.py"
LOG_DIR="${HOME}/Library/Logs"
LOG_OUT="${LOG_DIR}/pqbench-processor.out.log"
LOG_ERR="${LOG_DIR}/pqbench-processor.err.log"
mkdir -p "${LOG_DIR}"

# --- Forensic Logging ---
echo "--- [DEBUG] run_processor.sh started at $(date) ---" >> "${LOG_OUT}"
echo "--- [DEBUG] REPO_DIR is ${REPO_DIR}" >> "${LOG_OUT}"
echo "--- [DEBUG] VENV_DIR is ${VENV_DIR}" >> "${LOG_OUT}"

# --- Wait for the shared volume to be mounted after a reboot ---
echo "--- [DEBUG] Checking for processor script at ${PROC}..." >> "${LOG_OUT}"
MAX_RETRIES=12 # 60 seconds total wait
RETRY_COUNT=0
while [[ ! -f "${PROC}" ]]; do
  if (( RETRY_COUNT >= MAX_RETRIES )); then
    echo "--- [FATAL] Processor script not found at ${PROC} after ${MAX_RETRIES} retries. Is /Volumes/shared mounted? Exiting." >> "${LOG_ERR}"
    exit 1
  fi
  echo "--- [DEBUG] Attempt #${RETRY_COUNT}: ${PROC} not found. Waiting 5s..." >> "${LOG_OUT}"
  sleep 5
  RETRY_COUNT=$((RETRY_COUNT + 1))
done
echo "--- [DEBUG] OK: Processor script found at ${PROC}." >> "${LOG_OUT}"
# -----------------------------------------------------------------

# --- Check for Python virtual environment ---
echo "--- [DEBUG] Checking for Python executable at ${PY}..." >> "${LOG_OUT}"
if [[ ! -x "${PY}" ]]; then
    echo "--- [FATAL] Python executable not found at ${PY}. The venv might be corrupted or missing. Exiting." >> "${LOG_ERR}"
    exit 1
fi
echo "--- [DEBUG] OK: Python executable found." >> "${LOG_OUT}"
# -----------------------------------------------------------------


# send stdout/stderr to both terminal and log files
echo "--- [DEBUG] Starting Python process now... ---" >> "${LOG_OUT}"
exec "${PY}" "${PROC}" \
  > >(tee -a "${LOG_OUT}") \
  2> >(tee -a "${LOG_ERR}" >&2)
