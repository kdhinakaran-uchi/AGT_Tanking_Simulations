"""Tests for simulation.skill_update."""
import pytest

from mechanisms.base import DraftResult
from simulation.skill_update import (
    MAX_SKILL,
    MEAN_SKILL,
    MIN_SKILL,
    PICK_SCALE,
    REVERSION_RATE,
    pick_delta,
    update_skills,
)
from simulation.team import Team


def make_team(tid: int = 0, skill: float = MEAN_SKILL) -> Team:
    return Team(team_id=tid, name=f"T{tid}", true_skill=skill)


class TestPickDelta:
    def test_pick_1_gives_max_positive_boost(self):
        assert pick_delta(1, 30) == pytest.approx(PICK_SCALE)

    def test_pick_n_gives_max_negative_boost(self):
        assert pick_delta(30, 30) == pytest.approx(-PICK_SCALE)

    def test_monotone_decreasing(self):
        deltas = [pick_delta(p, 30) for p in range(1, 31)]
        for i in range(len(deltas) - 1):
            assert deltas[i] >= deltas[i + 1]

    def test_pick_1_better_than_median_better_than_last(self):
        assert pick_delta(1, 30) > pick_delta(15, 30) > pick_delta(30, 30)

    def test_formula_exact(self):
        # pick 1, n=30: 0.06 * (1 - 2*0/29) = 0.06
        assert pick_delta(1, 30) == pytest.approx(PICK_SCALE * (1 - 0))
        # pick 30, n=30: 0.06 * (1 - 2*29/29) = 0.06 * (-1) = -0.06
        assert pick_delta(30, 30) == pytest.approx(PICK_SCALE * -1)


class TestUpdateSkills:
    def test_pick_1_increases_skill_from_mean(self):
        team = make_team(0, MEAN_SKILL)
        update_skills([team], [DraftResult(team_id=0, pick=1, made_playoffs=False)], 30)
        assert team.true_skill > MEAN_SKILL

    def test_pick_n_decreases_skill_from_mean(self):
        team = make_team(0, MEAN_SKILL)
        update_skills([team], [DraftResult(team_id=0, pick=30, made_playoffs=False)], 30)
        assert team.true_skill < MEAN_SKILL

    def test_above_mean_skill_reverts_toward_mean(self):
        team = make_team(0, 2.0)
        update_skills([team], [DraftResult(team_id=0, pick=15, made_playoffs=False)], 30)
        assert team.true_skill < 2.0

    def test_below_mean_skill_reverts_toward_mean(self):
        team = make_team(0, 0.5)
        update_skills([team], [DraftResult(team_id=0, pick=15, made_playoffs=False)], 30)
        assert team.true_skill > 0.5

    def test_skill_clamped_at_min(self):
        team = make_team(0, MIN_SKILL)
        update_skills([team], [DraftResult(team_id=0, pick=30, made_playoffs=False)], 30)
        assert team.true_skill >= MIN_SKILL

    def test_skill_clamped_at_max(self):
        team = make_team(0, MAX_SKILL)
        update_skills([team], [DraftResult(team_id=0, pick=1, made_playoffs=False)], 30)
        assert team.true_skill <= MAX_SKILL

    def test_all_teams_updated(self):
        teams = [make_team(i, MEAN_SKILL) for i in range(30)]
        results = [DraftResult(team_id=i, pick=i + 1, made_playoffs=False) for i in range(30)]
        before = [t.true_skill for t in teams]
        update_skills(teams, results, 30)
        after = [t.true_skill for t in teams]
        assert before != after

    def test_correct_team_gets_correct_pick(self):
        team_a = make_team(0, MEAN_SKILL)
        team_b = make_team(1, MEAN_SKILL)
        results = [
            DraftResult(team_id=0, pick=1, made_playoffs=False),   # best pick
            DraftResult(team_id=1, pick=30, made_playoffs=False),  # worst pick
        ]
        update_skills([team_a, team_b], results, 30)
        assert team_a.true_skill > team_b.true_skill

    def test_reversion_rate_magnitude(self):
        # skill=2.0, pick=15 (delta ~0) -> new skill ≈ 2.0 - REVERSION_RATE*(2.0-1.0)
        team = make_team(0, 2.0)
        delta_15 = pick_delta(15, 30)   # near-zero but not exact
        expected = max(MIN_SKILL, min(MAX_SKILL, 2.0 - REVERSION_RATE * (2.0 - MEAN_SKILL) + delta_15))
        update_skills([team], [DraftResult(team_id=0, pick=15, made_playoffs=False)], 30)
        assert team.true_skill == pytest.approx(expected)
