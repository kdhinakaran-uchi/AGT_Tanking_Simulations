"""Integration tests: run a full mini-season and verify structural invariants."""
import random

import pytest

from agents.honest import HonestAgent
from agents.rational import RationalAgent
from mechanisms.bilevel import BilevelMechanism
from mechanisms.cola import COLAMechanism
from mechanisms.nba_lottery import NBALottery
from simulation.season import Season
from simulation.team import Team

# Small world so tests run in < 1s
N = 10
PLAYOFF_SPOTS = 4
GAMES = 20
CHECKPOINT = 5


def make_teams(n: int = N) -> list[Team]:
    rng = random.Random(99)
    return [
        Team(team_id=i, name=f"T{i}", true_skill=0.5 + rng.random())
        for i in range(n)
    ]


def run_season(mech, agent_type: str = "honest") -> tuple:
    teams = make_teams()
    if agent_type == "honest":
        agents = {t.team_id: HonestAgent(t) for t in teams}
    else:
        n_lottery = N - PLAYOFF_SPOTS
        ev = mech.expected_pick_values(
            n_lottery, {i: float(100 - i * 5) for i in range(1, n_lottery + 1)}
        )
        agents = {}
        for t in teams:
            a = RationalAgent(t, playoff_value=50.0)
            a.set_ev_table(ev)
            agents[t.team_id] = a

    season = Season(
        teams=teams, agents=agents, mechanism=mech,
        season=0, playoff_spots=PLAYOFF_SPOTS, games_per_team=GAMES,
        checkpoint_interval=CHECKPOINT, run_id="test",
        rng=random.Random(42),
    )
    return season.run(), teams


# ── parametrize over all mechanisms ──────────────────────────────────────────

MECHS = [NBALottery, BilevelMechanism, COLAMechanism]


@pytest.mark.parametrize("mech_cls", MECHS)
def test_all_teams_get_exactly_one_pick(mech_cls):
    mech = mech_cls()
    result, teams = run_season(mech)
    assert {r.team_id for r in result.draft_results} == {t.team_id for t in teams}


@pytest.mark.parametrize("mech_cls", MECHS)
def test_picks_are_1_to_n_with_no_gaps(mech_cls):
    mech = mech_cls()
    result, _ = run_season(mech)
    picks = sorted(r.pick for r in result.draft_results)
    assert picks == list(range(1, N + 1))


@pytest.mark.parametrize("mech_cls", MECHS)
def test_correct_playoff_count(mech_cls):
    mech = mech_cls()
    result, _ = run_season(mech)
    n_playoff = sum(1 for r in result.draft_results if r.made_playoffs)
    assert n_playoff == PLAYOFF_SPOTS


@pytest.mark.parametrize("mech_cls", MECHS)
def test_all_teams_play_correct_number_of_games(mech_cls):
    mech = mech_cls()
    _, teams = run_season(mech)
    for t in teams:
        assert t.wins + t.losses == GAMES


@pytest.mark.parametrize("mech_cls", MECHS)
def test_tanking_rate_in_valid_range(mech_cls):
    mech = mech_cls()
    result, _ = run_season(mech)
    assert 0.0 <= result.tanking_rate <= 1.0


def test_honest_agents_zero_tanking():
    result, _ = run_season(NBALottery(), agent_type="honest")
    assert result.tanking_rate == 0.0


def test_rational_agents_nba_show_some_tanking():
    """Sanity check: rational agents under NBA lottery should tank at least sometimes."""
    mech = NBALottery()
    # Run several seeds; at least one should produce tanking
    for seed in range(5):
        teams = make_teams()
        n_lottery = N - PLAYOFF_SPOTS
        ev = mech.expected_pick_values(n_lottery, {i: float(100 - i * 5) for i in range(1, n_lottery + 1)})
        agents = {}
        for t in teams:
            a = RationalAgent(t, playoff_value=5.0)  # low playoff value -> more tanking
            a.set_ev_table(ev)
            agents[t.team_id] = a
        season = Season(
            teams=teams, agents=agents, mechanism=mech,
            season=0, playoff_spots=PLAYOFF_SPOTS, games_per_team=GAMES,
            checkpoint_interval=CHECKPOINT, run_id="test",
            rng=random.Random(seed),
        )
        result = season.run()
        if result.tanking_rate > 0:
            return   # at least one seed produced tanking → pass
    pytest.fail("Expected at least one seed to produce tanking with NBA lottery and low playoff value")
