"""Reverse-game-order weighted-loss mechanism.

Generalizes bilevel: each loss contributes w(game_idx) to lottery position.
For decreasing w(g), late-season tanking is worth less than early-season
tanking — continuous suppression rather than a hard cutoff at the lock game.

Bilevel is the limit case w(g) = 1{g < lock_game}.
NBA-style flat weighting is the limit case w(g) = 1.
"""

import random as _random
from collections import defaultdict
from typing import Callable

from mechanisms.base import DraftMechanism, DraftResult
from simulation.team import Team

_LOTTERY_WEIGHTS = [140, 140, 140, 125, 105, 90, 75, 60, 45, 30, 20, 15, 10, 5]


# ── weight function factories ─────────────────────────────────────────────────

def exponential_decay(half_life: float = 20.0) -> Callable[[int, int], float]:
    """w(g) = 0.5 ** (g / half_life). Default half-life = 20 games."""
    return lambda g, T: 0.5 ** (g / half_life)


def linear_decay() -> Callable[[int, int], float]:
    """w(g) = (T - g) / T. Game 0 worth 1.0, last game worth ~0."""
    return lambda g, T: max(0.0, (T - g) / T)


def step_decay(lock_game: int = 70) -> Callable[[int, int], float]:
    """w(g) = 1 if g < lock_game else 0. Recovers bilevel exactly."""
    return lambda g, T: 1.0 if g < lock_game else 0.0


def power_decay(alpha: float = 1.5) -> Callable[[int, int], float]:
    """w(g) = (1 - g/T) ** alpha. alpha=1 -> linear; alpha>1 -> steeper falloff."""
    return lambda g, T: max(0.0, (1.0 - g / T)) ** alpha


# ── mechanism ─────────────────────────────────────────────────────────────────

class WeightedLossMechanism(DraftMechanism):
    """Lottery odds determined by weighted cumulative losses.

    Playoff eligibility (top 16) is still determined by final W-L record —
    same as bilevel. Only the LOTTERY ORDER among non-playoff teams uses
    the weighted-loss score.

    The weight function w(game_idx, total_games) decreases over the season,
    so late-season losses contribute less to lottery position than early ones.
    This discourages end-of-season tanking without requiring a hard lock point.

    Special cases:
      step_decay(70)  → identical to BilevelMechanism
      constant w=1    → identical to NBALottery (flat weighting)
    """

    def __init__(
        self,
        weight_fn: Callable[[int, int], float] | None = None,
        weight_fn_name: str = "exp_hl20",
    ):
        self.weight_fn = weight_fn or exponential_decay(20.0)
        self.weight_fn_name = weight_fn_name
        self._weighted_losses: dict[int, float] = defaultdict(float)

    @property
    def name(self) -> str:
        return f"weighted_loss_{self.weight_fn_name}"

    @property
    def description(self) -> str:
        return (
            "Weighted-loss lottery: each loss contributes w(game_idx) to the team's "
            "lottery position score. Higher score = better odds. Weight function "
            f"({self.weight_fn_name}) decreases over the season, so late-season losses "
            "are worth less than early-season losses — tanking incentives decay "
            "smoothly across the season instead of vanishing at a hard lock point."
        )

    def record_game_loss(self, game_idx: int, loser_team_id: int, total_games: int) -> None:
        """Called by Season after every game to accumulate weighted losses."""
        self._weighted_losses[loser_team_id] += self.weight_fn(game_idx, total_games)

    def rank_affects_lottery(self, games_completed: int, total_games: int) -> bool:
        return self.weight_fn(games_completed, total_games) > 1e-6

    def run_draft(
        self,
        teams: list[Team],
        playoff_spots: int,
        rng: _random.Random | None = None,
    ) -> list[DraftResult]:
        _rng = rng or _random.Random()
        n = len(teams)
        n_lottery = n - playoff_spots

        # Playoff eligibility: final-record top 16, same as bilevel
        sorted_by_wins = sorted(teams, key=lambda t: (t.wins, t.team_id))
        lottery_pool = sorted_by_wins[:n_lottery]
        playoff_teams = sorted_by_wins[n_lottery:]

        # Lottery ORDER: highest weighted-loss score = worst record = best odds (rank 1)
        lottery_teams = sorted(
            lottery_pool,
            key=lambda t: (-self._weighted_losses.get(t.team_id, 0.0), t.team_id),
        )

        # Standard weighted lottery for picks 1-4 (same odds structure as NBA/bilevel)
        weights = _LOTTERY_WEIGHTS[:n_lottery]
        n_lottery_picks = min(4, n_lottery)
        remaining_idx = list(range(n_lottery))
        remaining_w = list(weights)
        picks: dict[int, int] = {}

        for pick_num in range(1, n_lottery_picks + 1):
            pos = _rng.choices(range(len(remaining_idx)), weights=remaining_w)[0]
            picks[lottery_teams[remaining_idx[pos]].team_id] = pick_num
            remaining_idx.pop(pos)
            remaining_w.pop(pos)

        next_pick = n_lottery_picks + 1
        for idx in remaining_idx:
            picks[lottery_teams[idx].team_id] = next_pick
            next_pick += 1

        results = [
            DraftResult(team_id=t.team_id, pick=picks[t.team_id], made_playoffs=False)
            for t in lottery_teams
        ]
        for i, t in enumerate(sorted(playoff_teams, key=lambda t: t.wins)):
            results.append(DraftResult(team_id=t.team_id, pick=n_lottery + 1 + i, made_playoffs=True))

        self._weighted_losses = defaultdict(float)  # reset for next season
        return results

    def _simulate_one_lottery(self, n_lottery_teams: int, rng: _random.Random) -> dict[int, int]:
        """Same odds structure as NBA lottery — rank 1 = most weighted losses = best odds."""
        weights = _LOTTERY_WEIGHTS[:n_lottery_teams]
        remaining_ranks = list(range(1, n_lottery_teams + 1))
        remaining_w = list(weights)
        picks: dict[int, int] = {}

        for pick_num in range(1, min(5, n_lottery_teams + 1)):
            pos = rng.choices(range(len(remaining_ranks)), weights=remaining_w)[0]
            picks[remaining_ranks[pos]] = pick_num
            remaining_ranks.pop(pos)
            remaining_w.pop(pos)

        next_pick = min(5, n_lottery_teams + 1)
        for rank in remaining_ranks:
            picks[rank] = next_pick
            next_pick += 1

        return picks
