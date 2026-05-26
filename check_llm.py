import sqlite3, statistics

conn = sqlite3.connect("tanking_sim.db")

# LLM run summary
print("=== LLM RUNS ===")
runs = conn.execute("""
    SELECT run_id, mechanism, agent_type, n_seasons FROM runs
    WHERE agent_type='llm' ORDER BY created_at
""").fetchall()
for r in runs:
    print(f"  {r[0]}  mech={r[1]}  seasons={r[3]}")

print()
print("=== LLM TANKING RATE ===")
for run_id, mech, agent_type, n_seasons in runs:
    decisions = conn.execute("""
        SELECT season,
               SUM(CASE WHEN effort_chosen < 0.5 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as tank_rate
        FROM agent_decisions WHERE run_id=? GROUP BY season
    """, (run_id,)).fetchall()
    if decisions:
        rates = [r[1] for r in decisions]
        print(f"  {mech}: avg tanking = {statistics.mean(rates):.1%}  (over {len(rates)} seasons)")
    else:
        print(f"  {mech}: no decisions found")

print()
print("=== SAMPLE LLM REASONING (tanking decisions only) ===")
samples = conn.execute("""
    SELECT team_id, season, checkpoint, effort_chosen, reasoning
    FROM agent_decisions
    WHERE agent_type='LLMAgent' AND effort_chosen < 0.5
    ORDER BY RANDOM() LIMIT 5
""").fetchall()
for s in samples:
    print(f"  team={s[0]} s={s[1]} ck={s[2]} e={s[3]:.2f}: {s[4][:120]}")

print()
print("=== SAMPLE LLM REASONING (full effort decisions) ===")
samples2 = conn.execute("""
    SELECT team_id, season, checkpoint, effort_chosen, reasoning
    FROM agent_decisions
    WHERE agent_type='LLMAgent' AND effort_chosen >= 0.9
    ORDER BY RANDOM() LIMIT 3
""").fetchall()
for s in samples2:
    print(f"  team={s[0]} s={s[1]} ck={s[2]} e={s[3]:.2f}: {s[4][:120]}")

conn.close()
