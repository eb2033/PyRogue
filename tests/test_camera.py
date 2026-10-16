"""The combat camera's geometry and staging (render/camera.py). Pure logic, no
pygame -- runs in the nothing-installed CI job too."""

import unittest
from unittest import mock

from game.item import Item
from game.monster import Monster
from game.state import GameState
from game.tiles import FLOOR, WALL
from render import camera
from render.camera import Director, Flight, Impact, Pan, Swing, View

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
        self.assertEqual(beats, [Pan(camera.full_view(state.width, state.height), target)])
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
        self.assertEqual([type(b) for b in beats], [Swing, Impact, Pan])
        self.assertTrue(beats[1].hit.killed)
        self.assertEqual(beats[2].end, camera.full_view(state.width, state.height))  # fight over
        self.assertIsNone(director.view)

    def test_each_hit_is_staged_once(self):
        state, goblin = lone_fight()
        director = Director()
        director.plan(state)
        state.attack(goblin, state.player)
        self.assertEqual([type(b) for b in director.plan(state)], [Swing, Impact])
        self.assertEqual(director.plan(state), [])  # the same round, redrawn

    def test_archer_does_not_zoom(self):
        state, goblin = lone_fight('archer')
        state.attack(goblin, state.player)
        beats = Director().plan(state)
        self.assertEqual([type(b) for b in beats], [Swing, Impact])  # hit shown, no zoom

    def test_zoom_can_be_switched_off(self):
        state, _ = lone_fight()
        self.assertEqual(Director(zoom=False).plan(state), [])

    def test_death_pulls_the_camera_back_out(self):
        state, _ = lone_fight()
        director = Director()
        director.plan(state)
        state.game_over = True
        self.assertEqual(director.plan(state)[-1].end, camera.full_view(state.width, state.height))

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
            beats,
            [
                Pan(
                    camera.full_view(state.width, state.height),
                    camera.combat_view(state.player, m),
                )
            ],
        )
        self.assertIs(director.focus, m)
        # fight over (monster dies): zoom back out
        m.alive = False
        self.assertEqual(director.plan(state)[-1].end, camera.full_view(state.width, state.height))

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
            [
                Pan(
                    camera.full_view(state.width, state.height),
                    camera.combat_view(state.player, goblin),
                )
            ],
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
        self.assertEqual(beats[-1].end, camera.full_view(state.width, state.height))

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
        beats = [b for b in director.plan(state) if not isinstance(b, Swing)]
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
    # A plain single-target weapon, not the archer's starting longbow.
    state.player.weapon = Item(0, 0, 'weapon', 'common')
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
        path = ((10, 10), (11, 10), (12, 10), (13, 10), (14, 10))
        self.assertEqual(beats[0], Flight((path,), 4))  # one arrow: a one-path flight
        self.assertEqual(path[-1], (beats[1].hit.x, beats[1].hit.y))
        self.assertEqual(beats[1].held, ())  # nothing else in the air
        self.assertIs(beats[1].hit.defender, goblin)
        self.assertEqual(self.director.plan(self.state), [])  # staged once

    def test_a_pierce_shots_second_impact_follows_the_second_flight(self):
        Item(0, 0, 'longbow', 'common').apply(self.state.player, self.state.log)
        first, second = add_goblin(self.state, 12, 10), add_goblin(self.state, 14, 10)
        beats = self.shoot()
        self.assertEqual([type(b) for b in beats], [Flight, Impact, Flight, Impact])
        self.assertEqual(beats[0].paths[0][-1], (12, 10))
        self.assertIs(beats[1].hit.defender, first)
        # The arrow hangs at the first goblin while it is struck...
        self.assertEqual(beats[1].held, (((11, 10), (12, 10)),))
        # ... then flies on from the first goblin to the second.
        self.assertEqual(beats[2], Flight((((12, 10), (13, 10), (14, 10)),), 2))
        self.assertIs(beats[3].hit.defender, second)

    def test_a_miss_flies_to_the_landing_tile_with_no_impact(self):
        self.state.game_map[10][14] = WALL
        beats = self.shoot()
        self.assertEqual([type(b) for b in beats], [Flight])
        self.assertEqual(beats[0].paths[0][-1], (13, 10))
        self.assertIsNotNone(self.state.arrows_at(13, 10))  # the pile tile

    def test_a_volley_is_one_shot_whose_arrows_all_leave_the_player(self):
        Item(0, 0, 'volley_bow', 'common').apply(self.state.player, self.state.log)
        add_goblin(self.state, 13, 10)
        add_goblin(self.state, 13, 9)
        add_goblin(self.state, 13, 11)
        beats = self.shoot()
        # One shot record carrying all three arrows, each from the player's cell.
        self.assertEqual(len(self.state.shots), 1)
        shot = self.state.shots[0]
        self.assertEqual(len(shot.arrows), 3)
        self.assertEqual({arrow.path[0] for arrow in shot.arrows}, {(10, 10)})
        # The aim arrow is the shot's own path: flown first, its Impact after it.
        self.assertEqual((shot.path, shot.hits), shot.arrows[0])
        self.assertIsInstance(beats[0], Flight)
        self.assertEqual(beats[0].paths, tuple(arrow.path for arrow in shot.arrows))
        self.assertIsInstance(beats[1], Impact)
        self.assertEqual(beats[0].paths[0][-1], (beats[1].hit.x, beats[1].hit.y))
        # Every arrow's hit is staged once.
        hits = [hit.serial for arrow in shot.arrows for hit in arrow.hits]
        impacts = [b.hit.serial for b in beats if isinstance(b, Impact)]
        self.assertEqual(sorted(impacts), sorted(hits))
        self.assertEqual(len(hits), 3)

    def test_a_flight_stops_where_the_arrow_leaves_sight(self):
        beats = self.shoot()  # down an open row longer than the FOV radius
        (path,) = beats[0].paths
        self.assertTrue(all(self.state.visible[y][x] for x, y in path))
        x, y = path[-1]
        self.assertFalse(self.state.visible[y][x + 1])

    def test_flight_timing_and_position(self):
        path = ((0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0))
        flight = Flight((path,), 5)
        self.assertEqual(camera.flight_ms(flight), 5 * camera.FLIGHT_MS_PER_CELL)
        self.assertTrue(35 <= camera.FLIGHT_MS_PER_CELL <= 45)
        self.assertEqual(camera.flight_step(path, 5, 0), ((0, 0), (1, 0), 0))
        self.assertEqual(camera.flight_step(path, 5, 0.5), ((2, 0), (3, 0), 0.5))
        self.assertEqual(camera.flight_step(path, 5, 1), ((4, 0), (5, 0), 1))

    def test_a_shorter_path_in_a_flight_keeps_pace_then_is_gone(self):
        short = ((0, 0), (1, 0), (2, 0))
        # Same pace as a 4-step arrow: one cell per quarter of the flight.
        self.assertEqual(camera.flight_step(short, 4, 0.25), ((1, 0), (2, 0), 0))
        self.assertEqual(camera.flight_step(short, 4, 0.375), ((1, 0), (2, 0), 0.5))
        self.assertIsNone(camera.flight_step(short, 4, 0.5))  # landed
        self.assertIsNone(camera.flight_step(((0, 0),), 1, 0))

    def volley(self):
        Item(0, 0, 'volley_bow', 'common').apply(self.state.player, self.state.log)
        return self.state.shots

    def test_a_volley_flies_all_its_arrows_at_once_from_the_player(self):
        self.volley()
        add_goblin(self.state, 13, 9)  # a side arrow's goblin, 3 steps out
        add_goblin(self.state, 15, 10)  # the aim arrow's, 5 steps out
        beats = self.shoot()
        shot = self.state.shots[0]
        self.assertEqual(len(shot.arrows), 3)
        flights = [b for b in beats if isinstance(b, Flight)]
        # The first flight carries every arrow, each from the player's cell.
        self.assertEqual(len(flights[0].paths), 3)
        self.assertEqual({p[0] for p in flights[0].paths}, {(10, 10)})
        # Nothing plays before it: all three arrows leave on the same beat.
        self.assertIs(beats[0], flights[0])
        # The flights tile one shared timeline, a cell a step for every arrow,
        # up to where the last one seen lands or leaves sight.
        seen = [Director._in_sight(self.state, a.path) for a in shot.arrows]
        self.assertEqual(sum(f.steps for f in flights), max(len(p) - 1 for p in seen))
        self.assertEqual(flights[0].steps, 3)  # cut where the side arrow lands its hit

    def test_each_volley_arrows_impact_follows_its_own_flight(self):
        self.volley()
        near = add_goblin(self.state, 12, 9)  # side lane: 2 steps
        far = add_goblin(self.state, 14, 10)  # aim line: 4 steps
        beats = self.shoot()
        kinds = [type(b) for b in beats]
        impacts = {b.hit.defender: i for i, b in enumerate(beats) if isinstance(b, Impact)}
        self.assertLess(impacts[near], impacts[far])
        # Flown time up to each impact equals that arrow's steps to its goblin.
        for monster, steps in ((near, 2), (far, 4)):
            flown = sum(b.steps for b in beats[: impacts[monster]] if isinstance(b, Flight))
            self.assertEqual(flown, steps, monster)
        # The flight right before each impact ends with an arrow on its goblin.
        for i in impacts.values():
            self.assertIs(kinds[i - 1], Flight)
            ends = {p[-1] for p in beats[i - 1].paths}
            hit = beats[i].hit
            self.assertIn((hit.x, hit.y), ends)
        # The aim arrow is still in the air while the near goblin is struck.
        aim = self.state.shots[0].arrows[0].path
        self.assertIn((aim[1], aim[2]), beats[impacts[near]].held)

    def test_the_goblin_archers_shot_is_a_one_arrow_flight_then_impact(self):
        from game.combat import Arrow, Shot

        state = self.state
        goblin = add_goblin(state, 14, 10)
        state.player.hp = 1000
        with mock.patch.object(state, '_dodged', return_value=False):
            state._monster_shot(goblin)
        shot = state.shots[-1]
        self.assertEqual(len(shot.arrows), 1)
        self.assertIsInstance(shot, Shot)
        self.assertIsInstance(shot.arrows[0], Arrow)
        beats = self.director.plan(state)
        flights = [b for b in beats if isinstance(b, Flight)]
        self.assertEqual(flights[0].paths[0][0], (14, 10))  # from the goblin
        self.assertEqual([type(b) for b in beats[:2]], [Flight, Impact])
        self.assertEqual(flights[0].paths[0][-1], (10, 10))
        self.assertIs(beats[1].hit.defender, state.player)


def open_floor(width, height):
    """A level whose map is `width` x `height` of open floor inside a wall
    border, with only the player on it, standing in the middle."""
    state = GameState(WIDTH, HEIGHT)
    state.width, state.height = width, height
    state.game_map = [
        [WALL if x in (0, width - 1) or y in (0, height - 1) else FLOOR for x in range(width)]
        for y in range(height)
    ]
    state.visible = [[False] * width for _ in range(height)]
    state.seen = [[False] * width for _ in range(height)]
    state.entities = [state.player]
    state.player.x, state.player.y = width // 2, height // 2
    state.update_fov()
    return state


class FollowViewTest(unittest.TestCase):
    """Exploring, the view is a fixed number of cells (VIEW_ZOOM) following
    the player over maps bigger than it, clamped to the map's edges."""

    SIZE = camera.view_size(WIDTH, HEIGHT)

    def test_view_size_is_the_base_map_over_the_zoom(self):
        self.assertEqual(camera.VIEW_ZOOM, 1.25)
        self.assertEqual(camera.view_size(40, 20), (32, 16))
        self.assertEqual(camera.view_size(50, 20), (40, 16))

    def test_the_view_centres_the_player_and_clamps_to_the_map(self):
        def at(x, y):
            return camera.follow_view(Monster(x, y, 'goblin'), 100, 50, (32, 16))

        self.assertEqual(at(50, 25), View(34, 17, 32, 16))  # player at its centre
        self.assertEqual(at(1, 1), View(0, 0, 32, 16))
        self.assertEqual(at(98, 48), View(68, 34, 32, 16))

    def test_a_map_that_fits_is_shown_whole_and_centred(self):
        for x, y in ((1, 1), (10, 5), (18, 8)):
            view = camera.follow_view(Monster(x, y, 'goblin'), 20, 10, (32, 16))
            self.assertEqual(view, View(-6, -3, 32, 16))

    def test_the_view_pans_to_follow_the_player_on_a_big_map(self):
        state = open_floor(100, 50)
        director = Director(view_size=self.SIZE)
        self.assertEqual(director.plan(state), [])
        first = director.current(state)
        state.player.x += 1
        state.turn += 1
        beats = director.plan(state)
        self.assertEqual(len(beats), 1)
        pan = beats[0]
        self.assertIsInstance(pan, Pan)
        self.assertTrue(pan.follow)
        self.assertEqual((pan.start, pan.end.left - pan.start.left), (first, 1))
        view = director.current(state)
        self.assertEqual(view, pan.end)
        self.assertTrue(view.left <= state.player.x < view.left + view.width)
        self.assertTrue(view.top <= state.player.y < view.top + view.height)

    def test_no_pan_on_a_map_that_fits(self):
        state = open_floor(20, 10)
        director = Director(view_size=self.SIZE)
        director.plan(state)
        for dx in (1, 1, -1, -1, -1):
            state.player.x += dx
            state.turn += 1
            self.assertEqual(director.plan(state), [])
        self.assertEqual(director.current(state), View(-6, -3, 32, 16))

    def test_combat_zoom_runs_on_top_of_the_follow_view(self):
        state = open_floor(100, 50)
        director = Director(view_size=self.SIZE)
        director.plan(state)
        explore = director.current(state)
        goblin = Monster(state.player.x + 1, state.player.y, 'goblin')
        state.entities.append(goblin)
        state.update_fov()
        beats = director.plan(state)
        self.assertEqual(beats, [Pan(explore, camera.combat_view(state.player, goblin))])
        self.assertFalse(beats[0].follow)
        # The fight ends: back out to the exploring view, not the whole map.
        goblin.alive = False
        state.entities.remove(goblin)
        state.update_fov()
        beats = director.plan(state)
        self.assertEqual(beats[-1].end, director.explore_view(state))
        self.assertEqual(beats[-1].end.width, self.SIZE[0])
        self.assertIsNone(director.view)

    def test_a_new_floor_does_not_pan_from_the_old_one(self):
        state = GameState(WIDTH, HEIGHT)
        director = Director(view_size=self.SIZE)
        director.plan(state)
        state.next_level()
        self.assertEqual(director.plan(state), [])
        view = director.current(state)
        self.assertEqual((view.width, view.height), self.SIZE)
        self.assertTrue(view.left <= state.player.x < view.left + view.width)


def warrior_arena(kind='weapon'):
    """A warrior at (10, 10) on open floor holding a common `kind`, alone on
    the level."""
    state = GameState(WIDTH, HEIGHT, char_class='warrior')
    for y in range(1, HEIGHT - 1):
        for x in range(1, WIDTH - 1):
            state.game_map[y][x] = FLOOR
    state.player.x, state.player.y = 10, 10
    state.player.weapon = Item(0, 0, kind, 'common')
    state.entities = [state.player]
    state.update_fov()
    return state


class SwingTest(unittest.TestCase):
    """Every melee blow is staged as a Swing right before its Impact, shaped
    by the attacker's weapon; arrows and dodges get none."""

    def setUp(self):
        patcher = mock.patch('game.state.BASE_CRIT_CHANCE', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def blow(self, kind, at=(11, 10)):
        """The beats staged for the player's blow with `kind` on a goblin at `at`."""
        state = warrior_arena(kind)
        goblin = add_goblin(state, *at)
        director = Director()
        director.plan(state)
        state.attack(state.player, goblin)
        return director.plan(state)

    @staticmethod
    def swings(beats):
        return [b for b in beats if isinstance(b, Swing)]

    @staticmethod
    def extent(swing, steps=40):
        """(furthest along, widest across) the arc gets from the attacker's
        cell centre over the whole beat, for a blow pointing east."""
        cx, cy = swing.origin[0] + 0.5, swing.origin[1] + 0.5
        pts = [p for i in range(steps) for p in camera.swing_points(swing, i / steps)]
        return max(x - cx for x, _, _ in pts), max(abs(y - cy) for _, y, _ in pts)

    def test_each_weapon_kind_gets_its_swing(self):
        expected = {
            'weapon': ('standard', 120),
            'sword_shield': ('standard', 120),
            'dagger': ('short', 90),
            'rapier': ('skinny', 80),
            'great_sword': ('wide', 150),
            'war_axe': ('wide', 150),
            'spear': ('long', 200),
        }
        for kind, (name, ms) in expected.items():
            with self.subTest(kind=kind):
                (swing,) = self.swings(self.blow(kind))
                self.assertEqual((swing.shape.name, swing.shape.ms), (name, ms))
                self.assertEqual((swing.origin, swing.target), ((10, 10), (11, 10)))

    def test_the_spear_swings_across_two_tiles(self):
        (swing,) = self.swings(self.blow('spear', at=(12, 10)))
        self.assertEqual((swing.origin, swing.target), ((10, 10), (12, 10)))
        along, _ = self.extent(swing)
        self.assertTrue(1.5 < along < 2.0, along)  # past the cell between, into the target's

    def test_shapes_differ_in_length_and_width(self):
        kinds = ('weapon', 'dagger', 'rapier', 'great_sword', 'spear')
        shapes = {kind: self.swings(self.blow(kind))[0] for kind in kinds}
        along = {k: self.extent(s)[0] for k, s in shapes.items()}
        across = {k: self.extent(s)[1] for k, s in shapes.items()}
        self.assertLess(along['dagger'], along['weapon'])  # shorter
        self.assertGreater(across['great_sword'], across['weapon'])  # wider
        self.assertGreater(across['weapon'], across['rapier'])  # skinny
        self.assertLess(shapes['rapier'].shape.thickness, shapes['weapon'].shape.thickness)
        self.assertGreater(along['spear'], 1.5 * along['weapon'])  # long

    def test_the_rapier_strikes_get_two_skinny_swings_one_after_the_other(self):
        state = warrior_arena('rapier')
        goblin = add_goblin(state, 11, 10)
        director = Director()
        director.plan(state)
        state.melee(goblin)  # the first strike; the second is owed
        first = director.plan(state)
        self.assertTrue(state.strike_pending())
        self.assertTrue(state.step_strike())
        second = director.plan(state)
        for beats in (first, second):
            self.assertEqual([type(b) for b in beats[:2]], [Swing, Impact])
            self.assertEqual(beats[0].shape.name, 'skinny')
            self.assertIs(beats[0].hit, beats[1].hit)
        self.assertNotEqual(first[0].hit.serial, second[0].hit.serial)
        # The second arc is traced the other way.
        self.assertFalse(first[0].mirror)
        self.assertTrue(second[0].mirror)
        lead_a = camera.swing_points(first[0], 0.1)[-1]
        lead_b = camera.swing_points(second[0], 0.1)[-1]
        self.assertLess((lead_a[1] - 10.5) * (lead_b[1] - 10.5), 0)

    def test_a_monster_blow_gets_a_standard_swing_from_its_cell(self):
        state = warrior_arena('spear')  # the player's weapon is not the monster's
        goblin = add_goblin(state, 10, 11)
        director = Director()
        director.plan(state)
        state.attack(goblin, state.player)
        swing = director.plan(state)[0]
        self.assertIsInstance(swing, Swing)
        self.assertEqual(swing.shape, camera.SWING_SHAPES['standard'])
        self.assertEqual((swing.origin, swing.target), ((10, 11), (10, 10)))
        self.assertIs(swing.hit.attacker, goblin)

    def test_a_swing_is_planned_right_before_its_impact(self):
        beats = self.blow('great_sword')
        self.assertEqual([type(b) for b in beats[:2]], [Swing, Impact])
        self.assertIs(beats[0].hit, beats[1].hit)

    def test_an_arrow_gets_no_swing(self):
        state = archer_arena()
        add_goblin(state, 11, 10)  # point blank, even
        director = Director()
        director.plan(state)
        self.assertTrue(state.shoot_arrow(1, 0))
        beats = director.plan(state)
        self.assertTrue(any(isinstance(b, Impact) for b in beats))
        self.assertEqual(self.swings(beats), [])

    def test_a_goblin_archers_arrow_gets_no_swing(self):
        state = warrior_arena()
        archer = add_goblin(state, 14, 10)
        director = Director()
        director.plan(state)
        state._monster_shot(archer)
        beats = director.plan(state)
        self.assertTrue(any(isinstance(b, Impact) for b in beats))
        self.assertEqual(self.swings(beats), [])

    def test_a_dodge_gets_no_swing(self):
        state = warrior_arena()
        goblin = add_goblin(state, 11, 10)
        director = Director()
        director.plan(state)
        with mock.patch('game.state.dodge_chance', return_value=100):
            state.attack(goblin, state.player)
        self.assertEqual(state.combat_events, [])
        self.assertEqual(self.swings(director.plan(state)), [])

    def test_the_arc_lies_in_the_direction_of_the_blow(self):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            with self.subTest(direction=(dx, dy)):
                (swing,) = self.swings(self.blow('weapon', at=(10 + dx, 10 + dy)))
                cx, cy = 10.5, 10.5
                pts = [p for i in range(20) for p in camera.swing_points(swing, i / 20)]
                self.assertTrue(pts)
                for x, y, _ in pts:
                    self.assertGreater((x - cx) * dx + (y - cy) * dy, 0)
                # Mid-swing the leading edge is out in front, over the target.
                x, y, alpha = camera.swing_points(swing, 0.5)[-1]
                self.assertAlmostEqual((x - cx) * dx + (y - cy) * dy, swing.shape.forward, 1)
                self.assertGreater(alpha, 0.5)

    def test_the_arc_fades_out_by_the_end(self):
        (swing,) = self.swings(self.blow('weapon'))
        self.assertEqual(camera.swing_points(swing, 1.0), [])
        late = camera.swing_points(swing, 0.97)
        self.assertTrue(all(alpha < 0.1 for _, _, alpha in late))


class ParryTest(unittest.TestCase):
    """A parried blow records no Hit but a Parry, which stages the monster's
    swing, the shield (Guard), the riposte's own swing and impact, then the
    "Parry!" text's fade (ParryText)."""

    def setUp(self):
        patcher = mock.patch('game.state.BASE_CRIT_CHANCE', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('game.state.dodge_chance', return_value=0)
        self.dodge = patcher.start()
        self.addCleanup(patcher.stop)

    def parried(self, kind='great_sword', armed=True):
        """The goblin east of the warrior swings at them; the beats staged."""
        state = warrior_arena(kind)
        goblin = add_goblin(state, 11, 10)
        director = Director()
        director.plan(state)
        state.parry_armed = armed
        hp = state.player.hp
        state._monster_melee(goblin)
        beats = [b for b in director.plan(state) if not isinstance(b, Pan)]
        return state, goblin, hp, beats

    def test_a_parried_blow_stages_swing_shield_riposte_then_the_text_fade(self):
        state, goblin, _, beats = self.parried()
        self.assertEqual(
            [type(b) for b in beats], [Swing, camera.Guard, Swing, Impact, camera.ParryText]
        )
        (parry,) = state.parries
        monster_swing, guard, riposte_swing, impact, text = beats
        # 1. The monster's standard swing, from its cell at the warrior.
        self.assertIs(monster_swing.hit, parry)
        self.assertEqual(monster_swing.shape, camera.SWING_SHAPES['standard'])
        self.assertEqual((monster_swing.origin, monster_swing.target), ((11, 10), (10, 10)))
        # 2. The shield, and the text's span opening and closing on this parry.
        self.assertIs(guard.parry, parry)
        self.assertIs(text.parry, parry)
        # 3. The riposte: the warrior's weapon's swing back, then its impact.
        self.assertIs(riposte_swing.hit.attacker, state.player)
        self.assertEqual(riposte_swing.shape.name, 'wide')  # the great sword's
        self.assertEqual((riposte_swing.origin, riposte_swing.target), ((10, 10), (11, 10)))
        self.assertIs(impact.hit, riposte_swing.hit)
        self.assertIs(impact.hit.defender, goblin)

    def test_the_parry_sorts_before_the_riposte_and_records_no_hit(self):
        state, goblin, hp, _ = self.parried()
        (parry,) = state.parries
        (riposte,) = state.combat_events  # nothing for the parried blow
        self.assertLess(parry.serial, riposte.serial)
        self.assertIs(riposte.attacker, state.player)
        self.assertEqual((parry.monster, parry.player), (goblin, state.player))
        self.assertEqual((parry.x, parry.y), (10, 10))
        self.assertEqual(state.player.hp, hp)  # no damage taken

    def test_the_parry_is_staged_once(self):
        state = warrior_arena()
        goblin = add_goblin(state, 11, 10)
        director = Director()
        director.plan(state)
        state.parry_armed = True
        state._monster_melee(goblin)
        director.plan(state)
        self.assertEqual(director.plan(state), [])  # the same round, redrawn

    def test_a_dodged_blow_shows_no_parry(self):
        self.dodge.return_value = 100
        state, _, _, beats = self.parried()
        self.assertEqual(state.parries, [])
        self.assertTrue(state.parry_armed)  # still armed for the next blow
        self.assertEqual(beats, [])

    def test_a_normal_blow_shows_its_swing_and_no_parry(self):
        state, goblin, _, beats = self.parried(armed=False)
        self.assertEqual(state.parries, [])
        self.assertEqual([type(b) for b in beats], [Swing, Impact])
        self.assertIs(beats[0].hit.attacker, goblin)
        self.assertEqual(beats[0].shape, camera.SWING_SHAPES['standard'])


if __name__ == '__main__':
    unittest.main()
