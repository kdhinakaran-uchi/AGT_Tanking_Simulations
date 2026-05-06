"""Draft pick -> team skill evolution.

Model: each season, a team's skill changes via two forces:
  1. Mean reversion: skill drifts back toward the league average.
  2. Draft pick boost: a linear boost centered at zero for the median pick.
     Pick #1 gives the maximum positive boost; pick #n_teams gives the maximum
     negative adjustment (star players on bad teams, veteran decline, cap issues).

Formula:
  new_skill = skill
             - REVERSION_RATE * (skill - MEAN_SKILL)
             + PICK_SCALE * (1 - 2*(pick - 1) / (n_teams - 1))

Parameters are intentionally small so that one season's pick shifts skill modestly;
multi-season compounding creates realistic long-run divergence between teams.
"""

from simulation.team import Team
from mechanisms.base import DraftResult

MEAN_SKILL: float = 1.0      # long-run league average
REVERSION_RATE: float = 0.10  # fraction of gap to mean closed each season
PICK_SCALE: float = 0.06      # max boost/penalty magnitude (pick 1 vs pick n_teams)
MIN_SKILL: float = 0.25
MAX_SKILL: float = 2.50


def pick_delta(pick: int, n_teams: int) -> float:
    """Skill change from receiving draft pick number `pick`.
    Ranges from +PICK_SCALE (pick 1) through 0 (median) to -PICK_SCALE (pick n_teams).
    """
    return PICK_SCALE * (1.0 - 2.0 * (pick - 1) / (n_teams - 1))


def update_skills(
    teams: list[Team],
    draft_results: list[DraftResult],
    n_teams: int,
) -> None:
    """Update each team's true_skill in-place after the draft."""
    pick_map = {r.team_id: r.pick for r in draft_results}
    for team in teams:
        pick = pick_map[team.team_id]
        reversion = -REVERSION_RATE * (team.true_skill - MEAN_SKILL)
        boost = pick_delta(pick, n_teams)
        team.true_skill = max(MIN_SKILL, min(MAX_SKILL, team.true_skill + reversion + boost))
