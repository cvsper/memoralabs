"""
Temporal decay scoring service.

Applies time-based score decay so older memories rank lower in search results.
Half-life is 30 days: a memory created 30 days ago retains ~90% of its base
score (80% base + 10% of 20% recency bonus).

Port of ZimMemory apply_decay() pattern.
"""

import time

# Half-life in days — score recency component drops by 50% every 30 days.
DECAY_HALF_LIFE_DAYS = 30

# Seconds in one day
_SECONDS_PER_DAY = 86_400


def decay_factor(created_at: int) -> float:
    """Return the raw decay factor (0.0–1.0) for a memory timestamp.

    Factor is 1.0 for brand-new memories and approaches 0.0 as age grows.
    Based on exponential decay: 0.5 ^ (age_days / DECAY_HALF_LIFE_DAYS).

    Args:
        created_at: Unix timestamp (seconds) when the memory was created.

    Returns:
        Float in [0.0, 1.0].
    """
    now = time.time()
    age_seconds = max(0.0, now - created_at)
    age_days = age_seconds / _SECONDS_PER_DAY
    return 0.5 ** (age_days / DECAY_HALF_LIFE_DAYS)


def apply_decay(score: float, created_at: int) -> float:
    """Blend a base relevance score with a temporal recency bonus.

    Formula: 0.80 * score + 0.20 * (score * decay_factor)

    This means:
    - A brand-new memory retains 100% of its score.
    - A 30-day-old memory retains ~90% (0.80 + 0.20 * 0.5 = 0.90).
    - A 90-day-old memory retains ~82.5% (0.80 + 0.20 * 0.125 = 0.825).

    Args:
        score: Base relevance score (e.g., from BM25 or cosine similarity).
        created_at: Unix timestamp (seconds) when the memory was created.

    Returns:
        Decayed score, always <= score.
    """
    factor = decay_factor(created_at)
    return 0.80 * score + 0.20 * score * factor
