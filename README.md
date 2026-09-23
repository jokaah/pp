# PP v3

Monthly speedrun recommendations built around distinct decisions instead of one
universal score.

## Run it

```bash
python3 analyze_v3.py -c ../snapshots/sep26 -p ../snapshots/aug26
```

The monthly `sep26` and `aug26` snapshot directories are private inputs and
are not checked into this repository. Put them outside the checkout and pass
their paths to the report, for example `-c ../snapshots/sep26 -p
../snapshots/aug26`. The integration tests currently expect `sep26` and
`aug26` at the checkout root; local symlinks to those external directories
allow `python3 -m unittest -v test_v3` to run without copying snapshot data
into Git.

Defaults: 15 Quick Points, 15 Worth Grinding, 10 Improvements, and 5
Wildcards. Use `--help` to change the counts.

## V3 rules

- **Quick Points** balances durable points, run length, rank depth, and how
  forgiving the leaderboard looks.
- **Worth Grinding** values meaningful/popular games, penalizes compressed
  competitive regions, and rewards sustained gaps around ranks 4–20.
- **Improvements** requires at least +100 points by default and ranks targets
  by gain, resulting score, feasibility, and effect on average.
- **Wildcards** stay lightweight and deterministic, but include three concrete
  non-podium point/time/rank goals as a scouting report.
- **Podium ranks are never recommendation targets.** Landing on a podium is
  fine; planning around one is not.

The first calibration pass also recognizes a practical Grind sweet spot
(established boards, roughly 6–18 minutes, with a durable 700-point target),
while extremely short games are primarily treated as Quick territory rather
than automatic Grind material. Games may appear in both main lanes when they
genuinely fit both.

The old scripts remain for comparison. V3 reuses `common.py` for the proven
spreadsheet parsing and `passive_points.py` for monthly point changes.

The CLI prints a compact CSV after the detailed report; `--csv v3_report.csv`
also saves it. Its columns are category, game, current run (for Improvements),
goal one, goal two, final goal, and leaderboard link. Wildcards use their three
scouting goals. Goals at or slower than an existing personal time are blank.
Each game occupies one row.
