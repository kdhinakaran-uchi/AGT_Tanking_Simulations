import random as _random
from dataclasses import dataclass

from simulation.team import Team
from simulation.game import simulate_game
from mechanisms.base import DraftMechanism, DraftResult
from agents.base import Agent, DecisionContext
from data.db import Database


@dataclass
class SeasonResult:
    season: int
    draft_results: list[DraftResult]
    tanking_rate: float   # fraction of agent decisions with effort < 0.5
    avg_effort: float


class Season:
    def __init__(
        self,
        teams: list[Team],
        agents: dict[int, Agent],
        mechanism: DraftMechanism,
        season: int,
        playoff_spots: int,
        games_per_team: int,
        checkpoint_interval: int,
        run_id: str,
        db: Database | None = None,
        rng: _random.Random | None = None,
        snapshot_interval: int = 10,
    ):
        self.teams = teams
        self.agents = agents
        self.mechanism = mechanism
        self.season = season
        self.playoff_spots = playoff_spots
        self.games_per_team = games_per_team
        self.checkpoint_interval = checkpoint_interval
        self.run_id = run_id
        self.db = db
        self._rng = rng or _random.Random()
        self.snapshot_interval = snapshot_interval
        self._team_by_id: dict[int, Team] = {t.team_id: t for t in teams}

    def run(self) -> SeasonResult:
        schedule = self._generate_schedule()
        current_efforts: dict[int, float] = {}
        total_decisions = 0
        tanking_decisions = 0

        # Checkpoint 0: decisions before the first game
        checkpoint_num = 0
        for team in self.teams:
            ctx = self._ctx(team, checkpoint_num, 0)
            effort, reasoning = self.agents[team.team_id].decide(ctx)
            effort = _clip(effort)
            current_efforts[team.team_id] = effort
            total_decisions += 1
            if effort < 0.5:
                tanking_decisions += 1
            if self.db:
                self.db.insert_decision(
                    self.run_id, self.season, checkpoint_num, team.team_id,
                    0, self.games_per_team, team.wins, team.losses,
                    self._rank(team), effort, reasoning,
                    type(self.agents[team.team_id]).__name__,
                )

        for game_idx, (id_a, id_b) in enumerate(schedule):
            # New checkpoint?
            if game_idx > 0 and game_idx % self.checkpoint_interval == 0:
                checkpoint_num = game_idx // self.checkpoint_interval
                for team in self.teams:
                    ctx = self._ctx(team, checkpoint_num, game_idx)
                    effort, reasoning = self.agents[team.team_id].decide(ctx)
                    effort = _clip(effort)
                    current_efforts[team.team_id] = effort
                    total_decisions += 1
                    if effort < 0.5:
                        tanking_decisions += 1
                    if self.db:
                        self.db.insert_decision(
                            self.run_id, self.season, checkpoint_num, team.team_id,
                            game_idx, self.games_per_team - team.games_played,
                            team.wins, team.losses, self._rank(team),
                            effort, reasoning, type(self.agents[team.team_id]).__name__,
                        )

            # Bilevel: snapshot standings when we hit the lock game
            if (
                hasattr(self.mechanism, "record_lock_snapshot")
                and game_idx == getattr(self.mechanism, "lock_game", -1)
            ):
                self.mechanism.record_lock_snapshot(self.teams)  # type: ignore[attr-defined]

            team_a = self._team_by_id[id_a]
            team_b = self._team_by_id[id_b]
            eff_a = current_efforts.get(id_a, 1.0)
            eff_b = current_efforts.get(id_b, 1.0)

            a_w, a_l = team_a.wins, team_a.losses
            b_w, b_l = team_b.wins, team_b.losses

            winner, loser = simulate_game(team_a, eff_a, team_b, eff_b, self._rng)

            # Hook for mechanisms that track per-game outcomes (e.g. WeightedLossMechanism)
            if hasattr(self.mechanism, "record_game_loss"):
                self.mechanism.record_game_loss(game_idx, loser.team_id, self.games_per_team)

            if self.db:
                self.db.insert_game(
                    self.run_id, self.season, game_idx,
                    id_a, id_b, eff_a, eff_b, winner.team_id,
                    a_w, a_l, b_w, b_l,
                )

            if self.db and (game_idx + 1) % self.snapshot_interval == 0:
                self.db.insert_standings_snapshot(
                    self.run_id, self.season, game_idx + 1, self.teams
                )

        if self.db:
            self.db.commit()

        draft_results = self.mechanism.run_draft(self.teams, self.playoff_spots, self._rng)
        self.mechanism.on_season_end(self.teams, draft_results)

        if self.db:
            sorted_final = sorted(self.teams, key=lambda t: t.wins, reverse=True)
            pick_map = {r.team_id: r for r in draft_results}
            for i, t in enumerate(sorted_final):
                r = pick_map[t.team_id]
                self.db.insert_draft_result(
                    self.run_id, self.season, t.team_id,
                    t.wins, t.losses, i + 1,
                    r.made_playoffs, r.pick, t.lottery_tickets,
                )
            self.db.commit()

        tanking_rate = tanking_decisions / total_decisions if total_decisions else 0.0
        avg_effort = 1.0 - tanking_rate

        return SeasonResult(
            season=self.season,
            draft_results=draft_results,
            tanking_rate=tanking_rate,
            avg_effort=avg_effort,
        )

    def _ctx(self, team: Team, checkpoint: int, games_completed: int) -> DecisionContext:
        return DecisionContext(
            season=self.season,
            checkpoint=checkpoint,
            games_completed=games_completed,
            games_remaining=self.games_per_team - team.games_played,
            total_games=self.games_per_team,
            team=team,
            standings=sorted(self.teams, key=lambda t: t.wins, reverse=True),
            playoff_spots=self.playoff_spots,
            mechanism=self.mechanism,
            checkpoint_interval=self.checkpoint_interval,
        )

    def _rank(self, team: Team) -> int:
        return (
            sorted(self.teams, key=lambda t: t.wins, reverse=True).index(team) + 1
        )

    def _generate_schedule(self) -> list[tuple[int, int]]:
        """Greedy balanced schedule: all pairs pooled 3x, shuffled, selected until each
        team has games_per_team games."""
        ids = [t.team_id for t in self.teams]
        n = len(ids)
        all_pairs = [(ids[i], ids[j]) for i in range(n) for j in range(i + 1, n)]
        pool = all_pairs * 3
        self._rng.shuffle(pool)

        counts: dict[int, int] = {tid: 0 for tid in ids}
        schedule: list[tuple[int, int]] = []
        for a, b in pool:
            if counts[a] < self.games_per_team and counts[b] < self.games_per_team:
                schedule.append((a, b))
                counts[a] += 1
                counts[b] += 1
            if all(c == self.games_per_team for c in counts.values()):
                break

        self._rng.shuffle(schedule)
        return schedule


def _clip(effort: float) -> float:
    return max(0.0, min(1.0, effort))
