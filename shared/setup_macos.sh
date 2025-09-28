#!/bin/bash

# Ensure bash even if someone invokes with sh
[ -n "$BASH_VERSION" ] || { echo "Please run with bash:  bash setup_macos.sh"; exit 1; }
set -euo pipefail

# =========================
# PQBench macOS bootstrapper
# - Ensures Python3 + pip
# - Creates venv & installs deps
# - Installs a LaunchAgent to run processor.py on login
# - Disables sleep (pmset) and adds a caffeinate LaunchAgent fallback
# - Ensures 'sudo mount_9p shared' persists across reboots (LaunchDaemon)
# - Installs browsers (Chrome/Firefox) + drivers based on MODE
# =========================

MODE="${MODE:-nonpq}"                       # run_kyber / run_mlkem set this; keep default if you ever run manually
APP_ID="com.pqbench.processor"
CAFFEINATE_ID="com.pqbench.caffeinate"
MOUNT9P_ID="com.pqbench.mount9p"
LA_DIR="${HOME}/Library/LaunchAgents"
LD_DIR="/Library/LaunchDaemons"
LOG_DIR="${HOME}/Library/Logs"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${REPO_DIR}/.venv"
RUNNER="${REPO_DIR}/run_processor.sh"
PY="${VENV_DIR}/bin/python"
PROC="${REPO_DIR}/processor.py"

mkdir -p "${LA_DIR}" "${LOG_DIR}"

echo "==> PQBench setup (macOS) | MODE=${MODE}"
echo "==> Repo: ${REPO_DIR}"

need_cmd() { command -v "$1" >/dev/null 2>&1; }

ensure_homebrew() {
  if ! need_cmd brew; then
    echo "==> Homebrew not found. Installing..."
    NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [[ -d "/opt/homebrew/bin" ]]; then
      eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -d "/usr/local/bin" ]]; then
      export PATH="/usr/local/bin:${PATH}"
    fi
  else
    echo "==> Homebrew found."
  fi
}

ensure_tool() {
  # Install a tool via brew if missing
  local t="$1"
  if ! need_cmd "$t"; then
    ensure_homebrew
    echo "==> Installing ${t} via Homebrew..."
    brew install "$t"
  fi
}

ensure_python() {
  if need_cmd python3; then
    echo "==> python3 present: $(python3 -V)"
  else
    echo "==> python3 not found. Installing via Homebrew..."
    ensure_homebrew
    brew update
    brew install python
  fi
  echo "==> pip3: $(pip3 --version || true)"
}

# ---------- 9P SHARED (persistent) ----------
mount9p_now() {
  local MOUNT_BIN
  MOUNT_BIN="$(command -v mount_9p || echo /sbin/mount_9p)"
  echo "==> Ensuring 'shared' 9P mount is present (running: sudo ${MOUNT_BIN} shared)"
  if sudo "${MOUNT_BIN}" shared 2>/dev/null; then
    echo "==> 9P 'shared' mounted (or already mounted)."
  else
    echo "!! Could not mount 9P 'shared' right now. Will still install LaunchDaemon to do this on boot."
  fi
}

install_mount9p_daemon() {
  local PLIST="${LD_DIR}/${MOUNT9P_ID}.plist"
  local MOUNT_BIN
  MOUNT_BIN="$(command -v mount_9p || echo /sbin/mount_9p)"

  echo "==> Installing 9P LaunchDaemon: ${PLIST}"
  sudo /usr/bin/tee "${PLIST}" >/dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${MOUNT9P_ID}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${MOUNT_BIN}</string>
    <string>shared</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
  <key>StandardOutPath</key><string>/var/log/pqbench-mount9p.out.log</string>
  <key>StandardErrorPath</key><string>/var/log/pqbench-mount9p.err.log</string>
</dict>
</plist>
EOF
  sudo chown root:wheel "${PLIST}"
  sudo chmod 644 "${PLIST}"

  if launchctl print system | grep -q "${MOUNT9P_ID}" 2>/dev/null; then
    sudo launchctl bootout system "/${PLIST#*/}" 2>/dev/null || true
  fi
  if sudo launchctl bootstrap system "/${PLIST#*/}" 2>/dev/null; then
    sudo launchctl enable "system/${MOUNT9P_ID}" || true
    echo "==> 9P LaunchDaemon bootstrapped."
  else
    sudo launchctl unload "${PLIST}" >/dev/null 2>&1 || true
    sudo launchctl load -w "${PLIST}"
    echo "==> 9P LaunchDaemon loaded (legacy)."
  fi
}
# -------------------------------------------

# ---------- Python venv ----------
setup_venv() {
  echo "==> Creating virtualenv at ${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install --upgrade pip wheel setuptools
  if [[ -f "${REPO_DIR}/requirements.txt" ]]; then
    echo "==> Installing requirements.txt"
    "${VENV_DIR}/bin/pip" install -r "${REPO_DIR}/requirements.txt"
  else
    echo "==> No requirements.txt found; skipping."
  fi
}

# ---------- Browser install (Chrome/Firefox + drivers) ----------
# Arch detection
ARCH="$(uname -m)"
if [[ "$ARCH" == "arm64" ]]; then
  CHROME_ARCH="mac-arm64"
  FIREFOX_ARCH="macos-aarch64"
else
  CHROME_ARCH="mac-x64"
  FIREFOX_ARCH="macos"
fi

# Versions & URLs by MODE (from your snippet)
choose_browser_versions() {
  case "${MODE}" in
    kyber)
      CHROME_VERSION="128.0.6613.137"
      FIREFOX_VERSION="130.0.1"
      FIREFOX_APP_NAME="Firefox 130.app"
      CHROME_APP_NAME="Google Chrome 128.app"
      FIREFOX_URL="https://download.mozilla.org/?product=firefox-130.0.1-ssl&os=osx&lang=en-US"
      ;;
    mlkem)
      CHROME_VERSION="138.0.7204.183"
      FIREFOX_VERSION="142.0.1"
      FIREFOX_APP_NAME="Firefox 142.app"
      CHROME_APP_NAME="Google Chrome 138.app"
      FIREFOX_URL="https://download.mozilla.org/?product=firefox-142.0.1-ssl&os=osx&lang=en-US"
      ;;
    *)
      CHROME_VERSION=""
      FIREFOX_VERSION=""
      ;;
  esac
}

install_chrome_and_driver() {
  [[ -z "${CHROME_VERSION}" ]] && { echo "==> MODE=${MODE}: skipping Chrome setup."; return 0; }

  ensure_tool unzip   # required for zip extraction
  local CHROME_PATH="/Applications/${CHROME_APP_NAME}"

  if [[ ! -d "${CHROME_PATH}" ]]; then
    echo "==> Installing Chrome ${CHROME_VERSION}..."
    local URL="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/${CHROME_ARCH}/chrome-${CHROME_ARCH}.zip"
    rm -rf chrome_temp chrome.zip
    curl -L -o chrome.zip "${URL}"
    unzip -q chrome.zip -d chrome_temp

    local CHROME_APP_PATH
    CHROME_APP_PATH="$(find chrome_temp -type d -name 'Google Chrome for Testing.app' | head -n 1 || true)"
    if [[ -z "${CHROME_APP_PATH:-}" ]]; then
      echo "!! Error: Google Chrome for Testing.app not found in archive"
      rm -rf chrome.zip chrome_temp
      exit 1
    fi

    mv "${CHROME_APP_PATH}" "${CHROME_APP_NAME}"
    sudo mv "${CHROME_APP_NAME}" "${CHROME_PATH}"
    rm -rf chrome.zip chrome_temp
  else
    echo "==> Chrome ${CHROME_VERSION} already installed at ${CHROME_PATH}."
  fi

  # ChromeDriver
  local DRIVER_PATH="/usr/local/bin/chromedriver-${CHROME_VERSION}"
  local SYMLINK_PATH="/usr/local/bin/chromedriver"
  if [[ ! -f "${DRIVER_PATH}" ]]; then
    echo "==> Installing ChromeDriver ${CHROME_VERSION}..."
    local ZIP_NAME="chromedriver-${CHROME_ARCH}.zip"
    local DL_URL="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/${CHROME_ARCH}/chromedriver-${CHROME_ARCH}.zip"
    rm -rf "${ZIP_NAME}" chromedriver_temp
    curl -L -o "${ZIP_NAME}" "${DL_URL}"
    unzip -q "${ZIP_NAME}" -d chromedriver_temp
    local CHROMEDRIVER_BINARY
    CHROMEDRIVER_BINARY="$(find chromedriver_temp -type f -name chromedriver | head -n 1 || true)"
    if [[ -z "${CHROMEDRIVER_BINARY:-}" ]]; then
      echo "!! Error: chromedriver binary not found!"
      rm -rf "${ZIP_NAME}" chromedriver_temp
      exit 1
    fi
    sudo mv "${CHROMEDRIVER_BINARY}" "${DRIVER_PATH}"
    sudo chmod +x "${DRIVER_PATH}"
    rm -rf "${ZIP_NAME}" chromedriver_temp
  else
    echo "==> ChromeDriver ${CHROME_VERSION} already installed."
  fi

  # Maintain a stable symlink
  if [[ ! -L "${SYMLINK_PATH}" || "$(readlink "${SYMLINK_PATH}")" != "${DRIVER_PATH}" ]]; then
    echo "==> Linking ${SYMLINK_PATH} -> ${DRIVER_PATH}"
    sudo ln -sf "${DRIVER_PATH}" "${SYMLINK_PATH}"
  else
    echo "==> ChromeDriver symlink already correct."
  fi
}

install_firefox_and_geckodriver() {
  [[ -z "${FIREFOX_VERSION}" ]] && { echo "==> MODE=${MODE}: skipping Firefox setup."; return 0; }

  local FIREFOX_PATH="/Applications/${FIREFOX_APP_NAME}"
  if [[ ! -d "${FIREFOX_PATH}" ]]; then
    echo "==> Downloading Firefox ${FIREFOX_VERSION}..."
    rm -f firefox.dmg
    curl -L -o firefox.dmg "${FIREFOX_URL}"

    echo "==> Mounting Firefox DMG..."
    # Capture mountpoint to detach reliably
    MOUNT_OUT="$(hdiutil attach firefox.dmg -nobrowse)"
    VOL_PATH="$(echo "${MOUNT_OUT}" | awk -F'\t' '/\/Volumes\//{print $NF; exit}')"
    if [[ -z "${VOL_PATH:-}" || ! -d "${VOL_PATH}" ]]; then
      echo "!! Could not determine Firefox volume mountpoint."
      hdiutil detach "/Volumes/Firefox" >/dev/null 2>&1 || true
      rm -f firefox.dmg
      exit 1
    fi

    echo "==> Copying Firefox to /Applications..."
    cp -R "${VOL_PATH}/Firefox.app" "${FIREFOX_PATH}" 2>/dev/null || sudo cp -R "${VOL_PATH}/Firefox.app" "${FIREFOX_PATH}"

    echo "==> Unmounting Firefox..."
    hdiutil detach "${VOL_PATH}" || true
    rm -f firefox.dmg
  else
    echo "==> Firefox ${FIREFOX_VERSION} already installed."
  fi

  # Geckodriver
  local GECKODRIVER_VERSION="v0.34.0"
  local GECKO_TARGET="/usr/local/bin/geckodriver"
  local WANT_VERSION_STR="${GECKODRIVER_VERSION}"
  if ! command -v geckodriver >/dev/null 2>&1 || [[ "$("${GECKO_TARGET}" --version 2>/dev/null || echo "")" != *"${WANT_VERSION_STR}"* ]]; then
    echo "==> Installing geckodriver ${GECKODRIVER_VERSION}..."
    local TGZ="geckodriver-${GECKODRIVER_VERSION}-${FIREFOX_ARCH}.tar.gz"
    rm -f geckodriver.tar.gz geckodriver "${TGZ}"
    curl -L -o geckodriver.tar.gz "https://github.com/mozilla/geckodriver/releases/download/${GECKODRIVER_VERSION}/geckodriver-${GECKODRIVER_VERSION}-${FIREFOX_ARCH}.tar.gz"
    tar -xzf geckodriver.tar.gz
    sudo mv geckodriver "${GECKO_TARGET}"
    sudo chmod +x "${GECKO_TARGET}"
    rm -f geckodriver.tar.gz
  else
    echo "==> geckodriver ${GECKODRIVER_VERSION} already installed."
  fi
}

install_browsers() {
  choose_browser_versions
  if [[ -z "${CHROME_VERSION}" && -z "${FIREFOX_VERSION}" ]]; then
    echo "==> MODE=${MODE} (nonpq) — skipping browser installs."
    return 0
  fi
  install_chrome_and_driver
  install_firefox_and_geckodriver
}
# --------------------------------------------

# ---------- Runner & LaunchAgent ----------
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
exec "${PY}" "${PROC}" 1>>"${LOG_OUT}" 2>>"${LOG_ERR}"
EOF
  chmod +x "${RUNNER}"
  echo "==> Created runner: ${RUNNER}"
}

install_launchagent() {
  local PLIST="${LA_DIR}/${APP_ID}.plist"
  local SHELL_ENV=""
  if [[ -d "/opt/homebrew/bin" ]]; then
    SHELL_ENV="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  else
    SHELL_ENV="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
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

  echo "==> Installed LaunchAgent: ${PLIST}"
  launchctl unload "${PLIST}" >/dev/null 2>&1 || true
  launchctl load -w "${PLIST}"
  echo "==> LaunchAgent loaded (will run now and on login)."
}

# ---------- Power (no sleep) ----------
disable_sleep_pmset() {
  echo "==> Attempting to disable system sleep via pmset (may require sudo)..."
  if command -v pmset >/dev/null 2>&1; then
    sudo pmset -a sleep 0 || true
    sudo pmset -a displaysleep 0 || true
    sudo pmset -a disksleep 0 || true
    sudo pmset -a disablesleep 1 || true
  fi
}

install_caffeinate_agent() {
  local PLIST="${LA_DIR}/${CAFFEINATE_ID}.plist"
  local CAFF_LOG="${LOG_DIR}/pqbench-caffeinate.log"
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
  <key>StandardOutPath</key><string>${CAFF_LOG}</string>
  <key>StandardErrorPath</key><string>${CAFF_LOG}</string>
</dict>
</plist>
EOF
  echo "==> Installed caffeinate fallback LaunchAgent: ${PLIST}"
  launchctl unload "${PLIST}" >/dev/null 2>&1 || true
  launchctl load -w "${PLIST}"
  echo "==> caffeinate agent loaded (prevents sleep as a fallback)."
}

# ---------- Smoke run ----------
run_once_now() {
  if [[ ! -f "${PROC}" ]]; then
    echo "!! processor.py not found at ${PROC}"
    exit 1
  fi
  echo "==> Running processor.py once to verify..."
  MODE="${MODE}" "${PY}" "${PROC}" || true
  echo "==> One-time run complete (logs in ${LOG_DIR})."
}

main() {
  # 9P now + persistent
  mount9p_now
  install_mount9p_daemon

  # Tooling & Python
  ensure_python
  setup_venv

  # Browsers + drivers (based on MODE)
  install_browsers

  # Launches & power settings
  make_runner
  install_launchagent
  disable_sleep_pmset
  install_caffeinate_agent

  # Test run
  run_once_now

  echo "==> Done. ${APP_ID} is configured to run on login and KeepAlive."
  echo "==> 9P 'shared' will auto-mount at boot via ${MOUNT9P_ID}."
}

main "$@"
