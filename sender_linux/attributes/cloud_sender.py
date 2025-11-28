import os
import time

import backoff
import tldextract
# Selenium Imports
import undetected_chromedriver as uc
from page_interactor import PageInteractor
# Playwright Imports
from playwright.sync_api import sync_playwright
from sender import Sender


class CloudSender(Sender):
    """
    Uses Playwright specifically for robust file upload handling.
    Does NOT use PageInteractor (Selenium).
    """
    uses_playwright = True

    def create_traffic(self, interactor, data):
        print(f"[CloudSender] Starting Playwright logic for {self.website_url}")

        # Create dummy file
        dummy_file = "dummy_upload.txt"
        with open(dummy_file, "w") as f:
            f.write("Dummy content")

        with sync_playwright() as p:
            # We treat 'browser_str' loosely here, usually default to Chromium for Playwright
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()

            try:
                page.goto(self.website_url, timeout=60000, wait_until="domcontentloaded")

                # Upload Logic
                try:
                    page.wait_for_selector('input[type="file"]', timeout=10000)
                    page.set_input_files('input[type="file"]', dummy_file)
                    print("[V] File staged for upload")

                    # Try Submit
                    submit_btn = page.query_selector('button[type="submit"], input[type="submit"]')
                    if submit_btn:
                        submit_btn.click()
                        print("[V] Clicked Submit")
                except Exception as e:
                    print(f"[W] Upload interaction failed: {e}")

                time.sleep(self.wait_time)
            except Exception as e:
                print(f"[X] Cloud Playwright Error: {e}")
            finally:
                browser.close()
                if os.path.exists(dummy_file): os.remove(dummy_file)