import platform
import subprocess
import shutil
from selenium import webdriver
import undetected_chromedriver as uc
from abc import ABC, abstractmethod

# Import strategies (Assuming they are in the same file or imported)
from algo_strategies import *  # Ensure this import matches your file structure


def get_linux_chrome_version():
    """Attempts to get the installed Chromium/Chrome major version on Linux."""
    try:
        # Check for chromium or google-chrome
        executable = shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chromium-browser")
        if not executable:
            return None

        output = subprocess.check_output([executable, "--version"]).decode("utf-8")
        # Output format example: "Chromium 131.0.6778.85 ..."
        parts = output.strip().split()
        for part in parts:
            if part.count('.') >= 1:  # Find the version number
                major = int(part.split('.')[0])
                print(f"[DEBUG] Detected Linux Chrome version: {major}")
                return major
    except Exception as e:
        print(f"[W] Could not detect Linux Chrome version: {e}")
    return None


class BrowserManager:
    def __init__(self, browser_str: str, algo_id: int):
        self.browser_str = browser_str.lower()
        self.algo_strategy = get_algo_strategy(algo_id)
        self.driver = None

    def setup_driver(self) -> webdriver.Remote:
        if "firefox" in self.browser_str:
            self.open_firefox()
        else:
            self.open_chrome()
        return self.driver

    def open_chrome(self):
        options = uc.ChromeOptions()
        prefs = {
            "profile.default_content_setting_values.geolocation": 1,
            "browser": {}
        }

        # Apply Strategy
        #self.algo_strategy.apply_chrome_options(options, prefs)

        options.add_experimental_option("prefs", prefs)

        # --- ESSENTIAL DOCKER FLAGS ---
        options.add_argument("--disable-dev-shm-usage")  # Fixes shared memory crash
        options.add_argument("--no-sandbox")  # Required for root user
        options.add_argument("--headless=new")  # Required if no Xvfb/Display

        # Standard flags
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--allow-insecure-localhost")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-gpu")

        # Determine Version and Binary Path
        kwargs = {"options": options}

        if platform.system() == "Linux":
            # Auto-detect version to prevent mismatch (Driver 142 vs Browser 131)
            major_ver = get_linux_chrome_version()
            if major_ver:
                kwargs["version_main"] = major_ver

            # Explicitly set binary if found, to ensure UC finds the right one
            binary_path = shutil.which("chromium") or shutil.which("google-chrome")
            if binary_path:
                options.binary_location = binary_path

        # Initialize Driver
        print(f"[DEBUG] Starting UC Chrome with args: {kwargs}")
        self.driver = uc.Chrome(**kwargs)

        # Geolocation Override
        try:
            self.driver.execute_cdp_cmd("Emulation.setGeolocationOverride",
                                        {"latitude": 32.0853, "longitude": 34.7818, "accuracy": 50})
        except Exception:
            pass

    def open_firefox(self):
        options = webdriver.FirefoxOptions()
        options.add_argument("--headless")  # Ensure Firefox is also headless
        self.algo_strategy.apply_firefox_options(options)
        self.driver = webdriver.Firefox(options=options)


class BrowserLaunchError(RuntimeError):
    """Raised when we fail to launch the requested browser."""
    pass
