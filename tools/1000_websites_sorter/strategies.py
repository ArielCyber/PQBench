import asyncio
import random
import json
import nodriver as uc
from abc import ABC, abstractmethod
from config import logger, UPLOAD_FILE_PATH
from scanner import PageScanner


class AutomationStrategy(ABC):
    def __init__(self, tab, cursor):
        self.tab = tab
        self.cursor = cursor

    @abstractmethod
    async def execute(self):
        pass

    async def _scroll_reading(self):
        for _ in range(3):
            await self.tab.evaluate(f"window.scrollBy(0, {random.randint(300, 700)})")
            await asyncio.sleep(2)


class BrowserStrategy(AutomationStrategy):
    async def execute(self):
        logger.info("Strategy: BROWSER")
        await self._scroll_reading()
        links = await self.tab.select_all("a[href]")
        if links:
            target = random.choice(links[:5])
            await target.click()
            await asyncio.sleep(5)


class AudioStrategy(AutomationStrategy):
    async def execute(self):
        logger.info("Strategy: AUDIO")
        await asyncio.sleep(3)

        js = PageScanner.get_audio_scan_js()

        # ONE-SHOT POLICY: We only try to click ONCE to avoid the "Play -> Pause" loop.
        for i in range(5):
            try:
                result_str = await self.tab.evaluate(js)
                if result_str:
                    data = json.loads(result_str)
                    status = data.get("status")

                    if status == "playing":
                        logger.info("Audio detected playing. Hovering...")
                        await self.cursor.move_to(500, 400)
                        return

                    if status == "clicked":
                        logger.info("Clicked Play button. Waiting for stream...")

                        # Wait for buffer (10s)
                        await asyncio.sleep(10)

                        # Check status one last time for logging
                        try:
                            check_str = await self.tab.evaluate(js)
                            if check_str and json.loads(check_str).get("status") == "playing":
                                logger.info("Playback confirmed.")
                            else:
                                logger.info("Playback assumed (detection is tricky on this site).")
                        except:
                            pass

                        # EXIT IMMEDIATELY - Do not loop again
                        return

            except Exception as e:
                pass

            await asyncio.sleep(1.5)

        logger.warning("Could not interact with audio player.")


class VideoStrategy(AutomationStrategy):
    async def execute(self):
        logger.info("Strategy: VIDEO")
        await asyncio.sleep(5)
        js = PageScanner.get_video_scan_js()
        result = await self.tab.evaluate(js)
        if result and "video" in result:
            logger.info("Video found, interacting...")


class MapStrategy(AutomationStrategy):
    async def execute(self):
        logger.info("Strategy: MAP")
        await self.cursor.zoom_via_js(500, 500, 300)


class CloudStrategy(AutomationStrategy):
    async def execute(self):
        logger.info("Strategy: CLOUD")
        try:
            file_input = await self.tab.select("input[type='file']")
            if file_input:
                await file_input.send_files(UPLOAD_FILE_PATH)
        except Exception as e:
            logger.error(f"Upload failed: {e}")


class StrategyFactory:
    @staticmethod
    def get_strategy(attribute_name, tab, cursor):
        strategies = {
            'browser': BrowserStrategy,
            'video': VideoStrategy,
            'audio': AudioStrategy,
            'map': MapStrategy,
            'cloud': CloudStrategy,
            'game': BrowserStrategy
        }
        strategy_class = strategies.get(attribute_name.lower(), BrowserStrategy)
        return strategy_class(tab, cursor)