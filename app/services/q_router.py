"""
Q-learning bandit router for retrieval strategy selection.

Ports the ZimMemory v14 Q-learning bandit pattern to MemoraLabs.
Learns from retrieval outcomes (result count + avg score as proxy reward)
and shifts strategy weights over time without developer intervention.

Activation threshold of 30 visits prevents noise-driven routing in the
early life of a tenant DB — pure Q-routing only kicks in after statistically
meaningful observations have accumulated.

Constants:
    ALPHA: Learning rate — controls how fast new rewards update Q-values.
    EPSILON: Exploration rate — slightly higher than ZimMemory (0.1 → 0.15)
             for SaaS diversity across heterogeneous tenant workloads.
    ACTIVATION_THRESHOLD: Minimum visits before Q-values influence routing.
    DEFAULT_Q: Initial Q-value for new state-action pairs.
    STRATEGIES: Available retrieval strategy names.
    CONFIG_KEYS: Per-strategy config dimensions tracked in the Q-table.
"""

import random
import time

import aiosqlite

ALPHA = 0.2
EPSILON = 0.15
ACTIVATION_THRESHOLD = 30
DEFAULT_Q = 0.5

STRATEGIES = ["precision", "temporal", "relational", "broad"]
CONFIG_KEYS = ["top_k_low", "top_k_high", "min_score_strict", "min_score_relaxed"]


def compute_reward(result_count: int, avg_score: float, max_possible: int = 10) -> float:
    """Compute proxy reward from retrieval outcome.

    No explicit relevance feedback required — uses result_count and avg_score
    as observable proxies for retrieval quality. This avoids the research
    pitfall of requiring user clicks or ratings to drive learning.

    Args:
        result_count: Number of results returned by the retrieval step.
        avg_score: Average similarity score across returned results.
        max_possible: Upper bound for result_count normalization (default: limit).

    Returns:
        Reward float in [0.0, 1.0]. Formula:
            0.4 * min(1.0, result_count / max_possible) + 0.6 * avg_score
    """
    count_component = 0.4 * min(1.0, result_count / max_possible if max_possible > 0 else 0.0)
    score_component = 0.6 * avg_score
    return count_component + score_component


async def update_q_value(
    conn: aiosqlite.Connection,
    strategy: str,
    config_key: str,
    reward: float,
) -> dict:
    """Apply a Q-learning update for a given strategy/config_key state-action pair.

    Reads the current Q-value and visit_count from retrieval_q_table,
    applies the Q-update rule, and upserts the new values.

    Q-update: new_q = old_q + ALPHA * (reward - old_q)

    Args:
        conn: Open aiosqlite connection to a tenant DB.
        strategy: Strategy name (e.g. "precision", "temporal").
        config_key: Config dimension (e.g. "top_k_high").
        reward: Reward signal in [0.0, 1.0] from compute_reward().

    Returns:
        Dict with strategy, config_key, old_q, new_q, visits (post-update),
        and activated (True if visits >= ACTIVATION_THRESHOLD after this update).
    """
    async with conn.execute(
        "SELECT q_value, visit_count FROM retrieval_q_table WHERE strategy = ? AND config_key = ?",
        (strategy, config_key),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        old_q = DEFAULT_Q
        visits = 0
    else:
        old_q = row["q_value"]
        visits = row["visit_count"]

    new_q = old_q + ALPHA * (reward - old_q)
    new_visits = visits + 1
    now = int(time.time())

    await conn.execute(
        """
        INSERT INTO retrieval_q_table (strategy, config_key, q_value, visit_count, last_updated)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(strategy, config_key) DO UPDATE SET
            q_value = excluded.q_value,
            visit_count = excluded.visit_count,
            last_updated = excluded.last_updated
        """,
        (strategy, config_key, new_q, new_visits, now),
    )
    await conn.commit()

    return {
        "strategy": strategy,
        "config_key": config_key,
        "old_q": round(old_q, 4),
        "new_q": round(new_q, 4),
        "visits": new_visits,
        "activated": new_visits >= ACTIVATION_THRESHOLD,
    }


async def select_strategy(conn: aiosqlite.Connection) -> str:
    """Select a retrieval strategy using epsilon-greedy Q-routing.

    If ALL state-action pairs have fewer than ACTIVATION_THRESHOLD visits,
    returns "default" — no Q-routing until the Q-table has meaningful data.

    Otherwise, applies epsilon-greedy selection:
    - With probability EPSILON: explore — return a random strategy.
    - With probability 1-EPSILON: exploit — return the strategy with the
      highest average Q-value across its config_keys.

    Args:
        conn: Open aiosqlite connection to a tenant DB.

    Returns:
        Strategy name string ("default", "precision", "temporal",
        "relational", or "broad").
    """
    # Fetch all Q-table rows
    rows = []
    async with conn.execute(
        "SELECT strategy, config_key, q_value, visit_count FROM retrieval_q_table"
    ) as cur:
        async for row in cur:
            rows.append(dict(row))

    if not rows:
        return "default"

    # Check activation threshold — all pairs must have >= ACTIVATION_THRESHOLD
    all_activated = all(row["visit_count"] >= ACTIVATION_THRESHOLD for row in rows)
    if not all_activated:
        return "default"

    # Epsilon-greedy selection
    if random.random() < EPSILON:
        return random.choice(STRATEGIES)

    # Compute average Q-value per strategy
    strategy_totals: dict[str, list[float]] = {}
    for row in rows:
        strat = row["strategy"]
        if strat not in strategy_totals:
            strategy_totals[strat] = []
        strategy_totals[strat].append(row["q_value"])

    strategy_avg = {
        strat: sum(qs) / len(qs)
        for strat, qs in strategy_totals.items()
    }

    return max(strategy_avg, key=lambda s: strategy_avg[s])


async def get_router_stats(conn: aiosqlite.Connection) -> dict:
    """Return the current state of the Q-table for diagnostics.

    Args:
        conn: Open aiosqlite connection to a tenant DB.

    Returns:
        Dict with:
        - strategies: list of {strategy, config_key, q_value, visit_count, activated}
        - total_updates: sum of all visit_counts
        - is_active: True if any state-action pair has >= ACTIVATION_THRESHOLD visits
    """
    entries = []
    total_updates = 0
    is_active = False

    async with conn.execute(
        "SELECT strategy, config_key, q_value, visit_count FROM retrieval_q_table ORDER BY strategy, config_key"
    ) as cur:
        async for row in cur:
            activated = row["visit_count"] >= ACTIVATION_THRESHOLD
            entries.append({
                "strategy": row["strategy"],
                "config_key": row["config_key"],
                "q_value": row["q_value"],
                "visit_count": row["visit_count"],
                "activated": activated,
            })
            total_updates += row["visit_count"]
            if activated:
                is_active = True

    return {
        "strategies": entries,
        "total_updates": total_updates,
        "is_active": is_active,
    }
