from __future__ import annotations

from typing import Optional

from common import (
    GameSnapshot,
    ScoredPick,
    clamp01,
    compression_ratio,
    count_safety_ranks_for_threshold,
    deterministic_tiebreak,
    find_easiest_rank_with_points,
    find_time_for_points_threshold,
    is_blacklisted,
    percentile_rank,
    rank_gap_for_threshold,
    safe_log_norm,
    tail_depth_from_rank,
    time_at_rank,
)


def score_new_game_picks(
    cur: dict[str, GameSnapshot],
    prev: Optional[dict[str, GameSnapshot]],
    top_n: int,
    blacklist: Optional[set[str]] = None,
) -> list[ScoredPick]:
    blacklist = blacklist or set()
    candidates = [
        snapshot
        for snapshot in cur.values()
        if not snapshot.has_me and not is_blacklisted(snapshot.game, blacklist)
    ]

    filtered: list[GameSnapshot] = []
    for snapshot in candidates:
        r500 = find_easiest_rank_with_points(snapshot, 500.0)
        if r500 is None or r500 <= 3:
            continue
        if snapshot.t4 is None:
            continue
        filtered.append(snapshot)
    candidates = filtered

    if not candidates:
        return []

    roi500_vals: list[float] = []
    roi700_vals: list[float] = []
    buffer500_vals: list[float] = []
    safety500_vals: list[float] = []
    tail_vals: list[float] = []
    growth_vals: list[float] = []
    comp14_vals: list[float] = []
    comp410_vals: list[float] = []
    invest_vals: list[float] = []
    gap500_pct_vals: list[float] = []
    gap700_pct_vals: list[float] = []
    n_max = max((snapshot.n for snapshot in candidates), default=1)

    for snapshot in candidates:
        r500 = find_easiest_rank_with_points(snapshot, 500.0)
        t500 = find_time_for_points_threshold(snapshot, 500.0)
        t700 = find_time_for_points_threshold(snapshot, 700.0)

        if t500 is not None and t500 > 0:
            roi500_vals.append(500.0 / (t500 / 60.0))
        if t700 is not None and t700 > 0:
            roi700_vals.append(700.0 / (t700 / 60.0))

        if t500 is not None and snapshot.t1 is not None and snapshot.t1 > 0:
            gap500_pct_vals.append((t500 - snapshot.t1) / snapshot.t1)
        if t700 is not None and snapshot.t1 is not None and snapshot.t1 > 0:
            gap700_pct_vals.append((t700 - snapshot.t1) / snapshot.t1)
        if snapshot.p4 is not None:
            buffer500_vals.append(float(snapshot.p4) - 500.0)
            invest_vals.append(max(0.0, float(snapshot.p4) - 500.0))

        safety500_vals.append(float(count_safety_ranks_for_threshold(snapshot, r500, 500.0)))
        tail_vals.append(float(tail_depth_from_rank(snapshot, r500)))

        if prev is not None and snapshot.game in prev:
            growth_vals.append((snapshot.n - prev[snapshot.game].n) / max(1, prev[snapshot.game].n))

        comp_14 = compression_ratio(snapshot.t1, snapshot.t4)
        if comp_14 is not None:
            comp14_vals.append(comp_14)
        comp_410 = compression_ratio(snapshot.t4, time_at_rank(snapshot, 10))
        if comp_410 is not None:
            comp410_vals.append(comp_410)

    for values in (
        roi500_vals,
        roi700_vals,
        buffer500_vals,
        safety500_vals,
        tail_vals,
        growth_vals,
        comp14_vals,
        comp410_vals,
        invest_vals,
        gap500_pct_vals,
        gap700_pct_vals,
    ):
        values.sort()

    picks: list[ScoredPick] = []
    for snapshot in candidates:
        r500 = find_easiest_rank_with_points(snapshot, 500.0)
        t500 = find_time_for_points_threshold(snapshot, 500.0)
        r700 = find_easiest_rank_with_points(snapshot, 700.0)
        t700 = find_time_for_points_threshold(snapshot, 700.0)

        roi500 = (
            percentile_rank(roi500_vals, 500.0 / (t500 / 60.0))
            if t500 is not None and t500 > 0 and roi500_vals
            else 0.0
        )
        roi700 = (
            percentile_rank(roi700_vals, 700.0 / (t700 / 60.0))
            if t700 is not None and t700 > 0 and roi700_vals
            else 0.0
        )
        gap500_to_4 = rank_gap_for_threshold(snapshot, 500.0, anchor_rank=4)
        gap500_to_4_bonus = clamp01(gap500_to_4 / 4.0) if gap500_to_4 is not None else 0.0

        immediate_roi = clamp01(0.68 * roi500 + 0.22 * roi700 + 0.10 * gap500_to_4_bonus)

        gap500_pct = (
            (t500 - snapshot.t1) / snapshot.t1
            if t500 is not None and snapshot.t1 is not None and snapshot.t1 > 0
            else None
        )
        gap700_pct = (
            (t700 - snapshot.t1) / snapshot.t1
            if t700 is not None and snapshot.t1 is not None and snapshot.t1 > 0
            else None
        )
        gap500_norm = percentile_rank(gap500_pct_vals, gap500_pct) if gap500_pct is not None and gap500_pct_vals else 0.0
        gap700_norm = percentile_rank(gap700_pct_vals, gap700_pct) if gap700_pct is not None and gap700_pct_vals else 0.0
        headroom_bonus = clamp01(0.35 * gap500_norm + 0.65 * gap700_norm)

        buffer500 = (float(snapshot.p4) - 500.0) if snapshot.p4 is not None else -9999.0
        buffer500_norm = percentile_rank(buffer500_vals, buffer500) if buffer500_vals else 0.0
        safety500 = float(count_safety_ranks_for_threshold(snapshot, r500, 500.0))
        safety500_norm = percentile_rank(safety500_vals, safety500) if safety500_vals else 0.0
        tail = float(tail_depth_from_rank(snapshot, r500))
        tail_norm = percentile_rank(tail_vals, tail) if tail_vals else 0.0
        stability = clamp01(0.42 * buffer500_norm + 0.33 * safety500_norm + 0.25 * tail_norm)

        runners_norm = safe_log_norm(snapshot.n, n_max)
        growth = None
        growth_norm = 0.0
        if prev is not None and snapshot.game in prev:
            growth = (snapshot.n - prev[snapshot.game].n) / max(1, prev[snapshot.game].n)
            growth_norm = percentile_rank(growth_vals, growth) if growth_vals else 0.0

        invest = max(0.0, float(snapshot.p4) - 500.0) if snapshot.p4 is not None else 0.0
        invest_norm = percentile_rank(invest_vals, invest) if invest_vals else 0.0
        future_value = clamp01(0.38 * growth_norm + 0.32 * tail_norm + 0.18 * runners_norm + 0.12 * invest_norm)

        comp_14 = compression_ratio(snapshot.t1, snapshot.t4)
        comp_410 = compression_ratio(snapshot.t4, time_at_rank(snapshot, 10))
        c14_norm = percentile_rank(comp14_vals, comp_14) if comp_14 is not None and comp14_vals else 0.5
        c410_norm = percentile_rank(comp410_vals, comp_410) if comp_410 is not None and comp410_vals else 0.5
        risk_penalty = clamp01(0.55 * (1.0 - c14_norm) + 0.45 * (1.0 - c410_norm))

        rank_difficulty_penalty = 0.0
        if r500 is not None and r500 <= 5:
            rank_difficulty_penalty += 0.08
        if r700 == 1:
            rank_difficulty_penalty += 0.05

        final_score01 = clamp01(
            0.31 * immediate_roi
            + 0.25 * stability
            + 0.20 * future_value
            + 0.20 * (1.0 - risk_penalty)
            + 0.12 * headroom_bonus
            - rank_difficulty_penalty
        )

        picks.append(
            ScoredPick(
                game=snapshot.game,
                score=round(final_score01 * 100.0, 2),
                snapshot=snapshot,
                extra={
                    "r500": r500,
                    "t500": t500,
                    "r700": r700,
                    "t700": t700,
                    "buffer500": buffer500,
                    "safety500": int(safety500),
                    "tail_depth": int(tail),
                    "growth": growth,
                    "immediate_roi": immediate_roi,
                    "stability": stability,
                    "future_value": future_value,
                    "headroom_bonus": headroom_bonus,
                    "risk_penalty": risk_penalty,
                    "investment_headroom": invest,
                },
            )
        )

    picks.sort(
        key=lambda pick: (
            -pick.score,
            -(pick.extra.get("tail_depth", 0)),
            -(pick.extra.get("buffer500", -9999.0)),
            pick.snapshot.t4 or 9e18,
            deterministic_tiebreak(pick.game),
        )
    )
    return picks[:top_n]
