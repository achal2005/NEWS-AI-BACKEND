from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID


# ============ Auth Schemas ============

class UserCreate(BaseModel):
    """Schema for user registration with age and news preferences."""
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=2, max_length=100)
    age: Optional[int] = Field(None, ge=5, le=120)
    preferred_categories: Optional[List[str]] = Field(default_factory=list)
    summary_mode: Optional[str] = Field(default="pro", pattern="^(kid|pro)$")


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """Schema for user response."""
    id: UUID
    email: str
    display_name: Optional[str]
    avatar_url: Optional[str] = None
    profile_complete: bool = False
    age: Optional[int] = None
    total_reading_time_seconds: int = 0
    articles_read_count: int = 0
    created_at: datetime
    taste_profile: Optional["TasteProfileResponse"] = None
    
    class Config:
        from_attributes = True


class Token(BaseModel):
    """Schema for JWT token response."""
    access_token: str
    token_type: str = "bearer"
    profile_complete: Optional[bool] = None


# ============ Article Schemas ============

class ArticleCreate(BaseModel):
    """Schema for article creation."""
    title: str = Field(max_length=500)
    content: str
    source_url: Optional[str] = None
    category: Optional[str] = None
    published_at: Optional[datetime] = None


class ArticleSummaryResponse(BaseModel):
    """Schema for article summary response."""
    mode: str
    summary: str
    generated_at: datetime
    
    class Config:
        from_attributes = True


class ArticleJargonResponse(BaseModel):
    """Schema for article jargon response."""
    term: str
    definition: str
    difficulty: str
    
    class Config:
        from_attributes = True


class ArticleResponse(BaseModel):
    """Schema for article response."""
    id: UUID
    title: str
    content: str
    source_url: Optional[str]
    category: Optional[str]
    published_at: Optional[datetime]
    ingested_at: datetime
    summaries: List[ArticleSummaryResponse] = []
    jargon: List[ArticleJargonResponse] = []
    
    class Config:
        from_attributes = True


class ArticleListResponse(BaseModel):
    """Schema for paginated article list."""
    items: List[ArticleResponse]
    total: int
    page: int
    page_size: int


# ============ Profile Schemas ============

class TasteProfileUpdate(BaseModel):
    """Schema for updating taste profile."""
    preferred_categories: Optional[List[str]] = None
    summary_mode: Optional[str] = Field(None, pattern="^(kid|pro)$")
    reading_level: Optional[int] = Field(None, ge=1, le=10)
    topic_weights: Optional[dict] = None


class TasteProfileResponse(BaseModel):
    """Schema for taste profile response."""
    preferred_categories: List[str]
    summary_mode: str
    reading_level: int
    topic_weights: dict
    
    class Config:
        from_attributes = True


# ============ Gamification Schemas ============

class PointsResponse(BaseModel):
    """Schema for points response."""
    points: int
    action_type: str
    earned_at: datetime
    
    class Config:
        from_attributes = True


class PointsHistoryResponse(BaseModel):
    """Schema for points history response."""
    items: List[PointsResponse]
    total_points: int


class LeaderboardEntry(BaseModel):
    """Schema for leaderboard entry with quiz and reading stats."""
    rank: int
    user_id: UUID
    display_name: str
    weekly_points: int
    quiz_accuracy: Optional[float] = None  # Percentage 0-100
    reading_time_minutes: Optional[int] = None
    articles_read: Optional[int] = None


class LeaderboardResponse(BaseModel):
    """Schema for leaderboard response."""
    entries: List[LeaderboardEntry]
    week_start: datetime
    user_rank: Optional[int] = None


# ============ Quiz Schemas ============

class QuizQuestionResponse(BaseModel):
    """Schema for quiz question response."""
    id: UUID
    question: str
    options: List[str]
    points_value: int
    
    class Config:
        from_attributes = True


class QuizResponse(BaseModel):
    """Schema for quiz response."""
    id: UUID
    week_start: datetime
    week_end: datetime
    questions: List[QuizQuestionResponse]
    
    class Config:
        from_attributes = True


class QuizAnswerSubmit(BaseModel):
    """Schema for submitting quiz answer."""
    question_id: UUID
    selected_answer: str


class QuizSubmit(BaseModel):
    """Schema for submitting quiz."""
    answers: List[QuizAnswerSubmit]


class QuizResultResponse(BaseModel):
    """Schema for quiz result response."""
    score: int
    max_score: int
    points_earned: int
    correct_answers: int
    total_questions: int
