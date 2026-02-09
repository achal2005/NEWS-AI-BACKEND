"""
Google FactCheck API Service

Checks news content against Google FactCheck Claims API
to determine veracity/credibility score.
"""

import httpx
import logging
from typing import Optional, List, Dict
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Google FactCheck API endpoint
FACTCHECK_API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


class FactCheckService:
    """Service for checking claims against Google FactCheck API."""
    
    def __init__(self):
        self.api_key = settings.gemini_api_key  # Can use same API key for Google APIs
        
    async def check_claim(self, claim_text: str, language: str = "en") -> Dict:
        """
        Check a claim against the FactCheck API.
        
        Args:
            claim_text: The claim or news headline to verify
            language: Language code (default: en)
            
        Returns:
            Dict with veracity score and matching claims
        """
        if not self.api_key:
            logger.warning("No API key configured for FactCheck")
            return {"veracity_score": None, "claims": [], "status": "no_api_key"}
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    FACTCHECK_API_URL,
                    params={
                        "key": self.api_key,
                        "query": claim_text[:200],  # Limit query length
                        "languageCode": language
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return self._process_response(data)
                elif response.status_code == 403:
                    logger.warning("FactCheck API access denied - API may not be enabled")
                    return {"veracity_score": None, "claims": [], "status": "access_denied"}
                else:
                    logger.warning(f"FactCheck API returned status {response.status_code}")
                    return {"veracity_score": None, "claims": [], "status": "error"}
                    
        except Exception as e:
            logger.error(f"FactCheck API error: {e}")
            return {"veracity_score": None, "claims": [], "status": "error"}
    
    def _process_response(self, data: Dict) -> Dict:
        """Process FactCheck API response and calculate veracity score."""
        claims = data.get("claims", [])
        
        if not claims:
            return {
                "veracity_score": None,
                "claims": [],
                "status": "no_matching_claims"
            }
        
        processed_claims = []
        total_score = 0
        scored_count = 0
        
        for claim in claims[:5]:  # Process top 5 matching claims
            claim_review = claim.get("claimReview", [{}])[0] if claim.get("claimReview") else {}
            
            rating = claim_review.get("textualRating", "")
            publisher = claim_review.get("publisher", {}).get("name", "Unknown")
            url = claim_review.get("url", "")
            
            # Map textual ratings to numeric score
            score = self._rating_to_score(rating)
            if score is not None:
                total_score += score
                scored_count += 1
            
            processed_claims.append({
                "claim_text": claim.get("text", ""),
                "claimant": claim.get("claimant", "Unknown"),
                "rating": rating,
                "score": score,
                "publisher": publisher,
                "review_url": url
            })
        
        # Calculate average veracity score (0-100)
        veracity_score = round(total_score / scored_count) if scored_count > 0 else None
        
        return {
            "veracity_score": veracity_score,
            "claims": processed_claims,
            "status": "success"
        }
    
    def _rating_to_score(self, rating: str) -> Optional[int]:
        """Convert textual rating to numeric score (0-100)."""
        rating_lower = rating.lower()
        
        # True/Accurate ratings
        if any(word in rating_lower for word in ["true", "accurate", "correct", "verified"]):
            return 100
        
        # Mostly true
        if any(word in rating_lower for word in ["mostly true", "mostly accurate", "largely true"]):
            return 80
        
        # Mixed/Half true
        if any(word in rating_lower for word in ["half true", "mixed", "partly", "partially"]):
            return 50
        
        # Mostly false
        if any(word in rating_lower for word in ["mostly false", "mostly inaccurate", "largely false"]):
            return 20
        
        # False/Fake
        if any(word in rating_lower for word in ["false", "fake", "incorrect", "wrong", "pants on fire"]):
            return 0
        
        # Unverifiable/Unrated
        if any(word in rating_lower for word in ["unverifiable", "unrated", "satire"]):
            return None
        
        return None


# Singleton instance
factcheck_service = FactCheckService()
