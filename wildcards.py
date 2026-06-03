from __future__ import annotations

import hashlib
import math
import random
from typing import Optional

from common import (
    GameSnapshot,
    deterministic_tiebreak,
    format_seconds,
    is_blacklisted,
    find_time_for_points_threshold,
    safe_log_norm,
)


def make_seed(current: object, previous: object | None = None) -> int:
    """Stable monthly seed based on the --current input string.

    previous is accepted for backwards-compatible call sites, but intentionally
    ignored so changing/omitting --previous does not reshuffle the month's picks.
    """
    h = hashlib.sha256(str(current).encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big")


def _weighted_sample_without_replacement(
    items: list[dict],
    weights: list[float],
    k: int,
    rng: random.Random,
) -> list[dict]:
    pool = list(zip(items, weights))
    selected: list[dict] = []

    while pool and len(selected) < k:
        total = sum(max(0.0, weight) for _, weight in pool)
        if total <= 0:
            index = rng.randrange(len(pool))
        else:
            pick = rng.uniform(0.0, total)
            running = 0.0
            index = len(pool) - 1
            for i, (_, weight) in enumerate(pool):
                running += max(0.0, weight)
                if running >= pick:
                    index = i
                    break
        item, _ = pool.pop(index)
        selected.append(item)

    return selected


def build_wildcards(
    cur: dict[str, GameSnapshot],
    low_runner_cap: int,
    wr_points_floor: float,
    popular_floor: int,
    seed: int,
    blacklist: Optional[set[str]] = None,
    exclude_games: Optional[set[str]] = None,
    max_seconds: int = 30 * 60,
    count: int = 10,
) -> list[dict]:
    """Build seeded random wildcard picks.

    Wildcards are intentionally different from the scored sections: take all
    short games where you have no run, remove already-picked games, weight the
    pool slightly by popularity, then draw without replacement using the monthly
    seed.
    """
    blacklist = blacklist or set()
    exclude_games = exclude_games or set()
    rng = random.Random(seed)

    base_candidates: list[GameSnapshot] = []
    for snapshot in cur.values():
        if snapshot.has_me or is_blacklisted(snapshot.game, blacklist):
            continue
        if snapshot.game in exclude_games:
            continue
        if snapshot.t4 is None or snapshot.t4 <= 0 or snapshot.t4 >= max_seconds:
            continue
        # Wildcards should still be capable of meaningful points: rank #4
        # must be worth at least 400 points.
        if snapshot.p4 is None or float(snapshot.p4) < 400.0:
            continue
        base_candidates.append(snapshot)

    if not base_candidates:
        return []

    n_max = max((snapshot.n for snapshot in base_candidates), default=1)
    items: list[dict] = []
    weights: list[float] = []

    for snapshot in base_candidates:
        popularity = safe_log_norm(snapshot.n, n_max)

        # Keep the popularity influence mild: popular games are more likely, but
        # small games can still get pulled from the hat.
        weight = 1.0 + (1.75 * popularity)

        # Prefer games where a short #4 is not just short, but also meaningful.
        p4 = snapshot.by_rank_points.get(4)
        if p4 is not None:
            weight *= 1.0 + min(0.50, max(0.0, float(p4) - 500.0) / 700.0)

        # Tiny deterministic jitter prevents too many identical weights while
        # still keeping the main draw seeded by the current input.
        jitter_seed = hashlib.sha256(f"{seed}|{snapshot.game}".encode("utf-8")).digest()
        jitter = 0.90 + (int.from_bytes(jitter_seed[:4], "big") / 0xFFFFFFFF) * 0.20
        weight *= jitter

        t500 = find_time_for_points_threshold(snapshot, 500.0)
        t700 = find_time_for_points_threshold(snapshot, 700.0)
        items.append(
            {
                "game": snapshot.game,
                "why": (
                    "Seeded weighted wildcard. You have no run; "
                    f"#4 takes {format_seconds(snapshot.t4)}"
                    f" for {p4:.0f} pts; " if p4 is not None else
                    "Seeded weighted wildcard. You have no run; "
                    f"#4 takes {format_seconds(snapshot.t4)}; "
                ) + f"runners={snapshot.n}; draw weight={weight:.2f}.",
                "score": weight,
                "t500": t500,
                "t700": t700,
                "t4": snapshot.t4,
            }
        )
        weights.append(weight)

    selected = _weighted_sample_without_replacement(items, weights, count, rng)
    selected.sort(key=lambda item: (deterministic_tiebreak(f"{seed}|{item['game']}")))
    return selected
