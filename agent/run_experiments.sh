#!/usr/bin/env bash
# Everything the write-up needs, run once, sequentially (the runs share one
# model endpoint - two at a time only make both slower).
#
#   bash agent/run_experiments.sh [OUTDIR]
#
# A. seed 0 with Prime Agent's own refine skill available: does the model ever
#    reach for it when it can, and does the harness state differ?
# B. seed 7, same goal: is any of this seed-0 memorisation?
# C. three learning episodes: does the workspace the agent writes for itself
#    actually compound?
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-/tmp/netherite-agent/experiments}"
GOAL="Craft a stone pickaxe, then mine coal, craft torches and place at least one torch."
mkdir -p "$OUT"

stamp() { date +%H:%M:%S; }

echo "[$(stamp)] A: seed 0, refine available"
SEED=0 FRAMES="$OUT/A_seed0_refine" GOAL="$GOAL" bash "$DIR/play.sh" > "$OUT/A.log" 2>&1 || true
echo "[$(stamp)] A done"

echo "[$(stamp)] B: seed 7, unseen world"
SEED=7 FRAMES="$OUT/B_seed7" GOAL="$GOAL" bash "$DIR/play.sh" > "$OUT/B.log" 2>&1 || true
echo "[$(stamp)] B done"

echo "[$(stamp)] C: 3 learning episodes from an empty workspace"
rm -rf "$DIR/workspace"          # C measures compounding from zero, not from A/B
SEED=0 GOAL="$GOAL" bash "$DIR/learn.sh" 3 > "$OUT/C.log" 2>&1 || true
echo "[$(stamp)] C done"

{
  echo "# Experiment log"
  echo
  for x in A B; do
    echo "## $x"
    tail -25 "$OUT/$x.log"
    echo
  done
  echo "## C (3 episodes)"
  grep -E "^=== episode" "$OUT/C.log" || true
  wc -l "$DIR/workspace"/* 2>/dev/null || true
} > "$OUT/SUMMARY.md"
echo "[$(stamp)] summary -> $OUT/SUMMARY.md"
