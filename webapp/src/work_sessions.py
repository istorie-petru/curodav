"""Difficulty vocabulary and averaging for work sessions.

Pure and clock-free. Feature notes: curodav-notes/documentation/features/work-sessions-planner.md.
"""

DIFFICULTIES = {
    "easy": {"name": "Easy", "color": "green", "icon": "baby", "score": 1},
    "moderate": {"name": "Moderate", "color": "orange", "icon": "trending-up", "score": 2},
    "hard": {"name": "Hard", "color": "red", "icon": "atom", "score": 3},
}
DEFAULT_DIFFICULTY = "moderate"


def normalize_difficulty(value: str | None) -> str:
    """The stored difficulty for a submitted value; anything unknown is the default."""
    return value if value in DIFFICULTIES else DEFAULT_DIFFICULTY


def parse_hours(value: str | float | None) -> float | None:
    """A non-negative hours estimate, or None when blank or unusable."""
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return None
    return round(hours, 2) if hours >= 0 else None


def average_difficulty(difficulties: list[str | None]) -> str | None:
    """The difficulty closest to the mean of the sessions; None for no sessions."""
    if not difficulties:
        return None
    scores = [DIFFICULTIES[normalize_difficulty(d)]["score"] for d in difficulties]
    mean = sum(scores) / len(scores)
    return min(DIFFICULTIES, key=lambda k: (abs(DIFFICULTIES[k]["score"] - mean), -DIFFICULTIES[k]["score"]))


def estimated_hours(sessions: list[dict]) -> float:
    return round(sum(s.get("hours_estimate") or 0 for s in sessions), 2)
