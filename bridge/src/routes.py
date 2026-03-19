"""OpenAI-compatible API routes."""

import hashlib
import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .arena_client import arena_client
from .models_list import get_models_response

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_api_key(authorization: Optional[str]) -> str:
    """Validate the Bearer API key and return it (or 'anonymous')."""
    from .config import load_config

    cfg = load_config()
    api_keys = cfg.get("api_keys", [])

    if not authorization:
        if api_keys:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        return "anonymous"

    token = authorization.replace("Bearer ", "").strip()

    if not api_keys:
        return token

    active_keys = [k["key"] for k in api_keys if k.get("active", True)]
    if token not in active_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return token


def _extract_conversation_fingerprint(body: dict, messages: list, api_key: str, model: str) -> str:
    """
    Build a stable key so repeated turns in the same Open WebUI chat map to one Arena chat.
    """

    candidates = [
        body.get("conversation_id"),
        body.get("conversationId"),
        body.get("chat_id"),
        body.get("chatId"),
        body.get("session_id"),
        body.get("sessionId"),
        body.get("id"),
    ]

    metadata = body.get("metadata")
    if isinstance(metadata, dict):
        candidates.extend(
            [
                metadata.get("conversation_id"),
                metadata.get("conversationId"),
                metadata.get("chat_id"),
                metadata.get("chatId"),
                metadata.get("session_id"),
                metadata.get("sessionId"),
                metadata.get("id"),
            ]
        )

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return f"{api_key}:{model}:{candidate.strip()}"

    # Fallback for clients that do not send an explicit chat id.
    first_user = ""
    for message in messages or []:
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            first_user = message["content"].strip()
            if first_user:
                break

    digest = hashlib.sha256(first_user.encode("utf-8")).hexdigest()[:20] if first_user else "default"
    return f"{api_key}:{model}:fallback:{digest}"


@router.get("/api/v1/models")
@router.get("/v1/models")
@router.get("/api/v1/v1/models")
async def list_models(authorization: Optional[str] = Header(None)):
    _get_api_key(authorization)
    return JSONResponse(get_models_response())


@router.get("/api/tags")
@router.get("/api/v1/api/tags")
async def list_tags(authorization: Optional[str] = Header(None)):
    _get_api_key(authorization)
    models = get_models_response()
    return JSONResponse(
        {
            "models": [
                {
                    "name": m["id"],
                    "model": m["id"],
                    "modified_at": "2024-01-01T00:00:00Z",
                }
                for m in models["data"]
            ]
        }
    )


async def _do_chat(
    model: str,
    messages: list,
    stream: bool,
    authorization: Optional[str],
    conv_fingerprint: str,
):
    _get_api_key(authorization)

    from . import userscript_server as us

    if not us.is_browser_connected():
        raise HTTPException(
            status_code=503,
            detail=(
                "No browser connected. Install the Tampermonkey userscript, "
                "open arena.ai, and send a message first."
            ),
        )

    logger.info("Chat request: model=%s, stream=%s, msgs=%s", model, stream, len(messages))

    if stream:

        async def generate():
            try:
                async for chunk in arena_client.stream_chat(model, messages, conv_fingerprint=conv_fingerprint):
                    if chunk:
                        data = {
                            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": chunk},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(data)}\n\n"

                final = {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(final)}\n\n"
                yield "data: [DONE]\n\n"

            except RuntimeError as exc:
                err_msg = str(exc)
                if "429" in err_msg or "Too Many" in err_msg:
                    logger.warning("Rate limited by Arena - wait ~5 minutes")
                    err_msg = "Arena rate limit reached (50 req/5min). Please wait a few minutes and try again."
                else:
                    logger.error("Stream error: %s", err_msg)

                err_data = {
                    "id": "chatcmpl-error",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"\n\n[Bridge error: {err_msg}]"},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(err_data)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        full_text = ""
        async for chunk in arena_client.stream_chat(model, messages, conv_fingerprint=conv_fingerprint):
            full_text += chunk

        return JSONResponse(
            {
                "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": full_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
        )

    except RuntimeError as exc:
        err_msg = str(exc)
        if "429" in err_msg or "Too Many" in err_msg:
            logger.warning("Rate limited by Arena - wait ~5 minutes")
            raise HTTPException(
                status_code=429,
                detail="Arena rate limit reached (50 req/5min). Please wait a few minutes.",
                headers={"Retry-After": "300"},
            )
        logger.error("Arena error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/api/v1/chat/completions")
@router.post("/v1/chat/completions")
@router.post("/api/v1/v1/chat/completions")
async def chat_completions(request: Request, authorization: Optional[str] = Header(None)):
    body = await request.json()
    model = body.get("model", "claude-opus-4-5-20251101")
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    api_key = _get_api_key(authorization)
    conv_fingerprint = _extract_conversation_fingerprint(body, messages, api_key, model)

    return await _do_chat(model, messages, stream, authorization, conv_fingerprint)


@router.get("/health")
async def health():
    from . import userscript_server as us

    return JSONResponse(
        {
            "status": "ok",
            "browser_connected": us.is_browser_connected(),
            "timestamp": int(time.time()),
        }
    )
