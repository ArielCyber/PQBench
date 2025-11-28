from sender import Sender
from page_interactor import PageInteractor
import time
from typing import Dict


class GameSender(Sender):
    uses_playwright = False

    def create_traffic(self, interactor: PageInteractor, data: Dict):
        play_class = data.get("play_class", "")

        interactor.fill_nickname_field()
        interactor.press_enter_on_focused()

        clicked = interactor.click_button_advanced(play_class)
        if not clicked:
            interactor.try_iframes(play_class)

        print(f"[V] Playing game for {self.wait_time}s...")
        time.sleep(self.wait_time)