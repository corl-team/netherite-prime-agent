# Notes on the netherite world (seed 0)

## Coordinate / aiming conventions (verified)
- yaw: 0 = +Z (south), 90 = -X (west), 180 = -Z (north), 270 = +X (east).
- pitch: 0 = horizontal, positive = down, 90 = straight down.
- Use `-atan2(dx, dz)` for yaw and `-atan2(dy, hdist)` for pitch.
- Player eye level is roughly feet_y + 1.62.
- When reading `obs["yaw"]`, treat it modulo 360; the engine accumulates rotation.

## Starting state
- Spawn at (8.5, 79.0, 8.5) inside a tree canopy.
- The canopy is made of leaves (id 18) and log trunks (id 17).
- Under the canopy is mostly empty space, then grass/dirt/stone ground around y = 71-73.
- The column directly under spawn is empty down to a small stone platform at (8, 70, 8).
- Coal ore (id 16) is visible in `obs["coal"]` deep underground, e.g. around y = 60-65.

## Block behavior (corrected in episode 3)
- Grass (id 2) and dirt (id 3) break by hand and drop dirt items (id 3 in hotbar).
- **Logs (id 17) DO drop log items** when broken by hand, but the item entity must be
  close enough to the player to be picked up.  Episode 1/2 assumed they did not drop
  because checks were made from too far away or without waiting for collection.
- Leaves (id 18) break by hand and usually drop nothing, but they can be cleared to
  move through the canopy.
- Stone (id 1) breaks very slowly by hand and gives **no cobblestone**.  A pickaxe
  (wooden or stone) is required to obtain cobblestone.
- Coal ore (id 16) can only be mined usefully with a pickaxe; it drops coal items.

## Items / crafting (verified)
- `inv_counts` indices: [log, planks, stick, cobblestone, table, w_pick, s_pick, coal, torch].
- Craft ids: 0 planks, 1 sticks, 2 crafting table, 3 wooden pick, 4 stone pick, 5 torch,
  6 furnace, 7 iron pick.
- Wood/stone pickaxes require an open crafting table (place the table, then `interact`).
- Torches are crafted in the 2x2 inventory grid (or in a table) with 1 coal + 1 stick
  yielding 4 torches; item/block id 50.
- Hotbar item ids include: 3 dirt, 5 planks, 17 log, 50 torch, 58 crafting-table item,
  270 wooden pickaxe, 274 stone pickaxe, 280 stick.

## Episode 3 progression recipe
This is the verified path to craft a stone pickaxe, mine coal, craft torches and place one:
1. Leave the canopy.  The quickest way found is to look straight down and hold `attack`
   + `jump` while breaking leaves; once on a solid surface, clear nearby leaves/log
   columns and harvest logs (id 17) by breaking trunks while standing close.
2. Craft logs -> planks (`craft:0`), craft a crafting table (`craft:2`), select the
   table in the hotbar and `use` it on a solid face.
3. Open the placed table (`interact`), craft sticks (`craft:1`) and a wooden pickaxe
   (`craft:3`).
4. Mine stone with the wooden pickaxe to obtain at least 3 cobblestone items.
5. With the crafting table still open, craft a stone pickaxe (`craft:4`).
6. Mine coal ore (id 16) with the stone pickaxe to obtain coal.
7. Craft sticks (`craft:1`) if needed, then craft torches (`craft:5`).
8. Select the torch in the hotbar and `use` it on a solid block face.

## World features
- The magma_game `--villages on` flag is **not wired** in the current binary, so villages
  are not a reliable source of loot.  The normal wood -> stone tool route works and is
  the intended way to obtain a pickaxe.
- Surface surveys within ~130 blocks of spawn did **not** find chests, crafting tables,
  furnaces, wool, or cobblestone exposed as topmost blocks.  Chest loot is therefore not
  a viable early-game route.
- The `blocks` array reports the topmost block per nearby column, so sub-surface ores or
  torches placed on walls will not always appear in it.  Use `obs["coal"]`, `obs["logs"]`,
  and the camera/ray helpers when direct line-of-sight is needed.

## Movement rules of thumb
- The leaf canopy is mostly solid and very obstructive to horizontal travel.
- Looking straight down and holding attack clears leaves below and drops the player.
- Placing blocks to rise ("towering") requires jumping so the new block is placed at the
  next integer y while the player is briefly above the current block.  Be careful to
  select the correct hotbar slot before using a block item; using with a log selected
  will place a log and consume it.
- Forward motion may be blocked by a block at head or foot height that is not on the
  exact crosshair ray; mine the wall at a slight downward angle to clear a path.

## Helpers that earned their place (see tools.py)
- `norm_yaw` / `set_yaw_pitch`: turn to exact aim without spinning on accumulated yaw.
- `select_item`: switch to a hotbar slot by item id.
- `pillar_up`: tower with a block item.
- `harvest_logs`: gather logs safely.
- `craft_all_planks`, `craft_table`, `craft_sticks`, `craft_wooden_pickaxe`,
  `craft_stone_pickaxe`, `craft_torches`: recipe shortcuts.
- `place_block_on_top` and `place_torch`: place blocks/torches on solid surfaces.
- `dig_straight_down`: controlled descent while mining.
