import google.generativeai as genai
from typing import Optional, List, Dict
import json
import logging

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Configure Gemini
if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)


class GeminiService:
    """Service for interacting with Gemini 2.0 Flash API."""
    
    def __init__(self):
        self.model = genai.GenerativeModel('gemini-2.0-flash')
    
    async def generate_summary(self, content: str, mode: str = "pro") -> str:
        """
        Generate article summary based on mode.
        
        Args:
            content: The article content to summarize
            mode: "kid" for child-friendly or "pro" for professional
            
        Returns:
            Generated summary text
        """
        if mode == "kid":
            prompt = f"""
Summarize this news article for a 10-year-old reader:
- Use simple words and short sentences
- Explain technical terms with fun analogies
- Keep it under 150 words
- Make it engaging and educational

Article: {content}

Summary:"""
        else:
            prompt = f"""
Provide a professional summary for industry experts:
- Maintain technical accuracy and terminology
- Include key statistics and citations if present
- Highlight industry implications
- Keep it under 300 words

Article: {content}

Summary:"""
        
        try:
            response = await self.model.generate_content_async(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            # Fallback for quota limits: Extract first 3 sentences
            # Split by period but preserve it, and rudimentary cleanup
            sentences = [s.strip() for s in content.split('.') if s.strip()]
            
            if not sentences:
                return "Summary unavailable for this article."
                
            # Take up to 3 sentences, but ensure we don't take too much text if sentences are long
            fallback_summary = ". ".join(sentences[:3]) + "."
            
            # Additional cleanup for potential HTML or weird formatting in fallback
            if len(fallback_summary) > 500:
                fallback_summary = fallback_summary[:497] + "..."
                
            return fallback_summary
    
    async def extract_jargon(self, content: str) -> List[Dict[str, str]]:
        """
        Extract technical jargon and definitions from article.
        
        Args:
            content: The article content to analyze
            
        Returns:
            List of dicts with term, definition, and difficulty
        """
        prompt = f"""
Extract technical terms from this article and provide definitions.
Return ONLY valid JSON array, no other text.

Format: [{{"term": "...", "definition": "...", "difficulty": "basic|intermediate|advanced"}}]

Article: {content}

JSON:"""
        
        try:
            response = await self.model.generate_content_async(prompt)
            text = response.text.strip()
            
            # Clean up response - remove markdown code blocks if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            
            jargon_list = json.loads(text)
            return jargon_list
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing jargon JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Error extracting jargon: {e}")
            raise
    
    async def generate_quiz_questions(
        self, 
        article_content: str, 
        num_questions: int = 3
    ) -> List[Dict]:
        """
        Generate quiz questions from article content.
        
        Args:
            article_content: The article to generate questions from
            num_questions: Number of questions to generate
            
        Returns:
            List of question dicts with question, options, and correct_answer
        """
        prompt = f"""
Generate {num_questions} multiple-choice quiz questions based on this article.
Return ONLY valid JSON array, no other text.

Format: [
  {{
    "question": "Question text?",
    "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
    "correct_answer": "A) Option 1"
  }}
]

Article: {article_content}

JSON:"""
        
        try:
            response = await self.model.generate_content_async(prompt)
            text = response.text.strip()
            
            # Clean up response
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            
            questions = json.loads(text)
            return questions
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing quiz JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Error generating quiz: {e}")
            raise

    async def chat_with_editor(self, article_content: str, question: str) -> str:
        """
        Chat with the AI editor about the article.
        """
        prompt = f"""
        You are a helpful news editor. Answer the reader's question based ONLY on the provided article content.
        
        Article: {article_content}
        
        Reader Question: {question}
        
        Answer (keep it concise and helpful):
        """
        try:
            response = await self.model.generate_content_async(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            return "I apologize, but I'm currently experiencing high traffic. Please try asking again in a moment."


# Singleton instance
gemini_service = GeminiService()
