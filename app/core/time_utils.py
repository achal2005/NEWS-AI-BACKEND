"""
Shared time utilities for consistent week boundary calculations.

FIX 8: Single canonical source for week-start computation.
All gamification, quiz, and leaderboard code must use these functions
to ensure timezone-aware, consistent week boundaries.
"""
from datetime import datetime, timezone, timedelta


def get_current_week_start() -> datetime:
    """
    Monday 00:00:00 UTC of the current ISO week.

    Returns a timezone-aware datetime that can be directly compared
    with other timezone-aware datetimes in the database.
    """
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def get_current_week_end() -> datetime:
    """
    Sunday 23:59:59 UTC of the current ISO week.

    Returns a timezone-aware datetime for the end of the current week.
    """
    week_start = get_current_week_start()
    return week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
