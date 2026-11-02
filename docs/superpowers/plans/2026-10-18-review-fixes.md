# Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix the High and Medium findings of `CODE_REVIEW_2026-10-18.md` (worktree root, untracked), then triage the Low findings.

**Architecture:** Bugs first, then the shared occupancy model the bugs point at, then injected randomness, then the structural refactors (actions, events, GameState split), then performance (board caching as the user asked: the stats and log boards refresh separately from map frames), then test hygiene and the window fix, then the Lows.

**Tech Stack:** Python 3.12+, pygame-ce, unittest, Hypothesis.

**Spec:** `CODE_REVIEW_2026-10-18.md` (the finding text, with file:line, is each task's authority; section numbers below refer to it) plus the user's request: "fix the high and medium findings with subagents, have a sonnet agent look at the low finding. Regarding the redrawing every frame, see if its possible to have some parts like the stats and log frame refresh seperately from the game loop to see if that can improve performance."

## Global Constraints

- `game/` stays standard-library only and must not import `render/`; pygame only in render modules.
- **No behaviour change to gameplay** beyond what a finding asks for. Gold balance tests (120 ± 12) and every existing behavioural test keep passing; tests that only pinned private structure may be rewritten to assert the same behaviour.
- After every task: `.venv/bin/python -m unittest discover -s tests`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/pyright`, `.venv/bin/vulture` all clean.
- **Do not commit, push or stash** (user instruction). Implementers never dispatch subagents.
- Test-first for every bug: a failing test that reproduces it, then the fix.
- Keep CLAUDE.md accurate for anything a task changes structurally (new modules, moved names).

## Review Focus

1. Arrows and every other line-of-effect rule after the occupancy refactor: doors, the shopkeeper, chests, shrines, piles. A "no two blocking entities share a tile" invariant in the Hypothesis playthrough.
2. Seeded reproducibility: two `GameState(seed=s)` runs fed the same actions produce identical states.
3. The cached boards must never show stale numbers: every state change the boards display (HP, gold, gear, belt, boons, depth, class, messages, quiver, dodge) invalidates them. Test: mutate each, redraw, compare pixels with an uncached paint.
4. Window resize, fullscreen toggle and font change invalidate board caches.
5. The single event stream must keep camera beats, sounds and parries in exactly today's order (existing camera/loop tests are the oracle).

---

### Task 1: Bug fixes (review §1 items 1, 4, 5, 6, 7)
Files: `game/archery.py`, `game/state.py`, `render/pygame_render.py` (`choose_class`), `main.py` (`play`), tests.
- Arrows (aim arrow and volley side arrows) stop at a closed door like a wall (`archery._fly`, `_volley_starts`); test a door in the lane: no hit, arrow stops before/at the door per how walls are handled.
- One `GameState._arrive(x, y)` helper used by walking and by the hop's landing tile: picks up gold and arrows (chest/shrine/shopkeeper stay walking-only as now). Test: hop landing on arrows picks them up.
- `choose_class` returns `None` on `q`/window close; `main.play` treats None as quit to title / exit as the hint says. Test via the scripted renderer pattern in tests/test_pygame_render.py.
- `drink` at full HP is refused: log line ("You are already at full health."), no potion used, no turn. Test.
- `end_turn()` does nothing after an action that took no turn (track the last `handle_action` result); re-run tests/test_properties.py and fix what it surfaces. Test.

### Task 2: Shared occupancy model (High §2.1, §1 item 3; Medium spawn/item/state chest bugs)
Create `game/level.py` per §2.1's recommendation (a `Level` or equivalent functions over the state: `blocking_at(x, y, purpose)` with purposes for walking/monster move, arrow flight, reach, knockback, spawn placement; `occupant(x, y)`; `free_tiles(room, occupied)`). Route every site in the §2.1 table through it; one `occupied` set flows through `spawn_level` → `spawn_chests` → `place_shrine` → shop room. Chests never spawn under monsters (test over seeded floors: zero overlaps). Draw order: blocking creatures paint above chests/piles regardless of list order. Add the invariant to tests/test_properties.py. Keep each site's *intended* rule (e.g. arrows pass the shopkeeper today — rule it explicitly in the purpose table and document it).

### Task 3: Injected randomness (§1 item 9, §2.5, monster.py:173, dungeon.py:259-270)
`GameState(..., seed=None)` owns `self.rng = random.Random(seed)` and passes it to generation (`generate_level`/`generate_dungeon`, which take `rng`), spawning, chests, shrine, shop, monster AI (`take_turn(..., rng)`), combat (crit, dodge), summons, drops. No module-level `random.*` calls remain in `game/` except as defaults for direct callers. `gold.full_clear_gold_split` stops saving/restoring global state. Replace test patching of `BASE_CRIT_CHANCE`/`_dodged`/`dodge_chance` where an rng stub is cleaner (keep tests' intent). Test: two seeded runs with the same actions are identical; balance test still 120 ± 12.

### Task 4: Actions into game/, archery's private writes (§2.4, archery.py:109)
Move `Action` to `game/actions.py`; `render/base.py` re-exports or imports it; `game/state.py` uses the constants instead of string literals. Add a test that every `Action` is handled by `GameState.handle_action` (or explicitly listed as renderer-only, e.g. QUIT). Give archery a public API on the state (e.g. `state.grant_free_turn()`, reload/quiver methods) instead of writing `_free_turn` and other private fields.

### Task 5: One event stream (§2.3)
Replace `combat_events`, `shots`, `parries`, `sound_events` with one ordered `events` list of typed records and one serial; a `Shot` owns its `Hit`s, a `Parry` names its riposte. Update `camera.Director`, `SoundBoard`, the renderer and tests; each consumer keeps its own cursor. Existing camera/loop/sound tests are the behavioural oracle — beats and sounds must come out in the same order.

### Task 6: Split GameState (§1 item 10, §2.2)
Extract a `game/combat.py` (or `game/fight.py` — `combat.py` already holds the event records; pick a name and keep records where they fit) with attack/crit/dodge/parry/riposte as functions over explicit inputs, and a turn controller module (`handle_action` dispatch, `end_player_phase`, `step_monster_phase`). `GameState` remains the composition root and public facade so `main.py` and the renderer don't change. Target: state.py well under half its current size. Pure refactor: no behaviour change.

### Task 7: Performance — boards refresh separately; FOV; corridors (§1 item 8, §4, state.py:1178, dungeon.py:160-211, §5 slow tests)
- **Boards (user request):** render the stats board and the log board to their own cached surfaces, rebuilt only when what they show changes (a signature of the displayed values, or explicit dirty flags set by GameState changes) or the layout/font changes; every frame — including camera beats, pans and impacts — only blits them. Measure frame time before/after at 870x489, 1920x1080, 3840x2160 in glyph and tile mode with the review's method and record the numbers in the report and in CLAUDE.md. Frame-pace `_play` with `pygame.time.Clock.tick` instead of a fixed sleep after paint. Cap/unify the ad hoc caches (§2.6) where touched.
- FOV computed once per player half (and when the player moves), not after every monster turn; `update_visibility` touches only lit cells. Same visible results (tests).
- `route_corridor`: A* (or a cost grid without per-edge allocations) with identical corridor rules; existing dungeon tests and the 2000-map routing checks pass; move the slow statistical placement tests to synthetic rooms where they test a placement function. Record suite time before/after.

### Task 8: Renderer tests assert output, not private calls (§5)
Rewrite the tests in tests/test_pygame_render.py that patch private paint methods to record calls so they assert on output pixels or on the Director's beat list instead, keeping each test's intent. No production changes beyond what testability requires.

### Task 9: First window size on a 1080p desktop (render/ui.py, review finding ~line 217 of §3)
Honour `DESKTOP_SHARE` when the desktop is 1920x1080 (the first window must not be the whole desktop). Test with a faked desktop size.

### Task 10: Low findings (Sonnet)
A Sonnet agent reads every Low finding in the review, fixes the ones that are clearly correct and contained (stale docstrings, dead/test-only production code, config range validation, capping `messages`, `.gitignore` leftovers, README gold/shops, tileset warnings, `noticeboard._planks` guard, vulture on production paths), and writes a triage table (fixed / not fixed + reason) to the report.
