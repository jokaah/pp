#!/usr/bin/env python3

"""
Speedrun leaderboard monthly picker (refactored split version)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    build_game_snapshots,
    dedupe_picks,
    load_blacklist,
    load_whitelist,
    load_snapshot,
    print_improvement_section,
    print_new_game_section,
    print_wildcards_section,
    print_my_runs_section,
    load_game_links,
    ScoredPick,
    find_easiest_rank_with_points,
    find_time_for_points_threshold,
)
from improvements import score_improvement_picks
from new_games import score_new_game_picks
from wildcards import build_wildcards, make_seed
from passive_points import calculate_point_changes, print_point_changes_section


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Monthly speedrun leaderboard picks (new/improve/wildcards)"
    )
    parser.add_argument(
        "-c",
        "--current",
        required=True,
        type=Path,
        help="Current snapshot (dir of CSVs or a single CSV)",
    )
    parser.add_argument(
        "-p",
        "--previous",
        type=Path,
        default=None,
        help="Previous snapshot (optional; dir or single CSV)",
    )
    parser.add_argument(
        "--my-name",
        type=str,
        default="Joka",
        help="Your player name",
    )
    parser.add_argument(
        "--max-minutes",
        type=int,
        default=50,
        help="Hard filter: ignore runs >= this many minutes",
    )
    parser.add_argument(
        "--top-new",
        type=int,
        default=25,
        help="How many new game picks to show",
    )
    parser.add_argument(
        "--top-improve",
        type=int,
        default=15,
        help="How many improvement picks to show",
    )
    parser.add_argument(
        "--top-wild",
        type=int,
        default=10,
        help="How many wildcards to show (short list)",
    )
    parser.add_argument(
        "--wild-low-runners",
        type=int,
        default=10,
        help="Wildcard rule: low runners cap",
    )
    parser.add_argument(
        "--wild-wr-points",
        type=float,
        default=600.0,
        help="Wildcard rule: WR points floor",
    )
    parser.add_argument(
        "--wild-popular",
        type=int,
        default=60,
        help="Wildcard rule: popular runners floor",
    )
    parser.add_argument(
        "--blacklist",
        type=Path,
        default=Path("./blacklist.txt"),
        help="Optional text file of exact game names to exclude",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Output CSV rows only (no human-readable text)",
    )
    parser.add_argument(
        "--mode",
        choices=("all", "passive", "normal"),
        default="normal",
        help="Run mode: normal or point changes only (all or passive)",
    )
    parser.add_argument(
        "--list-my-runs",
        action="store_true",
        help="List all my current runs ordered by points",
    )
    return parser



def _categorize_whitelist(whitelist: set[str], snapshots) -> tuple[list[str], list[str], list[str]]:
    """Split whitelisted games into NEW vs IMPROVEMENT based on whether I have a run."""
    snapshot_by_key = {game.casefold(): snapshot for game, snapshot in snapshots.items()}
    new_games: list[str] = []
    improve_games: list[str] = []
    missing: list[str] = []

    for requested in sorted(whitelist):
        snapshot = snapshot_by_key.get(requested.casefold())
        if snapshot is None:
            missing.append(requested)
        elif snapshot.has_me:
            improve_games.append(snapshot.game)
        else:
            new_games.append(snapshot.game)

    return new_games, improve_games, missing


def _forced_placeholder(snapshot, category: str) -> ScoredPick:
    if category == "new":
        r500 = find_easiest_rank_with_points(snapshot, 500.0)
        r700 = find_easiest_rank_with_points(snapshot, 700.0)
        return ScoredPick(
            game=snapshot.game,
            score=0.0,
            snapshot=snapshot,
            extra={
                "r500": r500,
                "t500": find_time_for_points_threshold(snapshot, 500.0),
                "r700": r700,
                "t700": find_time_for_points_threshold(snapshot, 700.0),
                "buffer500": (float(snapshot.p4) - 500.0) if snapshot.p4 is not None else 0.0,
                "safety500": 0,
                "tail_depth": max(0, snapshot.n - r500) if r500 is not None else 0,
                "growth": None,
                "investment_headroom": max(0.0, float(snapshot.p4) - 500.0) if snapshot.p4 is not None else 0.0,
                "forced": True,
                "natural_rank": None,
            },
        )

    return ScoredPick(
        game=snapshot.game,
        score=0.0,
        snapshot=snapshot,
        extra={
            "below_500": bool(snapshot.my_points is not None and snapshot.my_points < 500.0),
            "below_700": bool(snapshot.my_points is not None and snapshot.my_points < 700.0),
            "rank_for_500": None,
            "rank_for_700": None,
            "rank_for_100": None,
            "rank_for_200": None,
            "pct_for_100": None,
            "pct_for_200": None,
            "podium_hits": [],
            "podium_penalty": 0.0,
            "forced": True,
            "natural_rank": None,
        },
    )


def _merge_forced_picks(
    ranked: list[ScoredPick],
    top_n: int,
    forced_games: list[str],
    snapshots,
    category: str,
) -> tuple[list[ScoredPick], list[str]]:
    selected = list(ranked[:top_n])
    selected_by_key = {pick.game.casefold(): pick for pick in selected}
    ranked_by_key = {pick.game.casefold(): (index, pick) for index, pick in enumerate(ranked, start=1)}
    snapshot_by_key = {game.casefold(): snapshot for game, snapshot in snapshots.items()}
    warnings: list[str] = []

    for requested in forced_games:
        key = requested.casefold()
        ranked_entry = ranked_by_key.get(key)
        if ranked_entry is not None:
            natural_rank, pick = ranked_entry
            pick.extra["forced"] = True
            pick.extra["natural_rank"] = natural_rank
            if key not in selected_by_key:
                selected.append(pick)
                selected_by_key[key] = pick
            continue

        snapshot = snapshot_by_key.get(key)
        if snapshot is None:
            warnings.append(f'{category}: "{requested}" was not found in the current snapshot')
            continue

        pick = _forced_placeholder(snapshot, category)
        if key not in selected_by_key:
            selected.append(pick)
            selected_by_key[key] = pick
        warnings.append(f'{category}: "{snapshot.game}" is normally filtered out, so it has no natural rank')

    return selected, warnings


def main() -> int:
    args = build_arg_parser().parse_args()

    max_run_seconds = int(args.max_minutes * 60)
    my_names = {args.my_name.strip().casefold()}
    print(f"Runner(s): {my_names}")

    cur_games, cur_runs = load_snapshot(args.current, max_run_seconds=max_run_seconds)
    cur_snapshots = build_game_snapshots(cur_runs, my_names_casefold=my_names)

    if args.list_my_runs:
        game_links = load_game_links() if args.csv else None
        print_my_runs_section(cur_snapshots, csv_only=args.csv, game_links=game_links)
        return 0

    blacklist = load_blacklist(args.blacklist)
    whitelist = load_whitelist(Path("./whitelist.txt"))
    game_links = load_game_links() if args.csv else None

    prev_snapshots = None
    if args.previous is not None:
        _, prev_runs = load_snapshot(args.previous, max_run_seconds=max_run_seconds)
        prev_snapshots = build_game_snapshots(prev_runs, my_names_casefold=my_names)

    if args.mode == "passive" or args.mode == "all":
        if prev_snapshots is None:
            raise SystemExit("--mode passive/all requires --previous")
        point_changes = calculate_point_changes(
            cur_snapshots,
            prev_snapshots,
            blacklist=blacklist,
            mode=args.mode,
        )
        print_point_changes_section(point_changes, csv_only=args.csv, mode=args.mode)
        return 0

    always_new, always_improve, whitelist_missing = _categorize_whitelist(whitelist, cur_snapshots)
    # A whitelisted game must be considered even if it also appears in blacklist.txt.
    scoring_blacklist = blacklist - whitelist

    all_new_picks = score_new_game_picks(
        cur_snapshots,
        prev_snapshots,
        top_n=None,
        blacklist=scoring_blacklist,
    )
    all_improve_picks = score_improvement_picks(
        cur_snapshots,
        top_n=None,
        blacklist=scoring_blacklist,
    )
    new_picks, new_warnings = _merge_forced_picks(
        all_new_picks, args.top_new, always_new, cur_snapshots, "new"
    )
    improve_picks, improve_warnings = _merge_forced_picks(
        all_improve_picks, args.top_improve, always_improve, cur_snapshots, "improvement"
    )
    already_picked_games = {pick.game for pick in improve_picks} | {pick.game for pick in new_picks}
    wildcards = build_wildcards(
        cur_snapshots,
        low_runner_cap=args.wild_low_runners,
        wr_points_floor=args.wild_wr_points,
        popular_floor=args.wild_popular,
        blacklist=blacklist,
        seed=make_seed(args.current, args.previous),
        exclude_games=already_picked_games,
        count=args.top_wild,
    )

    new_picks, improve_picks, wildcards = dedupe_picks(new_picks, improve_picks, wildcards)
    wildcards = wildcards[: args.top_wild]

    if not args.csv:
        print(f"[OK] Current snapshot: {args.current.expanduser().resolve()}")
        print(f"[i] Current games detected: {len(cur_games)}")
        print(f"[i] Current runs parsed (after >= {args.max_minutes}min filter): {len(cur_runs)}")
        print(f"[i] Games where you have a run: {sum(1 for snapshot in cur_snapshots.values() if snapshot.has_me)}")
        if blacklist:
            print(f"[i] Blacklisted exact-name matches: {len(blacklist)}")
        if whitelist:
            print(f"[i] Whitelisted exact-name matches: {len(whitelist) - len(whitelist_missing)}")
        if args.previous is not None:
            print(f"[OK] Previous snapshot: {args.previous.expanduser().resolve()}")
            print(f"[i] Previous games detected: {len(prev_snapshots) if prev_snapshots is not None else 0}")
        for game in whitelist_missing:
            print(f'[!] Whitelist: "{game}" was not found in the current snapshot')
        for warning in new_warnings + improve_warnings:
            print(f"[!] Whitelist: {warning}")

    print_new_game_section(new_picks, csv_only=args.csv, game_links=game_links)
    print_improvement_section(improve_picks, csv_only=args.csv, game_links=game_links)
    print_wildcards_section(wildcards, csv_only=args.csv, game_links=game_links)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
