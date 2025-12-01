import asyncio
import json
import nodriver as uc
from config import logger
from cursor import HumanCursor
from scanner import PageScanner
from strategies import StrategyFactory


class AutomationEngine:
    def __init__(self, domain, attribute, target_button=None):
        self.domain = domain if domain.startswith("http") else f"https://{domain}"
        self.attribute = attribute
        self.target_button = target_button
        self.browser = None
        self.tab = None

    async def run(self):
        try:
            self.browser = await uc.start()
            self.tab = await self.browser.get(self.domain)
            cursor = HumanCursor(self.tab)

            logger.info(f"Visiting {self.domain} with mode: {self.attribute}")
            await asyncio.sleep(5)

            # --- 1. HANDLE TARGET BUTTONS (List Support) ---
            if self.target_button:
                # Split by comma to support multiple buttons: "cookie-btn,play-btn"
                targets = [t.strip() for t in self.target_button.split(',')]

                for i, target in enumerate(targets):
                    if not target: continue

                    logger.info(f"Processing Target {i + 1}/{len(targets)}: '{target}'")
                    success = await self._hunt_and_destroy_button(cursor, specific_target=target)

                    if success:
                        logger.info(f"Target '{target}' handled. Waiting 2s before next action...")
                        await asyncio.sleep(2)
                    else:
                        logger.warning(f"Target '{target}' was not found or failed.")

            # --- 2. EXECUTE STRATEGY ---
            strategy = StrategyFactory.get_strategy(self.attribute, self.tab, cursor)
            await strategy.execute()

            logger.info("Session finished successfully.")

        except Exception as e:
            logger.error(f"Engine Error: {e}")
        finally:
            if self.browser:
                try:
                    await self.browser.stop()
                except Exception:
                    pass

    async def _hunt_and_destroy_button(self, cursor, specific_target):
        """
        Hunts for a specific button string (Text, Class, ID, Aria).
        """
        logger.info(f"Deep Searching & Clicking: '{specific_target}'")

        # Generate JS using the specific target from the loop
        js = PageScanner.get_click_logic_js(specific_target)

        start_time = asyncio.get_event_loop().time()

        # Try for up to 20 seconds per button
        while (asyncio.get_event_loop().time() - start_time) < 20:
            try:
                result_str = await self.tab.evaluate(js)
                if result_str:
                    data = json.loads(result_str)

                    if data.get("status") == "clicked":
                        logger.info(f"Target '{specific_target}' destroyed in {data.get('location')}.")
                        # Wait briefly for page reaction (modal close, navigation, etc.)
                        await asyncio.sleep(2)
                        return True

            except Exception:
                pass

            # Retry every second
            await asyncio.sleep(1)

        logger.warning(f"Time limit reached hunting button: {specific_target}")
        return False