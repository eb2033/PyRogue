# Split Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the window's side panel into a sectioned stats board (right of the map) and a separate log board (a strip under the map), with the controls and potion belt drawn as tables.

**Architecture:** `render/ui.py`'s `Layout` gains a third region, the log board, fitted alongside the map and stats board in glyph, tile and stacked modes. `paint_panel` paints the stats board only; a new `paint_log` paints the log board. Both reuse `render/noticeboard.paint`. Table drawing is pygame line/rect work inside `ui.py`.

**Tech Stack:** Python 3.12+, pygame-ce (pinned in requirements.txt), unittest.

**Spec:** `docs/superpowers/specs/2026-10-17-gold-sound-ui-design.md` §1.

## Global Constraints

- `game/` stays standard-library only; pygame only in `render/pygame_render.py`, `input_map.py`, `ui.py`, `screens.py`, `tileset.py` (plus any new render module nothing on the stdlib path imports).
- Run everything with the worktree venv: `.venv/bin/python -m unittest discover -s tests`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/pyright`, `.venv/bin/vulture`. All must be clean at the end of every task.
- **Do not `git commit` or `git push`** (user instruction for this build). Leave changes in the working tree.
- Map cells go through `layout.map_cell_to_pixel` / the renderer's `_map_cell_rect`; text goes through `Canvas`.
- The panel must never overlap the map, in any layout, at any window size the existing layout tests sweep (`tests/test_ui.py` `SIZES`).

## Review Focus

1. Tiny windows (the smallest size in `SIZES`, and 320x240): the log board must not overlap the map or the stats board and nothing may raise. Test: `test_log_board_never_overlaps_map_or_panel` sweeps every size, both modes.
2. Stacked (portrait) windows: log board goes under the stats board, still inside the grid. Test: `test_stacked_log_board_is_under_the_panel`.
3. A long message wider than the strip still wraps and never draws outside the log page. Test: `test_long_message_wraps_inside_the_log_page`.
4. Archer vs warrior controls tables differ by exactly the move/shoot rows. Test: `test_controls_rows_by_class`.
5. Quick Hands (4 belt slots) still fits the belt row inside the page width. Test: `test_four_belt_boxes_fit_the_page`.

---

### Task 1: Log board geometry in `Layout`

**Files:**
- Modify: `render/ui.py` (constants block lines ~35-82; `Layout` lines 85-411)
- Test: `tests/test_ui.py` (LayoutTest, TileLayoutTest, StackedLayoutTest, MessageLogTest)

**Interfaces:**
- Produces (all on `Layout`, all usable after `fit()`):
  - `log_rect() -> pygame.Rect` — pixel rect of the log board (frame included).
  - `log_page_rect() -> pygame.Rect` — the parchment page inside it.
  - `log_text_x: int`, `log_text_y: int` (properties, grid cells) — where log text row 0 starts; row 0 is the `LOG` header, messages from row 1.
  - `log_text_width() -> int` — text columns on the log page.
  - `log_lines() -> int` — message rows on the log page, `MIN_LOG_LINES`..`LOG_LINES` (same constants, same meaning: at least 4, at most 12, more when the window has spare rows).
  - `panel_rows()` / `panel_rect()` / `page_rect()` / `text_rect()` now describe the **stats board only**, which is a fixed `PANEL_ROWS = PANEL_PAD_TOP + PANEL_TEXT_ROWS + PANEL_PAD_BOTTOM` tall (`PANEL_TEXT_ROWS` from Task 2; define it here as `25`). `PANEL_MAX_ROWS` is deleted.
  - New constants: `LOG_PAD_X = PANEL_PAD_X`, `LOG_PAD_TOP = 2`, `LOG_PAD_BOTTOM = PANEL_PAD_BOTTOM`, `LOG_BOARD_MIN_ROWS = LOG_PAD_TOP + 1 + MIN_LOG_LINES + LOG_PAD_BOTTOM`, `LOG_BOARD_MAX_ROWS` likewise with `LOG_LINES`, `LOG_GAP = 1` (rows between map bottom and log board).
- Placement rules:
  - **Side by side:** log board directly under the map (`LOG_GAP` rows below the map's last pixel row, snapped to the text grid), left edge on the first text column at or right of the map's left pixel, width = the whole text columns that fit inside the map's pixel width. Stats board stays where it is today, right of the map.
  - **Stacked:** map, then stats board (as today), then the log board `STACK_GAP` rows under the stats board, starting at the stats board's column, width `max(PANEL_COLS, columns under the map)` clipped to the grid.
  - **Glyph mode:** grid grows to hold the log board: side by side `rows >= map_height + LOG_GAP + LOG_BOARD_MIN_ROWS` and `>= PANEL_ROWS`; stacked `rows >= map_height + STACK_GAP + PANEL_ROWS + STACK_GAP + LOG_BOARD_MIN_ROWS`. Spare rows (up to `LOG_BOARD_MAX_ROWS`) go to the log.
  - **Tile mode:** `_block_size` adds the log board's height under the map (side by side) or under the panel (stacked); `_grow_tile_font` and the full-log centring use `LOG_BOARD_MAX_ROWS`.
  - The stacked-vs-side choice keeps its current rule (bigger map cells win).

- [ ] **Step 1: Write the failing tests** in `tests/test_ui.py` (adapt existing helpers `fitted(size, tiles)` and `SIZES`):

```python
def test_log_board_never_overlaps_map_or_panel(self):
    for tiles in (False, True):
        for size in SIZES + [(320, 240)]:
            layout = fitted(size, tiles)
            log, m, p = layout.log_rect(), layout.map_rect(), layout.panel_rect()
            self.assertFalse(log.colliderect(m), (size, tiles))
            self.assertFalse(log.colliderect(p), (size, tiles))


def test_side_by_side_log_board_is_under_the_map_and_as_wide(self):
    layout = fitted((1920, 1080), True)
    self.assertFalse(layout.stacked)
    log, m = layout.log_rect(), layout.map_rect()
    self.assertGreaterEqual(log.top, m.bottom)
    self.assertLessEqual(m.left, log.left)
    self.assertLessEqual(log.right, m.right)
    self.assertGreater(log.width, m.width - 2 * layout.cell_w)


def test_stacked_log_board_is_under_the_panel(self):
    for tiles in (False, True):
        layout = fitted((600, 1400), tiles)
        self.assertTrue(layout.stacked)
        self.assertGreaterEqual(layout.log_rect().top, layout.panel_rect().bottom)


def test_log_lines_between_min_and_cap(self):
    for tiles in (False, True):
        for size in SIZES:
            self.assertTrue(ui.MIN_LOG_LINES <= fitted(size, tiles).log_lines() <= ui.LOG_LINES)


def test_log_page_holds_the_log_text(self):
    layout = fitted((1920, 1080), True)
    self.assertTrue(layout.log_rect().contains(layout.log_page_rect()))
```

Update the existing tests that assume the log lives on the panel (`MessageLogTest`, the `PANEL_ROWS`/`PANEL_MAX_ROWS` uses at lines ~67-73, ~166-172, ~240-257) to the new meaning: `PANEL_ROWS` is the stats board's fixed height; log-length tests read `log_lines()` from the log board.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_ui -v 2>&1 | tail -20`
Expected: FAIL / ERROR on `log_rect` (AttributeError).

- [ ] **Step 3: Implement the geometry** in `render/ui.py` per the Interfaces block. Keep `_place_stacked_tiles`' rule that nothing overlaps the map even if it runs off the bottom; the log board follows the same rule relative to the stats board. `page_rect` for the log board uses the same inflate/clip recipe as the stats board's.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_ui -v 2>&1 | tail -5`
Expected: `OK` (PanelTest row tests may still fail until Task 2 — if so, they are the only failures).

---

### Task 2: Sectioned stats board, controls table, belt boxes, and `paint_log`

**Files:**
- Modify: `render/ui.py` (`paint_panel` ~467-512, `_paint_belt` ~548-565, row constants)
- Modify: `render/pygame_render.py:754` (call `ui.paint_log` after `ui.paint_panel`)
- Test: `tests/test_ui.py` (PanelTest, NoticeboardTest, PaintTest), any test in `tests/test_pygame_render.py` that asserts panel/log pixels (grep `LOG_TOP|CONTROLS_TOP|BELT_ROW|GEAR_TOP|log_lines`)

**Interfaces:**
- Consumes: Task 1's `log_rect`, `log_page_rect`, `log_text_x`, `log_text_y`, `log_text_width`, `log_lines`.
- Produces:
  - Row constants (text rows on the stats page, relative to `text_y`):
    `HEADER_ROW = 0` (bold `'{Class} - Depth {n}'`), `HP_ROW = 1`, `STATS_ROW = 2` (`stats_text`), `ITEMS_ROW = 3` (`items_text`), `GOLD_ROW = 4` (**left blank**; the gold plan fills it), `GEAR_TOP = 6` (header `'GEAR'`; weapon name/stats rows 7-8, armor 9-10), `BELT_TOP = 12` (header `'BELT'`), `BELT_ROW = 13` (slot boxes), `BOONS_TOP = 15` (header `'BOONS'`, text row 16, both painted only when a boon is held), `CONTROLS_TOP = 18` (header `'CONTROLS'`, table rows 19..24), `PANEL_TEXT_ROWS = 25`. `LOG_TOP` and `BOONS_ROW` are deleted.
  - Section headers are bold ink with a 1px `palette.PAGE_EDGE`-darker rule under the header row's text (a horizontal line across `text_width()` at the row's bottom).
  - `controls_rows(char_class: str) -> list[tuple[str, str]]`: archer `[('wasd', 'move'), ('arrows', 'shoot'), ('space', 'wait'), ('e', 'descend'), ('h', 'drink'), ('q', 'ability')]`; any other class `[('wasd/arrows', 'move'), ('space', 'wait'), ('e', 'descend'), ('h', 'drink'), ('q', 'ability')]`.
  - Controls table: one grid row per binding starting at `CONTROLS_TOP + 1`; key column `CONTROLS_KEY_COLS = 11` text columns wide, shaded `palette.PAGE_EDGE`, key text bold and centred; action text left-aligned one column into the second cell; 1px cell borders in a new `palette.TABLE_RULE = (185, 167, 127)`.
  - Belt: `belt_capacity(player)` equal-width boxes across `text_width()` on `BELT_ROW`, 1px `TABLE_RULE` borders, each slot's `belt_slot_label` centred in its rarity ink (empty: `'—'` in plain ink — change `belt_slot_label`'s empty value only if it isn't already a dash; don't change game logic). Slot 0 gets a 2px `palette.INK` outline. No `[ ]` brackets, no `Belt:` label, no second row.
  - `paint_log(canvas: Canvas, state) -> None`: noticeboard at `log_rect()`/`log_page_rect()`, bold `'LOG'` header with the same rule, then `log_rows(state.messages, log_text_width(), log_lines())` from row 1.
  - `paint_panel` no longer paints the log.

- [ ] **Step 1: Write the failing tests** in `tests/test_ui.py` `PanelTest` (use its existing `row_rect`/`pixels`/`row_bytes` helpers; add a `log_row_rect(i)` helper mirroring `row_rect` on `log_text_x/log_text_y`):

```python
def test_every_section_row_is_painted(self):
    # header, HP, stats, items, the four section headers, a weapon row, the belt, first control
    for row in (
        ui.HEADER_ROW,
        ui.HP_ROW,
        ui.STATS_ROW,
        ui.ITEMS_ROW,
        ui.GEAR_TOP,
        ui.GEAR_TOP + 1,
        ui.BELT_TOP,
        ui.BELT_ROW,
        ui.CONTROLS_TOP,
        ui.CONTROLS_TOP + 1,
    ):
        self.assertGreater(self.pixels(self.row_rect(row)), 0, row)


def test_gold_row_and_boons_are_blank_without_gold_or_boons(self):
    for row in (ui.GOLD_ROW, ui.BOONS_TOP, ui.BOONS_TOP + 1):
        self.assertEqual(self.pixels(self.row_rect(row)), 0, row)


def test_controls_rows_by_class(self):
    self.assertEqual(ui.controls_rows('archer')[:2], [('wasd', 'move'), ('arrows', 'shoot')])
    self.assertEqual(ui.controls_rows('warrior')[0], ('wasd/arrows', 'move'))
    self.assertEqual(ui.controls_rows('archer')[2:], ui.controls_rows('warrior')[1:])


def test_controls_table_has_one_row_per_binding(self):
    # warrior: 5 bindings -> rows CONTROLS_TOP+1..+5 painted, +6 blank
    for i in range(1, 6):
        self.assertGreater(self.pixels(self.row_rect(ui.CONTROLS_TOP + i)), 0, i)
    self.assertEqual(self.pixels(self.row_rect(ui.CONTROLS_TOP + 6)), 0)


def test_first_belt_slot_is_outlined_in_ink(self):
    # the 2px INK outline: INK pixels on the belt row's left box edge
    ...  # count palette.INK pixels in the first box's left 2 columns of the BELT_ROW rect > 0


def test_belt_is_one_row(self):
    self.assertEqual(self.pixels(self.row_rect(ui.BELT_ROW + 1)), 0)


def test_four_belt_boxes_fit_the_page(self):
    # give the player the quick_hands boon, paint, assert nothing outside text_rect on BELT_ROW
    ...


def test_panel_no_longer_paints_the_log_and_paint_log_does(self):
    self.state.log('hello there')
    ui.paint_panel(self.canvas, self.state)
    self.assertEqual(self.pixels(self.log_row_rect(1)), 0)
    ui.paint_log(self.canvas, self.state)
    self.assertGreater(self.pixels(self.log_row_rect(1)), 0)


def test_long_message_wraps_inside_the_log_page(self):
    self.state.log('word ' * 80)
    ui.paint_log(self.canvas, self.state)
    # every non-paper pixel of the log text area lies inside log_page_rect
    ...
```

The `...` bodies follow the existing PanelTest pixel-counting pattern (see `test_belt_shows_three_slots_each_in_its_rarity_ink`, `test_panel_paints_nothing_on_the_map`). Rewrite the existing PanelTest/NoticeboardTest tests that name `LOG_TOP`, `BOONS_ROW`, the old `CONTROLS_TOP + 2` text rows or the `Belt: [..]` text, keeping each one's intent (rarity inks, HP bar colours, quiver on items row, class/depth live, dodge shown for leather, log fills its rows, board drawn behind text, board cached).

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_ui -v 2>&1 | tail -20`
Expected: FAIL on `HEADER_ROW` / `controls_rows` / `paint_log` missing.

- [ ] **Step 3: Implement** the Interfaces block in `render/ui.py`; add `TABLE_RULE` to `render/palette.py`; call `ui.paint_log(self.canvas, state)` right after `ui.paint_panel(self.canvas, state)` in `PygameRenderer._paint_game`.

- [ ] **Step 4: Run the full suite and linters**

Run: `.venv/bin/python -m unittest discover -s tests 2>&1 | tail -3 && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pyright && .venv/bin/vulture`
Expected: `OK`, and every linter clean.

- [ ] **Step 5: Look at it.** Run `SDL_VIDEODRIVER=dummy .venv/bin/python - <<'EOF'` with a script that builds `PygameRenderer(40, 20, tileset=Tileset(resource_path('assets')))`, a `GameState(40, 20)` with a few log lines and a potion on the belt, calls `renderer.draw(state)` and `pygame.image.save(renderer.canvas.surface, '<job tmp>/panel.png')` at 1920x1080 and at 900x1400 (stacked); open both PNGs with the Read tool and confirm the layout matches the spec (two boards, sections, tables, outlined first belt slot). Fix anything off.

- [ ] **Step 6: Do not commit** (user instruction).
