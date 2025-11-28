set -euo pipefail

# --- PQBench env (KYBER) ---
export MODE="KYBER"

# --- Delegate to setup ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "${SCRIPT_DIR}/setup_macos.sh"
"${SCRIPT_DIR}/setup_macos.sh"