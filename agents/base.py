from abc import ABC, abstractmethod
from dataclasses import dataclass
from simulation.team import Team
from mechanisms.base import DraftMechanism


@dataclass
class DecisionContext:
    season: int
    checkpoint: int          # 0-indexed decision number within the season
    games_completed: int
    games_remaining: int
    total_games: int
    team: Team               # this agent's team (current state)
    standings: list[Team]    # all teams sorted by wins descending
    playoff_spots: int
    mechanism: DraftMechanism
    checkpoint_interval: int


class Agent(ABC):
    def __init__(self, team: Team):
        self.team = team

    @abstractmethod
    def decide(self, ctx: DecisionContext) -> tuple[float, str]:
        """Return (effort ∈ [0.0, 1.0], reasoning string)."""
        ...
