import random as _random
from mechanisms.base import DraftMechanism, DraftResult
from simulation.team import Team

# 2019 NBA reform: top 3 seeds share equal 14% odds; then weighted down.
# 1001 total combinations; 1 goes unassigned — scaled to 1000 for simplicity.
_LOTTERY_WEIGHTS = [140, 140, 140, 125, 105, 90, 75, 60, 45, 30, 20, 15, 10, 5]


class NBALottery(DraftMechanism):
    """Current NBA weighted draft lottery (2019 reform).

    14 non-playoff teams enter. Lottery determines picks 1-4; picks 5-14
    assigned in reverse standings order. Worse season record = better odds
    throughout the full season, creating a persistent tanking incentive.
    """

    @property
    def name(self) -> str:
        return "nba_lottery"

    @property
    def description(self) -> str:
        return (
            "NBA 2019 draft lottery: the 14 non-playoff teams enter a weighted lottery. "
            "The 3 worst teams each have a 14% chance at pick #1; better lottery teams "
            "have progressively lower odds. The lottery determines picks 1-4; picks 5-14 "
            "go in reverse standings order. A worse end-of-season record always improves "
            "lottery odds, so there is an incentive to lose games all season long."
        )

    def run_draft(
        self,
        teams: list[Team],
        playoff_spots: int,
        rng: _random.Random | None = None,
    ) -> list[DraftResult]:
        _rng = rng or _random.Random()
        n = len(teams)
        sorted_asc = sorted(teams, key=lambda t: (t.wins, t.team_id))  # worst first
        lottery_teams = sorted_asc[: n - playoff_spots]
        playoff_teams = sorted_asc[n - playoff_spots :]

        n_lottery = len(lottery_teams)
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
        for idx in remaining_idx:  # still in worst-first order
            picks[lottery_teams[idx].team_id] = next_pick
            next_pick += 1

        results = [
            DraftResult(team_id=t.team_id, pick=picks[t.team_id], made_playoffs=False)
            for t in lottery_teams
        ]
        for i, t in enumerate(sorted(playoff_teams, key=lambda t: t.wins)):
            results.append(DraftResult(team_id=t.team_id, pick=n_lottery + 1 + i, made_playoffs=True))

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
