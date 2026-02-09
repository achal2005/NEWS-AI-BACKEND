import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey, JSON, Date, Float
from sqlalchemy.orm import relationship
from app.db.session import Base


def generate_uuid():
    return str(uuid.uuid4())


class User(Base):
    """User model for authentication and profile."""
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)  # Nullable for OAuth users
    display_name = Column(String(100), nullable=True)  # Set during profile completion
    age = Column(Integer, nullable=True)  # User age for Kid/Pro mode defaults
    
    # Google OAuth fields
    google_id = Column(String(255), unique=True, nullable=True, index=True)
    avatar_url = Column(String(1000), nullable=True)
    profile_complete = Column(Boolean, default=False)  # True after user completes registration
    
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    total_reading_time_seconds = Column(Integer, default=0)  # Cumulative reading time
    articles_read_count = Column(Integer, default=0)  # Total articles read
    
    # Relationships
    taste_profile = relationship("TasteProfile", back_populates="user", uselist=False)
    points = relationship("PointsLedger", back_populates="user")
    quiz_attempts = relationship("QuizAttempt", back_populates="user")


class TasteProfile(Base):
    """User taste profile for personalization."""
    __tablename__ = "taste_profiles"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    preferred_categories = Column(JSON, default=list)  # ["tech", "science", "sports"]
    summary_mode = Column(String(10), default="pro")  # "kid" or "pro"
    reading_level = Column(Integer, default=5)  # 1-10 scale
    topic_weights = Column(JSON, default=dict)  # {"ai": 0.8, "crypto": 0.2}
    
    # Relationships
    user = relationship("User", back_populates="taste_profile")


class Article(Base):
    """News article model."""
    __tablename__ = "articles"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    source_url = Column(String(1000), nullable=True)
    source_name = Column(String(255), nullable=True)
    author = Column(String(255), nullable=True)
    category = Column(String(100), nullable=True, index=True)
    image_url = Column(String(1000), nullable=True)
    published_at = Column(DateTime, nullable=True)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    
    # Fact checking
    veracity_score = Column(Float, nullable=True)  # 0-100 score
    fact_check_claims = Column(JSON, default=list)  # List of claim reviews
    
    # Relationships
    summaries = relationship("ArticleSummary", back_populates="article")
    jargon = relationship("ArticleJargon", back_populates="article")
    quiz_questions = relationship("QuizQuestion", back_populates="article")


class ArticleSummary(Base):
    """Cached article summaries for different modes."""
    __tablename__ = "article_summaries"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    article_id = Column(String(36), ForeignKey("articles.id"), nullable=False)
    mode = Column(String(10), nullable=False)  # "kid" or "pro"
    summary = Column(Text, nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    article = relationship("Article", back_populates="summaries")


class ArticleJargon(Base):
    """Jargon terms extracted from articles."""
    __tablename__ = "article_jargon"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    article_id = Column(String(36), ForeignKey("articles.id"), nullable=False)
    term = Column(String(255), nullable=False)
    definition = Column(Text, nullable=False)
    difficulty = Column(String(20), default="medium")  # easy, medium, hard
    
    # Relationships
    article = relationship("Article", back_populates="jargon")


class PointsLedger(Base):
    """Points earned by users for various actions."""
    __tablename__ = "points_ledger"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    points = Column(Integer, nullable=False)
    action_type = Column(String(50), nullable=False)  # "read_article", "quiz_correct", etc.
    reference_id = Column(String(36), nullable=True)  # Article or quiz ID
    earned_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="points")


class WeeklyQuiz(Base):
    """Weekly quiz generated from articles."""
    __tablename__ = "weekly_quizzes"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    week_start = Column(Date, nullable=False, index=True)
    week_end = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    questions = relationship("QuizQuestion", back_populates="quiz")
    attempts = relationship("QuizAttempt", back_populates="quiz")


class QuizQuestion(Base):
    """Individual quiz question."""
    __tablename__ = "quiz_questions"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    quiz_id = Column(String(36), ForeignKey("weekly_quizzes.id"), nullable=False)
    article_id = Column(String(36), ForeignKey("articles.id"), nullable=True)
    question = Column(Text, nullable=False)
    options = Column(JSON, nullable=False)  # ["option1", "option2", "option3", "option4"]
    correct_answer = Column(String(500), nullable=False)
    points_value = Column(Integer, default=20)
    
    # Relationships
    quiz = relationship("WeeklyQuiz", back_populates="questions")
    article = relationship("Article", back_populates="quiz_questions")


class QuizAttempt(Base):
    """User's attempt at a quiz."""
    __tablename__ = "quiz_attempts"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    quiz_id = Column(String(36), ForeignKey("weekly_quizzes.id"), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    score = Column(Integer, default=0)
    
    # Relationships
    user = relationship("User", back_populates="quiz_attempts")
    quiz = relationship("WeeklyQuiz", back_populates="attempts")
    answers = relationship("QuizAnswer", back_populates="attempt")


class QuizAnswer(Base):
    """User's answer to a quiz question."""
    __tablename__ = "quiz_answers"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    attempt_id = Column(String(36), ForeignKey("quiz_attempts.id"), nullable=False)
    question_id = Column(String(36), ForeignKey("quiz_questions.id"), nullable=False)
    selected_answer = Column(String(500), nullable=False)
    is_correct = Column(Boolean, nullable=False)
    
    # Relationships
    attempt = relationship("QuizAttempt", back_populates="answers")


class LeaderboardCache(Base):
    """Cached leaderboard for performance."""
    __tablename__ = "leaderboard_cache"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    week_start = Column(Date, nullable=False, index=True)
    weekly_points = Column(Integer, default=0)
    rank = Column(Integer, nullable=True)
    articles_read = Column(Integer, default=0)
    quiz_accuracy = Column(Float, nullable=True)
    reading_time_minutes = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)
