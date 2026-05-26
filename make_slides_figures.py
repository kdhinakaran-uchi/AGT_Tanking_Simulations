"""
Generate all slide deck figures with consistent colors and labeling.
Output goes to figures/ directory as high-res PNGs.
"""

import sqlite3
import statistics
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

Path("figures").mkdir(exist_ok=True)

# ── Consistent style ──────────────────────────────────────────────────────────

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 13,
    "axes.titlesize": 15,
    "axes.titleweight": "bold",
    "axes.labelsize": 13,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
    "legend.fontsize": 11,
    "figure.dpi": 150,
})

COLORS = {
    "nba_lottery":          "#E63946",   # red
    "bilevel":              "#2196F3",   # blue
    "cola":                 "#4CAF50",   # green
    "weighted_loss_exp_hl20": "#FF9800", # orange
    "nba_321_lottery":      "#9C27B0",   # purple
    "llm":                  "#795548",   # brown
    "honest":               "#9E9E9E",   # gray
    "rational":             "#37474F",   # dark slate (accent)
}

MECH_KEYS  = ["nba_lottery", "bilevel", "cola", "weighted_loss_exp_hl20", "nba_321_lottery"]
MECH_LABEL = {
    "nba_lottery":            "NBA Lottery\n(2019)",
    "bilevel":                "Bilevel",
    "cola":                   "COLA",
    "weighted_loss_exp_hl20": "Weighted Loss\n(exp, t½=20)",
    "nba_321_lottery":        "NBA 3-2-1",
}
MECH_LABEL_SHORT = {
    "nba_lottery":            "NBA 2019",
    "bilevel":                "Bilevel",
    "cola":                   "COLA",
    "weighted_loss_exp_hl20": "Wt. Loss",
    "nba_321_lottery":        "3-2-1",
}

PICK_VALUES = {1:100,2:65,3:45,4:30,5:22,6:17,7:13,8:10,9:8,10:7,11:6,12:5,13:4,14:3}

# ── DB helpers ────────────────────────────────────────────────────────────────

conn = sqlite3.connect("tanking_sim.db")

# Rational runs — pv=200, probabilistic playoff EU, all bugs fixed
RATIONAL_RUNS = {
    "nba_lottery":            "nba_lottery_rational_8c11ac3f",
    "bilevel":                "bilevel_rational_3feb71d2",
    "cola":                   "cola_rational_2d65e52d",
    "weighted_loss_exp_hl20": "weighted_loss_exp_hl20_rational_58f128e9",
    "nba_321_lottery":        "nba_321_lottery_rational_67a0392d",
}
HONEST_RUNS = {
    "nba_lottery":            "nba_lottery_honest_f9f55233",
    "bilevel":                "bilevel_honest_192a6c28",
    "cola":                   "cola_honest_2d85b14f",
    "weighted_loss_exp_hl20": "weighted_loss_exp_hl20_honest_9ca2e02f",
    "nba_321_lottery":        "nba_321_lottery_honest_a7d23d4d",
}
# LLM run — fixed prompt (pv=200, per-team games_completed, DECISION RULES)
LLM_RUN = "nba_lottery_llm_3c7b7da2"

# Mixed-population sweep — pv=200, probabilistic playoff EU, all bugs fixed
MIXED_RUNS = {
    0:  "nba_lottery_mixed_0rational_1e0c57",
    1:  "nba_lottery_mixed_1rational_a9d7ab",
    5:  "nba_lottery_mixed_5rational_1de479",
    15: "nba_lottery_mixed_15rational_e4d95b",
    30: "nba_lottery_mixed_30rational_f8fef1",
}
# Playoff-value sensitivity sweep — pv=200 probabilistic EU baseline
PV_RUNS = {
    50:  "nba_lottery_pv50_5c9351",
    100: "nba_lottery_pv100_8955c9",
    150: "nba_lottery_pv150_5e65d4",
    200: "nba_lottery_pv200_9f4ccc",
    300: "nba_lottery_pv300_1a46d7",
}


def tanking_rate(run_id):
    r = conn.execute(
        "SELECT SUM(CASE WHEN effort_chosen<0.5 THEN 1 ELSE 0 END)*1.0/COUNT(*) "
        "FROM agent_decisions WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    return r or 0.0


def avg_tau(run_id):
    """Kendall tau between true_skill rank and win rank, averaged over seasons."""
    taus = []
    seasons = conn.execute(
        "SELECT DISTINCT season FROM draft_results WHERE run_id=?", (run_id,)
    ).fetchall()
    for (s,) in seasons:
        dr = conn.execute(
            "SELECT team_id, final_wins FROM draft_results WHERE run_id=? AND season=? "
            "ORDER BY final_wins DESC, team_id", (run_id, s)
        ).fetchall()
        sh = conn.execute(
            "SELECT team_id, true_skill FROM skill_history WHERE run_id=? AND season=? "
            "ORDER BY true_skill DESC, team_id", (run_id, s)
        ).fetchall()
        if len(dr) != 30 or len(sh) != 30:
            continue
        final_rank = [r[0] for r in dr]
        skill_rank = [r[0] for r in sh]
        pos = {v: i for i, v in enumerate(final_rank)}
        n = len(skill_rank)
        disc = sum(1 for i in range(n) for j in range(i+1,n) if pos[skill_rank[i]] > pos[skill_rank[j]])
        taus.append(disc / (n*(n-1)//2))
    return statistics.mean(taus) if taus else 0.0


def save(name):
    plt.tight_layout()
    plt.savefig(f"figures/{name}.png", bbox_inches="tight")
    plt.close()
    print(f"  saved figures/{name}.png")


# ══════════════════════════════════════════════════════════════════════════════
# Fig 1 — Tanking rate by mechanism (rational + LLM + honest)
# ══════════════════════════════════════════════════════════════════════════════

print("Fig 1: Tanking rate by mechanism...")
rat_rates  = [tanking_rate(RATIONAL_RUNS[m]) for m in MECH_KEYS]
hon_rates  = [tanking_rate(HONEST_RUNS[m])   for m in MECH_KEYS]
llm_rate   = tanking_rate(LLM_RUN)

x = np.arange(len(MECH_KEYS))
w = 0.28
fig, ax = plt.subplots(figsize=(10, 5.5))

bars_rat = ax.bar(x - w, rat_rates, w, label="Rational agents",
                  color=[COLORS[m] for m in MECH_KEYS], edgecolor="white", linewidth=0.5)
bars_hon = ax.bar(x,      hon_rates, w, label="Honest agents",
                  color=[COLORS[m] for m in MECH_KEYS], alpha=0.35,
                  edgecolor="white", linewidth=0.5, hatch="//")

# LLM bar only for nba_lottery (index 0)
ax.bar(x[0] + w, llm_rate, w, label="LLM agents (NBA only)",
       color=COLORS["llm"], edgecolor="white", linewidth=0.5)

# value labels
for bar in bars_rat:
    h = bar.get_height()
    if h > 0.005:
        ax.text(bar.get_x() + bar.get_width()/2, h + 0.005, f"{h:.1%}",
                ha="center", va="bottom", fontsize=9, fontweight="bold")

ax.text(x[0] + w + w/2, llm_rate + 0.005, f"{llm_rate:.1%}",
        ha="center", va="bottom", fontsize=9, fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels([MECH_LABEL[m] for m in MECH_KEYS])
ax.set_ylabel("Tanking rate (fraction of effort decisions < 0.5)")
ax.set_title("Tanking Rate by Draft Mechanism and Agent Type\n(50 seasons, seed 42)")
ax.set_ylim(0, max(rat_rates + [llm_rate]) * 1.25 + 0.02)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
ax.legend(loc="upper right")
ax.axhline(0, color="black", linewidth=0.5)
save("fig1_tanking_by_mechanism")


# ══════════════════════════════════════════════════════════════════════════════
# Fig 2 — Kendall tau distance by mechanism
# ══════════════════════════════════════════════════════════════════════════════

print("Fig 2: Kendall tau by mechanism...")
rat_taus = [avg_tau(RATIONAL_RUNS[m]) for m in MECH_KEYS]
hon_taus = [avg_tau(HONEST_RUNS[m])   for m in MECH_KEYS]

fig, ax = plt.subplots(figsize=(10, 5.5))
w = 0.35
ax.bar(x - w/2, rat_taus, w, label="Rational agents",
       color=[COLORS[m] for m in MECH_KEYS], edgecolor="white", linewidth=0.5)
ax.bar(x + w/2, hon_taus, w, label="Honest agents",
       color=[COLORS[m] for m in MECH_KEYS], alpha=0.35,
       edgecolor="white", linewidth=0.5, hatch="//")

for i, (rv, hv) in enumerate(zip(rat_taus, hon_taus)):
    ax.text(i - w/2, rv + 0.002, f"{rv:.3f}", ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.text(i + w/2, hv + 0.002, f"{hv:.3f}", ha="center", va="bottom", fontsize=9)

ax.set_xticks(x)
ax.set_xticklabels([MECH_LABEL[m] for m in MECH_KEYS])
ax.set_ylabel("Mean Kendall tau distance (0 = perfect skill alignment)")
ax.set_title("Competitive Balance by Mechanism\n(Kendall tau: final standings vs. true skill ranking)")
lo = min(min(rat_taus), min(hon_taus))
hi = max(max(rat_taus), max(hon_taus))
ax.set_ylim(max(0, lo - 0.02), hi + 0.02)
ax.legend(loc="upper left")
save("fig2_tau_by_mechanism")


# ══════════════════════════════════════════════════════════════════════════════
# Fig 3 — Tanking rate by number of rational agents (mixed sweep)
# ══════════════════════════════════════════════════════════════════════════════

print("Fig 3: Mixed population sweep...")
n_rats = sorted(MIXED_RUNS.keys())
mixed_rates = [tanking_rate(MIXED_RUNS[n]) for n in n_rats]

fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(n_rats, [r*100 for r in mixed_rates], "o-",
        color=COLORS["nba_lottery"], linewidth=2.5, markersize=8, markerfacecolor="white",
        markeredgewidth=2)

for n, r in zip(n_rats, mixed_rates):
    ax.annotate(f"{r:.1%}", (n, r*100), textcoords="offset points",
                xytext=(0, 10), ha="center", fontsize=10, fontweight="bold")

ax.set_xlabel("Number of rational agents (out of 30 teams)")
ax.set_ylabel("Aggregate tanking rate (%)")
ax.set_title("Contagion Effect: How Many Rational Agents Does It Take?\n(NBA Lottery, 50 seasons)")
ax.set_xticks(n_rats)
ax.set_xticklabels([str(n) for n in n_rats])
ax.set_ylim(-1, 20)
ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")

# annotation
ax.annotate("1 rational agent\nraises tanking to 0.4%",
            xy=(1, 0.4), xytext=(4, 3),
            arrowprops=dict(arrowstyle="->", color="gray"),
            fontsize=10, color="gray")
save("fig3_mixed_sweep")


# ══════════════════════════════════════════════════════════════════════════════
# Fig 4 — Tanking rate by playoff value (sensitivity sweep)
# ══════════════════════════════════════════════════════════════════════════════

print("Fig 4: Playoff value sensitivity...")
pv_vals  = sorted(PV_RUNS.keys())
pv_rates = [tanking_rate(PV_RUNS[v]) * 100 for v in pv_vals]

fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(pv_vals, pv_rates, "s-",
        color=COLORS["nba_lottery"], linewidth=2.5, markersize=8,
        markerfacecolor="white", markeredgewidth=2)

for v, r in zip(pv_vals, pv_rates):
    ax.annotate(f"{r:.1f}%", (v, r), textcoords="offset points",
                xytext=(0, 10), ha="center", fontsize=10, fontweight="bold")

ax.axvline(200, color="gray", linewidth=1, linestyle="--", alpha=0.7)
ax.text(205, max(pv_rates)*0.75, "Baseline V = 200", fontsize=9, color="gray")

ax.set_xlabel("Playoff value V (points)")
ax.set_ylabel("Tanking rate (%)")
ax.set_title("Tanking Rate vs. Playoff Value\n(NBA Lottery, rational agents, 50 seasons; pick values held fixed)")
ax.set_ylim(0, 55)
ax.set_xticks(pv_vals)
save("fig4_playoff_value_sweep")


# ══════════════════════════════════════════════════════════════════════════════
# Fig 5 — Draft pick value schedule (why the incentive exists)
# ══════════════════════════════════════════════════════════════════════════════

print("Fig 5: Draft pick value schedule...")
picks = list(PICK_VALUES.keys())
vals  = list(PICK_VALUES.values())

fig, ax = plt.subplots(figsize=(8, 5))
bar_colors = [COLORS["nba_lottery"] if i < 3 else
              "#78909C" if i < 6 else "#B0BEC5" for i in range(len(picks))]
ax.bar(picks, vals, color=bar_colors, edgecolor="white", linewidth=0.5)

for p, v in zip(picks, vals):
    ax.text(p, v + 1.5, str(v), ha="center", va="bottom", fontsize=9, fontweight="bold")

ax.axhline(200, color=COLORS["bilevel"], linewidth=1.5, linestyle="--", alpha=0.8)
ax.text(14.6, 201, "Playoff value\nV = 200", fontsize=9, color=COLORS["bilevel"], va="bottom")

ax.set_xlabel("Draft pick number")
ax.set_ylabel("Pick value D(k) (points)")
ax.set_title("Draft Pick Value Schedule vs. Playoff Value\n(Expected lottery value must beat V=200 to justify tanking)")
ax.set_xticks(picks)
ax.set_xlim(0.3, 15)
ax.set_ylim(0, 230)

legend_patches = [
    mpatches.Patch(color=COLORS["nba_lottery"], label="Picks 1–3 (highest face value)"),
    mpatches.Patch(color="#78909C", label="Picks 4–6"),
    mpatches.Patch(color="#B0BEC5", label="Picks 7–14"),
]
ax.legend(handles=legend_patches, loc="upper right")
save("fig5_pick_value_schedule")


# ══════════════════════════════════════════════════════════════════════════════
# Fig 6 — Tanking rate by draft pick value (sensitivity: vary max pick value)
# ══════════════════════════════════════════════════════════════════════════════

print("Fig 6: Tanking rate vs. expected draft value (theoretical)...")
# We compute: for the NBA lottery rational run, at each checkpoint what is
# the team's expected pick value given their current rank?
# Plot mean tanking rate by expected pick value bracket.

decisions = conn.execute("""
    SELECT ad.rank, ad.effort_chosen, sh.true_skill
    FROM agent_decisions ad
    JOIN skill_history sh ON sh.run_id=ad.run_id AND sh.season=ad.season AND sh.team_id=ad.team_id
    WHERE ad.run_id=?
""", (RATIONAL_RUNS["nba_lottery"],)).fetchall()

# Group by lottery rank (only non-playoff = rank 15–30 maps to lottery rank 1–14 by worst record)
# rank=30 is worst. lottery rank 1 = rank 30, lottery rank 14 = rank 17
rank_data = {}
for rank, effort, skill in decisions:
    if rank <= 16:  # playoff teams — skip
        continue
    lottery_rank = rank - 16  # 1 (best lottery) to 14 (worst)
    if lottery_rank not in rank_data:
        rank_data[lottery_rank] = []
    rank_data[lottery_rank].append(effort < 0.5)

# Expected pick value under NBA lottery for each lottery rank
# Approximate using simple weight proportions
weights = [140,140,140,125,105,90,75,60,45,30,20,15,10,5]
total_w = sum(weights)
# P(pick 1) = w_rank / total for simplified view; use pick values directly
nba_ev = []
for lottery_rank in range(1, 15):
    w = weights[lottery_rank - 1]
    # Very rough EV: weighted average using weight share × pick values
    ev = sum((weights[i]/total_w) * PICK_VALUES[i+1] for i in range(14))
    # Better: use weight to pick #1 for ordering proxy
    nba_ev.append(w / total_w * PICK_VALUES[1])

lr_vals   = sorted(rank_data.keys())
tank_by_lr = [statistics.mean(rank_data[lr])*100 if rank_data.get(lr) else 0 for lr in lr_vals]
# Expected draft value proxy: worse lottery rank (higher number) = lower weight = lower EV
# Invert so x-axis = "how good is your expected draft position?"

fig, ax = plt.subplots(figsize=(8, 5))
ax.bar(lr_vals, tank_by_lr, color=COLORS["nba_lottery"], alpha=0.8, edgecolor="white")
ax.set_xlabel("Lottery rank (1 = best lottery team, 14 = worst record / highest odds)")
ax.set_ylabel("Tanking rate (%)")
ax.set_title("Where Does Tanking Happen?\nTanking Rate by Lottery Standing\n(NBA Lottery, rational agents, 50 seasons)")
ax.set_xticks(lr_vals)
ax.set_xticklabels([str(lr) for lr in lr_vals])

# Annotate playoff bubble
ax.axvline(1.5, color="gray", linewidth=1, linestyle="--", alpha=0.6)
ax.text(1.6, max(tank_by_lr)*0.85, "← Better record\n(near bubble)", fontsize=9, color="gray")
save("fig6_tanking_by_lottery_rank")


# ══════════════════════════════════════════════════════════════════════════════
# Fig 7 — Summary comparison: tanking rate + tau on same axes (dual axis)
# ══════════════════════════════════════════════════════════════════════════════

print("Fig 7: Summary dual-axis chart...")
rat_rates_pct = [r * 100 for r in rat_rates]

fig, ax1 = plt.subplots(figsize=(10, 5.5))
ax2 = ax1.twinx()

w = 0.4
bars = ax1.bar(x - w/4, rat_rates_pct, w, color=[COLORS[m] for m in MECH_KEYS],
               label="Tanking rate (left axis)", alpha=0.85, edgecolor="white")
ax2.plot(x + w/4, rat_taus, "D--", color=COLORS["rational"],
         linewidth=2, markersize=9, label="Tau distance (right axis)", zorder=5)

for bar, r in zip(bars, rat_rates_pct):
    if r > 0.5:
        ax1.text(bar.get_x() + bar.get_width()/2, r + 0.3, f"{r:.1f}%",
                 ha="center", va="bottom", fontsize=9, fontweight="bold")

for i, t in enumerate(rat_taus):
    ax2.text(i + w/4, t + 0.001, f"{t:.3f}", ha="center", va="bottom",
             fontsize=9, color=COLORS["rational"], fontweight="bold")

ax1.set_xticks(x)
ax1.set_xticklabels([MECH_LABEL_SHORT[m] for m in MECH_KEYS], fontsize=12)
ax1.set_ylabel("Tanking rate (%)", color=COLORS["nba_lottery"])
ax1.tick_params(axis="y", labelcolor=COLORS["nba_lottery"])
ax1.set_ylim(0, 22)

ax2.set_ylabel("Kendall tau distance (lower = better skill alignment)", color=COLORS["rational"])
ax2.tick_params(axis="y", labelcolor=COLORS["rational"])
ax2.set_ylim(0.36, 0.42)

ax1.set_title("Tanking Rate and Competitive Balance by Mechanism\n(Rational agents, 50 seasons)")

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
save("fig7_summary_dual_axis")


# ══════════════════════════════════════════════════════════════════════════════
# Finish
# ══════════════════════════════════════════════════════════════════════════════

conn.close()
print("\nAll figures saved to figures/")
print("Files:")
for f in sorted(Path("figures").glob("fig*.png")):
    print(f"  {f.name}")
