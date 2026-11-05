import logging
import warnings
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

from app.config import get_settings
from app.models.database import init_db, engine
from app.api.bookings import router as bookings_router
from app.api.plivo import router as plivo_router
from app.api.admin import router as admin_router

settings = get_settings()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("voice_agent.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database schema...")
    await init_db()
    logger.info(
        f"Visitsly AI Outbound Voice Agent started. "
        f"LLM={settings.LLM_PROVIDER}, STT={settings.STT_PROVIDER}, TTS={settings.TTS_PROVIDER}, "
        f"Timezone={settings.TIMEZONE}"
    )
    yield
    logger.info("Shutting down database connections...")
    await engine.dispose()


app = FastAPI(
    title="Visitsly AI Outbound Voice Agent",
    description="Production-grade AI Voice Agent service calling site-visit customers in natural Hindi/Hinglish via Plivo.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bookings_router)
app.include_router(plivo_router)
app.include_router(admin_router)


@app.get("/health", summary="Service Health and Readiness Check")
async def health_check():
    """Returns database connectivity, provider states, and timezone status."""
    db_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            db_ok = True
    except Exception as e:
        logger.error(f"Health check DB error: {e}")

    now_ist = datetime.now(settings.tz).strftime("%Y-%m-%d %I:%M:%S %p IST")
    return {
        "status": "healthy" if db_ok else "degraded",
        "database_connected": db_ok,
        "current_time_ist": now_ist,
        "providers": {
            "llm": settings.LLM_PROVIDER,
            "stt": settings.STT_PROVIDER,
            "tts": settings.TTS_PROVIDER,
        },
        "plivo": {
            "configured": bool(settings.PLIVO_AUTH_ID and settings.PLIVO_CALLER_ID),
            "caller_id": settings.PLIVO_CALLER_ID,
            "stream_url": settings.stream_ws_url,
        },
        "calling_window": {
            "start": f"{settings.CALLING_WINDOW_START_HOUR}:00 IST",
            "end": f"{settings.CALLING_WINDOW_END_HOUR}:00 IST",
        },
    }


@app.get("/")
async def root():
    return {
        "service": "Visitsly AI Outbound Voice Agent",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }

