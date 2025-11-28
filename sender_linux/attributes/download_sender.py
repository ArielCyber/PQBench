import time
from typing import Dict

import backoff
import backoff
import tldextract
import tldextract
# Selenium Imports
import undetected_chromedriver as uc
# Selenium Imports
import undetected_chromedriver as uc
from page_interactor import PageInteractor
# Playwright Imports
from playwright.sync_api import sync_playwright
# Playwright Imports
from playwright.sync_api import sync_playwright
from sender import Sender


class DownloadSender(Sender):
    uses_playwright = False

    def create_traffic(self, interactor: PageInteractor, data: Dict):
        play_class = data.get("play_class", "")

        clicked = interactor.click_button_advanced(play_class)
        if not clicked:
            interactor.try_iframes(play_class)

        print("[V] Waiting for download completion...")
        time.sleep(self.wait_time)