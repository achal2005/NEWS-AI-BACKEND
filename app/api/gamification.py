from datetime import datetime, date, timedelta
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.db import (
    get_db, User, PointsLedger, WeeklyQuiz, QuizQuestion, 
    QuizAttempt, QuizAnswer, LeaderboardCache, Article
)
from app.core.security import get_current_user_id
from app.schemas import (
    PointsHistoryResponse, PointsResponse, LeaderboardResponse, 
    LeaderboardEntry, QuizResponse, QuizSubmit, QuizResultResponse
)
from app.services import gemini_service

router = APIRouter(prefix="/api", tags=["Gamification"])


# ============ Points Endpoints ============

@router.get("/user/points", response_model=PointsHistoryResponse)
async def get_points_history(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Get user's points history."""
    points = db.query(PointsLedger).filter(
        PointsLedger.user_id == user_id
    ).order_by(PointsLedger.earned_at.desc()).limit(100).all()
    
    total = db.query(func.sum(PointsLedger.points)).filter(
        PointsLedger.user_id == user_id
    ).scalar() or 0
    
    return PointsHistoryResponse(items=points, total_points=total)


@router.post("/user/points/award")
async def award_points(
    action_type: str,
    points: int,
    reference_id: Optional[UUID] = None,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Award points for an action."""
    # Point values by action type
    point_values = {
        "read_article": 10,
        "quiz_complete": 50,
        "quiz_correct": 20,
        "daily_streak": 15,
        "weekly_streak": 100,
        "learn_jargon": 5,
        "share_article": 10
    }
    
    # Use predefined points or custom value
    actual_points = point_values.get(action_type, points)
    
    ledger_entry = PointsLedger(
        user_id=user_id,
        points=actual_points,
        action_type=action_type,
        reference_id=reference_id
    )
    db.add(ledger_entry)
    db.commit()
    
    return {"points_awarded": actual_points, "action_type": action_type}


@router.post("/user/reading-time")
async def record_reading_time(
    article_id: UUID,
    seconds: int,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Record reading time for an article."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update cumulative reading time
    user.total_reading_time_seconds = (user.total_reading_time_seconds or 0) + seconds
    user.articles_read_count = (user.articles_read_count or 0) + 1
    
    # Award points for completing an article (if reading time > 30 seconds)
    if seconds >= 30:
        ledger_entry = PointsLedger(
            user_id=user_id,
            points=10,
            action_type="read_article",
            reference_id=article_id
        )
        db.add(ledger_entry)
    
    db.commit()
    
    return {
        "recorded_seconds": seconds,
        "total_reading_time_seconds": user.total_reading_time_seconds,
        "articles_read_count": user.articles_read_count
    }


# ============ Leaderboard Endpoints ============

@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """
    Get weekly leaderboard with rankings based on:
    - Quiz accuracy
    - Reading time
    - Total points
    """
    # Get current week start (Monday)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_start_dt = datetime.combine(week_start, datetime.min.time())
    
    # Get all users with their weekly stats
    users_query = db.query(User).all()
    
    entries = []
    for user in users_query:
        # Calculate weekly points
        weekly_points = db.query(func.sum(PointsLedger.points)).filter(
            PointsLedger.user_id == user.id,
            PointsLedger.earned_at >= week_start_dt
        ).scalar() or 0
        
        # Calculate quiz accuracy for this week
        quiz_attempts = db.query(QuizAttempt).filter(
            QuizAttempt.user_id == user.id,
            QuizAttempt.completed_at >= week_start_dt
        ).all()
        
        total_score = sum(a.score for a in quiz_attempts)
        max_score = sum(a.max_score for a in quiz_attempts)
        quiz_accuracy = (total_score / max_score * 100) if max_score > 0 else None
        
        # Get weekly reading stats
        reading_points = db.query(PointsLedger).filter(
            PointsLedger.user_id == user.id,
            PointsLedger.action_type == "read_article",
            PointsLedger.earned_at >= week_start_dt
        ).count()
        
        entries.append({
            "user_id": user.id,
            "display_name": user.display_name,
            "weekly_points": weekly_points,
            "quiz_accuracy": round(quiz_accuracy, 1) if quiz_accuracy else None,
            "reading_time_minutes": (user.total_reading_time_seconds or 0) // 60,
            "articles_read": reading_points
        })
    
    # Sort by weekly points (primary) and quiz accuracy (secondary)
    entries.sort(key=lambda x: (x["weekly_points"], x["quiz_accuracy"] or 0), reverse=True)
    
    # Add ranks
    leaderboard_entries = []
    user_rank = None
    for rank, entry in enumerate(entries[:100], 1):
        leaderboard_entries.append(LeaderboardEntry(
            rank=rank,
            user_id=entry["user_id"],
            display_name=entry["display_name"],
            weekly_points=entry["weekly_points"],
            quiz_accuracy=entry["quiz_accuracy"],
            reading_time_minutes=entry["reading_time_minutes"],
            articles_read=entry["articles_read"]
        ))
        if str(entry["user_id"]) == user_id:
            user_rank = rank
    
    return LeaderboardResponse(
        entries=leaderboard_entries,
        week_start=week_start_dt,
        user_rank=user_rank
    )


# ============ Quiz Endpoints ============

@router.get("/quiz/weekly", response_model=QuizResponse)
async def get_weekly_quiz(
    db: Session = Depends(get_db)
):
    """Get the current weekly quiz."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    quiz = db.query(WeeklyQuiz).filter(
        WeeklyQuiz.week_start == week_start,
        WeeklyQuiz.is_active == True
    ).first()
    
    if not quiz:
        # Create new quiz if none exists
        quiz = WeeklyQuiz(
            week_start=week_start,
            week_end=week_end,
            is_active=True
        )
        db.add(quiz)
        db.commit()
        db.refresh(quiz)
        
        # Generate questions from recent articles
        recent_articles = db.query(Article).order_by(
            Article.ingested_at.desc()
        ).limit(5).all()
        
        for article in recent_articles:
            try:
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
            except Exception:
                continue
        
        db.commit()
        db.refresh(quiz)
    
    return quiz


@router.post("/quiz/generate")
async def generate_quiz_from_verified_news(
    num_questions: int = 3,
    db: Session = Depends(get_db)
):
    """
    Generate a quiz using Gemini 2.0 Flash from the week's highest-scored verified news.
    
    This endpoint:
    - Finds articles with high veracity scores (70+)
    - Uses Gemini to create multiple-choice questions
    - Returns questions without saving (for preview)
    """
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_start_dt = datetime.combine(week_start, datetime.min.time())
    
    # Get highest-scored verified articles from this week
    verified_articles = db.query(Article).filter(
        Article.ingested_at >= week_start_dt,
        Article.veracity_score >= 70  # Only verified news
    ).order_by(
        Article.veracity_score.desc()
    ).limit(3).all()
    
    if not verified_articles:
        # Fallback to any recent articles if no verified ones
        verified_articles = db.query(Article).filter(
            Article.ingested_at >= week_start_dt
        ).order_by(
            Article.ingested_at.desc()
        ).limit(3).all()
    
    if not verified_articles:
        raise HTTPException(
            status_code=404,
            detail="No articles available for quiz generation"
        )
    
    # Generate questions from articles
    all_questions = []
    for article in verified_articles:
        try:
            questions = await gemini_service.generate_quiz_questions(
                article.content,
                num_questions=num_questions // len(verified_articles) or 1
            )
            for q in questions:
                q["article_id"] = str(article.id)
                q["article_title"] = article.title
                q["veracity_score"] = article.veracity_score
            all_questions.extend(questions)
        except Exception as e:
            continue
    
    return {
        "questions": all_questions[:num_questions],
        "source_articles": [
            {
                "id": str(a.id),
                "title": a.title,
                "veracity_score": a.veracity_score
            }
            for a in verified_articles
        ]
    }


@router.post("/quiz/submit", response_model=QuizResultResponse)
async def submit_quiz(
    submission: QuizSubmit,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Submit quiz answers."""
    if not submission.answers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No answers provided"
        )
    
    # Get quiz from first question
    first_question = db.query(QuizQuestion).filter(
        QuizQuestion.id == submission.answers[0].question_id
    ).first()
    
    if not first_question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found"
        )
    
    # Create attempt
    attempt = QuizAttempt(
        user_id=user_id,
        quiz_id=first_question.quiz_id,
        score=0,
        max_score=0
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    
    # Process answers
    correct_count = 0
    total_points = 0
    
    for answer_data in submission.answers:
        question = db.query(QuizQuestion).filter(
            QuizQuestion.id == answer_data.question_id
        ).first()
        
        if not question:
            continue
        
        is_correct = answer_data.selected_answer == question.correct_answer
        if is_correct:
            correct_count += 1
            total_points += question.points_value
        
        answer = QuizAnswer(
            attempt_id=attempt.id,
            question_id=question.id,
            selected_answer=answer_data.selected_answer,
            is_correct=is_correct
        )
        db.add(answer)
        attempt.max_score += question.points_value
    
    attempt.score = total_points
    db.commit()
    
    # Award points
    if total_points > 0:
        points_entry = PointsLedger(
            user_id=user_id,
            points=total_points + 50,  # Base + correct answers
            action_type="quiz_complete",
            reference_id=attempt.id
        )
        db.add(points_entry)
        db.commit()
    
    return QuizResultResponse(
        score=total_points,
        max_score=attempt.max_score,
        points_earned=total_points + 50,
        correct_answers=correct_count,
        total_questions=len(submission.answers)
    )
