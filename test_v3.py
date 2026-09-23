import unittest
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

from common import build_game_snapshots, load_snapshot
from v3_engine import analyze_new_games, improvement_picks, ranked_lanes, wildcard_picks


class V3IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, runs = load_snapshot(Path("sep26"), 50 * 60)
        cls.snapshots = build_game_snapshots(runs, {"joka"})
        points = [s.my_points for s in cls.snapshots.values() if s.my_points is not None]
        cls.average = sum(points) / len(points)
        cls.analyses = analyze_new_games(cls.snapshots, cls.average, set())

    def test_recommendations_never_target_podium(self):
        quick, grind = ranked_lanes(self.analyses)
        self.assertEqual(15, len(quick))
        self.assertEqual(15, len(grind))
        self.assertTrue(all(a.sweet.rank >= 4 for a in quick + grind))

    def test_improvements_respect_gain_floor_and_no_podium(self):
        picks = improvement_picks(self.snapshots, 86, self.average, set(), count=100)
        self.assertTrue(picks)
        self.assertTrue(all(p.gain >= 100 and p.target.rank >= 4 for p in picks))

    def test_wildcards_have_three_scouting_goals(self):
        picks = wildcard_picks(self.analyses, set(), "sep26", 5)
        self.assertEqual(5, len(picks))
        self.assertTrue(all(len(targets) == 3 for _, targets in picks))

    def test_first_user_calibration_examples(self):
        quick, grind = ranked_lanes(self.analyses, quick_n=30, grind_n=40)
        quick_rank = {pick.snapshot.game: i for i, pick in enumerate(quick, 1)}
        grind_rank = {pick.snapshot.game: i for i, pick in enumerate(grind, 1)}

        self.assertLessEqual(grind_rank["Chip 'n Dale Rescue Rangers 2"], 10)
        self.assertLessEqual(grind_rank["Ninja Gaiden II: The Dark Sword of Chaos"], 10)
        self.assertLessEqual(grind_rank["Jackal"], 15)
        self.assertLessEqual(grind_rank["Kabuki: Quantum Fighter"], 20)
        self.assertLessEqual(grind_rank["Shadow of the Ninja"], 20)
        self.assertGreater(grind_rank.get("Legend of Zelda, The", 999), 10)
        self.assertLessEqual(quick_rank["Mario's Time Machine"], 15)
        self.assertLessEqual(quick_rank["Sesame Street Countdown"], 30)
        self.assertGreater(quick_rank["Pinball"], quick_rank["Jackal"])

    def test_wildcard_goals_are_useful_non_podium_milestones(self):
        quick, grind = ranked_lanes(self.analyses)
        excluded = {a.snapshot.game for a in quick + grind}
        picks = wildcard_picks(self.analyses, excluded, "sep26", 5)
        self.assertTrue(all(all(t.rank >= 4 and t.points >= 300 for t in goals)
                            for _, goals in picks))

    def test_csv_has_one_wildcard_row_per_game_and_goal_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.csv"
            subprocess.run(
                [sys.executable, "analyze_v3.py", "-c", "sep26", "-p", "aug26", "--csv", str(output)],
                check=True, capture_output=True, text=True,
            )
            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(
            ["Category", "Game", "Current Run", "500 Goal", "700 Goal", "Suggested Goal", "Leaderboard Link"],
            list(rows[0]),
        )
        wildcards = [row for row in rows if row["Category"] == "WILDCARDS"]
        self.assertEqual(5, len(wildcards))
        self.assertEqual(5, len({row["Game"] for row in wildcards}))
        self.assertTrue(all(row["Suggested Goal"] and row["500 Goal"] and row["700 Goal"] for row in rows))
        self.assertTrue(any(row["Leaderboard Link"] for row in rows))
        improvements = [row for row in rows if row["Category"] == "IMPROVEMENTS"]
        self.assertTrue(all(row["Current Run"] for row in improvements))
        self.assertTrue(all(not row["Current Run"] for row in rows if row["Category"] != "IMPROVEMENTS"))
        self.assertNotIn("GOLD NUGGETS", {row["Category"] for row in rows})


if __name__ == "__main__":
    unittest.main()
