# Services module
from app.services.gemini import gemini_service, GeminiService
from app.services.kafka_service import kafka_producer, KafkaProducerService, KafkaConsumerService
from app.services.factcheck import factcheck_service, FactCheckService
from app.services.ai_consumer import ai_news_consumer, AINewsConsumer
from app.services.google_oauth import google_oauth_service, GoogleOAuthService
from app.services.news_api import news_api_service, NewsAPIService

__all__ = [
    "gemini_service", "GeminiService",
    "kafka_producer", "KafkaProducerService", "KafkaConsumerService",
    "factcheck_service", "FactCheckService",
    "ai_news_consumer", "AINewsConsumer",
    "google_oauth_service", "GoogleOAuthService",
    "news_api_service", "NewsAPIService",
]
