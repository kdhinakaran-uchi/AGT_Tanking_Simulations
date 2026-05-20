"""
Analysis and reporting for tanking simulation results.

Usage:
  python analysis.py                     # summarize all runs in tanking_sim.db
  python analysis.py --db my.db          # different database
  python analysis.py --run-ids id1 id2   # specific runs only
  python analysis.py --plot              # also generate matplotlib plots (if installed)
"""

import argparse
import json
import sqlite3
from pathlib import Path


# ── Kendall tau (mirrors main.py, needed for analysis-time recomputation) ────

def _kendall_tau(order_a: list[int], order_b: list[int]) -> float:
    """Normalized Kendall tau distance (0 = identical, 1 = fully reversed)."""
    n = len(order_a)
    pos_b = {v: i for i, v in enumerate(order_b)}
    discordant = sum(
        1
        for i in range(n)
        for j in range(i + 1, n)
        if pos_b[order_a[i]] > pos_b[order_a[j]]
    )
    pairs = n * (n - 1) // 2
    return discordant / pairs if pairs else 0.0


# ── data loading ──────────────────────────────────────────────────────────────

def load_runs(conn: sqlite3.Connection, run_ids: list[str] | None = None) -> list[dict]:
    q = "SELECT * FROM runs"
    params: tuple = ()
    if run_ids:
        placeholders = ",".join("?" * len(run_ids))
        q += f" WHERE run_id IN ({placeholders})"
        params = tuple(run_ids)
    q += " ORDER BY created_at"
    cur = conn.execute(q, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def tanking_stats(conn: sqlite3.Connection, run_id: str) -> dict:
    """Per-season tanking rate and average effort from agent_decisions."""
    rows = conn.execute(
        """
        SELECT season,
               AVG(CASE WHEN effort_chosen < 0.5 THEN 1.0 ELSE 0.0 END) AS tanking_rate,
               AVG(effort_chosen) AS avg_effort,
               COUNT(*) AS n_decisions
        FROM agent_decisions
        WHERE run_id = ?
        GROUP BY season
        ORDER BY season
        """,
        (run_id,),
    ).fetchall()
    if not rows:
        return {"tanking_rate": 0.0, "avg_effort": 1.0}
    rates = [r[1] for r in rows]
    efforts = [r[2] for r in rows]
    return {
        "tanking_rate": sum(rates) / len(rates),
        "avg_effort": sum(efforts) / len(efforts),
        "by_season": [{"season": r[0], "tanking_rate": r[1], "avg_effort": r[2]} for r in rows],
    }


def tau_distance_series(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    """Per-season Kendall tau distance between true-skill ranking and wins ranking.

    Computable from skill_history (true skill at season start) and draft_results
    (final wins rank). Returns [] if skill_history is absent for this run.
    """
    seasons = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT season FROM skill_history WHERE run_id=? ORDER BY season",
            (run_id,),
        ).fetchall()
    ]
    result = []
    for season in seasons:
        skill_rows = conn.execute(
            "SELECT team_id, true_skill FROM skill_history WHERE run_id=? AND season=?",
            (run_id, season),
        ).fetchall()
        win_rows = conn.execute(
            "SELECT team_id, final_rank FROM draft_results WHERE run_id=? AND season=? ORDER BY final_rank",
            (run_id, season),
        ).fetchall()
        if not skill_rows or not win_rows:
            continue
        true_order = [r[0] for r in sorted(skill_rows, key=lambda r: r[1], reverse=True)]
        wins_order = [r[0] for r in win_rows]  # already ordered by final_rank ASC (1=best)
        result.append({"season": season, "tau": _kendall_tau(true_order, wins_order)})
    return result


def avg_tau(conn: sqlite3.Connection, run_id: str) -> float:
    series = tau_distance_series(conn, run_id)
    return sum(s["tau"] for s in series) / len(series) if series else float("nan")


def pick_distribution(conn: sqlite3.Connection, run_id: str) -> dict:
    """Average draft pick received by initial-skill quartile."""
    rows = conn.execute(
        """
        WITH team_quartiles AS (
            SELECT team_id,
                   true_skill,
                   NTILE(4) OVER (ORDER BY true_skill) AS quartile
            FROM teams WHERE run_id = ?
        )
        SELECT tq.quartile,
               AVG(dr.draft_pick) AS avg_pick,
               COUNT(*) AS n
        FROM draft_results dr
        JOIN team_quartiles tq ON dr.team_id = tq.team_id
        WHERE dr.run_id = ?
        GROUP BY tq.quartile
        ORDER BY tq.quartile
        """,
        (run_id, run_id),
    ).fetchall()
    return {r[0]: {"avg_pick": r[1], "n": r[2]} for r in rows}


def skill_spread(conn: sqlite3.Connection, run_id: str) -> dict:
    """Skill variance and max/min by season — measures competitive balance evolution."""
    rows = conn.execute(
        """
        SELECT season,
               AVG(true_skill) AS mean_skill,
               MAX(true_skill) AS max_skill,
               MIN(true_skill) AS min_skill,
               MAX(true_skill) - MIN(true_skill) AS skill_range
        FROM skill_history
        WHERE run_id = ?
        GROUP BY season
        ORDER BY season
        """,
        (run_id,),
    ).fetchall()
    if not rows:
        return {}
    first = {"mean": rows[0][1], "range": rows[0][4]}
    last = {"mean": rows[-1][1], "range": rows[-1][4]}
    return {"first_season": first, "last_season": last, "n_seasons": len(rows)}


def playoff_attainment(conn: sqlite3.Connection, run_id: str) -> dict:
    """Fraction of seasons each skill quartile makes the playoffs."""
    rows = conn.execute(
        """
        WITH team_quartiles AS (
            SELECT team_id,
                   NTILE(4) OVER (ORDER BY true_skill) AS quartile
            FROM teams WHERE run_id = ?
        )
        SELECT tq.quartile,
               AVG(CAST(dr.made_playoffs AS REAL)) AS playoff_rate
        FROM draft_results dr
        JOIN team_quartiles tq ON dr.team_id = tq.team_id
        WHERE dr.run_id = ?
        GROUP BY tq.quartile
        ORDER BY tq.quartile
        """,
        (run_id, run_id),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ── reporting ─────────────────────────────────────────────────────────────────

def print_summary_table(conn: sqlite3.Connection, runs: list[dict]) -> None:
    print("\n" + "=" * 80)
    print(f"{'RUN':42s}  {'TANKING':>8}  {'AVG EFF':>8}  {'AVG TAU':>8}")
    print("-" * 80)
    for run in runs:
        rid = run["run_id"]
        ts = tanking_stats(conn, rid)
        tau = avg_tau(conn, rid)
        short_id = rid[:39] + "..." if len(rid) > 42 else rid
        tau_str = f"{tau:7.3f}" if tau == tau else "    n/a"
        print(
            f"{short_id:42s}  "
            f"{ts['tanking_rate']:7.1%}  "
            f"{ts['avg_effort']:7.1%}  "
            f"{tau_str}"
        )
    print("=" * 80)
    print("Avg tau: Kendall tau distance, true-skill rank vs wins rank (0=perfect, 1=worst)")


def print_mechanism_comparison(conn: sqlite3.Connection, runs: list[dict]) -> None:
    from collections import defaultdict
    by_mech: dict[str, list] = defaultdict(list)
    for run in runs:
        by_mech[run["mechanism"]].append(run)

    print("\n" + "=" * 75)
    print("MECHANISM COMPARISON")
    print("-" * 75)
    header = (
        f"{'Mechanism':14s}  {'Runs':>4}  {'Tanking':>8}  "
        f"{'Avg Effort':>10}  {'Avg Tau':>8}  {'Q1 Playoff%':>12}"
    )
    print(header)
    print("-" * 75)

    for mech, mech_runs in sorted(by_mech.items()):
        tank_vals, eff_vals, tau_vals, q1_vals = [], [], [], []
        for run in mech_runs:
            ts = tanking_stats(conn, run["run_id"])
            tank_vals.append(ts["tanking_rate"])
            eff_vals.append(ts["avg_effort"])
            t = avg_tau(conn, run["run_id"])
            if t == t:  # not nan
                tau_vals.append(t)
            pa = playoff_attainment(conn, run["run_id"])
            if 1 in pa:
                q1_vals.append(pa[1])

        avg_t = sum(tank_vals) / len(tank_vals) if tank_vals else 0.0
        avg_e = sum(eff_vals) / len(eff_vals) if eff_vals else 0.0
        avg_tau_v = sum(tau_vals) / len(tau_vals) if tau_vals else float("nan")
        avg_q1 = sum(q1_vals) / len(q1_vals) if q1_vals else float("nan")
        tau_str = f"{avg_tau_v:7.3f}" if avg_tau_v == avg_tau_v else "    n/a"

        print(
            f"{mech:14s}  {len(mech_runs):>4}  {avg_t:>7.1%}  "
            f"{avg_e:>10.1%}  {tau_str}  {avg_q1:>11.1%}"
        )
    print("=" * 75)
    print("Q1 Playoff%: fraction of seasons the bottom skill quartile makes playoffs")
    print("Avg Tau: Kendall tau distance between true-skill and wins rankings")


def print_pick_distribution(conn: sqlite3.Connection, runs: list[dict]) -> None:
    print("\n" + "=" * 55)
    print("AVG DRAFT PICK BY SKILL QUARTILE  (Q1=worst, Q4=best)")
    print("-" * 55)
    print(f"{'Run (mechanism)':30s}  {'Q1':>5}  {'Q2':>5}  {'Q3':>5}  {'Q4':>5}")
    print("-" * 55)
    for run in runs:
        pd = pick_distribution(conn, run["run_id"])
        label = run["mechanism"][:28]
        vals = [f"{pd.get(q, {}).get('avg_pick', float('nan')):5.1f}" for q in [1, 2, 3, 4]]
        print(f"{label:30s}  {'  '.join(vals)}")
    print("=" * 55)
    print("Lower pick number = better pick (pick 1 is best)")


def print_skill_evolution(conn: sqlite3.Connection, runs: list[dict]) -> None:
    print("\n" + "=" * 55)
    print("SKILL SPREAD EVOLUTION  (first vs last season)")
    print("-" * 55)
    print(f"{'Run':30s}  {'Range S0':>9}  {'Range SN':>9}")
    print("-" * 55)
    for run in runs:
        ss = skill_spread(conn, run["run_id"])
        if not ss:
            continue
        label = run["mechanism"][:28]
        r0 = ss["first_season"]["range"]
        rn = ss["last_season"]["range"]
        trend = "^" if rn > r0 else "v" if rn < r0 else "="
        print(f"{label:30s}  {r0:9.3f}  {rn:9.3f}  {trend}")
    print("=" * 55)
    print("Skill range = max_skill - min_skill across teams")
    print("^ increasing spread  v decreasing (convergence toward mean)")


# ── plots ─────────────────────────────────────────────────────────────────────

def _mpl():
    try:
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        print("matplotlib not installed. Run: uv add matplotlib")
        return None


_MECH_COLORS = {
    "nba_lottery": "#e15759",
    "bilevel":     "#4e79a7",
    "cola":        "#59a14f",
}
_MECH_LABELS = {
    "nba_lottery": "NBA Lottery",
    "bilevel":     "Bilevel",
    "cola":        "COLA",
}


def _save(fig, name: str) -> None:
    out = Path("results") / name
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"  Saved: {out}")


def plot_tanking_over_seasons(conn: sqlite3.Connection, runs: list[dict]) -> None:
    plt = _mpl()
    if plt is None:
        return
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for run in runs:
        ts = tanking_stats(conn, run["run_id"])
        if "by_season" not in ts:
            continue
        seasons = [s["season"] for s in ts["by_season"]]
        rates = [s["tanking_rate"] for s in ts["by_season"]]
        mech = run["mechanism"]
        ax.plot(seasons, rates,
                label=_MECH_LABELS.get(mech, mech),
                color=_MECH_COLORS.get(mech),
                linewidth=1.8)
    ax.set_xlabel("Season")
    ax.set_ylabel("Tanking rate")
    ax.set_title("Tanking rate over seasons by mechanism (rational agents)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.set_ylim(0, 1)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    _save(fig, "tanking_over_seasons.png")
    plt.close(fig)


def plot_tau_over_seasons(conn: sqlite3.Connection, runs: list[dict]) -> None:
    plt = _mpl()
    if plt is None:
        return
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for run in runs:
        series = tau_distance_series(conn, run["run_id"])
        if not series:
            continue
        mech = run["mechanism"]
        ax.plot([s["season"] for s in series], [s["tau"] for s in series],
                label=_MECH_LABELS.get(mech, mech),
                color=_MECH_COLORS.get(mech),
                linewidth=1.8)
    ax.set_xlabel("Season")
    ax.set_ylabel("Kendall tau distance")
    ax.set_title("Competitive balance: Kendall tau (true-skill rank vs wins rank)")
    ax.set_ylim(0, 1)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.text(0.5, -0.04,
             "0 = standings perfectly match true skill  |  1 = completely inverted",
             ha="center", fontsize=8, color="gray")
    _save(fig, "tau_over_seasons.png")
    plt.close(fig)


def plot_skill_spread(conn: sqlite3.Connection, runs: list[dict]) -> None:
    plt = _mpl()
    if plt is None:
        return
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for run in runs:
        rows = conn.execute(
            """SELECT season, MAX(true_skill) - MIN(true_skill)
               FROM skill_history WHERE run_id=?
               GROUP BY season ORDER BY season""",
            (run["run_id"],),
        ).fetchall()
        if rows:
            mech = run["mechanism"]
            ax.plot([r[0] for r in rows], [r[1] for r in rows],
                    label=_MECH_LABELS.get(mech, mech),
                    color=_MECH_COLORS.get(mech),
                    linewidth=1.8)
    ax.set_xlabel("Season")
    ax.set_ylabel("Skill range (max - min)")
    ax.set_title("Competitive spread of team skills over seasons")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    _save(fig, "skill_spread.png")
    plt.close(fig)


def plot_pick_distribution_bars(conn: sqlite3.Connection, runs: list[dict]) -> None:
    plt = _mpl()
    if plt is None:
        return

    mechs_in_runs = list(dict.fromkeys(r["mechanism"] for r in runs))
    n_mechs = len(mechs_in_runs)
    fig, axes = plt.subplots(1, n_mechs, figsize=(4 * n_mechs, 4.5), sharey=True)
    if n_mechs == 1:
        axes = [axes]

    for ax, mech in zip(axes, mechs_in_runs):
        mech_runs = [r for r in runs if r["mechanism"] == mech]
        # Aggregate pick distributions across runs for this mechanism
        q_totals = {q: [] for q in [1, 2, 3, 4]}
        for run in mech_runs:
            pd = pick_distribution(conn, run["run_id"])
            for q in [1, 2, 3, 4]:
                if q in pd:
                    q_totals[q].append(pd[q]["avg_pick"])
        avg_picks = [
            sum(q_totals[q]) / len(q_totals[q]) if q_totals[q] else float("nan")
            for q in [1, 2, 3, 4]
        ]
        bars = ax.bar(["Q1\n(worst)", "Q2", "Q3", "Q4\n(best)"], avg_picks,
                      color=_MECH_COLORS.get(mech, "#999"),
                      edgecolor="white", linewidth=0.5)
        ax.set_title(_MECH_LABELS.get(mech, mech))
        ax.set_ylabel("Avg draft pick (lower = better)" if ax is axes[0] else "")
        ax.invert_yaxis()
        ax.grid(axis="y", alpha=0.3)
        for bar, val in zip(bars, avg_picks):
            if val == val:
                ax.text(bar.get_x() + bar.get_width() / 2, val + 0.3,
                        f"{val:.1f}", ha="center", va="top", fontsize=9)

    fig.suptitle("Average draft pick received by initial-skill quartile", y=1.02)
    _save(fig, "pick_distribution_bars.png")
    plt.close(fig)


def plot_mixed_sweep(conn: sqlite3.Connection) -> None:
    """Tanking rate vs number of rational agents (NBA Lottery, pv=50)."""
    plt = _mpl()
    if plt is None:
        return

    rows = conn.execute(
        "SELECT run_id, params FROM runs WHERE agent_type='mixed' ORDER BY created_at"
    ).fetchall()
    if not rows:
        print("  No mixed-agent runs found; skipping mixed-sweep plot.")
        return

    data: list[tuple[int, float]] = []
    for run_id, params_str in rows:
        params = json.loads(params_str)
        n_rat = params.get("n_rational", 0)
        ts = tanking_stats(conn, run_id)
        data.append((n_rat, ts["tanking_rate"]))

    data.sort()
    xs = [d[0] for d in data]
    ys = [d[1] for d in data]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(xs, ys, "o-", color=_MECH_COLORS["nba_lottery"], linewidth=2, markersize=7)
    ax.set_xlabel("Number of rational agents (out of 30)")
    ax.set_ylabel("Average tanking rate")
    ax.set_title("Tanking rate vs proportion of rational agents\n(NBA Lottery, playoff value = 50)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.set_ylim(0, max(ys) * 1.2 if ys else 1)
    ax.grid(axis="y", alpha=0.3)
    _save(fig, "mixed_population_sweep.png")
    plt.close(fig)


def plot_playoff_value_sweep(conn: sqlite3.Connection) -> None:
    """Tanking rate vs playoff value (NBA Lottery, all-rational agents)."""
    plt = _mpl()
    if plt is None:
        return

    rows = conn.execute(
        """SELECT run_id, params FROM runs
           WHERE mechanism='nba_lottery' AND agent_type='rational'
           ORDER BY created_at"""
    ).fetchall()
    if not rows:
        print("  No playoff-value sweep runs found; skipping plot.")
        return

    # Keep only runs where the label suggests a pv-sweep (have varying playoff_value)
    data: list[tuple[float, float]] = []
    seen_pvs: set = set()
    for run_id, params_str in rows:
        params = json.loads(params_str)
        pv = params.get("playoff_value", 50.0)
        if pv in seen_pvs:
            continue   # take first occurrence per pv level
        seen_pvs.add(pv)
        ts = tanking_stats(conn, run_id)
        data.append((pv, ts["tanking_rate"]))

    data.sort()
    if len(data) < 2:
        print("  Need >= 2 distinct playoff values for sweep plot; skipping.")
        return

    xs = [d[0] for d in data]
    ys = [d[1] for d in data]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(xs, ys, "o-", color=_MECH_COLORS["nba_lottery"], linewidth=2, markersize=7)
    ax.set_xlabel("Playoff value (utils)")
    ax.set_ylabel("Average tanking rate")
    ax.set_title("Tanking rate sensitivity to playoff value\n(NBA Lottery, all-rational agents)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.set_ylim(0, max(ys) * 1.2 if ys else 1)
    ax.grid(axis="y", alpha=0.3)
    _save(fig, "playoff_value_sweep.png")
    plt.close(fig)


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze tanking simulation results")
    parser.add_argument("--db", default="tanking_sim.db")
    parser.add_argument("--run-ids", nargs="*", help="Specific run IDs to analyze")
    parser.add_argument("--plot", action="store_true", help="Generate matplotlib plots")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        print("Run main.py first to generate simulation data.")
        return

    conn = sqlite3.connect(args.db)
    runs = load_runs(conn, args.run_ids)

    if not runs:
        print("No runs found in database.")
        return

    print(f"\nFound {len(runs)} run(s) in {args.db}")
    print_summary_table(conn, runs)
    print_mechanism_comparison(conn, runs)
    print_pick_distribution(conn, runs)
    print_skill_evolution(conn, runs)

    if args.plot:
        print("\nGenerating plots...")
        # Per-mechanism time-series plots: one run per mechanism at default params
        # (rational, all 30 rational, playoff_value=50). This excludes sweep runs.
        seen_mechs: set[str] = set()
        standard_runs = []
        for r in sorted(runs, key=lambda r: -r["n_seasons"]):
            params = json.loads(r["params"])
            if (
                r["agent_type"] == "rational"
                and params.get("n_rational", 30) == 30
                and params.get("playoff_value", 50.0) == 50.0
                and r["mechanism"] not in seen_mechs
            ):
                seen_mechs.add(r["mechanism"])
                standard_runs.append(r)
        if standard_runs:
            plot_tanking_over_seasons(conn, standard_runs)
            plot_tau_over_seasons(conn, standard_runs)
            plot_skill_spread(conn, standard_runs)
            plot_pick_distribution_bars(conn, standard_runs)
        else:
            plot_tanking_over_seasons(conn, runs)
            plot_tau_over_seasons(conn, runs)
            plot_skill_spread(conn, runs)
            plot_pick_distribution_bars(conn, runs)

        # Experiment-specific aggregate plots (read all matching runs from DB)
        plot_mixed_sweep(conn)
        plot_playoff_value_sweep(conn)

    conn.close()


if __name__ == "__main__":
    main()
