"""The combat camera's geometry and staging (render/camera.py). Pure logic, no
pygame -- runs in the nothing-installed CI job too."""

import unittest

from game.monster import Monster
from game.state import GameState
from render import camera
from render.camera import Director, Impact, Pan, View

WIDTH, HEIGHT = 40, 20


def lone_fight(char_class='warrior'):
    """A level with only the player and one goblin, orthogonally adjacent."""
    state = GameState(WIDTH, HEIGHT, char_class=char_class)
    px, py = state.player.x, state.player.y
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if state.game_map[py + dy][px + dx] == '.':
            goblin = Monster(px + dx, py + dy, 'goblin')
            break
    else:
        raise AssertionError('player has no open floor next to it')
    state.entities = [state.player, goblin]
    state.update_fov()
    return state, goblin


class ViewGeometryTest(unittest.TestCase):
    def test_combat_view_centres_the_pair_with_two_squares_round_it(self):
        a, b = Monster(10, 5, 'goblin'), Monster(11, 5, 'goblin')
        view = camera.combat_view(a, b)
        self.assertEqual(view, View(8, 3, 6, 5))
        self.assertEqual(view.center, (11.0, 5.5))  # midway between the two cells

    def test_combat_view_is_not_clamped_at_the_map_edge(self):
        view = camera.combat_view(Monster(1, 1, 'goblin'), Monster(1, 2, 'goblin'))
        self.assertEqual(view, View(-1, -1, 5, 6))

    def test_full_view_projects_onto_the_unzoomed_grid(self):
        # A 40x20 map of 24px tiles at (100, 50): zoom 1, origin unchanged.
        proj = camera.project(camera.full_view(40, 20), (100, 50, 960, 480), (24, 24))
        self.assertEqual(proj, (24, 24, 100, 50))

    def test_zoomed_view_fills_the_rect_and_centres_the_fight(self):
        view = View(8, 3, 6, 5)
        cell_w, cell_h, ox, oy = camera.project(view, (0, 0, 960, 480), (24, 24))
        self.assertEqual((cell_w, cell_h), (96, 96))  # 5 rows fit 480px exactly
        cx, cy = view.center
        self.assertEqual((ox + cx * cell_w, oy + cy * cell_h), (480, 240))

    def test_text_cells_keep_their_shape(self):
        cell_w, cell_h, _, _ = camera.project(View(0, 0, 6, 5), (0, 0, 400, 400), (10, 20))
        self.assertEqual(cell_h, 2 * cell_w)

    def test_ease_and_lerp_hit_both_ends(self):
        a, b = View(0, 0, 40, 20), View(8, 3, 6, 5)
        self.assertEqual(camera.lerp_view(a, b, camera.ease(0)), a)
        self.assertEqual(camera.lerp_view(a, b, camera.ease(1)), b)
        self.assertEqual(camera.ease(-1), 0)
        self.assertEqual(camera.ease(2), 1)


class DirectorTest(unittest.TestCase):
    def test_nothing_in_melee_range_stages_nothing(self):
        state, goblin = lone_fight()
        goblin.x, goblin.y = state.player.x + 5, state.player.y
        director = Director()
        self.assertEqual(director.plan(state), [])
        self.assertIsNone(director.view)

    def test_enemy_in_melee_range_zooms_in_on_the_pair(self):
        state, goblin = lone_fight()
        director = Director()
        beats = director.plan(state)
        target = camera.combat_view(state.player, goblin)
        self.assertEqual(beats, [Pan(camera.full_view(WIDTH, HEIGHT), target)])
        self.assertEqual(director.view, target)
        self.assertIs(director.focus, goblin)
        # Already framed: the next frame stages nothing.
        self.assertEqual(director.plan(state), [])

    def test_a_hit_plays_before_the_camera_moves(self):
        state, goblin = lone_fight()
        director = Director()
        director.plan(state)
        goblin.hp = 1
        state.attack(state.player, goblin)       # the killing blow
        beats = director.plan(state)
        self.assertEqual([type(b) for b in beats], [Impact, Pan])
        self.assertTrue(beats[0].hit.killed)
        self.assertEqual(beats[1].end, camera.full_view(WIDTH, HEIGHT))  # fight over
        self.assertIsNone(director.view)

    def test_each_hit_is_staged_once(self):
        state, goblin = lone_fight()
        director = Director()
        director.plan(state)
        state.attack(goblin, state.player)
        self.assertEqual(len(director.plan(state)), 1)
        self.assertEqual(director.plan(state), [])  # the same round, redrawn

    def test_archer_does_not_zoom(self):
        state, goblin = lone_fight('archer')
        state.attack(goblin, state.player)
        beats = Director().plan(state)
        self.assertEqual([type(b) for b in beats], [Impact])  # hit shown, no zoom

    def test_zoom_can_be_switched_off(self):
        state, _ = lone_fight()
        self.assertEqual(Director(zoom=False).plan(state), [])

    def test_death_pulls_the_camera_back_out(self):
        state, _ = lone_fight()
        director = Director()
        director.plan(state)
        state.game_over = True
        self.assertEqual(director.plan(state)[-1].end, camera.full_view(WIDTH, HEIGHT))

    def test_focus_stays_on_the_fight_already_framed(self):
        state, goblin = lone_fight()
        director = Director()
        director.plan(state)
        px, py = state.player.x, state.player.y
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            x, y = px + dx, py + dy
            if state.game_map[y][x] == '.' and (x, y) != (goblin.x, goblin.y):
                second = Monster(x, y, 'orc')
                break
        else:
            self.skipTest('no second open neighbour on this map')
        state.entities.append(second)
        self.assertEqual(director.plan(state), [])
        self.assertIs(director.focus, goblin)
        # The framed goblin dies: the camera moves across to the orc.
        goblin.alive = False
        beats = director.plan(state)
        self.assertIs(director.focus, second)
        self.assertEqual(beats[-1].end, camera.combat_view(state.player, second))



class SpearZoomTest(unittest.TestCase):
    """A spear's reach (2) starts the combat zoom one square early."""

    def arena(self, spear=True):
        from game.item import Item
        state = GameState(WIDTH, HEIGHT, char_class='warrior')
        for y in range(1, HEIGHT - 1):
            for x in range(1, WIDTH - 1):
                state.game_map[y][x] = '.'
        p = state.player
        p.x, p.y = 10, 10
        if spear:
            Item(0, 0, 'spear', 'common').apply(p, state.log)
        state.entities = [p]
        state.update_fov()
        return state

    def add(self, state, x, y):
        m = Monster(x, y, 'goblin')
        state.entities.append(m)
        state.update_fov()
        return m

    def test_spear_zooms_on_a_monster_two_away_in_a_line(self):
        state = self.arena()
        m = self.add(state, 12, 10)
        self.assertIn(m, state.zoom_opponents())
        self.assertNotIn(m, state.melee_opponents())
        director = Director()
        beats = director.plan(state)
        self.assertEqual(beats, [Pan(camera.full_view(WIDTH, HEIGHT),
                                     camera.combat_view(state.player, m))])
        self.assertIs(director.focus, m)
        # fight over (monster dies): zoom back out
        m.alive = False
        self.assertEqual(director.plan(state)[-1].end, camera.full_view(WIDTH, HEIGHT))

    def test_wall_in_the_middle_does_not_zoom(self):
        state = self.arena()
        self.add(state, 10, 12)
        state.game_map[11][10] = '#'
        state.update_fov()
        self.assertEqual(state.zoom_opponents(), [])
        self.assertEqual(Director().plan(state), [])

    def test_monster_in_the_middle_is_the_only_opponent(self):
        state = self.arena()
        near = self.add(state, 9, 10)
        far = self.add(state, 8, 10)
        self.assertEqual(state.zoom_opponents(), [near])
        self.assertNotIn(far, state.zoom_opponents())

    def test_diagonal_two_away_does_not_zoom(self):
        state = self.arena()
        self.add(state, 12, 12)
        self.assertEqual(state.zoom_opponents(), [])
        self.assertEqual(Director().plan(state), [])

    def test_no_spear_two_away_does_not_zoom(self):
        state = self.arena(spear=False)
        self.add(state, 12, 10)
        self.assertEqual(state.zoom_opponents(), [])
        self.assertEqual(Director().plan(state), [])

    def test_spear_with_adjacent_monster_still_zooms(self):
        state = self.arena()
        m = self.add(state, 11, 10)
        self.assertEqual(state.zoom_opponents(), [m])
        self.assertIs(Director().plan(state) and True, True)
        d = Director()
        d.plan(state)
        self.assertIs(d.focus, m)


if __name__ == '__main__':
    unittest.main()
