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

    def perform_rtt_scrolling(self, duration: int = 10):
        """Performs continuous up/down scrolling for RTT simulation."""
        self.logger.info(f"Starting RTT scrolling for {duration} seconds...")
        t0 = time.time()
        while time.time() - t0 < duration:
            try:
                self.driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(0.3)
                h = self.driver.execute_script(
                    "return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight) || 2000;")
                self.driver.execute_script("window.scrollTo(0, Math.min(1200, arguments[0]-800));", h)
                time.sleep(0.3)
                self.driver.execute_script("window.scrollBy(0, -300);")
            except Exception as e:
                self.logger.warning(f"Error during RTT scroll: {e}")
            time.sleep(0.8)
        self.logger.info("RTT scrolling complete.")

    def pan_and_zoom_map(self, duration: int = 10):
        """Performs map-like panning and zooming."""
        self.logger.info(f"Starting map pan/zoom for {duration} seconds...")
        try:
            w = self.driver.execute_script("return window.innerWidth;")
            h = self.driver.execute_script("return window.innerHeight;")
            cx, cy = int(w / 2), int(h / 2)

            # Click center to focus
            self.driver.execute_script("""
                const el = document.elementFromPoint(arguments[0], arguments[1]);
                if (el) el.scrollIntoView({behavior: 'instant', block: 'center', inline: 'center'});
            """, cx, cy)
            ActionChains(self.driver).move_by_offset(cx, cy).click().perform()
            ActionChains(self.driver).move_by_offset(-cx, -cy).perform()  # Reset mouse

            t0 = time.time()
            while time.time() - t0 < duration:
                # Pan right
                ActionChains(self.driver).move_by_offset(cx, cy).click_and_hold().move_by_offset(180,
                                                                                                 10).release().perform()
                ActionChains(self.driver).move_by_offset(-cx - 180, -cy - 10).perform()
                time.sleep(0.3)

                # Pan left
                ActionChains(self.driver).move_by_offset(cx, cy).click_and_hold().move_by_offset(-160,
                                                                                                 -15).release().perform()
                ActionChains(self.driver).move_by_offset(-cx + 160, -cy + 15).perform()
                time.sleep(0.3)

                # Zoom in/out
                self.driver.execute_script("""  
                    const e1 = new WheelEvent('wheel', {deltaY: -220});
                    const e2 = new WheelEvent('wheel', {deltaY:  220});
                    const el = document.elementFromPoint(arguments[0], arguments[1]);
                    if (el) {
                        el.dispatchEvent(e1);
                        el.dispatchEvent(e2);
                    }
                """, cx, cy)
                time.sleep(0.3)
        except Exception as e:
            self.logger.error(f"Error during map pan/zoom: {e}")
        self.logger.info("Map pan/zoom complete.")

    def fill_nickname_field(self, value: str = "sinale"):
        """Finds and fills a nickname/username field."""
        if self.nicknamed_filled:
            return

        self.logger.info("Attempting to fill nickname field...")
        try:
            inputs = self.driver.find_elements(By.TAG_NAME, "input")
            keywords = ["name", "nickname", "displayname"]
            for input_el in inputs:
                attrs = {
                    "name": input_el.get_attribute("name") or "",
                    "id": input_el.get_attribute("id") or "",
                    "placeholder": input_el.get_attribute("placeholder") or ""
                }
                for attr_value in attrs.values():
                    if any(k in attr_value.lower() for k in keywords):
                        input_el.clear()
                        input_el.send_keys(value)
                        self.logger.info(f"[V] Filled nickname field: {attr_value}")
                        self.nicknamed_filled = True
                        return
        except Exception as e:
            self.logger.error(f"Error trying to fill nickname: {e}")
        self.logger.warning("[X] Could not find nickname field.")

    def press_enter_on_focused(self):
        """Finds the active element and presses ENTER."""
        self.logger.info("Pressing ENTER on focused element...")
        try:
            focused = self.driver.switch_to.active_element
            if focused:
                focused.send_keys(Keys.ENTER)
                self.logger.info("[V] Pressed ENTER.")
            else:
                self.logger.warning("No element focused.")
        except Exception as e:
            self.logger.error(f"Error pressing ENTER: {e}")

    def force_play_media(self, selector_string: str):
        """
        Attempts to find an <audio> or <video> element and force it to play
        using JavaScript. This is a robust fallback if a simple .click() fails.
        """
        if not selector_string:
            return

        self.logger.info(f"Attempting to force-play media: {selector_string}")
        # Use the same finding logic as click_button_advanced
        groups = [name.strip() for name in selector_string.split(",") if name.strip()]
        for group in groups:
            for original_name in [a.strip() for a in group.split("|") if a.strip()]:
                name, idx = original_name, 0
                m = CLASS_INDEX_RE.match(original_name)
                if m:
                    name, idx = m.group("class"), int(m.group("idx"))

                try:
                    elements = []
                    # Try to find by selector
                    if name.startswith(":"):
                        xpath = f"//*[contains(normalize-space(string()),'{name[1:]}') or contains(@aria-label, '{name[1:]}')]"
                        elements = self.driver.find_elements(By.XPATH, xpath)
                    else:
                        elements = self.driver.find_elements(By.CLASS_NAME, name)
                        if not elements:
                            elements = self.driver.find_elements(By.ID, name)

                    # Also check for <audio> or <video> tags directly
                    if not elements:
                        if name.lower() in ['audio', 'video']:
                            elements = self.driver.find_elements(By.TAG_NAME, name)

                    if not elements: continue
                    if not (0 <= idx < len(elements)): continue

                    element = elements[idx]
                    # Check if it's a media element before running JS
                    if element.tag_name in ['audio', 'video']:
                        self.logger.info(f"Found media element <{element.tag_name}>. Forcing play...")
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                        self.driver.execute_script("arguments[0].muted = false; return arguments[0].play();", element)
                        self.logger.info("Force-play command sent.")
                        return  # Found and played
                    else:
                        self.logger.info(f"Element {name} was found but was not <audio> or <video>.")

                except Exception as e:
                    self.logger.warning(f"Could not force-play media '{original_name}': {e}")

    def perform_browsing_simulation(self, max_links: int = 2):
        """
        Simulates basic browsing: scrolls and clicks a few internal links.
        """
        self.logger.info("Starting browsing simulation...")
        try:
            # Scroll around
            for _ in range(3):
                self.driver.execute_script("window.scrollBy(0, 1000);")
                time.sleep(0.2)
                self.driver.execute_script("window.scrollBy(0, -500);")
                time.sleep(1)

            # Find and click internal links
            domain = self.driver.current_url.split('/')[2]  # Get "www.example.com"
            base_domain = '.'.join(domain.split('.')[-2:])  # Get "example.com"
            if not base_domain:  # Handle cases like 'localhost'
                base_domain = domain

            # Find links that start with / OR contain the base domain
            links = self.driver.find_elements(By.XPATH,
                                              f"//a[starts-with(@href, '/') or contains(@href, '{base_domain}')]")

            internal_links = [l for l in links if l.is_displayed() and l.is_enabled()]
            self.logger.info(f"Found {len(internal_links)} clickable internal links.")

            clicked_links = 0
            for i in range(len(internal_links)):
                if clicked_links >= max_links:
                    break
                try:
                    # Re-find links each time to avoid StaleElementReferenceException
                    links_fresh = self.driver.find_elements(By.XPATH,
                                                            f"//a[starts-with(@href, '/') or contains(@href, '{base_domain}')]")
                    link = links_fresh[i]

                    if not (link.is_displayed() and link.is_enabled()):
                        continue

                    href = link.get_attribute('href')
                    self.logger.info(f"Clicking link {i + 1}: {href}")
                    link.click()
                    clicked_links += 1
                    time.sleep(3)  # Wait for new page to load

                    # After navigation, we must break or re-find elements
                    # For this sim, we'll try to go back and continue
                    if clicked_links < max_links:
                        self.logger.info("Navigating back to continue browsing.")
                        self.driver.back()
                        time.sleep(2)

                except Exception as e:
                    self.logger.warning(f"Could not click link {i + 1}: {e}")
                    # Try to recover by going back
                    try:
                        self.driver.back()
                        time.sleep(2)
                    except Exception as back_e:
                        self.logger.error(f"Could not navigate back: {back_e}")
                        break  # Stop simulation

        except Exception as e:
            self.logger.error(f"Error during browsing simulation: {e}")

    def upload_file(self, file_input_selector: str, submit_selector: str):
        """
        Simulates a file upload: creates a dummy file, finds the input,
        sends the file path, and clicks submit.
        """
        if not file_input_selector:
            self.logger.warning("No file input selector provided. Cannot upload.")
            return

        self.logger.info("Starting file upload simulation...")

        # Create a dummy file
        dummy_file_name = "dummy_upload.txt"
        dummy_file_path = os.path.abspath(dummy_file_name)
        try:
            with open(dummy_file_path, "w") as f:
                f.write("This is a dummy file for traffic generation.")
            self.logger.info(f"Created dummy file at: {dummy_file_path}")

            # Find the file input element
            file_input = None
            try:
                # Try finding by common selectors
                if file_input_selector.startswith(":"):
                    file_input = self.driver.find_element(By.XPATH,
                                                          f"//input[@type='file' and contains(@aria-label, '{file_input_selector[1:]}')]")
                elif file_input_selector.startswith("."):
                    file_input = self.driver.find_element(By.CLASS_NAME, file_input_selector[1:])
                elif file_input_selector.startswith("#"):
                    file_input = self.driver.find_element(By.ID, file_input_selector[1:])
                else:
                    # Fallback to a generic input[type=file]
                    file_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='file']")
            except Exception as e:
                self.logger.error(
                    f"Could not find file input element with selector '{file_input_selector}'. Error: {e}")
                return

            # Send the file path to the input
            # Selenium requires send_keys on the <input> element
            file_input.send_keys(dummy_file_path)
            self.logger.info("Sent file path to input element.")
            time.sleep(1)

            # Click the submit button
            if submit_selector:
                self.logger.info(f"Clicking submit button: {submit_selector}")
                # Use click_button_advanced for complex submit buttons
                self.click_button_advanced(submit_selector)
            else:
                self.logger.info("No submit selector, assuming upload starts automatically.")

            time.sleep(4)  # Wait for upload to process

        except Exception as e:
            self.logger.error(f"File upload failed: {e}")
        finally:
            # Clean up the dummy file
            if os.path.exists(dummy_file_path):
                os.remove(dummy_file_path)
                self.logger.info("Cleaned up dummy file.")