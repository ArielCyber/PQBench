#!/usr/bin/env bash
# PQBench macOS bootstrapper
# - Ensures Python3 + pip
# - Creates venv & installs deps
# - Installs a LaunchAgent to run processor.py on login
# - Disables sleep (pmset) and adds a caffeinate LaunchAgent fallback
# - Ensures 'sudo mount_9p shared' persists across reboots (LaunchDaemon)
# - Installs browsers (Chrome/Firefox) + drivers based on MODE
# - Skips re-download if a browser is already installed

set -euo pipefail

# -------------------------
# Globals & paths
# -------------------------
MODE="${MODE:-nonpq}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="com.pqbench.processor"
VENV_DIR="${REPO_DIR}/.venv"
REQ="${REPO_DIR}/requirements.txt"
RUNNER="${REPO_DIR}/run_processor.sh"
LOG_DIR="${HOME}/Library/Logs"
LA_DIR="${HOME}/Library/LaunchAgents"
LD_DIR="/Library/LaunchDaemons"
CAFFEINATE_ID="com.pqbench.caffeinate"
MOUNT9P_ID="com.pqbench.mount9p"
BIN_DIR="/usr/local/bin"   # will fallback to /opt/homebrew/bin on Apple Silicon if needed

# Ensure sudo early for daemon installs & /Applications modifications
if [[ "$EUID" -ne 0 ]]; then
  # Re-exec with sudo preserving env MODE to keep version selection deterministic
  export MODE
fi

# Detect arch for URLs (Chrome/driver & Firefox/geckodriver)
_mac_arch() {
  if [[ "$(uname -m)" == "arm64" ]]; then
    echo "arm64"
  else
    echo "x64"
  fi
}

# Prefer a writable bin dir
_pick_bin_dir() {
  if [[ -d "/opt/homebrew/bin" ]]; then
    echo "/opt/homebrew/bin"
  else
    echo "/usr/local/bin"
  fi
}
BIN_DIR="$(_pick_bin_dir)"

# -------------------------
# Versions by MODE
# -------------------------
choose_browser_versions() {
  case "${MODE}" in
    KYBER)
      CHROME_VERSION="128.0.6613.137"
      FIREFOX_VERSION="130.0.1"
      FIREFOX_APP_NAME="Firefox.app"
      CHROME_APP_NAME="Google Chrome.app"
      ;;
    MLKEM)
      CHROME_VERSION="139.0.7258.155"
      FIREFOX_VERSION="142.0.1"
      FIREFOX_APP_NAME="Firefox.app"
      CHROME_APP_NAME="Google Chrome.app"
      ;;
    *)
      CHROME_VERSION=""
      FIREFOX_VERSION=""
      ;;
  esac
}

# -------------------------
# Utilities
# -------------------------
_info() { echo -e "\033[1;34m==>\033[0m $*"; }
_warn() { echo -e "\033[1;33m[!]\033[0m $*"; }
_err()  { echo -e "\033[1;31m[✗]\033[0m $*" >&2; }

require_root_for_daemons() {
  if [[ "$EUID" -ne 0 ]]; then
    _info "Requesting sudo for system daemons (mount_9p & installs)..."
    sudo -v
  fi
}

mdread_version() {
  # Read CFBundleShortVersionString from an app bundle if possible
  local app_path="$1"
  /usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
    "${app_path}/Contents/Info.plist" 2>/dev/null || true
}

ensure_dirs() {
  mkdir -p "${LOG_DIR}" "${LA_DIR}"
}

# -------------------------
# Python & venv
# -------------------------
ensure_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    _err "python3 not found. Install Xcode CLT or Python via Homebrew, then re-run."
    exit 1
  fi
  _info "Python3 found: $(python3 --version)"
}

create_venv_install_deps() {
  if [[ ! -d "${VENV_DIR}" ]]; then
    _info "Creating venv at ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
  fi
  # shellcheck disable=SC1091
  source "${VENV_DIR}/bin/activate"
  python -m pip install --upgrade pip
  if [[ -f "${REQ}" ]]; then
    _info "Installing Python deps from ${REQ}"
    # macOS venvs often don't need --break-system-packages; omit to be safe.
    python -m pip install -r "${REQ}"
  else
    _warn "No requirements.txt found; skipping pip install."
  fi
}

# -------------------------
# Runner & LaunchAgent
# -------------------------
make_runner() {
  cat > "${RUNNER}" <<'EOF'
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
EOF
  chmod +x "${RUNNER}"
  _info "Created runner: ${RUNNER}"
}

install_launchagent() {
  local PLIST="${LA_DIR}/${APP_ID}.plist"
  if [[ -d "/opt/homebrew/bin" ]]; then
  SHELL_ENV="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  else
    SHELL_ENV="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  fi
  # prepend our chosen BIN_DIR if it isn't already there
  if [[ ":${SHELL_ENV}:" != *":${BIN_DIR}:"* ]]; then
    SHELL_ENV="${BIN_DIR}:${SHELL_ENV}"
  fi

  cat > "${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${APP_ID}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${RUNNER}</string>
  </array>
  <key>WorkingDirectory</key><string>${REPO_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MODE</key><string>${MODE}</string>
    <key>PATH</key><string>${SHELL_ENV}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${LOG_DIR}/pqbench-processor.launchd.out.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/pqbench-processor.launchd.err.log</string>
</dict>
</plist>
EOF

  _info "Installed LaunchAgent: ${PLIST}"
  launchctl unload "${PLIST}" >/dev/null 2>&1 || true
  launchctl load -w "${PLIST}"
  _info "LaunchAgent loaded (runs now and on login)."
}

# -------------------------
# Sleep prevention
# -------------------------
disable_sleep_pmset() {
  require_root_for_daemons
  _info "Disabling system sleep via pmset..."
  sudo pmset -a sleep 0 displaysleep 0 disksleep 0 || _warn "pmset tweak failed; continuing."
}

install_caffeinate_agent() {
  local PLIST="${LA_DIR}/${CAFFEINATE_ID}.plist"
  cat > "${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${CAFFEINATE_ID}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-dimsu</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${LOG_DIR}/pqbench-caffeinate.out.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/pqbench-caffeinate.err.log</string>
</dict>
</plist>
EOF
  _info "Installed caffeinate LaunchAgent: ${PLIST}"
  launchctl unload "${PLIST}" >/dev/null 2>&1 || true
  launchctl load -w "${PLIST}"
}

ensure_bin_dir() {
  # Create a writable bin dir if missing (works on both Intel & Apple Silicon VMs)
  if [[ ! -d "${BIN_DIR}" ]]; then
    require_root_for_daemons
    sudo mkdir -p "${BIN_DIR}"
    sudo chmod 755 "${BIN_DIR}"
  fi
}

# -------------------------
# Persistent mount_9p shared
# -------------------------
install_mount9p_daemon() {
  require_root_for_daemons
  local PLIST="/Library/LaunchDaemons/${MOUNT9P_ID}.plist"
  # The command should be run as root at boot
  sudo bash -c "cat > '${PLIST}'" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.pqbench.mount9p</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/sbin/mount_9p</string>
    <string>shared</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/var/log/pqbench-mount9p.out.log</string>
  <key>StandardErrorPath</key><string>/var/log/pqbench-mount9p.err.log</string>
</dict>
</plist>
EOF
  sudo chown root:wheel "${PLIST}"
  sudo chmod 644 "${PLIST}"
  _info "Installed LaunchDaemon: ${PLIST}"
  sudo launchctl unload "${PLIST}" >/dev/null 2>&1 || true
  sudo launchctl load -w "${PLIST}"
  _info "Mount daemon loaded (will attempt mount_9p shared at boot)."
}

# -------------------------
# Browser installers (idempotent)
# -------------------------

is_chrome_installed() {
  [[ -d "/Applications/Google Chrome.app" ]] && return 0
  [[ -d "/Applications/Google Chrome Canary.app" ]] && return 0
  return 1
}

get_chrome_version() {
  mdread_version "/Applications/Google Chrome.app"
}

install_chrome_and_driver() {
  if [[ -z "${CHROME_VERSION:-}" ]]; then
    _info "No CHROME_VERSION set (MODE=${MODE}). Skipping Chrome install."
    return 0
  fi

  ensure_bin_dir

  if is_chrome_installed; then
    local have_ver
    have_ver="$(get_chrome_version || true)"
    _info "Chrome already installed (version: ${have_ver:-unknown}); skipping download."
  else
    _info "Installing Chrome ${CHROME_VERSION}..."
    local ARCH CFT_BASE ZIP_URL TMP EXTRACT_DIR APP_SRC
    ARCH="$(_mac_arch)"
    CFT_BASE="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}"
    if [[ "${ARCH}" == "arm64" ]]; then
      ZIP_URL="${CFT_BASE}/mac-arm64/chrome-mac-arm64.zip"
    else
      ZIP_URL="${CFT_BASE}/mac-x64/chrome-mac-x64.zip"
    fi

    TMP="$(mktemp -d /tmp/pqbench.chrome.XXXXXX)"
    EXTRACT_DIR="${TMP}/extract"
    mkdir -p "${EXTRACT_DIR}"

    _info "Downloading: ${ZIP_URL}"
    if ! curl -fLsS "${ZIP_URL}" -o "${TMP}/chrome.zip"; then
      _err "Download failed (404 or network). URL: ${ZIP_URL}"
      return 1
    fi

    _info "Unzipping into ${EXTRACT_DIR} ..."
    if ! unzip -q "${TMP}/chrome.zip" -d "${EXTRACT_DIR}"; then
      _err "Unzip failed; archive may be corrupt."
      rm -rf "${TMP}"
      return 1
    fi

    # Try several patterns; some archives use 'chrome-mac*/Google Chrome for Testing.app',
    # others slightly differ. Use a broad search and pick the first match.
    APP_SRC="$(find "${EXTRACT_DIR}" -type d \( -iname 'Google Chrome for Testing.app' -o -iname 'Google Chrome.app' -o -ipath '*/chrome-mac*/Google Chrome*.app' \) -print -quit)"

    if [[ -z "${APP_SRC}" ]]; then
      _err "Chrome .app not found after unzip. Here are the extracted contents (depth <= 4):"
      (cd "${EXTRACT_DIR}" && find . -maxdepth 4 -print) || true
      rm -rf "${TMP}"
      return 1
    fi

    require_root_for_daemons
    # Clean any previous broken install/symlink
    [[ -L "/Applications/Google Chrome.app" ]] && sudo rm -f "/Applications/Google Chrome.app"
    sudo rm -rf "/Applications/Google Chrome.app" || true
    _info "Copying ${APP_SRC} -> /Applications/Google Chrome.app"
    sudo ditto "${APP_SRC}" "/Applications/Google Chrome.app"
    sudo xattr -dr com.apple.quarantine "/Applications/Google Chrome.app" || true
    rm -rf "${TMP}"
    _info "Installed Chrome to /Applications/Google Chrome.app"
  fi

  # Install matching chromedriver if absent
  local DRIVER_TARGET="${BIN_DIR}/chromedriver"
  if command -v chromedriver >/dev/null 2>&1; then
    _info "chromedriver already present at $(command -v chromedriver); skipping."
    return 0
  fi

  _info "Installing chromedriver for Chrome ${CHROME_VERSION}..."
  local DR_URL TMPD EXTRACT DRIVER_SRC CFT_BASE2
  CFT_BASE2="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}"
  if [[ "$(_mac_arch)" == "arm64" ]]; then
    DR_URL="${CFT_BASE2}/mac-arm64/chromedriver-mac-arm64.zip"
  else
    DR_URL="${CFT_BASE2}/mac-x64/chromedriver-mac-x64.zip"
  fi
  TMPD="$(mktemp -d /tmp/pqbench.cdriver.XXXXXX)"
  EXTRACT="${TMPD}/extract"
  mkdir -p "${EXTRACT}"

  if ! curl -fLsS "${DR_URL}" -o "${TMPD}/driver.zip"; then
    _err "Failed to download chromedriver: ${DR_URL}"
    rm -rf "${TMPD}"
    return 1
  fi
  if ! unzip -q "${TMPD}/driver.zip" -d "${EXTRACT}"; then
    _err "Unzip of chromedriver failed."
    rm -rf "${TMPD}"
    return 1
  fi

  DRIVER_SRC="$(find "${EXTRACT}" -type f -name 'chromedriver' -print -quit)"
  if [[ -z "${DRIVER_SRC}" ]]; then
    _err "chromedriver not found after unzip. Contents:"
    (cd "${EXTRACT}" && find . -maxdepth 4 -print) || true
    rm -rf "${TMPD}"
    return 1
  fi

  require_root_for_daemons
  sudo install -m 0755 "${DRIVER_SRC}" "${DRIVER_TARGET}"
  rm -rf "${TMPD}"
  _info "chromedriver installed to ${DRIVER_TARGET}"
}


is_firefox_installed() {
  [[ -d "/Applications/Firefox.app" ]] && return 0
  return 1
}

get_firefox_version() {
  mdread_version "/Applications/Firefox.app"
}

install_firefox_and_geckodriver() {
  if [[ -z "${FIREFOX_VERSION:-}" ]]; then
    _info "No FIREFOX_VERSION set (MODE=${MODE}). Skipping Firefox install."
    return 0
  fi

  ensure_bin_dir

  if is_firefox_installed; then
    local have_ver
    have_ver="$(get_firefox_version || true)"
    _info "Firefox already installed (version: ${have_ver:-unknown}); skipping download."
  else
    _info "Installing Firefox ${FIREFOX_VERSION}..."
    local ARCH
    if [[ "$(_mac_arch)" == "arm64" ]]; then
      ARCH="aarch64"
    else
      ARCH="x86_64"
    fi
    # Official release DMG archive (cdn.mozilla.net)
    local TMP; TMP="$(mktemp -d /tmp/pqbench.firefox.XXXXXX)"
    local DMG="${TMP}/Firefox-${FIREFOX_VERSION}.dmg"
    local MNT="${TMP}/mnt"
    # en-US locale; adjust if you need a different locale.
    local URL="https://download-installer.cdn.mozilla.net/pub/firefox/releases/${FIREFOX_VERSION}/mac/en-US/Firefox%20${FIREFOX_VERSION}.dmg"

    _info "Downloading: ${URL}"
    if ! curl -fLso "${DMG}" "${URL}"; then
      _err "Failed to download Firefox DMG (404 or network). URL: ${URL}"
      rm -rf "${TMP}"
      return 1
    fi

    mkdir -p "${MNT}"
    if ! hdiutil attach "${DMG}" -mountpoint "${MNT}" -nobrowse -quiet; then
      _err "hdiutil attach failed."
      rm -rf "${TMP}"
      return 1
    fi

  require_root_for_daemons
  sudo rm -rf "/Applications/Firefox.app" || true
  sudo ditto "${MNT}/Firefox.app" "/Applications/Firefox.app"
  hdiutil detach "${MNT}" -quiet || true
  rm -rf "${TMP}"
  fi

  # Geckodriver (install only if not present). Pick a broadly compatible version.
  if command -v geckodriver >/dev/null 2>&1; then
    _info "geckodriver already present at $(command -v geckodriver); skipping."
    return 0
  fi

  _info "Installing geckodriver..."
  local GD_VER="0.34.0"
  local GD_TGZ
  if [[ "$(_mac_arch)" == "arm64" ]]; then
    GD_TGZ="geckodriver-v${GD_VER}-macos-aarch64.tar.gz"
  else
    GD_TGZ="geckodriver-v${GD_VER}-macos.tar.gz"
  fi
  local TMP; TMP="$(mktemp -d /tmp/pqbench.gd.XXXXXX)"
  curl -fsSLo "${TMP}/${GD_TGZ}" "https://github.com/mozilla/geckodriver/releases/download/v${GD_VER}/${GD_TGZ}"
  tar -xzf "${TMP}/${GD_TGZ}" -C "${TMP}"
  require_root_for_daemons
  sudo install -m 0755 "${TMP}/geckodriver" "${BIN_DIR}/geckodriver"
  rm -rf "${TMP}"
  _info "geckodriver installed to ${BIN_DIR}/geckodriver"
}

install_browsers() {
  choose_browser_versions
  if [[ -z "${CHROME_VERSION}" && -z "${FIREFOX_VERSION}" ]]; then
    _info "MODE=${MODE} => No browser installs requested."
    return 0
  fi
  install_chrome_and_driver
  install_firefox_and_geckodriver
}

# -------------------------
# Orchestration
# -------------------------
main() {
  _info "PQBench macOS setup (MODE=${MODE})"
  ensure_dirs
  ensure_python
  create_venv_install_deps
  make_runner
  install_launchagent
  disable_sleep_pmset
  install_caffeinate_agent
  install_mount9p_daemon
  install_browsers

  _info "Done. Logs: ${LOG_DIR}"
  _info "Processor will also (re)start via LaunchAgent on login."
  _info "Starting processor.py now..."
  "${RUNNER}"
}


main "$@"
