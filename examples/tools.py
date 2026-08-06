"""Helpers for the netherite agent (episode 1+).

Conventions verified against seed 0, episode 1:
- yaw: 0 = +Z, 90 = -X, 180 = -Z, 270 = +X (standard Minecraft yaw).
- pitch: 0 = horizontal, positive = DOWN.
- Aiming at a voxel center and holding attack mines that voxel if within reach.
- Blocks id 1 (stone) is too hard for a bare hand; ids 2/3 (grass/dirt) break by hand.
- id 18 (leaves) and id 17 (logs) can be destroyed but do not give inventory items when
  broken by hand in the tested configuration, making normal wood progression impossible
  unless a tool/chest exists.
"""
import math
from collections import Counter

# ----- inventory/craft ids (matches mcbridge) -----
LOG, PLANKS, STICK, COBBLE, TABLE, W_PICK, S_PICK, COAL, TORCH = range(9)

CRAFT_PLANKS, CRAFT_STICKS, CRAFT_TABLE, CRAFT_W_PICK, CRAFT_S_PICK, CRAFT_TORCH, CRAFT_FURNACE, CRAFT_IRON_PICK = range(8)

CRAFT_NAMES = {
    CRAFT_PLANKS: "planks",
    CRAFT_STICKS: "sticks",
    CRAFT_TABLE: "crafting_table",
    CRAFT_W_PICK: "wooden_pickaxe",
    CRAFT_S_PICK: "stone_pickaxe",
    CRAFT_TORCH: "torch",
    CRAFT_FURNACE: "furnace",
    CRAFT_IRON_PICK: "iron_pickaxe",
}

# ----- block ids observed in seed 0 -----
ID_AIR = 0
ID_STONE = 1
ID_GRASS = 2
ID_DIRT = 3
ID_LOG = 17
ID_LEAVES = 18
# ----- additional block ids observed in seed 0 -----
ID_GRASS = 2
ID_DIRT = 3
ID_COBBLESTONE = 4
ID_WATER = 9
ID_SAND = 12
ID_COAL_ORE = 16
ID_SANDSTONE = 24
ID_DEAD_BUSH = 31
ID_WOOL = 35
ID_CHEST = 54
ID_CRAFTING_TABLE = 58
ID_FURNACE_OFF = 61
ID_FURNACE_ON = 62



# ----- helper accessors -----
def inv(obs, idx):
    return obs["inv_counts"][idx]


def pos(obs):
    """(feet_x, feet_y, feet_z)"""
    return obs["x"], obs["y"], obs["z"]


def block_center(bx, by, bz):
    return bx + 0.5, by + 0.5, bz + 0.5


def dist2(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3))


def dist3(a, b):
    return math.sqrt(dist2(a, b))


# ----- geometry verified by movement and camera checks -----
def yaw_to_point(px, pz, tx, tz):
    """Yaw (degrees 0..360) that points from (px,pz) toward (tx,tz).
    0 = +Z, 90 = -X, 180 = -Z, 270 = +X."""
    return math.degrees(-math.atan2(tx - px, tz - pz)) % 360


def pitch_to_point(px, py, pz, tx, ty, tz, eye_height=1.62):
    """Pitch (degrees) to look at world point (tx,ty,tz). 0=horizontal, positive=DOWN."""
    dx = tx - px
    dy = ty - (py + eye_height)
    dz = tz - pz
    h = math.hypot(dx, dz)
    if h == 0:
        return 0.0
    return math.degrees(-math.atan2(dy, h))


def shortest_yaw_delta(cur, target):
    d = (target - cur + 180) % 360 - 180
    return d


def face_action(obs, tx, ty, tz, tol_yaw=2.0, tol_pitch=2.0, max_rate=20.0):
    """Return a one-tick action dict that turns toward (tx,ty,tz), or None if aligned."""
    px, py, pz = pos(obs)
    tyaw = yaw_to_point(px, pz, tx, tz)
    tpitch = pitch_to_point(px, py, pz, tx, ty, tz)
    dyaw = shortest_yaw_delta(obs["yaw"], tyaw)
    dpitch = tpitch - obs["pitch"]
    if abs(dyaw) <= tol_yaw and abs(dpitch) <= tol_pitch:
        return None
    out = {}
    if abs(dyaw) > tol_yaw:
        out["dyaw"] = max(-max_rate, min(max_rate, dyaw))
    if abs(dpitch) > tol_pitch:
        out["dpitch"] = max(-max_rate, min(max_rate, dpitch))
    return out


# ----- voxel map and raycasting -----
def voxel_map(obs):
    """Map block coordinate -> block id from the 256-entry obs['blocks'] list.
    Keeps only the first entry per coordinate (topmost/nearest as reported)."""
    voxels = {}
    for bid, x, y, z in obs["blocks"]:
        voxels[(x, y, z)] = bid
    return voxels


def look_vector(obs, eye_height=1.62):
    """Unit direction the camera is currently facing."""
    yaw = math.radians(obs["yaw"])
    pitch = math.radians(obs["pitch"])
    # yaw 0 = +Z, 90 = -X, 180 = -Z, 270 = +X
    dx = -math.sin(yaw) * math.cos(pitch)
    dy = -math.sin(pitch)
    dz = math.cos(yaw) * math.cos(pitch)
    return dx, dy, dz


def first_block_along_view(obs, max_dist=8.0, eye_height=1.62):
    """Return (block_id, (x,y,z)) of the first block along the current view ray."""
    px, py, pz = pos(obs)
    ey = py + eye_height
    dx, dy, dz = look_vector(obs, eye_height)
    voxels = voxel_map(obs)
    if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
        return None, None
    stepx = 1 if dx > 0 else -1
    stepy = 1 if dy > 0 else -1
    stepz = 1 if dz > 0 else -1
    tdx = abs(1.0 / dx) if dx != 0 else float("inf")
    tdy = abs(1.0 / dy) if dy != 0 else float("inf")
    tdz = abs(1.0 / dz) if dz != 0 else float("inf")

    def next_boundary(coord, step):
        if step > 0:
            return math.floor(coord) + 1 - coord
        else:
            return coord - (math.ceil(coord) - 1)

    tx_n = next_boundary(px, stepx) * tdx if dx != 0 else float("inf")
    ty_n = next_boundary(ey, stepy) * tdy if dy != 0 else float("inf")
    tz_n = next_boundary(pz, stepz) * tdz if dz != 0 else float("inf")
    ix, iy, iz = int(math.floor(px)), int(math.floor(ey)), int(math.floor(pz))
    steps = int(max_dist * 2) + 10
    for _ in range(steps):
        key = (ix, iy, iz)
        if key in voxels:
            return voxels[key], key
        if tx_n < ty_n and tx_n < tz_n:
            ix += stepx
            tx_n += tdx
        elif ty_n < tz_n:
            iy += stepy
            ty_n += tdy
        else:
            iz += stepz
            tz_n += tdz
    return None, None


def nearest_visible(obs, coords, max_dist=8.0, eye_height=1.62):
    """Return list of ((bx,by,bz), distance) for block coordinates whose center is visible
    (first voxel hit on the ray is the target)."""
    px, py, pz = pos(obs)
    ey = py + eye_height
    voxels = voxel_map(obs)
    visible = []
    for bx, by, bz in coords:
        tx, ty, tz = bx + 0.5, by + 0.5, bz + 0.5
        dx, dy, dz = tx - px, ty - ey, tz - pz
        dist = math.hypot(dx, math.hypot(dy, dz))
        if dist > max_dist or dist == 0:
            continue
        stepx = 1 if dx > 0 else -1
        stepy = 1 if dy > 0 else -1
        stepz = 1 if dz > 0 else -1
        tdx = abs(1.0 / dx) if dx != 0 else float("inf")
        tdy = abs(1.0 / dy) if dy != 0 else float("inf")
        tdz = abs(1.0 / dz) if dz != 0 else float("inf")

        def nb(co, s):
            return (math.floor(co) + 1 - co) if s > 0 else (co - (math.ceil(co) - 1))

        tx_n = nb(px, stepx) * tdx if dx else float("inf")
        ty_n = nb(ey, stepy) * tdy if dy else float("inf")
        tz_n = nb(pz, stepz) * tdz if dz else float("inf")
        ix, iy, iz = int(math.floor(px)), int(math.floor(ey)), int(math.floor(pz))
        ok = True
        for _ in range(int(max_dist * 2) + 10):
            if (ix, iy, iz) in voxels:
                if (ix, iy, iz) == (bx, by, bz):
                    visible.append(((bx, by, bz), dist))
                    break
                ok = False
                break
            if tx_n < ty_n and tx_n < tz_n:
                ix += stepx
                tx_n += tdx
            elif ty_n < tz_n:
                iy += stepy
                ty_n += tdy
            else:
                iz += stepz
                tz_n += tdz
    return sorted(visible, key=lambda x: x[1])


# ----- higher-level actions -----
def aim_at(b, tx, ty, tz, max_ticks=40, tol_yaw=2.0, tol_pitch=2.0):
    """Turn the camera until it is aligned with point (tx,ty,tz)."""
    for _ in range(max_ticks):
        act = face_action(b.obs, tx, ty, tz, tol_yaw, tol_pitch)
        if act is None:
            break
        b.step(act)
    return b.obs


def mine(b, tx, ty, tz, max_ticks=200, item_idx=LOG):
    """Align with point and attack until inventory item_idx increases."""
    aim_at(b, tx, ty, tz, tol_yaw=1.0, tol_pitch=1.0)
    before = inv(b.obs, item_idx)
    for i in range(max_ticks):
        act = face_action(b.obs, tx, ty, tz, tol_yaw=1.0, tol_pitch=1.0) or {}
        act["attack"] = 1
        obs = b.step(act)
        if inv(obs, item_idx) > before:
            return obs, True, "inventory"
    return b.obs, False, "max_ticks"


# ----- episode 2 additions -----

def normalize_yaw(yaw):
    """Yaw in degrees -> -180..180 range."""
    return ((yaw + 180) % 360) - 180


def dirt_count(obs):
    """Number of dirt items currently in the hotbar."""
    n = 0
    for bid, cnt in zip(obs.get("hotbar_ids", []), obs.get("hotbar_counts", [])):
        if bid == ID_DIRT:
            n += cnt
    return n


def find_blocks(obs, bids, max_dist=None):
    """Find nearby block coords whose id is in `bids`.

    Returns list of (bid, x, y, z) sorted by distance from player.
    """
    if isinstance(bids, int):
        bids = {bids}
    else:
        bids = set(bids)
    px, py, pz = pos(obs)
    out = []
    for bid, x, y, z in obs.get("blocks", []):
        if bid in bids:
            d = dist3((px, py, pz), (x + 0.5, y + 0.5, z + 0.5))
            if max_dist is None or d <= max_dist:
                out.append((bid, x, y, z, d))
    out.sort(key=lambda r: r[-1])
    return [(b, x, y, z) for b, x, y, z, _ in out]


def first_block_ahead(obs, max_dist=8.0, eye_height=1.62):
    """Like first_block_along_view but skip the voxel containing the camera.

    This is useful when you are standing inside a block (e.g. a 1-block-wide shaft)
    and want to know what sits *ahead* of you rather than what surrounds you.
    """
    px, py, pz = pos(obs)
    ey = py + eye_height
    dx, dy, dz = look_vector(obs, eye_height)
    voxels = voxel_map(obs)
    if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
        return None, None
    stepx = 1 if dx > 0 else -1
    stepy = 1 if dy > 0 else -1
    stepz = 1 if dz > 0 else -1
    tdx = abs(1.0 / dx) if dx != 0 else float("inf")
    tdy = abs(1.0 / dy) if dy != 0 else float("inf")
    tdz = abs(1.0 / dz) if dz != 0 else float("inf")

    def next_boundary(coord, step):
        if step > 0:
            return math.floor(coord) + 1 - coord
        else:
            return coord - (math.ceil(coord) - 1)

    tx_n = next_boundary(px, stepx) * tdx if dx != 0 else float("inf")
    ty_n = next_boundary(ey, stepy) * tdy if dy != 0 else float("inf")
    tz_n = next_boundary(pz, stepz) * tdz if dz != 0 else float("inf")
    ix, iy, iz = int(math.floor(px)), int(math.floor(ey)), int(math.floor(pz))
    steps = int(max_dist * 2) + 10
    first = True
    for _ in range(steps):
        if not first:
            key = (ix, iy, iz)
            if key in voxels:
                return voxels[key], key
        first = False
        if tx_n < ty_n and tx_n < tz_n:
            ix += stepx
            tx_n += tdx
        elif ty_n < tz_n:
            iy += stepy
            ty_n += tdy
        else:
            iz += stepz
            tz_n += tdz
    return None, None


def break_block(b, bx, by, bz, max_ticks=200):
    """Aim at (bx,by,bz) and hold attack until it is no longer in voxel_map.

    Returns (success, final_obs).  Note: a block may not be present in
    voxel_map if another block is higher/topmost in the same column, so this
    only works reliably for exposed blocks.
    """
    tx, ty, tz = block_center(bx, by, bz)
    aim_at(b, tx, ty, tz, tol_yaw=2.0, tol_pitch=2.0)
    for _ in range(max_ticks):
        act = face_action(b.obs, tx, ty, tz, tol_yaw=1.0, tol_pitch=1.0) or {}
        act["attack"] = 1
        b.step(act)
        if voxel_map(b.obs).get((bx, by, bz)) is None:
            return True, b.obs
    return False, b.obs


def descend_to_ground(b, yaw=100, pitch=40, max_ticks=500):
    """Reliable way to leave the spawn canopy and reach solid ground.

    Reproducible on seed 0: idle a few ticks first, then move roughly
    west-southwest while looking down through the leaves.
    """
    for _ in range(15):
        b.step({})
    for _ in range(max_ticks):
        dy = normalize_yaw(yaw - b.obs["yaw"])
        dp = pitch - b.obs["pitch"]
        act = {"forward": 1, "jump": 1, "sprint": 1, "attack": 1,
               "dyaw": max(-20, min(20, dy)), "dpitch": max(-20, min(20, dp))}
        obs = b.step(act)
        if obs["y"] < 74 and obs["x"] < 0:
            return obs, True
    return b.obs, False


def special_blocks_nearby(obs, max_dist=8.0):
    """Look for blocks that usually mean structures / loot."""
    targets = {ID_CHEST, ID_CRAFTING_TABLE, ID_FURNACE_OFF, ID_FURNACE_ON,
               ID_WOOL, ID_COBBLESTONE, ID_SANDSTONE, ID_COAL_ORE}
    return find_blocks(obs, targets, max_dist=max_dist)


# ----- episode 3 additions / corrections -----

ID_PLANKS = 5
ID_TORCH = 50
ID_STICK_ITEM = 280
ID_WOODEN_PICKAXE = 270
ID_STONE_PICKAXE = 274


def norm_yaw(y):
    """Yaw in degrees -> [0,360)."""
    return y % 360.0


def set_yaw_pitch(b, target_yaw, target_pitch, rate=25.0):
    """Turn toward exact yaw/pitch in one tick, accounting for accumulated yaw.

    Returns the observation after the turn (which may be a no-op if already aligned).
    """
    obs = b.obs
    cur = norm_yaw(obs["yaw"])
    delta = (target_yaw - cur + 180.0) % 360.0 - 180.0
    dp = target_pitch - obs["pitch"]
    act = {}
    if abs(delta) > 0.5:
        act["dyaw"] = max(-rate, min(rate, delta))
    if abs(dp) > 0.5:
        act["dpitch"] = max(-rate, min(rate, dp))
    if act:
        return b.step(act)
    return obs


def select_item(b, item_id):
    """Select the hotbar slot that currently holds item_id. Returns obs."""
    obs = b.obs
    if item_id in obs.get("hotbar_ids", []):
        slot = obs["hotbar_ids"].index(item_id)
        return b.step({"hotbar": slot})
    return obs


def pillar_up(b, item_id=None, target_y=None, max_ticks=30):
    """Tower straight up by placing blocks under the player.

    Pass item_id of the block to place (e.g. ID_DIRT) or leave None to use the
    currently selected block. Stops when target_y is reached or blocks run out.
    """
    if item_id is not None:
        select_item(b, item_id)
    for _ in range(max_ticks):
        obs = b.obs
        if target_y is not None and obs["y"] >= target_y - 0.3:
            break
        # look straight down at the top of the block we are standing on
        set_yaw_pitch(b, norm_yaw(obs["yaw"]), 90.0)
        # jump and place; the new block appears at our feet and we land on it
        b.step({"use": 1, "jump": 1})
    return b.obs


def craft_all_planks(b):
    """Convert every log in inventory into planks."""
    while b.obs["inv_counts"][LOG] > 0:
        b.step({"craft": 0})
    return b.obs


def craft_table(b):
    """Craft a crafting table from planks (assumes 4+ planks are available)."""
    return b.step({"craft": 2})


def craft_sticks(b, n_pairs=1):
    """Craft up to n_pairs batches of sticks. Each batch uses 2 planks."""
    for _ in range(n_pairs):
        if b.obs["inv_counts"][PLANKS] < 2:
            break
        b.step({"craft": 1})
    return b.obs


def craft_wooden_pickaxe(b):
    """Craft a wooden pickaxe (needs a crafting table already open)."""
    return b.step({"craft": 3})


def craft_stone_pickaxe(b):
    """Craft a stone pickaxe (needs a crafting table already open)."""
    return b.step({"craft": 4})


def craft_torches(b, batches=1):
    """Craft up to batches of torches (needs coal + sticks in inventory).

    Each batch yields 4 torches and consumes 1 coal + 1 stick. No crafting table
    required for torches in the 2x2 inventory grid.
    """
    for _ in range(batches):
        if b.obs["inv_counts"][COAL] < 1 or b.obs["inv_counts"][STICK] < 1:
            break
        b.step({"craft": 5})
    return b.obs


def place_block_on_top(b, bx, by, bz, item_id=None):
    """Place the selected block item on top of the block at (bx,by,bz).

    If item_id is given, select it first. Returns the observation after the use.
    """
    if item_id is not None:
        select_item(b, item_id)
    aim_at(b, bx + 0.5, by + 1.0, bz + 0.5, tol_yaw=3.0, tol_pitch=3.0)
    return b.step({"use": 1})


def dig_straight_down(b, stop_y=None, max_ticks=200):
    """Mine the block directly below the feet and let the player fall onto the next layer.

    Stops when stop_y is reached, when no block below can be detected in voxel_map,
    or when health is critical. Requires an equipped pickaxe if stone is present.
    """
    for _ in range(max_ticks):
        obs = b.obs
        if stop_y is not None and obs["y"] <= stop_y + 0.5:
            break
        if obs.get("health", 20) < 5:
            break
        px, py, pz = pos(obs)
        bx = int(math.floor(px))
        by = int(math.floor(py)) - 1
        bz = int(math.floor(pz))
        aim_at(b, bx + 0.5, by + 0.5, bz + 0.5, tol_yaw=5.0, tol_pitch=5.0)
        before_y = obs["y"]
        for _ in range(120):
            obs = b.step({"attack": 1})
            if obs["y"] < by + 0.5 or voxel_map(obs).get((bx, by, bz)) is None:
                break
        # land
        for _ in range(10):
            obs = b.step({"jump": 1})
        if obs["y"] == before_y and voxel_map(obs).get((bx, by, bz)) is not None:
            # did not make progress
            break
    return b.obs


def harvest_logs(b, n=3, max_ticks=800):
    """Harvest at least n logs from nearby tree trunks.

    Works both in the canopy and on the ground. It breaks the closest log from
    obs['logs'] and waits for the drop to be picked up. Logs DO drop items in
    this world (contrary to earlier mistaken notes), but the player must be
    close enough to the break point to collect them.
    """
    start = b.obs["inv_counts"][LOG]
    for _ in range(max_ticks):
        if b.obs["inv_counts"][LOG] >= start + n:
            break
        obs = b.obs
        px, py, pz = pos(obs)
        logs = sorted(obs.get("logs", []),
                      key=lambda xyz: dist3((px, py, pz),
                                            (xyz[0] + 0.5, xyz[1] + 0.5, xyz[2] + 0.5)))
        if not logs:
            # move a bit to reveal more logs
            b.step({"forward": 1, "jump": 1, "attack": 1})
            continue
        target = logs[0]
        tx, ty, tz = [c + 0.5 for c in target]
        # prefer logs near the player's current y for easy pickup
        logs_same_y = [L for L in logs if abs(L[1] - py) <= 1.5 and
                       dist3((px, py, pz), (L[0] + 0.5, L[1] + 0.5, L[2] + 0.5)) < 2.5]
        if logs_same_y:
            target = logs_same_y[0]
            tx, ty, tz = [c + 0.5 for c in target]
        # move adjacent horizontally if needed
        while dist3(pos(b.obs), (tx, ty, tz)) > 2.0:
            txz = (tx, tz)
            yaw_t = yaw_to_point(b.obs["x"], b.obs["z"], txz[0], txz[1])
            set_yaw_pitch(b, yaw_t, 0.0)
            b.step({"forward": 1, "jump": 1, "attack": 1})
        aim_at(b, tx, ty, tz, tol_yaw=2.0, tol_pitch=2.0, max_ticks=40)
        before = b.obs["inv_counts"][LOG]
        for _ in range(120):
            act = face_action(b.obs, tx, ty, tz, tol_yaw=2.0, tol_pitch=2.0) or {}
            act["attack"] = 1
            obs = b.step(act)
            if obs["inv_counts"][LOG] != before or tuple(target) not in [tuple(x) for x in obs.get("logs", [])]:
                break
        # wiggle to collect any lingering drops
        for _ in range(10):
            b.step({"forward": 1})
    return b.obs


def place_torch(b):
    """Place one torch from inventory on a nearby solid surface.

    Scans around the player to find a solid block face and uses a torch item.
    Returns True if a torch block was observed after placement.
    """
    obs = b.obs
    if ID_TORCH not in obs.get("hotbar_ids", []):
        return False, obs
    # Try several rays for a solid block.
    for pitch_deg in [0, 20, 40, 60, -20]:
        for yaw_deg in range(0, 360, 45):
            fake = dict(obs)
            fake["yaw"] = yaw_deg
            fake["pitch"] = pitch_deg
            bid, key = first_block_along_view(fake, max_dist=5.0)
            if bid is not None and bid not in (ID_AIR, ID_LEAVES):
                select_item(b, ID_TORCH)
                set_yaw_pitch(b, yaw_deg, pitch_deg)
                obs2 = b.step({"use": 1})
                if any(bid2 == ID_TORCH for bid2, _, _, _ in obs2.get("blocks", [])):
                    return True, obs2
    return False, b.obs
