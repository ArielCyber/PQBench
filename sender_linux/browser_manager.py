import logging
import os

from selenium import webdriver
from selenium.common import WebDriverException
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from undetected_chromedriver import WebElement
from webdriver_manager.firefox import GeckoDriverManager
from algo_strategies import get_algo_strategy


class BrowserLaunchError(RuntimeError):
    """Raised when we fail to launch the requested browser."""
    pass


class BrowserManager:
    """
    Handles the creation and configuration of WebDriver instances.
    Its single responsibility is browser lifecycle.
    """

    def __init__(self, browser: str, algo: int):
        self.browser = browser
        self.algo = algo
        self.algo_strategy = get_algo_strategy(algo)
        self.logger = logging.getLogger(self.__class__.__name__)

    def setup_driver(self) -> webdriver.Remote:
        """Sets up and returns a configured driver instance."""
        self.logger.info(f"Setting up {self.browser} driver...")
        try:
            if self.browser.lower() == 'chrome':
                driver = self.open_chrome()
            else:
                driver = self.open_firefox()

            driver.set_page_load_timeout(180)
            driver.set_script_timeout(180)
            self.logger.info(f"Successfully opened {self.browser}.")

            # Set Spoofed Geolocation
            try:
                driver.execute_cdp_cmd("Emulation.setGeolocationOverride",
                                       {"latitude": 32.0853, "longitude": 34.7818, "accuracy": 50})
                self.logger.info("Set spoofed geolocation.")
            except Exception:
                self.logger.warning("Could not set spoofed geolocation (may not be supported).")

            return driver

        except WebDriverException as e:
            self.logger.critical(f"Failed to setup driver: {e}")
            raise BrowserLaunchError(f"Failed to open {self.browser}: is it installed/driver up to date?") from e
        except Exception as e:
            self.logger.critical(f"An unexpected error occurred during driver setup: {e}")
            raise

    def open_firefox(self):
        """
            Launch a Selenium WebDriver for Firefox with a given algorithm.
            """
        logging.debug("Trying to open Firefox")

        firefox_opts = webdriver.FirefoxOptions()

        # Headless mode
        firefox_opts.add_argument("-headless")

        self.algo_strategy.apply_firefox_options(firefox_opts)

        try:
            gecko_path = GeckoDriverManager().install()
            logging.debug("Installed GeckoDriverManager successfully!")
            return webdriver.Firefox(service=FirefoxService(gecko_path), options=firefox_opts, )
        except WebDriverException as e:
            logging.critical(e)
            raise BrowserLaunchError("Failed to open Firefox: is Firefox installed and the driver up to date?") from e

    def open_chrome(self):
        """
        Launch a Selenium WebDriver for Chrome with a given algorithm.
        """
        chrome_opts = webdriver.ChromeOptions()

        # Headless Chrome
        chrome_opts.add_argument("--no-sandbox")  # containers often need this
        chrome_opts.add_argument("--headless=new")
        chrome_opts.add_argument("--disable-gpu")  # Windows workaround
        chrome_opts.add_argument("--disable-dev-shm-usage")
        chrome_opts.add_argument("--remote-debugging-port=0")  # avoids DevTools port collision

        prefs = {"browser": {"enabled_labs_experiments": []}}

        # ----- Chrome PQC experiments (via Local State "enabled_labs_experiments") -----
        self.algo_strategy.apply_chrome_options(chrome_opts, prefs)

        chrome_opts.add_experimental_option("localState", prefs)

        try:
            chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/local/bin/chromedriver")
            service = ChromeService(executable_path=chromedriver_path)
            return webdriver.Chrome(options=chrome_opts, service=service)
        except WebDriverException as e:
            logging.critical(e)
            raise BrowserLaunchError("Failed to open Chrome: is Chrome installed and the driver up to date?") from e
