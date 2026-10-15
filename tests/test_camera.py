"""The combat camera's geometry and staging (render/camera.py). Pure logic, no
pygame -- runs in the nothing-installed CI job too."""

import unittest
from unittest import mock

from game.item import Item
from game.monster import Monster
from game.state import GameState
from game.tiles import FLOOR, WALL
from render import camera
from render.camera import Director, Flight, Impact, Pan, View

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
        state.attack(state.player, goblin)  # the killing blow
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
        self.assertEqual(
            beats, [Pan(camera.full_view(WIDTH, HEIGHT), camera.combat_view(state.player, m))]
        )
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


class SmoothZoomTest(unittest.TestCase):
    """The direction gate (no zooming in on a monster the player walks away
    from) and the hold (stay zoomed while a monster is within HOLD_RANGE, and
    for HOLD_TURNS player turns after) -- both counted in player turns."""

    def arena(self):
        state = GameState(WIDTH, HEIGHT, char_class='warrior')
        for y in range(1, HEIGHT - 1):
            for x in range(1, WIDTH - 1):
                state.game_map[y][x] = '.'
        state.player.x, state.player.y = 10, 10
        state.entities = [state.player]
        state.fov_radius = 10
        state.update_fov()
        return state

    def add(self, state, x, y, kind='goblin'):
        m = Monster(x, y, kind)
        state.entities.append(m)
        state.update_fov()
        return m

    def zoomed_on(self, state, monster):
        director = Director()
        director.plan(state)
        self.assertIs(director.focus, monster)
        self.assertIsNotNone(director.view)
        return director

    def test_no_zoom_in_while_stepping_away(self):
        state = self.arena()
        goblin = self.add(state, 12, 10)
        director = Director()
        self.assertEqual(director.plan(state), [])
        state.handle_action('move_w')  # the player flees west
        self.assertEqual(state.player.x, 9)
        # The goblin closes in right behind (it had been out of sight, say):
        # in range, but the player's last move took them away from it.
        goblin.x = 10
        state.update_fov()
        self.assertEqual(state.zoom_opponents(), [goblin])
        self.assertEqual(director.plan(state), [])
        self.assertIsNone(director.view)
        self.assertEqual(director.plan(state), [])  # redrawn: still out
        # The player stands and fights: now it zooms in.
        state.handle_action('wait')
        self.assertEqual(director.plan(state)[-1].end, camera.combat_view(state.player, goblin))

    def test_walking_toward_a_monster_zooms_in(self):
        state = self.arena()
        goblin = self.add(state, 12, 10)
        director = Director()
        self.assertEqual(director.plan(state), [])
        state.handle_action('move_e')
        self.assertEqual(
            director.plan(state),
            [Pan(camera.full_view(WIDTH, HEIGHT), camera.combat_view(state.player, goblin))],
        )
        self.assertIs(director.focus, goblin)

    def test_stepping_away_once_zoomed_stays_zoomed(self):
        # The reported jolt: fleeing an adjacent monster zoomed out, then
        # back in when it caught up.
        state = self.arena()
        goblin = self.add(state, 11, 10)
        director = self.zoomed_on(state, goblin)
        state.handle_action('move_w')
        director.plan(state)
        self.assertIsNotNone(director.view)
        self.assertIs(director.focus, goblin)
        while state.step_monster_phase():  # the goblin follows
            director.plan(state)
            self.assertIsNotNone(director.view)
        director.plan(state)
        self.assertEqual(director.view, camera.combat_view(state.player, goblin))

    def test_hold_lasts_exactly_two_player_turns(self):
        state = self.arena()
        goblin = self.add(state, 11, 10)
        director = self.zoomed_on(state, goblin)
        goblin.x = 15  # out of HOLD_RANGE, in view
        state.update_fov()
        for _ in range(camera.HOLD_TURNS):
            for _ in range(4):  # redrawn frames don't count
                director.plan(state)
                self.assertIsNotNone(director.view)
            state.handle_action('wait')
            state.cancel_monster_phase()  # keep the goblin where it is
        beats = director.plan(state)
        self.assertIsNone(director.view)
        self.assertEqual(beats[-1].end, camera.full_view(WIDTH, HEIGHT))

    def test_a_monster_back_in_range_resets_the_hold(self):
        state = self.arena()
        goblin = self.add(state, 11, 10)
        director = self.zoomed_on(state, goblin)
        goblin.x = 15
        state.update_fov()
        director.plan(state)
        state.handle_action('wait')
        goblin.x = 13  # within 3 again
        director.plan(state)
        self.assertEqual(director.view, camera.combat_view(state.player, goblin))
        goblin.x = 15
        for _ in range(camera.HOLD_TURNS):
            state.handle_action('wait')
            director.plan(state)
            self.assertIsNotNone(director.view)  # a fresh countdown
        state.handle_action('wait')
        director.plan(state)
        self.assertIsNone(director.view)

    def test_second_monster_approaching_keeps_the_zoom(self):
        # The other reported case: the first goblin dies while an orc is
        # still on its way -- no zoom-out for a turn in between.
        state = self.arena()
        goblin = self.add(state, 11, 10)
        orc = self.add(state, 15, 10, 'orc')
        director = self.zoomed_on(state, goblin)
        goblin.alive = False
        for x in (14, 13, 12, 11):
            director.plan(state)
            self.assertIsNotNone(director.view, f'zoomed out with the orc at x={orc.x}')
            state.handle_action('wait')
            state.cancel_monster_phase()
            orc.x = x
        director.plan(state)
        self.assertIs(director.focus, orc)
        self.assertEqual(director.view, camera.combat_view(state.player, orc))

    def test_monster_phase_frames_do_not_advance_the_hold(self):
        state = self.arena()
        goblin = self.add(state, 11, 10)
        far = [self.add(state, 17, 10), self.add(state, 10, 17)]  # 7 away, chasing
        director = self.zoomed_on(state, goblin)
        goblin.alive = False
        director.plan(state)  # the countdown starts
        state.handle_action('wait')  # turn 1 of 2
        director.plan(state)
        frames = 0
        while state.step_monster_phase():  # both far ones step closer
            frames += 1
            director.plan(state)
            self.assertIsNotNone(director.view)
        self.assertGreaterEqual(frames, 2)
        director.plan(state)
        self.assertIsNotNone(director.view)
        self.assertTrue(all(m.distance_to(state.player) > camera.HOLD_RANGE for m in far))
        state.handle_action('wait')  # turn 2: the hold is over
        director.plan(state)
        self.assertIsNone(director.view)

    def test_last_monster_gone_zooms_out_at_once(self):
        state = self.arena()
        goblin = self.add(state, 11, 10)
        director = self.zoomed_on(state, goblin)
        goblin.alive = False
        director.plan(state)
        self.assertIsNone(director.view)

    def test_game_over_ends_a_hold(self):
        state = self.arena()
        goblin = self.add(state, 11, 10)
        director = self.zoomed_on(state, goblin)
        goblin.x = 13
        director.plan(state)
        self.assertIsNotNone(director.view)
        state.game_over = True
        director.plan(state)
        self.assertIsNone(director.view)

    def test_turn_counts_player_actions_only(self):
        state = self.arena()
        self.add(state, 17, 10)
        state.handle_action('wait')
        state.end_turn()
        state.handle_action('move_n')
        while state.step_monster_phase():
            pass
        self.assertEqual(state.turn, 2)


class HitShakeTest(unittest.TestCase):
    """Every visible hit's Impact carries a Shake; a crit's is harder and longer."""

    def hit(self, crit):
        state, goblin = lone_fight()
        state.player.power = 1
        goblin.hp = goblin.max_hp = 99
        state.attack(state.player, goblin)
        hit = state.combat_events[-1]._replace(crit=crit)
        return state, hit

    @staticmethod
    def peak(shake, cell=40):
        steps = 400
        return max(
            max(abs(dx), abs(dy))
            for dx, dy in (camera.shake_offset(shake, i / steps, cell) for i in range(steps))
        )

    def test_a_hit_stages_an_impact_with_a_shake(self):
        state, goblin = lone_fight()
        director = Director()
        director.plan(state)
        state.attack(goblin, state.player)
        beats = director.plan(state)
        self.assertIsInstance(beats[0], Impact)
        self.assertEqual(beats[0].shake, camera.shake_for(beats[0].hit))

    def test_a_crit_shakes_harder_and_longer(self):
        _, normal_hit = self.hit(False)
        _, crit_hit = self.hit(True)
        normal, crit = camera.shake_for(normal_hit), camera.shake_for(crit_hit)
        self.assertGreater(crit.ms, normal.ms)
        self.assertGreater(camera.shake_peak(crit, 40), camera.shake_peak(normal, 40))
        self.assertGreater(self.peak(crit), self.peak(normal))
        self.assertTrue(150 <= normal.ms <= 250, normal.ms)
        self.assertTrue(normal.ms < crit.ms <= 350, crit.ms)

    def test_offsets_stay_within_the_peak_and_settle_to_zero(self):
        for crit in (False, True):
            shake = camera.shake_for(self.hit(crit)[1])
            self.assertLessEqual(self.peak(shake), camera.shake_peak(shake, 40))
            self.assertGreater(self.peak(shake), 0)
            self.assertEqual(camera.shake_offset(shake, 1.0, 40), (0, 0))
            self.assertEqual(camera.shake_offset(shake, 1.5, 40), (0, 0))
            late = [camera.shake_offset(shake, 0.97 + i / 1000, 40) for i in range(30)]
            self.assertTrue(all(abs(dx) <= 1 and abs(dy) <= 1 for dx, dy in late))

    def test_offsets_are_deterministic_per_seed(self):
        shake = camera.Shake(camera.SHAKE_MS, camera.SHAKE_AMPLITUDE, 7)
        times = [i / 20 for i in range(20)]
        first = [camera.shake_offset(shake, t, 40) for t in times]
        self.assertEqual(first, [camera.shake_offset(shake, t, 40) for t in times])
        other = shake._replace(seed=8)
        self.assertNotEqual(first, [camera.shake_offset(other, t, 40) for t in times])

    def test_peak_scales_with_the_cell(self):
        shake = camera.shake_for(self.hit(False)[1])
        self.assertGreater(camera.shake_peak(shake, 64), camera.shake_peak(shake, 24))
        self.assertGreaterEqual(camera.shake_peak(shake, 4), camera.MIN_SHAKE_PX)

    def test_sprite_shake_has_the_same_timing_and_a_bigger_crit(self):
        normal = camera.shake_for(self.hit(False)[1])
        crit = camera.shake_for(self.hit(True)[1])
        self.assertGreater(
            camera.sprite_shake_peak(crit, 40), camera.sprite_shake_peak(normal, 40)
        )
        for shake in (normal, crit):
            times = [i / 50 for i in range(50)]
            offsets = [camera.sprite_shake_offset(shake, t, 40) for t in times]
            self.assertEqual(offsets, [camera.sprite_shake_offset(shake, t, 40) for t in times])
            peak = camera.sprite_shake_peak(shake, 40)
            self.assertTrue(all(abs(dx) <= peak and abs(dy) <= peak for dx, dy in offsets))
            self.assertTrue(any(o != (0, 0) for o in offsets))
            self.assertEqual(camera.sprite_shake_offset(shake, 1.0, 40), (0, 0))
            # Its own draws from the hit's sequence, not the map's offset again.
            self.assertNotEqual(offsets, [camera.shake_offset(shake, t, 40) for t in times])


def archer_arena():
    """An archer at (10, 10) on open floor with nothing else on the level;
    crits off, so damage is predictable."""
    import random

    random.seed(5)
    state = GameState(WIDTH, HEIGHT, char_class='archer')
    for y in range(1, HEIGHT - 1):
        for x in range(1, WIDTH - 1):
            state.game_map[y][x] = FLOOR
    state.player.x, state.player.y = 10, 10
    state.entities = [state.player]
    state.update_fov()
    return state


def add_goblin(state, x, y, hp=1000):
    goblin = Monster(x, y, 'goblin')
    goblin.hp = goblin.max_hp = hp
    state.entities.append(goblin)
    state.update_fov()
    return goblin


class ArrowFlightTest(unittest.TestCase):
    """Every arrow is staged as Flight beats along its path (from
    GameState.shots), each hit's Impact right after the Flight that reaches it."""

    def setUp(self):
        patcher = mock.patch('game.state.BASE_CRIT_CHANCE', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state = archer_arena()
        self.director = Director()
        self.director.plan(self.state)

    def shoot(self, dx=1, dy=0):
        self.assertTrue(self.state.shoot_arrow(dx, dy))
        return self.director.plan(self.state)

    def test_a_shot_flies_to_its_target_then_the_impact_plays(self):
        goblin = add_goblin(self.state, 14, 10)
        beats = self.shoot()
        self.assertEqual([type(b) for b in beats], [Flight, Impact])
        self.assertEqual(beats[0].path, ((10, 10), (11, 10), (12, 10), (13, 10), (14, 10)))
        self.assertEqual(beats[0].path[-1], (beats[1].hit.x, beats[1].hit.y))
        self.assertIs(beats[1].hit.defender, goblin)
        self.assertEqual(self.director.plan(self.state), [])  # staged once

    def test_a_pierce_shots_second_impact_follows_the_second_flight(self):
        Item(0, 0, 'longbow', 'common').apply(self.state.player, self.state.log)
        first, second = add_goblin(self.state, 12, 10), add_goblin(self.state, 14, 10)
        beats = self.shoot()
        self.assertEqual([type(b) for b in beats], [Flight, Impact, Flight, Impact])
        self.assertEqual(beats[0].path[-1], (12, 10))
        self.assertIs(beats[1].hit.defender, first)
        # The arrow flies on from the first goblin to the second.
        self.assertEqual(beats[2].path, ((12, 10), (13, 10), (14, 10)))
        self.assertIs(beats[3].hit.defender, second)

    def test_a_miss_flies_to_the_landing_tile_with_no_impact(self):
        self.state.game_map[10][14] = WALL
        beats = self.shoot()
        self.assertEqual([type(b) for b in beats], [Flight])
        self.assertEqual(beats[0].path[-1], (13, 10))
        self.assertIsNotNone(self.state.arrows_at(13, 10))  # the pile tile

    def test_each_volley_arrow_gets_its_own_flight_and_impact(self):
        Item(0, 0, 'volley_bow', 'common').apply(self.state.player, self.state.log)
        add_goblin(self.state, 13, 10)
        add_goblin(self.state, 13, 9)
        add_goblin(self.state, 13, 11)
        beats = self.shoot()
        flights = [b for b in beats if isinstance(b, Flight)]
        self.assertEqual(len(flights), len(self.state.shots))
        for i, beat in enumerate(beats):
            if isinstance(beat, Impact):
                before = beats[i - 1]
                self.assertIsInstance(before, Flight)
                self.assertEqual(before.path[-1], (beat.hit.x, beat.hit.y))
        # A side arrow goes from the player straight to its diagonal first tile.
        side = flights[1].path
        self.assertEqual(side[0], (10, 10))
        self.assertEqual(abs(side[1][0] - 10) + abs(side[1][1] - 10), 2)

    def test_a_flight_stops_where_the_arrow_leaves_sight(self):
        beats = self.shoot()  # down an open row longer than the FOV radius
        path = beats[0].path
        self.assertTrue(all(self.state.visible[y][x] for x, y in path))
        x, y = path[-1]
        self.assertFalse(self.state.visible[y][x + 1])

    def test_flight_timing_and_position(self):
        flight = Flight(((0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0)))
        self.assertEqual(camera.flight_ms(flight), 5 * camera.FLIGHT_MS_PER_CELL)
        self.assertTrue(35 <= camera.FLIGHT_MS_PER_CELL <= 45)
        self.assertEqual(camera.flight_step(flight.path, 0), ((0, 0), (1, 0), 0))
        self.assertEqual(camera.flight_step(flight.path, 0.5), ((2, 0), (3, 0), 0.5))
        self.assertEqual(camera.flight_step(flight.path, 1), ((4, 0), (5, 0), 1))


if __name__ == '__main__':
    unittest.main()
