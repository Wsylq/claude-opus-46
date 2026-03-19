"""Arena.ai bridge client with chat continuation support."""

import asyncio
import logging
import time
import uuid as uuid_mod
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

ARENA_BASE = "https://arena.ai"
CREATE_STREAM_URL = f"{ARENA_BASE}/nextjs-api/stream/create-evaluation"


# Confirmed UUIDs from real network captures
SLUG_TO_UUID: dict = {
    "claude-opus-4-5-20251101": "019adbec-8396-71cc-87d5-b47f8431a6a6",
    "claude-opus-4-6": "019c2fac-13de-7550-a751-f5f593c77c72",
    "gpt-5.3-codex": "019cc0bf-aeb3-7a0f-9982-dab440effef3",
}

SLUG_TO_MODALITY: dict = {
    "gpt-5.3-codex": "webdev",
}

_runtime_uuid_map: dict = {}


def _make_uuid7() -> str:
    ms = int(time.time() * 1000)
    rand_a = uuid_mod.uuid4().int & 0xFFF
    rand_b = uuid_mod.uuid4().int & 0x3FFFFFFFFFFFFFFF
    hi = (ms << 16) | (0x7 << 12) | rand_a
    lo = (0b10 << 62) | rand_b
    h = f"{hi:016x}{lo:016x}"
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


class TokenEntry:
    def __init__(self, token_v1_0: str, token_v1_1: str = ""):
        self.token_v1_0 = token_v1_0
        self.token_v1_1 = token_v1_1


class TokenRotator:
    def __init__(self):
        self._entries: list[TokenEntry] = []
        self._idx = 0

    def set_tokens(self, entries: list[TokenEntry]):
        self._entries = entries
        self._idx = 0

    def next(self) -> Optional[TokenEntry]:
        if not self._entries:
            return None
        entry = self._entries[self._idx % len(self._entries)]
        self._idx += 1
        return entry

    @property
    def count(self) -> int:
        return len(self._entries)


token_rotator = TokenRotator()


STATIC_MODELS = [
    ("claude-opus-4-6", "anthropic"),
    ("claude-opus-4-5-20251101", "anthropic"),
    ("claude-sonnet-4-5-20251101", "anthropic"),
    ("claude-haiku-3-5-20241022", "anthropic"),
    ("claude-opus-4-20250514", "anthropic"),
    ("claude-sonnet-4-20250514", "anthropic"),
    ("claude-3-7-sonnet-20250219", "anthropic"),
    ("claude-3-5-sonnet-20241022", "anthropic"),
    ("gpt-5.3-codex", "openai"),
    ("gpt-4o", "openai"),
    ("gpt-4o-mini", "openai"),
    ("gpt-4-turbo", "openai"),
    ("o3", "openai"),
    ("o4-mini", "openai"),
    ("o3-mini", "openai"),
    ("o1", "openai"),
    ("gemini-2.5-pro-preview", "google"),
    ("gemini-2.5-flash-preview", "google"),
    ("gemini-2.0-flash", "google"),
    ("gemini-2.0-pro", "google"),
    ("gemini-1.5-pro", "google"),
    ("llama-3.3-70b-instruct", "meta"),
    ("llama-4-scout", "meta"),
    ("llama-4-maverick", "meta"),
    ("deepseek-r1", "deepseek"),
    ("deepseek-v3", "deepseek"),
    ("grok-3", "xai"),
    ("grok-3-mini", "xai"),
    ("mistral-large-2411", "mistral"),
    ("mistral-medium-3", "mistral"),
    ("qwen-2.5-72b-instruct", "alibaba"),
    ("qwen-3-235b", "alibaba"),
    ("gemma-3-27b-it", "google"),
    ("command-r-plus-08-2024", "cohere"),
]


def get_models_list() -> list[dict]:
    ts = int(time.time())
    return [
        {"id": slug, "object": "model", "created": ts, "owned_by": owner}
        for slug, owner in STATIC_MODELS
    ]


def resolve_model_uuid(slug: str) -> str:
    if slug in _runtime_uuid_map:
        return _runtime_uuid_map[slug]
    if slug in SLUG_TO_UUID:
        return SLUG_TO_UUID[slug]
    logger.warning("No UUID for '%s' - sending slug (will likely fail)", slug)
    return slug


def get_modality(slug: str) -> str:
    return SLUG_TO_MODALITY.get(slug, "chat")


def _message_text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(p.strip() for p in parts if p and p.strip()).strip()
    return ""


def _build_content(messages: list[dict]) -> str:
    """Build the initial prompt content for create-evaluation."""
    if not messages:
        return ""

    valid: list[dict] = []
    for message in messages:
        content = _message_text(message.get("content", ""))
        if content:
            valid.append({"role": message.get("role", "user"), "content": content})

    if not valid:
        return ""

    if len(valid) == 1:
        return valid[0]["content"]

    history = valid[:-1]
    current = valid[-1]

    parts = ["[Previous conversation]"]
    for message in history:
        role = str(message.get("role", "user")).capitalize()
        parts.append(f"{role}: {message['content']}")

    parts.append("")
    parts.append("[Current message]")
    parts.append(current["content"])
    return "\n".join(parts)


def _latest_user_content(messages: list[dict]) -> str:
    for message in reversed(messages or []):
        if message.get("role") != "user":
            continue
        content = _message_text(message.get("content", ""))
        if content:
            return content

    for message in reversed(messages or []):
        content = _message_text(message.get("content", ""))
        if content:
            return content

    return ""


@dataclass
class ConversationSession:
    conversation_id: str
    model_a_id: str
    modality: str
    model_slug: str
    updated_at: float


class SessionStore:
    def __init__(self, ttl_seconds: int = 6 * 60 * 60):
        self._ttl = ttl_seconds
        self._sessions: dict[str, ConversationSession] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[ConversationSession]:
        if not key:
            return None
        async with self._lock:
            self._cleanup_locked()
            return self._sessions.get(key)

    async def set(self, key: str, session: ConversationSession):
        if not key:
            return
        async with self._lock:
            self._sessions[key] = session
            self._cleanup_locked()

    async def drop(self, key: str):
        if not key:
            return
        async with self._lock:
            self._sessions.pop(key, None)

    def _cleanup_locked(self):
        now = time.time()
        stale = [
            key
            for key, value in self._sessions.items()
            if (now - value.updated_at) > self._ttl
        ]
        for key in stale:
            self._sessions.pop(key, None)


_session_store = SessionStore()


def _build_create_payload(model_slug: str, messages: list[dict], recaptcha_token: str) -> tuple[dict, ConversationSession]:
    conversation_id = _make_uuid7()
    model_uuid = resolve_model_uuid(model_slug)
    modality = get_modality(model_slug)

    payload = {
        "id": conversation_id,
        "mode": "direct-battle",
        "modelAId": model_uuid,
        "userMessageId": _make_uuid7(),
        "modelAMessageId": _make_uuid7(),
        "userMessage": {
            "content": _build_content(messages),
            "experimental_attachments": [],
            "metadata": {},
        },
        "modality": modality,
        "recaptchaV3Token": recaptcha_token,
    }

    session = ConversationSession(
        conversation_id=conversation_id,
        model_a_id=model_uuid,
        modality=modality,
        model_slug=model_slug,
        updated_at=time.time(),
    )
    return payload, session


def _build_followup_payload(session: ConversationSession, messages: list[dict], recaptcha_token: str) -> dict:
    return {
        "id": session.conversation_id,
        "modelAId": session.model_a_id,
        "userMessageId": _make_uuid7(),
        "modelAMessageId": _make_uuid7(),
        "userMessage": {
            "content": _latest_user_content(messages),
            "experimental_attachments": [],
            "metadata": {},
        },
        "modality": session.modality,
        "recaptchaV3Token": recaptcha_token,
    }


class ArenaClient:
    def __init__(self):
        self._browser_ctx = None
        self._page = None

    async def start(self):
        try:
            from camoufox.async_api import AsyncCamoufox

            logger.info("Launching Camoufox...")
            self._browser_ctx = AsyncCamoufox(headless=True, block_images=True)
            browser = await self._browser_ctx.__aenter__()
            self._page = await browser.new_page()
            logger.info("Camoufox browser ready")
        except Exception as exc:
            logger.warning("Camoufox failed to start: %s", exc)
            self._page = None

    async def stop(self):
        try:
            if self._browser_ctx:
                await self._browser_ctx.__aexit__(None, None, None)
        except Exception:
            pass

    async def _stream_request(self, payload: dict, url: str) -> AsyncGenerator[str, None]:
        from . import userscript_server as us

        q = await us.request_via_browser(payload, url=url)
        while True:
            kind, data = await q.get()
            if kind == "chunk":
                if data:
                    yield data
                continue
            if kind == "done":
                break
            if kind == "error":
                raise RuntimeError(data or "Unknown Arena stream error")

    async def stream_chat(
        self,
        model_slug: str,
        messages: list[dict],
        conv_fingerprint: str = "",
    ) -> AsyncGenerator[str, None]:
        from . import userscript_server as us

        if not us.is_browser_connected():
            raise RuntimeError(
                "No browser connected. Open arena.ai with the Tampermonkey userscript installed.\n"
                "See http://localhost:8000/dashboard for instructions."
            )

        token = await us.get_fresh_token(timeout=30.0)
        if not token:
            token = ""

        existing_session = await _session_store.get(conv_fingerprint)

        attempt = 0
        while attempt < 2:
            use_followup = existing_session is not None

            if use_followup:
                payload = _build_followup_payload(existing_session, messages, token)
                stream_url = (
                    f"{ARENA_BASE}/nextjs-api/stream/post-to-evaluation/"
                    f"{existing_session.conversation_id}"
                )
                next_session = ConversationSession(
                    conversation_id=existing_session.conversation_id,
                    model_a_id=existing_session.model_a_id,
                    modality=existing_session.modality,
                    model_slug=existing_session.model_slug,
                    updated_at=time.time(),
                )
                logger.info("Continuing Arena chat: %s", existing_session.conversation_id)
            else:
                payload, next_session = _build_create_payload(model_slug, messages, token)
                stream_url = CREATE_STREAM_URL
                logger.info("Creating new Arena chat: %s", payload["id"])

            emitted_any = False
            try:
                async for chunk in self._stream_request(payload, stream_url):
                    emitted_any = True
                    yield chunk

                if conv_fingerprint:
                    await _session_store.set(conv_fingerprint, next_session)
                return

            except RuntimeError as exc:
                # If continuation fails before output starts, recover by opening a new Arena chat.
                if use_followup and not emitted_any and conv_fingerprint:
                    logger.warning("Follow-up failed, resetting Arena session: %s", exc)
                    await _session_store.drop(conv_fingerprint)
                    existing_session = None
                    attempt += 1
                    continue
                raise

        raise RuntimeError("Failed to stream from Arena")


arena_client = ArenaClient()
