"""Headless tests for the pygame renderer (SDL dummy video/audio drivers).

Skipped cleanly when pygame-ce isn't installed, so a stdlib-only checkout still
has a green suite. Events are injected with pygame.event.post, which is the same
queue a real window feeds -- so these exercise the actual blocking wait.
"""

import collections
import os
import sys
import unittest
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
        pixels = {tuple(screen.get_at((x, y)))[:3]
                  for x in range(cell.left, cell.right) for y in range(cell.top, cell.bottom)}
        self.assertTrue(pixels - {BACKGROUND}, 'player cell is blank')

    def test_get_action_maps_keys_like_curses(self):
        self.post(key(pygame.K_w, 'w'), key(pygame.K_s, 'S', shift=True),
                  key(pygame.K_UP), key(pygame.K_PERIOD, '.'))
        self.assertEqual(self.renderer.get_action(), Action.MOVE_N)
        self.assertEqual(self.renderer.get_action(), Action.SAVE)
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
        self.post(pygame.event.Event(pygame.VIDEORESIZE, size=(3000, 1500), w=3000, h=1500),
                  key(pygame.K_d, 'd'))
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
        self.post(enter, key(pygame.K_s, 's'), enter,
                  key(pygame.K_w, 'w'), key(pygame.K_RIGHT), key(pygame.K_PERIOD, '.'),
                  key(pygame.K_q, 'q'))
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
        self.assertTrue(cell_pixels(self.renderer, cell) - {BACKGROUND},
                        'frame not repainted after going fullscreen')

    def test_f11_in_a_menu_is_not_a_selection(self):
        # F11 twice (in and out), then Down: still on the title menu, so the
        # Enter selects Quit -- F11 neither confirmed nor moved anything.
        self.post(key(pygame.K_F11), key(pygame.K_F11), key(pygame.K_DOWN),
                  key(pygame.K_RETURN, '\r'))
        self.assertFalse(self.renderer.show_title_screen())
        self.assertFalse(self.renderer.fullscreen)

    def test_fullscreen_failure_is_harmless(self):
        size = self.renderer.canvas.surface.get_size()
        window = mock.Mock()
        window.set_fullscreen.side_effect = pygame.error('no fullscreen here')
        with mock.patch.object(PygameRenderer, '_display_window', return_value=window):
            self.renderer.toggle_fullscreen()
        with mock.patch.object(PygameRenderer, '_display_window', return_value=None), \
                mock.patch('pygame.display.set_mode', side_effect=pygame.error('no')):
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
        renderer = main.make_renderer('pygame', WIDTH, HEIGHT)
        try:
            self.assertTrue(renderer.layout.font_path.endswith(main.BUNDLED_FONT))
            self.assertTrue(os.path.isfile(renderer.layout.font_path))
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
        self.post(self.click((9, 9)), self.motion((9, 9)), key(pygame.K_DOWN),
                  key(pygame.K_RETURN, '\r'))
        with mock.patch.object(screens, 'option_at', lambda *a: None):
            self.assertFalse(self.renderer.show_title_screen())  # keys decided it

    def test_menu_right_click_is_ignored(self):
        self.post(self.click((1, 1), button=3), key(pygame.K_RETURN, '\r'))
        with mock.patch.object(screens, 'option_at', lambda *a: 1):
            self.assertTrue(self.renderer.show_title_screen())

    def test_menu_repaints_only_when_the_highlight_changes(self):
        self.post(self.motion(), self.motion(), self.motion(), key(pygame.K_RETURN, '\r'))
        with mock.patch.object(screens, 'option_at', lambda *a: 1), \
                mock.patch.object(screens, 'paint_menu') as paint:
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
        with mock.patch.object(screens, 'option_at', lambda *a: 0) as hit:
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
        row = screens.game_over_rect(layout, state)
        player = pygame.Rect(layout.map_cell_to_pixel(state.player.x, state.player.y),
                             layout.map_cell_size())
        self.assertFalse(row.colliderect(player), 'the banner hides the player')
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
        rect = pygame.Rect(layout.map_cell_to_pixel(state.player.x, state.player.y),
                           layout.map_cell_size())
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
        self.assertGreater(cell, layout.tile)
        self.assertLessEqual(min(map_rect.w // cell, map_rect.h // cell) - 1,
                             min(view.width, view.height))
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
        screen = pygame.display.get_surface()
        self.renderer.draw(state)
        self.assertIsNotNone(self.renderer._view)
        zoomed = screen.copy()
        self.renderer.director = camera.Director(zoom=False)
        self.renderer.draw(state)
        # Blank the map area in both: everything else must match exactly.
        map_rect = self.renderer.layout.map_rect()
        for surface in (zoomed, screen):
            surface.fill(BACKGROUND, map_rect)
        self.assertEqual(pygame.image.tobytes(zoomed, 'RGB'),
                         pygame.image.tobytes(screen, 'RGB'))

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
        with mock.patch.object(self.renderer, '_show',
                               side_effect=lambda paint: (frames.append(1), show(paint))):
            self.renderer.draw(state)
        self.assertGreater(len(frames), 2)   # in-between frames, then the final one

    def test_impact_flashes_the_defender(self):
        self.renderer.zoom_ms = 0
        state, goblin = self.fight()
        self.renderer.draw(state)
        state.attack(goblin, state.player)
        frames = []
        with mock.patch.object(self.renderer, '_paint_impact',
                               side_effect=lambda hit, t: frames.append((hit, t))):
            self.renderer.draw(state)
        self.assertTrue(frames)
        self.assertIs(frames[0][0].defender, state.player)

    def test_crit_number_is_bigger_yellow_with_black_outline(self):
        from render.pygame_render import CRIT_OUTLINE_RGB, CRIT_RGB
        r = self.renderer
        self.assertGreater(r._glyph('-12', CRIT_RGB, bold=True, scale=2).get_height(),
                           r._glyph('-12', CRIT_RGB, bold=True).get_height())
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
        area = r.canvas.surface.subsurface(rect.inflate(rect.width, rect.height)
                                           .clip(r.canvas.surface.get_rect()))
        pixels = {tuple(area.get_at((x, y)))[:3]
                  for x in range(area.get_width()) for y in range(area.get_height())}
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
        band = screens.game_over_rect(self.renderer.layout, state)
        self.assertTrue(self.renderer.layout.map_rect().contains(band))
        after = pygame.display.get_surface()
        self.assertNotEqual(pygame.image.tobytes(after.subsurface(band), 'RGB'),
                            pygame.image.tobytes(before.subsurface(band), 'RGB'))

    def test_tiles_env_zero_keeps_glyph_mode(self):
        with mock.patch.dict(os.environ, {'TILES': '0'}):
            renderer = main.make_renderer('pygame', WIDTH, HEIGHT)
        try:
            self.assertFalse(renderer.layout.tiles)
        finally:
            renderer.close()

    def test_make_renderer_uses_the_bundled_tiles_by_default(self):
        with mock.patch.dict(os.environ):
            os.environ.pop('TILES', None)
            renderer = main.make_renderer('pygame', WIDTH, HEIGHT)
        try:
            self.assertTrue(renderer.layout.tiles)
        finally:
            renderer.close()


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class ChestChoiceScreenTest(unittest.TestCase):
    """The "choose one of three" overlay: drawn while state.is_choosing,
    answered with 1/2/3 or a left click on a card."""

    tiles = False

    def setUp(self):
        import random
        from game.item import Item, JUNK
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
        self.items = [Item(0, 0, 'armor', 'rare'), Item(0, 0, 'weapon', 'epic'),
                      Item(0, 0, JUNK)]
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
            for other in cards[i + 1:]:
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
        self.click((box.left + 2, box.top + 2))          # the box, not a card
        self.click((0, 0))                              # off the box entirely
        self.click(self.cards()[0].center, button=3)    # right click
        pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=self.cards()[0].center,
                                             rel=(1, 1), buttons=(0, 0, 0)))
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


class DefaultRendererTest(unittest.TestCase):
    """main.default_renderer: a frozen (--windowed) exe has no terminal."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop('RENDERER', None)

    def test_source_run_defaults_to_curses(self):
        with mock.patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(main.default_renderer(), 'curses')

    def test_frozen_build_defaults_to_pygame(self):
        with mock.patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(main.default_renderer(), 'pygame')

    def test_env_overrides_the_frozen_default(self):
        os.environ['RENDERER'] = 'curses'
        with mock.patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(main.default_renderer(), 'curses')

    def test_tcod_is_no_longer_a_choice(self):
        self.assertEqual(main.RENDERERS, ['curses', 'pygame'])


# -- helpers -----------------------------------------------------------------

def cell_pixels(renderer, rect, as_list=False):
    screen = renderer.canvas.surface
    pixels = [tuple(screen.get_at((x, y)))[:3]
              for y in range(rect.top, rect.bottom) for x in range(rect.left, rect.right)]
    return pixels if as_list else set(pixels)


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
