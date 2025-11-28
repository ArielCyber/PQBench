import time
from typing import Dict

import backoff
import tldextract
import undetected_chromedriver as uc
from page_interactor import PageInteractor
from sender import Sender


class VideoSender(Sender):
    uses_playwright = False

    def create_traffic(self, interactor: PageInteractor, data: Dict):
        try:
            play_class = data.get("play_class", "")

            time.sleep(1)
            clicked = interactor.click_play_button(play_class)
            time.sleep(3)

            found_video = interactor.search_and_play_video_recursive()

            if found_video:
                print(f"[V] Captured <Video> (playing for {self.wait_time}s)...")
                time.sleep(float(self.wait_time))
            else:
                # Fallback: If we couldn't find a <video> tag, maybe the 'play_class' click
                # opened a new player? Try iframes specifically for the button if we haven't already.
                if not clicked:
                    print("[DEBUG] Video tag not found, trying to click buttons inside iframes...")
                    if interactor.try_iframes(play_class):
                        # Try finding video again after clicking in iframe
                        if interactor.search_and_play_video_recursive():
                            print(f"[V] Captured <Video> after iframe click...")
                            time.sleep(float(self.wait_time))
                            return

            print(f"[V] Watching video for {self.wait_time}s...")
            time.sleep(self.wait_time)
        except Exception as e:
            # Catch-all to prevent the 'NameError' from hiding the real issue
            print(f"[X] Unexpected error in VideoSender: {e}")
