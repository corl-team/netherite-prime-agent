"""Raw transport to netherite's step protocol. No strategy, no macros.

One action line in, one observation line out, one game tick each time - the
same bridge the RL trainers use. Anything above this (aiming, pathing, tree
chopping, sensing helpers) is for the caller to invent.

    from mcbridge import Bridge
    b = Bridge(seed=0, frames_dir="/tmp/play")
    obs = b.step({"forward": 1})          # one tick
    obs = b.step({"attack": 1, "cam": 0}) # cam:0 skips the camera render

Action keys: forward, strafe (-1..1), dyaw, dpitch (delta degrees), jump,
sneak, sprint, attack, use, hotbar (0-8, -1 = keep), craft (0-7), interact,
smelt, cam (0/1).

Craft ids: 0 planks, 1 sticks, 2 table, 3 wooden_pick, 4 stone_pick,
5 torch, 6 furnace, 7 iron_pick. 3, 4, 6, 7 need an open crafting table.

Obs keys: t, x, y, z, yaw, pitch, dead, health, food, hotbar_ids,
hotbar_counts, hotbar_sel, container (0 none, 1 table, 2 furnace),
inv_counts [log, planks, stick, cobblestone, table, w_pick, s_pick, coal,
torch], inv_iron [furnace, iron_ore, iron_ingot, iron_pick], blocks
[[id,x,y,z] x256, topmost-per-column nearest first], logs [[x,y,z] x64],
coal [[x,y,z] x32], cam/depth/edge (64x36 semantic camera, row-major).

The runtime stops ticking the moment the player dies: the next step() raises
EpisodeOver. Nothing is undoable and there is no respawn.
"""
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.abspath(os.path.join(HERE, os.pardir, "magma", "magma_game"))
CAM_W, CAM_H = 64, 36


class EpisodeOver(RuntimeError):
    """The C runtime stopped ticking - the player died, or the process died."""


class Bridge:
    def __init__(self, seed=0, mobs=False, frames_dir=None, frame_every=10,
                 size=(480, 270)):
        self.seed = seed
        self.obs = None
        self.log_path = None
        cmd = [BIN, "--rl", "--render", "off", "--pace", "unlimited",
               "--seed", str(seed), "--mobs", "on" if mobs else "off"]
        if frames_dir:
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
        self._rec = open(os.path.join(frames_dir, "obs.jsonl"), "w") if frames_dir else None
        self._acts = open(os.path.join(frames_dir, "actions.jsonl"), "w") if frames_dir else None
        err = open(self.log_path, "w") if self.log_path else subprocess.DEVNULL
        # caps.c reads magma.conf from the CWD; run elsewhere and every cap
        # silently drops to its compile-time default.
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=err,
                                     cwd=os.path.dirname(BIN),
                                     text=True, bufsize=1)
        self.obs = self._read()

    def _read(self):
        line = self.proc.stdout.readline()
        if not line:
            last = self.obs or {}
            tail = "(none)"
            if self.log_path and os.path.exists(self.log_path):
                tail = " | ".join(open(self.log_path).read().splitlines()[-2:])
            raise EpisodeOver(f"episode ended at tick {last.get('t')}, "
                              f"health {last.get('health')}, y {last.get('y')}. "
                              f"engine stderr: {tail}")
        return json.loads(line)

    def step(self, action=None):
        """One tick. Returns the new observation."""
        line = json.dumps(action or {})
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        if self._acts:
            # every action, in order: the engine is deterministic, so this is
            # the episode. replay.py re-renders it at any resolution or frame
            # rate later, without paying for the model a second time.
            self._acts.write(line + "\n")
        self.obs = self._read()
        self._record()
        return self.obs

    def _record(self):
        """Log the cheap obs fields next to the frames, on frame ticks only, so
        a clip can be captioned with what was actually true at that frame."""
        if not self._rec or self.obs["t"] % self.frame_every:
            return
        o = self.obs
        row = {k: o[k] for k in ("t", "x", "y", "z", "yaw", "pitch", "health",
                                 "food", "hotbar_sel", "container",
                                 "inv_counts", "inv_iron")}
        # the semantic camera on frame ticks only: enough to composite "what it
        # saw" next to "what it rendered" long after the episode is gone.
        if o.get("cam") and max(o["cam"]):
            row["cam"] = o["cam"]
        self._rec.write(json.dumps(row) + "\n")
        self._rec.flush()

    def frame(self, path=None):
        """Newest rendered frame converted to PNG (needs frames_dir)."""
        from PIL import Image
        ppms = sorted(f for f in os.listdir(self.frames_dir) if f.endswith(".ppm"))
        if not ppms:
            raise RuntimeError("no frame written yet - step a few more ticks")
        path = path or os.path.join(self.frames_dir, "latest.png")
        Image.open(os.path.join(self.frames_dir, ppms[-1])).save(path)
        return path

    def show(self, path=None):
        """Put the newest frame into a vision model's context."""
        import base64
        path = path or self.frame()
        from IPython.display import display
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        display({"application/vnd.prime-agent.attachment+json":
                 {"mime_type": "image/png", "data": data, "path": path},
                 "text/plain": f"[frame {path}]"}, raw=True)
        return path

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
