"""LLM-powered team agent using the Anthropic API.

Requires ANTHROPIC_API_KEY environment variable.
Uses prompt caching on the system prompt (mechanism rules + value parameters)
to reduce per-call cost. Only the dynamic game state changes per call.
"""

import json
import os
import time
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
  effort level for the upcoming block of games.
  effort=0.0 → minimum (team plays at 30% effectiveness; cannot throw games outright)
  effort=1.0 → full effort (100% effectiveness)
  effort=0.5 → 65% effectiveness  [example of intermediate value]
- Win probability: P(A wins) = (skill_A × eff_A) / (skill_A × eff_A + skill_B × eff_B)
  where eff = 0.3 + 0.7 × effort  [so effort=0.0 → eff=0.30, effort=1.0 → eff=1.00]
- Your team's true_skill is fixed for your roster and does not change mid-season.

DRAFT MECHANISM
{ctx.mechanism.description}

VALUES (points you accumulate toward your long-run score)
- Making the playoffs:  {int(PLAYOFF_VALUE)} pts
- Draft pick quality:   {pick_preview}, picks beyond #14 ≈ 2 pts
- Goal: maximize total points across all seasons.

DECISION RULES
Treat this as a binary choice: effort=1.0 (compete) or effort=0.0 (tank for lottery).
Intermediate values are almost never correct — commit to one strategy.

Default to effort=1.0 UNLESS all three conditions hold:
  1. You have played at least 25 games (standings are not yet meaningful before that).
  2. Your current win rate projects you well outside playoff contention by season end.
  3. The expected lottery pick upside clearly outweighs your playoff probability.

Important calibration: the AVERAGE lottery pick across all non-playoff teams is worth ~24 pts —
far less than the {int(PLAYOFF_VALUE)}-pt playoff bonus. Even the best possible lottery outcome
(#1 pick, 100 pts, requires finishing dead last with only 14% odds) is worth far less than a
guaranteed playoff berth. Only tank if your playoff probability is negligible (under ~15%) AND
you are projected to finish among the league's worst 3-4 teams. When in doubt, compete.

RESPONSE FORMAT — return ONLY a raw JSON object, no markdown, no code fences, no explanation:
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

    season_pct = ctx.games_completed / ctx.total_games if ctx.total_games else 0
    if gap <= 0:
        position_note = f"IN PLAYOFF POSITION (ahead of bubble by {-gap})"
    elif season_pct < 0.35:
        position_note = (
            f"OUT of playoff position by {gap} spots — but only {ctx.games_completed} of "
            f"{ctx.total_games} games played; standings are highly uncertain this early"
        )
    else:
        position_note = f"OUT of playoffs by {gap} spots"
    lock_note = (
        "\nNOTE: The lottery draft position is LOCKED for this season — tanking has zero benefit."
        if not ctx.mechanism.rank_affects_lottery(ctx.games_completed, ctx.total_games)
        else ""
    )

    # Convert schedule-game checkpoint interval to approximate per-team games.
    games_per_checkpoint = max(1, round(ctx.checkpoint_interval * 2 / len(ctx.standings)))

    return f"""Season {ctx.season + 1}  |  Decision {ctx.checkpoint + 1}  |  After game {ctx.games_completed}/{ctx.total_games}

YOUR TEAM: {ctx.team.name}
  Record:     {ctx.team.wins}W-{ctx.team.losses}L  (Rank #{rank} of {len(ctx.standings)})
  Remaining:  {ctx.games_remaining} games  —  {position_note}
  Lottery tickets: {ctx.team.lottery_tickets}{lock_note}

STANDINGS (top 5 / bottom 5):
{standings_block}

What effort level do you choose for the next {games_per_checkpoint} games?"""


class LLMAgent(Agent):
    """Team agent powered by Claude. Caches the system prompt across calls."""

    def __init__(self, team: Team):
        super().__init__(team)
        self._cached_system: str | None = None

    def decide(self, ctx: DecisionContext) -> tuple[float, str]:
        if self._cached_system is None:
            self._cached_system = _system_prompt(ctx)

        client = _get_client()
        print(f"    [LLM] s={ctx.season} ck={ctx.checkpoint} team={ctx.team.name[:10]:<10}", end=" ", flush=True)
        for attempt in range(4):
            try:
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
                    timeout=30.0,
                )
                break
            except Exception as e:
                if attempt == 3:
                    raise
                wait = 5 * (2 ** attempt)  # 5, 10, 20 seconds
                print(f"\n    [retry {attempt+1}/3 in {wait}s: {type(e).__name__}]", flush=True)
                time.sleep(wait)

        raw = response.content[0].text.strip()
        # Strip markdown code fences if the model wraps the JSON
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            parsed = json.loads(raw)
            effort = float(parsed["effort"])
            reasoning = str(parsed.get("reasoning", ""))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            effort = 1.0
            reasoning = f"parse_error; raw={raw[:80]}"

        safe = reasoning[:80].encode("ascii", errors="replace").decode("ascii")
        print(f"e={effort:.2f}  [{safe}]", flush=True)
        return max(0.0, min(1.0, effort)), reasoning
