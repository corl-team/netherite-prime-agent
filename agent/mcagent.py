"""Text-mode Minecraft for an LLM: a macro-action wrapper over `magma_game --rl`.

The RL bridge is one action line -> one obs line per tick (20 ticks = 1s of
game time). A language model cannot act per tick, so this wrapper exposes
macros (walk / turn / mine / craft) that hold an action for N ticks and only
ask for the camera on the last one, plus a compact text observation: crosshair
target, inventory, nearest logs/coal, and an ASCII view of the 64x36 semantic
camera.

Nothing here simulates: every block, drop, recipe and dig timing comes from
the C runtime in magma/, the same tick that is bit-verified against the Java
game. This file only reshapes its I/O for a model.

    from mcagent import Game
    g = Game(seed=0)
    print(g.text())
    g.look_at(*g.nearest("log")[0])
    g.mine(60)
    g.craft("planks")
"""
import json
import math
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, os.pardir, "magma", "magma_game")

# rl_mode.c rl_inv_ids order, and the ids behind those names.
INV_NAMES = ("log", "planks", "stick", "cobblestone", "crafting_table",
             "wooden_pick", "stone_pick", "coal", "torch")
INV_IDS = (17, 5, 280, 4, 58, 270, 274, 263, 50)
IRON_NAMES = ("furnace", "iron_ore", "iron_ingot", "iron_pick")
IRON_IDS = (61, 15, 265, 257)
ITEM_IDS = dict(zip(INV_NAMES + IRON_NAMES, INV_IDS + IRON_IDS))
# rl_mode.c rl_crafts order. 3x3 recipes need an open crafting table.
CRAFTS = ("planks", "sticks", "table", "wooden_pick", "stone_pick",
          "torch", "furnace", "iron_pick")
CRAFT_NEEDS_TABLE = {"wooden_pick", "stone_pick", "furnace", "iron_pick"}

# Block ids that matter for the wood -> stone -> iron chain (MC 1.11.2).
BLOCKS = {
    0: "air", 1: "stone", 2: "grass", 3: "dirt", 4: "cobblestone", 5: "planks",
    7: "bedrock", 8: "water", 9: "water", 10: "lava", 11: "lava", 12: "sand",
    13: "gravel", 14: "gold_ore", 15: "iron_ore", 16: "coal_ore", 17: "log",
    18: "leaves", 24: "sandstone", 31: "tallgrass", 37: "flower", 38: "flower",
    56: "diamond_ore", 58: "crafting_table", 61: "furnace", 62: "furnace_lit",
    73: "redstone_ore", 78: "snow_layer", 79: "ice", 81: "cactus", 82: "clay",
    83: "reeds", 85: "fence", 86: "pumpkin", 106: "vine", 161: "leaves",
    162: "log", 175: "double_plant",
}
# ASCII glyph per block class for the camera view.
GLYPH = {"air": " ", "log": "T", "leaves": "t", "grass": ",", "dirt": ".",
         "stone": "#", "cobblestone": "c", "coal_ore": "C", "iron_ore": "I",
         "gold_ore": "G", "diamond_ore": "D", "water": "~", "lava": "!",
         "sand": ":", "gravel": ";", "crafting_table": "W", "furnace": "F",
         "furnace_lit": "F", "planks": "=", "tallgrass": "'", "flower": "*",
         "snow_layer": "-", "bedrock": "@"}

CAM_W, CAM_H = 64, 36


def block_name(i):
    return BLOCKS.get(i, f"id{i}")


class EpisodeOver(RuntimeError):
    """The C runtime stopped ticking: the player died (or the process died)."""


class Game:
    """One live magma_game process. Every method returns the newest obs dict."""

    def __init__(self, seed=0, mobs=False, bin_path=None, frames_dir=None,
                 frame_every=10, size=(480, 270)):
        """frames_dir: render the real game view there every frame_every ticks
        (PPM). screenshot() converts the newest one to PNG for a vision model."""
        self.seed = seed
        self.over = False
        self.log_path = None
        cmd = [bin_path or BIN, "--rl", "--render", "off", "--pace", "unlimited",
               "--seed", str(seed), "--mobs", "on" if mobs else "off"]
        if frames_dir:
            # one subdir per process: two live Games sharing a directory
            # interleave their frames and every clip comes out scrambled.
            # absolute: the game runs with cwd=magma/, so a relative frames dir
            # would be created (or fail) next to the binary instead of here.
            frames_dir = os.path.join(os.path.abspath(frames_dir),
                                      f"run{os.getpid()}_{id(self):x}")
            os.makedirs(frames_dir, exist_ok=True)
            cmd += ["--frames-out", frames_dir, "--frame-every", str(frame_every),
                    "--width", str(size[0]), "--height", str(size[1])]
            self.log_path = os.path.join(frames_dir, "magma.log")
        self.frames_dir = frames_dir
        self.frame_every = frame_every
        # obs.jsonl on frame ticks: what was actually true at each rendered
        # frame, so a clip can be captioned without guessing afterwards.
        self._rec = open(os.path.join(frames_dir, "obs.jsonl"), "w") if frames_dir else None
        # every action, in order: the engine is deterministic, so replay.py can
        # re-shoot the episode at any resolution or frame rate afterwards.
        self._acts = open(os.path.join(frames_dir, "actions.jsonl"), "w") if frames_dir else None
        err = open(self.log_path, "w") if self.log_path else subprocess.DEVNULL
        # caps.c loads magma.conf from the CWD, so run from magma/ or every
        # cap silently falls back to the compile-time default.
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=err,
                                     cwd=os.path.dirname(os.path.abspath(BIN)),
                                     text=True, bufsize=1)
        self.ticks = 0
        self.obs = self._read()

    # --- transport -------------------------------------------------------

    def _read(self):
        line = self.proc.stdout.readline()
        if not line:
            last = self.obs if hasattr(self, "obs") else {}
            self.over = True
            raise EpisodeOver(
                "the episode ended - the C runtime stops ticking the moment "
                f"the player dies. Last seen: health {last.get('health')}, "
                f"y {last.get('y')}, tick {last.get('t')}. "
                f"stderr: {self._stderr_tail()}")
        return json.loads(line)

    def _stderr_tail(self, n=2):
        if not self.log_path or not os.path.exists(self.log_path):
            return "(none)"
        with open(self.log_path) as f:
            return " | ".join(f.read().splitlines()[-n:]) or "(empty)"

    def _send(self, action):
        line = json.dumps(action)
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        if self._acts:
            self._acts.write(line + "\n")
        self.obs = self._read()
        self.ticks += 1
        self._record()
        return self.obs

    def _record(self):
        if not self._rec or self.obs["t"] % self.frame_every:
            return
        o = self.obs
        row = {k: o[k] for k in ("t", "x", "y", "z", "yaw", "pitch", "health",
                                 "food", "hotbar_sel", "container",
                                 "inv_counts", "inv_iron")}
        if o.get("cam") and max(o["cam"]):
            row["cam"] = o["cam"]
        self._rec.write(json.dumps(row) + "\n")
        self._rec.flush()

    def act(self, n=1, **keys):
        """Hold one action for n ticks. Camera is only rendered on the last."""
        n = max(1, int(n))
        for i in range(n):
            self._send({**keys, "cam": 1 if i == n - 1 else 0})
        return self.obs

    def close(self):
        # flush the recorders first: actions.jsonl is buffered, and a replay
        # that silently loses the tail is worse than no replay at all.
        for f in (getattr(self, "_acts", None), getattr(self, "_rec", None)):
            if f:
                f.close()
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()

    # --- macros ----------------------------------------------------------

    def turn(self, dyaw=0.0, dpitch=0.0, step=15.0):
        """Turn by a total delta, split into <=step-degree ticks."""
        n = max(1, int(math.ceil(max(abs(dyaw), abs(dpitch)) / step)))
        for i in range(n):
            self._send({"dyaw": dyaw / n, "dpitch": dpitch / n,
                        "cam": 1 if i == n - 1 else 0})
        return self.obs

    def face(self, yaw=None, pitch=None):
        """Turn to absolute yaw/pitch (MC convention: yaw 0 = +Z, 180 = -Z)."""
        o = self.obs
        dyaw = 0.0 if yaw is None else (yaw - o["yaw"] + 540) % 360 - 180
        dpitch = 0.0 if pitch is None else pitch - o["pitch"]
        return self.turn(dyaw, dpitch)

    def look_at(self, x, y, z):
        """Aim the crosshair at the centre of block (x, y, z)."""
        o = self.obs
        dx, dy, dz = x + 0.5 - o["x"], y + 0.5 - (o["y"] + 1.62), z + 0.5 - o["z"]
        yaw = math.degrees(math.atan2(-dx, dz))
        pitch = -math.degrees(math.atan2(dy, math.hypot(dx, dz)))
        return self.face(yaw, pitch)

    def walk(self, n=20, forward=1, strafe=0, sprint=0, jump=0):
        return self.act(n, forward=forward, strafe=strafe, sprint=sprint,
                        jump=jump)

    def goto(self, x, z, max_ticks=400, tol=1.2):
        """Walk (with autojump) toward a horizontal target. Stops when close
        or stuck: no simulation, just repeated forward ticks toward the yaw."""
        for _ in range(0, max_ticks, 10):
            o = self.obs
            dx, dz = x + 0.5 - o["x"], z + 0.5 - o["z"]
            if math.hypot(dx, dz) <= tol:
                break
            self.face(math.degrees(math.atan2(-dx, dz)))
            before = (self.obs["x"], self.obs["z"])
            self.act(10, forward=1, sprint=1)
            moved = math.dist(before, (self.obs["x"], self.obs["z"]))
            if moved < 0.3:                  # blocked: hop the obstacle
                self.act(6, forward=1, jump=1)
        return self.obs

    def mine(self, n=80, hotbar=None):
        """Hold attack on whatever the crosshair points at."""
        keys = {"attack": 1}
        if hotbar is not None:
            keys["hotbar"] = hotbar
        return self.act(n, **keys)

    def mine_block(self, x, y, z, n=120, collect=True):
        """Aim at a block, dig it out, then walk over the drop to pick it up.

        Drops are only picked up within 1 block horizontally, so digging from
        range and standing still leaves the item on the ground forever."""
        self.look_at(x, y, z)
        self.mine(n)
        if collect:
            self.collect(x, z)
        return self.obs

    def collect(self, x, z, ticks=25):
        """Walk onto (x, z) and wait: item drops only enter the inventory
        within 1 block horizontally of the player."""
        self.goto(x, z, tol=0.4)
        return self.act(ticks)

    def place(self, hotbar=None):
        """One raw use-click with the currently held item."""
        keys = {"use": 1}
        if hotbar is not None:
            keys["hotbar"] = hotbar
        return self.act(1, **keys)

    def place_block(self, item="crafting_table", budget=120):
        """Select `item`, aim at the ground and place it.

        Success is the inventory going DOWN by one, not the block turning up
        in the obs: `blocks` only carries the topmost entry per column, so a
        torch on a wall or a table under an overhang places fine and never
        appears - which used to make this return False after it had worked."""
        item_id = ITEM_IDS.get(item, item)
        if not self.select(item_id):
            return False
        before = self._count(item_id)
        self.act(4, forward=-1)              # back off so the ground is in reach
        self.face(pitch=35)
        for t in range(budget):
            if self._count(item_id) < before:
                return True
            near = [b for b in self.obs["blocks"]
                    if b[0] == item_id and abs(b[1] - self.obs["x"]) < 6
                    and abs(b[3] - self.obs["z"]) < 6]
            if near:
                return True
            self.act(1, use=1)
            if t == budget // 2:             # plan B: try another spot
                self.turn(90)
                self.act(3, forward=-1)
                self.face(pitch=35)
        return False

    def select(self, item):
        """Select the hotbar slot holding an item, by name or id.

        Takes names too ("stone_pick"), because passing one used to compare a
        string against integer ids, match nothing, and leave the previous slot
        selected - so the next mine() swung an empty hand and dropped nothing."""
        item_id = ITEM_IDS.get(item, item)
        if not isinstance(item_id, int):
            raise ValueError(f"unknown item {item!r}; known: {sorted(ITEM_IDS)}")
        for slot, hid in enumerate(self.obs["hotbar_ids"]):
            if hid == item_id and self.obs["hotbar_counts"][slot] > 0:
                if self.obs["hotbar_sel"] != slot:
                    self.hotbar(slot)
                return True
        return False

    def _count(self, item_id):
        """How many of item_id the whole inventory holds (0 if untracked)."""
        by_id = dict(zip(INV_IDS + IRON_IDS,
                         self.obs["inv_counts"] + self.obs["inv_iron"]))
        return by_id.get(item_id, 0)

    def hotbar(self, slot):
        return self.act(1, hotbar=int(slot))

    def interact(self):
        """Open the nearest crafting table / furnace in reach."""
        return self.act(1, interact=1)

    def smelt(self):
        """Service the open furnace: take output, load iron ore + coal fuel."""
        return self.act(1, smelt=1)

    def craft(self, what):
        """Craft by name (see CRAFTS). 3x3 recipes need an open table."""
        idx = CRAFTS.index(what) if isinstance(what, str) else int(what)
        if CRAFTS[idx] in CRAFT_NEEDS_TABLE and self.obs["container"] != 1:
            return {"error": f"{CRAFTS[idx]} needs an open crafting table: "
                             "place one (use) and call interact() first",
                    **self.obs}
        return self.act(1, craft=idx)

    # --- sensing ---------------------------------------------------------

    def inv(self):
        d = dict(zip(INV_NAMES + IRON_NAMES,
                     self.obs["inv_counts"] + self.obs["inv_iron"]))
        return {k: v for k, v in d.items() if v}

    def block_at(self, x, y, z):
        """Block name at a world cell, from the obs block list (None = unseen
        or air; the list is the nearest 256 non-air blocks around the player)."""
        for bid, bx, by, bz in self.obs["blocks"]:
            if (bx, by, bz) == (x, y, z):
                return block_name(bid)
        return None

    def nearest(self, kind="log", k=5):
        """[(x, y, z, distance)] of the nearest logs / coal / any block name."""
        o, out = self.obs, []
        if kind == "log":
            cand = [(x, y, z) for x, y, z in o["logs"] if (x, y, z) != (0, 0, 0)]
        elif kind in ("coal", "coal_ore"):
            cand = [(x, y, z) for x, y, z in o["coal"] if (x, y, z) != (0, 0, 0)]
        else:
            cand = [(x, y, z) for bid, x, y, z in o["blocks"]
                    if block_name(bid) == kind]
        for x, y, z in cand:
            out.append((x, y, z, round(math.dist((x + .5, y + .5, z + .5),
                                                 (o["x"], o["y"], o["z"])), 2)))
        out.sort(key=lambda t: t[3])
        return out[:k]

    def crosshair(self):
        """(block name, distance) the centre camera ray hits, or None."""
        i = (CAM_H // 2) * CAM_W + CAM_W // 2
        d = self.obs["depth"][i]
        if d >= 255:
            return None
        return block_name(self.obs["cam"][i]), round(d / 4.0, 2)

    def view(self, w=64, h=18):
        """ASCII render of the semantic camera (nearest-neighbour downsample)."""
        cam, rows = self.obs["cam"], []
        for r in range(h):
            sr = r * CAM_H // h
            line = []
            for c in range(w):
                sc = c * CAM_W // w
                line.append(GLYPH.get(block_name(cam[sr * CAM_W + sc]), "?"))
            rows.append("".join(line))
        mid = h // 2
        rows[mid] = rows[mid][:w // 2] + "+" + rows[mid][w // 2 + 1:]
        return "\n".join(rows)

    def screenshot(self, path=None):
        """Newest rendered frame as a PNG (needs frames_dir). Returns its path.

        This is the real software rasterizer's output - the same renderer the
        pixel gates diff against the Java game - not the ASCII view."""
        if not self.frames_dir:
            raise RuntimeError("Game(frames_dir=...) is required for screenshots")
        from PIL import Image
        ppms = sorted(f for f in os.listdir(self.frames_dir) if f.endswith(".ppm"))
        if not ppms:
            raise RuntimeError("no frame written yet - act() a few more ticks")
        src = os.path.join(self.frames_dir, ppms[-1])
        path = path or os.path.join(self.frames_dir, "latest.png")
        Image.open(src).save(path)
        return path

    def attach(self, path=None):
        """Put the newest rendered frame in front of a vision model.

        Emits the agent-harness attachment MIME from the kernel, so the image
        goes into the conversation exactly like a pasted screenshot. Falls back
        to returning the path when nothing is listening."""
        path = path or self.screenshot()
        try:
            from IPython.display import display
        except ImportError:
            return path
        import base64
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        display({"application/vnd.prime-agent.attachment+json":
                 {"mime_type": "image/png", "data": data, "path": path},
                 "text/plain": f"[frame {path}]"}, raw=True)
        return path

    def text(self, view=True):
        """The whole observation as one block of text for a model to read."""
        o = self.obs
        cross = self.crosshair()
        lines = [
            f"tick {o['t']}  pos {o['x']:.1f} {o['y']:.1f} {o['z']:.1f}  "
            f"yaw {o['yaw']:.0f} pitch {o['pitch']:.0f}  "
            f"health {o.get('health', '?')}/20  food {o.get('food', '?')}/20"
            f"{'  DEAD' if o['dead'] else ''}",
            f"crosshair: {cross[0]} at {cross[1]}m" if cross
            else "crosshair: sky (nothing in reach)",
            f"inventory: {self.inv() or 'empty'}  "
            f"hotbar_sel {o['hotbar_sel']}  "
            f"container {('none', 'crafting_table', 'furnace')[o['container']]}",
        ]
        for kind in ("log", "coal"):
            near = self.nearest(kind, 3)
            lines.append(f"nearest {kind}: " +
                         (", ".join(f"({x},{y},{z}) d={d}" for x, y, z, d in near)
                          if near else "none in sight"))
        if view:
            lines.append("view (T log, t leaves, # stone, C coal, I iron, "
                         "~ water, ! lava, + crosshair):")
            lines.append(self.view())
        return "\n".join(lines)


def demo(seed=0, ticks=40):
    """Sanity run: spawn, look around, report."""
    g = Game(seed=seed)
    g.act(ticks)
    print(g.text())
    g.close()


if __name__ == "__main__":
    demo()
