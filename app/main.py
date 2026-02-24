from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.core.config import get_settings
from app.db import Base, engine
from app.api import auth_router, news_router, user_router, gamification_router
from app.services import kafka_producer
from app.core.scheduler import start_scheduler

settings = get_settings()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting up AI News Ecosystem...")
    
    # Create database tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")
    
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
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
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

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", settings.frontend_url],
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
    """Health check endpoint."""
    return {"status": "healthy"}

