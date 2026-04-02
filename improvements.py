from __future__ import annotations

from typing import Optional

from common import (
    GameSnapshot,
    ScoredPick,
    clamp01,
    deterministic_tiebreak,
    find_easiest_rank_for_gain,
    is_blacklisted,
    percentile_rank,
    safe_log_norm,
    time_for_gain,
)


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
        and not is_blacklisted(snapshot.game, blacklist)
    ]

    pos_vals: list[float] = []
    for snapshot in candidates:
        if snapshot.n <= 1:
            continue
        pos_vals.append((snapshot.my_rank - 1) / (snapshot.n - 1))
    avg_pos = sum(pos_vals) / len(pos_vals) if pos_vals else 0.5

    t4_vals = sorted([snapshot.t4 for snapshot in candidates if snapshot.t4 is not None and snapshot.t4 > 0])
    spread_vals = sorted([snapshot.spread15_ratio for snapshot in candidates if snapshot.spread15_ratio is not None])
    n_max = max((snapshot.n for snapshot in candidates), default=1)

    eff_vals: list[float] = []
    for snapshot in candidates:
        for gain in (100.0, 200.0):
            target_rank = find_easiest_rank_for_gain(snapshot, gain)
            if target_rank is None:
                continue
            goal_time = snapshot.by_rank_time.get(target_rank)
            goal_points = snapshot.by_rank_points.get(target_rank)
            if goal_time is None or goal_points is None:
                continue
            saved = float(snapshot.my_time) - float(goal_time)
            gained = float(goal_points) - float(snapshot.my_points)
            if saved > 0 and gained > 0:
                eff_vals.append(gained / saved)
    eff_vals.sort()

    picks: list[ScoredPick] = []
    for snapshot in candidates:
        runners = safe_log_norm(snapshot.n, n_max)
        shortness = (
            1.0 - percentile_rank(t4_vals, snapshot.t4)
            if snapshot.t4 is not None and snapshot.t4 > 0 and t4_vals
            else 0.0
        )
        spread = (
            percentile_rank(spread_vals, snapshot.spread15_ratio)
            if snapshot.spread15_ratio is not None and spread_vals
            else 0.0
        )

        below = 0.0
        my_pos = None
        if snapshot.n > 1:
            my_pos = (snapshot.my_rank - 1) / (snapshot.n - 1)
            below = clamp01((my_pos - avg_pos) / 0.50)

        best_eff = 0.0
        for gain in (100.0, 200.0):
            target_rank = find_easiest_rank_for_gain(snapshot, gain)
            if target_rank is None:
                continue
            goal_time = snapshot.by_rank_time.get(target_rank)
            goal_points = snapshot.by_rank_points.get(target_rank)
            if goal_time is None or goal_points is None:
                continue
            saved = float(snapshot.my_time) - float(goal_time)
            gained = float(goal_points) - float(snapshot.my_points)
            if saved > 0 and gained > 0:
                best_eff = max(best_eff, gained / saved)

        eff_norm = percentile_rank(eff_vals, best_eff) if eff_vals else 0.0
        score01 = clamp01(0.32 * eff_norm + 0.22 * below + 0.18 * spread + 0.18 * runners + 0.10 * shortness)

        rank_for_100 = find_easiest_rank_for_gain(snapshot, 100.0)
        rank_for_200 = find_easiest_rank_for_gain(snapshot, 200.0)
        both_goals_need_top3 = (
            rank_for_100 is not None
            and rank_for_200 is not None
            and rank_for_100 <= 3
            and rank_for_200 <= 3
        )
        top3_penalty = 0.15 if both_goals_need_top3 else 0.0
        score01 = clamp01(score01 - top3_penalty)

        picks.append(
            ScoredPick(
                game=snapshot.game,
                score=round(score01 * 100.0, 2),
                snapshot=snapshot,
                extra={
                    "avg_pos": avg_pos,
                    "my_pos": my_pos,
                    "best_eff": best_eff,
                    "rank_for_100": rank_for_100,
                    "rank_for_200": rank_for_200,
                    "both_goals_need_top3": both_goals_need_top3,
                    "top3_penalty": top3_penalty,
                },
            )
        )

    filtered: list[ScoredPick] = []
    for pick in picks:
        snapshot = pick.snapshot
        if is_blacklisted(snapshot.game, blacklist):
            continue
        if time_for_gain(snapshot, 100.0) is None and time_for_gain(snapshot, 200.0) is None:
            continue
        filtered.append(pick)

    filtered.sort(
        key=lambda pick: (
            -pick.score,
            -pick.snapshot.n,
            pick.snapshot.t4 or 9e18,
            deterministic_tiebreak(pick.game),
        )
    )
    return filtered[:top_n]
