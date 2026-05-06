import random as _random
from mechanisms.base import DraftMechanism, DraftResult
from simulation.team import Team

_LOTTERY_WEIGHTS = [140, 140, 140, 125, 105, 90, 75, 60, 45, 30, 20, 15, 10, 5]


class BilevelMechanism(DraftMechanism):
    """Kazachkov & Vardi (2020) bilevel ranking mechanism.

    Lottery odds are determined by each team's standing at a mid-season
    breakpoint (default: game 68, roughly 5/6 through 82 games) rather than
    the end-of-season record. After the breakpoint, standings are locked and
    tanking provides no lottery benefit.
    """

    def __init__(self, lock_fraction: float = 6 / 7, games_per_team: int = 82):
        self.lock_game = int(lock_fraction * games_per_team)
        self._locked_wins: dict[int, int] = {}  # team_id -> wins at lock point

    @property
    def name(self) -> str:
        return "bilevel"

    @property
    def description(self) -> str:
        pct = int(self.lock_game / 82 * 100)
        return (
            f"Bilevel ranking: lottery odds are frozen at game {self.lock_game} "
            f"(~{pct}% through the season). After game {self.lock_game}, a team's "
            f"draft position is already set, so tanking is pointless for the remainder "
            f"of the season. Before the lock, incentives are similar to the current NBA lottery."
        )

    def record_lock_snapshot(self, teams: list[Team]) -> None:
        """Called by the season at game lock_game to snapshot current win totals."""
        self._locked_wins = {t.team_id: t.wins for t in teams}

    def rank_affects_lottery(self, games_completed: int, total_games: int) -> bool:
        return games_completed < self.lock_game

    def run_draft(
        self,
        teams: list[Team],
        playoff_spots: int,
        rng: _random.Random | None = None,
    ) -> list[DraftResult]:
        _rng = rng or _random.Random()
        n = len(teams)
        n_lottery = n - playoff_spots

        # Playoff eligibility: determined by FINAL record (same as always)
        sorted_final = sorted(teams, key=lambda t: (t.wins, t.team_id))  # worst final record first
        lottery_teams_pool = sorted_final[:n_lottery]
        playoff_teams_final = sorted_final[n_lottery:]

        # Lottery ORDER within the pool: determined by record at the lock point
        def lock_key(t: Team) -> tuple:
            return (self._locked_wins.get(t.team_id, t.wins), t.team_id)

        lottery_teams = sorted(lottery_teams_pool, key=lock_key)  # worst lock-record first

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
        for i, t in enumerate(sorted(playoff_teams_final, key=lambda t: t.wins)):
            results.append(DraftResult(team_id=t.team_id, pick=n_lottery + 1 + i, made_playoffs=True))

        self._locked_wins = {}  # reset for next season
        return results

    def _simulate_one_lottery(self, n_lottery_teams: int, rng: _random.Random) -> dict[int, int]:
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
