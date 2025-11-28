from typing import Dict

import backoff
import tldextract
# Selenium Imports
import undetected_chromedriver as uc
from page_interactor import PageInteractor
# Playwright Imports
from playwright.sync_api import sync_playwright
from sender import Sender


class MapSender(Sender):
    uses_playwright = False

    def create_traffic(self, interactor: PageInteractor, data: Dict):
        play_class = data.get("play_class", "")
        skip_class = data.get("skip_class", "")

        interactor.click_shadow_button_advanced(skip_class)
        interactor.click_button_advanced(play_class)

        # Grant Geolocation (Logic exists in BrowserManager setup, but page might need reload or prompt handling)

        print(f"[V] Interacting with Map for {self.wait_time}s...")
        interactor.pan_and_zoom_map(duration=self.wait_time)
