"""NBA '3-2-1' proposed lottery reform.

Key differences from the 2019 NBA lottery:

1. TIER-BASED balls (NOT rank-based):
     Tier A — bottom 3 records:    2 balls each  [FEWER than Tier B]
     Tier B — 4th–14th worst:      3 balls each
   Result: being 4th–worst is strictly better than being 3rd–worst.
   Rational agents should avoid the relegation zone rather than chase it.

2. ALL lottery picks (1–14) are determined by weighted draw without
   replacement. The 2019 lottery only randomized picks 1–4.

3. Tier A floor: no Tier A team can receive a pick worse than 12th.

4. Consecutive-win restrictions (tracked across seasons):
     Rule 1 — no back-to-back pick #1 winners.
     Rule 2 — no top-5 pick in three consecutive years.

5. Commissioner penalty: optional per-team ball reduction for
   non-competitive behavior (default: no penalties).

Simplifications vs. the full spec:
  - Play-in tournament not modeled. The full proposal has 16 lottery
    teams (10 pure lottery + 4 Tier-C play-in losers + 2 Tier-D losers);
    our simulation has no conference structure, so we retain 14 lottery
    teams and omit Tiers C and D.
  - Tier A floor is at pick 12 (matching the spec), so picks 13–14
    always go to Tier B teams.
"""

import random as _random

from mechanisms.base import DraftMechanism, DraftResult
from simulation.team import Team

_TIER_A_SIZE = 3        # bottom N records are relegated to Tier A
_TIER_A_BALLS = 2       # Tier A ball count (FEWER → worse odds than Tier B)
_TIER_B_BALLS = 3       # Tier B ball count
_TIER_A_FLOOR = 12      # Tier A teams cannot receive a pick worse than this


class NBAThreeTwoOneLottery(DraftMechanism):
    """NBA '3-2-1' proposed lottery reform (14-team adapted version)."""

    def __init__(self, penalty_balls: dict[int, int] | None = None):
        # Optional commissioner adjustment: {team_id: balls_to_subtract}
        self.penalty_balls: dict[int, int] = penalty_balls or {}
        # Two most recent picks per team for consecutive-win tracking
        # {team_id: [last_season_pick, two_seasons_ago_pick]}
        self._pick_history: dict[int, list[int | None]] = {}

    @property
    def name(self) -> str:
        return "nba_321_lottery"

    @property
    def description(self) -> str:
        return (
            "NBA '3-2-1' proposed reform: Tier A (bottom 3 records) gets 2 balls, "
            "Tier B (4th–14th worst) gets 3 balls — so the absolute worst teams have "
            "WORSE odds than the teams just above them. All 14 picks are lottery draws "
            "(not just top 4). Tier A teams are guaranteed no worse than pick 12. "
            "Consecutive top-pick winners face eligibility restrictions."
        )

    # ── ball pool ──────────────────────────────────────────────────────────────

    def _build_pool(
        self, lottery_teams: list[Team]
    ) -> tuple[list[int], set[int]]:
        """Return (pool, tier_a_ids). Pool is team_ids repeated by ball count."""
        pool: list[int] = []
        tier_a_ids: set[int] = set()
        for i, t in enumerate(lottery_teams):
            rank = i + 1  # 1 = worst record
            base = _TIER_A_BALLS if rank <= _TIER_A_SIZE else _TIER_B_BALLS
            balls = max(0, base - self.penalty_balls.get(t.team_id, 0))
            pool.extend([t.team_id] * balls)
            if rank <= _TIER_A_SIZE:
                tier_a_ids.add(t.team_id)
        return pool, tier_a_ids

    # ── consecutive-win helpers ────────────────────────────────────────────────

    def _no_pick1_ids(self) -> set[int]:
        """Teams ineligible for pick #1 (won it last year)."""
        return {
            tid for tid, hist in self._pick_history.items()
            if hist and hist[0] is not None and hist[0] == 1
        }

    def _no_top5_ids(self) -> set[int]:
        """Teams ineligible for top-5 (top-5 pick in each of last 2 years)."""
        return {
            tid for tid, hist in self._pick_history.items()
            if (
                len(hist) >= 2
                and hist[0] is not None and hist[0] <= 5
                and hist[1] is not None and hist[1] <= 5
            )
        }

    # ── draft machinery ────────────────────────────────────────────────────────

    def run_draft(
        self,
        teams: list[Team],
        playoff_spots: int,
        rng: _random.Random | None = None,
    ) -> list[DraftResult]:
        _rng = rng or _random.Random()

        sorted_asc = sorted(teams, key=lambda t: (t.wins, t.team_id))  # worst first
        n_lottery = len(teams) - playoff_spots
        lottery_teams = sorted_asc[:n_lottery]
        playoff_teams = sorted_asc[n_lottery:]

        pool, tier_a_ids = self._build_pool(lottery_teams)

        no_pick1 = self._no_pick1_ids() & {t.team_id for t in lottery_teams}
        no_top5 = self._no_top5_ids() & {t.team_id for t in lottery_teams}

        picks: dict[int, int] = {}
        remaining = list(pool)

        for pick_num in range(1, n_lottery + 1):
            excluded: set[int] = set()
            if pick_num == 1:
                excluded |= no_pick1
            if pick_num <= 5:
                excluded |= no_top5
            if pick_num > _TIER_A_FLOOR:
                excluded |= tier_a_ids

            eligible = [tid for tid in remaining if tid not in excluded]
            if not eligible:
                eligible = remaining  # edge case: lift all restrictions

            chosen = _rng.choice(eligible)
            picks[chosen] = pick_num
            remaining = [tid for tid in remaining if tid != chosen]

        # Enforce Tier A floor (handles edge cases from the fallback above)
        _enforce_tier_a_floor(picks, tier_a_ids, _TIER_A_FLOOR)

        results = [
            DraftResult(team_id=t.team_id, pick=picks[t.team_id], made_playoffs=False)
            for t in lottery_teams
        ]
        for i, t in enumerate(sorted(playoff_teams, key=lambda t: t.wins)):
            results.append(
                DraftResult(team_id=t.team_id, pick=n_lottery + 1 + i, made_playoffs=True)
            )
        return results

    def on_season_end(self, teams: list, results: list[DraftResult]) -> None:
        for r in results:
            if not r.made_playoffs:
                prev = self._pick_history.get(r.team_id, [None, None])
                self._pick_history[r.team_id] = [r.pick, prev[0]]

    # ── EV table for rational agent ────────────────────────────────────────────

    def _simulate_one_lottery(
        self, n_lottery_teams: int, rng: _random.Random
    ) -> dict[int, int]:
        """Simulate one lottery by lottery_rank (1=worst). No consecutive restrictions."""
        remaining_ranks = list(range(1, n_lottery_teams + 1))
        remaining_w = [
            _TIER_A_BALLS if r <= _TIER_A_SIZE else _TIER_B_BALLS
            for r in remaining_ranks
        ]
        picks: dict[int, int] = {}

        for pick_num in range(1, n_lottery_teams + 1):
            # Enforce Tier A floor: rank ≤ 3 ineligible for picks beyond floor
            if pick_num > _TIER_A_FLOOR:
                pairs = [
                    (r, w) for r, w in zip(remaining_ranks, remaining_w)
                    if r > _TIER_A_SIZE
                ]
            else:
                pairs = list(zip(remaining_ranks, remaining_w))

            if not pairs:
                pairs = list(zip(remaining_ranks, remaining_w))

            eligible_ranks, eligible_ws = zip(*pairs)
            idx = rng.choices(range(len(eligible_ranks)), weights=eligible_ws)[0]
            chosen = eligible_ranks[idx]
            picks[chosen] = pick_num

            pos = remaining_ranks.index(chosen)
            remaining_ranks.pop(pos)
            remaining_w.pop(pos)

        return picks


# ── helpers ────────────────────────────────────────────────────────────────────

def _enforce_tier_a_floor(
    picks: dict[int, int], tier_a_ids: set[int], floor: int
) -> None:
    """Swap any Tier A team assigned pick > floor with a non-Tier-A team.

    Handles the rare edge case where the draw's fallback (all-restrictions
    lifted) places a Tier A team at picks 13 or 14. Swaps them with the
    non-Tier-A team holding the numerically highest pick still within the
    floor range, minimising disruption to the rest of the order.
    """
    violations = sorted(
        [(tid, p) for tid, p in picks.items() if tid in tier_a_ids and p > floor],
        key=lambda x: -x[1],  # worst pick first
    )
    if not violations:
        return

    # Non-Tier-A teams with picks ≤ floor (eligible swap partners)
    candidates = sorted(
        [(tid, p) for tid, p in picks.items() if tid not in tier_a_ids and p <= floor],
        key=lambda x: -x[1],  # highest pick first → minimal disruption
    )

    for (tid_a, pick_a), (tid_b, pick_b) in zip(violations, candidates):
        picks[tid_a] = pick_b
        picks[tid_b] = pick_a
