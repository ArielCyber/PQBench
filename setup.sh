#!/bin/bash

set -e
echo "Starting macOS PQC setup..."

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

# Define Chrome versions
CHROME_VERSIONS=("128.0.6613.137" "138.0.7204.184")
CHROME_NAMES=("Google Chrome 128.app" "Google Chrome 138.app")
CHROME_URLS=(
  "https://storage.googleapis.com/chrome-for-testing-public/128.0.6613.137/${CHROME_ARCH}/chrome-${CHROME_ARCH}.zip"
  "https://storage.googleapis.com/chrome-for-testing-public/138.0.7204.184/${CHROME_ARCH}/chrome-${CHROME_ARCH}.zip"
)

# Step 4: Install required Chrome versions
for i in "${!CHROME_VERSIONS[@]}"; do
  VERSION="${CHROME_VERSIONS[$i]}"
  APP_NAME="${CHROME_NAMES[$i]}"
  URL="${CHROME_URLS[$i]}"

  if [ ! -d "/Applications/$APP_NAME" ]; then
    echo "Chrome $VERSION not found. Downloading..."
    ZIP_NAME="chrome-$VERSION.zip"

    # Download and unzip
    curl -L -o "$ZIP_NAME" "$URL"
    unzip -q "$ZIP_NAME"

    # Rename the app folder
    echo "Renaming app and moving to /Applications..."
    mv "chrome-${CHROME_ARCH}/Google Chrome for Testing.app" "chrome-${CHROME_ARCH}/$APP_NAME"
    sudo mv "chrome-${CHROME_ARCH}/$APP_NAME" "/Applications/$APP_NAME"

    # Cleanup
    rm -rf "$ZIP_NAME" "chrome-${CHROME_ARCH}"
    echo "Installed Chrome $VERSION as $APP_NAME"
  else
    echo "Chrome $VERSION already installed as $APP_NAME."
  fi
done

# Step 5: Install ChromeDrivers for all Chrome versions defined
for VERSION in "${CHROME_VERSIONS[@]}"; do
  DRIVER_VERSION="${VERSION}.0.7204.184"
  DRIVER_PATH="/usr/local/bin/chromedriver-${VERSION}"

  if [[ ! -f "$DRIVER_PATH" ]]; then
    echo "Installing ChromeDriver $DRIVER_VERSION for Chrome $VERSION..."

    # Determine architecture based on platform
    if [[ $(uname -m) == "arm64" ]]; then
      ARCH="mac-arm64"
    else
      ARCH="mac-x64"
    fi

    ZIP_NAME="chromedriver-${ARCH}.zip"
    DOWNLOAD_URL="https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/${DRIVER_VERSION}/${ARCH}/${ZIP_NAME}"

    # Download with headers to mimic browser
    curl -L -o "${ZIP_NAME}" "${DOWNLOAD_URL}" \
      -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36" \
      -H "Accept: */*" \
      -H "Connection: keep-alive"

    if [[ $? -ne 0 ]]; then
      echo "❌ Failed to download ChromeDriver for version $VERSION. Skipping..."
      continue
    fi

    # Unzip
    unzip -q "${ZIP_NAME}"

    # Move binary from nested folder (new Google format)
    if [[ -f chromedriver-${ARCH}/chromedriver ]]; then
      sudo mv "chromedriver-${ARCH}/chromedriver" "$DRIVER_PATH"
      sudo chmod +x "$DRIVER_PATH"
      rm -rf "chromedriver-${ARCH}"
    else
      echo "⚠️ chromedriver binary not found after unzip for version $VERSION"
      continue
    fi

    # Cleanup ZIP
    rm -f "${ZIP_NAME}"
  fi
done





# Define Firefox versions
FIREFOX_VERSIONS=("130.0.1" "142.0.1")
FIREFOX_NAMES=("Firefox 130.app" "Firefox 142.app")

# Step 6: Install required Firefox versions
for i in "${!FIREFOX_VERSIONS[@]}"; do
  VERSION="${FIREFOX_VERSIONS[$i]}"
  APP_NAME="${FIREFOX_NAMES[$i]}"
  if [ ! -d "/Applications/$APP_NAME" ]; then
    echo "Firefox $VERSION not found. Downloading..."
    DMG_NAME="firefox-$VERSION.dmg"
    curl -L -o "$DMG_NAME" "https://download-installer.cdn.mozilla.net/pub/firefox/releases/$VERSION/$FIREFOX_ARCH/en-US/Firefox%20$VERSION.dmg"
    hdiutil attach "$DMG_NAME"
    cp -r /Volumes/Firefox/Firefox.app "/Applications/$APP_NAME"
    hdiutil detach /Volumes/Firefox
    rm "$DMG_NAME"
    echo "Installed Firefox $VERSION as $APP_NAME"
  else
    echo "Firefox $VERSION already installed."
  fi
done

# Step 7: Install Geckodriver if not present
GECKODRIVER_VERSION="v0.34.0"
echo "Checking for geckodriver..."
if ! command -v geckodriver &> /dev/null; then
  echo "Installing geckodriver $GECKODRIVER_VERSION..."
  curl -L -o geckodriver.tar.gz "https://github.com/mozilla/geckodriver/releases/download/$GECKODRIVER_VERSION/geckodriver-$GECKODRIVER_VERSION-$FIREFOX_ARCH.tar.gz"
  tar -xvzf geckodriver.tar.gz
  sudo mv geckodriver /usr/local/bin/geckodriver
  sudo chmod +x /usr/local/bin/geckodriver
  rm geckodriver.tar.gz
  echo "Geckodriver installed."
else
  echo "Geckodriver already installed."
fi

echo "macOS PQC setup complete."
