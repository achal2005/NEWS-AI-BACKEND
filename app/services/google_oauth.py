"""Google OAuth Service for authentication."""
import httpx
from typing import Optional, Dict, Any
from dataclasses import dataclass
import logging

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


@dataclass
class GoogleUser:
    """Represents a Google user from OAuth."""
    id: str
    email: str
    name: str
    picture: Optional[str] = None
    verified_email: bool = True


class GoogleOAuthService:
    """Service for Google OAuth2 authentication."""
    
    def __init__(self):
        self.client_id = settings.google_client_id
        self.client_secret = settings.google_client_secret
        self.redirect_uri = settings.google_redirect_uri
    
    def get_authorization_url(self, state: Optional[str] = None) -> str:
        """
        Generate Google OAuth authorization URL.
        
        Args:
            state: Optional state parameter for CSRF protection
            
        Returns:
            Authorization URL to redirect user to
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "consent",
        }
        
        if state:
            params["state"] = state
        
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{GOOGLE_AUTH_URL}?{query_string}"
    
    async def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access tokens.
        
        Args:
            code: Authorization code from Google
            
        Returns:
            Token response containing access_token, id_token, etc.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
            )
            
            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.text}")
                raise ValueError("Failed to exchange authorization code")
            
            return response.json()
    
    async def get_user_info(self, access_token: str) -> GoogleUser:
        """
        Get user information from Google using access token.
        
        Args:
            access_token: Valid Google access token
            
        Returns:
            GoogleUser object with user details
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get user info: {response.text}")
                raise ValueError("Failed to get user information")
            
            data = response.json()
            
            return GoogleUser(
                id=data["id"],
                email=data["email"],
                name=data.get("name", data["email"].split("@")[0]),
                picture=data.get("picture"),
                verified_email=data.get("verified_email", True),
            )
    
    async def authenticate(self, code: str) -> GoogleUser:
        """
        Complete OAuth flow: exchange code and get user info.
        
        Args:
            code: Authorization code from Google callback
            
        Returns:
            GoogleUser with authenticated user's details
        """
        tokens = await self.exchange_code_for_tokens(code)
        access_token = tokens["access_token"]
        return await self.get_user_info(access_token)


# Singleton instance
google_oauth_service = GoogleOAuthService()
