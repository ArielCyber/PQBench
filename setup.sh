#!/bin/bash

set -e
echo "Starting macOS PQC setup..."

# Detect architecture (arm64 = Apple Silicon, x86_64 = Intel)
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
  CHROME_ARCH="mac-arm64"
  FIREFOX_ARCH="macos-aarch64"
elif [[ "$ARCH" == "x86_64" ]]; then
  CHROME_ARCH="mac-x64"
  FIREFOX_ARCH="macos"
else
  echo "Unsupported architecture: $ARCH"
  exit 1
fi
echo "Detected architecture: $ARCH"

# Step 1: Create Python virtual environment
echo "Creating Python virtual environment..."
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi

# Step 2: Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Step 3: Install Python dependencies
echo "Installing Python requirements..."
pip install --upgrade pip
pip install -r requirements.txt

# Step 4: Check for Chrome installation
echo "Checking for Google Chrome..."
if [ ! -d "/Applications/Google Chrome.app" ]; then
  echo "Google Chrome is not installed. Please install it manually."
else
  echo "Google Chrome is installed."
fi

# Step 5: Install ChromeDriver if needed
INSTALLED_CHROMEDRIVER=$(chromedriver --version 2>/dev/null || true)
if [[ "$INSTALLED_CHROMEDRIVER" != *"138."* ]]; then
  echo "Installing ChromeDriver for Chrome 138..."
  curl -L -o chromedriver.zip "https://storage.googleapis.com/chrome-for-testing-public/138.0.7204.0/$CHROME_ARCH/chromedriver-$CHROME_ARCH.zip"
  unzip chromedriver.zip
  sudo mv chromedriver-$CHROME_ARCH/chromedriver /usr/local/bin/chromedriver
  sudo chmod +x /usr/local/bin/chromedriver
  rm -rf chromedriver.zip chromedriver-$CHROME_ARCH
  echo "ChromeDriver installed."
else
  echo "ChromeDriver already installed and compatible."
fi

# Step 6: Check for Firefox installation
echo "Checking for Firefox..."
if [ ! -d "/Applications/Firefox.app" ]; then
  echo "Firefox not found. Installing Firefox 142.0.1..."
  curl -L -o firefox.dmg "https://download-installer.cdn.mozilla.net/pub/firefox/releases/142.0.1/$FIREFOX_ARCH/en-US/Firefox%20142.0.1.dmg"
  hdiutil attach firefox.dmg
  cp -r /Volumes/Firefox/Firefox.app /Applications/
  hdiutil detach /Volumes/Firefox
  rm firefox.dmg
  echo "Firefox installed."
else
  echo "Firefox is installed."
fi

# Step 7: Install Geckodriver if not present
echo "Checking for geckodriver..."
if ! command -v geckodriver &> /dev/null; then
  echo "Installing geckodriver v0.34.0..."
  curl -L -o geckodriver.tar.gz "https://github.com/mozilla/geckodriver/releases/download/v0.34.0/geckodriver-v0.34.0-$FIREFOX_ARCH.tar.gz"
  tar -xvzf geckodriver.tar.gz
  sudo mv geckodriver /usr/local/bin/geckodriver
  sudo chmod +x /usr/local/bin/geckodriver
  rm geckodriver.tar.gz
  echo "Geckodriver installed."
else
  echo "Geckodriver already installed."
fi

echo "macOS PQC setup complete."
