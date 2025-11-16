import logging
import time

from sender import Sender
from page_interactor import PageInteractor


class VideoSender(Sender):
    """
    Generates web traffic that simulates watching a video.
    """

    def __init__(self, browser: str, algo: int, sessions: int, website_url: str, wait_time: int = None):
        # We pass "Video" as the attribute, which is used by the
        # ConfigService to fetch the correct button names.
        super().__init__(
            browser=browser,
            algo=algo,
            sessions=sessions,
            website_url=website_url,
            attribute="Video",  # Hardcoded for this class
            wait_time=wait_time
        )
        self.logger.info(f"VideoSender initialized for {website_url}")

    def create_traffic(self, interactor: PageInteractor, button_data: dict):
        """
        Implements the specific traffic generation logic for a video
        by delegating actions to the PageInteractor.
        """
        self.logger.info("Running video-specific traffic logic...")

        # Get button names from the data passed by the base class
        shadow_button = button_data.get("shadow_button")
        play_button = button_data.get("play_button")

        # Delegate shadow button click
        interactor.click_shadow_button_advanced(shadow_button)

        # Delegate main play button click
        self.logger.info("Attempting to click main play button...")
        play_clicked = interactor.click_button_advanced(play_button)

        # Delegate iframe search if needed
        if not play_clicked:
            self.logger.info("Main play button not found, searching iframes...")
            interactor.try_iframes(play_button)
        else:
            self.logger.info("Main play button clicked successfully.")

        self.logger.info("Attempting to force-play media as a fallback...")
        interactor.force_play_media(play_button)

        # Simulate watch time
        watch_duration = 30
        self.logger.info(f"Simulating video watch time for {watch_duration} seconds...")
        time.sleep(watch_duration)
        self.logger.info("Video simulation complete.")
