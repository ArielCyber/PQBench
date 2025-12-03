import asyncio
import os
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
        """Scrolls down gently to simulate reading/viewing."""
        for _ in range(3):
            # Scroll a random amount
            await self.tab.evaluate(f"window.scrollBy(0, {random.randint(300, 700)})")
            await asyncio.sleep(1.5)


class BrowserStrategy(AutomationStrategy):
    async def execute(self):
        logger.info("Strategy: BROWSER (Multi-Step)")

        # How many pages/links to visit?
        steps_to_perform = 3

        for i in range(steps_to_perform):
            logger.info(f"Browser Action {i + 1}/{steps_to_perform}")

            try:
                # 1. Scroll to look like a human reading
                await self._scroll_reading()

                # 2. Re-scan the CURRENT page for links/buttons
                # We must do this every loop because the previous click might have changed the page.
                links = await self.tab.select_all("a[href]")

                if not links:
                    logger.warning("No links found on this page. Stopping browser strategy.")
                    break

                # 3. Pick a random target
                # We shuffle or pick random to simulate browsing
                target = random.choice(links)

                # Optional: log what we are clicking (if it has text)
                # text = await target.get_text()
                # logger.info(f"Clicking link...")

                # 4. Click
                await target.click()

                # 5. WAIT FOR NAVIGATION
                # This is crucial. If the page changes, we need to wait for it to load
                # before the next loop iteration tries to scroll/scan.
                logger.info("Clicked. Waiting for potential page load...")
                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Error during browser step {i + 1}: {e}")
                # If a click failed (e.g. popup blocked, element covered), wait briefly and try next step
                await asyncio.sleep(2)

        logger.info("Browser strategy finished.")


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


class DownloadStrategy(AutomationStrategy):
    async def execute(self):
        logger.info("Strategy: DOWNLOAD")

        js_scan = PageScanner.get_download_scan_js()

        # Try a few times (scrolling in between) to find a download link
        for attempt in range(5):
            try:
                result_str = await self.tab.evaluate(js_scan)
                if result_str:
                    data = json.loads(result_str)
                    status = data.get("status")

                    if status == "clicked":
                        text = data.get('text') or "Icon"
                        logger.info(f"Clicked Download trigger: '{text}'.")

                        # Wait a significant amount of time for the download to initiate/finish
                        # (Browsers often handle the download in the background)
                        await asyncio.sleep(5)

                        # We return after one successful click to avoid downloading 50 files
                        return

            except Exception as e:
                logger.error(f"Download Strategy Error: {e}")

            # If nothing found, scroll down and try again
            logger.info("No download found yet, scrolling...")
            await self._scroll_reading()
            await asyncio.sleep(1)

        logger.warning("Could not find a download link or button.")

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

        # Ensure path is absolute (Critical for Chrome uploads)
        abs_path = os.path.abspath(UPLOAD_FILE_PATH)
        if not os.path.exists(abs_path):
            logger.error(f"Upload file not found at: {abs_path}")
            return

        js_scan = PageScanner.get_upload_scan_js()

        for attempt in range(5):
            try:
                # Run the scanner to find inputs or buttons
                result_str = await self.tab.evaluate(js_scan)
                if result_str:
                    data = json.loads(result_str)
                    status = data.get("status")

                    # CASE A: Input Exists (Hidden or Visible)
                    if status == "found_input":
                        logger.info("File input detected. Attempting upload via Raw CDP...")

                        try:
                            # USE RAW CDP (Most Robust)
                            # 1. Get the document root node
                            doc = await self.tab.send(uc.cdp.dom.get_document())

                            # 2. Find the file input node ID
                            node = await self.tab.send(uc.cdp.dom.query_selector(doc.node_id, "input[type='file']"))

                            if node:
                                # 3. Set the files directly on that node
                                # FIXED: Removed .node_id access, passing 'node' directly
                                await self.tab.send(uc.cdp.dom.set_file_input_files(files=[abs_path], node_id=node))
                                logger.info(f"Upload successful: {abs_path}")
                                await asyncio.sleep(5)
                                return
                            else:
                                logger.warning("CDP failed to locate the input element.")

                        except Exception as cdp_e:
                            logger.error(f"CDP Upload Error: {cdp_e}")

                    # CASE B: Clicked a Button ("Upload", "Import", etc)
                    elif status == "clicked_button":
                        logger.info(f"Clicked upload trigger: '{data.get('text')}'. Waiting for input to appear...")
                        await asyncio.sleep(2)
                        continue

            except Exception as e:
                logger.error(f"Cloud Strategy Error: {e}")

            await asyncio.sleep(1)

        logger.warning("Could not find a way to upload a file.")


class GameStrategy(AutomationStrategy):
    async def execute(self):
        logger.info("Strategy: GAME")

        # State tracking
        nickname_set = False
        play_clicked = False

        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < 40:
            try:
                # DYNAMIC SCANNER:
                # If we already set the nickname, tell scanner to IGNORE inputs and find the Play button.
                js_scan = PageScanner.get_game_scan_js(ignore_inputs=nickname_set)

                result_str = await self.tab.evaluate(js_scan)

                if not isinstance(result_str, str):
                    await asyncio.sleep(1)
                    continue

                data = json.loads(result_str)
                action_type = data.get("type")
                x = data.get("x", 0)
                y = data.get("y", 0)

                # 1. FOUND NICKNAME INPUT (Only if not set yet)
                if action_type == "nickname" and not nickname_set:
                    logger.info(f"Nickname input found at {x},{y}. Entering name...")

                    await self.cursor.click_via_cdp(x, y)
                    await asyncio.sleep(0.5)

                    await self.tab.send(uc.cdp.input_.insert_text(text="Player1"))
                    await asyncio.sleep(0.5)

                    # Press Enter
                    await self.tab.send(uc.cdp.input_.dispatch_key_event(type_="keyDown", windows_virtual_key_code=13))
                    await self.tab.send(uc.cdp.input_.dispatch_key_event(type_="keyUp", windows_virtual_key_code=13))

                    logger.info("Nickname submitted.")
                    nickname_set = True
                    # Reset play clicked to force looking for a play button now that we have a name
                    play_clicked = False
                    await asyncio.sleep(2)
                    continue

                # 2. FOUND PLAY BUTTON
                elif action_type == "play" and not play_clicked:
                    logger.info(f"Play button found at {x},{y}. Clicking...")
                    await self.cursor.click_via_cdp(x, y)
                    play_clicked = True
                    await asyncio.sleep(3)
                    continue

                # 3. GAME RUNNING (Canvas)
                elif action_type in ["canvas", "canvas_blind"]:

                    # PRIORITY CHECK:
                    # If we just set the nickname, we MUST find a Play button before accepting Canvas.
                    # We wait up to 15 seconds for a Play button to appear.
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if nickname_set and not play_clicked and elapsed < 20:
                        logger.info("Canvas found, but waiting for Play button (Sequence enforced)...")
                        await asyncio.sleep(1.5)
                        continue

                    # If we clicked play OR timed out waiting for it, assume game is ready
                    logger.info("Game active. Waiting 20s for graphics data...")
                    await self.cursor.move_to(x if x else 500, y if y else 400)
                    await asyncio.sleep(20)
                    logger.info("Graphics data collection period finished.")
                    return

                else:
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Game Strategy Error: {e}")
                await asyncio.sleep(1)

        logger.warning("Could not fully engage with the game.")

class StrategyFactory:
    @staticmethod
    def get_strategy(attribute_name, tab, cursor):
        strategies = {
            'browser': BrowserStrategy,
            'video': VideoStrategy,
            'audio': AudioStrategy,
            'map': MapStrategy,
            'download': DownloadStrategy,
            'cloud': CloudStrategy,
            'game': GameStrategy
        }
        strategy_class = strategies.get(attribute_name.lower(), BrowserStrategy)
        return strategy_class(tab, cursor)