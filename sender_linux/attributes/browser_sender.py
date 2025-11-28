import time

import backoff
import tldextract
# Selenium Imports
import undetected_chromedriver as uc
from page_interactor import PageInteractor
# Playwright Imports
from playwright.sync_api import sync_playwright
from sender import Sender


class BrowserSender(Sender):
    """
    Uses Playwright for fast browsing simulation.
    """
    uses_playwright = True

    def create_traffic(self, interactor, data):
        print(f"[BrowserSender] Starting Playwright logic for {self.website_url}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            try:
                page.goto(self.website_url, timeout=60000, wait_until="domcontentloaded")

                # Scroll
                for _ in range(3):
                    page.mouse.wheel(0, 1000)
                    time.sleep(0.5)
                    page.mouse.wheel(0, -500)
                    time.sleep(1)

                # Click Internal Links
                links = page.query_selector_all("a[href^='/']")
                for i in range(min(2, len(links))):
                    try:
                        links[i].click(timeout=3000)
                        print(f"[V] Clicked internal link {i}")
                        time.sleep(2)
                    except:
                        continue

            except Exception as e:
                print(f"[X] Browser Playwright Error: {e}")
            finally:
                browser.close()