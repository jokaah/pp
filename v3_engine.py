"""V3 recommendation engine.

Selection policy is separate from CSV parsing. A target is always a real,
non-podium leaderboard row; podium points are never used as the goal.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import random
from statistics import median

from common import GameSnapshot, format_seconds, is_blacklisted


@dataclass(frozen=True)
class Target:
    rank: int
    points: float
    time: float
    wr_gap: float


@dataclass
class Analysis:
    snapshot: GameSnapshot
    targets: list[Target]
    sweet: Target
    runtime_score: float
    accessibility: float
    popularity: float
    softness: float
    compression: float
    durable_700: float = 0.0
    route_opportunity: float = 0.0
    quick_score: float = 0.0
    grind_score: float = 0.0


@dataclass(frozen=True)
class Improvement:
    snapshot: GameSnapshot
    target: Target
    gain: float
    percent_faster: float
    average_gain: float
    score: float


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _available_targets(snapshot: GameSnapshot, max_rank: int = 60) -> list[Target]:
    if snapshot.t1 is None or snapshot.t1 <= 0:
        return []
    result = []
    for rank in sorted(snapshot.by_rank_points):
        if rank < 4 or rank > max_rank:
            continue
        time = snapshot.by_rank_time.get(rank)
        points = snapshot.by_rank_points.get(rank)
        if time is None or points is None or time <= 0:
            continue
        result.append(Target(rank, float(points), float(time), max(0.0, (time - snapshot.t1) / snapshot.t1)))
    return result


def _softness(snapshot: GameSnapshot) -> tuple[float, float]:
    """Measure a region of opportunity, so one freak gap is insufficient."""
    gaps = []
    ordered = [(r, snapshot.by_rank_time.get(r)) for r in range(4, min(snapshot.n, 20) + 1)]
    ordered = [(r, t) for r, t in ordered if t is not None and t > 0]
    for (_, before), (_, after) in zip(ordered, ordered[1:]):
        if after >= before:
            gaps.append((after - before) / before)
    if not gaps:
        return 0.0, 1.0
    ordered_gaps = sorted(gaps)
    med = median(ordered_gaps)
    q75 = ordered_gaps[min(len(ordered_gaps) - 1, int(0.75 * (len(ordered_gaps) - 1)))]
    softness = _clamp((0.65 * med + 0.35 * q75) / 0.012)
    return softness, _clamp(1.0 - softness)


def _choose_sweet(targets: list[Target], current_average: float) -> Target:
    def value(t: Target) -> tuple[float, float, int]:
        points = _clamp((t.points - 250.0) / 650.0)
        depth = _clamp((t.rank - 4) / 22.0)
        forgiveness = _clamp(t.wr_gap / 0.12)
        average_fit = 1.0 - _clamp(abs(t.points - current_average) / 550.0)
        # A deep, forgiving 450 is useful information, but it should not beat
        # a realistic ~700 target. Protecting the player's average is the point.
        return (0.55 * points + 0.10 * depth + 0.15 * forgiveness + 0.20 * average_fit, t.points, t.rank)
    return max(targets, key=value)


def analyze_new_games(snapshots, current_average: float, blacklist: set[str]) -> list[Analysis]:
    raw = []
    max_runners = max((s.n for s in snapshots.values()), default=1)
    for snapshot in snapshots.values():
        if snapshot.has_me or is_blacklisted(snapshot.game, blacklist):
            continue
        targets = _available_targets(snapshot)
        if not targets:
            continue
        sweet = _choose_sweet(targets, current_average)
        softness, compression = _softness(snapshot)
        runtime_score = _clamp(1.0 - math.log1p(sweet.time) / math.log1p(30 * 60))
        accessibility = _clamp(0.42 * _clamp((sweet.rank - 3) / 25.0) + 0.38 * _clamp(sweet.wr_gap / 0.15) + 0.20 * softness)
        popularity = math.log1p(snapshot.n) / math.log1p(max_runners)
        raw.append(Analysis(snapshot, targets, sweet, runtime_score, accessibility, popularity, softness, compression))

    for item in raw:
        snapshot = item.snapshot
        point_quality = _clamp((item.sweet.points - 300.0) / 600.0)
        average_quality = _clamp((item.sweet.points - (current_average - 200.0)) / 400.0)
        effort = _clamp(0.48 * item.runtime_score + 0.37 * item.accessibility + 0.15 * (1.0 - item.compression))

        target_700s = [t for t in item.targets if t.points >= 700.0]
        target_700 = max(target_700s, key=lambda t: t.rank) if target_700s else None
        target_500s = [t for t in item.targets if t.points >= 500.0]
        target_500 = max(target_500s, key=lambda t: t.rank) if target_500s else None
        if target_700 is not None:
            item.durable_700 = _clamp(0.45 + 0.55 * ((target_700.rank - 3) / 22.0))

        time_gap = 0.0
        if target_500 is not None and snapshot.t4 is not None and snapshot.t4 > 0:
            time_gap = max(0.0, (target_500.time - snapshot.t4) / snapshot.t4)
        point_gap = max(0.0, float(snapshot.p4 or 0.0) - 500.0)
        item.route_opportunity = _clamp(0.55 * (time_gap / 0.25) + 0.45 * (point_gap / 700.0))

        quick_700 = 0.0
        if target_700 is not None and target_700.time <= 10 * 60:
            quick_700 = _clamp(0.70 + 0.30 * ((target_700.rank - 3) / 20.0))
        item.quick_score = 100 * _clamp(
            0.34 * point_quality + 0.26 * effort + 0.25 * quick_700 + 0.15 * average_quality
        )
        # The clearest Quick signal from calibration: a sub-10-minute 700 that
        # does not require a podium deserves to be seen even when the board is
        # dense (Mario's Time Machine / Sesame Street Countdown).
        if target_700 is not None and target_700.time <= 10 * 60 and target_700.rank >= 4:
            item.quick_score = min(100.0, item.quick_score + 8.0)
        if target_500 is not None and target_500.time < 5 * 60:
            item.quick_score = min(100.0, item.quick_score + 7.0)
        # An enormous rank-4-to-15 spread in a tiny game is a warning about
        # volatile execution, not evidence that the top score is easy.
        if snapshot.t15 is not None and snapshot.t15 < 5 * 60:
            volatility = _clamp((snapshot.spread15_ratio - 0.65) / 0.75)
            item.quick_score = max(0.0, item.quick_score - 18.0 * volatility)

        commitment_time = target_700.time if target_700 is not None else item.sweet.time
        length_fit = _clamp(1.0 - max(0.0, commitment_time - 20 * 60) / (20 * 60))
        # For Grind, reaching a durable ~700 is already a full-quality prize;
        # 900 should not swamp a saner 700 target just because it is larger.
        grind_prize = _clamp((item.sweet.points - 500.0) / 200.0)
        # Popularity is evidence of significance, not an unlimited bonus.
        meaningful_board = _clamp(math.log1p(snapshot.n) / math.log1p(150))
        overcrowding = _clamp((snapshot.n - 200) / 200.0) * _clamp((commitment_time - 15 * 60) / (20 * 60))
        item.grind_score = 100 * (
            0.25 * grind_prize
            + 0.25 * item.durable_700
            + 0.18 * meaningful_board
            + 0.17 * length_fit
            + 0.15 * item.route_opportunity
            - 0.24 * overcrowding
        )
        # The useful Grind "goldilocks zone": established but not gigantic,
        # roughly 6–18 minutes, with 700 available in strong non-podium ranks.
        # This captures Kabuki, Shadow, Jackal, NGII, and Chip 'n Dale 2.
        if (
            target_700 is not None
            and 8 <= target_700.rank <= 40
            and 6 * 60 <= target_700.time <= 18 * 60
            and 55 <= snapshot.n <= 180
        ):
            item.grind_score += 12.0
        # A deeper 700 and distributed gaps are sturdier than a rank-four
        # prize, even when both boards have similar headline points.
        if target_700 is not None and 6 * 60 <= target_700.time <= 18 * 60:
            item.grind_score += 10.0 * _clamp((target_700.rank - 4) / 16.0) + 3.0 * item.softness
        # Extremely short boards are usually Quick territory. They can still
        # Grind well, but no longer dominate merely through enormous spread.
        if commitment_time < 4 * 60:
            item.grind_score = max(0.0, item.grind_score - 12.0)
        # Longer boards with a tight 700 region and small distributed gaps
        # demand substantial optimization despite an attractive point prize.
        if target_700 is not None:
            optimized = (_clamp((target_700.time - 14 * 60) / (2 * 60))
                         * _clamp((0.12 - target_700.wr_gap) / 0.06)
                         * _clamp((0.40 - item.softness) / 0.20))
            item.grind_score -= 12.0 * optimized
        # Keep the displayed score on a 0–100 scale without clipping the
        # strongest candidates into an arbitrary tie.
        item.grind_score = _clamp(item.grind_score / 120.0) * 100.0

    return raw


def ranked_lanes(analyses, quick_n=15, grind_n=15):
    tie = lambda a: hashlib.sha1(a.snapshot.game.encode()).hexdigest()
    # "Quick" must describe the commitment as well as the score. Fifteen
    # minutes is deliberately stricter than the global ingestion limit.
    quick_pool = [a for a in analyses if a.sweet.time <= 15 * 60]
    quick = sorted(quick_pool, key=lambda a: (-a.quick_score, tie(a)))[:quick_n]
    grind = sorted(analyses, key=lambda a: (-a.grind_score, tie(a)))[:grind_n]
    return quick, grind


def improvement_picks(snapshots, run_count, current_average, blacklist, count=10, minimum_gain=100.0):
    picks = []
    for snapshot in snapshots.values():
        if not snapshot.has_me or snapshot.my_points is None or snapshot.my_time is None or is_blacklisted(snapshot.game, blacklist):
            continue
        targets = [t for t in _available_targets(snapshot) if t.rank < (snapshot.my_rank or 10**9)]
        targets = [t for t in targets if t.points - float(snapshot.my_points) >= minimum_gain and t.time < snapshot.my_time]
        if not targets:
            continue
        def target_value(t):
            gain = t.points - float(snapshot.my_points)
            pct = (snapshot.my_time - t.time) / snapshot.my_time
            resulting = _clamp((t.points - 400.0) / 450.0)
            feasibility = _clamp(1.0 - pct / 0.20)
            return 0.44 * _clamp(gain / 350.0) + 0.36 * resulting + 0.20 * feasibility
        target = max(targets, key=target_value)
        gain = target.points - float(snapshot.my_points)
        pct = (snapshot.my_time - target.time) / snapshot.my_time
        score = 100 * target_value(target)
        if snapshot.my_points < current_average <= target.points:
            score += 8.0
        picks.append(Improvement(snapshot, target, gain, pct, gain / max(1, run_count), score))
    return sorted(picks, key=lambda p: (-p.score, -p.gain, p.snapshot.game))[:count]


def _scouting_targets(analysis: Analysis, count=3):
    # Show achievable point milestones, avoiding a card dominated by nearly
    # worthless tail ranks. Each target remains an actual leaderboard row.
    targets = sorted(analysis.targets, key=lambda t: t.points)
    selected = []
    peak = max(t.points for t in targets)
    thresholds = (350, 500, 700) if peak >= 700 else (300, 400, 500)
    for threshold in thresholds:
        options = [t for t in targets if t.points >= threshold and t not in selected]
        if options:
            selected.append(options[0])
    for target in reversed(targets):
        if len(selected) >= count:
            break
        if target not in selected:
            selected.append(target)
    return sorted(selected[:count], key=lambda t: t.points)


def wildcard_picks(analyses, excluded, seed_text, count=5):
    # A wildcard without a useful scouting card is just noise. Require enough
    # real non-podium rows to show three distinct goals.
    pool = [a for a in analyses if a.snapshot.game not in excluded
            and len(a.targets) >= 3 and any(t.points >= 500 for t in a.targets)]
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], "big"))
    rng.shuffle(pool)
    return [(a, _scouting_targets(a)) for a in pool[:count]]


def target_summary(target: Target) -> str:
    return f"{target.points:.0f} pts @ #{target.rank} in {format_seconds(target.time)}"
