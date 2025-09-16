#!/bin/bash

set -e
MODE=${MODE:-nonpq}
echo "Setup started with mode: $MODE"

# detect arch
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
  CHROME_ARCH="mac-arm64"
  FIREFOX_ARCH="macos-aarch64"
else
  CHROME_ARCH="mac-x64"
  FIREFOX_ARCH="macos"
fi

# Python venv
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
source venv/bin/activate
python3 -m pip install --upgrade pip --break-system-packages
python3 -m pip install -r requirements.txt --break-system-packages

# Determine versions by mode
if [[ "$MODE" == "kyber" ]]; then
  CHROME_VERSION="128.0.6613.137"
  FIREFOX_VERSION="130.0.1"
  FIREFOX_APP_NAME="Firefox 130.app"
  CHROME_APP_NAME="Google Chrome 128.app"
  FIREFOX_URL="https://download.mozilla.org/?product=firefox-130.0.1-ssl&os=osx&lang=en-US"
elif [[ "$MODE" == "mlkem" ]]; then
  CHROME_VERSION="138.0.7204.183"
  FIREFOX_VERSION="142.0.1"
  FIREFOX_APP_NAME="Firefox 142.app"
  CHROME_APP_NAME="Google Chrome 138.app"
  FIREFOX_URL="https://download.mozilla.org/?product=firefox-142.0.1-ssl&os=osx&lang=en-US"
else
  echo "MODE is nonpq. Skipping browser version setup."
  CHROME_VERSION=""
  FIREFOX_VERSION=""
fi

# --- Install Chrome ---
if [[ -n "$CHROME_VERSION" ]]; then
  CHROME_PATH="/Applications/$CHROME_APP_NAME"
  if [ ! -d "$CHROME_PATH" ]; then
    echo "Installing Chrome version $CHROME_VERSION..."
    URL="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/${CHROME_ARCH}/chrome-${CHROME_ARCH}.zip"
    curl -L -o chrome.zip "$URL"
    unzip -q chrome.zip -d chrome_temp

    # Find and rename
    CHROME_APP_PATH=$(find chrome_temp -type d -name "Google Chrome for Testing.app" | head -n 1)
    if [[ -z "$CHROME_APP_PATH" ]]; then
      echo "Error: Google Chrome for Testing.app not found!"
      exit 1
    fi

    mv "$CHROME_APP_PATH" "$CHROME_APP_NAME"
    sudo mv "$CHROME_APP_NAME" "/Applications/$CHROME_APP_NAME"
    rm -rf chrome.zip chrome_temp
  else
    echo "Chrome version $CHROME_VERSION already installed."
  fi

  # ChromeDriver
  DRIVER_PATH="/usr/local/bin/chromedriver-${CHROME_VERSION}"
  SYMLINK_PATH="/usr/local/bin/chromedriver"
  if [[ ! -f "$DRIVER_PATH" ]]; then
    echo "Installing ChromeDriver version $CHROME_VERSION..."
    ZIP_NAME="chromedriver-${CHROME_ARCH}.zip"
    DL_URL="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/${CHROME_ARCH}/chromedriver-${CHROME_ARCH}.zip"
    curl -L -o "$ZIP_NAME" "$DL_URL"
    unzip -q "$ZIP_NAME" -d chromedriver_temp
    CHROMEDRIVER_BINARY=$(find chromedriver_temp -type f -name chromedriver)

    if [[ -z "$CHROMEDRIVER_BINARY" ]]; then
      echo "Error: chromedriver binary not found!"
      exit 1
    fi

    sudo mv "$CHROMEDRIVER_BINARY" "$DRIVER_PATH"
    sudo chmod +x "$DRIVER_PATH"
    rm -rf "$ZIP_NAME" chromedriver_temp
  else
    echo "ChromeDriver version $CHROME_VERSION already installed."
  fi

  # Link to chromedriver
  if [[ ! -L "$SYMLINK_PATH" || "$(readlink $SYMLINK_PATH)" != "$DRIVER_PATH" ]]; then
    echo "Linking $SYMLINK_PATH to $DRIVER_PATH..."
    sudo ln -sf "$DRIVER_PATH" "$SYMLINK_PATH"
  else
    echo "Symlink for ChromeDriver already correct."
  fi
fi

# --- Install Firefox ---
if [[ -n "$FIREFOX_VERSION" ]]; then
  FIREFOX_PATH="/Applications/$FIREFOX_APP_NAME"
  if [ ! -d "$FIREFOX_PATH" ]; then
    echo "Downloading Firefox $FIREFOX_VERSION..."
    curl -L -o firefox.dmg "$FIREFOX_URL"
    echo "Mounting Firefox..."
    hdiutil attach firefox.dmg -nobrowse
    echo "Copying Firefox to /Applications..."
    cp -r /Volumes/Firefox/Firefox.app "$FIREFOX_PATH"
    echo "Unmounting Firefox..."
    hdiutil detach /Volumes/Firefox
    echo "Cleaning up..."
    rm -f firefox.dmg
  else
    echo "Firefox $FIREFOX_VERSION already installed."
  fi

  # Geckodriver
  GECKODRIVER_VERSION="v0.34.0"
  GECKO_TARGET="/usr/local/bin/geckodriver"
  if ! command -v geckodriver >/dev/null || [[ "$($GECKO_TARGET --version 2>/dev/null)" != *"$GECKODRIVER_VERSION"* ]]; then
    echo "Installing Geckodriver $GECKODRIVER_VERSION..."
    curl -L -o geckodriver.tar.gz "https://github.com/mozilla/geckodriver/releases/download/$GECKODRIVER_VERSION/geckodriver-$GECKODRIVER_VERSION-$FIREFOX_ARCH.tar.gz"
    tar -xvzf geckodriver.tar.gz
    sudo mv geckodriver "$GECKO_TARGET"
    sudo chmod +x "$GECKO_TARGET"
    rm -f geckodriver.tar.gz
  else
    echo "Geckodriver $GECKODRIVER_VERSION already installed."
  fi
fi

# --- Disable Password & Lock for Automation ---
echo "Disabling sudo password prompts..."
echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/nopasswd

echo "Removing user password..."
sudo dscl . -passwd /Users/$USER ""

echo "Enabling auto login..."
sudo defaults write /Library/Preferences/com.apple.loginwindow autoLoginUser "$USER"

echo "Disabling screen lock password..."
REAL_USER=$(logname)
sudo -u "$REAL_USER" defaults write com.apple.screensaver askForPassword -int 0
sudo -u "$REAL_USER" defaults write com.apple.screensaver askForPasswordDelay -int 0

echo "Disabling FileVault (if enabled)..."
sudo fdesetup disable

echo "Setup complete for mode: $MODE"


