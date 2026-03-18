"""
WebSocket server that the Tampermonkey userscript connects to.

Protocol (JSON messages):
  Browser → Bridge:
    { type: "hello",          version: "13.0.0" }
    { type: "recaptcha_token",token: "..." }
    { type: "model_uuid",     slug: "...", uuid: "..." }
    { type: "model_uuids",    uuids: { slug: uuid, ... } }
    { type: "chunk",          id: "reqId", text: "..." }
    { type: "done",           id: "reqId" }
    { type: "error",          id: "reqId", error: "..." }
    { type: "debug",          message: "..." }

  Bridge → Browser:
    { type: "make_request", id: "reqId", payload: { ... }, url: "..." }
"""

import asyncio
import json
import logging
import re
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# ── Shared state ──────────────────────────────────────────────────────────────
_recaptcha_token: Optional[str] = None
_token_event: Optional[asyncio.Event] = None
_model_uuids: dict = {}
_pending: dict = {}       # reqId → asyncio.Queue
_browser_ws = None        # current connected WebSocket


def _get_event() -> asyncio.Event:
    global _token_event
    if _token_event is None:
        _token_event = asyncio.Event()
    return _token_event


def get_recaptcha_token() -> Optional[str]:
    return _recaptcha_token


def get_model_uuids() -> dict:
    return _model_uuids


def is_browser_connected() -> bool:
    return _browser_ws is not None


async def wait_for_token(timeout: float = 15.0) -> Optional[str]:
    if _recaptcha_token:
        return _recaptcha_token
    try:
        await asyncio.wait_for(_get_event().wait(), timeout=timeout)
        return _recaptcha_token
    except asyncio.TimeoutError:
        return None


async def request_via_browser(payload: dict, url: Optional[str] = None) -> asyncio.Queue:
    """Ask the browser to make the fetch and stream back results."""
    global _browser_ws
    if not _browser_ws:
        raise RuntimeError("No browser connected via Tampermonkey")

    req_id = str(uuid.uuid4())
    q: asyncio.Queue = asyncio.Queue()
    _pending[req_id] = q

    msg: dict = {
        "type":    "make_request",
        "id":      req_id,
        "payload": payload,
    }
    if url:
        msg["url"] = url

    await _browser_ws.send(json.dumps(msg))
    logger.info(f"📡 [Userscript] Sent request {req_id[:8]}… to browser")
    return q


# ── Arena stream line parser ──────────────────────────────────────────────────
def _parse_arena_line(line: str) -> Optional[str]:
    """
    Parse a line from Arena's stream format.

    Examples:
      a0:"Hello "           → "Hello "
      a0:"line\\nbreak"     → "line\nbreak"
      a2:[{"type":"heartbeat"}]  → None (skip)
      ad:{"finishReason":…} → None  (end signal)
      3:"error"             → raises RuntimeError
    """
    line = line.strip()
    if not line:
        return None

    # Text chunk  a<n>:"..."
    m = re.match(r'^a\d+:"(.*)"$', line, re.DOTALL)
    if m:
        text = m.group(1)
        text = text.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        return text if text else None

    # Array format a<n>:[...] — check for text content inside
    m = re.match(r'^a\d+:\[(.+)\]$', line, re.DOTALL)
    if m:
        try:
            items = json.loads(f"[{m.group(1)}]")
            for item in items:
                if isinstance(item, dict):
                    if item.get("type") == "textDelta":
                        return item.get("delta", "") or None
                    if item.get("type") == "text":
                        return item.get("text", "") or None
        except Exception:
            pass
        return None  # heartbeat/other array events

    # Finish signal
    if re.match(r'^ad:\{', line):
        return None

    # Error signal
    m = re.match(r'^3:"(.*)"$', line)
    if m:
        raise RuntimeError(f"Arena error: {m.group(1)}")

    # Standard SSE data: prefix
    if line.startswith("data:"):
        data = line[5:].strip()
        if data in ("[DONE]", ""):
            return None
        try:
            obj = json.loads(data)
            choices = obj.get("choices", [])
            if choices:
                return choices[0].get("delta", {}).get("content") or None
            if obj.get("type") == "textDelta":
                return obj.get("delta", "") or None
        except Exception:
            pass

    return None


# ── WebSocket handler ─────────────────────────────────────────────────────────
async def _handle_client(ws):
    global _recaptcha_token, _browser_ws

    _browser_ws = ws
    logger.info(f"🌐 [Userscript] Browser connected from {ws.remote_address}")

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            t = msg.get("type", "")

            if t == "hello":
                logger.info(f"👋 [Userscript] version={msg.get('version', '?')}")

            elif t == "debug":
                logger.info(f"🔍 [Userscript] {msg.get('message', '')}")

            elif t == "recaptcha_token":
                tok = msg.get("token", "")
                if tok and len(tok) > 100:
                    _recaptcha_token = tok
                    ev = _get_event()
                    ev.set()
                    await asyncio.sleep(0)
                    ev.clear()
                    ev.set()
                    logger.info(f"🔐 [Userscript] reCAPTCHA token received (len={len(tok)})")

            elif t == "model_uuid":
                slug = msg.get("slug", "")
                uid  = msg.get("uuid", "")
                if slug and uid:
                    _model_uuids[slug] = uid
                    logger.info(f"🗺️  [Userscript] UUID: {slug} → {uid}")

            elif t == "model_uuids":
                uuids = msg.get("uuids", {})
                if uuids:
                    _model_uuids.update(uuids)
                    logger.info(f"🗺️  [Userscript] Bulk {len(uuids)} model UUIDs received")

            elif t == "chunk":
                # v11+ userscript sends pre-parsed text chunks
                req_id = msg.get("id", "")
                text   = msg.get("text", "")
                if req_id in _pending and text:
                    await _pending[req_id].put(("chunk", text))

            elif t == "line":
                # Legacy: raw arena stream line, parse it here
                req_id = msg.get("id", "")
                line   = msg.get("line", "")
                if req_id in _pending:
                    try:
                        text = _parse_arena_line(line)
                        if text is not None:
                            await _pending[req_id].put(("chunk", text))
                    except RuntimeError as e:
                        await _pending[req_id].put(("error", str(e)))

            elif t == "done":
                req_id = msg.get("id", "")
                if req_id in _pending:
                    await _pending[req_id].put(("done", None))
                    del _pending[req_id]

            elif t == "error":
                req_id = msg.get("id", "")
                err    = msg.get("error", "Unknown error")
                if "429" in err or "Too Many" in err:
                    logger.warning(f"🚦 [Userscript] RATE LIMITED — wait ~5 minutes before retrying")
                else:
                    logger.warning(f"⚠️  [Userscript] Request {req_id[:8]} error: {err}")
                if req_id in _pending:
                    await _pending[req_id].put(("error", err))
                    del _pending[req_id]

    except Exception as e:
        logger.warning(f"[Userscript] Connection error: {e}")

    finally:
        if _browser_ws is ws:
            _browser_ws = None
        for q in list(_pending.values()):
            await q.put(("error", "Browser disconnected"))
        _pending.clear()
        logger.info("🔌 [Userscript] Browser disconnected")


async def start_server(host: str = "127.0.0.1", port: int = 7823):
    import websockets
    logger.info(f"🔌 [Userscript] WebSocket server listening on ws://{host}:{port}")
    async with websockets.serve(_handle_client, host, port):
        await asyncio.Future()   # run forever
