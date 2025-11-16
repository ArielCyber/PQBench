import logging
from abc import ABC, abstractmethod
from selenium.webdriver.support.wait import WebDriverWait
import os

# Import the components
from browser_manager import BrowserManager, BrowserLaunchError
from page_interactor import PageInteractor
from config_service import ConfigService


class Sender(ABC):
    """
    Orchestrates the traffic generation process.
    It USES a BrowserManager, ConfigService, and PageInteractor.
    Its single responsibility is to manage the overall flow.
    """

    def __init__(self, browser: str, algo: int, sessions: int, website_url: str,
                 attribute: str, wait_time=10):
        self.website_url = website_url
        self.attribute = attribute
        self.sessions = sessions
        self.wait_time = wait_time
        self.logger = logging.getLogger(self.__class__.__name__)

        # --- COMPOSITION ---
        # Sender owns and delegates to these specialists
        self.browser_manager = BrowserManager(browser, algo)
        self.config_service = ConfigService()
        # -------------------

        if wait_time is not None:
            self.wait_time = wait_time
        else:
            # Try to find an attribute-specific env var (e.g., VIDEO_WAIT_TIME)
            specific_wait_env = f"{attribute.upper()}_WAIT_TIME"
            default_wait_env = os.environ.get("DEFAULT_WAIT_TIME", "10")  # Default 10 if nothing found

            self.wait_time = int(os.environ.get(specific_wait_env, default_wait_env))

        self.logger.info(f"Set wait time to {self.wait_time} seconds")
        self.button_data: dict = {}

    def run(self):
        """Executes the full traffic generation flow."""
        self.logger.info(f"--- Starting traffic generation for {self.website_url} ---")

        # Fetch config ONCE
        self.button_data = self.config_service.get_button_values(self.website_url, self.attribute) or {}
        if self.button_data:
            self.logger.info(f"Got button config: {self.button_data}")
        else:
            self.logger.warning("Could not fetch button config. Proceeding without.")

        # Loop for each session
        for i in range(self.sessions):
            self.logger.info(f"Starting session {i + 1} of {self.sessions}...")
            driver = None
            try:
                # Delegate browser setup
                driver = self.browser_manager.setup_driver()

                # Create a PageInteractor for this specific driver
                interactor = PageInteractor(driver)

                # Navigate
                driver.get(self.website_url)
                WebDriverWait(driver, self.wait_time).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )

                # Delegate initial interaction
                interactor.perform_initial_page_load_actions()

                # Call the child class's specific logic
                # We pass the interactor and config to the child
                self.create_traffic(interactor, self.button_data)

            except Exception as e:
                self.logger.error(f"Error during session {i + 1}: {e}", exc_info=True)
            finally:
                # Cleanup
                if driver:
                    driver.quit()
                self.logger.info(f"Finished session {i + 1}.")

        self.logger.info(f"--- Finished all traffic for {self.website_url} ---")

    @abstractmethod
    def create_traffic(self, interactor: PageInteractor, button_data: dict):
        """
        Main logic for generating traffic, implemented by child classes.
        It receives the PageInteractor and button config to perform its work.
        """
        pass