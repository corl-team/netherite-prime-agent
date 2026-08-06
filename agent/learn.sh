#!/usr/bin/env bash
# Run N episodes of netherite, letting the agent build and keep its own harness.
#
#   bash agent/learn.sh 5                     # 5 episodes, default goal
#   GOAL="reach iron" SEED=7 bash agent/learn.sh 3
#
# Each episode is a FRESH agent session with no memory of the last one - the
# only thing that carries over is what it chose to write into its workspace:
#
#   agent/workspace/NOTES.md   what it learned about this world
#   agent/workspace/tools.py   the helpers it wrote for itself
#
# It gets mcbridge.py (raw one-tick protocol) and nothing else: no context
# files, no discovered skills, no macros from us. Everything above a single
# tick is its own.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EPISODES="${1:-3}"
SEED="${SEED:-0}"
WS="$DIR/workspace"
GOAL="${GOAL:-Get from an empty inventory to a stone pickaxe, then mine coal and craft torches.}"

command -v prime-agent >/dev/null || { echo "prime-agent not on PATH"; exit 1; }
[ -x "$DIR/../magma/magma_game" ] || make -C "$DIR/../magma" game
mkdir -p "$WS"
[ -f "$WS/NOTES.md" ] || printf '# What I know about netherite\n\n(nothing yet)\n' > "$WS/NOTES.md"
[ -f "$WS/tools.py" ] || printf '"""My helpers. Empty until I write some."""\n' > "$WS/tools.py"

# -nc/-ns/-ne make the run reproducible: no context files, no discovered
# skills or extensions, so the player starts from PLAY.md and nothing else.
# Prime Agent's own two skills are loaded back explicitly - refine drives its
# continual harness, attach-image is its vision path.
PA_BIN="$(readlink -f "$(command -v prime-agent)")"
PA_SKILLS="$(cd "$(dirname "$PA_BIN")/../../skills" 2>/dev/null && pwd)"
SKILLS=""
[ -d "$PA_SKILLS" ] && SKILLS="--skill $PA_SKILLS/refine --skill $PA_SKILLS/attach-image"

for i in $(seq 1 "$EPISODES"); do
  FRAMES="/tmp/netherite-agent/learn/ep$i"
  mkdir -p "$FRAMES"
  echo "=== episode $i/$EPISODES  seed $SEED  frames -> $FRAMES ==="
  prime-agent --cwd "$DIR" -nc -ns -ne $SKILLS -p "$(cat <<EOF
This is episode $i of $EPISODES in the same world (seed $SEED). You keep no
memory between episodes except two files you own and maintain:

  workspace/NOTES.md   everything you have figured out about this world
  workspace/tools.py   the helper functions you have written for yourself

Start by reading BOTH, plus mcbridge.py (the raw protocol - one action dict in,
one observation out, one game tick each call). We wrote the transport; every
abstraction above a single tick is yours to invent, and yours to fix when it
turns out to be wrong.

    import sys; sys.path.insert(0, "$DIR"); sys.path.insert(0, "$WS")
    from mcbridge import Bridge, EpisodeOver
    import tools                       # your own module, reload it as you edit
    b = Bridge(seed=$SEED, frames_dir="$FRAMES")

Goal this episode: $GOAL

Rules that make this worth doing:
- Verify every claim against the observation. An action that "should" have
  worked and an inventory that did not change means it did not work.
- b.show() puts the rendered frame into your context when text is not enough.
- When a helper in tools.py misbehaves, fix tools.py - do not work around it
  in a throwaway cell. The next episode only inherits what is in those files.
- Before you finish, update NOTES.md (what is true about this world, what
  failed and why) and tools.py (helpers that earned their place). Write them
  for a reader who has never played this world and cannot see this session.

Finish with a short report: what you achieved, what you changed in your own
harness, and what you still do not understand.
EOF
)" 2>&1 | tee "$FRAMES/report.txt"
done

echo "=== workspace after $EPISODES episodes ==="
wc -l "$WS"/*.md "$WS"/*.py
