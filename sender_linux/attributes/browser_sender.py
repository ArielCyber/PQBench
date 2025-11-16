class BrowserSender(Sender):
    """
    Generates Browsing traffic by scrolling and clicking internal links.
    """

    def __init__(self, browser: str, algo: int, sessions: int, website_url: str, wait_time: int = None):
        super().__init__(
            browser=browser, algo=algo, sessions=sessions,
            website_url=website_url, attribute="Browsing", wait_time=wait_time
        )
        self.logger.info(f"BrowserSender initialized for {website_url}")

    def create_traffic(self, interactor: PageInteractor, button_data: dict):
        self.logger.info("Running Browsing-specific traffic logic...")

        shadow_button = button_data.get("shadow_button")

        # Clear overlays
        interactor.click_shadow_button_advanced(shadow_button)

        # Perform browsing simulation (scroll and click links)
        interactor.perform_browsing_simulation(max_links=2)

        self.logger.info("Browsing simulation complete.")
        time.sleep(self.wait_time)  # Wait on the last page