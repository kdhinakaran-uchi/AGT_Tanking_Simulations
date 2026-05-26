import random as _random
from mechanisms.base import DraftMechanism, DraftResult
from simulation.team import Team

TICKETS_PER_MISS = 1  # tickets earned per season a team misses playoffs

# High lottery picks cost tickets (discourages gaming the system over multiple seasons).
_TICKET_PENALTY = {1: 5, 2: 4, 3: 3, 4: 2}


class COLAMechanism(DraftMechanism):
    """Carry-Over Lottery Allocation (Highley, Duncan & Volkov 2026, arXiv:2602.02487).

    Every non-playoff team earns one ticket per season. Tickets accumulate
    across seasons and are reduced when a team wins a high draft pick. Draft
    order is purely by ticket count (most tickets = pick #1). Because this
    season's record does NOT determine lottery odds, there is no within-season
    incentive to tank — only the playoff/miss-playoffs boundary matters.
    """

    @property
    def name(self) -> str:
        return "cola"

    @property
    def description(self) -> str:
        return (
            "COLA (Carry-Over Lottery Allocation): every non-playoff team earns 1 ticket "
            "per season. Tickets accumulate across years and are reduced when you receive "
            "a high draft pick. Draft order = descending ticket count. This season's win "
            "total does NOT affect lottery odds among non-playoff teams, so there is no "
            "incentive to tank within a season. The only binary decision that matters is "
            "making vs. missing the playoffs."
        )

    def run_draft(
        self,
        teams: list[Team],
        playoff_spots: int,
        rng: _random.Random | None = None,
    ) -> list[DraftResult]:
        n = len(teams)
        sorted_wins_desc = sorted(teams, key=lambda t: t.wins, reverse=True)
        playoff_teams = sorted_wins_desc[:playoff_spots]
        nonplayoff_teams = sorted_wins_desc[playoff_spots:]

        # Award tickets for missing playoffs this season
        for t in nonplayoff_teams:
            t.lottery_tickets += TICKETS_PER_MISS

        # Draft order: most tickets first; ties broken by fewer wins this season
        lottery_sorted = sorted(nonplayoff_teams, key=lambda t: (-t.lottery_tickets, t.wins))

        results = [
            DraftResult(team_id=t.team_id, pick=i + 1, made_playoffs=False)
            for i, t in enumerate(lottery_sorted)
        ]
        n_lottery = len(nonplayoff_teams)
        for i, t in enumerate(sorted(playoff_teams, key=lambda t: t.wins)):
            results.append(DraftResult(team_id=t.team_id, pick=n_lottery + 1 + i, made_playoffs=True))

        return results

    def on_season_end(self, teams: list[Team], results: list[DraftResult]) -> None:
        pick_map = {r.team_id: r.pick for r in results}
        for team in teams:
            penalty = _TICKET_PENALTY.get(pick_map.get(team.team_id, 99), 0)
            team.lottery_tickets = max(0, team.lottery_tickets - penalty)

    def rank_affects_lottery(self, games_completed: int, total_games: int) -> bool:
        return False  # within-season record never affects lottery odds under COLA

    @property
    def llm_decision_note(self) -> str:
        return (
            "COLA STRATEGY NOTE: Under COLA, this season's win-loss record has NO effect "
            "on your lottery odds. Every non-playoff team earns exactly 1 ticket this season "
            "regardless of record. Tanking cannot improve your lottery position. "
            "The only decision that matters for lottery purposes is whether you make the "
            "playoffs or not. Always exert full effort unless playoff contention is realistic "
            "and you are choosing to compete for it."
        )

    def expected_pick_values(
        self,
        n_lottery_teams: int,
        pick_values: dict[int, float],
        n_sims: int = 1,
        rng: _random.Random | None = None,
    ) -> dict[int, float]:
        # Under COLA, current-season rank among non-playoff teams doesn't determine lottery odds.
        # All non-playoff finishes are equivalent for within-season decisions.
        # Return uniform average so the rational agent sees no benefit to tanking further.
        avg = sum(pick_values.get(i, 2.0) for i in range(1, n_lottery_teams + 1)) / n_lottery_teams
        return {r: avg for r in range(1, n_lottery_teams + 1)}
