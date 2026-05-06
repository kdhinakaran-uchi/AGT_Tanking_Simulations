"""Tests for HonestAgent and shared Agent contract."""
import pytest

from agents.base import DecisionContext
from agents.honest import HonestAgent
from mechanisms.nba_lottery import NBALottery
from simulation.team import Team


def _ctx(team: Team) -> DecisionContext:
    return DecisionContext(
        season=0, checkpoint=0, games_completed=0, games_remaining=82,
        total_games=82, team=team,
        standings=[team],
        playoff_spots=1,
        mechanism=NBALottery(),
        checkpoint_interval=10,
    )


class TestHonestAgent:
    def test_always_returns_full_effort(self):
        team = Team(team_id=0, name="T0", true_skill=1.0)
        agent = HonestAgent(team)
        for _ in range(10):
            effort, _ = agent.decide(_ctx(team))
            assert effort == 1.0

    def test_reasoning_is_nonempty_string(self):
        team = Team(team_id=0, name="T0", true_skill=1.0)
        agent = HonestAgent(team)
        _, reasoning = agent.decide(_ctx(team))
        assert isinstance(reasoning, str) and len(reasoning) > 0

    def test_ignores_standings_context(self):
        """Effort is always 1.0 regardless of win/loss state."""
        team = Team(team_id=0, name="T0", true_skill=1.0)
        team.wins = 0
        team.losses = 81    # terrible record
        agent = HonestAgent(team)
        effort, _ = agent.decide(_ctx(team))
        assert effort == 1.0
