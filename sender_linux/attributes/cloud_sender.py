class CloudSender(Sender):
    """
    Generates Cloud traffic by simulating a file upload.

    For this to work, the ConfigService must be configured:
    - "play_button": The selector for the <input type="file"> element.
    - "shadow_button": The selector for the "Submit" or "Upload" button.
    """

    def __init__(self, browser: str, algo: int, sessions: int, website_url: str, wait_time: int = None):
        super().__init__(
            browser=browser, algo=algo, sessions=sessions,
            website_url=website_url, attribute="Cloud", wait_time=wait_time
        )
        self.logger.info(f"CloudSender initialized for {website_url}")

    def create_traffic(self, interactor: PageInteractor, button_data: dict):
        self.logger.info("Running Cloud-specific traffic logic...")

        # Assumes config service maps "play_button" to the file input
        # and "shadow_button" to the submit button.
        file_input_selector = button_data.get("play_button")
        submit_button_selector = button_data.get("shadow_button")

        # Upload the file. This method handles all the logic.
        interactor.upload_file(file_input_selector, submit_button_selector)

        # 2Wait for upload to process
        self.logger.info(f"Waiting {self.wait_time} seconds for upload to process...")
        time.sleep(self.wait_time)
        self.logger.info("Cloud simulation complete.")