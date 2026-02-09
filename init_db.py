"""Initialize the database tables."""
from app.db.session import engine, Base
from app.db.models import (
    User, TasteProfile, Article, ArticleSummary, ArticleJargon,
    PointsLedger, WeeklyQuiz, QuizQuestion, QuizAttempt, QuizAnswer, LeaderboardCache
)

if __name__ == "__main__":
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully!")
