import json
import logging
from typing import Optional
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class KafkaProducerService:
    """Kafka producer for publishing news events."""
    
    def __init__(self):
        self.producer: Optional[AIOKafkaProducer] = None
    
    async def start(self):
        """Start the Kafka producer."""
        self.producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        await self.producer.start()
        logger.info("Kafka producer started")
    
    async def stop(self):
        """Stop the Kafka producer."""
        if self.producer:
            await self.producer.stop()
            logger.info("Kafka producer stopped")
    
    async def publish_raw_article(self, article_data: dict):
        """Publish a raw article to the news-raw topic."""
        if not self.producer:
            raise RuntimeError("Producer not started")
        
        await self.producer.send_and_wait(
            topic="news-raw",
            value=article_data
        )
        logger.info(f"Published article to news-raw: {article_data.get('title', 'Unknown')}")
    
    async def publish_summarized_article(self, article_data: dict):
        """Publish a summarized article to the news-summarized topic."""
        if not self.producer:
            raise RuntimeError("Producer not started")
        
        await self.producer.send_and_wait(
            topic="news-summarized",
            value=article_data
        )
        logger.info(f"Published article to news-summarized: {article_data.get('title', 'Unknown')}")
    
    async def publish_user_event(self, event_data: dict):
        """Publish a user event for analytics."""
        if not self.producer:
            raise RuntimeError("Producer not started")
        
        await self.producer.send_and_wait(
            topic="user-events",
            value=event_data
        )
        logger.debug(f"Published user event: {event_data.get('event_type', 'Unknown')}")


class KafkaConsumerService:
    """Kafka consumer for processing news events."""
    
    def __init__(self, topic: str, group_id: str):
        self.topic = topic
        self.group_id = group_id
        self.consumer: Optional[AIOKafkaConsumer] = None
    
    async def start(self):
        """Start the Kafka consumer."""
        self.consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=self.group_id,
            value_deserializer=lambda v: json.loads(v.decode('utf-8'))
        )
        await self.consumer.start()
        logger.info(f"Kafka consumer started for topic: {self.topic}")
    
    async def stop(self):
        """Stop the Kafka consumer."""
        if self.consumer:
            await self.consumer.stop()
            logger.info(f"Kafka consumer stopped for topic: {self.topic}")
    
    async def consume(self):
        """Consume messages from the topic."""
        if not self.consumer:
            raise RuntimeError("Consumer not started")
        
        async for message in self.consumer:
            yield message.value


# Singleton instances
kafka_producer = KafkaProducerService()
