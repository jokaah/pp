from __future__ import annotations

import math
from typing import Optional

from common import (
    GameSnapshot,
    ScoredPick,
    clamp01,
    deterministic_tiebreak,
    find_easiest_rank_for_gain,
    find_easiest_rank_with_points,
    is_blacklisted,
    percentile_rank,
    time_for_gain,
)


BELOW_500_WEIGHT = 0.34
BELOW_700_WEIGHT = 0.24
PLUS_100_WEIGHT = 0.18
PLUS_200_WEIGHT = 0.14
PLACEMENT_WEIGHT = 0.10

PODIUM_PENALTIES = {
    "500": 0.08,
    "700": 0.06,
    "+100": 0.05,
    "+200": 0.04,
}


def _pct_improvement_needed(snapshot: GameSnapshot, target_time: Optional[float]) -> Optional[float]:
    if snapshot.my_time is None or target_time is None:
        return None
    my_time = float(snapshot.my_time)
    goal_time = float(target_time)
    if my_time <= 0 or goal_time >= my_time:
        return None
    return (my_time - goal_time) / my_time


def _normalized_percent_score(sorted_values: list[float], pct_needed: Optional[float]) -> float:
    if pct_needed is None or not math.isfinite(pct_needed):
        return 0.0
    return 1.0 - percentile_rank(sorted_values, pct_needed)


def score_improvement_picks(
    cur: dict[str, GameSnapshot],
    top_n: int,
    blacklist: Optional[set[str]] = None,
) -> list[ScoredPick]:
    blacklist = blacklist or set()
    candidates = [
        snapshot
        for snapshot in cur.values()
        if snapshot.has_me
        and snapshot.my_rank is not None
        and snapshot.my_time is not None
        and snapshot.my_points is not None
        and not is_blacklisted(snapshot.game, blacklist)
    ]

    pct100_values: list[float] = []
    pct200_values: list[float] = []
    for snapshot in candidates:
        pct100 = _pct_improvement_needed(snapshot, time_for_gain(snapshot, 100.0))
        pct200 = _pct_improvement_needed(snapshot, time_for_gain(snapshot, 200.0))
        if pct100 is not None and math.isfinite(pct100):
            pct100_values.append(pct100)
        if pct200 is not None and math.isfinite(pct200):
            pct200_values.append(pct200)
    pct100_values.sort()
    pct200_values.sort()

    picks: list[ScoredPick] = []
    for snapshot in candidates:
        my_points = float(snapshot.my_points)
        my_rank = int(snapshot.my_rank)

        below_500 = 1.0 if my_points < 500.0 else 0.0
        below_700 = 1.0 if my_points < 700.0 else 0.0

        rank_for_500 = find_easiest_rank_with_points(snapshot, 500.0) if below_500 else None
        rank_for_700 = find_easiest_rank_with_points(snapshot, 700.0) if below_700 else None
        rank_for_100 = find_easiest_rank_for_gain(snapshot, 100.0)
        rank_for_200 = find_easiest_rank_for_gain(snapshot, 200.0)

        pct100 = _pct_improvement_needed(snapshot, time_for_gain(snapshot, 100.0))
        pct200 = _pct_improvement_needed(snapshot, time_for_gain(snapshot, 200.0))
        pct100_score = _normalized_percent_score(pct100_values, pct100)
        pct200_score = _normalized_percent_score(pct200_values, pct200)

        placement_score = 0.0
        if snapshot.n > 1:
            placement_score = clamp01((my_rank - 1) / (snapshot.n - 1))

        score01 = (
            BELOW_500_WEIGHT * below_500
            + BELOW_700_WEIGHT * below_700
            + PLUS_100_WEIGHT * pct100_score
            + PLUS_200_WEIGHT * pct200_score
            + PLACEMENT_WEIGHT * placement_score
        )

        podium_hits: list[str] = []
        podium_penalty = 0.0
        if rank_for_500 is not None and rank_for_500 <= 3:
            podium_hits.append("500")
            podium_penalty += PODIUM_PENALTIES["500"]
        if rank_for_700 is not None and rank_for_700 <= 3:
            podium_hits.append("700")
            podium_penalty += PODIUM_PENALTIES["700"]
        if rank_for_100 is not None and rank_for_100 <= 3:
            podium_hits.append("+100")
            podium_penalty += PODIUM_PENALTIES["+100"]
        if rank_for_200 is not None and rank_for_200 <= 3:
            podium_hits.append("+200")
            podium_penalty += PODIUM_PENALTIES["+200"]

        score01 = clamp01(score01 - podium_penalty)

        picks.append(
            ScoredPick(
                game=snapshot.game,
                score=round(score01 * 100.0, 2),
                snapshot=snapshot,
                extra={
                    "below_500": bool(below_500),
                    "below_700": bool(below_700),
                    "rank_for_500": rank_for_500,
                    "rank_for_700": rank_for_700,
                    "rank_for_100": rank_for_100,
                    "rank_for_200": rank_for_200,
                    "pct_for_100": pct100,
                    "pct_for_200": pct200,
                    "pct100_score": pct100_score,
                    "pct200_score": pct200_score,
                    "placement_score": placement_score,
                    "podium_hits": podium_hits,
                    "podium_penalty": podium_penalty,
                    "weights": {
                        "below_500": BELOW_500_WEIGHT,
                        "below_700": BELOW_700_WEIGHT,
                        "+100_pct": PLUS_100_WEIGHT,
                        "+200_pct": PLUS_200_WEIGHT,
                        "placement": PLACEMENT_WEIGHT,
                    },
                },
            )
        )

    filtered: list[ScoredPick] = []
    for pick in picks:
        snapshot = pick.snapshot
        if is_blacklisted(snapshot.game, blacklist):
            continue

        has_500_target = bool(pick.extra.get("below_500")) and pick.extra.get("rank_for_500") is not None
        has_700_target = bool(pick.extra.get("below_700")) and pick.extra.get("rank_for_700") is not None
        has_100_target = pick.extra.get("rank_for_100") is not None
        has_200_target = pick.extra.get("rank_for_200") is not None

        if not (has_500_target or has_700_target or has_100_target or has_200_target):
            continue
        filtered.append(pick)

    filtered.sort(
        key=lambda pick: (
            -pick.score,
            -int(bool(pick.extra.get("below_500"))),
            -int(bool(pick.extra.get("below_700"))),
            -(pick.extra.get("placement_score") or 0.0),
            -pick.snapshot.n,
            pick.snapshot.t4 or 9e18,
            deterministic_tiebreak(pick.game),
        )
    )
    return filtered[:top_n]
