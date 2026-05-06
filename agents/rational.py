from agents.base import Agent, DecisionContext
from simulation.game import win_probability

PLAYOFF_VALUE = 50.0

# Declining pick values calibrated to reflect real NBA draft pick trade value.
PICK_VALUES: dict[int, float] = {
    1: 100, 2: 65, 3: 45, 4: 30, 5: 22, 6: 17, 7: 13, 8: 10,
    9: 8, 10: 7, 11: 6, 12: 5, 13: 4, 14: 3,
}
DEFAULT_PICK_VALUE = 2.0

_EFFORT_LEVELS = [0.0, 0.25, 0.5, 0.75, 1.0]


class RationalAgent(Agent):
    """Expected-utility maximizing agent.

    At each decision checkpoint, evaluates EU for a grid of effort levels and
    picks the best one. EU is computed analytically: estimate final win total
    under each effort level -> project final rank -> look up expected pick value
    from a pre-computed Monte Carlo table for the active mechanism.
    """

    def __init__(
        self,
        team,
        ev_table: dict[int, float] | None = None,
        playoff_value: float = PLAYOFF_VALUE,
    ):
        super().__init__(team)
        self._ev_table: dict[int, float] = ev_table or {}
        self._playoff_value = playoff_value

    def set_ev_table(self, table: dict[int, float]) -> None:
        self._ev_table = table

    def decide(self, ctx: DecisionContext) -> tuple[float, str]:
        if not ctx.mechanism.rank_affects_lottery(ctx.games_completed, ctx.total_games):
            return 1.0, "Lottery locked; maximizing wins"

        best_effort, best_eu = 1.0, float("-inf")
        for effort in _EFFORT_LEVELS:
            eu = self._eu(effort, ctx)
            if eu > best_eu:
                best_eu, best_effort = eu, effort
            elif eu == best_eu and effort > best_effort:
                best_effort = effort  # prefer higher effort when indifferent

        action = "tank" if best_effort < 0.5 else "try"
        return best_effort, f"{action} (e={best_effort:.2f}, EU={best_eu:.1f})"

    def _eu(self, effort: float, ctx: DecisionContext) -> float:
        n = len(ctx.standings)
        n_lottery = n - ctx.playoff_spots
        avg_skill = sum(t.true_skill for t in ctx.standings) / n

        p_win = win_probability(ctx.team.true_skill, effort, avg_skill, 1.0)
        exp_final_wins = ctx.team.wins + ctx.games_remaining * p_win

        # Project all other teams assuming they play at full effort
        teams_ahead = sum(
            1
            for t in ctx.standings
            if t.team_id != ctx.team.team_id
            and t.wins + (ctx.total_games - t.games_played)
                * win_probability(t.true_skill, 1.0, avg_skill, 1.0)
            > exp_final_wins
        )
        exp_rank = teams_ahead + 1  # 1 = best team

        if exp_rank <= ctx.playoff_spots:
            return self._playoff_value

        # EV table rank 1 = worst overall team = best lottery odds.
        # exp_rank 1 = best team, so we invert: lottery_rank = n_teams + 1 - exp_rank.
        n_teams = len(ctx.standings)
        lottery_rank = max(1, min(n_teams + 1 - exp_rank, n_lottery))
        if self._ev_table:
            return self._ev_table.get(lottery_rank, DEFAULT_PICK_VALUE)
        return PICK_VALUES.get(lottery_rank, DEFAULT_PICK_VALUE)
