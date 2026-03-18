"""LMArena Bridge — main entry point."""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Lifespan ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    from .config import load_config
    from .admin import _reload_tokens
    from .arena_client import token_rotator, arena_client
    from . import userscript_server as us

    cfg = load_config()
    port = cfg.get("port", 8000)
    _reload_tokens()

    logger.info("=" * 60)
    logger.info("🚀 LMArena Bridge starting...")
    logger.info(f"   Port    : {port}")
    logger.info(f"   Tokens  : {token_rotator.count}")
    logger.info(f"   Debug   : {cfg.get('debug', False)}")
    logger.info(f"   Dashboard: http://localhost:{port}/dashboard")
    logger.info(f"   API Base : http://localhost:{port}/api/v1")
    logger.info(f"   Userscript WS: ws://127.0.0.1:7823  (Tampermonkey)")
    logger.info("=" * 60)

    # Start Camoufox (for CF bypass)
    camoufox_task = asyncio.create_task(arena_client.start())

    # Start WebSocket server for Tampermonkey userscript
    ws_task = asyncio.create_task(_start_ws_safe(us))

    yield  # ← server is running here

    # Shutdown
    camoufox_task.cancel()
    ws_task.cancel()
    try:
        await camoufox_task
    except asyncio.CancelledError:
        pass
    try:
        await ws_task
    except asyncio.CancelledError:
        pass
    await arena_client.stop()


async def _start_ws_safe(us):
    """Start the WebSocket server, handling port-already-in-use gracefully."""
    try:
        await us.start_server()
    except OSError as e:
        if "10048" in str(e) or "address already in use" in str(e).lower():
            logger.warning(
                "⚠️  WebSocket port 7823 already in use — "
                "another bridge instance may be running. "
                "Kill it with: taskkill /F /IM python.exe"
            )
        else:
            logger.error(f"❌ WebSocket server error: {e}")


# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="LMArena Bridge", version="5.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Import routers ────────────────────────────────────────────────────────────
from .admin import admin_router
from .routes import router

app.include_router(router)
app.include_router(admin_router)


# ── Dashboard routes ──────────────────────────────────────────────────────────
DIST_INDEX = Path(__file__).parent.parent.parent / "dist" / "index.html"


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
async def dashboard():
    if DIST_INDEX.exists():
        return HTMLResponse(content=DIST_INDEX.read_text(encoding="utf-8"), status_code=200)
    return HTMLResponse(
        content="<h1>Dashboard not built</h1><p>Run <code>npm run build</code> first.</p>",
        status_code=200,
    )


@app.get("/dashboard/{path:path}")
async def dashboard_spa(path: str):
    """Serve the SPA for all dashboard sub-routes."""
    if DIST_INDEX.exists():
        return HTMLResponse(content=DIST_INDEX.read_text(encoding="utf-8"), status_code=200)
    return RedirectResponse(url="/dashboard")


USERSCRIPT = Path(__file__).parent.parent / "userscript" / "arena-bridge.user.js"


@app.get("/userscript")
async def serve_userscript():
    """Serve the Tampermonkey userscript."""
    if USERSCRIPT.exists():
        return PlainTextResponse(
            content=USERSCRIPT.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )
    return PlainTextResponse("// Userscript not found", status_code=404)


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from .config import load_config
    cfg = load_config()
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=cfg.get("port", 8000),
        reload=False,
    )
