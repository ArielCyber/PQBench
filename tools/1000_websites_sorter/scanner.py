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
    def get_upload_scan_js():
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

                // 1. Check for File Input (Visible or Hidden)
                const inputs = document.querySelectorAll('input[type="file"]');
                if (inputs.length > 0) {
                    // If we found an input, we return true so Python knows to try uploading
                    return JSON.stringify({status: "found_input"});
                }

                // 2. Hunt for "Upload" Buttons
                // Keywords to look for in buttons/links
                const keywords = ['upload', 'import', 'select file', 'choose file', 'add file', 'browse'];

                function isUploadButton(el) {
                    if (el.offsetWidth === 0 || el.offsetHeight === 0) return false;

                    const text = (el.innerText || "").toLowerCase().trim();
                    const label = (el.getAttribute('aria-label') || "").toLowerCase();
                    const title = (el.getAttribute('title') || "").toLowerCase();

                    // Check keywords
                    return keywords.some(k => text.includes(k) || label.includes(k) || title.includes(k));
                }

                const candidates = document.querySelectorAll('button, a, div[role="button"], span[role="button"], input[type="button"], input[type="submit"]');

                for (let el of candidates) {
                    if (isUploadButton(el)) {
                        console.log("Found Upload Button:", el);
                        flash(el, '#00FF00');

                        // Click it to trigger the dialog or create the input
                        try {
                            el.click();
                            const opts = { bubbles: true, cancelable: true, view: window, buttons: 1 };
                            el.dispatchEvent(new MouseEvent('mousedown', opts));
                            el.dispatchEvent(new MouseEvent('mouseup', opts));
                            return JSON.stringify({status: "clicked_button", text: el.innerText});
                        } catch(e) {}
                    }
                }

                return JSON.stringify({status: "searching"});
            })()
            """

    @staticmethod
    def get_download_scan_js():
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

                function triggerEvents(target) {
                    console.log("Triggering download on:", target);
                    try {
                        const rect = target.getBoundingClientRect();
                        const centerX = rect.left + (rect.width / 2);
                        const centerY = rect.top + (rect.height / 2);

                        const opts = { 
                            bubbles: true, cancelable: true, view: window, buttons: 1,
                            clientX: centerX, clientY: centerY,
                            pointerId: 1, pointerType: 'mouse', isPrimary: true
                        };

                        target.dispatchEvent(new PointerEvent('pointerdown', opts));
                        target.dispatchEvent(new MouseEvent('mousedown', opts));
                        target.dispatchEvent(new PointerEvent('pointerup', opts));
                        target.dispatchEvent(new MouseEvent('mouseup', opts));
                        target.click(); 
                        return true;
                    } catch(e) { return false; }
                }

                function attemptClick(el) {
                    flash(el, '#00FF00');
                    // Smart Targeting: Click icon child if parent is a generic container
                    if (['DIV', 'SPAN', 'A', 'BUTTON'].includes(el.tagName)) {
                        const iconChild = el.querySelector('img, svg, path');
                        if (iconChild) return triggerEvents(iconChild);
                    }
                    return triggerEvents(el);
                }

                // --- DOWNLOAD HEURISTICS ---
                function isDownloadButton(el) {
                    if (el.offsetWidth === 0 || el.offsetHeight === 0) return false;

                    // 1. Explicit 'download' attribute (Strongest signal)
                    if (el.hasAttribute('download')) return true;

                    // 2. File Extensions in HREF
                    if (el.tagName === 'A' && el.href) {
                        const ext = el.href.split('.').pop().toLowerCase().split('?')[0];
                        const commonExts = ['zip', 'exe', 'dmg', 'iso', 'pdf', 'csv', 'apk', 'msi', 'tar', 'gz', '7z', 'rar'];
                        if (commonExts.includes(ext)) return true;
                    }

                    // 3. Keywords in Text or Title
                    const text = (el.innerText || "").toLowerCase().trim();
                    const title = (el.getAttribute('title') || "").toLowerCase();
                    const label = (el.getAttribute('aria-label') || "").toLowerCase();
                    const combined = text + " " + title + " " + label;

                    const keywords = ['download', 'save file', 'export data', 'get app', 'installer'];
                    if (keywords.some(k => combined.includes(k))) return true;

                    return false;
                }

                // Scan relevant elements
                const candidates = document.querySelectorAll('a, button, [role="button"], input[type="button"], input[type="submit"]');

                for (let el of candidates) {
                    if (isDownloadButton(el)) {
                        return JSON.stringify({status: "clicked", text: (el.innerText || "icon")});
                        // Note: We return immediately after finding/clicking ONE to avoid spamming multiple downloads
                        // The strategy loop will handle finding more if needed.
                    }
                }

                return JSON.stringify({status: "searching"});
            })()
            """

    @staticmethod
    def get_game_scan_js(ignore_inputs=False):
        # Python bool to JS bool string
        js_ignore_flag = "true" if ignore_inputs else "false"

        return f"""
            (function() {{
                try {{
                    const ignoreInputs = {js_ignore_flag};

                    // --- HELPERS ---
                    function isVisible(el) {{
                        if (!el) return false;
                        const r = el.getBoundingClientRect();
                        return r.width > 20 && r.height > 20 && 
                               window.getComputedStyle(el).visibility !== 'hidden' &&
                               window.getComputedStyle(el).display !== 'none';
                    }}

                    function flash(el, color) {{
                        try {{
                            el.style.outline = "5px solid " + color;
                            el.style.zIndex = "2147483647";
                        }} catch(e) {{}}
                    }}

                    function scanRoot(root) {{
                        // 1. LOOK FOR NICKNAME INPUT (Only if ignoreInputs is false)
                        if (!ignoreInputs) {{
                            const inputs = root.querySelectorAll('input');
                            for (let el of inputs) {{
                                const type = (el.type || "").toLowerCase();
                                // Skip non-text types
                                if (['checkbox', 'radio', 'button', 'submit', 'hidden', 'file', 'image', 'reset', 'range', 'color'].includes(type)) continue;

                                if (!isVisible(el)) continue;

                                // Skip if disabled/readonly
                                if (el.disabled || el.readOnly) continue;

                                const attr = (
                                    (el.name || "") + " " + (el.id || "") + " " + 
                                    (el.placeholder || "") + " " + (el.getAttribute('aria-label') || "") + " " + (el.className || "")
                                ).toLowerCase();

                                // Broad Check: If it looks like a nickname/login field
                                // or if it's just a generic text input on a game site
                                const isNick = ['nick', 'name', 'player', 'guest', 'login', 'user'].some(k => attr.includes(k));
                                const isSearch = attr.includes('search') || attr.includes('query');
                                const isPass = attr.includes('pass');

                                if ((isNick || inputs.length < 3) && !isSearch && !isPass) {{
                                    flash(el, '#0000FF');
                                    const r = el.getBoundingClientRect();
                                    return {{
                                        type: "nickname", 
                                        x: r.left + r.width/2, 
                                        y: r.top + r.height/2
                                    }};
                                }}
                            }}
                        }}

                        // 2. LOOK FOR PLAY BUTTON
                        // Broad selector for anything clickable
                        const buttons = root.querySelectorAll('button, a, div, span, input[type="button"], input[type="submit"], img, svg');

                        for (let el of buttons) {{
                            if (!isVisible(el)) continue;

                            // Check keywords in text, class, id, aria
                            const text = (el.innerText || "").toLowerCase().trim();
                            const label = (el.getAttribute('aria-label') || "").toLowerCase();
                            const title = (el.getAttribute('title') || "").toLowerCase();
                            const cls = (el.getAttribute('class') || "").toLowerCase();
                            const id = (el.id || "").toLowerCase();

                            const combined = text + " " + label + " " + title + " " + cls + " " + id;

                            // Keywords for starting a game
                            const playKeywords = ['play', 'start', 'join', 'go!', 'enter', 'ready', 'battle', 'fight'];

                            if (playKeywords.some(k => combined.includes(k))) {{
                                // Filter out "Google Play", "App Store", "Video Player" controls if possible
                                if (combined.includes('google') || combined.includes('store') || combined.includes('android') || combined.includes('ios')) continue;

                                // If it's a div/span/img, ensure it looks interactive (cursor pointer or role button)
                                const style = window.getComputedStyle(el);
                                if (['DIV', 'SPAN', 'IMG', 'SVG'].includes(el.tagName)) {{
                                    if (style.cursor !== 'pointer' && el.getAttribute('role') !== 'button' && !cls.includes('btn') && !cls.includes('button')) {{
                                        continue; 
                                    }}
                                }}

                                flash(el, '#00FF00');
                                const r = el.getBoundingClientRect();
                                return {{
                                    type: "play", 
                                    x: r.left + r.width/2, 
                                    y: r.top + r.height/2
                                }};
                            }}
                        }}

                        // 3. LOOK FOR GAME CANVAS
                        const canvas = root.querySelector('canvas');
                        if (canvas && isVisible(canvas)) {{
                            const r = canvas.getBoundingClientRect();
                            return {{
                                type: "canvas",
                                x: r.left + r.width/2,
                                y: r.top + r.height/2
                            }};
                        }}

                        return null;
                    }}

                    // --- MAIN EXECUTION ---

                    let res = scanRoot(document);
                    if (res) return JSON.stringify(res);

                    const iframes = document.querySelectorAll('iframe');
                    for (let iframe of iframes) {{
                        try {{
                            const inner = iframe.contentDocument || iframe.contentWindow.document;
                            if (inner) {{
                                res = scanRoot(inner);
                                if (res) {{
                                    const frameRect = iframe.getBoundingClientRect();
                                    res.x += frameRect.left;
                                    res.y += frameRect.top;
                                    return JSON.stringify(res);
                                }}
                            }}
                        }} catch(e) {{
                            // Fallback: If blocked iframe is massive, assume it's the game canvas
                            const r = iframe.getBoundingClientRect();
                            if (r.width > 600 && r.height > 400) {{
                                return JSON.stringify({{
                                    type: "canvas_blind",
                                    x: r.left + r.width/2,
                                    y: r.top + r.height/2
                                }});
                            }}
                        }}
                    }}

                    return JSON.stringify({{type: "searching"}});

                }} catch(e) {{
                    return JSON.stringify({{type: "error", msg: e.toString()}});
                }}
            }})()
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