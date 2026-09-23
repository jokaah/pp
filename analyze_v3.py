#!/usr/bin/env python3
"""Monthly v3 speedrun picker."""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

from common import (
    build_game_snapshots,
    find_easiest_rank_with_points,
    format_seconds,
    load_blacklist,
    load_game_links,
    load_snapshot,
)
from passive_points import calculate_point_changes, print_point_changes_section
from v3_engine import analyze_new_games, improvement_picks, ranked_lanes, target_summary, wildcard_picks


def parser():
    p = argparse.ArgumentParser(description="V3 monthly speedrun recommendations")
    p.add_argument("-c", "--current", required=True, type=Path)
    p.add_argument("-p", "--previous", type=Path)
    p.add_argument("--my-name", default="Joka")
    p.add_argument("--max-minutes", type=int, default=50)
    p.add_argument("--blacklist", type=Path, default=Path("blacklist.txt"))
    p.add_argument("--quick", type=int, default=15)
    p.add_argument("--grinds", type=int, default=15)
    p.add_argument("--improvements", type=int, default=10)
    p.add_argument("--wildcards", type=int, default=5)
    p.add_argument("--min-improvement", type=float, default=100.0)
    p.add_argument("--csv", type=Path, help="also write one combined CSV report")
    p.add_argument("--mode", choices=("recommendations", "passive", "all"), default="recommendations")
    return p


SCORE_ATTR = {"QUICK POINTS": "quick_score", "WORTH GRINDING": "grind_score"}


def _reason(a, lane):
    if lane == "QUICK POINTS":
        return f"short-run value; durable target #{a.sweet.rank}; accessibility {a.accessibility*100:.0f}/100"
    if lane == "WORTH GRINDING":
        return f"{a.snapshot.n} runners; board softness {a.softness*100:.0f}/100; non-podium opportunity"
    raise ValueError(f"Unknown lane: {lane}")


def _goal_text(snapshot, points):
    rank = find_easiest_rank_with_points(snapshot, points)
    if rank is None:
        return "N/A"
    time = snapshot.by_rank_time.get(rank)
    if time is None:
        return "N/A"
    podium = " (podium)" if rank <= 3 else ""
    return f"{points:.0f} pts @ #{rank} in {format_seconds(time)}{podium}"


def _current_run_text(snapshot):
    if snapshot.my_points is None or snapshot.my_rank is None or snapshot.my_time is None:
        return ""
    return f"{snapshot.my_points:.0f} pts @ #{snapshot.my_rank} in {format_seconds(snapshot.my_time)}"


def _csv_row(section, snapshot, custom_goal, links, include_current=False):
    """A deliberately tiny overview row, modeled after the old CSV output."""
    return {
        "Category": str(section),
        "Game": str(snapshot.game),
        "Current Run": _current_run_text(snapshot) if include_current else "",
        "500 Goal": _goal_text(snapshot, 500.0),
        "700 Goal": _goal_text(snapshot, 700.0),
        "Suggested Goal": target_summary(custom_goal),
        "Leaderboard Link": str(links.get(snapshot.game, "")),
    }


def _print_lane(title, picks, rows, average, run_count, links):
    print(f"\n=== {title} ({len(picks)}) ===")
    for i, a in enumerate(picks, 1):
        impact = (a.sweet.points - average) / (run_count + 1)
        score = getattr(a, SCORE_ATTR[title])
        print(f"{i:>2}. {a.snapshot.game} — {target_summary(a.sweet)}")
        print(f"    score={score:.1f} | runners={a.snapshot.n} | average impact {impact:+.2f}")
        print(f"    {_reason(a, title)}")
        rows.append(_csv_row(title, a.snapshot, a.sweet, links))


def main():
    args = parser().parse_args()
    max_seconds = args.max_minutes * 60
    games, runs = load_snapshot(args.current, max_seconds)
    snapshots = build_game_snapshots(runs, {args.my_name.casefold().strip()})
    blacklist = load_blacklist(args.blacklist)
    links = load_game_links()
    previous = None
    if args.previous:
        _, previous_runs = load_snapshot(args.previous, max_seconds)
        previous = build_game_snapshots(previous_runs, {args.my_name.casefold().strip()})
    if args.mode in {"passive", "all"}:
        if previous is None:
            raise SystemExit("--mode passive/all requires --previous")
        print_point_changes_section(calculate_point_changes(snapshots, previous, blacklist, args.mode), False, args.mode)
        if args.mode == "passive":
            return 0

    my_points = [float(s.my_points) for s in snapshots.values() if s.my_points is not None]
    run_count = len(my_points)
    average = sum(my_points) / run_count if run_count else 0.0
    analyses = analyze_new_games(snapshots, average, blacklist)
    quick, grinds = ranked_lanes(analyses, args.quick, args.grinds)
    improvements = improvement_picks(snapshots, run_count, average, blacklist, args.improvements, args.min_improvement)
    excluded = {a.snapshot.game for a in quick + grinds}
    wildcards = wildcard_picks(analyses, excluded, str(args.current.resolve()), args.wildcards)

    print(f"\nV3 MONTHLY REPORT — {len(games)} games, {run_count} of your runs, current average {average:.2f}")
    rows = []
    _print_lane("QUICK POINTS", quick, rows, average, run_count, links)
    _print_lane("WORTH GRINDING", grinds, rows, average, run_count, links)

    print(f"\n=== IMPROVEMENTS ({len(improvements)}) — minimum +{args.min_improvement:.0f} ===")
    for i, pick in enumerate(improvements, 1):
        print(f"{i:>2}. {pick.snapshot.game}: {pick.snapshot.my_points:.0f} → {pick.target.points:.0f} (+{pick.gain:.0f})")
        print(f"    #{pick.target.rank} in {format_seconds(pick.target.time)} | need {pick.percent_faster*100:.2f}% faster | average +{pick.average_gain:.2f}")
        rows.append(_csv_row("IMPROVEMENTS", pick.snapshot, pick.target, links, include_current=True))

    print(f"\n=== WILDCARDS ({len(wildcards)}) ===")
    for i, (analysis, targets) in enumerate(wildcards, 1):
        print(f"{i:>2}. {analysis.snapshot.game} — {analysis.snapshot.n} runners")
        print("    " + " | ".join(target_summary(t) for t in targets))
        # Wildcards print three scouting goals in the human report, but export
        # exactly one row. The normal 500/700 columns plus the script's custom
        # goal provide the compact spreadsheet view.
        rows.append(_csv_row("WILDCARDS", analysis.snapshot, analysis.sweet, links))

    if args.csv:
        fields = [
            "Category", "Game", "Current Run", "500 Goal", "700 Goal",
            "Suggested Goal", "Leaderboard Link",
        ]
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nCSV written to {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
