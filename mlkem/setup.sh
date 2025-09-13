#!/bin/bash

set -e
echo "Starting Kyber setup..."

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
pip install --upgrade pip
pip install -r requirements.txt

# Install Chrome 138
CHROME_VERSION="138.0.7204.183"
APP_NAME="Google Chrome 138.app"
URL="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/${CHROME_ARCH}/chrome-${CHROME_ARCH}.zip"

if [ ! -d "/Applications/$APP_NAME" ]; then
  echo "Installing Chrome version $CHROME_VERSION..."
  curl -L -o chrome.zip "$URL"
  unzip -q chrome.zip
  mv "chrome-${CHROME_ARCH}/Google Chrome for Testing.app" "chrome-${CHROME_ARCH}/$APP_NAME"
  sudo mv "chrome-${CHROME_ARCH}/$APP_NAME" "/Applications/$APP_NAME"
  rm -rf chrome.zip "chrome-${CHROME_ARCH}"
else
  echo "Chrome version $CHROME_VERSION already installed."
fi

# ChromeDriver 138
DRIVER_PATH="/usr/local/bin/chromedriver-${CHROME_VERSION}"
SYMLINK_PATH="/usr/local/bin/chromedriver"
if [[ ! -f "$DRIVER_PATH" ]]; then
  echo "Installing ChromeDriver version $CHROME_VERSION..."
  ZIP_NAME="chromedriver-${CHROME_ARCH}.zip"
  DL_URL="https://repo.huaweicloud.com/chromedriver/${CHROME_VERSION}/${ZIP_NAME}"
  curl -L -A "Mozilla/5.0" -o "$ZIP_NAME" "$DL_URL"
  unzip -q "$ZIP_NAME"
  sudo mv chromedriver "$DRIVER_PATH"
  sudo chmod +x "$DRIVER_PATH"
  rm "$ZIP_NAME"
else
  echo "ChromeDriver version $CHROME_VERSION already installed."
fi

# Create or update symlink to match processor.py default path
if [[ ! -L "$SYMLINK_PATH" || "$(readlink $SYMLINK_PATH)" != "$DRIVER_PATH" ]]; then
  echo "Linking $SYMLINK_PATH to $DRIVER_PATH..."
  sudo ln -sf "$DRIVER_PATH" "$SYMLINK_PATH"
else
  echo "Symlink for ChromeDriver already correct."
fi

# Install Firefox 142
FIREFOX_VERSION="142.0.1"
FIREFOX_APP_NAME="Firefox 142.app"
FIREFOX_URL="https://ftp.mozilla.org/pub/firefox/releases/${FIREFOX_VERSION}/mac/${CHROME_ARCH}/en-US/Firefox%20${FIREFOX_VERSION}.dmg"

if [ ! -d "/Applications/$FIREFOX_APP_NAME" ]; then
  echo "Installing Firefox $FIREFOX_VERSION..."
  curl -L -o firefox.dmg "$FIREFOX_URL"
  hdiutil attach firefox.dmg
  cp -r "/Volumes/Firefox/Firefox.app" "$FIREFOX_APP_NAME"
  hdiutil detach "/Volumes/Firefox"
  sudo mv "$FIREFOX_APP_NAME" "/Applications/"
  rm firefox.dmg
else
  echo "Firefox $FIREFOX_VERSION already installed."
fi

# Geckodriver
GECKO_TARGET="/usr/local/bin/geckodriver"
GECKODRIVER_VERSION="v0.34.0"

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

echo "Kyber setup complete."
