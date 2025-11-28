import backoff
import tldextract
# Selenium Imports
import undetected_chromedriver as uc
# Playwright Imports
from playwright.sync_api import sync_playwright
import os
from attributes.audio_sender import AudioSender
from attributes.browser_sender import BrowserSender
from attributes.cloud_sender import CloudSender
from attributes.download_sender import DownloadSender
from attributes.game_sender import GameSender
from attributes.map_sender import MapSender
from attributes.rtt_sender import RTTSender
from attributes.video_sender import VideoSender
from sender import Sender


class SenderFactory:
    @staticmethod
    def create_sender(attribute: str, browser_str: str, sessions: int, website_url: str, algo: int) -> Sender:
        wait_time = int(os.getenv('DEFAULT_WAIT_TIME', 15))  # Default wait time, could be passed in
        attr_lower = attribute.lower()

        if "video" in attr_lower:
            return VideoSender(attribute, browser_str, sessions, website_url, wait_time, algo)
        elif "audio" in attr_lower:
            return AudioSender(attribute, browser_str, sessions, website_url, wait_time, algo)
        elif "game" in attr_lower:
            return GameSender(attribute, browser_str, sessions, website_url, wait_time, algo)
        elif "map" in attr_lower:
            return MapSender(attribute, browser_str, sessions, website_url, wait_time, algo)
        elif "rtt" in attr_lower:
            return RTTSender(attribute, browser_str, sessions, website_url, wait_time, algo)
        elif "download" in attr_lower:
            return DownloadSender(attribute, browser_str, sessions, website_url, wait_time, algo)
        elif "cloud" in attr_lower:
            return CloudSender(attribute, browser_str, sessions, website_url, wait_time, algo)
        elif "browser" in attr_lower:
            return BrowserSender(attribute, browser_str, sessions, website_url, wait_time, algo)
        else:
            # Default to BrowserSender if unknown
            print(f"[W] Unknown attribute '{attribute}', defaulting to BrowserSender.")
            return BrowserSender(attribute, browser_str, sessions, website_url, wait_time)