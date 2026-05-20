"""
NBA Tanking Simulation -- experiment runner.

Standard comparison (all 3 mechanisms, 50 seasons, rational agents):
  python main.py

Single mechanism:
  python main.py --mechanism nba --seasons 100

LLM agents (requires ANTHROPIC_API_KEY):
  python main.py --agent llm --mechanism nba --seasons 10

Mixed population (29 honest teams + 1 rational):
  python main.py --mechanism nba --agent mixed --n-rational 1 --seasons 50

Playoff value sensitivity sweep:
  python main.py --mechanism nba --playoff-values 20,50,80,120

Reset DB before running:
  python main.py --reset-db

Skip DB writes for quick tests:
  python main.py --no-db --seasons 5
"""

import argparse
import os
import random
import time
import uuid
from pathlib import Path

from simulation.team import Team
from simulation.season import Season
from simulation.skill_update import update_skills
from mechanisms.nba_lottery import NBALottery
from mechanisms.bilevel import BilevelMechanism
from mechanisms.cola import COLAMechanism
from mechanisms.weighted_loss import WeightedLossMechanism, exponential_decay
from mechanisms.nba_321_lottery import NBAThreeTwoOneLottery
from mechanisms.base import DraftMechanism
from agents.base import Agent
from agents.rational import RationalAgent, PICK_VALUES
from agents.honest import HonestAgent
from agents.llm_agent import LLMAgent
from data.db import Database
from data.export import export_run

# ── experiment parameters ─────────────────────────────────────────────────────

N_TEAMS = 30
PLAYOFF_SPOTS = 16
GAMES_PER_TEAM = 82
CHECKPOINT_INTERVAL = 10
SNAPSHOT_INTERVAL = 10
DEFAULT_SEASONS = 50
DEFAULT_PLAYOFF_VALUE = 50.0

NBA_TEAM_NAMES = [
    "Hawks", "Celtics", "Nets", "Hornets", "Bulls", "Cavaliers", "Mavericks",
    "Nuggets", "Pistons", "Warriors", "Rockets", "Pacers", "Clippers", "Lakers",
    "Grizzlies", "Heat", "Bucks", "Timberwolves", "Pelicans", "Knicks",
    "Thunder", "Magic", "76ers", "Suns", "Trail Blazers", "Kings",
    "Spurs", "Raptors", "Jazz", "Wizards",
]

# ── helpers ───────────────────────────────────────────────────────────────────

def create_teams(seed: int = 42) -> list[Team]:
    rng = random.Random(seed)
    skills = sorted(rng.lognormvariate(0, 0.3) for _ in range(N_TEAMS))
    return [Team(team_id=i, name=NBA_TEAM_NAMES[i], true_skill=skills[i]) for i in range(N_TEAMS)]


def kendall_tau_distance(order_a: list[int], order_b: list[int]) -> float:
    """Normalized Kendall tau distance (0 = identical rankings, 1 = fully reversed)."""
    n = len(order_a)
    pos_b = {v: i for i, v in enumerate(order_b)}
    discordant = sum(
        1
        for i in range(n)
        for j in range(i + 1, n)
        if pos_b[order_a[i]] > pos_b[order_a[j]]
    )
    pairs = n * (n - 1) // 2
    return discordant / pairs if pairs else 0.0


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


# ── core experiment ───────────────────────────────────────────────────────────

def run_experiment(
    mechanism: DraftMechanism,
    agent_type: str,          # "rational" | "honest" | "llm" | "mixed"
    n_seasons: int,
    db: Database | None,
    seed: int = 42,
    n_rational: int = N_TEAMS,  # for mixed: how many rational agents (rest honest)
    playoff_value: float = DEFAULT_PLAYOFF_VALUE,
    label: str | None = None,
) -> str:
    rng = random.Random(seed)
    teams = create_teams(seed)
    n_lottery = N_TEAMS - PLAYOFF_SPOTS

    run_id = label or f"{mechanism.name}_{agent_type}_{uuid.uuid4().hex[:8]}"

    if db:
        db.create_run(
            run_id=run_id,
            mechanism=mechanism.name,
            agent_type=agent_type,
            n_teams=N_TEAMS,
            playoff_spots=PLAYOFF_SPOTS,
            games_per_team=GAMES_PER_TEAM,
            n_seasons=n_seasons,
            checkpoint_interval=CHECKPOINT_INTERVAL,
            params={"n_rational": n_rational, "playoff_value": playoff_value},
        )
        db.insert_teams(run_id, teams)

    # Pre-compute expected pick value table (used by rational agents)
    print(f"  Pre-computing EV table for {mechanism.name}...", end=" ", flush=True)
    ev_table = mechanism.expected_pick_values(
        n_lottery, PICK_VALUES, n_sims=5000, rng=random.Random(seed)
    )
    print("done")

    # Build agent roster
    def make_agent(team: Team, is_rational: bool) -> Agent:
        if agent_type == "honest" or not is_rational:
            return HonestAgent(team)
        if agent_type in ("rational", "mixed"):
            a = RationalAgent(team, playoff_value=playoff_value)
            a.set_ev_table(ev_table)
            return a
        if agent_type == "llm":
            return LLMAgent(team)
        raise ValueError(f"Unknown agent type: {agent_type!r}")

    # For mixed: last n_rational teams (highest team_id, i.e. strongest initial skill) are rational
    sorted_ids = sorted(t.team_id for t in teams)
    rational_ids = set(sorted_ids[N_TEAMS - n_rational :])
    agents = {t.team_id: make_agent(t, t.team_id in rational_ids) for t in teams}

    true_skill_rank = [t.team_id for t in sorted(teams, key=lambda t: t.true_skill, reverse=True)]

    tanking_rates: list[float] = []
    tau_distances: list[float] = []

    for s in range(n_seasons):
        for t in teams:
            t.reset_season_record()

        if db:
            db.insert_skill_snapshot(run_id, s, teams)

        season = Season(
            teams=teams,
            agents=agents,
            mechanism=mechanism,
            season=s,
            playoff_spots=PLAYOFF_SPOTS,
            games_per_team=GAMES_PER_TEAM,
            checkpoint_interval=CHECKPOINT_INTERVAL,
            run_id=run_id,
            db=db,
            rng=random.Random(rng.randint(0, 2**31)),
            snapshot_interval=SNAPSHOT_INTERVAL,
        )
        result = season.run()

        # Update team skills based on draft picks received
        update_skills(teams, result.draft_results, N_TEAMS)

        # Recompute true-skill ranking after skill update (it evolves each season)
        true_skill_rank = [t.team_id for t in sorted(teams, key=lambda t: t.true_skill, reverse=True)]

        tanking_rates.append(result.tanking_rate)
        final_rank = [t.team_id for t in sorted(teams, key=lambda t: t.wins, reverse=True)]
        tau_distances.append(kendall_tau_distance(true_skill_rank, final_rank))

        if (s + 1) % 10 == 0 or s == 0:
            window_t = tanking_rates[-10:]
            window_d = tau_distances[-10:]
            print(
                f"  s={s+1:3d}/{n_seasons}  "
                f"tanking={_mean(window_t):5.1%}  "
                f"tau-dist={_mean(window_d):.3f}"
            )

    print(f"\n  [{mechanism.name.upper()}] Summary:")
    print(f"    agent={agent_type}  n_rational={n_rational}  playoff_value={playoff_value}")
    print(f"    Avg tanking rate : {_mean(tanking_rates):.1%}")
    print(f"    Avg tau distance : {_mean(tau_distances):.3f}  (0=perfect, 1=worst)")
    return run_id


# ── experiment presets ────────────────────────────────────────────────────────

def run_standard(args, db):
    """Compare all mechanisms head-to-head."""
    mechanisms = {
        "nba": NBALottery(),
        "bilevel": BilevelMechanism(),
        "cola": COLAMechanism(),
        "weighted_loss": WeightedLossMechanism(),  # default: exponential decay, half-life 20
        "nba_321": NBAThreeTwoOneLottery(),
    }
    to_run = list(mechanisms.values()) if args.mechanism == "all" else [mechanisms[args.mechanism]]
    run_ids = []
    for mech in to_run:
        _print_header(mech.name, args.agent, args.seasons)
        t0 = time.time()
        rid = run_experiment(
            mech, args.agent, args.seasons, db,
            seed=args.seed, playoff_value=args.playoff_value,
        )
        run_ids.append(rid)
        print(f"  Completed in {time.time()-t0:.1f}s  |  run_id={rid}")
    return run_ids


def run_mixed(args, db):
    """Stability experiment: vary the number of rational agents from 0 to N_TEAMS."""
    mech = {
        "nba": NBALottery(),
        "bilevel": BilevelMechanism(),
        "cola": COLAMechanism(),
        "weighted_loss": WeightedLossMechanism(),
    }[args.mechanism]
    run_ids = []
    for n_rat in args.mixed_sweep:
        label = f"{mech.name}_mixed_{n_rat}rational_{uuid.uuid4().hex[:6]}"
        _print_header(mech.name, f"mixed({n_rat} rational)", args.seasons)
        t0 = time.time()
        rid = run_experiment(
            mech, "mixed", args.seasons, db,
            seed=args.seed, n_rational=n_rat,
            playoff_value=args.playoff_value, label=label,
        )
        run_ids.append(rid)
        print(f"  Completed in {time.time()-t0:.1f}s  |  run_id={rid}")
    return run_ids


def run_playoff_sweep(args, db):
    """Sensitivity: vary playoff_value, fixed mechanism."""
    mech = {
        "nba": NBALottery(),
        "bilevel": BilevelMechanism(),
        "cola": COLAMechanism(),
        "weighted_loss": WeightedLossMechanism(),
    }[args.mechanism]
    run_ids = []
    for pv in args.playoff_values:
        label = f"{mech.name}_pv{int(pv)}_{uuid.uuid4().hex[:6]}"
        _print_header(mech.name, args.agent, args.seasons, extra=f"playoff_value={pv}")
        t0 = time.time()
        rid = run_experiment(
            mech, args.agent, args.seasons, db,
            seed=args.seed, playoff_value=pv, label=label,
        )
        run_ids.append(rid)
        print(f"  Completed in {time.time()-t0:.1f}s  |  run_id={rid}")
    return run_ids


def _print_header(mech: str, agent: str, seasons: int, extra: str = "") -> None:
    extras = f"  {extra}" if extra else ""
    print(f"\n{'='*58}")
    print(f"Mechanism: {mech.upper()}  |  Agent: {agent}  |  Seasons: {seasons}{extras}")


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="NBA Tanking Simulation")
    parser.add_argument(
        "--mechanism",
        choices=["nba", "bilevel", "cola", "weighted_loss", "nba_321", "all"],
        default="all",
    )
    parser.add_argument("--agent", choices=["rational", "honest", "llm", "mixed"], default="rational")
    parser.add_argument("--seasons", type=int, default=DEFAULT_SEASONS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--db", default="tanking_sim.db")
    parser.add_argument("--output", default="results")
    parser.add_argument("--no-db", action="store_true")
    parser.add_argument("--reset-db", action="store_true", help="Delete and recreate the database before running")

    # Mixed-population stability experiment
    parser.add_argument(
        "--mixed-sweep", type=str, default="0,1,5,15,30",
        help="Comma-separated list of n_rational values for --agent mixed (default: 0,1,5,15,30)"
    )

    # Playoff value sensitivity
    parser.add_argument(
        "--playoff-value", type=float, default=DEFAULT_PLAYOFF_VALUE,
        help="Value of making playoffs (default: 50)"
    )
    parser.add_argument(
        "--playoff-values", type=str, default=None,
        help="Comma-separated playoff values for sensitivity sweep (overrides --playoff-value)"
    )

    args = parser.parse_args()
    args.mixed_sweep = [int(x) for x in args.mixed_sweep.split(",")]

    if args.reset_db and Path(args.db).exists():
        os.remove(args.db)
        print(f"Deleted {args.db}")

    db = None if args.no_db else Database(args.db)
    run_ids: list[str] = []

    if args.playoff_values:
        # Playoff value sensitivity sweep
        args.playoff_values = [float(x) for x in args.playoff_values.split(",")]
        if args.mechanism == "all":
            args.mechanism = "nba"
            print("Note: --playoff-values requires a single --mechanism; defaulting to nba")
        run_ids = run_playoff_sweep(args, db)
    elif args.agent == "mixed":
        if args.mechanism == "all":
            args.mechanism = "nba"
            print("Note: --agent mixed requires a single --mechanism; defaulting to nba")
        run_ids = run_mixed(args, db)
    else:
        run_ids = run_standard(args, db)

    if db:
        print(f"\nExporting CSVs -> ./{args.output}/")
        Path(args.output).mkdir(exist_ok=True)
        for rid in run_ids:
            paths = export_run(args.db, rid, args.output)
            print(f"  {rid}: {len(paths)} files")
        db.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
