import random as _random
from simulation.team import Team

# Even a tanking team still plays at 30% effective strength — you can't perfectly throw games.
EFFORT_FLOOR = 0.3


def win_probability(skill_a: float, effort_a: float, skill_b: float, effort_b: float) -> float:
    """P(team A wins) using ratio of effective strengths."""
    eff_a = skill_a * (EFFORT_FLOOR + (1 - EFFORT_FLOOR) * effort_a)
    eff_b = skill_b * (EFFORT_FLOOR + (1 - EFFORT_FLOOR) * effort_b)
    return eff_a / (eff_a + eff_b)


def simulate_game(
    team_a: Team,
    effort_a: float,
    team_b: Team,
    effort_b: float,
    rng: _random.Random | None = None,
) -> tuple[Team, Team]:
    """Simulate one game. Updates win/loss counts in-place. Returns (winner, loser)."""
    r = (rng or _random).random()
    if r < win_probability(team_a.true_skill, effort_a, team_b.true_skill, effort_b):
        winner, loser = team_a, team_b
    else:
        winner, loser = team_b, team_a
    winner.wins += 1
    loser.losses += 1
    return winner, loser
