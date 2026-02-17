"""
Seed quizzes from the past month's articles using Gemini AI.

Usage:
    cd backend
    python seed_monthly_quizzes.py

This will:
1. Find all articles from the past 30 days
2. Group them by week
3. For each week, create a WeeklyQuiz with AI-generated questions
4. Store everything in the database
"""
import asyncio
import sys
import os
from datetime import datetime, date, timedelta
from pathlib import Path

# Ensure the backend directory is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

from app.db.session import SessionLocal, Base, engine
from app.db.models import Article, WeeklyQuiz, QuizQuestion
from app.services.gemini import gemini_service

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)


async def seed_quizzes():
    db = SessionLocal()
    try:
        today = date.today()

        # Generate quizzes for the past 4 weeks
        for weeks_ago in range(4, 0, -1):
            week_start = today - timedelta(days=today.weekday() + 7 * weeks_ago)
            week_end = week_start + timedelta(days=6)
            week_start_dt = datetime.combine(week_start, datetime.min.time())
            week_end_dt = datetime.combine(week_end + timedelta(days=1), datetime.min.time())

            # Check if quiz already exists for this week
            existing = db.query(WeeklyQuiz).filter(
                WeeklyQuiz.week_start == week_start
            ).first()
            if existing:
                q_count = len(existing.questions)
                print(f"  ⏭  Quiz for {week_start} already exists ({q_count} questions), skipping")
                continue

            # Get articles from this week
            articles = db.query(Article).filter(
                Article.ingested_at >= week_start_dt,
                Article.ingested_at < week_end_dt
            ).order_by(Article.ingested_at.desc()).limit(5).all()

            if not articles:
                # Fallback: get any recent articles
                articles = db.query(Article).order_by(
                    Article.ingested_at.desc()
                ).limit(5).all()

            if not articles:
                print(f"  ⚠  No articles available, skipping week {week_start}")
                continue

            # Create the quiz
            quiz = WeeklyQuiz(
                week_start=week_start,
                week_end=week_end,
                is_active=True
            )
            db.add(quiz)
            db.commit()
            db.refresh(quiz)

            total_questions = 0
            for article in articles:
                try:
                    print(f"    📰 Generating questions from: {article.title[:60]}...")
                    questions = await gemini_service.generate_quiz_questions(
                        article.content,
                        num_questions=2
                    )
                    for q in questions:
                        question = QuizQuestion(
                            quiz_id=quiz.id,
                            article_id=article.id,
                            question=q.get("question", ""),
                            options=q.get("options", []),
                            correct_answer=q.get("correct_answer", ""),
                            points_value=20
                        )
                        db.add(question)
                        total_questions += 1
                except Exception as e:
                    print(f"    ⚠  Failed for article '{article.title[:40]}': {e}")
                    continue

            db.commit()
            print(f"  ✅ Week {week_start} → {week_end}: {total_questions} questions from {len(articles)} articles")

        # Summary
        all_quizzes = db.query(WeeklyQuiz).filter(
            WeeklyQuiz.is_active == True
        ).order_by(WeeklyQuiz.week_start.desc()).all()
        print(f"\n📊 Total active quizzes: {len(all_quizzes)}")
        for q in all_quizzes:
            print(f"   • {q.week_start} → {q.week_end}: {len(q.questions)} questions")

    finally:
        db.close()


if __name__ == "__main__":
    print("🧠 Seeding monthly quizzes from articles...\n")
    asyncio.run(seed_quizzes())
    print("\n✅ Done!")
