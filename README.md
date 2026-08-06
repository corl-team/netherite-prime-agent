# netherite-prime-agent

### Letting an LLM play a from-scratch C reimplementation of Minecraft

A bridge between [netherite](https://github.com/Infatoshi/netherite) - Elliot
Arledge's Minecraft 1.11.2 rewritten in C/CUDA and bit-verified against the
Java game - and [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent),
so a language model can play it from a persistent Python kernel.

The engine is not ours. This repository is the wiring, the runners, and the
experiments: about 700 lines of Python and shell.

## What is here

| Path | What it is |
|------|------------|
| `agent/mcbridge.py` | Raw transport: one action dict in, one observation out, one game tick. No strategy. |
| `agent/mcagent.py` | Macro wrapper over the same protocol: aim, walk, mine, craft, place, plus a text observation. |
| `agent/replay.py` | Re-render a recorded episode at any resolution or frame rate. The engine is deterministic, so recorded actions replay exactly. |
| `agent/play.sh` | Hand the game to the model with a goal. |
| `agent/learn.sh` | Continual-learning loop: every episode starts with no memory, the only inheritance is the notes and helper files the agent writes for itself. |
| `agent/PLAY.md` | The brief the model reads. |
| `patches/` | The engine-side changes this bridge needs, described in prose. |
| `examples/` | `NOTES.md` and `tools.py` as the agent wrote them for itself over three episodes. |

## Where the Prime Agent side is

Deliberately thin. The agent plays from its own IPython kernel by importing
these modules, so there are only three touch points:

- `agent/play.sh` and `agent/learn.sh` invoke the CLI:
  `prime-agent --cwd agent -nc -ns -ne --skill .../refine --skill .../attach-image -p "<brief>"`.
  The three `-n*` flags drop context files, discovered skills and extensions so
  a run is reproducible; the two skills are added back explicitly.
- `Game.attach()` / `Bridge.show()` publish
  `application/vnd.prime-agent.attachment+json` from the kernel, which is how a
  rendered frame reaches a vision model's context.
- Everything else is the model writing Python against `mcbridge` / `mcagent`.

## Requirements

1. **netherite**, built: clone `Infatoshi/netherite`, run its bootstrap (it
   extracts assets from a Minecraft 1.11.2 jar you must own), `make -C magma game`.
2. **Three engine-side changes**, described in `patches/README.md`: `health`
   and `food` in the JSON observation, a raised cutout draw-buffer cap, and a
   test include path. Not upstream yet.
3. **Prime Agent** on PATH, pointed at any OpenAI-compatible endpoint. Runs
   here used Kimi K2.7-Code on a self-hosted vLLM deployment.

Put this repository's `agent/` directory next to netherite's `magma/`, or edit
`BIN` in `mcbridge.py`.

## Quickstart

```bash
# one episode toward a goal
SEED=0 GOAL="Craft a stone pickaxe, then mine coal and place a torch." bash agent/play.sh

# three episodes; the agent keeps only what it writes into agent/workspace/
bash agent/learn.sh 3

# re-shoot a recorded episode in 720p, one frame per tick
python agent/replay.py FRAMES_DIR out/ --from 9200 --to 9425 --width 1280 --height 720 --every 1
```

## What we measured

Runs of 2026-08-06, seed 0 unless noted, verified against session transcripts
and the game's own inventory.

- **The chain gets done.** 79 tool calls, 13,050 ticks: stone pickaxe, 21
  cobblestone, a torch placed in a self-dug mineshaft, full health.
- **An unseen world too.** Seed 7 (swamp), same goal, torch placed at
  (-32, 62, 11) - not seed memorisation.
- **It found a real engine bug.** Digging straight up through a canopy exposes
  every interior leaf face at once: 263,916 verts against a 262,144 cap,
  SIGABRT. Reproducible; the fix is change 2 in `patches/README.md`.
- **Continual learning propagates mistakes too.** Episode 1 failed to collect
  a log and wrote "logs produce no inventory item" into its notes; episode 2
  believed it and wrote a 415-line search script for a tool that does not
  exist; episode 3 retested the claim, corrected the note and finished the
  chain. Final self-written toolkit: 1,836 lines across six files.
- **It barely uses the RL camera.** netherite's observation includes a 64x36
  grid of block ids, one per camera ray. The model reads one pixel of it (the
  crosshair) and screenshots the game for everything else.
- **Where the tokens go.** One observation is 23,086 bytes; a 25,820-tick run
  pushed 594 MB through the Python kernel while 157 KB reached the model's
  context. About 190 game ticks per tool call.

## Credits

Engine: [netherite](https://github.com/Infatoshi/netherite) by Elliot Arledge.
Agent harness: [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent)
by Prime Intellect. Model: Kimi K2.7-Code by Moonshot AI, served with vLLM.

## Licensing

Everything in this repository is ours and MIT-licensed (see `LICENSE`).

netherite itself carries **no license** - all rights reserved by its author -
so nothing of it is redistributed here: no engine source, and not even a diff
of one. `patches/README.md` describes the three changes to make in your own
checkout. Get the engine from
[Infatoshi/netherite](https://github.com/Infatoshi/netherite) and treat it
under whatever terms its author sets.
