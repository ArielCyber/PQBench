import json


class PageScanner:
    # --- 1. GENERIC CLICKER (Precision Single-Click) ---
    @staticmethod
    def get_click_logic_js(search_term):
        safe_search = search_term.replace('"', '\\"').lower()
        return f"""
        (function() {{
            const searchRaw = "{safe_search}";
            const search = searchRaw.replace(/\\s+/g, ' ').trim();

            function flash(el, color) {{
                try {{
                    const originalOutline = el.style.outline;
                    el.style.outline = "5px solid " + color;
                    el.style.zIndex = "2147483647";
                    setTimeout(() => {{ el.style.outline = originalOutline; }}, 1000);
                }} catch(e) {{}}
            }}

            function isTarget(el) {{
                const r = el.getBoundingClientRect();

                const allowedZeroSize = ['AUDIO', 'VIDEO', 'A', 'BUTTON'];
                if (!allowedZeroSize.includes(el.tagName) && (r.width === 0 || r.height === 0)) return false;

                if (el.innerText && el.innerText.toLowerCase().includes(search)) return true;
                if (el.className && typeof el.className === 'string' && el.className.toLowerCase().includes(search)) return true;
                if (el.id && el.id.toLowerCase().includes(search)) return true;
                if (el.getAttribute('aria-label') && el.getAttribute('aria-label').toLowerCase().includes(search)) return true;
                if (el.getAttribute('title') && el.getAttribute('title').toLowerCase().includes(search)) return true;

                return false;
            }}

            function triggerEvents(target) {{
                console.log("Triggering click on:", target);
                try {{
                    if (target.tagName === 'AUDIO' || target.tagName === 'VIDEO') {{
                        target.play();
                        return true;
                    }}
                    if (target.focus) target.focus();

                    const rect = target.getBoundingClientRect();
                    const centerX = rect.left + (rect.width / 2);
                    const centerY = rect.top + (rect.height / 2);

                    const opts = {{ 
                        bubbles: true, cancelable: true, view: window, buttons: 1,
                        clientX: centerX, clientY: centerY,
                        pointerId: 1, pointerType: 'mouse', isPrimary: true
                    }};

                    target.dispatchEvent(new PointerEvent('pointerdown', opts));
                    target.dispatchEvent(new MouseEvent('mousedown', opts));
                    target.dispatchEvent(new PointerEvent('pointerup', opts));
                    target.dispatchEvent(new MouseEvent('mouseup', opts));
                    target.click(); 
                    return true;
                }} catch(e) {{ return false; }}
            }}

            function attemptClick(el) {{
                flash(el, '#00FF00');
                if (['DIV', 'SPAN', 'A', 'BUTTON'].includes(el.tagName)) {{
                    const iconChild = el.querySelector('img, svg, path');
                    if (iconChild) return triggerEvents(iconChild);
                }}
                return triggerEvents(el);
            }}

            function scanAndClick(root) {{
                const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
                while(walker.nextNode()) {{
                    const el = walker.currentNode;
                    if (el.tagName === 'IFRAME') {{
                        try {{
                            const inner = el.contentDocument || el.contentWindow.document;
                            if (inner && scanAndClick(inner)) return true;
                        }} catch(e) {{}}
                        continue;
                    }}
                    if (isTarget(el)) {{
                        const style = window.getComputedStyle(el);
                        const isInteractiveTag = ['BUTTON', 'A', 'INPUT', 'AUDIO', 'VIDEO'].includes(el.tagName);
                        const hasPointer = style.cursor === 'pointer';
                        const hasRole = el.getAttribute('role') === 'button';
                        const classMatches = (el.className && typeof el.className === 'string' && el.className.toLowerCase().includes(search));
                        const idMatches = (el.id && el.id.toLowerCase().includes(search));

                        if (isInteractiveTag || hasPointer || hasRole || idMatches || classMatches) {{
                            return attemptClick(el);
                        }}
                    }}
                    if (el.shadowRoot) {{
                        if (scanAndClick(el.shadowRoot)) return true;
                    }}
                }}
                return false;
            }}

            if (scanAndClick(document)) return JSON.stringify({{status: "clicked", location: "main"}});
            return JSON.stringify({{status: "not_found"}});
        }})()
        """

    # --- 2. AUDIO SCANNER (Updated: Detects ID-based Pause buttons) ---
    @staticmethod
    def get_audio_scan_js():
        return """
        (function() {
            function flash(el, color) {
                try {
                    const originalOutline = el.style.outline;
                    el.style.outline = "5px solid " + color;
                    el.style.zIndex = "2147483647";
                    setTimeout(() => { el.style.outline = originalOutline; }, 1000);
                } catch(e) {}
            }

            function attemptClick(el) {
                flash(el, '#00FF00'); 
                try {
                    const rect = el.getBoundingClientRect();
                    const centerX = rect.left + (rect.width / 2);
                    const centerY = rect.top + (rect.height / 2);
                    const opts = { 
                        bubbles: true, cancelable: true, view: window, buttons: 1,
                        clientX: centerX, clientY: centerY,
                        pointerId: 1, pointerType: 'mouse', isPrimary: true
                    };
                    el.dispatchEvent(new PointerEvent('pointerdown', opts));
                    el.dispatchEvent(new MouseEvent('mousedown', opts));
                    el.dispatchEvent(new PointerEvent('pointerup', opts));
                    el.dispatchEvent(new MouseEvent('mouseup', opts));
                    el.click();
                    return true;
                } catch (e) { return false; }
            }

            function isActuallyPause(el) {
                const label = (el.getAttribute('aria-label') || "").toLowerCase();
                const title = (el.getAttribute('title') || "").toLowerCase();
                const text = el.innerText.trim().toLowerCase();
                const testId = (el.getAttribute('data-testid') || "").toLowerCase();
                const id = (el.id || "").toLowerCase();
                const cls = (typeof el.className === 'string' ? el.className : "").toLowerCase();

                // 1. Explicit Attributes
                if (label === 'pause' || title === 'pause' || text === 'pause') return true;
                if (testId.includes('pause') && !testId.includes('play')) return true;

                // 2. ID/Class Check (Newgrounds uses id="audio-listen-pause")
                if (id.includes('pause') && !id.includes('play-pause')) return true;
                if (cls.includes('pause') && !cls.includes('play')) return true;

                // 3. Icon Check (FontAwesome, Material, SVG)
                // Look for 'fa-pause', 'mdi-av-pause', or 2-bar SVGs
                if (el.innerHTML.toLowerCase().includes('pause')) return true;

                const svgs = el.querySelectorAll('svg');
                for (let svg of svgs) {
                    if (svg.getAttribute('aria-label') === 'Pause') return true;
                    const paths = svg.querySelectorAll('path, rect');
                    if (paths.length >= 2) return true; 
                }
                return false;
            }

            function isPlaying(root) {
                // 1. Search for Visible Pause Buttons
                // (Updated to check IDs and classes, not just aria-labels)
                const pauseCandidates = root.querySelectorAll('button, a, [role="button"], div');
                for (let el of pauseCandidates) {
                    if (el.offsetWidth > 0 && el.offsetHeight > 0) {
                        if (isActuallyPause(el)) return true;
                    }
                }

                // 2. Check Audio Tags
                const audios = root.querySelectorAll('audio');
                for (let audio of audios) {
                    if (!audio.paused && audio.currentTime > 0) return true;
                    if (audio.networkState === 2 || audio.readyState >= 1) return true; 
                }

                // 3. Check Title
                if (document.title.includes('▶') || document.title.toLowerCase().includes('playing')) return true;
                return false;
            }

            function findAndClickPlay(root) {
                const selectors = [
                    'button[aria-label*="Play" i]', 'button[title*="Play" i]',
                    'a[aria-label*="Play" i]', 'a[title*="Play" i]',
                    '[role="button"][aria-label*="Play" i]',
                    '.play-button', '.btn-play', '.player-control-play', 
                    'button[data-testid*="play"]',
                    'button', 'a', '[role="button"]', 'div.play-btn' 
                ];

                for (let sel of selectors) {
                    const candidates = root.querySelectorAll(sel);
                    for (let el of candidates) {
                        // Allow 0-width for anchors acting as icon containers
                        if (el.tagName !== 'A' && (el.offsetWidth === 0 || el.offsetHeight === 0)) continue;

                        if (['button', 'a', '[role="button"]'].includes(sel)) {
                            const t = (el.innerText + el.id + el.className).toLowerCase();
                            // Stricter check: Must look like a player control
                            if (!t.includes('play') && !t.includes('listen') && !t.includes('start')) continue;
                        }

                        // CRITICAL: Double check we aren't clicking a pause button
                        if (isActuallyPause(el)) continue;

                        return attemptClick(el);
                    }
                }
                return false;
            }

            if (isPlaying(document)) return JSON.stringify({status: "playing"});
            if (findAndClickPlay(document)) return JSON.stringify({status: "clicked"});

            const iframes = document.querySelectorAll('iframe');
            for (let iframe of iframes) {
                try {
                    const inner = iframe.contentDocument || iframe.contentWindow.document;
                    if (inner) {
                        if (isPlaying(inner)) return JSON.stringify({status: "playing"});
                        if (findAndClickPlay(inner)) return JSON.stringify({status: "clicked"});
                    }
                } catch(e) {}
            }
            return JSON.stringify({status: "searching"});
        })()
        """

    @staticmethod
    def get_video_scan_js():
        return """
        (function() {
            const video = document.querySelector('video');
            if(video) {
                const r = video.getBoundingClientRect();
                return JSON.stringify({ type: 'video', x: r.x + r.width/2, y: r.y + r.height/2 });
            }
            return null;
        })()
        """