from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.core.config import get_settings
from app.db import Base, engine
from app.api import auth_router, news_router, user_router, gamification_router
from app.services import kafka_producer, ai_news_consumer

settings = get_settings()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Background task reference
consumer_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global consumer_task
    
    # Startup
    logger.info("Starting up AI News Ecosystem...")
    
    # Create database tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")
    
    # Start Kafka producer
    try:
        await kafka_producer.start()
        logger.info("Kafka producer started")
    except Exception as e:
        logger.warning(f"Kafka producer failed to start: {e}")
    
    # Start AI consumer as background task
    try:
        consumer_task = asyncio.create_task(ai_news_consumer.start())
        logger.info("AI News Consumer started as background task")
    except Exception as e:
        logger.warning(f"AI News Consumer failed to start: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    
    # Stop AI consumer
    if consumer_task:
        try:
            await ai_news_consumer.stop()
            consumer_task.cancel()
        except Exception:
            pass
    
    # Stop Kafka producer
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
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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


@app.get("/consumer/status")
async def consumer_status():
    """Check AI Consumer status."""
    return {
        "consumer_running": ai_news_consumer.running,
        "kafka_topic": "news-raw"
    }
