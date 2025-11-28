import time
from typing import Dict

import backoff
import tldextract
# Selenium Imports
import undetected_chromedriver as uc
from page_interactor import PageInteractor
# Playwright Imports
from playwright.sync_api import sync_playwright
from sender import Sender


class AudioSender(Sender):
    uses_playwright = False

    def create_traffic(self, interactor: PageInteractor, data: Dict):
        play_class = data.get("play_class", "")
        clicked = interactor.click_button_advanced(play_class)

        time.sleep(5)

        if not clicked:
            interactor.try_iframes(play_class)

        if isinstance(clicked, WebElement):
            print("running <audio> play")
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", clicked)
            clicked.click()
            self.driver.execute_script("arguments[0].muted = false; return arguments[0].play();", clicked)
            time.sleep(wait_time)
            print(f"[V] Captured <Audio> for {wait_time} seconds...")
        else:
            self.try_iframes()
        if not self.play_class:
            time.sleep(wait_time)
            print(f"[V] Captured <Audio> for {wait_time} seconds...")

        print(f"[V] Listening to audio for {self.wait_time}s...")
        time.sleep(self.wait_time)
