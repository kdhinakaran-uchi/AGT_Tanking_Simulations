from abc import ABC, abstractmethod
from dataclasses import dataclass
import random as _random


@dataclass
class DraftResult:
    team_id: int
    pick: int           # 1 = best pick; picks > n_lottery_teams = playoff team (no lottery)
    made_playoffs: bool


class DraftMechanism(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def description(self) -> str:
        return self.name

    @abstractmethod
    def run_draft(
        self,
        teams: list,
        playoff_spots: int,
        rng: _random.Random | None = None,
    ) -> list[DraftResult]: ...

    def expected_pick_values(
        self,
        n_lottery_teams: int,
        pick_values: dict[int, float],
        n_sims: int = 5000,
        rng: _random.Random | None = None,
    ) -> dict[int, float]:
        """Returns {lottery_rank: E[pick_value]} via Monte Carlo. lottery_rank 1 = worst team."""
        _rng = rng or _random.Random(42)
        totals: dict[int, float] = {r: 0.0 for r in range(1, n_lottery_teams + 1)}
        default_val = pick_values.get(max(pick_values), 1.0)
        for _ in range(n_sims):
            sim = self._simulate_one_lottery(n_lottery_teams, _rng)
            for rank, pick in sim.items():
                totals[rank] += pick_values.get(pick, default_val)
        return {r: totals[r] / n_sims for r in totals}

    def _simulate_one_lottery(self, n_lottery_teams: int, rng: _random.Random) -> dict[int, int]:
        """Default: deterministic reverse-standings (no lottery randomness). Override per mechanism."""
        return {rank: rank for rank in range(1, n_lottery_teams + 1)}

    def rank_affects_lottery(self, games_completed: int, total_games: int) -> bool:
        """True if results of games still being played affect this team's lottery draft order."""
        return True

    def on_season_end(self, teams: list, results: list[DraftResult]) -> None:
        """Hook called after draft to update multi-season state (e.g. COLA ticket balances)."""
        pass
