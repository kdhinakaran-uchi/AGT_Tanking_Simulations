import json
import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    mechanism           TEXT NOT NULL,
    agent_type          TEXT NOT NULL,
    n_teams             INTEGER NOT NULL,
    playoff_spots       INTEGER NOT NULL,
    games_per_team      INTEGER NOT NULL,
    n_seasons           INTEGER NOT NULL,
    checkpoint_interval INTEGER NOT NULL,
    params              TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    run_id      TEXT NOT NULL,
    team_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    true_skill  REAL NOT NULL,
    PRIMARY KEY (run_id, team_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS games (
    game_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,
    season              INTEGER NOT NULL,
    game_number         INTEGER NOT NULL,
    team_a_id           INTEGER NOT NULL,
    team_b_id           INTEGER NOT NULL,
    effort_a            REAL NOT NULL,
    effort_b            REAL NOT NULL,
    winner_id           INTEGER NOT NULL,
    team_a_wins_before  INTEGER NOT NULL,
    team_a_losses_before INTEGER NOT NULL,
    team_b_wins_before  INTEGER NOT NULL,
    team_b_losses_before INTEGER NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS agent_decisions (
    decision_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    season          INTEGER NOT NULL,
    checkpoint      INTEGER NOT NULL,
    team_id         INTEGER NOT NULL,
    games_completed INTEGER NOT NULL,
    games_remaining INTEGER NOT NULL,
    wins            INTEGER NOT NULL,
    losses          INTEGER NOT NULL,
    rank            INTEGER NOT NULL,
    effort_chosen   REAL NOT NULL,
    reasoning       TEXT,
    agent_type      TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS draft_results (
    result_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL,
    season              INTEGER NOT NULL,
    team_id             INTEGER NOT NULL,
    final_wins          INTEGER NOT NULL,
    final_losses        INTEGER NOT NULL,
    final_rank          INTEGER NOT NULL,
    made_playoffs       INTEGER NOT NULL,
    draft_pick          INTEGER NOT NULL,
    lottery_tickets_end INTEGER NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS standings_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    season      INTEGER NOT NULL,
    after_game  INTEGER NOT NULL,
    team_id     INTEGER NOT NULL,
    wins        INTEGER NOT NULL,
    losses      INTEGER NOT NULL,
    rank        INTEGER NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS skill_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    season      INTEGER NOT NULL,
    team_id     INTEGER NOT NULL,
    true_skill  REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
"""


class Database:
    def __init__(self, path: str | Path = "tanking_sim.db"):
        self.path = Path(path)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ── run metadata ──────────────────────────────────────────────────────────

    def create_run(
        self,
        run_id: str,
        mechanism: str,
        agent_type: str,
        n_teams: int,
        playoff_spots: int,
        games_per_team: int,
        n_seasons: int,
        checkpoint_interval: int,
        params: dict | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, mechanism, agent_type, n_teams, playoff_spots,
                games_per_team, n_seasons, checkpoint_interval,
                json.dumps(params or {}), datetime.utcnow().isoformat(),
            ),
        )
        self._conn.commit()

    def insert_teams(self, run_id: str, teams: list) -> None:
        self._conn.executemany(
            "INSERT OR IGNORE INTO teams VALUES (?,?,?,?)",
            [(run_id, t.team_id, t.name, t.true_skill) for t in teams],
        )
        self._conn.commit()

    # ── per-game ──────────────────────────────────────────────────────────────

    def insert_game(
        self,
        run_id: str,
        season: int,
        game_number: int,
        team_a_id: int,
        team_b_id: int,
        effort_a: float,
        effort_b: float,
        winner_id: int,
        a_wins_before: int,
        a_losses_before: int,
        b_wins_before: int,
        b_losses_before: int,
    ) -> None:
        self._conn.execute(
            "INSERT INTO games VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, season, game_number, team_a_id, team_b_id,
                effort_a, effort_b, winner_id,
                a_wins_before, a_losses_before, b_wins_before, b_losses_before,
            ),
        )

    # ── agent decisions ───────────────────────────────────────────────────────

    def insert_decision(
        self,
        run_id: str,
        season: int,
        checkpoint: int,
        team_id: int,
        games_completed: int,
        games_remaining: int,
        wins: int,
        losses: int,
        rank: int,
        effort: float,
        reasoning: str,
        agent_type: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO agent_decisions VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, season, checkpoint, team_id, games_completed, games_remaining,
                wins, losses, rank, effort, reasoning, agent_type,
            ),
        )

    # ── draft results ─────────────────────────────────────────────────────────

    def insert_draft_result(
        self,
        run_id: str,
        season: int,
        team_id: int,
        final_wins: int,
        final_losses: int,
        final_rank: int,
        made_playoffs: bool,
        draft_pick: int,
        lottery_tickets_end: int,
    ) -> None:
        self._conn.execute(
            "INSERT INTO draft_results VALUES (NULL,?,?,?,?,?,?,?,?,?)",
            (
                run_id, season, team_id, final_wins, final_losses, final_rank,
                int(made_playoffs), draft_pick, lottery_tickets_end,
            ),
        )

    # ── standings snapshots ───────────────────────────────────────────────────

    def insert_standings_snapshot(self, run_id: str, season: int, after_game: int, teams: list) -> None:
        sorted_teams = sorted(teams, key=lambda t: t.wins, reverse=True)
        self._conn.executemany(
            "INSERT INTO standings_snapshots VALUES (NULL,?,?,?,?,?,?,?)",
            [
                (run_id, season, after_game, t.team_id, t.wins, t.losses, i + 1)
                for i, t in enumerate(sorted_teams)
            ],
        )

    def insert_skill_snapshot(self, run_id: str, season: int, teams: list) -> None:
        self._conn.executemany(
            "INSERT INTO skill_history VALUES (NULL,?,?,?,?)",
            [(run_id, season, t.team_id, t.true_skill) for t in teams],
        )

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()
