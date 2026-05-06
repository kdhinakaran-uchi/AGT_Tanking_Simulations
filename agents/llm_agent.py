"""LLM-powered team agent using the Anthropic API.

Requires ANTHROPIC_API_KEY environment variable.
Uses prompt caching on the system prompt (mechanism rules + value parameters)
to reduce per-call cost. Only the dynamic game state changes per call.
"""

import json
import os
from agents.base import Agent, DecisionContext
from agents.rational import PICK_VALUES, PLAYOFF_VALUE
from simulation.team import Team

try:
    import anthropic as _anthropic
    _CLIENT: _anthropic.Anthropic | None = None

    def _get_client() -> "_anthropic.Anthropic":
        global _CLIENT
        if _CLIENT is None:
            _CLIENT = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        return _CLIENT
except ImportError:
    _anthropic = None  # type: ignore
    def _get_client():
        raise RuntimeError("anthropic package not installed. Run: uv add anthropic")


_MODEL = "claude-haiku-4-5-20251001"


def _system_prompt(ctx: DecisionContext) -> str:
    pick_preview = ", ".join(f"#{k}={int(v)}pts" for k, v in list(PICK_VALUES.items())[:8])
    return f"""You are managing an NBA team in a research simulation studying draft lottery incentives.

GAME MODEL
- {len(ctx.standings)} teams total. Top {ctx.playoff_spots} make the playoffs each season.
- Teams play {ctx.total_games} games per season. Every {ctx.checkpoint_interval} games you set your
  effort level for the upcoming block of games. effort=1.0 means full effort; effort=0.0 means
  minimal effort (but your team still plays at a 30% effectiveness floor — you cannot throw games).
- Win probability: P(A wins) = (skill_A × eff_A) / (skill_A × eff_A + skill_B × eff_B)
  where eff = 0.3 + 0.7 × effort
- Your team's true_skill is fixed for your roster and does not change mid-season.

DRAFT MECHANISM
{ctx.mechanism.description}

VALUES (points you accumulate toward your long-run score)
- Making the playoffs:  {int(PLAYOFF_VALUE)} pts
- Draft pick quality:   {pick_preview}, picks beyond #14 ≈ 2 pts
- Goal: maximize total points across all seasons.

RESPONSE FORMAT — return ONLY valid JSON, nothing else:
{{"effort": <float 0.0–1.0>, "reasoning": "<one concise sentence>"}}"""


def _user_message(ctx: DecisionContext) -> str:
    sorted_standings = sorted(ctx.standings, key=lambda t: t.wins, reverse=True)
    rank = next(i + 1 for i, t in enumerate(sorted_standings) if t.team_id == ctx.team.team_id)
    gap = rank - ctx.playoff_spots

    def _fmt(t: Team, i: int) -> str:
        marker = " ← YOU" if t.team_id == ctx.team.team_id else ""
        return f"  #{i+1:2d}  {t.name:<18} {t.wins}W-{t.losses}L{marker}"

    top5 = sorted_standings[:5]
    bot5 = sorted_standings[-5:]
    divider = "  ..." if len(ctx.standings) > 10 else ""
    standings_block = (
        "\n".join(_fmt(t, i) for i, t in enumerate(top5))
        + ("\n" + divider if divider else "")
        + "\n"
        + "\n".join(_fmt(t, len(ctx.standings) - 5 + i) for i, t in enumerate(bot5))
    )

    position_note = (
        f"IN PLAYOFF POSITION (ahead of bubble by {-gap})"
        if gap <= 0
        else f"OUT of playoffs by {gap} spots"
    )
    lock_note = (
        "\nNOTE: The lottery draft position is LOCKED for this season — tanking has zero benefit."
        if not ctx.mechanism.rank_affects_lottery(ctx.games_completed, ctx.total_games)
        else ""
    )

    return f"""Season {ctx.season + 1}  |  Decision {ctx.checkpoint + 1}  |  After game {ctx.games_completed}/{ctx.total_games}

YOUR TEAM: {ctx.team.name}
  True skill: {ctx.team.true_skill:.3f}
  Record:     {ctx.team.wins}W-{ctx.team.losses}L  (Rank #{rank} of {len(ctx.standings)})
  Remaining:  {ctx.games_remaining} games  —  {position_note}
  COLA tickets: {ctx.team.lottery_tickets}{lock_note}

STANDINGS (top 5 / bottom 5):
{standings_block}

What effort level do you choose for the next {ctx.checkpoint_interval} games?"""


class LLMAgent(Agent):
    """Team agent powered by Claude. Caches the system prompt across calls."""

    def __init__(self, team: Team):
        super().__init__(team)
        self._cached_system: str | None = None

    def decide(self, ctx: DecisionContext) -> tuple[float, str]:
        if self._cached_system is None:
            self._cached_system = _system_prompt(ctx)

        client = _get_client()
        response = client.messages.create(
            model=_MODEL,
            max_tokens=200,
            system=[
                {
                    "type": "text",
                    "text": self._cached_system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": _user_message(ctx)}],
        )

        raw = response.content[0].text.strip()
        try:
            parsed = json.loads(raw)
            effort = float(parsed["effort"])
            reasoning = str(parsed.get("reasoning", ""))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            effort = 1.0
            reasoning = f"parse_error; raw={raw[:80]}"

        return max(0.0, min(1.0, effort)), reasoning
