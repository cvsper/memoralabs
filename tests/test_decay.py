"""Tests for app/services/decay.py."""
import time
import pytest
from app.services.decay import DECAY_HALF_LIFE_DAYS, apply_decay, decay_factor

@pytest.fixture
def anyio_backend():
    return "asyncio"

def test_decay_factor_range():
    now = int(time.time())
    assert 0.0 <= decay_factor(now) <= 1.0
    assert 0.0 <= decay_factor(now - 365 * 86400) <= 1.0

def test_decay_factor_recent_is_near_one():
    now = int(time.time())
    factor = decay_factor(now)
    assert factor >= 0.99, f"Expected factor >= 0.99, got {factor}"

def test_decay_factor_half_life():
    now = int(time.time())
    half_life_ago = now - DECAY_HALF_LIFE_DAYS * 86400
    factor = decay_factor(half_life_ago)
    assert 0.45 <= factor <= 0.55, f"Expected ~0.5 at half-life, got {factor}"

def test_decay_recent_memory():
    now = int(time.time())
    original = 1.0
    decayed = apply_decay(original, now)
    assert decayed >= 0.95 * original, f"Expected >= 0.95, got {decayed}"

def test_decay_30_day_old():
    now = int(time.time())
    thirty_days_ago = now - 30 * 86400
    original = 1.0
    decayed = apply_decay(original, thirty_days_ago)
    assert 0.80 <= decayed <= 0.95, f"Expected 0.80-0.95, got {decayed}"

def test_decay_very_old():
    now = int(time.time())
    year_ago = now - 365 * 86400
    original = 1.0
    decayed = apply_decay(original, year_ago)
    assert decayed < 0.85, f"Expected < 0.85 for very old memory, got {decayed}"

def test_decay_monotonic():
    now = int(time.time())
    base_score = 0.8
    timestamps = [
        now - 1 * 86400,
        now - 7 * 86400,
        now - 30 * 86400,
        now - 90 * 86400,
        now - 365 * 86400,
    ]
    decayed_scores = [apply_decay(base_score, t) for t in timestamps]
    for i in range(len(decayed_scores) - 1):
        assert decayed_scores[i] > decayed_scores[i + 1], (
            f"Score at index {i} ({decayed_scores[i]}) should be > "
            f"score at index {i+1} ({decayed_scores[i+1]})"
        )

def test_decay_preserves_zero():
    now = int(time.time())
    assert apply_decay(0.0, now) == 0.0
    assert apply_decay(0.0, now - 365 * 86400) == 0.0
