"""Headless tests for the pygame renderer (SDL dummy video/audio drivers).

Skipped cleanly when pygame-ce isn't installed, so a stdlib-only checkout still
has a green suite. Events are injected with pygame.event.post, which is the same
queue a real window feeds -- so these exercise the actual blocking wait.
"""

import collections
import os
import unittest
from typing import Any, cast
from unittest import mock

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

try:
    import pygame
except ImportError:  # pragma: no cover - terminal-only checkout
    pygame = None

import main
from game.monster import Monster
from game.state import GameState
from render.base import Action

if pygame is not None:
    from render import camera, screens
    from render.palette import BACKGROUND
    from render.pygame_render import PygameRenderer

WIDTH, HEIGHT = 40, 20


def key(k, char='', shift=False):
    mod = pygame.KMOD_SHIFT if shift else 0
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=char, mod=mod, scancode=0)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class PygameRendererTest(unittest.TestCase):
    def setUp(self):
        self.renderer = PygameRenderer(WIDTH, HEIGHT)
        pygame.event.clear()

    def tearDown(self):
        self.renderer.close()

    def post(self, *events):
        for event in events:
            pygame.event.post(event)

    def test_draw_paints_the_player_cell(self):
        state = GameState(WIDTH, HEIGHT)
        self.renderer.draw(state)
        cell = self.renderer.layout.cell_rect(state.player.x, state.player.y)
        screen = self.renderer.canvas.surface
        pixels = {
            tuple(screen.get_at((x, y)))[:3]
            for x in range(cell.left, cell.right)
            for y in range(cell.top, cell.bottom)
        }
        self.assertTrue(pixels - {BACKGROUND}, 'player cell is blank')

    def test_walking_tilts_alternate_sign(self):
        state = GameState(WIDTH, HEIGHT)
        player = state.player
        self.assertEqual(self.renderer.track_steps([player]), {})
        self.assertEqual(self.renderer.track_steps([player]), {})  # idle: upright
        angles = []
        for _ in range(4):
            player.x += 1
            angles.append(self.renderer.track_steps([player]).get(id(player)))
        self.assertEqual(angles, [15, -15, 15, -15])
        self.assertEqual(self.renderer.track_steps([player]), {})  # stopped

    def test_a_jump_is_not_a_step_and_gone_entities_are_forgotten(self):
        state = GameState(WIDTH, HEIGHT)
        player = state.player
        self.renderer.track_steps([player])
        player.x += 5
        self.assertEqual(self.renderer.track_steps([player]), {})
        self.renderer.track_steps([])
        self.assertEqual(self.renderer._gait, {})

    def test_draw_plays_a_step_beat_and_ends_upright(self):
        state = GameState(WIDTH, HEIGHT)
        self.renderer.draw(state)
        state.player.x += 1
        with mock.patch.object(self.renderer, '_play') as play:
            self.renderer.draw(state)
        self.assertEqual(play.call_args[0][0], 110)
        self.assertEqual(self.renderer._tilts, {})

    def test_get_action_maps_keys(self):
        self.post(
            key(pygame.K_w, 'w'),
            key(pygame.K_e, 'e'),
            key(pygame.K_UP),
            key(pygame.K_PERIOD, '.'),
        )
        self.assertEqual(self.renderer.get_action(), Action.MOVE_N)
        self.assertEqual(self.renderer.get_action(), Action.DESCEND)
        self.assertEqual(self.renderer.get_action(), Action.SHOOT_N)
        self.assertEqual(self.renderer.get_action(), Action.WAIT)

    def test_unmapped_key_returns_none_and_is_ignored(self):
        self.post(key(pygame.K_z, 'z'))
        self.assertIsNone(self.renderer.get_action())

    def test_window_close_is_quit(self):
        self.post(pygame.event.Event(pygame.QUIT))
        self.assertEqual(self.renderer.get_action(), Action.QUIT)

    def test_resize_relayouts_and_keeps_waiting(self):
        self.renderer.draw(GameState(WIDTH, HEIGHT))
        before = self.renderer.layout.cell_w
        pygame.display.set_mode((3000, 1500), pygame.RESIZABLE)
        self.post(
            pygame.event.Event(pygame.VIDEORESIZE, size=(3000, 1500), w=3000, h=1500),
            key(pygame.K_d, 'd'),
        )
        self.assertEqual(self.renderer.get_action(), Action.MOVE_E)
        self.assertGreater(self.renderer.layout.cell_w, before)
        self.assertEqual(self.renderer.canvas.surface.get_size(), (3000, 1500))

    def test_pause_keeps_typed_ahead_keys(self):
        self.post(key(pygame.K_a, 'a'))
        start = pygame.time.get_ticks()
        self.renderer.pause(50)
        self.assertGreaterEqual(pygame.time.get_ticks() - start, 50)
        self.assertEqual(self.renderer.get_action(), Action.MOVE_W)

    def test_window_close_during_pause_is_delivered_next(self):
        self.post(pygame.event.Event(pygame.QUIT))
        self.renderer.pause(20)
        self.assertEqual(self.renderer.get_action(), Action.QUIT)

    def test_zero_pause_is_instant(self):
        start = pygame.time.get_ticks()
        self.renderer.pause(0)
        self.assertLess(pygame.time.get_ticks() - start, 5)

    def test_menus_and_a_full_run_through_main_loop(self):
        import main

        enter = key(pygame.K_RETURN, '\r')
        # Title: Start. Class: down to Archer, enter. Then a few turns, quit.
        self.post(
            enter,
            key(pygame.K_s, 's'),
            enter,
            key(pygame.K_w, 'w'),
            key(pygame.K_RIGHT),
            key(pygame.K_PERIOD, '.'),
            key(pygame.K_q, 'q'),
        )
        self.assertTrue(self.renderer.show_title_screen())
        char_class = self.renderer.choose_class()
        self.assertEqual(char_class, 'archer')
        state = GameState(WIDTH, HEIGHT, char_class=char_class)
        main.run(self.renderer, state, delay_ms=5)
        self.assertFalse(state.running)

    def test_title_quit_option(self):
        self.post(key(pygame.K_DOWN), key(pygame.K_RETURN, '\r'))
        self.assertFalse(self.renderer.show_title_screen())

    # -- P1: fullscreen, bosses, fonts ---------------------------------------

    def test_f11_toggles_fullscreen_and_back_while_waiting(self):
        self.renderer.draw(GameState(WIDTH, HEIGHT))
        windowed = self.renderer.canvas.surface.get_size()
        desktop = pygame.display.get_desktop_sizes()[0]
        self.post(key(pygame.K_F11), key(pygame.K_w, 'w'))
        self.assertEqual(self.renderer.get_action(), Action.MOVE_N)  # F11 is no Action
        self.assertTrue(self.renderer.fullscreen)
        self.assertEqual(self.renderer.canvas.surface.get_size(), desktop)
        self.assertEqual(pygame.display.get_surface().get_size(), desktop)

        self.post(key(pygame.K_F11), key(pygame.K_PERIOD, '.'))
        self.assertEqual(self.renderer.get_action(), Action.WAIT)
        self.assertFalse(self.renderer.fullscreen)
        self.assertEqual(self.renderer.canvas.surface.get_size(), windowed)

    def test_f11_repaints_the_current_frame(self):
        state = GameState(WIDTH, HEIGHT)
        self.renderer.draw(state)
        self.renderer.toggle_fullscreen()
        cell = self.renderer.layout.cell_rect(state.player.x, state.player.y)
        self.assertTrue(
            set(cell_pixels(self.renderer, cell)) - {BACKGROUND},
            'frame not repainted after going fullscreen',
        )

    def test_f11_in_a_menu_is_not_a_selection(self):
        # F11 twice (in and out), then Down: still on the title menu, so the
        # Enter selects Quit -- F11 neither confirmed nor moved anything.
        self.post(
            key(pygame.K_F11), key(pygame.K_F11), key(pygame.K_DOWN), key(pygame.K_RETURN, '\r')
        )
        self.assertFalse(self.renderer.show_title_screen())
        self.assertFalse(self.renderer.fullscreen)

    def test_fullscreen_failure_is_harmless(self):
        size = self.renderer.canvas.surface.get_size()
        window = mock.Mock()
        window.set_fullscreen.side_effect = pygame.error('no fullscreen here')
        with mock.patch.object(PygameRenderer, '_display_window', return_value=window):
            self.renderer.toggle_fullscreen()
        with (
            mock.patch.object(PygameRenderer, '_display_window', return_value=None),
            mock.patch('pygame.display.set_mode', side_effect=pygame.error('no')),
        ):
            self.renderer.toggle_fullscreen()
        self.assertFalse(self.renderer.fullscreen)
        self.assertEqual(self.renderer.canvas.surface.get_size(), size)

    def test_fullscreen_falls_back_to_set_mode_without_window_api(self):
        windowed = self.renderer.canvas.surface.get_size()
        desktop = pygame.display.get_desktop_sizes()[0]
        with mock.patch.object(PygameRenderer, '_display_window', return_value=None):
            self.renderer.toggle_fullscreen()
            self.assertEqual(self.renderer.canvas.surface.get_size(), desktop)
            self.renderer.toggle_fullscreen()
        self.assertFalse(self.renderer.fullscreen)
        self.assertEqual(self.renderer.canvas.surface.get_size(), windowed)

    def test_boss_is_drawn_heavier_and_brighter_than_a_regular_monster(self):
        state = GameState(WIDTH, HEIGHT)
        state.entities = [state.player]
        x, y = open_neighbour(state)
        boss = Monster(x, y, 'goblin', is_boss=True)
        state.entities.append(boss)
        cell = self.renderer.layout.cell_rect(x, y)
        # The boss stands next to the player; this compares the unzoomed cell.
        self.renderer.director.zoom = False

        self.renderer.draw(state)
        boss_pixels = lit_pixels(self.renderer, cell)
        boss.is_boss = False
        self.renderer.draw(state)
        plain_pixels = lit_pixels(self.renderer, cell)

        self.assertGreater(len(boss_pixels), len(plain_pixels))

        # The glyph's solid core -- its most common red pixel -- is the colour
        # it was drawn in. (Not the brightest: an anti-aliased edge blended
        # over the white floor dot under the glyph can outshine the core.)
        def core_red(pixels):
            reds = [tuple(p[:3]) for p in pixels if p[0] > p[1] + 40]
            return sum(collections.Counter(reds).most_common(1)[0][0])

        self.assertGreater(core_red(boss_pixels), core_red(plain_pixels))

    def test_font_path_reaches_the_layout(self):
        font = os.path.join(os.path.dirname(pygame.__file__), pygame.font.get_default_font())
        self.renderer.close()
        self.renderer = PygameRenderer(WIDTH, HEIGHT, font_path=font)
        self.assertEqual(self.renderer.layout.font_path, font)
        self.renderer.draw(GameState(WIDTH, HEIGHT))

    def test_make_renderer_uses_the_bundled_font(self):
        renderer = cast(PygameRenderer, main.make_renderer(WIDTH, HEIGHT))
        try:
            font_path = cast(str, renderer.layout.font_path)
            self.assertTrue(font_path.endswith(main.BUNDLED_FONT))
            self.assertTrue(os.path.isfile(font_path))
        finally:
            renderer.close()

    # -- P3: mouse in the menus ----------------------------------------------

    @staticmethod
    def motion(pos=(5, 5)):
        return pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(1, 1), buttons=(0, 0, 0))

    @staticmethod
    def click(pos=(5, 5), button=1):
        return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button)

    def test_menu_hover_moves_the_highlight(self):
        seen = []

        def fake_hit(layout, menu, banner, pos):
            seen.append(menu.index)
            return {(1, 1): 1}.get(pos)

        self.post(self.motion((1, 1)), key(pygame.K_RETURN, '\r'))
        with mock.patch.object(screens, 'option_at', fake_hit):
            self.assertFalse(self.renderer.show_title_screen())  # Quit, via hover
        self.assertEqual(seen, [0])

    def test_menu_click_selects_like_enter(self):
        self.post(self.click((1, 1)))
        with mock.patch.object(screens, 'option_at', lambda *a: 1):
            self.assertFalse(self.renderer.show_title_screen())
        self.post(self.click((2, 2)))
        with mock.patch.object(screens, 'option_at', lambda *a: 0):
            self.assertTrue(self.renderer.show_title_screen())

    def test_menu_click_outside_any_option_does_nothing(self):
        self.post(
            self.click((9, 9)), self.motion((9, 9)), key(pygame.K_DOWN), key(pygame.K_RETURN, '\r')
        )
        with mock.patch.object(screens, 'option_at', lambda *a: None):
            self.assertFalse(self.renderer.show_title_screen())  # keys decided it

    def test_menu_right_click_is_ignored(self):
        self.post(self.click((1, 1), button=3), key(pygame.K_RETURN, '\r'))
        with mock.patch.object(screens, 'option_at', lambda *a: 1):
            self.assertTrue(self.renderer.show_title_screen())

    def test_menu_repaints_only_when_the_highlight_changes(self):
        self.post(self.motion(), self.motion(), self.motion(), key(pygame.K_RETURN, '\r'))
        with (
            mock.patch.object(screens, 'option_at', lambda *a: 1),
            mock.patch.object(screens, 'paint_menu') as paint,
        ):
            self.renderer.show_title_screen()
        # first paint, one repaint after the highlight moved, none for the
        # two motions that changed nothing, then Enter returns.
        self.assertEqual(paint.call_count, 2)

    def test_menu_keys_unchanged_with_mouse_support(self):
        self.post(key(pygame.K_s, 's'), key(pygame.K_SPACE, ' '))
        self.assertFalse(self.renderer.show_title_screen())
        self.post(key(pygame.K_q, 'q'))
        self.assertFalse(self.renderer.show_title_screen())

    def test_mouse_events_are_ignored_during_get_action(self):
        self.post(self.motion(), self.click(), self.click(button=3), key(pygame.K_d, 'd'))
        with mock.patch.object(screens, 'option_at', lambda *a: 0):
            self.assertEqual(self.renderer.get_action(), Action.MOVE_E)

    def test_pause_keeps_keys_when_mouse_events_are_queued(self):
        self.post(self.motion(), key(pygame.K_a, 'a'), self.click())
        self.renderer.pause(30)
        self.assertEqual(self.renderer.get_action(), Action.MOVE_W)

    def test_window_close_in_a_menu_is_delivered_by_get_action(self):
        self.post(self.motion(), pygame.event.Event(pygame.QUIT))
        self.assertFalse(self.renderer.show_title_screen())
        self.assertEqual(self.renderer.get_action(), Action.QUIT)

    # -- P1: game over, and a whole run --------------------------------------

    def test_game_over_shows_overlay_and_q_quits(self):
        state = GameState(WIDTH, HEIGHT)
        kill_player_next_turn(state)
        # '.' lets the goblin kill us; 'w' after death is ignored; 'q' quits.
        self.post(key(pygame.K_PERIOD, '.'), key(pygame.K_w, 'w'), key(pygame.K_q, 'q'))
        frames = record_frames(self.renderer)
        main.run(self.renderer, state, delay_ms=1)
        self.assertTrue(state.game_over)
        self.assertFalse(state.running)
        self.assertGreaterEqual(frames.count(True), 2)  # game-over frame, before 'w' and 'q'
        self.assertOverlayDrawn(state)

    def test_window_close_on_game_over_quits(self):
        state = GameState(WIDTH, HEIGHT)
        kill_player_next_turn(state)
        self.post(key(pygame.K_PERIOD, '.'), pygame.event.Event(pygame.QUIT))
        main.run(self.renderer, state, delay_ms=1)
        self.assertTrue(state.game_over)
        self.assertFalse(state.running)

    def test_complete_run_title_class_descend_death_quit(self):
        """Plan WS-A acceptance: a complete run, in-window, through main.run.

        Keys go through the real event queue; between keystrokes the script
        only rearranges the world (puts the player on the stairs, brings a
        monster in for the kill) instead of path-finding to them."""
        enter = key(pygame.K_RETURN, '\r')
        self.post(enter, key(pygame.K_s, 's'), enter)  # Start, then Archer
        self.assertTrue(self.renderer.show_title_screen())
        state = GameState(WIDTH, HEIGHT, char_class=self.renderer.choose_class())
        self.assertEqual(state.player.char_class, 'archer')

        def to_stairs():
            state.player.x, state.player.y = find_tile(state, '>')
            state.update_fov()
            return [key(pygame.K_e, 'e')]

        def die_on_level_two():
            self.assertEqual(state.depth, 2)
            kill_player_next_turn(state)
            return [key(pygame.K_PERIOD, '.')]

        def on_game_over_frame():
            self.assertTrue(state.game_over)
            self.assertOverlayDrawn(state)
            return [key(pygame.K_d, 'd'), key(pygame.K_q, 'q')]  # move ignored; quit

        script = [to_stairs, die_on_level_two, on_game_over_frame]
        real_get_action = self.renderer.get_action

        def scripted_get_action():
            if script and not pygame.event.peek(pygame.KEYDOWN):
                for event in script.pop(0)():
                    pygame.event.post(event)
            return real_get_action()

        self.renderer.get_action = scripted_get_action
        main.run(self.renderer, state, delay_ms=1)
        self.assertEqual(script, [])
        self.assertEqual(state.depth, 2)
        self.assertTrue(state.game_over)
        self.assertFalse(state.running)

    def assertOverlayDrawn(self, state):
        """The game-over line differs from the same frame without it."""
        layout = self.renderer.layout
        row = screens.game_over_rect(layout)
        self.renderer.draw(state)
        with_overlay = cell_pixels(self.renderer, row, as_list=True)
        state.game_over = False
        try:
            self.renderer.draw(state)
            without = cell_pixels(self.renderer, row, as_list=True)
        finally:
            state.game_over = True
            self.renderer.draw(state)
        self.assertNotEqual(with_overlay, without)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class TileModeTest(unittest.TestCase):
    """The bundled tileset puts the window in tile mode: square map cells."""

    def setUp(self):
        from game.paths import resource_path
        from render.tileset import Tileset

        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=Tileset(resource_path('assets')))
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()

    def tearDown(self):
        self.renderer.close()

    def test_layout_is_in_tile_mode(self):
        self.assertTrue(self.renderer.layout.tiles)
        self.assertIsNotNone(self.renderer.layout.tile)

    def test_draw_paints_the_players_tile_over_the_floor(self):
        state = GameState(WIDTH, HEIGHT)
        self.renderer.draw(state)
        layout = self.renderer.layout
        rect = pygame.Rect(
            layout.map_cell_to_pixel(state.player.x, state.player.y), layout.map_cell_size()
        )
        drawn = pygame.display.get_surface().subsurface(rect)
        expected = self.renderer.tileset.glyph('.', 0, layout.tile).copy()
        expected.blit(self.renderer.tileset.glyph('@', state.player.color, layout.tile), (0, 0))
        for point in [(layout.tile // 2, layout.tile // 2), (1, 1), (layout.tile // 3, 2)]:
            self.assertEqual(drawn.get_at(point)[:3], expected.get_at(point)[:3])

    def fight(self):
        state = GameState(WIDTH, HEIGHT)
        x, y = open_neighbour(state)
        goblin = Monster(x, y, 'goblin')
        state.entities = [state.player, goblin]
        state.update_fov()
        return state, goblin

    def test_melee_zooms_in_with_the_fight_centred(self):
        self.renderer.zoom_ms = self.renderer.impact_ms = 0
        state, goblin = self.fight()
        self.renderer.draw(state)
        layout = self.renderer.layout
        map_rect = layout.map_rect()
        # The pair plus 2 squares each side: 6x5 or 5x6 cells fill the map
        # area on its tighter axis.
        view = self.renderer._view
        cell, _, ox, oy = camera.project(view, map_rect, layout.map_cell_size())
        self.assertGreater(cell, cast(int, layout.tile))
        self.assertLessEqual(
            min(map_rect.w // cell, map_rect.h // cell) - 1, min(view.width, view.height)
        )
        # The player's zoomed tile is where the projection says, at the bigger size.
        rect = pygame.Rect(ox + state.player.x * cell, oy + state.player.y * cell, cell, cell)
        drawn = pygame.display.get_surface().subsurface(rect)
        expected = self.renderer.tileset.glyph('.', 0, cell).copy()
        expected.blit(self.renderer.tileset.glyph('@', state.player.color, cell), (0, 0))
        for point in [(cell // 2, cell // 2), (1, 1), (cell // 3, 2)]:
            self.assertEqual(drawn.get_at(point)[:3], expected.get_at(point)[:3])
        # The midpoint between the two sits on the centre of the map area.
        mid_x = ox + (state.player.x + goblin.x + 1) / 2 * cell
        mid_y = oy + (state.player.y + goblin.y + 1) / 2 * cell
        self.assertLessEqual(abs(mid_x - map_rect.centerx), 1)
        self.assertLessEqual(abs(mid_y - map_rect.centery), 1)

    def test_zoom_stays_inside_the_map_area(self):
        self.renderer.zoom_ms = self.renderer.impact_ms = 0
        state, _ = self.fight()
        screen = cast(Any, pygame.display.get_surface())
        self.renderer.draw(state)
        self.assertIsNotNone(self.renderer._view)
        zoomed = screen.copy()
        self.renderer.director = camera.Director(zoom=False)
        self.renderer.draw(state)
        # Blank the map area in both: everything else must match exactly.
        map_rect = self.renderer.layout.map_rect()
        for surface in (zoomed, screen):
            surface.fill(BACKGROUND, map_rect)
        self.assertEqual(pygame.image.tobytes(zoomed, 'RGB'), pygame.image.tobytes(screen, 'RGB'))

    def test_fight_over_zooms_back_out(self):
        self.renderer.zoom_ms = self.renderer.impact_ms = 0
        state, goblin = self.fight()
        self.renderer.draw(state)
        self.assertIsNotNone(self.renderer._view)
        goblin.hp = 1
        state.attack(state.player, goblin)
        self.renderer.draw(state)
        self.assertIsNone(self.renderer._view)

    def test_beats_animate_and_a_queued_key_cuts_them_short(self):
        self.renderer.zoom_ms = 2000
        state, _ = self.fight()
        pygame.event.post(key(pygame.K_d, 'd'))
        start = pygame.time.get_ticks()
        self.renderer.draw(state)
        self.assertLess(pygame.time.get_ticks() - start, 1000)
        self.assertEqual(self.renderer.get_action(), Action.MOVE_E)  # not swallowed

    def test_a_beat_plays_its_frames(self):
        self.renderer.zoom_ms = 80
        state, _ = self.fight()
        frames = []
        show = self.renderer._show
        with mock.patch.object(
            self.renderer, '_show', side_effect=lambda paint: (frames.append(1), show(paint))
        ):
            self.renderer.draw(state)
        self.assertGreater(len(frames), 2)  # in-between frames, then the final one

    def test_impact_flashes_the_defender(self):
        self.renderer.zoom_ms = 0
        state, goblin = self.fight()
        self.renderer.draw(state)
        state.attack(goblin, state.player)
        frames = []
        with mock.patch.object(
            self.renderer, '_paint_impact', side_effect=lambda hit, t: frames.append((hit, t))
        ):
            self.renderer.draw(state)
        self.assertTrue(frames)
        self.assertIs(frames[0][0].defender, state.player)

    def test_crit_number_is_bigger_yellow_with_black_outline(self):
        from render.pygame_render import CRIT_OUTLINE_RGB, CRIT_RGB

        r = self.renderer
        self.assertGreater(
            r._glyph('-12', CRIT_RGB, bold=True, scale=2).get_height(),
            r._glyph('-12', CRIT_RGB, bold=True).get_height(),
        )
        state, goblin = self.fight()
        r.draw(state)
        state.player.power = 5
        with mock.patch('game.state.BASE_CRIT_CHANCE', 1.0):
            state.attack(state.player, goblin)
        hit = state.combat_events[-1]
        self.assertTrue(hit.crit)
        r.canvas.surface.fill((50, 50, 50))
        r._paint_impact(hit, 0.0)
        rect = r._map_cell_rect(hit.x, hit.y)
        area = r.canvas.surface.subsurface(
            rect.inflate(rect.width, rect.height).clip(r.canvas.surface.get_rect())
        )
        pixels = {
            tuple(area.get_at((x, y)))[:3]
            for x in range(area.get_width())
            for y in range(area.get_height())
        }
        self.assertIn(CRIT_RGB, pixels)
        self.assertIn(CRIT_OUTLINE_RGB, pixels)

    def test_char_without_a_tile_is_drawn_as_its_glyph(self):
        state = GameState(WIDTH, HEIGHT)
        stranger = Monster(state.player.x + 1, state.player.y, 'goblin')
        stranger.char = 'Z'  # no tiles.json entry
        state.entities.append(stranger)
        state.update_fov()
        self.renderer.draw(state)  # must not raise

    def test_game_over_overlay_is_drawn_on_the_map(self):
        state = GameState(WIDTH, HEIGHT)
        self.renderer.draw(state)
        before = pygame.display.get_surface().copy()
        state.game_over = True
        self.renderer.draw(state)
        band = screens.game_over_rect(self.renderer.layout)
        self.assertTrue(self.renderer.layout.map_rect().contains(band))
        after = pygame.display.get_surface()
        self.assertNotEqual(
            pygame.image.tobytes(after.subsurface(band), 'RGB'),
            pygame.image.tobytes(before.subsurface(band), 'RGB'),
        )

    def test_tiles_env_zero_keeps_glyph_mode(self):
        with mock.patch.dict(os.environ, {'TILES': '0'}):
            renderer = cast(PygameRenderer, main.make_renderer(WIDTH, HEIGHT))
        try:
            self.assertFalse(renderer.layout.tiles)
        finally:
            renderer.close()

    def test_make_renderer_uses_the_bundled_tiles_by_default(self):
        with mock.patch.dict(os.environ):
            os.environ.pop('TILES', None)
            renderer = cast(PygameRenderer, main.make_renderer(WIDTH, HEIGHT))
        try:
            self.assertTrue(renderer.layout.tiles)
        finally:
            renderer.close()


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class HitShakeAndHealthBarTest(unittest.TestCase):
    """The hit shake (an Impact beat that always plays out, keys left queued)
    and enemy health bars, in tile mode."""

    def setUp(self):
        from game.paths import resource_path
        from render.tileset import Tileset

        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=Tileset(resource_path('assets')))
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        self.renderer.zoom_ms = 0
        pygame.event.clear()

    def tearDown(self):
        self.renderer.close()

    def fight(self, zoom=False):
        self.renderer.director = camera.Director(zoom=zoom)
        state = GameState(WIDTH, HEIGHT)
        x, y = open_neighbour(state)
        goblin = Monster(x, y, 'goblin')
        goblin.hp = goblin.max_hp = 20
        state.entities = [state.player, goblin]
        state.update_fov()
        self.renderer.draw(state)
        return state, goblin

    def played(self, state):
        """The (ms, interruptible) of every beat draw() plays."""
        calls = []
        with mock.patch.object(
            self.renderer,
            '_play',
            side_effect=lambda ms, paint, interruptible=True: calls.append((ms, interruptible)),
        ):
            self.renderer.draw(state)
        return calls

    # -- shake ----------------------------------------------------------------

    def test_a_hit_plays_an_uninterruptible_shake_and_a_crit_plays_longer(self):
        state, goblin = self.fight()
        state.attack(goblin, state.player)
        normal = self.played(state)
        self.assertEqual(len(normal), 1)
        normal_ms, interruptible = normal[0]
        self.assertFalse(interruptible)
        self.assertTrue(150 <= normal_ms <= 250, normal_ms)

        state.player.power = 1
        with mock.patch('game.state.BASE_CRIT_CHANCE', 1.0):
            state.attack(state.player, goblin)
        self.assertTrue(state.combat_events[-1].crit)
        (crit_ms, interruptible), *_ = self.played(state)
        self.assertFalse(interruptible)
        self.assertTrue(normal_ms < crit_ms <= 350, crit_ms)

    def test_shake_offsets_frames_and_ends_still(self):
        state, goblin = self.fight()
        state.attack(goblin, state.player)
        offsets = []
        real = self.renderer._paint_game

        def paint(state, impact=None, shake=(0, 0), **kw):
            offsets.append(shake)
            real(state, impact=impact, shake=shake, **kw)

        with mock.patch.object(self.renderer, '_paint_game', side_effect=paint):
            self.renderer.draw(state)
        self.assertTrue(any(o != (0, 0) for o in offsets[:-1]), offsets)
        self.assertEqual(offsets[-1], (0, 0))  # draw()'s own frame is still
        hit = state.combat_events[-1]
        shake = camera.shake_for(hit)
        self.assertEqual(self.renderer.shake_offset(shake, 1.0), (0, 0))

    def test_shake_moves_the_whole_map(self):
        state, _ = self.fight()
        r = self.renderer
        r._paint_game(state)
        still = r.canvas.surface.copy()
        r.canvas.clear()
        r._paint_game(state, shake=(4, -3))
        moved = r.canvas.surface
        centre = r.layout.map_rect().center
        for dx, dy in ((0, 0), (17, 5), (-30, 11)):
            p = (centre[0] + dx, centre[1] + dy)
            self.assertEqual(moved.get_at((p[0] + 4, p[1] - 3)), still.get_at(p))

    def test_keys_pressed_during_the_shake_wait_until_it_ends(self):
        state, goblin = self.fight()
        state.attack(goblin, state.player)
        typed = [key(pygame.K_d, 'd'), key(pygame.K_s, 's')]
        real_show = self.renderer._show
        shown = []

        def show(paint):
            if not shown:  # the shake's first frame: the player types ahead
                for event in typed:
                    pygame.event.post(event)
            shown.append(1)
            real_show(paint)

        start = pygame.time.get_ticks()
        with mock.patch.object(self.renderer, '_show', side_effect=show):
            self.renderer.draw(state)
        elapsed = pygame.time.get_ticks() - start
        self.assertGreaterEqual(elapsed, self.renderer.impact_ms - 20)  # not cut short
        self.assertGreaterEqual(len(shown), 2)  # shake frame(s), then the final one
        self.assertTrue(pygame.event.peek(pygame.KEYDOWN))  # not consumed
        self.assertEqual(self.renderer.get_action(), Action.MOVE_E)  # in order
        self.assertEqual(self.renderer.get_action(), Action.MOVE_S)

    def test_window_close_still_ends_a_shake(self):
        state, goblin = self.fight()
        state.attack(goblin, state.player)
        self.renderer.impact_ms = 5000
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        start = pygame.time.get_ticks()
        self.renderer.draw(state)
        self.assertLess(pygame.time.get_ticks() - start, 1000)
        self.assertEqual(self.renderer.get_action(), Action.QUIT)

    # -- the struck sprite's own shake ----------------------------------------

    def impact_frame(self, state, hit, t, sprite=True):
        """The map painted at t of `hit`'s beat, without the map's shake, so
        only the sprite's own jitter differs between sprite=True and False."""
        r = self.renderer
        r.canvas.clear()
        shake = camera.shake_for(hit)
        r._paint_game(state, impact=(hit, t), sprite_shake=shake if sprite else None)
        return r.canvas.surface.copy()

    def assert_sprite_shakes(self, state, hit, attacker):
        r = self.renderer
        map_rect = r.layout.map_rect()
        if r._view is not None:
            r._proj = camera.project(r._view, map_rect, r.layout.map_cell_size())
        try:
            struck = r._map_cell_rect(hit.x, hit.y)
            other = r._map_cell_rect(attacker.x, attacker.y)
        finally:
            r._proj = None
        # The struck sprite may spill a few pixels over the edge it shares
        # with the attacker; the rest of the attacker's cell is its own
        # sprite, which must not jitter.
        spill = camera.sprite_shake_peak(camera.shake_for(hit), struck.height)
        dx, dy = attacker.x - hit.x, attacker.y - hit.y
        own = pygame.Rect(other)
        if dx:
            own.width -= spill
            own.left += spill if dx > 0 else 0
        else:
            own.height -= spill
            own.top += spill if dy > 0 else 0
        moved = False
        for step in range(10):
            t = step / 10
            jolted = self.impact_frame(state, hit, t)
            still = self.impact_frame(state, hit, t, sprite=False)
            if area_bytes(jolted, struck) != area_bytes(still, struck):
                moved = True
            self.assertEqual(area_bytes(jolted, own), area_bytes(still, own), t)
        self.assertTrue(moved, 'the struck sprite never moved')
        # The beat's end: exactly back in its cell, the whole map unchanged.
        end = self.impact_frame(state, hit, 1.0)
        still = self.impact_frame(state, hit, 1.0, sprite=False)
        self.assertEqual(area_bytes(end, map_rect), area_bytes(still, map_rect))

    def test_the_struck_monster_shakes_in_its_cell(self):
        state, goblin = self.fight()
        state.attack(state.player, goblin)
        hit = state.combat_events[-1]
        self.assertIs(hit.defender, goblin)
        self.assertFalse(hit.killed)
        self.assert_sprite_shakes(state, hit, state.player)

    def test_the_struck_player_shakes_in_its_cell(self):
        state, goblin = self.fight()
        state.attack(goblin, state.player)
        hit = state.combat_events[-1]
        self.assertIs(hit.defender, state.player)
        self.assert_sprite_shakes(state, hit, goblin)

    def test_the_struck_sprite_shakes_zoomed_in(self):
        state, goblin = self.fight(zoom=True)
        self.assertIsNotNone(self.renderer._view)
        state.attack(state.player, goblin)
        self.assert_sprite_shakes(state, state.combat_events[-1], state.player)

    def test_sprite_shake_is_repeatable_decays_and_is_bigger_for_a_crit(self):
        state, goblin = self.fight()
        state.attack(state.player, goblin)
        hit = state.combat_events[-1]
        crit = hit._replace(crit=True)
        r = self.renderer
        cell = r._map_cell_rect(hit.x, hit.y).height

        def peak(h):
            shake = camera.shake_for(h)
            ts = [i / 50 for i in range(50)]
            offsets = [r.sprite_shake_offset(shake, t, h) for t in ts]
            self.assertEqual(offsets, [r.sprite_shake_offset(shake, t, h) for t in ts])
            self.assertEqual(r.sprite_shake_offset(shake, 1.0, h), (0, 0))
            return max(max(abs(dx), abs(dy)) for dx, dy in offsets)

        normal, big = peak(hit), peak(crit)
        self.assertGreater(normal, 0)
        self.assertGreater(big, normal)
        self.assertLessEqual(normal, round(cell * camera.SHAKE_AMPLITUDE))
        self.assertLessEqual(big, round(cell * camera.CRIT_SHAKE_AMPLITUDE))
        # Not just the map's shake again: the sprite has its own draws.
        shake = camera.shake_for(hit)
        self.assertNotEqual(
            [camera.sprite_shake_offset(shake, i / 10, cell) for i in range(10)],
            [camera.shake_offset(shake, i / 10, cell) for i in range(10)],
        )

    def test_health_bar_moves_with_the_shaking_sprite(self):
        from render.pygame_render import HEALTH_BAR_COLORS

        state, goblin = self.fight()
        r = self.renderer
        map_rect = r.layout.map_rect()
        still = r.health_bar_rect(goblin, state.player, map_rect)
        r._jolt = (goblin, (3, -2))
        try:
            moved = r.health_bar_rect(goblin, state.player, map_rect)
        finally:
            r._jolt = None
        self.assertEqual(moved, still.move(3, -2))
        # Painted with the goblin jolted: the bar is drawn at the moved rect.
        r.canvas.clear()
        r._jolt = (goblin, (3, -2))
        r._paint_game(state)
        self.assertIsNone(r._jolt)  # one frame only
        self.assertTrue(set(cell_pixels(r, moved)) <= HEALTH_BAR_COLORS)
        r.canvas.clear()
        r._paint_game(state)
        self.assertTrue(set(cell_pixels(r, still)) <= HEALTH_BAR_COLORS)

    # -- health bars ----------------------------------------------------------

    def bar(self, state, goblin):
        r = self.renderer
        r.draw(state)
        return r.health_bar_rect(goblin, state.player, r.layout.map_rect())

    def fill_width(self, rect, color):
        y = rect.centery
        screen = self.renderer.canvas.surface
        return sum(
            1 for x in range(rect.left, rect.right) if tuple(screen.get_at((x, y)))[:3] == color
        )

    def test_bar_fill_is_proportional_and_banded(self):
        from render.pygame_render import HEALTH_AMBER, HEALTH_GREEN, HEALTH_RED

        state, goblin = self.fight()
        for hp, color in (
            (20, HEALTH_GREEN),
            (11, HEALTH_GREEN),
            (10, HEALTH_AMBER),
            (5, HEALTH_AMBER),
            (4, HEALTH_RED),
        ):
            goblin.hp = hp
            rect = self.bar(state, goblin)
            self.assertEqual(self.fill_width(rect, color), round(rect.width * hp / 20), hp)
        goblin.hp = 20
        self.assertEqual(
            self.fill_width(self.bar(state, goblin), HEALTH_GREEN), self.bar(state, goblin).width
        )

    def test_bar_has_only_bar_colours(self):
        from render.pygame_render import HEALTH_BAR_COLORS

        state, goblin = self.fight()
        for hp in (20, 10, 3):
            goblin.hp = hp
            rect = self.bar(state, goblin)
            self.assertTrue(set(cell_pixels(self.renderer, rect)) <= HEALTH_BAR_COLORS)

    def test_bar_sits_above_the_cell_and_never_on_the_player(self):
        state, goblin = self.fight()
        r = self.renderer
        map_rect = r.layout.map_rect()
        cell = r._map_cell_rect(goblin.x, goblin.y)
        far = collections.namedtuple('P', 'x y')(goblin.x + 5, goblin.y)
        above = r.health_bar_rect(goblin, far, map_rect)
        self.assertLessEqual(above.bottom, cell.top)
        self.assertLess(above.width, cell.width)
        # The player in the cell above: the bar moves onto the goblin's own top edge.
        player = collections.namedtuple('P', 'x y')(goblin.x, goblin.y - 1)
        own = r.health_bar_rect(goblin, player, map_rect)
        self.assertTrue(cell.contains(own))
        self.assertFalse(own.colliderect(r._map_cell_rect(player.x, player.y)))
        # Top row of the map: along its top edge too.
        top = Monster(goblin.x, 0, 'goblin')
        self.assertTrue(r._map_cell_rect(top.x, 0).contains(r.health_bar_rect(top, far, map_rect)))

    def test_boss_bar_is_wider_and_bars_follow_the_zoom(self):
        state, goblin = self.fight()
        r = self.renderer
        map_rect = r.layout.map_rect()
        far = collections.namedtuple('P', 'x y')(goblin.x + 5, goblin.y)
        boss = Monster(goblin.x, goblin.y, 'goblin', is_boss=True)
        self.assertGreater(
            r.health_bar_rect(boss, far, map_rect).width,
            r.health_bar_rect(goblin, far, map_rect).width,
        )
        normal = r.health_bar_rect(goblin, far, map_rect)
        state, goblin = self.fight(zoom=True)
        self.assertIsNotNone(r._view)
        r._proj = camera.project(r._view, map_rect, r.layout.map_cell_size())
        try:
            zoomed = r.health_bar_rect(goblin, far, map_rect)
            cell = r._map_cell_rect(goblin.x, goblin.y)
        finally:
            r._proj = None
        self.assertGreater(zoomed.width, normal.width)
        self.assertEqual(zoomed.centerx, cell.centerx)

    def test_no_bar_for_the_player_or_an_unseen_monster(self):
        state, goblin = self.fight()
        painted = []
        with mock.patch.object(
            self.renderer, '_paint_health_bar', side_effect=lambda m, p, r: painted.append(m)
        ):
            self.renderer.draw(state)
            self.assertEqual(painted, [goblin])
            painted.clear()
            state.visible[goblin.y][goblin.x] = False  # remembered, not in view
            state.seen[goblin.y][goblin.x] = True
            self.renderer.draw(state)
        self.assertEqual(painted, [])


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class GlyphModeSpriteShakeTest(unittest.TestCase):
    """The struck sprite's own shake with no tileset: glyphs, not tiles."""

    fight = HitShakeAndHealthBarTest.fight
    impact_frame = HitShakeAndHealthBarTest.impact_frame
    assert_sprite_shakes = HitShakeAndHealthBarTest.assert_sprite_shakes
    test_the_struck_monster_shakes_in_its_cell = (
        HitShakeAndHealthBarTest.test_the_struck_monster_shakes_in_its_cell
    )
    test_the_struck_player_shakes_in_its_cell = (
        HitShakeAndHealthBarTest.test_the_struck_player_shakes_in_its_cell
    )
    test_the_struck_sprite_shakes_zoomed_in = (
        HitShakeAndHealthBarTest.test_the_struck_sprite_shakes_zoomed_in
    )

    def setUp(self):
        self.renderer = PygameRenderer(WIDTH, HEIGHT)
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        self.renderer.zoom_ms = 0
        self.assertFalse(self.renderer.layout.tile)
        pygame.event.clear()

    def tearDown(self):
        self.renderer.close()


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class ChestChoiceScreenTest(unittest.TestCase):
    """The "choose one of three" overlay: drawn while state.is_choosing,
    answered with 1/2/3 or a left click on a card."""

    tiles = False

    def setUp(self):
        import random

        from game.item import JUNK, Item

        tileset = None
        if self.tiles:
            from game.paths import resource_path
            from render.tileset import Tileset

            tileset = Tileset(resource_path('assets'))
        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=tileset)
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        pygame.event.clear()
        random.seed(70)
        self.state = GameState(WIDTH, HEIGHT)
        self.items = [Item(0, 0, 'armor', 'rare'), Item(0, 0, 'weapon', 'epic'), Item(0, 0, JUNK)]
        self.state.pending_choice = list(self.items)

    def tearDown(self):
        self.renderer.close()

    def click(self, pos, button=1):
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button))

    def cards(self):
        return screens.choice_rects(self.renderer.layout, self.state)[1]

    def test_frame_while_choosing_differs_from_one_without(self):
        box = screens.choice_rects(self.renderer.layout, self.state)[0]
        self.renderer.draw(self.state)
        with_choice = cell_pixels(self.renderer, box, as_list=True)
        pending, self.state.pending_choice = self.state.pending_choice, None
        self.renderer.draw(self.state)
        without = cell_pixels(self.renderer, box, as_list=True)
        self.state.pending_choice = pending
        self.assertNotEqual(with_choice, without)

    def test_three_cards_inside_the_box_and_apart(self):
        box, cards, _ = screens.choice_rects(self.renderer.layout, self.state)
        self.assertEqual(len(cards), 3)
        for i, card in enumerate(cards):
            self.assertTrue(box.contains(card))
            for other in cards[i + 1 :]:
                self.assertFalse(card.colliderect(other))

    def test_clicking_a_card_chooses_it(self):
        self.renderer.draw(self.state)
        self.click(self.cards()[1].center)
        action = self.renderer.get_action()
        self.assertEqual(action, Action.CHOOSE_2)
        self.state.handle_action(action)
        self.assertFalse(self.state.is_choosing)
        self.assertIs(self.state.player.weapon, self.items[1])

    def test_clicking_outside_the_cards_does_nothing(self):
        self.renderer.draw(self.state)
        box = screens.choice_rects(self.renderer.layout, self.state)[0]
        self.click((box.left + 2, box.top + 2))  # the box, not a card
        self.click((0, 0))  # off the box entirely
        self.click(self.cards()[0].center, button=3)  # right click
        pygame.event.post(
            pygame.event.Event(
                pygame.MOUSEMOTION, pos=self.cards()[0].center, rel=(1, 1), buttons=(0, 0, 0)
            )
        )
        pygame.event.post(key(pygame.K_PERIOD, '.'))
        self.assertEqual(self.renderer.get_action(), Action.WAIT)
        self.assertTrue(self.state.is_choosing)

    def test_keyboard_2_chooses_the_second_item(self):
        self.renderer.draw(self.state)
        pygame.event.post(key(pygame.K_2, '2'))
        self.state.handle_action(self.renderer.get_action())
        self.assertIs(self.state.player.weapon, self.items[1])
        self.assertIsNone(self.state.player.armor)

    def test_card_clicks_mean_nothing_once_the_choice_is_made(self):
        self.renderer.draw(self.state)
        center = self.cards()[0].center
        self.state.choose(2)
        self.renderer.draw(self.state)
        self.click(center)
        pygame.event.post(key(pygame.K_d, 'd'))
        self.assertEqual(self.renderer.get_action(), Action.MOVE_E)

    def test_narrow_map_stacks_the_cards(self):
        renderer = self.renderer
        renderer._set_mode((420, 700), pygame.RESIZABLE)
        renderer._relayout()
        box, cards, compact = screens.choice_rects(renderer.layout, self.state)
        if compact:
            self.assertTrue(cards[0].bottom <= cards[1].top <= cards[1].bottom <= cards[2].top)
        renderer.draw(self.state)  # paints without error either way


class TileModeChestChoiceScreenTest(ChestChoiceScreenTest):
    tiles = True


class NewWeaponChoiceScreenTest(ChestChoiceScreenTest):
    """The same overlay with the longest weapon-type cards on it."""

    def setUp(self):
        super().setUp()
        from game.item import JUNK, Item

        self.items = [
            Item(0, 0, 'great_sword', 'rare'),
            Item(0, 0, 'rapier', 'epic'),
            Item(0, 0, JUNK),
        ]
        self.state.pending_choice = list(self.items)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class BoonChoiceScreenTest(unittest.TestCase):
    """A shrine's boons on the same overlay as a chest's items: painted in
    glyph and tile mode, chosen with 2 or a click on the second card; and
    the shrine itself painted on the map."""

    tiles = False

    def setUp(self):
        import random

        from game.shrine import BOONS

        tileset = None
        if self.tiles:
            from game.paths import resource_path
            from render.tileset import Tileset

            tileset = Tileset(resource_path('assets'))
        self.renderer = PygameRenderer(WIDTH, HEIGHT, tileset=tileset)
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        pygame.event.clear()
        random.seed(71)
        self.state = GameState(WIDTH, HEIGHT)
        self.boons = [BOONS['blood_pact'], BOONS['iron_skin'], BOONS['quick_hands']]
        self.state.pending_choice = list(self.boons)

    def tearDown(self):
        self.renderer.close()

    def cards(self):
        return screens.choice_rects(self.renderer.layout, self.state)[1]

    def test_boon_cards_paint_inside_the_box(self):
        box, cards, _ = screens.choice_rects(self.renderer.layout, self.state)
        self.assertEqual(len(cards), 3)
        self.renderer.draw(self.state)
        for card in cards:
            self.assertTrue(box.contains(card))
            self.assertGreater(len(cell_pixels(self.renderer, card)), 2)  # inked text

    def test_clicking_a_boon_card_takes_that_boon(self):
        self.renderer.draw(self.state)
        pygame.event.post(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=self.cards()[1].center, button=1)
        )
        action = self.renderer.get_action()
        self.assertEqual(action, Action.CHOOSE_2)
        self.assertFalse(self.state.handle_action(action))  # no turn
        self.assertFalse(self.state.is_choosing)
        self.assertEqual(self.state.player.boons, ['iron_skin'])

    def test_keyboard_3_takes_the_third_boon(self):
        self.renderer.draw(self.state)
        pygame.event.post(key(pygame.K_3, '3'))
        self.state.handle_action(self.renderer.get_action())
        self.assertEqual(self.state.player.boons, ['quick_hands'])

    def test_shrine_is_painted_on_the_map(self):
        from game.shrine import Shrine

        state = self.state
        state.pending_choice = None
        x, y = open_neighbour(state)
        self.renderer.draw(state)
        rect = self.renderer._map_cell_rect(x, y)
        floor = cell_pixels(self.renderer, rect, as_list=True)
        state.entities.append(Shrine(x, y))
        self.renderer.draw(state)
        self.assertNotEqual(cell_pixels(self.renderer, rect, as_list=True), floor)


class TileModeBoonChoiceScreenTest(BoonChoiceScreenTest):
    tiles = True


class ChoiceCardTextTest(unittest.TestCase):
    """render/choice.py's card text (stdlib only: no pygame needed)."""

    def text(self, kind, rarity='common'):
        from game.item import Item
        from render import choice

        return choice.stat_text(Item(0, 0, kind, rarity))

    def test_each_kind_at_each_rarity(self):
        expected = {
            'weapon': ['+1 damage', '+2 damage', '+4 damage', '+7 damage'],
            'armor': ['+3 defence', '+6 defence', '+12 defence', '+21 defence'],
            'leather': [
                '+2 defence, 4% dodge',
                '+3 defence, 6% dodge',
                '+6 defence, 9% dodge',
                '+10 defence, 12% dodge',
            ],
            'war_axe': [
                '+0 damage, +3 HP',
                '+1 damage, +6 HP',
                '+3 damage, +9 HP',
                '+6 damage, +15 HP',
            ],
            'rapier': [
                '-1 damage, strikes twice',
                '+0 damage, strikes twice',
                '+2 damage, strikes twice',
                '+5 damage, strikes twice',
            ],
            'great_sword': [
                '+2 damage, hits a 2nd adjacent foe',
                '+3 damage, hits a 2nd adjacent foe',
                '+5 damage, hits a 2nd adjacent foe',
                '+8 damage, hits a 2nd adjacent foe',
            ],
            'sword_shield': [
                '+1 damage, +3 defence',
                '+2 damage, +6 defence',
                '+4 damage, +9 defence',
                '+7 damage, +12 defence',
            ],
            'dagger': [
                '+0 damage, +5% crit',
                '+1 damage, +10% crit',
                '+3 damage, +15% crit',
                '+6 damage, +20% crit',
            ],
            'spear': [
                '+1 damage, reach 2',
                '+2 damage, reach 2',
                '+4 damage, reach 2',
                '+7 damage, reach 2',
            ],
            'longbow': [
                '+0 damage, pierces 2',
                '+1 damage, pierces 2',
                '+3 damage, pierces 3',
                '+6 damage, pierces 4',
            ],
            'heavy_crossbow': [
                '+3 damage, reload 2',
                '+4 damage, reload 2',
                '+6 damage, reload 1',
                '+9 damage, reload 1',
            ],
            'volley_bow': [
                '-1 damage, +2 arrows at 50%',
                '+0 damage, +2 arrows at 50%',
                '+2 damage, +3 arrows at 60%',
                '+5 damage, +3 arrows at 70%',
            ],
            'sling': [
                '+0 damage, knockback 1',
                '+1 damage, knockback 1',
                '+3 damage, knockback 2',
                '+6 damage, knockback 2',
            ],
            'hunters_bow': [
                '+0 damage, mark +25%',
                '+1 damage, mark +50%',
                '+3 damage, mark +75%',
                '+6 damage, mark +100%',
            ],
            'quickdraw': [
                '+1 damage, every 4 shots free',
                '+2 damage, every 4 shots free',
                '+4 damage, every 3 shots free',
                '+7 damage, every 2 shots free',
            ],
        }
        from game.item import GEAR_KINDS, RARITIES

        self.assertEqual(set(expected), set(GEAR_KINDS))
        for kind, lines in expected.items():
            self.assertEqual([self.text(kind, r) for r in RARITIES], lines, kind)

    def test_junk_still_shows_nothing_useful(self):
        from game.item import JUNK, Item
        from render import choice

        junk = Item(0, 0, JUNK)
        self.assertEqual(choice.stat_text(junk), 'nothing useful')
        self.assertEqual(
            choice.card_lines(3, junk), ['[3]', 'Rusty scrap', 'junk', 'nothing useful']
        )

    def test_cards_name_and_rarity_for_a_new_kind(self):
        from game.item import Item
        from render import choice

        item = Item(0, 0, 'dagger', 'rare')
        self.assertEqual(
            choice.card_lines(1, item), ['[1]', item.name, 'rare', '+3 damage, +15% crit']
        )
        self.assertIn('+15% crit', choice.compact_lines(1, item)[1])


# -- helpers -----------------------------------------------------------------


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class BossArenaTest(unittest.TestCase):
    """Dark stone in the arena's 3x3 centre and blood decals round the room
    (a stub `boss_arena` stands in for the one game/ provides)."""

    class Arena:
        x1, y1, x2, y2 = 8, 4, 28, 16

        def center(self):
            return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    def setUp(self):
        from game.paths import resource_path
        from render.tileset import Tileset

        self.renderer = PygameRenderer(
            WIDTH, HEIGHT, tileset=Tileset(resource_path('assets')), combat_zoom=False
        )
        self.renderer._set_mode((1600, 900), pygame.RESIZABLE)
        self.renderer._relayout()
        self.arena = self.Arena()

    def tearDown(self):
        self.renderer.close()

    def state(self, arena):
        state = GameState(WIDTH, HEIGHT)
        state.entities[:] = []
        for y in range(HEIGHT):
            for x in range(WIDTH):
                edge = x in (0, WIDTH - 1) or y in (0, HEIGHT - 1)
                state.game_map[y][x] = '#' if edge else '.'
                state.visible[y][x] = state.seen[y][x] = True
        state.player.x, state.player.y = 1, 1
        state.boss_arena = arena
        return state

    def frame(self, arena):
        self.renderer.draw(self.state(arena))
        return self.renderer.canvas.surface.copy()

    def cell(self, surface, x, y):
        rect = self.renderer.layout.map_cell_to_pixel(x, y)
        size = self.renderer.layout.map_cell_size()
        return pygame.image.tobytes(surface.subsurface(pygame.Rect(rect, size)), 'RGB')

    def decal_cells(self):
        layout = self.renderer._arena_decals(self.arena)
        return sorted(layout)

    def test_centre_stone_differs_from_plain_floor(self):
        plain, arena = self.frame(None), self.frame(self.arena)
        cx, cy = self.arena.center()
        self.assertNotEqual(self.cell(plain, cx, cy), self.cell(arena, cx, cy))

        # The tint is darker, not just different.
        def total(b):
            return sum(b)

        self.assertLess(total(self.cell(arena, cx, cy)), total(self.cell(plain, cx, cy)))

    def test_decal_cell_differs_from_plain_floor(self):
        plain, arena = self.frame(None), self.frame(self.arena)
        cx, cy = self.arena.center()
        changed = [
            c
            for c in self.decal_cells()
            if max(abs(c[0] - cx), abs(c[1] - cy)) > 1
            and self.cell(plain, *c) != self.cell(arena, *c)
        ]
        self.assertTrue(changed)

    def test_decals_are_stable_across_draws(self):
        first, second = self.frame(self.arena), self.frame(self.arena)
        self.assertEqual(pygame.image.tobytes(first, 'RGB'), pygame.image.tobytes(second, 'RGB'))
        layout = dict(self.renderer._arena_decals(self.arena))
        self.renderer._decal_layouts.clear()
        self.assertEqual(layout, self.renderer._arena_decals(self.arena))

    def test_no_arena_is_the_plain_frame(self):
        plain = self.frame(None)
        state = self.state(None)
        del state.boss_arena
        self.renderer.draw(state)
        self.assertEqual(
            pygame.image.tobytes(plain, 'RGB'),
            pygame.image.tobytes(self.renderer.canvas.surface, 'RGB'),
        )

    def test_decals_stay_off_walls(self):
        state = self.state(self.arena)
        state.game_map[6][10] = '#'
        decals = {(10, 6): (0, 0, 1.0)}
        with mock.patch.object(self.renderer, '_arena_decals', return_value=decals):
            self.renderer.draw(state)
        after = self.renderer.canvas.surface
        wall = self.cell(after, 10, 6)
        state.boss_arena = None
        self.renderer.draw(state)
        self.assertEqual(wall, self.cell(self.renderer.canvas.surface, 10, 6))


def cell_pixels(renderer, rect, as_list=False):
    screen = renderer.canvas.surface
    pixels = [
        tuple(screen.get_at((x, y)))[:3]
        for y in range(rect.top, rect.bottom)
        for x in range(rect.left, rect.right)
    ]
    return pixels if as_list else set(pixels)


def area_bytes(surface, rect):
    """The RGB bytes of `rect` on `surface`, to compare two frames' areas."""
    return pygame.image.tobytes(surface.subsurface(rect).copy(), 'RGB')


def lit_pixels(renderer, rect):
    return [p for p in cell_pixels(renderer, rect, as_list=True) if p != BACKGROUND]


def find_tile(state, char):
    for y, row in enumerate(state.game_map):
        for x, tile in enumerate(row):
            if tile == char:
                return x, y
    raise AssertionError(f'no {char!r} on the map')


def open_neighbour(state):
    """An orthogonal floor tile next to the player (it starts mid-room)."""
    px, py = state.player.x, state.player.y
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if state.game_map[py + dy][px + dx] == '.':
            return px + dx, py + dy
    raise AssertionError('player has no open floor next to it')


def kill_player_next_turn(state):
    """Clear the level, then put one goblin next to a 1-HP player."""
    state.cancel_monster_phase()
    state.player.hp = 1
    state.player.defense = 0
    x, y = open_neighbour(state)
    state.entities = [state.player, Monster(x, y, 'goblin', depth=state.depth)]
    state.update_fov()


def record_frames(renderer):
    """Wrap renderer.draw to note state.game_over at every frame."""
    frames = []
    real_draw = renderer.draw

    def draw(state):
        frames.append(state.game_over)
        real_draw(state)

    renderer.draw = draw
    return frames


if __name__ == '__main__':
    unittest.main()
