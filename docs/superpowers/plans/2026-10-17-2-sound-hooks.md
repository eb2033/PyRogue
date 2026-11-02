# Sound Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Named sound slots that fire on game events and play `assets/sounds/<slot>.ogg|.wav` when such a file exists — silent otherwise. No audio files ship.

**Architecture:** `game/` records `SoundEvent(serial, slot)` values in `GameState.sound_events` (same lifetime as `combat_events`). A new `render/sound.py` `SoundBoard` plays events it hasn't played yet; `PygameRenderer.draw` calls it once per frame, so each sound lands with the frame that shows its event. Mixer failure or a missing file is silent.

**Tech Stack:** Python 3.12+, pygame-ce `pygame.mixer`, unittest.

**Spec:** `docs/superpowers/specs/2026-10-17-gold-sound-ui-design.md` §2.

## Global Constraints

- `game/sound.py` and every change under `game/` are standard-library only.
- `render/sound.py` may import pygame; only `render/pygame_render.py` and `main.make_renderer` (inside the function, like the existing pygame imports) may import it.
- Sound must never crash or block the game: mixer init failure, no audio device, a missing/corrupt file → silent, logged nowhere.
- `SOUND=0` (read in `main.make_renderer` via `game.settings.env_int('SOUND', 1)`) disables sound.
- Same test/lint commands as plan 1. **Do not commit or push.**

## Review Focus

1. Headless CI / no audio device: `pygame.mixer.init()` raises → `SoundBoard.enabled` False, `play_new` is a no-op. Test: `test_mixer_failure_is_silent`.
2. The same frame drawn twice (renderer redraws on expose/resize) must not replay a sound. Test: `test_events_play_once_across_redraws`.
3. A corrupt sound file → silent, and later slots still play. Test: `test_corrupt_file_is_skipped`.
4. Several monsters noticing in one round → one `enemy_alert`. Test: `test_two_monsters_noticing_alert_once`.
5. A bump that's blocked (wall) plays no footsteps. Test: `test_bumping_a_wall_is_silent`.

---

### Task 1: Slots and event recording in `game/`

**Files:**
- Create: `game/sound.py`
- Modify: `game/state.py` (init ~144-151, `handle_action` ~279-281, `try_move_player` ~525-562, `hop` ~419-442, `melee` ~634-659, `step_strike` ~666-686, `open_chest` ~724-750, `try_descend` ~835-842, `step_monster_phase` ~1000-1042, `_monster_melee` ~471, `_monster_shot` ~1044, `end_player_phase` ~976)
- Modify: `game/archery.py:shoot` (after the quiver is spent, before the arrow flies)
- Test: `tests/test_sound_events.py` (new)

**Interfaces:**
- Produces (`game/sound.py`):
  - Slot name constants and `SLOTS: tuple[str, ...]` = `('attack_heavy', 'attack_light', 'attack_bow', 'attack_crossbow', 'monster_attack_goblin', 'monster_attack_orc', 'door', 'descend', 'chest_open', 'enemy_alert', 'gold_pickup', 'footsteps')`.
  - `SoundEvent = namedtuple('SoundEvent', 'serial slot')`.
  - `LIGHT_MELEE = frozenset({'dagger', 'rapier'})`; `melee_slot(weapon) -> str`: `'attack_light'` if `weapon` is not None and `weapon.kind in LIGHT_MELEE`, else `'attack_heavy'` (the starting `'weapon'` kind and no weapon included).
  - `shot_slot(weapon) -> str`: `'attack_crossbow'` if `weapon.kind == 'heavy_crossbow'`, else `'attack_bow'`.
  - `MONSTER_ATTACK_SLOTS = {'goblin': 'monster_attack_goblin', 'orc': 'monster_attack_orc', 'goblin_archer': 'attack_bow'}`; `monster_attack_slot(monster) -> str` looks up `monster.kind` (a boss uses its kind's slot; unknown kind → `'monster_attack_goblin'`).
- Produces (`GameState`):
  - `self.sound_events: list[SoundEvent]` — cleared in `handle_action` together with `combat_events` / `shots` / `parries`.
  - `self._sound_serial: int` — its own counter (do **not** reuse `next_event_serial`; Hit serials must stay unchanged). Never reset, not even by `next_level`.
  - `def sound(self, slot: str) -> None` — appends `SoundEvent(next serial, slot)`.
- Hook points (spec table):
  - `footsteps`: in `try_move_player`, after `self.player.move(...)` when the position changed; `hop` emits one `footsteps` if it moved at all. Never on a bump-attack, a refused move, or bumping a wall.
  - `door`: in `try_move_player`, after the move, if the player now stands on `DOOR` (in addition to `footsteps`).
  - `attack_heavy`/`attack_light`: once per player swing — in `melee` (first strike) and each extra strike in `step_strike`. The Great Sword's cleave is part of the same swing: no extra sound.
  - `attack_bow`/`attack_crossbow`: once per `archery.shoot` that actually fires (not refused), via `shot_slot(player.weapon)`.
  - `monster_attack_*`: in `_monster_melee` at the swing (a parried or dodged blow still swings); `_monster_shot` emits `monster_attack_slot(monster)` (= `'attack_bow'` for the goblin archer).
  - `chest_open`: in `open_chest`, after the belt-refusal check, before contents are rolled.
  - `descend`: in `try_descend`, after `next_level()` succeeds.
  - `enemy_alert`: in `step_monster_phase`, a monster whose `chasing` was False before `take_turn` and is True after (or which attacked/shot this turn while not chasing before) triggers it, at most once per round: an `_alerted_this_round` flag reset in `end_player_phase`.
  - `gold_pickup` is reserved here; the gold plan emits it.

- [ ] **Step 1: Write the failing tests** in `tests/test_sound_events.py` (build states the way `tests/test_game.py` does — `GameState(WIDTH, HEIGHT)` then place entities / carve tiles by hand; `random.seed` where rolls matter):

```python
def slots(state):
    return [e.slot for e in state.sound_events]


def test_slot_tables(self):
    self.assertEqual(len(sound.SLOTS), 12)
    self.assertEqual(sound.melee_slot(Item(0, 0, 'dagger')), 'attack_light')
    self.assertEqual(sound.melee_slot(Item(0, 0, 'rapier')), 'attack_light')
    for kind in ('war_axe', 'great_sword', 'sword_shield', 'spear', 'weapon'):
        self.assertEqual(sound.melee_slot(Item(0, 0, kind)), 'attack_heavy')
    self.assertEqual(sound.melee_slot(None), 'attack_heavy')
    self.assertEqual(sound.shot_slot(Item(0, 0, 'heavy_crossbow')), 'attack_crossbow')
    for kind in ('longbow', 'volley_bow', 'sling', 'hunters_bow', 'quickdraw'):
        self.assertEqual(sound.shot_slot(Item(0, 0, kind)), 'attack_bow')
    self.assertEqual(sound.MONSTER_ATTACK_SLOTS['goblin_archer'], 'attack_bow')


def test_a_step_plays_footsteps(self): ...  # move onto floor -> ['footsteps']
def test_bumping_a_wall_is_silent(self): ...  # move into '#' -> []
def test_stepping_into_a_doorway_plays_door(self): ...  # -> ['footsteps', 'door']
def test_bump_attack_plays_the_weapon_sound(
    self,
): ...  # dagger -> 'attack_light' first, no 'footsteps'
def test_rapier_plays_once_per_strike(self): ...  # after resolve_player_phase: two 'attack_light'
def test_archer_shot_plays_bow_and_crossbow(self): ...
def test_refused_shot_is_silent(self): ...  # empty quiver -> no attack sound
def test_chest_open_plays(self): ...
def test_descend_plays(self): ...  # stand on '>' , handle_action('descend') -> 'descend' in slots
def test_monster_attack_slots(self): ...  # goblin/orc adjacent, end_turn -> their slot
def test_goblin_archer_shot_uses_attack_bow(self): ...
def test_two_monsters_noticing_alert_once(self): ...
def test_sound_events_cleared_when_the_player_acts(self): ...
def test_serials_only_grow_across_levels(self): ...
def test_hit_serials_unchanged_by_sound(self):  # combat_events serials are 1,2,... as before
    ...
```

Each `...` is the arrange/act/assert its name says, with the slot lists above as the asserted values.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_sound_events -v 2>&1 | tail -20`
Expected: ImportError on `game.sound`.

- [ ] **Step 3: Implement** `game/sound.py` and the hook points.

- [ ] **Step 4: Run the full suite** (the hooks must not change any existing behaviour)

Run: `.venv/bin/python -m unittest discover -s tests 2>&1 | tail -3`
Expected: `OK`.

---

### Task 2: `SoundBoard` and renderer wiring

**Files:**
- Create: `render/sound.py`
- Modify: `render/pygame_render.py` (`__init__` gains `sound=None`; `draw` ~484)
- Modify: `main.py:make_renderer` (~31-48)
- Modify: `assets/ASSETS.md` (a short "Sounds" note: `assets/sounds/<slot>.ogg|.wav`, the 12 slot names, every file added later needs a row here)
- Test: `tests/test_sound.py` (new; skips without pygame like the other pygame suites, sets `SDL_VIDEODRIVER=dummy` and `SDL_AUDIODRIVER=dummy`)

**Interfaces:**
- Consumes: `game.sound.SLOTS`, `SoundEvent`; `GameState.sound_events`.
- Produces (`render/sound.py`):
  - `class SoundBoard:` `__init__(self, directory: pathlib.Path | None, enabled: bool = True)`. Calls `pygame.mixer.init()` inside `try/except Exception` → on failure `self.enabled = False`. Never raises.
  - `self.enabled: bool`; `self.last_serial: int = 0`.
  - `def sound_for(self, slot: str) -> 'pygame.mixer.Sound | None'` — lazily loads `directory/<slot>.ogg`, else `.wav`; caches the result **including None** (a missing or unloadable file is looked up once).
  - `def play_new(self, events: list[SoundEvent]) -> None` — for each event with `serial > last_serial`, in order: play its sound if any, then advance `last_serial`. Disabled → only advances `last_serial`.
  - `SoundBoard.silent()` classmethod → a disabled board (the renderer's default).
- `PygameRenderer.__init__(..., sound=None)`: `self.sound = sound or SoundBoard.silent()`. `draw(state)` calls `self.sound.play_new(getattr(state, 'sound_events', ()))` first thing.
- `main.make_renderer`: `sound=SoundBoard(resource_path('assets', 'sounds'), enabled=bool(env_int('SOUND', 1)))`.

- [ ] **Step 1: Write the failing tests** in `tests/test_sound.py`:

```python
def test_missing_directory_is_silent(self):
    board = SoundBoard(Path('/nonexistent'), enabled=True)
    board.play_new([SoundEvent(1, 'door')])
    self.assertEqual(board.last_serial, 1)
    self.assertIsNone(board.sound_for('door'))


def test_mixer_failure_is_silent(self):
    with mock.patch('pygame.mixer.init', side_effect=pygame.error('no audio')):
        board = SoundBoard(Path(tmp), enabled=True)
    self.assertFalse(board.enabled)
    board.play_new([SoundEvent(1, 'door')])  # no raise


def test_disabled_board_plays_nothing(
    self,
): ...  # enabled=False, a real wav present -> Sound.play never called (mock)


def test_events_play_once_across_redraws(self):
    # write a tiny valid WAV (stdlib `wave`, 10 ms of silence) as door.wav in a temp dir;
    # mock pygame.mixer.Sound.play; play_new the same list twice -> play called once
    ...


def test_ogg_preferred_over_wav(self): ...
def test_corrupt_file_is_skipped(
    self,
): ...  # garbage door.wav + valid descend.wav -> descend plays, no raise
def test_renderer_plays_state_sounds_on_draw(
    self,
): ...  # PygameRenderer(..., sound=mock board); draw(state with one event) -> play_new called with it
def test_make_renderer_respects_sound_0(self): ...  # env SOUND=0 -> renderer.sound.enabled False
```

Write test audio into a `tempfile.TemporaryDirectory()`; never into `assets/`.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_sound -v 2>&1 | tail -20`
Expected: ImportError on `render.sound`.

- [ ] **Step 3: Implement** per Interfaces.

- [ ] **Step 4: Full suite + linters + frozen-build check**

Run: `.venv/bin/python -m unittest discover -s tests 2>&1 | tail -3 && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pyright && .venv/bin/vulture`
Expected: `OK`, all clean. Confirm `packaging/pyrogue.spec` doesn't exclude `pygame.mixer` (it must stay importable in the frozen build); if the spec has an excludes list, check it.

- [ ] **Step 5: Smoke-test real playback once**: generate a 0.2 s 440 Hz WAV into `$CLAUDE_JOB_DIR/tmp/sounds/footsteps.wav` with stdlib `wave`, construct `SoundBoard(that_dir)`, `play_new([SoundEvent(1, 'footsteps')])` — no exception (audio may or may not be audible on the box; the point is no crash with a real mixer).

- [ ] **Step 6: Do not commit** (user instruction).
