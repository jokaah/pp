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
    load_snapshot,
    print_improvement_section,
    print_new_game_section,
    print_wildcards_section,
    load_game_links,
)
from improvements import score_improvement_picks
from new_games import score_new_game_picks
from wildcards import build_wildcards


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
        action="append",
        default=["Joka"],
        help="Your player name(s). Repeatable.",
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
        default=50,
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
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    max_run_seconds = int(args.max_minutes * 60)
    my_names = {name.strip().casefold() for name in args.my_name if name and name.strip()}

    cur_games, cur_runs = load_snapshot(args.current, max_run_seconds=max_run_seconds)
    cur_snapshots = build_game_snapshots(cur_runs, my_names_casefold=my_names)
    blacklist = load_blacklist(args.blacklist)
    game_links = load_game_links() if args.csv else None

    prev_snapshots = None
    if args.previous is not None:
        _, prev_runs = load_snapshot(args.previous, max_run_seconds=max_run_seconds)
        prev_snapshots = build_game_snapshots(prev_runs, my_names_casefold=my_names)

    new_picks = score_new_game_picks(
        cur_snapshots,
        prev_snapshots,
        top_n=args.top_new,
        blacklist=blacklist,
    )
    improve_picks = score_improvement_picks(
        cur_snapshots,
        top_n=args.top_improve,
        blacklist=blacklist,
    )
    wildcards = build_wildcards(
        cur_snapshots,
        low_runner_cap=args.wild_low_runners,
        wr_points_floor=args.wild_wr_points,
        popular_floor=args.wild_popular,
        blacklist=blacklist,
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
        if args.previous is not None:
            print(f"[OK] Previous snapshot: {args.previous.expanduser().resolve()}")
            print(f"[i] Previous games detected: {len(prev_snapshots) if prev_snapshots is not None else 0}")

    print_new_game_section(new_picks, csv_only=args.csv, game_links=game_links)
    print_improvement_section(improve_picks, csv_only=args.csv, game_links=game_links)
    print_wildcards_section(wildcards, csv_only=args.csv, game_links=game_links)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
