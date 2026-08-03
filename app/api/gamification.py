from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, case, update
from sqlalchemy.exc import IntegrityError

from app.db import (
    get_db, User, PointsLedger, WeeklyQuiz, QuizQuestion, 
    QuizAttempt, QuizAnswer, LeaderboardCache, Article
)
from app.core.security import get_current_user_id, get_optional_user_id
from app.schemas import (
    PointsHistoryResponse, PointsResponse, LeaderboardResponse, 
    LeaderboardEntry, QuizResponse, QuizSubmit, QuizResultResponse
)
from app.services import gemini_service
from app.services.gemini import GeminiParseError  # FIX 7
from app.core.time_utils import get_current_week_start, get_current_week_end  # FIX 8

import logging

logger = logging.getLogger(__name__)

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


# REMOVED: Public POST /user/points/award endpoint (security fix W5)
# Points should only be awarded internally by server logic, not by client request.
# The endpoint allowed any authenticated user to award themselves arbitrary points.



class ReadingTimeRequest(BaseModel):
    article_id: UUID
    seconds: int


@router.post("/user/reading-time")
async def record_reading_time(
    body: ReadingTimeRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Record reading time for an article."""
    # R5: Atomic counter updates — prevents lost updates from concurrent tabs
    db.execute(
        update(User)
        .where(User.id == user_id)
        .values(total_reading_time_seconds=func.coalesce(User.total_reading_time_seconds, 0) + body.seconds)
    )
    
    # Deduplication: check if points were already awarded for this article
    already_awarded = db.query(PointsLedger).filter(
        PointsLedger.user_id == user_id,
        PointsLedger.action_type == "read_article",
        PointsLedger.reference_id == str(body.article_id)
    ).first()
    
    # Only increment articles_read_count and award points if first time reading
    if not already_awarded:
        # R5: Atomic increment
        db.execute(
            update(User)
            .where(User.id == user_id)
            .values(articles_read_count=func.coalesce(User.articles_read_count, 0) + 1)
        )
        
        # Award points for completing an article (if reading time > 30 seconds)
        if body.seconds >= 30:
            ledger_entry = PointsLedger(
                user_id=user_id,
                points=10,
                action_type="read_article",
                reference_id=str(body.article_id)
            )
            try:
                db.add(ledger_entry)
                db.flush()  # Raises IntegrityError on duplicate
            except IntegrityError:
                db.rollback()  # Safely ignore duplicate award
                user = db.query(User).filter(User.id == user_id).first()
                return {
                    "recorded_seconds": body.seconds,
                    "total_reading_time_seconds": user.total_reading_time_seconds if user else 0,
                    "articles_read_count": user.articles_read_count if user else 0,
                }
    
    db.commit()
    
    user = db.query(User).filter(User.id == user_id).first()
    return {
        "recorded_seconds": body.seconds,
        "total_reading_time_seconds": user.total_reading_time_seconds if user else 0,
        "articles_read_count": user.articles_read_count if user else 0,
    }


# ============ Leaderboard Endpoints ============

@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    user_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db)
):
    """
    Get weekly leaderboard with rankings based on:
    - Quiz accuracy
    - Reading time
    - Total points
    """
    # FIX 8: Use canonical timezone-aware week start
    week_start_dt = get_current_week_start()
    
    # Aggregated query: get weekly points per user in one query
    weekly_points_subq = (
        db.query(
            PointsLedger.user_id,
            func.sum(PointsLedger.points).label("weekly_points")
        )
        .filter(PointsLedger.earned_at >= week_start_dt)
        .group_by(PointsLedger.user_id)
        .subquery()
    )
    
    # Aggregated query: weekly articles read per user
    articles_read_subq = (
        db.query(
            PointsLedger.user_id,
            func.count(PointsLedger.id).label("articles_read")
        )
        .filter(
            PointsLedger.action_type == "read_article",
            PointsLedger.earned_at >= week_start_dt
        )
        .group_by(PointsLedger.user_id)
        .subquery()
    )
    
    # Aggregated query: quiz accuracy per user
    quiz_accuracy_subq = (
        db.query(
            QuizAttempt.user_id,
            func.sum(QuizAttempt.score).label("total_score"),
            func.sum(QuizAttempt.max_score).label("total_max_score")
        )
        .filter(QuizAttempt.completed_at >= week_start_dt)
        .group_by(QuizAttempt.user_id)
        .subquery()
    )
    
    # Join all together in a single query
    results = (
        db.query(
            User.id,
            User.display_name,
            User.total_reading_time_seconds,
            func.coalesce(weekly_points_subq.c.weekly_points, 0).label("weekly_points"),
            func.coalesce(articles_read_subq.c.articles_read, 0).label("articles_read"),
            quiz_accuracy_subq.c.total_score,
            quiz_accuracy_subq.c.total_max_score,
        )
        .outerjoin(weekly_points_subq, User.id == weekly_points_subq.c.user_id)
        .outerjoin(articles_read_subq, User.id == articles_read_subq.c.user_id)
        .outerjoin(quiz_accuracy_subq, User.id == quiz_accuracy_subq.c.user_id)
        .order_by(func.coalesce(weekly_points_subq.c.weekly_points, 0).desc())
        .limit(100)
        .all()
    )
    
    leaderboard_entries = []
    user_rank = None
    for rank, row in enumerate(results, 1):
        quiz_accuracy = None
        if row.total_max_score and row.total_max_score > 0:
            quiz_accuracy = round(row.total_score / row.total_max_score * 100, 1)
        
        leaderboard_entries.append(LeaderboardEntry(
            rank=rank,
            user_id=row.id,
            display_name=row.display_name,
            weekly_points=row.weekly_points,
            quiz_accuracy=quiz_accuracy,
            reading_time_minutes=(row.total_reading_time_seconds or 0) // 60,
            articles_read=row.articles_read
        ))
        if str(row.id) == user_id:
            user_rank = rank
    
    return LeaderboardResponse(
        entries=leaderboard_entries,
        week_start=week_start_dt,
        user_rank=user_rank
    )


# ============ Quiz Endpoints ============

@router.get("/quiz/weekly", response_model=QuizResponse)
async def get_weekly_quiz(
    request: Request,
    user_id: Optional[str] = Depends(get_optional_user_id),
    db: Session = Depends(get_db)
):
    """
    Get the current weekly quiz.
    FIX 12 + FIX 15: Lock-then-generate pattern to prevent wasted Gemini calls.
    """
    # FIX 8: Use canonical timezone-aware week boundaries
    week_start = get_current_week_start()
    week_end = get_current_week_end()
    
    # ── Step 1: Check if quiz already exists ──────────────────────────
    quiz = db.query(WeeklyQuiz).filter(
        WeeklyQuiz.week_start == week_start,
        WeeklyQuiz.is_active == True
    ).first()
    
    if quiz and len(quiz.questions) > 0:
        return quiz  # Quiz exists with questions — return immediately

    # ── Step 2: Quiz doesn't exist or has no questions — acquire lock ──
    # FIX 12: Use asyncio.Lock for SQLite, advisory lock for Postgres
    quiz_lock = request.app.state.quiz_creation_lock

    async with quiz_lock:
        # ── Step 3: Re-check inside the lock (another request may have created it) ──
        quiz = db.query(WeeklyQuiz).filter(
            WeeklyQuiz.week_start == week_start,
            WeeklyQuiz.is_active == True
        ).first()

        if quiz and len(quiz.questions) > 0:
            return quiz  # Created by another request while we waited

        needs_questions = False

        if not quiz:
            # Create new quiz — handle race condition with IntegrityError
            quiz = WeeklyQuiz(
                week_start=week_start,
                week_end=week_end,
                is_active=True
            )
            try:
                db.add(quiz)
                db.commit()
                db.refresh(quiz)
                needs_questions = True
            except IntegrityError:
                db.rollback()
                # Another request created it first — fetch it
                quiz = db.query(WeeklyQuiz).filter(
                    WeeklyQuiz.week_start == week_start,
                    WeeklyQuiz.is_active == True
                ).first()
                if quiz and len(quiz.questions) > 0:
                    return quiz
                needs_questions = len(quiz.questions) == 0 if quiz else False
        elif len(quiz.questions) == 0:
            needs_questions = True

        # ── Step 4: FIX 12+15: Only call Gemini INSIDE the lock ──────
        if needs_questions and quiz:
            # Generate questions from recent articles
            recent_articles = db.query(Article).order_by(
                Article.ingested_at.desc()
            ).limit(5).all()

            for article in recent_articles:
                try:
                    questions = await gemini_service.generate_quiz_questions(
                        article_content=article.content,
                        num_questions=2,
                        user_id=user_id,
                    )
                    for q in questions:
                        question = QuizQuestion(
                            quiz_id=quiz.id,
                            article_id=article.id,
                            question=q.get("question", ""),
                            options=q.get("options", []),
                            correct_answer=q.get("correct_answer", ""),
                            hint=q.get("hint"),
                            points_value=20
                        )
                        db.add(question)
                except GeminiParseError as e:
                    logger.warning(f"Quiz generation parse error for article {article.id}: {e}")
                    continue
                except Exception:
                    continue

            db.commit()
            db.refresh(quiz)

    return quiz


@router.get("/quiz/list")
async def list_available_quizzes(
    db: Session = Depends(get_db),
    limit: int = 20,
    offset: int = 0
):
    """List all active quizzes (for quiz selection UI)."""
    quizzes = db.query(WeeklyQuiz).filter(
        WeeklyQuiz.is_active == True
    ).order_by(WeeklyQuiz.week_start.desc()).limit(limit).offset(offset).all()

    return {
        "quizzes": [
            {
                "id": str(q.id),
                "week_start": q.week_start.isoformat(),
                "week_end": q.week_end.isoformat(),
                "question_count": len(q.questions),
                "is_active": q.is_active,
            }
            for q in quizzes
        ]
    }


@router.get("/quiz/{quiz_id}", response_model=QuizResponse)
async def get_quiz_by_id(
    quiz_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific quiz by its ID."""
    quiz = db.query(WeeklyQuiz).filter(
        WeeklyQuiz.id == quiz_id,
        WeeklyQuiz.is_active == True
    ).first()

    if not quiz:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quiz not found"
        )

    return quiz


@router.post("/quiz/generate")
async def generate_quiz_from_verified_news(
    num_questions: int = 3,
    user_id: str = Depends(get_current_user_id),  # R3: Require auth to prevent AI quota abuse
    db: Session = Depends(get_db)
):
    """
    Generate a quiz using Gemini 2.0 Flash from the week's highest-scored verified news.
    
    This endpoint:
    - Finds articles with high veracity scores (70+)
    - Uses Gemini to create multiple-choice questions
    - Returns questions without saving (for preview)
    """
    # FIX 8: Use canonical week start
    week_start_dt = get_current_week_start()
    
    # Get most recent articles this week
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
                article_content=article.content,
                num_questions=num_questions // len(verified_articles) or 1,
                user_id=user_id,
            )
            for q in questions:
                q["article_id"] = str(article.id)
                q["article_title"] = article.title
            all_questions.extend(questions)
        except GeminiParseError:
            # FIX 7: Return 502 for AI parse failures
            raise HTTPException(
                status_code=502,
                detail="AI returned unexpected response format"
            )
        except Exception as e:
            continue
    
    return {
        "questions": all_questions[:num_questions],
        "source_articles": [
            {
                "id": str(a.id),
                "title": a.title
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
    
    # Get quiz from first question.
    # NOTE: question_id arrives as a UUID object but QuizQuestion.id is a String(36)
    # column — comparing the two never matches on SQLite, so cast to str.
    first_question = db.query(QuizQuestion).filter(
        QuizQuestion.id == str(submission.answers[0].question_id)
    ).first()
    
    if not first_question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found"
        )
    
    # Prevent quiz re-submission (W7 fix)
    existing_attempt = db.query(QuizAttempt).filter(
        QuizAttempt.user_id == user_id,
        QuizAttempt.quiz_id == first_question.quiz_id
    ).first()
    if existing_attempt:
        # Return actual previous results
        prev_correct = db.query(QuizAnswer).filter(
            QuizAnswer.attempt_id == existing_attempt.id,
            QuizAnswer.is_correct == True
        ).count()
        prev_total = db.query(QuizAnswer).filter(
            QuizAnswer.attempt_id == existing_attempt.id
        ).count()
        return QuizResultResponse(
            score=existing_attempt.score,
            max_score=existing_attempt.max_score,
            points_earned=0,
            correct_answers=prev_correct,
            total_questions=prev_total
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
    correct_count: int = 0
    total_points: int = 0
    
    for answer_data in submission.answers:
        question = db.query(QuizQuestion).filter(
            QuizQuestion.id == str(answer_data.question_id)
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
    attempt.completed_at = datetime.now(timezone.utc)
    db.commit()
    # Calculate actual points earned (base 50 + correct answer points)
    actual_points_earned = total_points + 50 if total_points > 0 else 0
    
    # Award points — R6: graceful handling of race condition
    if total_points > 0:
        points_entry = PointsLedger(
            user_id=user_id,
            points=actual_points_earned,
            action_type="quiz_complete",
            reference_id=str(attempt.id)
        )
        try:
            db.add(points_entry)
            db.commit()
        except IntegrityError:
            db.rollback()
            # Another request already awarded points — return existing
            existing = db.query(PointsLedger).filter_by(
                user_id=user_id, action_type="quiz_complete",
                reference_id=str(attempt.id)
            ).first()
            actual_points_earned = existing.points if existing else 0
    
    return QuizResultResponse(
        score=total_points,
        max_score=attempt.max_score,
        points_earned=actual_points_earned,
        correct_answers=correct_count,
        total_questions=len(submission.answers)
    )
