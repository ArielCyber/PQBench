class MapSender(Sender):
    """
    Generates Map traffic by panning and zooming on the page.
    """

    def __init__(self, browser: str, algo: int, sessions: int, website_url: str, wait_time: int = None):
        super().__init__(
            browser=browser, algo=algo, sessions=sessions,
            website_url=website_url, attribute="Map", wait_time=wait_time
        )
        self.logger.info(f"MapSender initialized for {website_url}")

    def create_traffic(self, interactor: PageInteractor, button_data: dict):
        self.logger.info("Running Map-specific traffic logic...")

        shadow_button = button_data.get("shadow_button")
        play_button = button_data.get("play_button")  # e.g., "search" or "find"

        # Clear overlays
        interactor.click_shadow_button_advanced(shadow_button)

        # Click any initial button
        clicked = interactor.click_button_advanced(play_button)
        if not clicked:
            interactor.try_iframes(play_button)

        # Perform Map pan/zoom
        interactor.pan_and_zoom_map(duration=self.wait_time)
