"""Quick smoke test for LLM agents across all 5 mechanisms.

Runs 1 season with 10 games per team and one decision checkpoint per team.
Total: ~30 API calls per mechanism, ~150 calls overall. Takes ~3-5 minutes.

Usage:
  $env:ANTHROPIC_API_KEY = "sk-ant-..."
  python test_llm_smoke.py
"""

import os
import random

from simulation.team import Team
from simulation.season import Season
from agents.llm_agent import LLMAgent
from mechanisms.nba_lottery import NBALottery
from mechanisms.bilevel import BilevelMechanism
from mechanisms.cola import COLAMechanism
from mechanisms.weighted_loss import WeightedLossMechanism, exponential_decay
from mechanisms.nba_321_lottery import NBAThreeTwoOneLottery

if not os.environ.get("ANTHROPIC_API_KEY"):
    raise SystemExit("Set ANTHROPIC_API_KEY before running.")

GAMES_PER_TEAM  = 10   # very short season
PLAYOFF_SPOTS   = 16
N_TEAMS         = 30
CHECKPOINT      = 80   # fires once at schedule-game 80 (mid-season)
SEED            = 42

NBA_TEAM_NAMES = [
    "Hawks", "Celtics", "Nets", "Hornets", "Bulls", "Cavaliers", "Mavericks",
    "Nuggets", "Pistons", "Warriors", "Rockets", "Pacers", "Clippers", "Lakers",
    "Grizzlies", "Heat", "Bucks", "Timberwolves", "Pelicans", "Knicks",
    "Thunder", "Magic", "76ers", "Suns", "Trail Blazers", "Kings",
    "Spurs", "Raptors", "Jazz", "Wizards",
]

MECHANISMS = [
    ("nba_lottery",            NBALottery()),
    ("bilevel",                BilevelMechanism()),
    ("cola",                   COLAMechanism()),
    ("weighted_loss_exp_hl20", WeightedLossMechanism(exponential_decay(20.0), "exp_hl20")),
    ("nba_321_lottery",        NBAThreeTwoOneLottery()),
]


def make_teams(seed: int) -> list[Team]:
    rng = random.Random(seed)
    skills = sorted(rng.lognormvariate(0, 0.3) for _ in range(N_TEAMS))
    return [Team(team_id=i, name=NBA_TEAM_NAMES[i], true_skill=skills[i]) for i in range(N_TEAMS)]


def run_one(key: str, mech, rng_seed: int) -> None:
    print(f"\n{'='*60}")
    print(f"  Mechanism: {key}")
    if mech.llm_decision_note:
        preview = mech.llm_decision_note[:80].replace("\n", " ")
        print(f"  Note injected: {preview}...")
    else:
        print("  Note injected: (none)")
    print(f"{'='*60}")

    teams = make_teams(rng_seed)
    agents = {t.team_id: LLMAgent(t) for t in teams}
    rng = random.Random(rng_seed)

    season = Season(
        teams=teams,
        agents=agents,
        mechanism=mech,
        season=0,
        playoff_spots=PLAYOFF_SPOTS,
        games_per_team=GAMES_PER_TEAM,
        checkpoint_interval=CHECKPOINT,
        run_id=f"smoke_{key}",
        db=None,
        rng=rng,
    )
    result = season.run()
    print(f"\n  tanking_rate={result.tanking_rate:.1%}  avg_effort={result.avg_effort:.2f}")
    print(f"  OK")


errors: list[str] = []
for key, mech in MECHANISMS:
    try:
        run_one(key, mech, SEED)
    except Exception as e:
        print(f"\n  ERROR in {key}: {e}")
        errors.append(key)

print(f"\n{'='*60}")
if errors:
    print(f"FAILED mechanisms: {errors}")
else:
    print("All 5 mechanisms passed smoke test.")
