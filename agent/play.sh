#!/usr/bin/env bash
# Hand netherite to a local LLM agent and let it play.
#
#   bash agent/play.sh                       # default goal, seed 0
#   GOAL="mine coal and craft torches" SEED=7 bash agent/play.sh
#
# The agent talks to magma_game through agent/mcagent.py (see PLAY.md). Frames
# land in $FRAMES; agent/make_clip.sh turns them into an mp4.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED="${SEED:-0}"
FRAMES="${FRAMES:-/tmp/netherite-agent/seed$SEED}"
GOAL="${GOAL:-Get 4 logs, craft planks, sticks and a crafting table, place the table, and craft a wooden pickaxe. Then mine cobblestone and craft a stone pickaxe.}"

command -v prime-agent >/dev/null || { echo "prime-agent not on PATH"; exit 1; }
[ -x "$DIR/../magma/magma_game" ] || make -C "$DIR/../magma" game

mkdir -p "$FRAMES"
echo "=== seed $SEED  frames -> $FRAMES ==="

# -nc/-ns/-ne make the run reproducible: no context files, no discovered
# skills or extensions, so the player starts from PLAY.md and nothing else.
# Prime Agent's own two skills are loaded back explicitly - refine drives its
# continual harness, attach-image is its vision path.
PA_BIN="$(readlink -f "$(command -v prime-agent)")"
PA_SKILLS="$(cd "$(dirname "$PA_BIN")/../../skills" 2>/dev/null && pwd)"
SKILLS=""
[ -d "$PA_SKILLS" ] && SKILLS="--skill $PA_SKILLS/refine --skill $PA_SKILLS/attach-image"
prime-agent --cwd "$DIR" -nc -ns -ne $SKILLS -p "$(cat <<EOF
Read PLAY.md, then play. Use the ipython tool and keep ONE Game object alive
across cells:

    import sys; sys.path.insert(0, "$DIR")
    from mcagent import Game
    g = Game(seed=$SEED, frames_dir="$FRAMES")

Goal: $GOAL

Check g.inv() after every step - claiming a step worked without the inventory
backing it up is the one failure mode that matters here. Call g.screenshot()
and attach_image() when you want to actually look at the world. Finish with a
short report: what worked, what the world refused to let you do, and anything
that contradicted your Minecraft intuition.
EOF
)"
