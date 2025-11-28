from typing import Dict

import backoff
import tldextract
# Selenium Imports
import undetected_chromedriver as uc
from page_interactor import PageInteractor
# Playwright Imports
from playwright.sync_api import sync_playwright
from sender import Sender


class RTTSender(Sender):
    uses_playwright = False

    def create_traffic(self, interactor: PageInteractor, data: Dict):
        play_class = data.get("play_class", "")

        interactor.click_button_advanced(play_class)

        print(f"[V] Scrolling (RTT) for {self.wait_time}s...")
        interactor.perform_rtt_scrolling(duration=self.wait_time)
