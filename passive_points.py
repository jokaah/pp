from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from common import GameSnapshot, is_blacklisted, normalize_game_name


@dataclass(frozen=True)
class PointChange:
    game: str
    previous_points: float
    current_points: float
    delta: float


def calculate_point_changes(
    cur: dict[str, GameSnapshot],
    prev: dict[str, GameSnapshot],
    blacklist: Optional[set[str]] = None,
    mode: str = "passive",
) -> list[PointChange]:
    blacklist = blacklist or set()
    changes: list[PointChange] = []

    for game in sorted(set(cur) & set(prev)):
        current = cur[game]
        previous = prev[game]
        previous_points = 0

        if previous.has_me and previous.my_points is not None:
            previous_points = previous.my_points

        if not current.has_me or (not previous.has_me and mode == "passive"):
            continue
        if current.my_points is None or (previous.my_points is None and mode == "passive"):
            continue

        changes.append(
            PointChange(
                game=game,
                previous_points=float(previous_points),
                current_points=float(current.my_points),
                delta=float(current.my_points) - float(previous_points),
            )
        )

    changes.sort(key=lambda item: (-(item.delta), item.game.casefold()))
    return changes


def print_point_changes_section(
    changes: list[PointChange],
    csv_only: bool = False,
    mode: str = "passive",
) -> None:
    total = sum(item.delta for item in changes)

    if csv_only:
        for item in changes:
            print(
                f"{normalize_game_name(item.game)},"
                f"{item.previous_points:.1f},"
                f"{item.current_points:.1f},"
                f"{item.delta:+.1f}"
            )
        print(f"TOTAL,,,{total:+.1f}")
        return

    print(f"\n=== POINT CHANGES ({mode}) ===")
    print(f"Games compared: {len(changes)}")
    print(f"Total point change: {total:+.1f}\n")

    for item in changes:
        print(
            f"{item.game}: "
            f"{item.previous_points:.1f} -> {item.current_points:.1f} "
            f"({item.delta:+.1f})"
        )
