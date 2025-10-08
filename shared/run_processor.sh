#!/usr/bin/env bash
set -euo pipefail
MODE="${MODE:-nonpq}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${REPO_DIR}/.venv"
PY="${VENV_DIR}/bin/python"
PROC="${REPO_DIR}/processor.py"
LOG_DIR="${HOME}/Library/Logs"
LOG_OUT="${LOG_DIR}/pqbench-processor.out.log"
LOG_ERR="${LOG_DIR}/pqbench-processor.err.log"
mkdir -p "${LOG_DIR}"
{
  echo "=== $(date) :: Starting processor (MODE=${MODE}) ==="
  echo "Repo: ${REPO_DIR}"
  echo "Python: ${PY}"
} >> "${LOG_OUT}"

# send stdout/stderr to both terminal and log files
exec "${PY}" "${PROC}" \
  > >(tee -a "${LOG_OUT}") \
  2> >(tee -a "${LOG_ERR}" >&2)
