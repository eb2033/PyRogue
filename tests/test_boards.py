"""The cached stats and log boards (render/boards.py) must never show stale
values: every displayed value, when it changes, has to reach the screen on
the next frame, exactly as an uncached paint would draw it -- and a resize,
an F11 toggle or a refit must rebuild them. Headless (SDL dummy driver);
skipped without pygame-ce."""

import hashlib
import os
import unittest
from unittest import mock

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

try:
    import pygame
except ImportError:  # pragma: no cover - terminal-only checkout
    pygame = None

from game.item import Item
from game.paths import resource_path
from game.state import GameState

if pygame is not None:
    from render import boards, pygame_render, ui
    from render.pygame_render import PygameRenderer
    from render.tileset import Tileset

WIDTH, HEIGHT = 40, 20


def _areas(surface, layout):
    window = surface.get_rect()
    return [a.clip(window) for a in (boards.panel_area(layout), boards.log_area(layout))]


def _pixels(surface, layout):
    """A digest of each board's pixels (a failure's diff stays readable)."""
    return [
        hashlib.sha1(pygame.image.tobytes(surface.subsurface(a), 'RGB')).hexdigest()
        for a in _areas(surface, layout)
    ]


def frame_boards(renderer, state):
    """The boards' pixels in a real frame (through the cache)."""
    renderer._show(lambda: renderer._paint_game(state))
    return _pixels(renderer.canvas.surface, renderer.layout)


def uncached_boards(renderer, state):
    """The boards' pixels painted from scratch, the way they were before the
    cache: on a cleared surface the window's size."""
    window = renderer.canvas.surface
    surface = pygame.Surface(window.get_size(), 0, window)
    canvas = ui.Canvas(surface, renderer.layout)
    canvas.clear()
    ui.paint_panel(canvas, state)
    ui.paint_log(canvas, state)
    return _pixels(surface, renderer.layout)


def _mutations():
    """(name, class to start as, mutate(state)) for every value the boards show."""

    def player(attr, fn):
        return lambda s: setattr(s.player, attr, fn(getattr(s.player, attr)))

    return [
        ('hp', 'warrior', player('hp', lambda v: v - 3)),
        ('hp into danger', 'warrior', player('hp', lambda v: 1)),
        ('max hp', 'warrior', player('max_hp', lambda v: v + 7)),
        ('atk', 'warrior', player('power', lambda v: v + 2)),
        ('def', 'warrior', player('defense', lambda v: v + 3)),
        ('dodge', 'archer', lambda s: setattr(s.player.armor, 'dodge', s.player.armor.dodge + 5)),
        ('items', 'warrior', lambda s: s.player.items_used.append('a trinket')),
        ('gold', 'warrior', player('gold', lambda v: v + 5)),
        ('quiver', 'archer', player('quiver', lambda v: v - 1)),
        ('class', 'warrior', player('char_class', lambda v: 'archer')),
        ('depth', 'warrior', lambda s: setattr(s, 'depth', s.depth + 1)),
        ('weapon', 'warrior', player('weapon', lambda v: Item(0, 0, 'weapon', 'epic'))),
        ('armor', 'warrior', player('armor', lambda v: Item(0, 0, 'armor', 'rare'))),
        ('weapon bonus', 'warrior', lambda s: setattr(s.player.weapon, 'bonus', 9)),
        ('weapon rarity', 'warrior', lambda s: setattr(s.player.weapon, 'rarity', 'epic')),
        ('belt potion', 'warrior', lambda s: s.belt.append(Item(0, 0, 'potion', 'epic'))),
        ('belt emptied', 'warrior', lambda s: s.belt.clear()),
        ('belt capacity', 'warrior', lambda s: s.player.boons.append('quick_hands')),
        ('boon', 'warrior', lambda s: s.player.boons.append('blood_pact')),
        ('message', 'warrior', lambda s: s.log('The goblin hits you for 2.')),
        ('long message', 'warrior', lambda s: s.log('A long message ' * 6)),
    ]


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class CachedBoardsTest(unittest.TestCase):
    tiles = False

    def setUp(self):
        tileset = Tileset(resource_path('assets')) if self.tiles else None
        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=tileset)
        pygame.event.clear()

    def tearDown(self):
        self.renderer.close()

    def _state(self, char_class='warrior'):
        state = GameState(WIDTH, HEIGHT, char_class=char_class, seed=0)
        if char_class == 'warrior':
            state.player.weapon = Item(0, 0, 'weapon', 'common')
        state.belt[:] = [Item(0, 0, 'potion', 'uncommon')]
        for i in range(6):
            state.log(f'Message {i}.')
        return state

    def test_every_displayed_value_reaches_the_cached_boards(self):
        r = self.renderer
        for name, char_class, mutate in _mutations():
            with self.subTest(name):
                state = self._state(char_class)
                r.draw(state)
                before = frame_boards(r, state)
                self.assertEqual(before, uncached_boards(r, state))
                mutate(state)
                after = frame_boards(r, state)
                self.assertNotEqual(after, before, f'{name}: the board never changed')
                self.assertEqual(after, uncached_boards(r, state), f'{name}: stale board')

    def test_a_frame_without_changes_rebuilds_nothing_but_a_relayout_does(self):
        r = self.renderer
        state = self._state()
        r.draw(state)
        rebuilds = r.boards.rebuilds
        frame_boards(r, state)
        frame_boards(r, state)
        self.assertEqual(r.boards.rebuilds, rebuilds)
        # A relayout invalidates them, even at the same size.
        r._relayout()
        frame_boards(r, state)
        self.assertGreater(r.boards.rebuilds, rebuilds)

    def test_a_beat_only_blits_the_boards(self):
        r = self.renderer
        state = self._state()
        r.draw(state)
        frames = []

        def paint(t):
            frames.append(t)
            r._paint_game(state)

        with (
            mock.patch.object(ui, 'paint_panel_content', wraps=ui.paint_panel_content) as panel,
            mock.patch.object(ui, 'paint_log_messages', wraps=ui.paint_log_messages) as log,
        ):
            r._play(80, paint, interruptible=False)
            self.assertGreater(len(frames), 1)
            panel.assert_not_called()
            log.assert_not_called()
            # A change mid-beat is painted once, then blitted again.
            state.player.gold += 1
            r._play(80, paint, interruptible=False)
            self.assertEqual(panel.call_count, 1)
            log.assert_not_called()

    def test_a_refit_resize_or_fullscreen_rebuilds_the_boards(self):
        r = self.renderer
        state = self._state()
        r.draw(state)
        frame_boards(r, state)
        with self.subTest('a refit alone'):
            # The layout key, not only the relayout's invalidate(): a new font
            # size or placement is a new board even if nobody says so.
            font = r.layout.font_size
            r.layout.fit((700, 400))
            self.assertNotEqual(r.layout.font_size, font)
            self.assertEqual(frame_boards(r, state), uncached_boards(r, state))
        with self.subTest('resize'):
            r._relayout()  # back to the window's own layout
            before = frame_boards(r, state)
            r._set_mode((1300, 700), pygame.RESIZABLE)
            r._relayout()
            after = frame_boards(r, state)
            self.assertNotEqual(after, before)
            self.assertEqual(after, uncached_boards(r, state))
        with self.subTest('fullscreen'):
            for _ in range(2):  # in, then out again
                r.toggle_fullscreen()
                self.assertEqual(frame_boards(r, state), uncached_boards(r, state))

    def test_beats_are_paced_by_a_clock(self):
        r = self.renderer
        r._clock = mock.Mock()
        r._play(40, lambda t: None, interruptible=False)
        r._clock.tick.assert_called_with(pygame_render.BEAT_FPS)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class CachedBoardsTileModeTest(CachedBoardsTest):
    tiles = True
