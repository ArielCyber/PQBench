import logging

from sender import Sender
from page_interactor import PageInteractor
import time


class AudioSender(Sender):
    """
    Generates Audio traffic by clicking a play button and
    using a JS fallback to force playback.
    """

    def __init__(self, browser: str, algo: int, sessions: int, website_url: str, wait_time: int = None):
        super().__init__(
            browser=browser, algo=algo, sessions=sessions,
            website_url=website_url, attribute="Audio", wait_time=wait_time
        )
        self.logger.info(f"AudioSender initialized for {website_url}")

    def create_traffic(self, interactor: PageInteractor, button_data: dict):
        self.logger.info("Running Audio-specific traffic logic...")

        shadow_button = button_data.get("shadow_button")
        play_button = button_data.get("play_button")
        logging.debug(f"found button to press: {play_button}")

        # Clear overlays
        interactor.click_shadow_button_advanced(shadow_button)

        # Try to click the "Play" button
        clicked = interactor.click_button_advanced(play_button)

        # If not found, try iframes
        if not clicked:
            interactor.try_iframes(play_button)

        # As a fallback, try to force-play the media element
        # This handles cases where .click() isn't enough
        interactor.force_play_media(play_button)

        # Simulate listening time
        self.logger.info(f"Simulating audio listening for {self.wait_time} seconds...")
        time.sleep(self.wait_time)
        self.logger.info("Audio simulation complete.")