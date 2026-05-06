"""Tests for all three draft mechanisms."""
import random

import pytest

from mechanisms.bilevel import BilevelMechanism
from mechanisms.cola import COLAMechanism, _TICKET_PENALTY
from mechanisms.nba_lottery import NBALottery
from simulation.team import Team

N = 30
PLAYOFF_SPOTS = 16
N_LOTTERY = N - PLAYOFF_SPOTS


def make_teams(n: int = N) -> list[Team]:
    teams = []
    for i in range(n):
        t = Team(team_id=i, name=f"T{i}", true_skill=1.0)
        t.wins = i        # team 0 = worst (0 wins), team 29 = best (29 wins)
        t.losses = n - 1 - i
        teams.append(t)
    return teams


# ── shared assertions ─────────────────────────────────────────────────────────

def assert_valid_draft(results, teams, playoff_spots):
    n = len(teams)
    n_lottery = n - playoff_spots
    assert len(results) == n
    picks = sorted(r.pick for r in results)
    assert picks == list(range(1, n + 1)), "picks must be 1..N with no gaps"
    team_ids = {r.team_id for r in results}
    assert team_ids == {t.team_id for t in teams}, "every team gets exactly one pick"
    lottery = [r for r in results if not r.made_playoffs]
    playoff = [r for r in results if r.made_playoffs]
    assert len(playoff) == playoff_spots
    assert len(lottery) == n_lottery
    assert all(r.pick <= n_lottery for r in lottery)
    assert all(r.pick > n_lottery for r in playoff)


# ── NBA Lottery ───────────────────────────────────────────────────────────────

class TestNBALottery:
    def setup_method(self):
        self.mech = NBALottery()
        self.teams = make_teams()
        self.rng = random.Random(42)

    def test_valid_draft_structure(self):
        results = self.mech.run_draft(self.teams, PLAYOFF_SPOTS, self.rng)
        assert_valid_draft(results, self.teams, PLAYOFF_SPOTS)

    def test_worst_teams_in_lottery(self):
        results = self.mech.run_draft(self.teams, PLAYOFF_SPOTS, self.rng)
        pick_map = {r.team_id: r for r in results}
        for tid in range(N_LOTTERY):        # teams 0-13 have lowest wins
            assert not pick_map[tid].made_playoffs

    def test_best_teams_make_playoffs(self):
        results = self.mech.run_draft(self.teams, PLAYOFF_SPOTS, self.rng)
        pick_map = {r.team_id: r for r in results}
        for tid in range(N_LOTTERY, N):     # teams 14-29 have highest wins
            assert pick_map[tid].made_playoffs

    def test_pick_1_always_goes_to_lottery_team(self):
        for seed in range(20):
            results = self.mech.run_draft(self.teams, PLAYOFF_SPOTS, random.Random(seed))
            pick1 = next(r for r in results if r.pick == 1)
            assert not pick1.made_playoffs

    def test_rank_affects_lottery_is_always_true(self):
        assert self.mech.rank_affects_lottery(0, 82) is True
        assert self.mech.rank_affects_lottery(81, 82) is True


# ── Bilevel ───────────────────────────────────────────────────────────────────

class TestBilevel:
    def setup_method(self):
        self.mech = BilevelMechanism()
        self.teams = make_teams()
        self.rng = random.Random(42)

    def test_valid_draft_structure(self):
        results = self.mech.run_draft(self.teams, PLAYOFF_SPOTS, self.rng)
        assert_valid_draft(results, self.teams, PLAYOFF_SPOTS)

    def test_default_lock_game(self):
        assert self.mech.lock_game == int(6 / 7 * 82)  # 70

    def test_rank_affects_lottery_before_lock(self):
        assert self.mech.rank_affects_lottery(0, 82) is True
        assert self.mech.rank_affects_lottery(self.mech.lock_game - 1, 82) is True

    def test_rank_affects_lottery_at_and_after_lock(self):
        assert self.mech.rank_affects_lottery(self.mech.lock_game, 82) is False
        assert self.mech.rank_affects_lottery(81, 82) is False

    def test_playoff_determined_by_final_record(self):
        teams = make_teams()
        self.mech.record_lock_snapshot(teams)   # lock now (teams[N_LOTTERY-1] is on the bubble)
        # Give a clearly-lottery team a massive final-record boost → should make playoffs
        teams[0].wins = 82      # was worst, now best final record
        results = self.mech.run_draft(teams, PLAYOFF_SPOTS, self.rng)
        pick_map = {r.team_id: r for r in results}
        assert pick_map[0].made_playoffs, "Final record determines playoff qualification"

    def test_lock_state_reset_after_draft(self):
        teams = make_teams()
        self.mech.record_lock_snapshot(teams)
        self.mech.run_draft(teams, PLAYOFF_SPOTS, self.rng)
        assert self.mech._locked_wins == {}, "_locked_wins should be cleared after draft"

    def test_custom_lock_fraction(self):
        mech = BilevelMechanism(lock_fraction=0.5, games_per_team=82)
        assert mech.lock_game == 41
        assert mech.rank_affects_lottery(40, 82) is True
        assert mech.rank_affects_lottery(41, 82) is False


# ── COLA ──────────────────────────────────────────────────────────────────────

class TestCOLA:
    def setup_method(self):
        self.mech = COLAMechanism()
        self.teams = make_teams()
        self.rng = random.Random(42)

    def test_valid_draft_structure(self):
        results = self.mech.run_draft(self.teams, PLAYOFF_SPOTS, self.rng)
        assert_valid_draft(results, self.teams, PLAYOFF_SPOTS)

    def test_nonplayoff_teams_earn_one_ticket(self):
        pre = {t.team_id: t.lottery_tickets for t in self.teams}
        results = self.mech.run_draft(self.teams, PLAYOFF_SPOTS, self.rng)
        nonplayoff = {r.team_id for r in results if not r.made_playoffs}
        for t in self.teams:
            if t.team_id in nonplayoff:
                assert t.lottery_tickets == pre[t.team_id] + 1

    def test_playoffs_teams_do_not_earn_ticket(self):
        pre = {t.team_id: t.lottery_tickets for t in self.teams}
        results = self.mech.run_draft(self.teams, PLAYOFF_SPOTS, self.rng)
        playoff_ids = {r.team_id for r in results if r.made_playoffs}
        for t in self.teams:
            if t.team_id in playoff_ids:
                assert t.lottery_tickets == pre[t.team_id]

    def test_ticket_penalty_applied_for_top_picks(self):
        results = self.mech.run_draft(self.teams, PLAYOFF_SPOTS, self.rng)
        for t in self.teams:
            t.lottery_tickets = 10
        self.mech.on_season_end(self.teams, results)
        pick_map = {r.team_id: r.pick for r in results}
        for team in self.teams:
            penalty = _TICKET_PENALTY.get(pick_map[team.team_id], 0)
            assert team.lottery_tickets == 10 - penalty

    def test_tickets_never_go_below_zero(self):
        results = self.mech.run_draft(self.teams, PLAYOFF_SPOTS, self.rng)
        for t in self.teams:
            t.lottery_tickets = 0
        self.mech.on_season_end(self.teams, results)
        assert all(t.lottery_tickets >= 0 for t in self.teams)

    def test_expected_pick_values_are_uniform(self):
        from agents.rational import PICK_VALUES
        ev = self.mech.expected_pick_values(N_LOTTERY, PICK_VALUES)
        assert len(ev) == N_LOTTERY
        values = list(ev.values())
        assert max(values) - min(values) < 1e-10

    def test_team_with_most_tickets_gets_best_pick(self):
        teams = make_teams(6)
        teams[0].lottery_tickets = 20   # most tickets → should get pick 1 (among non-playoff)
        teams[0].wins = 0
        # Ensure team 0 misses playoffs
        results = self.mech.run_draft(teams, playoff_spots=3, rng=random.Random(0))
        pick_map = {r.team_id: r.pick for r in results}
        if not next(r for r in results if r.team_id == 0).made_playoffs:
            assert pick_map[0] == 1
