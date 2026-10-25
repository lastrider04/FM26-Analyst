"""Goalkeeper metrics and outfield role scores."""
from analytics.metrics import PlayerAggregate, PlayerMatchLine
from analytics.roles import _percentiles, goalkeeping, role_scores


def gk_line(fid, score, minutes, held, parried, faced, rating=7.0):
    return PlayerMatchLine(fixture_id=fid, date=f"2031-11-{fid:02d}", opponent="X", venue="H", result="W", score=score,
                           competition="PL", unique_id=1, name="Keeper", started=True, minutes=minutes, rating=rating,
                           goals=0, assists=0, xg=0, xa=0, passes_attempted=20, passes_completed=15, distance_km=5,
                           counters={"saves_held": held, "saves_parried": parried, "shots_faced": faced})


def test_goalkeeping_uses_score_for_full_matches_and_shots_for_partial():
    lines = [gk_line(1, "3-1", 90, 2, 1, 4),       # conceded 1 (score)
             gk_line(2, "1-0", 90, 5, 0, 5),       # won 1-0 (score is ours-theirs): conceded 0 -> clean sheet
             gk_line(3, "0-1", 90, 4, 1, 5),       # own goal: 5 saves of 5 on target, but conceded 1 by the score
             gk_line(4, "2-2", 45, 1, 0, 2)]       # subbed off at 45: 2 on target, 1 save -> 1 conceded on his watch
    g = goalkeeping(lines, {1})[1]
    assert (g["saves"], g["shots_on_target_faced"]) == (14, 16)
    assert g["goals_conceded"] == 1 + 0 + 1 + 1 and g["clean_sheets"] == 1
    assert g["save_pct"] == round(100 * 14 / 16, 1) and g["minutes"] == 315


def test_percentiles_and_role_scores():
    assert _percentiles({1: 1.0, 2: 2.0, 3: 2.0, 4: 5.0}) == {1: 0.0, 2: 50.0, 3: 50.0, 4: 100.0}
    a = PlayerAggregate(1, "Creator", minutes=900, apps=10, passes_attempted=500, passes_completed=450, xa=4.0,
                        counters={"key_passes": 30, "progressive_passes": 80, "crosses_completed": 10})
    b = PlayerAggregate(2, "Stopper", minutes=900, apps=10, passes_attempted=400, passes_completed=380, xa=0.5,
                        counters={"key_passes": 3, "progressive_passes": 20, "tackles_won": 40, "interceptions": 30})
    c = PlayerAggregate(3, "Sub", minutes=60, apps=2)                       # too few minutes: no scores
    r = role_scores({1: a, 2: b, 3: c}, {1, 2, 3})
    assert set(r) == {1, 2}
    assert r[1]["chance_creation"] == 100 and r[2]["chance_creation"] == 0
    assert r[2]["defensive_work"] > r[1]["defensive_work"]
    assert r[2]["ball_security"] >= 0
