"""Tests for the rational agent, including regression tests for prior bugs."""
import pytest

from agents.base import DecisionContext
from agents.rational import PICK_VALUES, RationalAgent
from mechanisms.bilevel import BilevelMechanism
from mechanisms.cola import COLAMechanism
from mechanisms.nba_lottery import NBALottery
from simulation.team import Team


# ── helpers ───────────────────────────────────────────────────────────────────

def make_team(tid: int = 0, skill: float = 1.0, wins: int = 0) -> Team:
    t = Team(team_id=tid, name=f"T{tid}", true_skill=skill)
    t.wins = wins
    return t


def make_standings(n: int = 30, my_tid: int = 0, my_wins: int = 0) -> list[Team]:
    teams = [make_team(i, skill=1.0, wins=i * 2) for i in range(n)]
    teams[my_tid].wins = my_wins
    return sorted(teams, key=lambda t: t.wins, reverse=True)


def make_ctx(
    team: Team,
    standings: list[Team],
    *,
    games_completed: int = 0,
    games_per_team: int = 82,
    playoff_spots: int = 16,
    mechanism=None,
    checkpoint_interval: int = 10,
) -> DecisionContext:
    return DecisionContext(
        season=0,
        checkpoint=0,
        games_completed=games_completed,
        games_remaining=games_per_team - games_completed,
        total_games=games_per_team,
        team=team,
        standings=standings,
        playoff_spots=playoff_spots,
        mechanism=mechanism or NBALottery(),
        checkpoint_interval=checkpoint_interval,
    )


# ── tests ─────────────────────────────────────────────────────────────────────

class TestRationalAgent:
    def test_full_effort_when_lottery_locked(self):
        """After bilevel lock game, rank_affects_lottery=False -> agent must try."""
        mech = BilevelMechanism()
        team = make_team(0, skill=0.5, wins=0)
        standings = make_standings(my_tid=0, my_wins=0)
        ctx = make_ctx(team, standings, games_completed=mech.lock_game + 1, mechanism=mech)
        agent = RationalAgent(team, playoff_value=5.0)
        agent.set_ev_table({r: 30.0 for r in range(1, 15)})
        effort, _ = agent.decide(ctx)
        assert effort == 1.0

    def test_prefers_higher_effort_on_eu_tie(self):
        """Regression: COLA's flat EV table should not cause effort=0.0 (old tie-break bug)."""
        mech = COLAMechanism()
        team = make_team(0, skill=1.0, wins=5)
        standings = make_standings(my_tid=0, my_wins=5)
        ctx = make_ctx(team, standings, games_completed=0, mechanism=mech)
        flat_ev = mech.expected_pick_values(14, PICK_VALUES)
        agent = RationalAgent(team, playoff_value=5.0)
        agent.set_ev_table(flat_ev)
        effort, _ = agent.decide(ctx)
        assert effort >= 0.5, "Flat EV must not make agent choose to tank"

    def test_tanking_improves_lottery_rank_when_it_matters(self):
        """Regression: lottery_rank direction — worse final rank should give better lottery odds.

        Setup (5 teams, 2 playoff spots, 3 lottery slots, 7 games):
          team0: wins=3, losses=0, 4 remaining  (subject)
          team1: wins=3, losses=1, 3 remaining  (projects to 4.5 wins)
          team2: wins=4, losses=1, 2 remaining  (projects to 5.0 wins)
          team3: wins=6, losses=1, done         (playoff)
          team4: wins=7, losses=0, done         (playoff)

        At effort < 0.5, team1 (proj 4.5) ends up ahead of team0 -> team0 gets exp_rank=5
        -> lottery_rank=1 -> EV=100.  At effort >= 0.5 team0 ties/beats team1
        -> exp_rank=4 -> lottery_rank=2 -> EV=20.  Best effort from {0, .25} is 0.25.
        """
        n, playoff_spots = 5, 2
        gpt = 7
        teams = [
            Team(team_id=0, name="T0", true_skill=1.0),  # 3W 0L → 4 remaining
            Team(team_id=1, name="T1", true_skill=1.0),  # 3W 1L → 3 remaining
            Team(team_id=2, name="T2", true_skill=1.0),  # 4W 1L → 2 remaining
            Team(team_id=3, name="T3", true_skill=1.0),  # 6W 1L → done
            Team(team_id=4, name="T4", true_skill=1.0),  # 7W 0L → done
        ]
        wins_losses = [(3, 0), (3, 1), (4, 1), (6, 1), (7, 0)]
        for t, (w, l) in zip(teams, wins_losses):
            t.wins, t.losses = w, l

        team = teams[0]
        standings = sorted(teams, key=lambda t: t.wins, reverse=True)
        ctx = make_ctx(team, standings, games_completed=3,
                       games_per_team=gpt, playoff_spots=playoff_spots,
                       mechanism=NBALottery(), checkpoint_interval=1)

        ev_table = {1: 100.0, 2: 20.0, 3: 5.0}
        agent = RationalAgent(team, playoff_value=5.0)
        agent.set_ev_table(ev_table)
        effort, _ = agent.decide(ctx)
        assert effort < 0.5, (
            f"Agent should choose effort<0.5 to stay below team1's proj 4.5 wins "
            f"(lottery_rank=1, EV=100) rather than tie/beat team1 (lottery_rank=2, EV=20). "
            f"Got effort={effort}"
        )

    def test_high_playoff_value_discourages_tanking_near_bubble(self):
        """Team near the playoff bubble with high playoff_value should try."""
        mech = NBALottery()
        n = 30
        playoff_spots = 16
        # Team is right on the bubble: rank ~17
        team = make_team(0, skill=1.5, wins=30)
        standings = [make_team(i, skill=1.0, wins=40 - i) for i in range(1, n)] + [team]
        standings = sorted(standings, key=lambda t: t.wins, reverse=True)
        ctx = make_ctx(team, standings, games_completed=70,
                       playoff_spots=playoff_spots, mechanism=mech)
        ev_table = {r: 5.0 for r in range(1, n - playoff_spots + 1)}
        agent = RationalAgent(team, playoff_value=200.0)
        agent.set_ev_table(ev_table)
        effort, _ = agent.decide(ctx)
        assert effort >= 0.75, "High playoff value should push bubble team to try"

    def test_low_playoff_value_encourages_tanking_when_rank_changes(self):
        """Same setup as the lottery-rank direction test — also confirms low playoff_value
        doesn't override the tanking decision when lottery EV is strongly superior."""
        n, playoff_spots = 5, 2
        gpt = 7
        teams = [
            Team(team_id=0, name="T0", true_skill=1.0),
            Team(team_id=1, name="T1", true_skill=1.0),
            Team(team_id=2, name="T2", true_skill=1.0),
            Team(team_id=3, name="T3", true_skill=1.0),
            Team(team_id=4, name="T4", true_skill=1.0),
        ]
        for t, (w, l) in zip(teams, [(3, 0), (3, 1), (4, 1), (6, 1), (7, 0)]):
            t.wins, t.losses = w, l

        team = teams[0]
        standings = sorted(teams, key=lambda t: t.wins, reverse=True)
        ctx = make_ctx(team, standings, games_completed=3,
                       games_per_team=gpt, playoff_spots=playoff_spots,
                       mechanism=NBALottery(), checkpoint_interval=1)

        # Very high prize for pick 1, very low playoff value
        ev_table = {1: 100.0, 2: 5.0, 3: 2.0}
        agent = RationalAgent(team, playoff_value=1.0)
        agent.set_ev_table(ev_table)
        effort, _ = agent.decide(ctx)
        assert effort < 0.5, f"Low playoff value + pick-1 premium should induce tanking, got {effort}"

    def test_decide_returns_valid_effort_range(self):
        team = make_team(0, skill=1.0, wins=10)
        standings = make_standings(my_tid=0, my_wins=10)
        ctx = make_ctx(team, standings)
        agent = RationalAgent(team)
        effort, reasoning = agent.decide(ctx)
        assert 0.0 <= effort <= 1.0
        assert isinstance(reasoning, str)

    def test_ev_table_fallback_when_empty(self):
        """Agent still decides correctly using module-level PICK_VALUES when ev_table not set."""
        team = make_team(0, skill=1.0, wins=0)
        standings = make_standings(my_tid=0, my_wins=0)
        ctx = make_ctx(team, standings)
        agent = RationalAgent(team, playoff_value=5.0)
        # No ev_table set
        effort, _ = agent.decide(ctx)
        assert 0.0 <= effort <= 1.0
