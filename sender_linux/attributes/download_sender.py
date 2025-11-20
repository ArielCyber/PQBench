from sender import Sender
from page_interactor import PageInteractor
import time


class DownloadSender(Sender):
    """
    Generates Download traffic by clicking a download button
    and waiting for the download to process.
    """

    def __init__(self, browser: str, algo: int, sessions: int, website_url: str, wait_time: int = None):
        # Default wait_time for downloads is shorter
        super().__init__(
            browser=browser, algo=algo, sessions=sessions,
            website_url=website_url, attribute="Download", wait_time=wait_time
        )
        self.logger.info(f"DownloadSender initialized for {website_url}")

    def create_traffic(self, interactor: PageInteractor, button_data: dict):
        self.logger.info("Running Download-specific traffic logic...")

        shadow_button = button_data.get("shadow_button")
        play_button = button_data.get("play_button")  # The "Download" button

        # Clear overlays
        interactor.click_shadow_button_advanced(shadow_button)

        # Click the "Download" button
        clicked = interactor.click_button_advanced(play_button)
        if not clicked:
            interactor.try_iframes(play_button)

        # Wait for download to start
        self.logger.info(f"Waiting {self.wait_time} seconds for download to start...")
        time.sleep(self.wait_time)
        self.logger.info("Download simulation complete.")