#!/usr/bin/env python3
"""Re-render a recorded episode at any resolution and frame rate.

The engine is deterministic: same seed plus the same action lines gives the
same world, tick for tick (that is what magma/game/test_script.sh asserts).
The bridge writes every action to actions.jsonl, so a clip can be re-shot in
720p at one frame per tick without paying for the model again.

    uv run --no-project --with pillow python agent/replay.py \
        FRAMES_DIR OUT_DIR [--seed 0] [--from 8000] [--to 9200] \
        [--width 1280] [--height 720] [--every 1] [--view-distance 12]

--from/--to select a tick window: everything before --from is simulated with
rendering off (fast), so a 1,000-tick window costs a thousand frames, not
twenty-five thousand.
"""
import argparse
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.abspath(os.path.join(HERE, os.pardir, "magma", "magma_game"))


def replay(actions_path, out_dir, seed=0, mobs=False, start=0, end=None,
           width=1280, height=720, every=1, view_distance=None):
    actions = [l.rstrip("\n") for l in open(actions_path) if l.strip()]
    end = len(actions) if end is None else min(end, len(actions))
    if start >= end:
        raise SystemExit(f"empty window: {start}..{end} of {len(actions)} ticks")
    os.makedirs(out_dir, exist_ok=True)
    cmd = [BIN, "--rl", "--render", "off", "--pace", "unlimited",
           "--seed", str(seed), "--mobs", "on" if mobs else "off",
           "--frames-out", os.path.abspath(out_dir),
           "--frame-every", str(every), "--frame-offset", str(start),
           "--width", str(width), "--height", str(height)]
    if view_distance:
        cmd += ["--view-distance", str(view_distance)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, cwd=os.path.dirname(BIN),
                         text=True, bufsize=1)
    p.stdout.readline()                       # tick-0 obs
    for i, line in enumerate(actions[:end]):
        # camera obs is dead weight in a replay; the frames come from --frames-out
        act = json.loads(line)
        act["cam"] = 0
        p.stdin.write(json.dumps(act) + "\n")
        p.stdin.flush()
        if not p.stdout.readline():
            print(f"engine stopped at tick {i}: {p.stderr.read()[-300:]}")
            break
    p.stdin.close()
    p.wait(timeout=30)
    n = len([f for f in os.listdir(out_dir) if f.endswith(".ppm")])
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames_dir", help="episode dir holding actions.jsonl")
    ap.add_argument("--actions", help="action log path, if not <frames_dir>/actions.jsonl")
    ap.add_argument("out_dir")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mobs", action="store_true")
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--to", dest="end", type=int, default=None)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--view-distance", type=int, default=None)
    a = ap.parse_args()
    acts = a.actions or os.path.join(a.frames_dir, "actions.jsonl")
    if not os.path.exists(acts):
        raise SystemExit(f"{acts} not found - that episode predates action "
                         "recording, or ran without frames_dir")
    n = replay(acts, a.out_dir, a.seed, a.mobs, a.start, a.end, a.width,
               a.height, a.every, a.view_distance)
    print(f"wrote {n} frames to {a.out_dir}")


if __name__ == "__main__":
    main()
