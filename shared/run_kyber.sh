#!/bin/bash

set -euo pipefail

# --- PQBench env (KYBER) ---
export MODE="KYBER"

# Add any shared env your processor expects:
# export SNIFFER_URL="http://127.0.0.1:8080"
# export TARGET_HOST="pq.cloudflareresearch.com"
# export BROWSER="chrome"

# --- Delegate to setup ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "${SCRIPT_DIR}/setup_macos.sh"
"${SCRIPT_DIR}/setup_macos.sh"