import logging
import re
import time
from typing import Dict, Optional

import requests
from selenium.common import NoSuchElementException
from selenium.webdriver.common.by import By

CLASS_INDEX_RE = re.compile(r'^(?P<class>[A-Za-z0-9_\-.:]+)\\[(?P<idx>\\d+)\\]$')

def click_shadow_button(shadow_class, driver):
    logging.debug("############### shadow_button ##############  ")
    try:
        shadow_hosts = driver.execute_script("""
            return Array.from(document.querySelectorAll("*"))
                .filter(el => el.shadowRoot !== null);
        """)
        if not shadow_hosts:
            logging.error(f"No shadow_hosts")
        for host in shadow_hosts:
            clicked = driver.execute_script("""
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
            """, host, shadow_class)
            if clicked:
                logging.info(f"Clicked '{shadow_class}'")
                return
            else:
                logging.error(f"Couldn't find '{shadow_class}'")
    except Exception as e:
        logging.error("No shadow DOM found")


def click_play_button(play_class, driver, tries=0):
    logging.debug("############# click_play_button ############  ")
    time.sleep(2)
    groups = [name.strip() for name in play_class.split(",") if name.strip()]
    name_done = [False for _ in range(len(groups))]
    not_found_so_unloaded = True
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
                    elements = driver.find_elements(By.XPATH,
                                                    f"//button[contains(normalize-space(string()),'{name[1:]}')]")
                else:
                    elements = driver.find_elements(By.CLASS_NAME, name)
                if not elements and not name.startswith(":"):
                    elements = driver.find_elements(By.ID, name)
                if elements:
                    not_found_so_unloaded = False
                else:
                    logging.error("No element found")
                    raise Exception("no elements found")
                if idx < 0 or idx >= len(elements):
                    logging.debug(
                        f"Class/Name '{name}' has {len(elements)} elements; index {idx} is out of range")
                    continue
                for element in elements[idx:]:
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                        time.sleep(0.5)
                        if element.tag_name.lower() == "audio": return element
                        element.click()
                        logging.info(f"Clicked '{name}'")
                        play_class = after_click(play_class, group)
                        name_done[i] = True
                        time.sleep(3)
                        break
                    except:
                        continue
            except Exception as e:
                logging.error(f"Couln't find {name}")
                continue
            if name_done[i]:
                break
    if not_found_so_unloaded:
        if tries > 0:
            logging.error(f"Unloaded '{play_class}'")
            return False
        click_play_button(play_class, driver, tries)
    for curNameDone in name_done:
        if curNameDone:
            return True
    return False


def after_click(play_class, name):
    return ",".join([c for c in play_class.split(",") if c.strip() != name])


def play_video(driver):
    try:
        wait_time = 10
        driver.find_element(By.TAG_NAME, "video")
        time.sleep(2)
        driver.execute_script("""
                    const video = document.querySelector('video');
                    if (video) {
                        video.muted = true;
                        video.play().catch(() => {});
                    }
                """)
        time.sleep(wait_time)
        logging.info(f"Captured <Video> for {wait_time} seconds...")
        return True
    except NoSuchElementException:
        logging.error(f"Failed to play <Video>")
        return False


def get_button_values(domain: str, attribute: str, base_url: str = "http://domain_maintainer:5010") -> Optional[
    Dict[str, str]]:
    """
    Fetches button values for a given domain and attribute by making a GET request
    to the domain_maintainer service.

    Args:
        domain: The domain to search for (e.g., "youtube.com").
        attribute: The attribute (worksheet) to search within (e.g., "video").
        base_url: The base URL of the domain_maintainer service.

    Returns:
        A dictionary containing the values from the first and second columns
        (e.g., {"value_col_1": "...", "value_col_2": "..."}) if found.
        Returns None if the domain is not found or if an error occurs.
    """
    if not domain or not attribute:
        logging.error("Domain and attribute cannot be empty.")
        return None

    endpoint = f"{base_url}/get_button_by_domain/"
    params = {"domain": domain, "attribute": attribute}

    try:
        response = requests.get(endpoint, params=params)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"Info: Domain '{domain}' not found in attribute '{attribute}'.")
        else:
            print(f"HTTP Error fetching button values: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching button values: {e}")
        return None
    except ValueError:
        print("Error: Failed to decode JSON response from the server.")
        return None


def find_and_play_in_iframes(driver, play_class):
    """
    Searches all iframes recursively to find and play a video.
    It can also click a play button if specified.
    """
    logging.debug("Attempting to find video in iframes...")

    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    if not iframes:
        return False

    for iframe in iframes:
        try:
            driver.switch_to.frame(iframe)
            logging.debug("Switched to an iframe.")

            if play_video(driver):
                return True

            if play_class and click_play_button(play_class, driver):
                time.sleep(2)
                if play_video(driver):
                    return True

            if find_and_play_in_iframes(driver, play_class):
                return True

            driver.switch_to.parent_frame()

        except Exception as e:
            logging.warning(f"Error processing iframe: {e}. Switching to default content and continuing.")
            driver.switch_to.default_content()
            continue

    return False