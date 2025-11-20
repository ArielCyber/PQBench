from sender import Sender
from page_interactor import PageInteractor


class RTTSender(Sender):
    """
    Generates RTT (Real-Time Ticker/Text) traffic by continuously
    scrolling a page to simulate reading a live feed.
    """

    def __init__(self, browser: str, algo: int, sessions: int, website_url: str, wait_time: int = None):
        super().__init__(
            browser=browser, algo=algo, sessions=sessions,
            website_url=website_url, attribute="RTT", wait_time=wait_time
        )
        self.logger.info(f"RTTSender initialized for {website_url}")

    def create_traffic(self, interactor: PageInteractor, button_data: dict):
        self.logger.info("Running RTT-specific traffic logic...")

        shadow_button = button_data.get("shadow_button")
        play_button = button_data.get("play_button")  # e.g., a "load more" button

        # Clear overlays
        interactor.click_shadow_button_advanced(shadow_button)

        # Click any initial button (if one exists)
        clicked = interactor.click_button_advanced(play_button)
        if not clicked:
            interactor.try_iframes(play_button)

        # Perform RTT scrolling
        interactor.perform_rtt_scrolling(duration=self.wait_time)
