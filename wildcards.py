from __future__ import annotations

import math
from typing import Optional

from common import (
    GameSnapshot,
    count_wr_ties,
    deterministic_tiebreak,
    format_seconds,
    highest_rank_number_available,
    is_blacklisted,
)


def build_wildcards(
    cur: dict[str, GameSnapshot],
    low_runner_cap: int,
    wr_points_floor: float,
    popular_floor: int,
    blacklist: Optional[set[str]] = None,
) -> list[dict]:
    blacklist = blacklist or set()
    candidates = []

    for snapshot in cur.values():
        if snapshot.has_me or is_blacklisted(snapshot.game, blacklist):
            continue

        wr_ties = count_wr_ties(snapshot)
        is_super_popular = snapshot.n >= popular_floor
        has_big_wr_tie = wr_ties >= 4

        if not (is_super_popular or has_big_wr_tie):
            continue

        jackpot_roi = 0.0
        for rank in range(1, min(4, highest_rank_number_available(snapshot)) + 1):
            time_value = snapshot.by_rank_time.get(rank)
            points_value = snapshot.by_rank_points.get(rank)
            if time_value is None or points_value is None or time_value <= 0:
                continue
            jackpot_roi = max(jackpot_roi, float(points_value) / (time_value / 60.0))

        reason_bits = []
        if is_super_popular:
            reason_bits.append(f"super popular (n={snapshot.n})")
        if has_big_wr_tie:
            reason_bits.append(f"{wr_ties} players tied on WR time {format_seconds(snapshot.t1)}")

        score = (
            0.55 * (1.0 if is_super_popular else 0.0)
            + 0.30 * min(1.0, wr_ties / 6.0)
            + 0.15 * math.log(jackpot_roi + 1.0)
        )

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
                        f"best top-4 ROI is {jackpot_roi:.1f} pts/min."
                    ),
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

    return [item[4] for item in candidates]
