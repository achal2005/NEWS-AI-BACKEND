"""
AI News Consumer Service

Kafka consumer that processes raw news articles:
1. Generates Kid Mode and Pro Mode summaries using Gemini 2.0 Flash
2. Extracts technical jargon with definitions
3. Checks veracity using Google FactCheck API
4. Saves processed data to PostgreSQL
"""

import json
import asyncio
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import SessionLocal, Article, ArticleSummary, ArticleJargon
from app.services.gemini import gemini_service
from app.services.factcheck import factcheck_service
from app.services.kafka_service import KafkaConsumerService

settings = get_settings()
logger = logging.getLogger(__name__)


class AINewsConsumer:
    """
    Kafka consumer that processes raw news articles with AI.
    
    Listens to 'news-raw' topic and:
    - Generates dual summaries (Kid Mode / Pro Mode)
    - Extracts technical jargon with definitions
    - Checks news veracity via FactCheck API
    - Saves all processed data to PostgreSQL
    """
    
    def __init__(self):
        self.consumer = KafkaConsumerService(
            topic="news-raw",
            group_id="ai-processor-group"
        )
        self.running = False
    
    async def start(self):
        """Start the consumer and begin processing messages."""
        logger.info("Starting AI News Consumer...")
        self.running = True
        
        try:
            await self.consumer.start()
            logger.info("AI News Consumer connected to Kafka")
            
            async for message in self.consumer.consume():
                if not self.running:
                    break
                    
                try:
                    await self.process_article(message)
                except Exception as e:
                    logger.error(f"Error processing article: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Consumer error: {e}")
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the consumer."""
        self.running = False
        await self.consumer.stop()
        logger.info("AI News Consumer stopped")
    
    async def process_article(self, article_data: dict):
        """
        Process a raw article with AI services.
        
        Args:
            article_data: Dict containing article info from Kafka
        """
        article_id = article_data.get("id")
        title = article_data.get("title", "")
        content = article_data.get("content", "")
        
        if not article_id or not content:
            logger.warning("Received article without id or content, skipping")
            return
        
        logger.info(f"Processing article: {title[:50]}...")
        
        # Run AI tasks concurrently
        kid_summary_task = self._generate_summary(content, "kid")
        pro_summary_task = self._generate_summary(content, "pro")
        jargon_task = self._extract_jargon(content)
        factcheck_task = self._check_veracity(title, content)
        
        # Wait for all tasks
        kid_summary, pro_summary, jargon_list, veracity_data = await asyncio.gather(
            kid_summary_task,
            pro_summary_task,
            jargon_task,
            factcheck_task,
            return_exceptions=True
        )
        
        # Handle any exceptions from concurrent tasks
        if isinstance(kid_summary, Exception):
            logger.error(f"Kid summary generation failed: {kid_summary}")
            kid_summary = None
        if isinstance(pro_summary, Exception):
            logger.error(f"Pro summary generation failed: {pro_summary}")
            pro_summary = None
        if isinstance(jargon_list, Exception):
            logger.error(f"Jargon extraction failed: {jargon_list}")
            jargon_list = []
        if isinstance(veracity_data, Exception):
            logger.error(f"Veracity check failed: {veracity_data}")
            veracity_data = {"veracity_score": None, "claims": []}
        
        # Save to database
        await self._save_to_database(
            article_id=article_id,
            kid_summary=kid_summary,
            pro_summary=pro_summary,
            jargon_list=jargon_list,
            veracity_data=veracity_data
        )
        
        logger.info(f"Completed processing article: {article_id}")
    
    async def _generate_summary(self, content: str, mode: str) -> Optional[str]:
        """Generate article summary using Gemini."""
        try:
            summary = await gemini_service.generate_summary(content, mode)
            return summary
        except Exception as e:
            logger.error(f"Summary generation error ({mode}): {e}")
            return None
    
    async def _extract_jargon(self, content: str) -> list:
        """Extract technical jargon from article."""
        try:
            jargon = await gemini_service.extract_jargon(content)
            return jargon if isinstance(jargon, list) else []
        except Exception as e:
            logger.error(f"Jargon extraction error: {e}")
            return []
    
    async def _check_veracity(self, title: str, content: str) -> dict:
        """Check article veracity using FactCheck API."""
        try:
            # Use title for primary claim check
            result = await factcheck_service.check_claim(title)
            
            # If no results from title, try first sentence of content
            if result.get("status") == "no_matching_claims" and content:
                first_sentence = content.split('.')[0][:200]
                result = await factcheck_service.check_claim(first_sentence)
            
            return result
        except Exception as e:
            logger.error(f"Veracity check error: {e}")
            return {"veracity_score": None, "claims": [], "status": "error"}
    
    async def _save_to_database(
        self,
        article_id: str,
        kid_summary: Optional[str],
        pro_summary: Optional[str],
        jargon_list: list,
        veracity_data: dict
    ):
        """Save processed article data to PostgreSQL."""
        db: Session = SessionLocal()
        
        try:
            # Get or verify article exists
            article = db.query(Article).filter(Article.id == article_id).first()
            
            if not article:
                logger.warning(f"Article {article_id} not found in database")
                return
            
            # Update article with veracity score
            if veracity_data.get("veracity_score") is not None or veracity_data.get("claims"):
                article.veracity_score = veracity_data.get("veracity_score")
                article.veracity_claims = veracity_data.get("claims", [])
                article.veracity_checked_at = datetime.utcnow()
                logger.info(f"Veracity score for {article_id}: {veracity_data.get('veracity_score')}")
            
            # Save Kid summary
            if kid_summary:
                existing_kid = db.query(ArticleSummary).filter(
                    ArticleSummary.article_id == article_id,
                    ArticleSummary.mode == "kid"
                ).first()
                
                if existing_kid:
                    existing_kid.summary = kid_summary
                    existing_kid.generated_at = datetime.utcnow()
                else:
                    db.add(ArticleSummary(
                        article_id=article_id,
                        mode="kid",
                        summary=kid_summary
                    ))
            
            # Save Pro summary
            if pro_summary:
                existing_pro = db.query(ArticleSummary).filter(
                    ArticleSummary.article_id == article_id,
                    ArticleSummary.mode == "pro"
                ).first()
                
                if existing_pro:
                    existing_pro.summary = pro_summary
                    existing_pro.generated_at = datetime.utcnow()
                else:
                    db.add(ArticleSummary(
                        article_id=article_id,
                        mode="pro",
                        summary=pro_summary
                    ))
            
            # Save jargon terms
            if jargon_list:
                # Clear existing jargon for this article
                db.query(ArticleJargon).filter(
                    ArticleJargon.article_id == article_id
                ).delete()
                
                # Add new jargon terms
                for item in jargon_list:
                    if isinstance(item, dict) and item.get("term"):
                        db.add(ArticleJargon(
                            article_id=article_id,
                            term=item.get("term", ""),
                            definition=item.get("definition", ""),
                            difficulty=item.get("difficulty", "intermediate")
                        ))
            
            db.commit()
            logger.info(f"Saved processed data for article {article_id}")
            
        except Exception as e:
            db.rollback()
            logger.error(f"Database save error: {e}")
            raise
        finally:
            db.close()


# Create singleton instance
ai_news_consumer = AINewsConsumer()


async def run_consumer():
    """Entry point to run the consumer."""
    await ai_news_consumer.start()


if __name__ == "__main__":
    asyncio.run(run_consumer())
