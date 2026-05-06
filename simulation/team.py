from dataclasses import dataclass


@dataclass
class Team:
    team_id: int
    name: str
    true_skill: float   # fixed baseline ability α; higher = better
    wins: int = 0
    losses: int = 0
    lottery_tickets: int = 0  # COLA carry-over tickets accumulated across seasons

    @property
    def games_played(self) -> int:
        return self.wins + self.losses

    @property
    def win_pct(self) -> float:
        return self.wins / self.games_played if self.games_played else 0.0

    def reset_season_record(self) -> None:
        self.wins = 0
        self.losses = 0
