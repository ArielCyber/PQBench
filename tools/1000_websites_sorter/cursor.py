import asyncio
import random
import json
from config import logger


class HumanCursor:
    def __init__(self, tab):
        self.tab = tab

    async def _send_cdp(self, cmd_dict):
        try:
            await self.tab.send(cmd_dict)
        except Exception:
            try:
                if self.tab.connection.websocket:
                    await self.tab.connection.websocket.send(json.dumps(cmd_dict))
            except Exception:
                pass

    async def move_to(self, x, y):
        # Simply move without path generation for the final click to ensure precision
        await self._send_cdp({
            "method": "Input.dispatchMouseEvent",
            "params": {"type": "mouseMoved", "x": int(x), "y": int(y)}
        })

    async def click_via_cdp(self, x, y):
        """
        Aggressive Physical Click:
        1. Teleport (No jitter)
        2. Press
        3. Release
        4. Explicit 'Click' event
        """
        ix, iy = int(x), int(y)
        logger.info(f"Physical CDP Click at {ix}, {iy}")

        # 1. Hover
        await self._send_cdp({
            "method": "Input.dispatchMouseEvent",
            "params": {"type": "mouseMoved", "x": ix, "y": iy}
        })
        await asyncio.sleep(0.1)

        # 2. Mouse Down
        await self._send_cdp({
            "method": "Input.dispatchMouseEvent",
            "params": {"type": "mousePressed", "x": ix, "y": iy, "button": "left", "clickCount": 1}
        })
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # 3. Mouse Up
        await self._send_cdp({
            "method": "Input.dispatchMouseEvent",
            "params": {"type": "mouseReleased", "x": ix, "y": iy, "button": "left", "clickCount": 1}
        })

        # 4. Explicit Click (Helps with some frameworks)
        # Note: 'mousePressed' and 'mouseReleased' usually generate a click, but this forces it for some CDP implementations
        try:
            await self._send_cdp({
                "method": "Input.dispatchMouseEvent",
                "params": {"type": "click", "x": ix, "y": iy, "button": "left", "clickCount": 1}
            })
        except:
            pass  # Some CDP versions don't support 'click' type directly, safe to ignore

    async def click_via_js(self, x, y):
        """
        JS Click attempts to click the element at x,y.
        Note: This often fails for cross-origin iframes.
        """
        logger.info(f"JS Click fallback at {x}, {y}")
        js = f"""
        (function() {{
            const el = document.elementFromPoint({x}, {y});
            if (el) {{
                el.click();
                const opts = {{ bubbles: true, cancelable: true, view: window, buttons: 1 }};
                el.dispatchEvent(new MouseEvent('mousedown', opts));
                el.dispatchEvent(new MouseEvent('mouseup', opts));
            }}
        }})()
        """
        await self.tab.evaluate(js)
