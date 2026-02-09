"""NewsAPI.org Service for fetching live news articles."""
import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class NewsAPIService:
    """Service for fetching news from NewsAPI.org."""
    
    def __init__(self):
        self.api_key = settings.news_api_key
        self.base_url = settings.news_api_base_url
        self._last_fetch: Optional[datetime] = None
        self._cache: List[Dict] = []
        self._cache_duration = timedelta(minutes=30)
    
    async def fetch_top_headlines(
        self,
        category: Optional[str] = None,
        country: str = "us",
        page_size: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Fetch top headlines from NewsAPI.
        
        Args:
            category: News category (business, technology, science, health, sports, entertainment)
            country: ISO country code
            page_size: Number of articles to fetch (max 100)
            
        Returns:
            List of article dictionaries
        """
        if not self.api_key:
            logger.warning("NEWS_API_KEY not configured, returning empty list")
            return []
        
        params = {
            "apiKey": self.api_key,
            "country": country,
            "pageSize": min(page_size, 100),
        }
        
        if category:
            params["category"] = category.lower()
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/top-headlines",
                    params=params,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    logger.error(f"NewsAPI error: {response.text}")
                    return []
                
                data = response.json()
                articles = data.get("articles", [])
                
                # Transform to our format
                return [self._transform_article(article) for article in articles if article.get("content")]
                
        except Exception as e:
            logger.error(f"Error fetching news: {e}")
            return []
    
    async def search_news(
        self,
        query: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page_size: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Search for news articles.
        
        Args:
            query: Search query
            from_date: Start date for search
            to_date: End date for search
            page_size: Number of results
            
        Returns:
            List of matching articles
        """
        if not self.api_key:
            return []
        
        params = {
            "apiKey": self.api_key,
            "q": query,
            "pageSize": min(page_size, 100),
            "sortBy": "publishedAt",
            "language": "en",
        }
        
        if from_date:
            params["from"] = from_date.isoformat()
        if to_date:
            params["to"] = to_date.isoformat()
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/everything",
                    params=params,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    logger.error(f"NewsAPI search error: {response.text}")
                    return []
                
                data = response.json()
                articles = data.get("articles", [])
                
                return [self._transform_article(article) for article in articles if article.get("content")]
                
        except Exception as e:
            logger.error(f"Error searching news: {e}")
            return []
    
    async def fetch_by_categories(
        self,
        categories: List[str],
        articles_per_category: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fetch articles from multiple categories.
        
        Args:
            categories: List of category names
            articles_per_category: How many articles per category
            
        Returns:
            Combined list of articles from all categories
        """
        all_articles = []
        
        for category in categories:
            articles = await self.fetch_top_headlines(
                category=category,
                page_size=articles_per_category
            )
            all_articles.extend(articles)
        
        return all_articles
    
    def _transform_article(self, article: Dict) -> Dict[str, Any]:
        """Transform NewsAPI article to our format."""
        # Extract category from source or default
        source_name = article.get("source", {}).get("name", "Unknown")
        
        # Determine category based on content or source
        content = article.get("content", "") or article.get("description", "")
        category = self._infer_category(content, source_name)
        
        return {
            "title": article.get("title", "Untitled"),
            "content": article.get("content", article.get("description", "")),
            "description": article.get("description", ""),
            "source_url": article.get("url", ""),
            "source_name": source_name,
            "image_url": article.get("urlToImage"),
            "published_at": article.get("publishedAt"),
            "author": article.get("author"),
            "category": category,
        }
    
    def _infer_category(self, content: str, source: str) -> str:
        """Infer article category from content and source."""
        content_lower = content.lower()
        source_lower = source.lower()
        
        # Tech keywords
        if any(word in content_lower for word in ["ai", "tech", "software", "app", "startup", "google", "apple", "microsoft"]):
            return "Technology"
        
        # Science keywords
        if any(word in content_lower for word in ["science", "research", "study", "discovery", "nasa", "space"]):
            return "Science"
        
        # Business keywords
        if any(word in content_lower for word in ["market", "stock", "economy", "business", "company", "investment"]):
            return "Business"
        
        # Health keywords
        if any(word in content_lower for word in ["health", "medical", "doctor", "hospital", "disease", "vaccine"]):
            return "Health"
        
        # Sports keywords
        if any(word in content_lower for word in ["sport", "game", "team", "player", "score", "championship"]):
            return "Sports"
        
        # Entertainment keywords
        if any(word in content_lower for word in ["movie", "music", "celebrity", "entertainment", "show", "film"]):
            return "Entertainment"
        
        return "General"


# Singleton instance
news_api_service = NewsAPIService()
