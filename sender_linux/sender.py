import tldextract
from abc import ABC, abstractmethod
from typing import Dict, Optional, Any

import backoff
import tldextract
import undetected_chromedriver as uc
from playwright.sync_api import sync_playwright

from browser_manager import BrowserManager
from config_service import ConfigService
from page_interactor import PageInteractor


class Sender(ABC):
    """Abstract Base Class for all traffic senders."""

    uses_playwright = False

    def __init__(self, attribute: str, browser_str: str, sessions: int, website_url: str, wait_time: int, algo: int):
        self.attribute = attribute
        self.browser_str = browser_str
        self.sessions = sessions
        self.website_url = website_url
        self.wait_time = wait_time

        # Dependencies
        self.config_service = ConfigService()
        self.browser_manager = BrowserManager(browser_str, algo)

    def run(self):
        """Main Template Method."""
        print(f"\n[{self.attribute}] Starting sender for {self.website_url}")

        # Fetch Config
        config_data = self.config_service.get_button_values(self.website_url, self.attribute) or {}

        if self.uses_playwright:
            self.create_traffic(None, config_data)
        else:
            # Selenium Lifecycle
            driver = self.browser_manager.setup_driver()
            try:
                driver.get(self.website_url)
                interactor = PageInteractor(driver, config_data.get("play_class", ""), self.website_url)
                interactor.click_shadow_button()
                self.create_traffic(interactor, config_data)
            except Exception as e:
                print(f"[X] Error in Sender run: {e}")
            finally:
                if driver:
                    driver.quit()

    @abstractmethod
    def create_traffic(self, interactor: Optional[PageInteractor], data: Dict[str, Any]):
        pass
