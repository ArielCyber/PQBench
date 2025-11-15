import logging
import re
import time
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver import ActionChains

# Regex from the old code for parsing class[index] selectors
CLASS_INDEX_RE = re.compile(r'^(?P<class>[A-Za-z0-9_\-:.]+)\[(?P<idx>\d+)\]$')


class PageInteractor:
    """
    Handles all interactions with a webpage (clicks, scrolls, iframes).
    Its single responsibility is to be an "action toolkit".
    """

    def __init__(self, driver: WebDriver):
        self.driver = driver
        self.logger = logging.getLogger(self.__class__.__name__)

    def perform_initial_page_load_actions(self):
        """Actions to run immediately after page load."""
        # SSL Bypass
        try:
            ActionChains(self.driver).send_keys("thisisunsafe").perform()
            self.logger.info("Sent 'thisisunsafe' for potential SSL bypass.")
        except Exception:
            pass  # Ignore if it fails

        time.sleep(2)

        # Scrolling
        self.logger.info("Scrolling page to trigger lazy-load.")
        self.driver.execute_script(
            "(document.scrollingElement || document.documentElement).scrollTo({top: 99999, behavior: 'smooth'});")
        time.sleep(1)
        self.driver.execute_script(
            "(document.scrollingElement || document.documentElement).scrollTo({ top: 0, behavior: 'smooth' });")
        time.sleep(2)

    def click_button_advanced(self, selector_string: str) -> bool:
        """Advanced click logic."""
        if not selector_string:
            self.logger.info("No selector string provided to click_button_advanced.")
            return True

        self.logger.info(f"Attempting advanced click with: '{selector_string}'")
        groups = [name.strip() for name in selector_string.split(",") if name.strip()]
        name_done = [False for _ in range(len(groups))]

        for i, group in enumerate(groups):
            for original_name in [a.strip() for a in group.split("|") if a.strip()]:
                name, idx = original_name, 0
                m = CLASS_INDEX_RE.match(original_name)
                if m:
                    name, idx = m.group("class"), int(m.group("idx"))

                try:
                    elements = []
                    if name.startswith(":"):
                        xpath = f"//*[contains(normalize-space(string()),'{name[1:]}') or contains(@aria-label, '{name[1:]}')]"
                        elements = self.driver.find_elements(By.XPATH, xpath)
                    else:
                        elements = self.driver.find_elements(By.CLASS_NAME, name)
                        if not elements:
                            elements = self.driver.find_elements(By.ID, name)

                    if not elements: continue
                    if not (0 <= idx < len(elements)):
                        self.logger.warning(f"Selector '{name}' index {idx} out of range.")
                        continue

                    element_to_click = elements[idx]
                    try:
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element_to_click)
                        time.sleep(0.5)
                        element_to_click.click()
                        self.logger.info(f"[V] Clicked '{original_name}' (Group {i + 1})")
                        name_done[i] = True
                        time.sleep(2)
                        break
                    except Exception as e:
                        self.logger.warning(f"Found '{original_name}' but failed to click: {e}")
                except Exception as e:
                    self.logger.error(f"Error finding selector '{name}': {e}")

            if not name_done[i]:
                self.logger.warning(f"Failed to click any options in group: '{group}'")

        return all(name_done)

    def click_shadow_button_advanced(self, shadow_selector: str):
        """Searches all shadow DOMs for the given selector."""
        if not shadow_selector:
            self.logger.debug("No shadow_button selector provided, skipping.")
            return

        self.logger.info(f"Attempting to find shadow button: '{shadow_selector}'")
        try:
            clicked = self.driver.execute_script("""
                const selector = arguments[0];
                const shadow_hosts = Array.from(document.querySelectorAll("*"))
                                          .filter(el => el.shadowRoot !== null);
                for (const host of shadow_hosts) {
                    const root = host.shadowRoot;
                    if (!root) continue;
                    const btn = root.querySelector(selector);
                    if (btn) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            """, shadow_selector)

            if clicked:
                self.logger.info(f"[V] Clicked shadow button '{shadow_selector}'")
            else:
                self.logger.warning(f"[X] Shadow button '{shadow_selector}' not found.")
        except Exception as e:
            self.logger.error(f"Error while searching shadow DOM: {e}")

    def try_iframes(self, play_button_selector: str):
        """Searches iframes for the play button."""
        self.logger.info("Searching inside iframes...")
        try:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            if not iframes:
                self.logger.info("No iframes found.")
                return

            for index, iframe in enumerate(iframes):
                if self.handle_iframe(iframe, play_button_selector):
                    self.logger.info(f"Successfully clicked in iframe #{index}.")
                    self.click_out_of_iframe()
                    return
                else:
                    self.click_out_of_iframe()
        except Exception as e:
            self.logger.error(f"Error searching iframes: {e}")
            self.click_out_of_iframe()

    def handle_iframe(self, iframe_element: WebElement, play_button_selector: str) -> bool:
        """Switches to iframe and tries to click play button."""
        try:
            self.driver.switch_to.frame(iframe_element)
            self.logger.info("Switched to iframe.")
            if self.click_button_advanced(play_button_selector):
                return True
            self.logger.info("Button not found in this iframe.")
            return False
        except Exception as e:
            self.logger.error(f"Error handling iframe: {e}")
            return False

    def click_out_of_iframe(self):
        try:
            self.driver.switch_to.default_content()
        except Exception as e:
            self.logger.error(f"Could not switch to default content: {e}")