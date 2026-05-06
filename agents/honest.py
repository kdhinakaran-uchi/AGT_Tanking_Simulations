from agents.base import Agent, DecisionContext


class HonestAgent(Agent):
    """Always plays at full effort. Baseline for stability experiments."""

    def decide(self, ctx: DecisionContext) -> tuple[float, str]:
        return 1.0, "always try"
