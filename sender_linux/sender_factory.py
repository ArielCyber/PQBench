import logging
from typing import Type

from attributes.video_sender import VideoSender
from attributes.rtt_sender import RTTSender
from attributes.map_sender import MapSender
from attributes.game_sender import GameSender
from attributes.download_sender import DownloadSender
from attributes.cloud_sender import CloudSender
from attributes.browser_sender import BrowserSender
from attributes.audio_sender import AudioSender
from sender import Sender


class SenderFactory:
    """
    A Factory class to instantiate specific Sender classes based on an attribute string.
    """

    # A dictionary mapping lowercase attribute names to their classes.
    # This is efficient (O(1) lookup) and easy to maintain.
    _SENDER_MAP = {
        "video": VideoSender,
        "rtt": RTTSender,
        "map": MapSender,
        "game": GameSender,
        "download": DownloadSender,
        "cloud": CloudSender,
        "browsing": BrowserSender,
        "audio": AudioSender
    }

    @staticmethod
    def create_sender(attribute: str, browser: str, algo: int, sessions: int, website_url: str) -> Sender:
        """
        Creates and returns an instance of the appropriate Sender subclass.
        """
        logger = logging.getLogger("SenderFactory")

        # Normalize input
        key = attribute.lower() if attribute else ""

        # Lookup the class in the map
        sender_class = SenderFactory._SENDER_MAP.get(key)

        # Handle unknown attributes (Default logic)
        if not sender_class:
            logger.warning(f"Unknown attribute: '{attribute}'. Defaulting to VideoSender.")
            sender_class = VideoSender

        # Instantiate and return the object
        logger.debug(f"Factory creating instance of {sender_class.__name__}")
        return sender_class(
            browser=browser,
            algo=algo,
            sessions=sessions,
            website_url=website_url
        )