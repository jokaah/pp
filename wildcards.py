from __future__ import annotations

import hashlib
import math
import random
from typing import Optional

from common import (
    GameSnapshot,
    count_wr_ties,
    deterministic_tiebreak,
    format_seconds,
    highest_rank_number_available,
    is_blacklisted,
    find_time_for_points_threshold,
)


def make_seed(a: str, b: str) -> int:
    h = hashlib.sha256(f"{a}||{b}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big")  # 64-bit integer


def build_wildcards(
    cur: dict[str, GameSnapshot],
    low_runner_cap: int,
    wr_points_floor: float,
    popular_floor: int,
    seed: int,
    blacklist: Optional[set[str]] = None,
) -> list[dict]:
    blacklist = blacklist or set()
    rng = random.Random(seed)

    candidates = []
    random_pool = []

    for snapshot in cur.values():
        if snapshot.has_me or is_blacklisted(snapshot.game, blacklist):
            continue

        wr_ties = count_wr_ties(snapshot)
        is_super_popular = snapshot.n >= popular_floor
        has_big_wr_tie = wr_ties >= 4

        jackpot_roi = 0.0
        for rank in range(1, min(4, highest_rank_number_available(snapshot)) + 1):
            time_value = snapshot.by_rank_time.get(rank)
            points_value = snapshot.by_rank_points.get(rank)
            if time_value is None or points_value is None or time_value <= 0:
                continue
            jackpot_roi = max(jackpot_roi, float(points_value) / (time_value / 60.0))

        t500 = find_time_for_points_threshold(snapshot, 500.0)
        t700 = find_time_for_points_threshold(snapshot, 700.0)

        score = (
            0.55 * (1.0 if is_super_popular else 0.0)
            + 0.30 * min(1.0, wr_ties / 6.0)
            + 0.15 * math.log(jackpot_roi + 1.0)
        )

        # Separate random pool:
        # - at least 500 points possible for 4th placement
        # - 4th place time less than 30 minutes
        t4 = snapshot.t4
        p4 = snapshot.by_rank_points.get(4)
        if (
            t4 is not None
            and t4 > 0
            and t4 < 30 * 60
            and p4 is not None
            and p4 >= 500.0
        ):
            random_pool.append(
                {
                    "game": snapshot.game,
                    "why": (
                        "Random wildcard. You have no run; "
                        f"4th place is worth {p4:.0f} pts and takes {format_seconds(t4)}. "
                        f"reference score: {score:.3f}."
                    ),
                    "score": score,
                    "t500": t500,
                    "t700": t700,
                    "t4": t4,
                }
            )

        if not (is_super_popular or has_big_wr_tie):
            continue

        reason_bits = []
        if is_super_popular:
            reason_bits.append(f"super popular (n={snapshot.n})")
        if has_big_wr_tie:
            reason_bits.append(f"{wr_ties} players tied on WR time {format_seconds(snapshot.t1)}")

        candidates.append(
            (
                score,
                is_super_popular,
                wr_ties,
                jackpot_roi,
                {
                    "game": snapshot.game,
                    "why": (
                        f"You have no run; {'; '.join(reason_bits)}. "
                        f"best top-4 ROI is {jackpot_roi:.1f} pts/min. "
                        f"score: {score:.3f}."
                    ),
                    "score": score,
                    "t500": t500,
                    "t700": t700,
                    "t4": snapshot.t4,
                },
            )
        )

    candidates.sort(
        key=lambda item: (
            -item[0],
            -int(item[1]),
            -item[2],
            -item[3],
            deterministic_tiebreak(item[4]["game"]),
        )
    )

    random_selected = rng.sample(random_pool, k=min(2, len(random_pool)))
    random_selected_games = {item["game"] for item in random_selected}

    ranked_selected = [
        item[4] for item in candidates
        if item[4]["game"] not in random_selected_games
    ]

    # Merge and sort everything by score (descending)
    final = random_selected + ranked_selected
    final.sort(
        key=lambda item: (
            -item["score"],
            deterministic_tiebreak(item["game"]),
        )
    )

    return final