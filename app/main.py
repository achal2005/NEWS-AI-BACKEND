from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import os
import asyncio

from app.core.config import get_settings, _DEV_DEFAULT_SECRETS
from app.db import Base, engine
from app.api import auth_router, news_router, user_router, gamification_router
from app.services import kafka_producer
from app.core.scheduler import start_scheduler

# ── slowapi rate limiting (FIX 5) ────────────────────────────────────
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.limiter import limiter

settings = get_settings()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting up AI News Ecosystem...")

    # ── FIX 1: JWT secret startup guard ───────────────────────────────
    if not settings.debug:
        if settings.jwt_secret_key in _DEV_DEFAULT_SECRETS:
            raise RuntimeError(
                "FATAL: JWT_SECRET_KEY is set to a known dev default. "
                "Set a strong, unique secret in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
    else:
        if settings.jwt_secret_key in _DEV_DEFAULT_SECRETS:
            logger.warning(
                "⚠️  WARNING: JWT_SECRET_KEY is a known dev default! "
                "Do NOT deploy to production with this value."
            )
        if len(settings.jwt_secret_key) < 64:
            logger.warning(
                "⚠️  WARNING: JWT_SECRET_KEY is shorter than 64 characters. "
                "Consider using a longer key for production."
            )

    # R9: Warn if dev-login is enabled
    if settings.dev_login_enabled:
        logger.warning(
            "⚠️  WARNING: DEV_LOGIN_ENABLED=true — dev-login bypass is active! "
            "Disable this in production environments."
        )

    # ── FIX 12: asyncio lock for SQLite quiz creation ─────────────────
    app.state.quiz_creation_lock = asyncio.Lock()
    
    # Create database tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")
    
    # Auto-migrate: add depth_level column to article_summaries if missing
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(engine)
        columns = [c['name'] for c in inspector.get_columns('article_summaries')]
        if 'depth_level' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE article_summaries ADD COLUMN depth_level INTEGER DEFAULT 5"))
            logger.info("Migration: added depth_level column to article_summaries")
        else:
            logger.info("Migration: depth_level column already exists")
    except Exception as e:
        logger.warning(f"Migration check skipped: {e}")
    
    # Start Kafka producer (optional — app works without it)
    try:
        await kafka_producer.start()
        logger.info("Kafka producer started")
    except Exception as e:
        logger.warning(f"Kafka producer failed to start: {e}")

    # Start Background Scheduler (Daily News Refresh)
    try:
        start_scheduler()
    except Exception as e:
        logger.warning(f"Scheduler failed to start: {e}")

    # ── Keep-Alive Self-Ping (prevents Render free tier cold starts) ──
    import httpx

    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    keep_alive_task = None  # R18: Store reference for cancellation
    if render_url:
        async def keep_alive_ping():
            """Ping our own /health endpoint every 14 minutes to prevent spin-down."""
            await asyncio.sleep(60)  # Wait 1 min after startup
            url = f"{render_url}/health"
            # Reuse a single client to avoid connection pool memory leaks
            async with httpx.AsyncClient(timeout=10.0) as client:
                while True:
                    try:
                        r = await client.get(url)
                        logger.info(f"Keep-alive ping: {r.status_code}")
                    except Exception as e:
                        logger.warning(f"Keep-alive ping failed, will retry: {e}")
                    
                    # Sleep is outside the try block so it always waits before next ping
                    # even if the request fails
                    await asyncio.sleep(14 * 60)  # Every 14 minutes

        keep_alive_task = asyncio.create_task(keep_alive_ping())
        logger.info("Keep-alive self-ping task started (every 14 min)")
    else:
        logger.info("RENDER_EXTERNAL_URL not set, skipping keep-alive ping")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")

    # R18: Cancel keep-alive task to prevent accumulation on hot reload
    if keep_alive_task is not None:
        keep_alive_task.cancel()
        try:
            await keep_alive_task
        except asyncio.CancelledError:
            pass
        logger.info("Keep-alive task cancelled")

    try:
        await kafka_producer.stop()
    except Exception:
        pass


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="AI-powered news ecosystem with personalized summaries and gamification",
    version="1.0.0",
    lifespan=lifespan
)

# ── FIX 5: Attach slowapi limiter to app ─────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Configure CORS
allowed_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
if settings.frontend_url and settings.frontend_url not in allowed_origins:
    allowed_origins.append(settings.frontend_url)
# Include production URL from environment (e.g. Vercel deployment)
vercel_url = os.environ.get("VERCEL_URL", "https://news-ai-wine.vercel.app")
if vercel_url:
    # Vercel env var sometimes omits protocol
    if not vercel_url.startswith("http"):
        vercel_url = f"https://{vercel_url}"
    if vercel_url not in allowed_origins:
        allowed_origins.append(vercel_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(news_router)
app.include_router(user_router)
app.include_router(gamification_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint with memory diagnostics."""
    import sys
    
    # Get memory usage without psutil (works on Linux/Render)
    mem_info = {}
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith(('VmRSS:', 'VmSize:', 'VmPeak:')):
                    key, value = line.split(':')
                    mem_info[key.strip()] = value.strip()
    except (FileNotFoundError, PermissionError):
        # Windows/macOS — fall back to basic info
        pass
    
    # Cache stats
    from app.core.cache import article_list_cache

    return {
        "status": "healthy",
        "memory": mem_info or "unavailable (non-Linux)",
        "cache": {
            "article_list_entries": article_list_cache.size,
        },
    }
