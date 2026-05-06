"""Tests for simulation.game: win_probability and simulate_game."""
import random

import pytest

from simulation.game import EFFORT_FLOOR, simulate_game, win_probability
from simulation.team import Team


def make_team(tid: int = 0, skill: float = 1.0) -> Team:
    return Team(team_id=tid, name=f"T{tid}", true_skill=skill)


class TestWinProbability:
    def test_equal_skill_equal_effort_returns_half(self):
        assert win_probability(1.0, 1.0, 1.0, 1.0) == pytest.approx(0.5)

    def test_symmetry(self):
        p = win_probability(1.5, 0.8, 1.0, 0.6)
        q = win_probability(1.0, 0.6, 1.5, 0.8)
        assert p + q == pytest.approx(1.0)

    def test_higher_skill_wins_more(self):
        assert win_probability(2.0, 1.0, 1.0, 1.0) > 0.5

    def test_higher_effort_wins_more(self):
        assert win_probability(1.0, 1.0, 1.0, 0.0) > 0.5

    def test_effort_zero_uses_floor(self):
        # effort=0 -> effective = skill * EFFORT_FLOOR
        p = win_probability(1.0, 0.0, 1.0, 1.0)
        expected = EFFORT_FLOOR / (EFFORT_FLOOR + 1.0)
        assert p == pytest.approx(expected)

    def test_both_effort_zero_is_skill_ratio(self):
        # Both at floor: p = (s_a * floor) / (s_a * floor + s_b * floor) = s_a / (s_a + s_b)
        p = win_probability(2.0, 0.0, 1.0, 0.0)
        assert p == pytest.approx(2.0 / 3.0)

    def test_never_reaches_zero(self):
        assert win_probability(0.001, 0.0, 100.0, 1.0) > 0

    def test_never_reaches_one(self):
        assert win_probability(100.0, 1.0, 0.001, 0.0) < 1.0


class TestSimulateGame:
    def test_returns_winner_and_loser(self):
        a = make_team(0, 1.0)
        b = make_team(1, 1.0)
        winner, loser = simulate_game(a, 1.0, b, 1.0, random.Random(0))
        assert winner in (a, b)
        assert loser in (a, b)
        assert winner is not loser

    def test_updates_wins_and_losses(self):
        a = make_team(0, 1.0)
        b = make_team(1, 1.0)
        winner, loser = simulate_game(a, 1.0, b, 1.0, random.Random(0))
        assert winner.wins == 1 and winner.losses == 0
        assert loser.wins == 0 and loser.losses == 1

    def test_each_team_plays_exactly_one_game(self):
        a = make_team(0, 1.0)
        b = make_team(1, 1.0)
        simulate_game(a, 1.0, b, 1.0, random.Random(7))
        assert a.wins + a.losses == 1
        assert b.wins + b.losses == 1

    def test_dominant_team_wins_most_often(self):
        wins = sum(
            1
            for seed in range(300)
            if simulate_game(make_team(0, 3.0), 1.0, make_team(1, 1.0), 1.0, random.Random(seed))[0].team_id == 0
        )
        # P(A wins) ≈ 3/(3+1) = 75%; expect >200/300
        assert wins > 200
