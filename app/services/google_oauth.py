"""Google OAuth Service for authentication."""
import httpx
from typing import Optional, Dict, Any
from dataclasses import dataclass
import logging
import urllib.parse
import json
import base64

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
# Standard Google userinfo endpoint (v3 — stable and well-documented)
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


@dataclass
class GoogleUser:
    """Represents a Google user from OAuth."""
    id: str
    email: str
    name: str
    picture: Optional[str] = None
    verified_email: bool = True


def _decode_id_token_unverified(id_token: str) -> Optional[Dict[str, Any]]:
    """
    Decode the ID token payload WITHOUT signature verification.
    
    This is safe because we received the token directly from Google's
    token endpoint over HTTPS (not from the client). We use this to
    extract user info without an extra HTTP call.
    """
    try:
        # JWT = header.payload.signature — we want the payload
        parts = id_token.split(".")
        if len(parts) != 3:
            return None
        
        # Base64url decode the payload (add padding if needed)
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)
    except Exception as e:
        logger.warning(f"Failed to decode ID token: {e}")
        return None


class GoogleOAuthService:
    """Service for Google OAuth2 authentication."""
    
    def __init__(self):
        self.client_id = settings.google_client_id
        self.client_secret = settings.google_client_secret
        self.redirect_uri = settings.google_redirect_uri
    
    def get_authorization_url(self, state: Optional[str] = None) -> Optional[str]:
        """
        Generate Google OAuth authorization URL.
        
        Args:
            state: Optional state parameter for CSRF protection
            
        Returns:
            Authorization URL to redirect user to, or None if not configured
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
        
        if not self.client_id:
            logger.error("Google Client ID is missing.")
            return None

        query_string = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items())
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
                logger.error(f"Token exchange failed ({response.status_code}): {response.text}")
                raise ValueError(f"Failed to exchange authorization code: {response.text}")
            
            result: Dict[str, Any] = response.json()
            return result
    
    async def get_user_info(self, access_token: str) -> GoogleUser:
        """
        Get user information from Google using the OIDC userinfo endpoint.
        
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
                logger.error(f"Failed to get user info ({response.status_code}): {response.text}")
                raise ValueError("Failed to get user information from Google")
            
            data: Dict[str, Any] = response.json()
            
            return GoogleUser(
                id=data.get("sub", data.get("id", "")),
                email=data["email"],
                name=data.get("name", data["email"].split("@")[0]),
                picture=data.get("picture"),
                verified_email=data.get("email_verified", True),
            )
    
    async def authenticate(self, code: str) -> GoogleUser:
        """
        Complete OAuth flow: exchange code and get user info.
        
        Primary path: decode ID token (no extra HTTP call needed).
        Fallback: call OIDC userinfo endpoint with access token.
        
        Args:
            code: Authorization code from Google callback
            
        Returns:
            GoogleUser with authenticated user's details
        """
        tokens = await self.exchange_code_for_tokens(code)
        
        # Primary path: extract user info from ID token (faster, no extra call)
        id_token = tokens.get("id_token")
        if id_token:
            claims = _decode_id_token_unverified(id_token)
            if claims and claims.get("email"):
                logger.info("Extracted user info from ID token (no extra HTTP call)")
                return GoogleUser(
                    id=claims.get("sub", ""),
                    email=claims["email"],
                    name=claims.get("name", claims["email"].split("@")[0]),
                    picture=claims.get("picture"),
                    verified_email=claims.get("email_verified", True),
                )
        
        # Fallback: call OIDC userinfo endpoint
        logger.info("ID token missing or incomplete, falling back to userinfo endpoint")
        access_token = tokens["access_token"]
        return await self.get_user_info(access_token)


# Singleton instance
google_oauth_service = GoogleOAuthService()

