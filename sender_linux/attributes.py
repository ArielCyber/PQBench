import time

from sender import Sender  # Import from your main sender file


class VideoSender(Sender):
    """
    Generates web traffic that simulates watching a video.

    This class inherits all the complex browser and clicking logic
    from the Sender base class and simply implements the
    `create_traffic` method for the "Video" attribute.
    """

    def __init__(self, browser: str, algo: int, sessions: int, website_url: str, wait_time=10):
        """
        Initializes the VideoSender.

        It automatically sets the attribute to "Video" for the
        base class constructor.
        """
        # We pass "Video" as the attribute, which is used to
        # fetch the correct button names (play_button, shadow_button)
        # from your external domain_maintainer service.
        super().__init__(
            browser=browser,
            algo=algo,
            sessions=sessions,
            website_url=website_url,
            attribute="Video",  # Hardcoded for this class
            wait_time=wait_time
        )
        self.logger.info(f"VideoSender initialized for {website_url}")

    def create_traffic(self):
        """
        Implements the specific traffic generation logic for a video.

        The flow is:
        1. Try to click any "shadow buttons" (popups, cookie consents).
        2. Try to click the main "play button" on the page.
        3. If the main button isn't found, search for it inside iframes.
        4. Wait for 30 seconds to simulate watching the video.
        """
        self.logger.info("Running video-specific traffic logic...")

        # Click shadow button first (e.g., cookie banners, ad overlays)
        # self.shadow_button name is already populated by the run() method.
        self.click_shadow_button_advanced()

        # Try to click the main play button.
        # self.play_button name is also populated by run().
        self.logger.info("Attempting to click main play button...")
        play_clicked = self.click_button_advanced(self.play_button)

        # If no main play button was found/clicked, search in iframes.
        if not play_clicked:
            self.logger.info("Main play button not found or failed, searching iframes...")
            self.try_iframes()
        else:
            self.logger.info("Main play button clicked successfully.")

        # Simulate watch time
        watch_duration = 30  # Simulate 30 seconds of watch time
        self.logger.info(f"Simulating video watch time for {watch_duration} seconds...")
        try:
            time.sleep(watch_duration)
            self.logger.info("Video simulation complete.")
        except KeyboardInterrupt:
            self.logger.info("Watch simulation interrupted.")