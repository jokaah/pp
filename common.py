from __future__ import annotations

import csv
import hashlib
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

LOGICAL_HEADER = ["rank", "name", "time", "curvea", "curveb", "points", "final"]


@dataclass(frozen=True)
class Run:
    game: str
    rank: int
    name: str
    time_str: str
    time_seconds: Optional[float]
    final_points: float
    source_file: str


@dataclass
class GameSnapshot:
    game: str
    n: int
    t1: Optional[float]
    p1: Optional[float]
    t4: Optional[float]
    p4: Optional[float]
    t15: Optional[float]
    p15: Optional[float]
    spread15_ratio: Optional[float]
    spread15_points: Optional[float]
    has_me: bool
    my_rank: Optional[int]
    my_time: Optional[float]
    my_points: Optional[float]
    by_rank_time: dict[int, Optional[float]]
    by_rank_points: dict[int, float]


@dataclass
class ScoredPick:
    game: str
    score: float
    snapshot: GameSnapshot
    extra: dict


_TIME_HMS_RE = re.compile(r"^\s*(\d+):(\d{2}):(\d{2})(?:\.(\d+))?\s*$")
_TIME_DAYS_RE = re.compile(
    r"^\s*(\d+)\s+day[s]?,\s*(\d+):(\d{2}):(\d{2})(?:\.(\d+))?\s*$",
    re.IGNORECASE,
)


def _fractional_to_seconds(fractional_part: str | None) -> float:
    if not fractional_part:
        return 0.0
    return int(fractional_part) / (10 ** len(fractional_part))


def parse_time_to_seconds(time_string: str, game_name: str = "") -> Optional[float]:
    if not time_string:
        return None
    normalized = time_string.strip()
    if not normalized:
        return None
    is_mega_man = "mega man" in (game_name or "").casefold()

    day_match = _TIME_DAYS_RE.match(normalized)
    if day_match:
        days = int(day_match.group(1))
        hours = int(day_match.group(2))
        minutes = int(day_match.group(3))
        seconds = int(day_match.group(4))
        fractional_seconds = _fractional_to_seconds(day_match.group(5))
        if is_mega_man:
            total_minutes = days * 24 + hours
            total_seconds = minutes
            centiseconds = seconds
            return total_minutes * 60 + total_seconds + (centiseconds / 100.0) + fractional_seconds
        return days * 86400 + hours * 3600 + minutes * 60 + seconds + fractional_seconds

    hms_match = _TIME_HMS_RE.match(normalized)
    if not hms_match:
        return None

    part_a = int(hms_match.group(1))
    part_b = int(hms_match.group(2))
    part_c = int(hms_match.group(3))
    fractional_seconds = _fractional_to_seconds(hms_match.group(4))

    if is_mega_man:
        minutes = part_a
        seconds = part_b
        centiseconds = part_c
        return minutes * 60 + seconds + (centiseconds / 100.0) + fractional_seconds

    return part_a * 3600 + part_b * 60 + part_c + fractional_seconds


def format_seconds(seconds: Optional[float], decimals: int = 3) -> str:
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return "N/A"

    scaled = int(round(seconds * (10 ** decimals)))
    scale = 10 ** decimals
    whole_seconds = scaled // scale
    fractional = scaled % scale

    hours = whole_seconds // 3600
    minutes = (whole_seconds % 3600) // 60
    secs = whole_seconds % 3600 % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}.{fractional:0{decimals}d}"
    return f"{minutes}:{secs:02d}.{fractional:0{decimals}d}"


def csv_time(seconds: Optional[float]) -> str:
    s = format_seconds(seconds)
    return f"'{s}" if s != "N/A" else "'N/A"


def normalize_game_name(name: str) -> str:
    if not name:
        return name

    name = name.strip()

    # Handle ", The", ", A", ", An"
    for article in ("The", "A", "An"):
        suffix = f", {article}"
        if name.endswith(suffix):
            base = name[: -len(suffix)].strip()
            return f"{article} {base}"

    return name

def to_float(value: str) -> Optional[float]:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped or stripped.upper() in {"NAN", "NONE"}:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def load_game_links(path: Path = Path("./games.csv")) -> dict[str, str]:
    links = {}

    if not path.exists():
        return links

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("NES Game") or row.get("game")
            link = row.get("Relevant Link") or row.get("link")

            if name and link:
                links[name.strip()] = link.strip()

    return links


def parse_rank(value: str) -> Optional[int]:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    try:
        rank_value = float(stripped)
        if math.isnan(rank_value) or rank_value <= 0:
            return None
        return int(round(rank_value))
    except ValueError:
        return None


def normalize_header(header_cell: str) -> str:
    normalized = (header_cell or "").strip().casefold()
    return re.sub(r"[\s\-\_\(\)\[\]\{\}\.\:\/\\]+", "", normalized)


def _cell(rows: list[list[str]], row_index: int, col_index: int) -> str:
    if row_index < 0 or row_index >= len(rows):
        return ""
    if col_index < 0 or col_index >= len(rows[row_index]):
        return ""
    return (rows[row_index][col_index] or "").strip()


def _looks_like_header_block(rows: list[list[str]], header_row: int, header_col: int) -> bool:
    for offset, header_key in enumerate(LOGICAL_HEADER):
        if normalize_header(_cell(rows, header_row, header_col + offset)) != header_key:
            return False
    return True


def _find_game_name(rows: list[list[str]], header_row: int, header_col: int) -> str:
    title = _cell(rows, 0, header_col)
    if title:
        return title
    for row in range(header_row - 1, -1, -1):
        title = _cell(rows, row, header_col)
        if title:
            return title
    return f"UNKNOWN_GAME_COL_{header_col}"


def _read_csv_rows(path: Path) -> list[list[str]]:
    raw_bytes = path.read_bytes()
    text = raw_bytes.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t,")
    except Exception:
        dialect = csv.excel
    reader = csv.reader(text.splitlines(), dialect)
    return [list(row) for row in reader]


def parse_csv_file(path: Path, max_run_seconds: int) -> tuple[set[str], list[Run]]:
    rows = _read_csv_rows(path)
    games_detected: set[str] = set()
    runs: list[Run] = []

    for row_index in range(len(rows)):
        for col_index in range(len(rows[row_index])):
            if normalize_header(_cell(rows, row_index, col_index)) != "rank":
                continue
            if not _looks_like_header_block(rows, row_index, col_index):
                continue

            game_name = _find_game_name(rows, row_index, col_index)
            games_detected.add(game_name)

            data_row_index = row_index + 1
            while data_row_index < len(rows):
                if (
                    normalize_header(_cell(rows, data_row_index, col_index)) == "rank"
                    and _looks_like_header_block(rows, data_row_index, col_index)
                ):
                    break

                rank_text = _cell(rows, data_row_index, col_index + 0)
                player_name = _cell(rows, data_row_index, col_index + 1)
                time_text = _cell(rows, data_row_index, col_index + 2)
                final_points_text = _cell(rows, data_row_index, col_index + 6)

                if not rank_text and not player_name and not time_text and not final_points_text:
                    data_row_index += 1
                    continue
                if "#DIV/0!" in (final_points_text or ""):
                    data_row_index += 1
                    continue

                rank = parse_rank(rank_text)
                if rank is None or not player_name:
                    data_row_index += 1
                    continue

                final_points = to_float(final_points_text)
                if final_points is None or (isinstance(final_points, float) and math.isnan(final_points)):
                    data_row_index += 1
                    continue

                time_seconds = parse_time_to_seconds(time_text, game_name)
                if time_seconds is not None and time_seconds >= max_run_seconds:
                    data_row_index += 1
                    continue

                runs.append(
                    Run(
                        game=game_name,
                        rank=rank,
                        name=player_name,
                        time_str=time_text,
                        time_seconds=time_seconds,
                        final_points=float(final_points),
                        source_file=path.name,
                    )
                )
                data_row_index += 1

    return games_detected, runs


def load_snapshot(path: Path, max_run_seconds: int) -> tuple[set[str], list[Run]]:
    path = path.expanduser().resolve()
    if path.is_dir():
        csv_files = sorted(p for p in path.iterdir() if p.suffix.lower() == ".csv")
        if not csv_files:
            raise SystemExit(f"No .csv files found in: {path}")
        all_games: set[str] = set()
        all_runs: list[Run] = []
        for csv_path in csv_files:
            games, runs = parse_csv_file(csv_path, max_run_seconds=max_run_seconds)
            all_games |= games
            all_runs.extend(runs)
        return all_games, all_runs
    if path.is_file():
        return parse_csv_file(path, max_run_seconds=max_run_seconds)
    raise SystemExit(f"Path not found: {path}")


def top15_rank(n: int) -> int:
    if n <= 0:
        return 1
    return max(1, int(math.ceil(0.15 * n)))


def build_game_snapshots(runs: list[Run], my_names_casefold: set[str]) -> dict[str, GameSnapshot]:
    runs_by_game: dict[str, list[Run]] = defaultdict(list)
    for run in runs:
        runs_by_game[run.game].append(run)
    for game in runs_by_game:
        runs_by_game[game].sort(key=lambda item: item.rank)

    my_best: dict[str, Run] = {}
    for run in runs:
        if run.name.strip().casefold() not in my_names_casefold:
            continue
        prev = my_best.get(run.game)
        if prev is None or run.rank < prev.rank:
            my_best[run.game] = run

    snapshots: dict[str, GameSnapshot] = {}
    for game, game_runs in runs_by_game.items():
        by_rank_time = {run.rank: run.time_seconds for run in game_runs}
        by_rank_points = {run.rank: run.final_points for run in game_runs}
        n = len(game_runs)

        r1t = by_rank_time.get(1)
        r1p = by_rank_points.get(1)
        r4t = by_rank_time.get(4)
        r4p = by_rank_points.get(4)
        r15 = top15_rank(n)
        r15t = by_rank_time.get(r15)
        r15p = by_rank_points.get(r15)

        spread15_ratio = None
        if r1t is not None and r15t is not None and r1t > 0 and r15t >= r1t:
            spread15_ratio = (r15t - r1t) / r1t

        spread15_points = None
        if r1p is not None and r15p is not None:
            spread15_points = float(r1p) - float(r15p)

        my_run = my_best.get(game)
        snapshots[game] = GameSnapshot(
            game=game,
            n=n,
            t1=r1t,
            p1=r1p,
            t4=r4t,
            p4=r4p,
            t15=r15t,
            p15=r15p,
            spread15_ratio=spread15_ratio,
            spread15_points=spread15_points,
            has_me=(my_run is not None),
            my_rank=(my_run.rank if my_run else None),
            my_time=(my_run.time_seconds if my_run else None),
            my_points=(my_run.final_points if my_run else None),
            by_rank_time=by_rank_time,
            by_rank_points=by_rank_points,
        )
    return snapshots


def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def percentile_rank(sorted_values: list[float], x: float) -> float:
    if not sorted_values:
        return 0.5
    lo, hi = 0, len(sorted_values)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_values[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo / len(sorted_values)


def safe_log_norm(n: int, n_max: int) -> float:
    if n_max <= 1:
        return 0.0
    return clamp01(math.log(n + 1) / math.log(n_max + 1))


def deterministic_tiebreak(game: str) -> float:
    h = hashlib.sha1(game.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def load_blacklist(path: Optional[Path]) -> set[str]:
    if path is None:
        return set()
    text = path.expanduser().resolve().read_text(encoding="utf-8")
    return {
        line.strip().casefold()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def is_blacklisted(game: str, blacklist: set[str]) -> bool:
    return game.strip().casefold() in blacklist


def time_at_rank(snapshot: GameSnapshot, rank: int) -> Optional[float]:
    return snapshot.by_rank_time.get(rank)


def highest_rank_number_available(snapshot: GameSnapshot) -> int:
    return max(snapshot.by_rank_points) if snapshot.by_rank_points else 0


def find_easiest_rank_with_points(snapshot: GameSnapshot, threshold: float) -> Optional[int]:
    for rank in range(highest_rank_number_available(snapshot), 0, -1):
        time_value = snapshot.by_rank_time.get(rank)
        points_value = snapshot.by_rank_points.get(rank)
        if time_value is None or points_value is None:
            continue
        if float(points_value) >= threshold:
            return rank
    return None


def find_time_for_points_threshold(snapshot: GameSnapshot, threshold: float) -> Optional[float]:
    rank = find_easiest_rank_with_points(snapshot, threshold)
    return snapshot.by_rank_time.get(rank) if rank is not None else None


def count_safety_ranks_for_threshold(snapshot: GameSnapshot, achieved_rank: Optional[int], threshold: float) -> int:
    if achieved_rank is None:
        return 0
    count = 0
    for rank in range(achieved_rank + 1, highest_rank_number_available(snapshot) + 1):
        points_value = snapshot.by_rank_points.get(rank)
        if points_value is None:
            break
        if float(points_value) >= threshold:
            count += 1
        else:
            break
    return count


def tail_depth_from_rank(snapshot: GameSnapshot, rank: Optional[int]) -> int:
    return max(0, snapshot.n - rank) if rank is not None else 0


def rank_gap_for_threshold(snapshot: GameSnapshot, threshold: float, anchor_rank: int = 4) -> Optional[int]:
    target_rank = find_easiest_rank_with_points(snapshot, threshold)
    if target_rank is None:
        return None
    return max(0, anchor_rank - target_rank)


def compression_ratio(time_a: Optional[float], time_b: Optional[float]) -> Optional[float]:
    if time_a is None or time_b is None or time_a <= 0 or time_b < time_a:
        return None
    return (time_b - time_a) / time_a


def count_wr_ties(snapshot: GameSnapshot, epsilon: float = 1e-9) -> int:
    ranked_times = [
        time_value
        for _, time_value in sorted(snapshot.by_rank_time.items())
        if time_value is not None and math.isfinite(time_value)
    ]
    if not ranked_times:
        return 0
    best = ranked_times[0]
    return sum(1 for time_value in ranked_times if abs(time_value - best) <= epsilon)


def find_easiest_rank_for_gain(snapshot: GameSnapshot, gain_threshold: float) -> Optional[int]:
    if not snapshot.has_me or snapshot.my_rank is None or snapshot.my_points is None or snapshot.my_time is None:
        return None
    my_rank = snapshot.my_rank
    my_points = float(snapshot.my_points)
    my_time = float(snapshot.my_time)
    for rank in range(my_rank - 1, 0, -1):
        time_value = snapshot.by_rank_time.get(rank)
        points_value = snapshot.by_rank_points.get(rank)
        if time_value is None or points_value is None:
            continue
        if float(points_value) - my_points >= gain_threshold and my_time - float(time_value) > 0:
            return rank
    return None


def time_for_gain(snapshot: GameSnapshot, gain_threshold: float) -> Optional[float]:
    rank = find_easiest_rank_for_gain(snapshot, gain_threshold)
    return snapshot.by_rank_time.get(rank) if rank is not None else None


def dedupe_picks(
    new_picks: list[ScoredPick],
    improve_picks: list[ScoredPick],
    wildcards: list[dict],
) -> tuple[list[ScoredPick], list[ScoredPick], list[dict]]:
    used: set[str] = set()

    improvement_output: list[ScoredPick] = []
    for pick in improve_picks:
        if pick.game not in used:
            improvement_output.append(pick)
            used.add(pick.game)

    new_output: list[ScoredPick] = []
    for pick in new_picks:
        if pick.game not in used:
            new_output.append(pick)
            used.add(pick.game)

    wildcard_output: list[dict] = []
    for wildcard in wildcards:
        game = wildcard.get("game")
        if game and game not in used:
            wildcard_output.append(wildcard)
            used.add(game)

    return new_output, improvement_output, wildcard_output


def print_new_game_section(picks: list[ScoredPick], csv_only: bool = False, game_links: dict[str, str] | None = None) -> None:
    print("\n=== NEW GAME PICKS ===")

    for index, pick in enumerate(picks, start=1):
        snapshot = pick.snapshot
        t500 = pick.extra.get("t500")
        t700 = pick.extra.get("t700")
        growth = pick.extra.get("growth")
        growth_str = "N/A" if growth is None else f"{growth*100:.1f}%"
        r500 = pick.extra.get("r500")
        buffer500 = pick.extra.get("buffer500")
        safety500 = pick.extra.get("safety500")
        tail_depth = pick.extra.get("tail_depth")

        link = ""
        if game_links:
            link = game_links.get(snapshot.game, "")

        csv_row = f"{normalize_game_name(snapshot.game)},{csv_time(t500)},{csv_time(t700)},{csv_time(snapshot.t4)},{link}"

        if csv_only:
            print(csv_row)
            continue

        print(f"{index:>2}. {snapshot.game}")
        print(
            f"    score={pick.score:.2f} runners={snapshot.n} "
            f"runner_growth(prev)={growth_str} WR={format_seconds(snapshot.t1)}"
        )
        print(
            f"    times: 500+={format_seconds(t500)} "
            f"700+={format_seconds(t700)} #4={format_seconds(snapshot.t4)}"
        )
        print(
            f"    analysis: 500@rank {r500 if r500 is not None else 'N/A'} | "
            f"buffer {buffer500:+.1f} pts | safety {safety500} ranks | "
            f"tail {tail_depth} runners | "
            f"headroom_to_4 {pick.extra.get('investment_headroom', 0.0):+.1f} pts"
        )


def print_improvement_section(picks: list[ScoredPick], csv_only: bool = False, game_links: dict[str, str] | None = None) -> None:
    print("\n=== IMPROVEMENT PICKS ===")

    for index, pick in enumerate(picks, start=1):
        snapshot = pick.snapshot
        t500 = find_time_for_points_threshold(snapshot, 500.0)
        t700 = find_time_for_points_threshold(snapshot, 700.0)
        t100 = time_for_gain(snapshot, 100.0)
        t200 = time_for_gain(snapshot, 200.0)

        podium_hits = pick.extra.get("podium_hits") or []
        penalty_note = ""
        if podium_hits:
            penalty_note = (
                f" penalty=-{(pick.extra.get('podium_penalty', 0.0) * 100):.0f}"
                f" ({', '.join(podium_hits)} need podium)"
            )

        pct100 = pick.extra.get("pct_for_100")
        pct200 = pick.extra.get("pct_for_200")
        pct100_str = "N/A" if pct100 is None else f"{pct100 * 100:.2f}%"
        pct200_str = "N/A" if pct200 is None else f"{pct200 * 100:.2f}%"

        link = ""
        if game_links:
            link = game_links.get(snapshot.game, "")

        csv_row = (
            f"{normalize_game_name(snapshot.game)},"
            f"{csv_time(snapshot.my_time)},"
            f"{csv_time(t500) if pick.extra.get('rank_for_500') is not None else ''},"
            f"{csv_time(t700) if pick.extra.get('rank_for_700') is not None else ''},"
            f"{csv_time(t100) if pick.extra.get('rank_for_100') is not None else ''},"
            f"{csv_time(t200) if pick.extra.get('rank_for_200') is not None else ''},"
            f"{csv_time(snapshot.t4)},"
            f"{link}"
        )

        if csv_only:
            print(csv_row)
            continue

        print(f"{index:>2}. {snapshot.game}")
        print(
            f"    score={pick.score:.2f}{penalty_note} you: rank={snapshot.my_rank} "
            f"pts={snapshot.my_points:.1f} time={format_seconds(snapshot.my_time)} "
            f"runners={snapshot.n} WR={format_seconds(snapshot.t1)}"
        )
        print(
            f"    targets: 500={format_seconds(t500)}"
            f" (rank {pick.extra.get('rank_for_500') if pick.extra.get('rank_for_500') is not None else 'N/A'})"
            f" 700={format_seconds(t700)}"
            f" (rank {pick.extra.get('rank_for_700') if pick.extra.get('rank_for_700') is not None else 'N/A'})"
            f" +100={format_seconds(t100)}"
            f" (rank {pick.extra.get('rank_for_100') if pick.extra.get('rank_for_100') is not None else 'N/A'}, need {pct100_str})"
            f" +200={format_seconds(t200)}"
            f" (rank {pick.extra.get('rank_for_200') if pick.extra.get('rank_for_200') is not None else 'N/A'}, need {pct200_str})"
            f" #4={format_seconds(snapshot.t4)}"
        )


def print_wildcards_section(items: list[dict], csv_only: bool = False, game_links: dict[str, str] | None = None) -> None:
    print("\n=== WILDCARDS ===")

    for index, item in enumerate(items, start=1):
        link = ""
        if game_links:
            link = game_links.get(item["game"], "")

        csv_row = (
            f"{normalize_game_name(item['game'])},"
            f"{csv_time(item.get('t500'))},"
            f"{csv_time(item.get('t700'))},"
            f"{csv_time(item.get('t4'))},"
            f"{link}"
        )

        if csv_only:
            print(csv_row)
            continue

        print(f"{index:>2}. {item['game']} - {item['why']}")
