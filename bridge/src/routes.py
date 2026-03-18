"""OpenAI-compatible API routes."""
import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .arena_client import arena_client, token_rotator
from .models_list import get_models_response

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Auth helper ───────────────────────────────────────────────────────────────
def _get_api_key(authorization: Optional[str]) -> str:
    """Validate the Bearer API key and return it (or 'anonymous')."""
    from .config import load_config
    cfg      = load_config()
    api_keys = cfg.get("api_keys", [])

    if not authorization:
        if api_keys:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        return "anonymous"

    token = authorization.replace("Bearer ", "").strip()

    if not api_keys:
        return token  # No keys configured — allow all, use token as session key

    active_keys = [k["key"] for k in api_keys if k.get("active", True)]
    if token not in active_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return token


# ── Models endpoint ───────────────────────────────────────────────────────────
@router.get("/api/v1/models")
@router.get("/v1/models")
@router.get("/api/v1/v1/models")     # Open WebUI double-prefix
async def list_models(authorization: Optional[str] = Header(None)):
    _get_api_key(authorization)
    return JSONResponse(get_models_response())


# Ollama-style tags endpoint (Open WebUI uses this)
@router.get("/api/tags")
@router.get("/api/v1/api/tags")      # Open WebUI double-prefix
async def list_tags(authorization: Optional[str] = Header(None)):
    _get_api_key(authorization)
    models = get_models_response()
    return JSONResponse({
        "models": [
            {"name": m["id"], "model": m["id"], "modified_at": "2024-01-01T00:00:00Z"}
            for m in models["data"]
        ]
    })


# ── Chat completions ──────────────────────────────────────────────────────────
async def _do_chat(model: str, messages: list, stream: bool, authorization: Optional[str]):
    api_key = _get_api_key(authorization)

    from . import userscript_server as us
    if not us.is_browser_connected():
        raise HTTPException(
            status_code=503,
            detail="No browser connected. Install the Tampermonkey userscript, open arena.ai, and send a message first."
        )

    logger.info(f"🔵 Chat request: model={model}, stream={stream}, msgs={len(messages)}")

    if stream:
        async def generate():
            try:
                async for chunk in arena_client.stream_chat(model, messages):
                    if chunk:
                        data = {
                            "id":      f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            "object":  "chat.completion.chunk",
                            "created": int(time.time()),
                            "model":   model,
                            "choices": [{
                                "index": 0,
                                "delta": {"content": chunk},
                                "finish_reason": None,
                            }],
                        }
                        yield f"data: {json.dumps(data)}\n\n"

                # Send final chunk
                final = {
                    "id":      f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object":  "chat.completion.chunk",
                    "created": int(time.time()),
                    "model":   model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(final)}\n\n"
                yield "data: [DONE]\n\n"

            except RuntimeError as e:
                err_msg = str(e)
                if "429" in err_msg or "Too Many" in err_msg:
                    logger.warning(f"🚦 Rate limited by Arena — wait ~5 minutes")
                    err_msg = "Arena rate limit reached (50 req/5min). Please wait a few minutes and try again."
                else:
                    logger.error(f"❌ Stream error: {err_msg}")

                err_data = {
                    "id":      "chatcmpl-error",
                    "object":  "chat.completion.chunk",
                    "created": int(time.time()),
                    "model":   model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": f"\n\n[Bridge error: {err_msg}]"},
                        "finish_reason": "stop",
                    }],
                }
                yield f"data: {json.dumps(err_data)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    else:
        # Non-streaming
        try:
            full_text = ""
            async for chunk in arena_client.stream_chat(model, messages):
                full_text += chunk

            return JSONResponse({
                "id":      f"chatcmpl-{uuid.uuid4().hex[:8]}",
                "object":  "chat.completion",
                "created": int(time.time()),
                "model":   model,
                "choices": [{
                    "index":         0,
                    "message":       {"role": "assistant", "content": full_text},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens":     0,
                    "completion_tokens": 0,
                    "total_tokens":      0,
                },
            })

        except RuntimeError as e:
            err_msg = str(e)
            if "429" in err_msg or "Too Many" in err_msg:
                logger.warning(f"🚦 Rate limited by Arena — wait ~5 minutes")
                raise HTTPException(
                    status_code=429,
                    detail="Arena rate limit reached (50 req/5min). Please wait a few minutes.",
                    headers={"Retry-After": "300"},
                )
            logger.error(f"❌ Arena error: {e}")
            raise HTTPException(status_code=502, detail=str(e))


@router.post("/api/v1/chat/completions")
@router.post("/v1/chat/completions")
@router.post("/api/v1/v1/chat/completions")   # Open WebUI double-prefix
async def chat_completions(request: Request, authorization: Optional[str] = Header(None)):
    body     = await request.json()
    model    = body.get("model", "claude-opus-4-5-20251101")
    messages = body.get("messages", [])
    stream   = body.get("stream", False)
    return await _do_chat(model, messages, stream, authorization)


# Health check
@router.get("/health")
async def health():
    from . import userscript_server as us
    return JSONResponse({
        "status":           "ok",
        "browser_connected": us.is_browser_connected(),
        "timestamp":        int(time.time()),
    })
