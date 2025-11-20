from sender import Sender
from page_interactor import PageInteractor
import time


class GameSender(Sender):
    """
    Generates Game traffic by filling a nickname, pressing Enter,
    and simulating play time.
    """

    def __init__(self, browser: str, algo: int, sessions: int, website_url: str, wait_time: int = None):
        super().__init__(
            browser=browser, algo=algo, sessions=sessions,
            website_url=website_url, attribute="Game", wait_time=wait_time
        )
        self.logger.info(f"GameSender initialized for {website_url}")

    def create_traffic(self, interactor: PageInteractor, button_data: dict):
        self.logger.info("Running Game-specific traffic logic...")

        shadow_button = button_data.get("shadow_button")
        play_button = button_data.get("play_button")  # "Play" or "Start"

        # Fill nickname/username field if found
        interactor.fill_nickname_field()

        # Try pressing enter on the focused element (e.g., after filling form)
        interactor.press_enter_on_focused()

        # Clear overlays
        interactor.click_shadow_button_advanced(shadow_button)

        # Click the "Play" button
        clicked = interactor.click_button_advanced(play_button)
        if not clicked:
            interactor.try_iframes(play_button)

        # Simulate play time
        self.logger.info(f"Simulating game play for {self.wait_time} seconds...")
        time.sleep(self.wait_time)
        self.logger.info("Game simulation complete.")