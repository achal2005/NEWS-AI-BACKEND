"""
Standalone AI Consumer Runner

Run this script to start the AI consumer independently from the main API.
Useful for scaling consumers separately or for development/testing.

Usage:
    python -m app.consumer_runner
    
    Or with uvicorn for auto-reload:
    uvicorn app.consumer_runner:run --reload
"""

import asyncio
import logging
import signal
import sys

from app.services.ai_consumer import ai_news_consumer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def shutdown(signal_type, loop):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received {signal_type.name}, shutting down...")
    await ai_news_consumer.stop()
    
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()


async def main():
    """Main entry point for the consumer."""
    loop = asyncio.get_event_loop()
    
    # Setup signal handlers for graceful shutdown
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(shutdown(s, loop))
            )
    
    logger.info("=" * 50)
    logger.info("AI News Consumer - Starting")
    logger.info("=" * 50)
    logger.info("Listening to Kafka topic: news-raw")
    logger.info("Processing: Kid/Pro summaries, Jargon extraction, FactCheck")
    logger.info("=" * 50)
    
    try:
        await ai_news_consumer.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Consumer error: {e}")
    finally:
        await ai_news_consumer.stop()
        logger.info("Consumer shutdown complete")


def run():
    """Synchronous entry point for the consumer."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
