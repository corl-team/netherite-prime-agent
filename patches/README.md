# Engine-side changes this bridge needs

netherite carries **no license** (all rights reserved upstream), so this
repository ships no engine code and no diff of it - only a description of the
three changes to make in your own checkout, and why.

Send them upstream rather than keeping a fork if you can.

### 1. `health` and `food` in the JSON observation

`magma/game/rl_mode.c`, in the JSON branch of the obs emitter: add the player's
health and food next to `dead`, from the same `GmPlayerView` the line already
holds. The binary (`--rl-bin`) layout must stay frozen - the fidelity gate
depends on it.

**Why:** without them an agent cannot see itself dying. The runtime stops
ticking the moment health hits zero, so from the model's side the episode just
ends with no reason it can observe. The field exists for a coal-mining RL task
where the agent never dies.

### 2. Raise the cutout draw-buffer cap

`CR_DEF_DRAW_CUTOUT` in `magma/game/caps.h` (and the matching `draw_cutout` in
`magma/magma.conf`): 262144 -> 1048576.

**Why:** digging straight up through a tree canopy exposes every interior leaf
face at once. Measured 263,916 verts against the 262,144 cap, which aborts the
process in `world_live.c`. Costs about 31 MB more at 40 B/vert. Reproduce the
old behaviour by pointing `MAGMA_CONF` at a conf with the old value.

### 3. Fix `magma/game/test_world_live.sh`

Add the repository root to its include path. The test includes
`verify/chunk_scene.h`, which moved to the top level in the java/blaze/magma/
verify restructure, so the test had stopped compiling entirely.
