# Services module
from app.services.gemini import gemini_service, GeminiService, GeminiQuotaError, GeminiServiceError, GeminiParseError
from app.services.google_oauth import google_oauth_service, GoogleOAuthService
from app.services.news_api import news_api_service, NewsAPIService
from app.services.rss_aggregator import rss_aggregator_service, RSSAggregatorService

# Kafka is optional — app runs fine without it
try:
    from app.services.kafka_service import kafka_producer, KafkaProducerService, KafkaConsumerService
except ImportError:
    kafka_producer = None
    KafkaProducerService = None
    KafkaConsumerService = None

__all__ = [
    "gemini_service", "GeminiService", "GeminiQuotaError", "GeminiServiceError", "GeminiParseError",
    "kafka_producer", "KafkaProducerService", "KafkaConsumerService",
    "google_oauth_service", "GoogleOAuthService",
    "news_api_service", "NewsAPIService",
    "rss_aggregator_service", "RSSAggregatorService",
]
