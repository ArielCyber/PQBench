import time
import time

import backoff
import tldextract
import undetected_chromedriver as uc
# Playwright Imports
from playwright.sync_api import sync_playwright
# Selenium Imports
from selenium.common.exceptions import NoSuchElementException
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys


class PageInteractor:
    """
    Encapsulates DOM interactions for Selenium-based Senders.
    """

    def __init__(self, driver: webdriver.Remote, play_class, url, skip_class=""):
        self.driver = driver
        self.skip_class = skip_class
        self.play_class = play_class
        self.url = url

    def setup_website(self):
        print(f"\nStarting capture for {self.app_name} with: {self.url}")
        self.driver.get(self.url)
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(self.driver).send_keys("thisisunsafe").perform()
        self.driver.execute_script("if (document.activeElement) document.activeElement.blur();")
        print("[W] Bypassed SSL warning screen with 'thisisunsafe'")
        time.sleep(2)
        self.driver.execute_script(
            "(document.scrollingElement || document.documentElement).scrollTo({top: 99999, behavior: 'smooth'});")
        time.sleep(1)
        self.driver.execute_script(
            "(document.scrollingElement || document.documentElement).scrollTo({ top: 0, behavior: 'smooth' });")
        time.sleep(2)

    def click_shadow_button(self):
        if not self.skip_class or isinstance(self.skip_class, int): return
        print("############### shadow_button ##############  ", end='')
        try:
            shadow_hosts = self.driver.execute_script("""
                return Array.from(document.querySelectorAll("*"))
                    .filter(el => el.shadowRoot !== null);
            """)
            if not shadow_hosts: print(f"[X] - No shadow_hosts")
            for host in shadow_hosts:
                clicked = self.driver.execute_script("""
                    const footer = arguments[0];
                    const selector = arguments[1];
                    const root = footer.shadowRoot;
                    if (!root) return false;
                    const btn = root.querySelector(selector);
                    if (btn) {
                        btn.focus();
                        btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                        btn.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                        btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                        return true;
                    }
                    return false;
                """, host, self.skip_class)
                if clicked:
                    print(f"[V] - Clicked '{self.skip_class}'")
                    self.skip_class = ""
                    return
                else:
                    print(f"[X] - Couldn't find '{self.skip_class}'")
        except Exception as e:
            print("[X] - No shadow DOM found")

    def force_play_media(self, tag_name="video"):
        """Attempts to play media in the CURRENT frame."""
        try:
            # Check if element exists first to avoid silent JS failures
            els = self.driver.find_elements(By.TAG_NAME, tag_name)
            if els:
                self.driver.execute_script(f"""
                    const media = document.querySelector('{tag_name}');
                    if (media) {{
                        media.muted = false;
                        media.play().catch(e => console.error("Play failed:", e));
                    }}
                """)
                return True
        except Exception:
            pass
        return False

    def _get_all_iframes_including_shadow(self):
        """
        Finds all iframes, including those inside Shadow DOMs.
        Returns a list of WebElement iframes.
        """
        # 1. Standard Iframes
        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")

        # 2. Shadow DOM Iframes (Javascript fallback)
        try:
            shadow_iframes = self.driver.execute_script("""
                function getAllIframes(root) {
                    let frames = Array.from(root.querySelectorAll('iframe'));
                    let shadowHosts = root.querySelectorAll('*');
                    shadowHosts.forEach(host => {
                        if (host.shadowRoot) {
                            frames = frames.concat(getAllIframes(host.shadowRoot));
                        }
                    });
                    return frames;
                }
                return getAllIframes(document.body);
            """)
            if shadow_iframes:
                # Merge lists, avoiding duplicates if possible (Selenium references handle this poorly, so we just append)
                iframes.extend(shadow_iframes)
        except Exception:
            pass

        return iframes

    def search_and_play_video_recursive(self, depth=0, max_depth=4) -> bool:
        """
        Recursively searches for a <video> tag in all iframes (nested & shadow).
        """
        if depth > max_depth: return False

        # 1. Try to play in current frame
        if self.force_play_media("video"):
            print(f"[DEBUG] Found and played video at depth {depth}")
            return True

        # 2. Wait slightly if no iframes found yet (Logic for top level only)
        if depth == 0:
            try:
                WebDriverWait(self.driver, 5).until(
                    lambda d: len(d.find_elements(By.TAG_NAME, "iframe")) > 0 or
                              len(d.find_elements(By.TAG_NAME, "video")) > 0
                )
            except:
                print("[DEBUG] Timeout waiting for iframes/video to populate.")

        # 3. Get all iframes in this context
        iframes = self._get_all_iframes_including_shadow()

        if not iframes and depth == 0:
            print("[DEBUG] No iframes found even after wait.")

        for i, iframe in enumerate(iframes):
            try:
                # Switch to frame
                self.driver.switch_to.frame(iframe)

                # Recurse
                if self.search_and_play_video_recursive(depth + 1, max_depth):
                    return True

                # Switch back to parent to continue loop
                self.driver.switch_to.parent_frame()
            except Exception:
                # If frame switching fails (e.g. cross-origin restriction or frame detached), ensure we go back
                try:
                    self.driver.switch_to.parent_frame()
                except:
                    pass

        return False

    def click_play_button(self, tries=0):
        if not self.play_class: return True
        print("############# click_play_button ############  ", end='')
        time.sleep(2)
        groups = [name.strip() for name in self.play_class.split(",") if name.strip()]
        nameDone = [False for _ in range(len(groups))]
        notFoundSoUnloaded = True
        tries += 1
        for i, group in enumerate(groups):
            for originalName in [a.strip() for a in group.split("|") if a.strip()]:
                name = originalName
                idx = 0
                m = CLASS_INDEX_RE.match(originalName)
                if m:
                    name = m.group("class")
                    idx = int(m.group("idx"))
                try:
                    if name.startswith(":"):
                        elements = self.driver.find_elements(By.XPATH,
                                                             f"//button[contains(normalize-space(string()),'{name[1:]}')]")
                    else:
                        elements = self.driver.find_elements(By.CLASS_NAME, name)
                    if not elements and not name.startswith(":"):
                        elements = self.driver.find_elements(By.ID, name)
                    if elements:
                        notFoundSoUnloaded = False
                    else:
                        raise Exception("no elements found")
                    if idx < 0 or idx >= len(elements):
                        print(f"[X] - Class/Name '{name}' has {len(elements)} elements; index {idx} is out of range")
                        continue
                    for element in elements[idx:]:
                        try:
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                            time.sleep(0.5)
                            if element.tag_name.lower() == "audio": return element
                            element.click()
                            print(f"[V] - Clicked '{name}'")
                            self.after_click(group)
                            nameDone[i] = True
                            time.sleep(3)
                            break
                        except:
                            continue
                except Exception as e:
                    print(f"[X] - Couln't find {name}")
                    continue
                if nameDone[i]: break
        if notFoundSoUnloaded:
            if tries > 0:
                print(f"[X] - Unloaded '{self.play_class}'")
                return False
            self.click_play_button(tries)
        for curNameDone in nameDone:
            if curNameDone: return True
        return False

    def after_click(self, name):
        self.play_class = ",".join([c for c in self.play_class.split(",") if c.strip() != name])

    def try_iframes(self):
        print(f"################## iframe ##################  ", end='')
        self.driver.switch_to.default_content()
        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            if self.handle_iframe(iframe): return True
        return False

    def click_outof_iframe(self):
        if not self.play_class: return True
        self.driver.switch_to.default_content()
        clicked = self.click_play_button()
        time.sleep(2)
        self.force_play_media()
        return clicked

    def try_iframes_in_iframe(self):
        try:
            print(f"############# iframe in iframe #############  ", end='')
            self.driver.switch_to.default_content()
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                self.driver.switch_to.frame(iframe)
                iframes2 = self.driver.find_elements(By.TAG_NAME, "iframe")
                for iframe2 in iframes2:
                    if self.handle_iframe(iframe2): return True
            return False
        except Exception as e:
            return False

    def handle_iframe(self, iframe):
        try:
            self.driver.switch_to.frame(iframe)
            time.sleep(2)
            clicked = self.click_play_button()
            if clicked and not self.click_outof_iframe():
                self.try_iframes()
            time.sleep(2)
            if clicked and self.force_play_media():
                self.driver.switch_to.default_content()
                return True
            self.driver.switch_to.default_content()
        except:
            self.driver.switch_to.default_content()
        return False