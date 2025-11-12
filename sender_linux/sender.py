import logging
import os
import re
import time
from abc import abstractmethod
from typing import Dict, Optional

import requests
from selenium import webdriver
from selenium.common import WebDriverException
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.wait import WebDriverWait
from undetected_chromedriver import WebElement
from webdriver_manager.firefox import GeckoDriverManager

from exceptions import *

CLASS_INDEX_RE = re.compile(r'^(?P<class>[A-Za-z0-9_\-:.]+)\[(?P<idx>\d+)\]$')


class Sender:

    def __init__(self, browser: str, algo: int, sessions: int, website_url: str,
                 attribute: str, wait_time=10):

        self.browser = browser
        self.algo = algo
        self.sessions = sessions
        self.website_url = website_url
        self.attribute = attribute
        self.wait_time = wait_time
        self.driver: Optional[webdriver.Remote] = None  # Type hint for clarity

        # These will be populated by get_button_values()
        self.play_button: Optional[str] = None
        self.shadow_button: Optional[str] = None
        self.skip_class: Optional[str] = None  # Assuming get_button_values will return this too

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"Initialized for URL: {self.website_url}, Attribute: {self.attribute}")

    def click_button_advanced(self, selector_string: str, tries=0) -> bool:
        """
        Handles comma-separated, pipe-separated, index, and text selectors.
        """
        if not selector_string:
            self.logger.info("No selector string provided.")
            return True  # No button, so "success"

        self.logger.info(f"Attempting advanced click with: '{selector_string}'")

        # Split into sequential groups (e.g., "accept_cookies, play_video")
        groups = [name.strip() for name in selector_string.split(",") if name.strip()]
        name_done = [False for _ in range(len(groups))]

        for i, group in enumerate(groups):
            # Split into fallback options (e.g., "play-btn|play-button-class")
            for original_name in [a.strip() for a in group.split("|") if a.strip()]:
                name = original_name
                idx = 0

                # Check for index syntax (e.g., "my-class[1]")
                m = CLASS_INDEX_RE.match(original_name)
                if m:
                    name = m.group("class")
                    idx = int(m.group("idx"))

                try:
                    elements = []
                    if name.startswith(":"):
                        # Find by text (e.g., ":Play")
                        xpath = f"//*[contains(normalize-space(string()),'{name[1:]}') or contains(@aria-label, '{name[1:]}')]"
                        elements = self.driver.find_elements(By.XPATH, xpath)
                    else:
                        # Try by class, then ID
                        elements = self.driver.find_elements(By.CLASS_NAME, name)
                        if not elements:
                            elements = self.driver.find_elements(By.ID, name)

                    if not elements:
                        self.logger.debug(f"Selector '{name}' not found.")
                        continue  # Try next fallback

                    if idx < 0 or idx >= len(elements):
                        self.logger.warning(
                            f"Selector '{name}' has {len(elements)} elements; index {idx} is out of range")
                        continue

                    # We have a valid element
                    element_to_click = elements[idx]

                    try:
                        # Scroll to element and click
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element_to_click)
                        time.sleep(0.5)
                        element_to_click.click()
                        self.logger.info(f"[V] Clicked '{original_name}' (Group {i + 1})")
                        name_done[i] = True
                        time.sleep(2)  # Wait after click
                        break  # Success, move to next group
                    except Exception as e:
                        self.logger.warning(f"Found '{original_name}' but failed to click: {e}")
                        # Try next element if this one failed
                        continue

                except Exception as e:
                    self.logger.error(f"Error finding selector '{name}': {e}")
                    continue

            if name_done[i]:
                continue  # This group is done, move to the next
            else:
                self.logger.warning(f"Failed to click any options in group: '{group}'")
                # If one group fails, do we stop? For now, we'll continue.
                # You could change this to `return False` if one failure should stop all.

        # Return True if all groups were successfully clicked
        return all(name_done)

    def click_shadow_button_advanced(self):
        """
        Searches all shadow DOMs for the `self.shadow_button` selector.
        """
        if not self.shadow_button:
            self.logger.debug("No shadow_button selector provided, skipping.")
            return

        self.logger.info(f"Attempting to find shadow button: '{self.shadow_button}'")
        try:
            # This JS finds all shadow hosts, then searches inside each shadow root
            # for the selector.
            clicked = self.driver.execute_script("""
                const selector = arguments[0];
                const shadow_hosts = Array.from(document.querySelectorAll("*"))
                                          .filter(el => el.shadowRoot !== null);

                for (const host of shadow_hosts) {
                    const root = host.shadowRoot;
                    if (!root) continue;

                    const btn = root.querySelector(selector);
                    if (btn) {
                        btn.focus();
                        btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                        btn.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                        btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                        return true; // Clicked
                    }
                }
                return false; // Not found
            """, self.shadow_button)

            if clicked:
                self.logger.info(f"[V] Clicked shadow button '{self.shadow_button}'")
            else:
                self.logger.warning(f"[X] Shadow button '{self.shadow_button}' not found in any shadow DOM.")
        except Exception as e:
            self.logger.error(f"Error while searching shadow DOM: {e}")

        self.logger.info(f"Attempting to click shadow button: {self.shadow_button}")
        # This assumes shadow_button is a CSS selector for the button *inside* the shadow DOM
        # and play_button is the selector for the *host* of that shadow DOM.
        # You may need to adjust this logic.
        if not self.click_button(selector=self.shadow_button, inside_shadow_dom=True,
                                 shadow_host_selector=self.play_button):
            self.logger.warning(f"Shadow button '{self.shadow_button}' not found.")

    def try_iframes(self):
        self.logger.info("Searching inside iframes...")
        try:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            if not iframes:
                self.logger.info("No iframes found.")
                return

            for index, iframe in enumerate(iframes):
                if self.handle_iframe(iframe):
                    self.logger.info(f"Successfully clicked in iframe #{index}.")
                    self.click_out_of_iframe()
                    return  # Stop after first success
                else:
                    self.click_out_of_iframe()
        except Exception as e:
            self.logger.error(f"Error searching iframes: {e}")
            self.click_out_of_iframe()

    def click_out_of_iframe(self):
        try:
            self.driver.switch_to.default_content()
        except Exception as e:
            self.logger.error(f"Could not switch to default content: {e}")

    def handle_iframe(self, iframe_element: WebElement) -> bool:
        """Switches to iframe and tries to click play button."""
        try:
            self.driver.switch_to.frame(iframe_element)
            self.logger.info("Switched to iframe.")

            # Try to click the play button INSIDE the iframe
            if self.click_button_advanced(self.play_button):
                return True

            # Try to click the shadow button INSIDE the iframe
            self.click_shadow_button_advanced()
            # (We might not know if this was a "success" so we don't return,
            # unless the shadow button is the main action)

            self.logger.info("Button not found in this iframe.")
            return False
        except Exception as e:
            self.logger.error(f"Error handling iframe: {e}")
            return False

    def setup_driver(self):
        """
        The decision-making for which browser should be opened

        browser : str
            'chrome' or 'firefox'.
        algo : int
            0 for non PQC
            1 for Kyber
            2 for MLKEM

        Returns
        -------
        WebDriver
            An instance of Chrome or Firefox WebDriver.

        Raises
        ------
        BrowserLaunchError
            If the driver fails to start or browser is not installed.
        """

        try:
            if self.browser.lower() == 'chrome':
                self.driver = self.open_chrome()
            else:
                self.driver = self.open_firefox()
        except WebDriverException as e:
            raise e

    def open_firefox(self):
        """
            Launch a Selenium WebDriver for Firefox with a given algorithm.
            """
        logging.debug("Trying to open Firefox")

        firefox_opts = webdriver.FirefoxOptions()

        # Headless mode
        firefox_opts.add_argument("-headless")

        if self.algo == 0:
            firefox_opts.set_preference('network.http.http3.enable_kyber', False)
            firefox_opts.set_preference('security.tls.enable_kyber', False)
            logging.debug("Set non PQC preferences")
        if self.algo == 1 or self.algo == 2:  # Enable Kyber or MLKEM (Same flags)
            firefox_opts.set_preference("security.tls.enable_kyber", True)
            firefox_opts.set_preference("network.http.http3.enabled", True)
            firefox_opts.set_preference("network.http.http3.enable_kyber", True)
            logging.debug("Set PQC on")

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
        if self.algo == 0:
            prefs["browser"]["enabled_labs_experiments"] = [
                "enable-tls13-kyber@2",
                "use-ml-kem@2"]

        elif self.algo == 1:
            prefs["browser"]["enabled_labs_experiments"] = [
                "use-ml-kem@2"]
        elif self.algo == 2:  # ML-KEM
            prefs["browser"]["enabled_labs_experiments"] = [
                "enable-tls13-kyber@2",  # Disabled
                "use-ml-kem@1",  # Enabled
            ]

        chrome_opts.add_experimental_option("localState", prefs)

        try:
            chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/local/bin/chromedriver")
            service = ChromeService(executable_path=chromedriver_path)
            return webdriver.Chrome(options=chrome_opts, service=service)
        except WebDriverException as e:
            logging.critical(e)
            raise BrowserLaunchError("Failed to open Chrome: is Chrome installed and the driver up to date?") from e

    @abstractmethod
    def create_traffic(self):
        logging.warning("start() is not implemented!")
        pass

    def close_driver(self):
        """Closes the browser driver if it's open."""
        if self.driver:
            logging.info("Closing browser driver.")
            self.driver.quit()
            self.driver = None
        else:
            logging.info("No driver to close.")

    def run(self):
        """
        Executes the full traffic generation flow for a single site,
        running for the specified number of sessions.
        """
        self.logger.info(f"--- Starting traffic generation for {self.website_url} ---")
        try:
            # Fetch button config once before starting sessions
            button_data = self.get_button_values()
            if button_data:
                self.play_button = button_data.get("play_button")
                self.shadow_button = button_data.get("shadow_button")
                self.logger.info(f"Got button config: Play='{self.play_button}', Shadow='{self.shadow_button}'")
            else:
                self.logger.warning("Could not fetch button config. Proceeding without.")

            # Loop for each session
            for i in range(self.sessions):
                self.logger.info(f"Starting session {i + 1} of {self.sessions}...")
                try:
                    # Setup Driver
                    self.setup_driver()  # Sets self.driver

                    if self.driver:
                        # Navigate
                        self.logger.info(f"Navigating to {self.website_url}")
                        self.driver.get(self.website_url)

                        # SSL Bypass
                        try:
                            ActionChains(self.driver).send_keys("thisisunsafe").perform()
                            self.logger.info("Sent 'thisisunsafe' for potential SSL bypass.")
                        except Exception:
                            pass  # Ignore if it fails

                        time.sleep(2)

                        WebDriverWait(self.driver, self.wait_time).until(
                            lambda d: d.execute_script("return document.readyState") == "complete"
                        )

                        # Interact (Scrolling)
                        self.logger.info("Scrolling page to trigger lazy-load.")
                        self.driver.execute_script(
                            "(document.scrollingElement || document.documentElement).scrollTo({top: 99999, behavior: 'smooth'});")
                        time.sleep(1)
                        self.driver.execute_script(
                            "(document.scrollingElement || document.documentElement).scrollTo({ top: 0, behavior: 'smooth' });")
                        time.sleep(2)

                        # Run Specific Logic (from child class)
                        self.create_traffic()
                    else:
                        self.logger.error("Driver not available for this session.")

                except Exception as e:
                    self.logger.error(f"Error during session {i + 1}: {e}", exc_info=True)
                finally:
                    # Cleanup
                    self.close_driver()
                    self.logger.info(f"Finished session {i + 1}.")

        except Exception as e:
            self.logger.error(f"Critical error in main run loop: {e}", exc_info=True)
        finally:
            self.logger.info(f"--- Finished all traffic for {self.website_url} ---")

    def get_button_values(self, base_url: str = "http://domain_maintainer:5010") -> Optional[
        Dict[str, str]]:
        """
        Fetches button values for a given domain and attribute by making a GET request
        to the domain_maintainer service.

        Args:
            website_url: The domain to search for (e.g., "youtube.com").
            attribute: The attribute (worksheet) to search within (e.g., "video").
            base_url: The base URL of the domain_maintainer service.

        Returns:
            A dictionary containing the values from the first and second columns
            (e.g., {"value_col_1": "...", "value_col_2": "..."}) if found.
            Returns None if the domain is not found or if an error occurs.
        """
        if not self.website_url or not self.attribute:
            logging.error("Domain and attribute cannot be empty.")
            return None

        endpoint = f"{base_url}/get_button_by_domain/"
        params = {"domain": self.website_url, "attribute": self.attribute}

        try:
            response = requests.get(endpoint, params=params)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"Info: Domain '{self.website_url}' not found in attribute '{self.attribute}'.")
            else:
                print(f"HTTP Error fetching button values: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Error fetching button values: {e}")
            return None
        except ValueError:
            print("Error: Failed to decode JSON response from the server.")
            return None
