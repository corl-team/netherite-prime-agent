# Playing netherite from an LLM

You control a survival player inside netherite: Minecraft 1.11.2 rebuilt in C,
bit-verified against the real Java game. Nothing is mocked - worldgen, dig
timings, recipes, item drops and physics come from the same tick the pixel
gates diff against Java.

## Loop

```python
import sys; sys.path.insert(0, "<repo>/agent")   # this directory
from mcagent import Game
g = Game(seed=0, frames_dir="/tmp/agentplay")   # frames_dir enables screenshots
print(g.text())                                  # position, inventory, ASCII view
```

`g.text()` is your cheap sense. For a real look at the rendered game, call
`g.attach()` - it puts the newest rendered frame straight into your context.
That PNG is the software rasterizer's own output, HUD included.

## Actions

| call | what it does |
|------|--------------|
| `g.act(n, forward=1, jump=1, attack=1, ...)` | hold one raw action for n ticks (20 ticks = 1s) |
| `g.walk(n)` / `g.goto(x, z)` | move; `goto` re-aims and hops obstacles |
| `g.face(yaw, pitch)` / `g.look_at(x, y, z)` | aim |
| `g.mine(n)` | hold attack on whatever the crosshair points at |
| `g.mine_block(x, y, z)` | aim, dig it out, walk over the drop |
| `g.collect(x, z)` | walk onto a spot to pick drops up |
| `g.place_block("crafting_table")` | select it, aim at the ground, place it; returns True/False |
| `g.place()` / `g.select(id)` / `g.hotbar(i)` | raw use-click / select the slot holding an item |
| `g.interact()` | open a crafting table or furnace in reach |
| `g.craft("planks")` | craft by name: planks, sticks, table, wooden_pick, stone_pick, torch, furnace, iron_pick |
| `g.smelt()` | service the open furnace (take output, load ore + coal) |

## Sensing

- `g.inv()` - what you actually hold.
- `g.nearest("log")`, `g.nearest("coal")`, `g.nearest("stone")` - `(x, y, z, distance)`.
- `g.crosshair()` - the block your ray hits and how far.
- `g.view()` - ASCII of the 64x36 semantic camera (`T` log, `#` stone, `C` coal).
- `g.block_at(x, y, z)` - only sees the nearest 256 blocks the obs reports.

## Rules the world actually enforces

- **Drops do not teleport.** Breaking a block spawns an item where the block
  was; you pick it up only within 1 block horizontally. Dig, then walk over it.
- **A block you stand inside cannot be dug.** If the crosshair reports 0.5m,
  back off - aim at something 1.5-3m away.
- **3x3 recipes need an open table**: craft a table, `g.place()` it on the
  ground, `g.interact()`, then craft the pick.
- Digging is real-time: wood by hand is ~60 ticks, stone by hand far longer.
  Use `g.mine(120)` rather than many short bursts.
- Nothing is undoable. There is no respawn shortcut: if health hits 0 the
  episode is over.

## The chain

logs -> planks -> sticks + table -> wooden pick -> cobblestone -> stone pick
-> coal -> torches -> (iron ore -> furnace -> iron ingot -> iron pick).

Report what you did, what surprised you, and where the world disagreed with
your Minecraft intuition.
