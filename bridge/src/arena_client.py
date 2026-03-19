"""Arena.ai bridge client with conversation continuation support."""

import asyncio
import json
import logging
import time
import uuid as uuid_mod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

ARENA_BASE = "https://arena.ai"
CREATE_STREAM_URL = f"{ARENA_BASE}/nextjs-api/stream/create-evaluation"


# Confirmed UUID mappings from captured Arena requests.
SLUG_TO_UUID: dict[str, str] = {
    "claude-opus-4-6": "019c2fac-13de-7550-a751-f5f593c77c72",
    "claude-opus-4-5-20251101": "019adbec-8396-71cc-87d5-b47f8431a6a6",
    "claude-sonnet-4-6": "019c6d29-a30c-7e20-9bd0-6650af926623",
    "gpt-5.3-codex": "019cc0bf-aeb3-7a0f-9982-dab440effef3",
}

SLUG_TO_MODALITY: dict[str, str] = {
    "gpt-5.3-codex": "webdev",
}

ALLOWED_MODELS = set(SLUG_TO_UUID.keys())
IMAGE_MODEL_ALIASES = {"image-generation", "image generation"}

# Runtime override map exposed to admin routes.
_runtime_uuid_map: dict[str, str] = {}


def _make_uuid7() -> str:
    """Generate UUIDv7-compatible IDs (matches Arena-like IDs)."""
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


def resolve_model_uuid(slug: str) -> str:
    if slug in _runtime_uuid_map:
        return _runtime_uuid_map[slug]
    if slug in SLUG_TO_UUID:
        return SLUG_TO_UUID[slug]
    raise RuntimeError(f"Unsupported model '{slug}'. Allowed: {', '.join(sorted(ALLOWED_MODELS))}")


def get_modality(slug: str) -> str:
    if is_image_model(slug):
        return "image"
    return SLUG_TO_MODALITY.get(slug, "chat")


def is_image_model(slug: str) -> bool:
    return slug in IMAGE_MODEL_ALIASES


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
    """Build first-turn payload content from message history."""
    if not messages:
        return ""

    valid: list[dict] = []
    for msg in messages:
        content = _message_text(msg.get("content", ""))
        if content:
            valid.append({"role": msg.get("role", "user"), "content": content})

    if not valid:
        return ""
    if len(valid) == 1:
        return valid[0]["content"]

    history = valid[:-1]
    current = valid[-1]["content"]

    parts = ["[Previous conversation]"]
    for msg in history:
        role = str(msg.get("role", "user")).capitalize()
        parts.append(f"{role}: {msg['content']}")

    parts.append("")
    parts.append("[Current message]")
    parts.append(current)
    return "\n".join(parts)


def _latest_user_content(messages: list[dict]) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            content = _message_text(msg.get("content", ""))
            if content:
                return content
    for msg in reversed(messages or []):
        content = _message_text(msg.get("content", ""))
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
        stale = [k for k, s in self._sessions.items() if (now - s.updated_at) > self._ttl]
        for key in stale:
            self._sessions.pop(key, None)


_session_store = SessionStore()


def _build_create_payload(model_slug: str, messages: list[dict], recaptcha_token: str) -> tuple[dict, ConversationSession]:
    conversation_id = _make_uuid7()
    model_uuid = ""
    if not is_image_model(model_slug):
        model_uuid = resolve_model_uuid(model_slug)
    modality = get_modality(model_slug)

    if is_image_model(model_slug):
        payload = {
            "id": conversation_id,
            "mode": "battle",
            "userMessageId": _make_uuid7(),
            "modelAMessageId": _make_uuid7(),
            "modelBMessageId": _make_uuid7(),
            "userMessage": {
                "content": _latest_user_content(messages),
                "experimental_attachments": [],
                "metadata": {},
            },
            "modality": "image",
            "recaptchaV3Token": recaptcha_token,
        }
    else:
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
    async def start(self):
        """Reserved for future startup hooks."""
        return None

    async def stop(self):
        """Reserved for future shutdown hooks."""
        return None

    async def _stream_from_browser(self, payload: dict, url: str):
        from . import userscript_server as us

        queue = await us.request_via_browser(payload, url=url)
        while True:
            kind, data = await queue.get()
            if kind == "chunk":
                yield data
                continue
            if kind == "done":
                break
            if kind == "error":
                raise RuntimeError(str(data))

    def _extract_image_urls_from_event(self, event_payload) -> list[str]:
        urls: list[str] = []
        if not isinstance(event_payload, list):
            return urls
        for item in event_payload:
            if isinstance(item, dict) and item.get("type") == "image":
                image_url = item.get("image")
                if isinstance(image_url, str) and image_url.strip():
                    urls.append(image_url.strip())
        return urls

    def _normalize_stream_chunk(self, raw_chunk: str) -> str:
        if not isinstance(raw_chunk, str):
            return ""

        chunk = raw_chunk.strip()
        if not chunk:
            return ""

        if ":" not in chunk:
            return raw_chunk

        prefix, payload = chunk.split(":", 1)
        prefix = prefix.strip().lower()

        if prefix in {"a0", "b0"}:
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                return raw_chunk
            return value if isinstance(value, str) else ""

        if prefix in {"a2", "b2"}:
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                return ""
            urls = self._extract_image_urls_from_event(value)
            if not urls:
                return ""
            return "\n".join(f"![generated image]({u})" for u in urls) + "\n"

        return ""

    async def collect_image_urls(self, model: str, messages: list[dict], conv_fingerprint: str = "") -> list[str]:
        urls: list[str] = []
        async for chunk in self.stream_chat(model, messages, conv_fingerprint=conv_fingerprint):
            for part in chunk.splitlines():
                text = part.strip()
                if text.startswith("![generated image](") and text.endswith(")"):
                    url = text[len("![generated image](") : -1]
                    if url and url not in urls:
                        urls.append(url)
        return urls

    async def stream_chat(self, model: str, messages: list[dict], conv_fingerprint: str = ""):
        from . import userscript_server as us

        if model not in ALLOWED_MODELS and not is_image_model(model):
            raise RuntimeError(f"Model '{model}' is not enabled.")

        recaptcha = await us.get_fresh_token(timeout=15)
        if not recaptcha:
            raise RuntimeError("No reCAPTCHA token from browser. Keep arena.ai tab open and retry.")

        session = await _session_store.get(conv_fingerprint) if conv_fingerprint else None

        # Continue same Arena chat when we already have a session for this Open WebUI chat.
        if session and session.model_slug == model and not is_image_model(model):
            follow_url = f"{ARENA_BASE}/nextjs-api/stream/post-to-evaluation/{session.conversation_id}"
            follow_payload = _build_followup_payload(session, messages, recaptcha)
            yielded = False
            try:
                async for chunk in self._stream_from_browser(follow_payload, follow_url):
                    normalized = self._normalize_stream_chunk(chunk)
                    if not normalized:
                        continue
                    yielded = True
                    yield normalized

                session.updated_at = time.time()
                await _session_store.set(conv_fingerprint, session)
                return
            except Exception as exc:
                # If follow-up fails before output begins, reset and retry as a fresh chat.
                if yielded:
                    raise RuntimeError(str(exc))
                logger.warning("Follow-up failed before output, resetting session: %s", exc)
                await _session_store.drop(conv_fingerprint)

        # First turn (or fallback after failed follow-up)
        create_payload, new_session = _build_create_payload(model, messages, recaptcha)
        async for chunk in self._stream_from_browser(create_payload, CREATE_STREAM_URL):
            normalized = self._normalize_stream_chunk(chunk)
            if normalized:
                yield normalized

        if conv_fingerprint and not is_image_model(model):
            new_session.updated_at = time.time()
            await _session_store.set(conv_fingerprint, new_session)


arena_client = ArenaClient()
