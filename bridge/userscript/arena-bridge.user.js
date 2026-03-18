// ==UserScript==
// @name         Arena Bridge
// @namespace    http://localhost:7823
// @version      14.0.0
// @description  Bridges arena.ai to your local LMArena Bridge server
// @author       LMArena Bridge
// @match        https://arena.ai/*
// @match        https://lmarena.ai/*
// @grant        unsafeWindow
// @run-at       document-start
// ==/UserScript==

(function () {
    'use strict';

    const WS_URL    = 'ws://127.0.0.1:7823';
    const VERSION   = '14.0.0';
    const ARENA_URL = 'https://arena.ai/nextjs-api/stream/create-evaluation';
    // Sitekey discovered dynamically — do not hardcode
    let SITEKEY = null;

    // ── State ──────────────────────────────────────────────────────────────────
    let ws           = null;
    let wsReady      = false;
    let lastToken    = null;
    let tokenAge     = 0;
    let reconnectT   = null;
    let badge        = null;
    let modelUUIDs   = {};

    // ── Capture window.fetch BEFORE any framework loads ────────────────────────
    const _origFetch = (unsafeWindow || window).fetch.bind(unsafeWindow || window);

    // Hook fetch to intercept tokens and UUIDs from Arena's own requests
    const _hookedFetch = function (url, opts) {
        const urlStr = typeof url === 'string' ? url : (url && url.url ? url.url : String(url));

        if (urlStr.includes('/nextjs-api/stream/')) {
            try {
                const body = opts && opts.body;
                if (typeof body === 'string') {
                    const parsed = JSON.parse(body);

                    // Steal reCAPTCHA token from Arena's own requests
                    if (parsed.recaptchaV3Token && parsed.recaptchaV3Token.length > 50) {
                        lastToken = parsed.recaptchaV3Token;
                        tokenAge  = Date.now();
                        sendWS({ type: 'recaptcha_token', token: lastToken });
                        updateBadge();
                        // Also try to discover sitekey now that page is active
                        if (!SITEKEY) discoverSitekey();
                    }

                    // Capture model UUID
                    if (parsed.modelAId && parsed.modelAId.length === 36) {
                        tryMapUUID(parsed.modelAId);
                    }
                }
            } catch (_) {}
        }

        return _origFetch(url, opts);
    };

    try {
        (unsafeWindow || window).fetch = _hookedFetch;
    } catch (_) {
        window.fetch = _hookedFetch;
    }

    // ── Discover reCAPTCHA sitekey from the page ───────────────────────────────
    function discoverSitekey() {
        try {
            // Method 1: scan script tags for the sitekey pattern
            const scripts = document.querySelectorAll('script[src]');
            for (const s of scripts) {
                const m = s.src.match(/[?&]render=([^&]+)/);
                if (m) { SITEKEY = m[1]; return SITEKEY; }
            }
            // Method 2: scan inline scripts
            const inlines = document.querySelectorAll('script:not([src])');
            for (const s of inlines) {
                const m = s.textContent.match(/['"](6L[a-zA-Z0-9_-]{38})['"]/);
                if (m) { SITEKEY = m[1]; return SITEKEY; }
            }
            // Method 3: check grecaptcha internal config
            const g = (unsafeWindow || window).grecaptcha;
            if (g && g.enterprise && g.enterprise.getResponse) {
                // Some versions expose the sitekey
            }
            // Method 4: check __recaptchaScriptLoadedFor
            const win = unsafeWindow || window;
            if (win.__recaptchaScriptLoadedFor) {
                SITEKEY = win.__recaptchaScriptLoadedFor;
                return SITEKEY;
            }
            // Method 5: scan all script src for recaptcha enterprise key
            document.querySelectorAll('script').forEach(s => {
                if (s.src && s.src.includes('recaptcha')) {
                    const m = s.src.match(/render=([^&]+)/);
                    if (m) SITEKEY = m[1];
                }
                if (!s.src && s.textContent) {
                    const m = s.textContent.match(/execute\(['"]([^'"]{20,})['"]/);
                    if (m) SITEKEY = m[1];
                }
            });
        } catch (e) {}
        return SITEKEY;
    }

    // ── Mint a fresh reCAPTCHA token using grecaptcha.enterprise ───────────────
    async function mintFreshToken(action) {
        action = action || 'chat_submit';
        // Discover sitekey if not known yet
        if (!SITEKEY) discoverSitekey();
        if (!SITEKEY) {
            sendWS({ type: 'debug', message: 'mintFreshToken: sitekey not discovered yet' });
            return null;
        }
        try {
            const g = (unsafeWindow || window).grecaptcha;
            if (g && g.enterprise && g.enterprise.execute) {
                const token = await g.enterprise.execute(SITEKEY, { action });
                if (token && token.length > 50) {
                    lastToken = token;
                    tokenAge  = Date.now();
                    sendWS({ type: 'recaptcha_token', token });
                    updateBadge();
                    return token;
                }
            }
            if (g && g.execute) {
                const token = await g.execute(SITEKEY, { action });
                if (token && token.length > 50) {
                    lastToken = token;
                    tokenAge  = Date.now();
                    sendWS({ type: 'recaptcha_token', token });
                    updateBadge();
                    return token;
                }
            }
        } catch (e) {
            sendWS({ type: 'debug', message: `mintFreshToken failed (key=${SITEKEY}): ${e.message}` });
        }
        return null;
    }

    // ── Wait for grecaptcha to be available on the page ────────────────────────
    function waitForGrecaptcha(timeoutMs) {
        timeoutMs = timeoutMs || 5000;
        return new Promise((resolve) => {
            const start = Date.now();
            const check = () => {
                const g = (unsafeWindow || window).grecaptcha;
                if (g && (g.execute || (g.enterprise && g.enterprise.execute))) {
                    resolve(g);
                } else if (Date.now() - start < timeoutMs) {
                    setTimeout(check, 200);
                } else {
                    resolve(null);
                }
            };
            check();
        });
    }

    // ── Get a fresh token for each request ─────────────────────────────────────
    async function getToken() {
        // Always try to mint a fresh token first (single-use tokens!)
        await waitForGrecaptcha(3000);
        const fresh = await mintFreshToken('chat_submit');
        if (fresh) return fresh;

        // Fall back to last intercepted token if recent enough (< 30s)
        if (lastToken && (Date.now() - tokenAge) < 30000) {
            sendWS({ type: 'debug', message: 'Using intercepted token as fallback' });
            return lastToken;
        }

        // Last resort — stale token
        if (lastToken) {
            sendWS({ type: 'debug', message: '⚠️ Using stale token — may fail' });
            return lastToken;
        }

        sendWS({ type: 'debug', message: '⚠️ No token available — send a message on arena.ai!' });
        return '';
    }

    // ── Parse Arena stream line → text or signal ───────────────────────────────
    function parseArenaLine(line) {
        line = line.trim();
        if (!line) return null;

        // a0:"text chunk"
        const textMatch = line.match(/^a\d+:"([\s\S]*)"$/);
        if (textMatch) {
            let text = textMatch[1];
            text = text.replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\').replace(/\\t/g, '\t');
            return text ? { type: 'text', text } : null;
        }

        // a2:[...] — arrays (heartbeat, webdev, etc.)
        const arrMatch = line.match(/^a\d+:(\[[\s\S]*\])$/);
        if (arrMatch) {
            try {
                const arr = JSON.parse(arrMatch[1]);
                let combined = '';
                for (const item of arr) {
                    if (!item) continue;
                    if (item.type === 'textDelta' && item.delta) combined += item.delta;
                    else if (item.type === 'text' && item.text) combined += item.text;
                    // heartbeat, webdev events → skip
                }
                return combined ? { type: 'text', text: combined } : null;
            } catch (_) { return null; }
        }

        // ad:{...} — finish
        if (line.startsWith('ad:')) return { type: 'done' };

        // 3:"error"
        const errMatch = line.match(/^3:"([\s\S]*)"$/);
        if (errMatch) return { type: 'error', text: errMatch[1] };

        return null;
    }

    // ── Try to map UUID to model slug from DOM ─────────────────────────────────
    function tryMapUUID(uuid) {
        try {
            const selectors = ['[data-model-id]', '[data-slug]', '[data-model-slug]'];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el) {
                    const slug = el.dataset.modelSlug || el.dataset.slug || el.value;
                    if (slug) {
                        modelUUIDs[slug] = uuid;
                        sendWS({ type: 'model_uuid', slug, uuid });
                    }
                }
            }
        } catch (_) {}
    }

    // ── Discover model UUIDs from Next.js page data ────────────────────────────
    function discoverModelUUIDs() {
        try {
            const nd = (unsafeWindow || window).__NEXT_DATA__;
            if (nd) {
                const str = JSON.stringify(nd);
                const re = /"slug":"([^"]+)"[^}]{0,200}?"id":"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"/g;
                let m;
                const found = {};
                while ((m = re.exec(str)) !== null) found[m[1]] = m[2];
                if (Object.keys(found).length > 0) {
                    Object.assign(modelUUIDs, found);
                    sendWS({ type: 'model_uuids', uuids: found });
                    sendWS({ type: 'debug', message: `Discovered ${Object.keys(found).length} UUIDs from __NEXT_DATA__` });
                }
            }

            document.querySelectorAll('script').forEach(s => {
                const text = s.textContent || '';
                const match = text.match(/"initialModels":(\[[\s\S]*?\]),"initialModel[A-Z]/);
                if (match) {
                    try {
                        const models = JSON.parse(match[1]);
                        const found2 = {};
                        for (const mdl of models) {
                            if (mdl.slug && mdl.id) found2[mdl.slug] = mdl.id;
                        }
                        if (Object.keys(found2).length > 0) {
                            Object.assign(modelUUIDs, found2);
                            sendWS({ type: 'model_uuids', uuids: found2 });
                            sendWS({ type: 'debug', message: `Discovered ${Object.keys(found2).length} UUIDs from initialModels` });
                        }
                    } catch (_) {}
                }
            });
        } catch (_) {}
    }

    // ── Handle make_request from bridge ───────────────────────────────────────
    async function handleMakeRequest(reqId, payload, overrideUrl) {
        try {
            // Always get a FRESH token — reCAPTCHA tokens are single-use!
            const token = await getToken();

            sendWS({
                type: 'debug',
                message: `Request ${reqId.slice(0, 8)}: modelAId=${payload.modelAId} modality=${payload.modality} token_len=${token.length}`
            });

            // Inject fresh token
            payload.recaptchaV3Token = token;

            // Use override URL for follow-up messages (post-to-evaluation)
            const requestUrl = overrideUrl || ARENA_URL;
            const sessionUrl = payload.id ? `https://arena.ai/c/${payload.id}` : 'https://arena.ai/';

            const resp = await _origFetch(requestUrl, {
                method:  'POST',
                headers: {
                    'content-type':   'text/plain;charset=UTF-8',
                    'accept':         '*/*',
                    'cache-control':  'no-cache',
                    'pragma':         'no-cache',
                    'origin':         'https://arena.ai',
                    'referer':        sessionUrl,
                    'priority':       'u=1, i',
                    'sec-fetch-dest': 'empty',
                    'sec-fetch-mode': 'cors',
                    'sec-fetch-site': 'same-origin',
                },
                body:        JSON.stringify(payload),
                credentials: 'include',
            });

            if (!resp.ok) {
                const errBody = await resp.text();
                sendWS({ type: 'debug', message: `Arena HTTP ${resp.status}: ${errBody.slice(0, 300)}` });
                sendWS({ type: 'error', id: reqId, error: `HTTP_${resp.status}: ${errBody.slice(0, 200)}` });
                return;
            }

            // Stream response
            const reader  = resp.body.getReader();
            const decoder = new TextDecoder();
            let   buf     = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buf += decoder.decode(value, { stream: true });
                const lines = buf.split('\n');
                buf = lines.pop();

                for (const rawLine of lines) {
                    const line = rawLine.trim();
                    if (!line) continue;

                    const parsed = parseArenaLine(line);
                    if (!parsed) continue;

                    if (parsed.type === 'text' && parsed.text) {
                        sendWS({ type: 'chunk', id: reqId, text: parsed.text });
                    } else if (parsed.type === 'error') {
                        sendWS({ type: 'error', id: reqId, error: parsed.text });
                        return;
                    }
                }
            }

            // Flush remaining
            if (buf.trim()) {
                const parsed = parseArenaLine(buf.trim());
                if (parsed && parsed.type === 'text' && parsed.text) {
                    sendWS({ type: 'chunk', id: reqId, text: parsed.text });
                }
            }

            sendWS({ type: 'done', id: reqId });

        } catch (err) {
            sendWS({ type: 'error', id: reqId, error: String(err) });
        }
    }

    // ── WebSocket ──────────────────────────────────────────────────────────────
    function connect() {
        if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;

        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            wsReady = true;
            if (reconnectT) { clearTimeout(reconnectT); reconnectT = null; }
            sendWS({ type: 'hello', version: VERSION });
            if (Object.keys(modelUUIDs).length > 0) {
                sendWS({ type: 'model_uuids', uuids: modelUUIDs });
            }
            updateBadge();
        };

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === 'make_request') {
                    handleMakeRequest(msg.id, msg.payload, msg.url);
                }
            } catch (_) {}
        };

        ws.onclose = () => {
            wsReady = false;
            ws = null;
            updateBadge();
            reconnectT = setTimeout(connect, 3000);
        };

        ws.onerror = () => { ws && ws.close(); };
    }

    function sendWS(obj) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(obj));
        }
    }

    // ── Status badge ──────────────────────────────────────────────────────────
    function createBadge() {
        badge = document.createElement('div');
        badge.style.cssText = [
            'position:fixed', 'bottom:12px', 'right:12px', 'z-index:2147483647',
            'padding:4px 10px', 'border-radius:6px', 'font-size:11px',
            'font-family:monospace', 'font-weight:bold', 'cursor:default',
            'box-shadow:0 2px 8px rgba(0,0,0,0.4)', 'transition:all 0.3s',
            'user-select:none', 'pointer-events:none',
        ].join(';');
        document.body.appendChild(badge);
        updateBadge();
    }

    function updateBadge() {
        if (!badge) return;
        const uuidCount = Object.keys(modelUUIDs).length;
        const g = (unsafeWindow || window).grecaptcha;
        const rcReady = !!(g && (g.execute || (g.enterprise && g.enterprise.execute)));

        if (!wsReady) {
            badge.style.background = '#991b1b';
            badge.style.color      = '#fca5a5';
            badge.textContent      = '🔴 Bridge disconnected';
        } else {
            badge.style.background = '#14532d';
            badge.style.color      = '#86efac';
            const skReady = !!SITEKEY;
            badge.textContent      = `🟢 Bridge v14 | UUIDs:${uuidCount} | SK:${skReady ? '✅' : '⏳'} | RC:${rcReady ? '✅' : '⏳'}`;
        }
    }

    // ── Init ──────────────────────────────────────────────────────────────────
    function init() {
        createBadge();
        connect();
        discoverModelUUIDs();
        discoverSitekey();
        setInterval(updateBadge, 3000);
        window.addEventListener('load', () => {
            setTimeout(() => {
                discoverModelUUIDs();
                discoverSitekey();
                updateBadge();
                if (SITEKEY) sendWS({ type: 'debug', message: `Sitekey discovered: ${SITEKEY}` });
                else sendWS({ type: 'debug', message: 'Sitekey not found — will use intercepted tokens only' });
            }, 2000);
        });
    }

    if (document.body) {
        init();
    } else {
        document.addEventListener('DOMContentLoaded', init);
    }

})();
