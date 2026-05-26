"""
LLM agent sweep: run all 5 draft mechanisms with 5 seasons each.

Usage:
  $env:ANTHROPIC_API_KEY = "sk-ant-..."
  python run_llm_sweep.py

Writes run IDs to llm_sweep_run_ids.txt when done.
Estimated time: 45-90 min wall-clock, ~5,250 API calls, ~$10-20.
"""

import os
import time
import uuid
from pathlib import Path

from mechanisms.nba_lottery import NBALottery
from mechanisms.bilevel import BilevelMechanism
from mechanisms.cola import COLAMechanism
from mechanisms.weighted_loss import WeightedLossMechanism, exponential_decay
from mechanisms.nba_321_lottery import NBAThreeTwoOneLottery
from data.db import Database
from data.export import export_run
from main import run_experiment, _print_header

if not os.environ.get("ANTHROPIC_API_KEY"):
    raise SystemExit("Set ANTHROPIC_API_KEY before running.")

# ── Config ────────────────────────────────────────────────────────────────────

SEASONS  = 5
SEED     = 42
DB_PATH  = "tanking_sim.db"
OUT_DIR  = "results"

# checkpoint_interval=154 schedule-games ≈ 7 decisions per team per season
# Matches the existing NBA Lottery LLM baseline run.
CHECKPOINT_INTERVAL = 154

MECHANISMS = [
    ("nba_lottery",            NBALottery()),
    ("bilevel",                BilevelMechanism()),
    ("cola",                   COLAMechanism()),
    ("weighted_loss_exp_hl20", WeightedLossMechanism(exponential_decay(20.0), "exp_hl20")),
    ("nba_321_lottery",        NBAThreeTwoOneLottery()),
]

# ── Run ───────────────────────────────────────────────────────────────────────

Path(OUT_DIR).mkdir(exist_ok=True)
db = Database(DB_PATH)
run_ids: dict[str, str] = {}
t_total = time.time()

for key, mech in MECHANISMS:
    label = f"{mech.name}_llm5_{uuid.uuid4().hex[:8]}"
    _print_header(mech.name, "llm", SEASONS)
    t0 = time.time()
    rid = run_experiment(
        mech, "llm", SEASONS, db,
        seed=SEED,
        label=label,
        checkpoint_interval=CHECKPOINT_INTERVAL,
    )
    elapsed = time.time() - t0
    run_ids[key] = rid
    print(f"  Completed in {elapsed:.1f}s  |  run_id={rid}")
    export_run(DB_PATH, rid, OUT_DIR)
    # Small pause between mechanisms to avoid hitting rate limits
    if key != MECHANISMS[-1][0]:
        print("  (pausing 5s before next mechanism...)")
        time.sleep(5)

db.close()
total_elapsed = time.time() - t_total
print(f"\nAll 5 mechanisms done in {total_elapsed/60:.1f} min.")

# ── Print update instructions ─────────────────────────────────────────────────

lines = [
    "",
    "=" * 60,
    "Paste these into make_slides_figures.py:",
    "=" * 60,
    "LLM_MECHANISM_RUNS = {",
]
for k, v in run_ids.items():
    lines.append(f'    "{k}": "{v}",')
lines.append("}")
output = "\n".join(lines)
print(output)

# Write to file for easy reference
out_file = Path("llm_sweep_run_ids.txt")
out_file.write_text(output + "\n")
print(f"\nAlso saved to {out_file}")
