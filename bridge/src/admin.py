"""Admin API routes for the dashboard."""
import hashlib
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .arena_client import token_rotator, arena_client, TokenEntry, _runtime_uuid_map
from .config import load_config, save_config

logger = logging.getLogger(__name__)
admin_router = APIRouter(prefix="/admin")


# ── Auth helper ───────────────────────────────────────────────────────────────
def _check_auth(x_admin_password: Optional[str]):
    cfg = load_config()
    if x_admin_password != cfg.get("admin_password", "admin"):
        raise HTTPException(status_code=401, detail="Invalid admin password")


# ── Token management ──────────────────────────────────────────────────────────
def _reload_tokens():
    cfg = load_config()
    entries = []
    for t in cfg.get("tokens", []):
        if t.get("active", True):
            entries.append(TokenEntry(
                token_v1_0=t.get("value", ""),
                token_v1_1=t.get("value_v1_1", ""),
            ))
    token_rotator.set_tokens(entries)
    logger.info(f"🔑 Loaded {token_rotator.count} active token(s)")


# Load on startup
_reload_tokens()


# ── Pydantic models ───────────────────────────────────────────────────────────
class TokenAdd(BaseModel):
    # Accept both naming conventions
    token: Optional[str] = ""       # from React dashboard
    value: Optional[str] = ""       # legacy
    token_v11: Optional[str] = ""   # from React dashboard
    value_v1_1: Optional[str] = ""  # legacy
    label: Optional[str] = ""


class ApiKeyAdd(BaseModel):
    label: Optional[str] = ""
    rate_limit: Optional[int] = 60


class ConfigUpdate(BaseModel):
    debug: Optional[bool] = None
    timeout: Optional[int] = None


class PasswordChange(BaseModel):
    new_password: str


class ModelUUIDAdd(BaseModel):
    slug: str
    uuid: str


# ── Routes ────────────────────────────────────────────────────────────────────
@admin_router.get("/status")
def get_status(x_admin_password: Optional[str] = Header(None)):
    _check_auth(x_admin_password)
    from . import userscript_server as us
    cfg = load_config()
    return {
        "tokens":            token_rotator.count,
        "api_keys":          len(cfg.get("api_keys", [])),
        "debug":             cfg.get("debug", False),
        "timeout":           cfg.get("timeout", 120),
        "browser_connected": us.is_browser_connected(),
        "recaptcha_ready":   us.get_recaptcha_token() is not None,
        "known_uuids":       len(us.get_model_uuids()) + len(_runtime_uuid_map),
    }


@admin_router.get("/tokens")
def list_tokens(x_admin_password: Optional[str] = Header(None)):
    _check_auth(x_admin_password)
    cfg = load_config()
    tokens = []
    for t in cfg.get("tokens", []):
        val = t.get("value", "")
        tokens.append({
            "id":       t.get("id", ""),
            "label":    t.get("label", ""),
            "active":   t.get("active", True),
            "preview":  val[:40] + "..." if len(val) > 40 else val,
            "added_at": t.get("added_at", ""),
            "has_v1_1": bool(t.get("value_v1_1", "")),
        })
    return tokens


@admin_router.post("/tokens")
def add_token(body: TokenAdd, x_admin_password: Optional[str] = Header(None)):
    _check_auth(x_admin_password)
    from datetime import datetime, timezone
    cfg = load_config()
    # Accept both naming conventions from React dashboard
    val     = (body.token or body.value or "").strip()
    val_v11 = (body.token_v11 or body.value_v1_1 or "").strip()
    if not val:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Token value is required")
    token_id = secrets.token_hex(8)
    cfg.setdefault("tokens", []).append({
        "id":         token_id,
        "label":      body.label or f"Token {token_id[:6]}",
        "value":      val,
        "value_v1_1": val_v11,
        "active":     True,
        "added_at":   datetime.now(timezone.utc).isoformat(),
    })
    save_config(cfg)
    _reload_tokens()
    return {"ok": True, "id": token_id}


@admin_router.delete("/tokens/{token_id}")
def delete_token(token_id: str, x_admin_password: Optional[str] = Header(None)):
    _check_auth(x_admin_password)
    cfg = load_config()
    cfg["tokens"] = [t for t in cfg.get("tokens", []) if t.get("id") != token_id]
    save_config(cfg)
    _reload_tokens()
    return {"ok": True}


@admin_router.patch("/tokens/{token_id}/toggle")
def toggle_token(token_id: str, x_admin_password: Optional[str] = Header(None)):
    _check_auth(x_admin_password)
    cfg = load_config()
    for t in cfg.get("tokens", []):
        if t.get("id") == token_id:
            t["active"] = not t.get("active", True)
            break
    save_config(cfg)
    _reload_tokens()
    return {"ok": True}


# ── API Keys ──────────────────────────────────────────────────────────────────
@admin_router.get("/api-keys")
def list_api_keys(x_admin_password: Optional[str] = Header(None)):
    _check_auth(x_admin_password)
    cfg = load_config()
    return cfg.get("api_keys", [])


@admin_router.post("/api-keys")
def add_api_key(body: ApiKeyAdd, x_admin_password: Optional[str] = Header(None)):
    _check_auth(x_admin_password)
    cfg = load_config()
    key = f"sk-lmab-{secrets.token_hex(16)}"
    key_id = secrets.token_hex(8)
    cfg.setdefault("api_keys", []).append({
        "id":         key_id,
        "label":      body.label or f"Key {len(cfg['api_keys']) + 1}",
        "key":        key,
        "rate_limit": body.rate_limit or 60,
        "active":     True,
    })
    save_config(cfg)
    return {"ok": True, "key": key, "id": key_id}


@admin_router.delete("/api-keys/{key_id}")
def delete_api_key(key_id: str, x_admin_password: Optional[str] = Header(None)):
    _check_auth(x_admin_password)
    cfg = load_config()
    cfg["api_keys"] = [k for k in cfg.get("api_keys", []) if k.get("id") != key_id]
    save_config(cfg)
    return {"ok": True}


# ── Config ────────────────────────────────────────────────────────────────────
@admin_router.patch("/config")
def update_config(body: ConfigUpdate, x_admin_password: Optional[str] = Header(None)):
    _check_auth(x_admin_password)
    cfg = load_config()
    if body.debug is not None:
        cfg["debug"] = body.debug
    if body.timeout is not None:
        cfg["timeout"] = body.timeout
    save_config(cfg)
    return {"ok": True}


@admin_router.post("/change-password")
def change_password(body: PasswordChange, x_admin_password: Optional[str] = Header(None)):
    _check_auth(x_admin_password)
    cfg = load_config()
    cfg["admin_password"] = body.new_password
    save_config(cfg)
    return {"ok": True}


# ── Model UUIDs ───────────────────────────────────────────────────────────────
@admin_router.get("/model-uuids")
def get_model_uuids(x_admin_password: Optional[str] = Header(None)):
    _check_auth(x_admin_password)
    from . import userscript_server as us
    from .arena_client import SLUG_TO_UUID
    all_uuids = {**SLUG_TO_UUID, **_runtime_uuid_map, **us.get_model_uuids()}
    return {"uuids": all_uuids, "count": len(all_uuids)}


@admin_router.post("/model-uuids")
def add_model_uuid(body: ModelUUIDAdd, x_admin_password: Optional[str] = Header(None)):
    _check_auth(x_admin_password)
    _runtime_uuid_map[body.slug] = body.uuid
    return {"ok": True}
