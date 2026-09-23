# PP v3

Monthly speedrun recommendations built around distinct decisions instead of one
universal score.

## Run it

```bash
python3 analyze_v3.py -c sep26 -p aug26 --csv v3_report.csv
```

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

The optional CSV is intentionally a minimal overview: category, game, current
run (for Improvements), 500 goal, 700 goal, suggested goal, and leaderboard
link. Each game occupies one row, including each Wildcard. Detailed scoring and
selection explanations stay in the CLI output.
