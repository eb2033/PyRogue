"""Sound events recorded by game logic (game/sound.py). No audio is played."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import sound
from game.item import Chest, Item
from game.monster import Monster
from game.sound import SoundEvent
from game.state import GameState
from game.tiles import DOOR, FLOOR, STAIRS_DOWN


def slots(state):
    return [e.slot for e in state.events_of(SoundEvent)]


def arena(char_class='warrior'):
    """An open arena, player at (10, 10), no other entities."""
    state = GameState(50, 20, char_class=char_class, seed=5)
    for y in range(1, 19):
        for x in range(1, 49):
            state.game_map[y][x] = FLOOR
    p = state.player
    p.x, p.y = 10, 10
    p.hp = p.max_hp = 1000
    state.entities = [p]
    state.update_fov()
    return state


def equip(state, kind, rarity='common'):
    Item(0, 0, kind, rarity).apply(state.player, state.log)


def add_monster(state, x, y, kind='goblin', hp=1000):
    m = Monster(x, y, kind)
    m.hp = m.max_hp = hp
    state.entities.append(m)
    state.update_fov()
    return m


class SoundEventTests(unittest.TestCase):
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
        boss = Monster(0, 0, 'orc', depth=8, is_boss=True)
        self.assertEqual(sound.monster_attack_slot(boss), 'monster_attack_orc')

    def test_movement_sounds(self):
        state = arena()
        state.handle_action('move_e')
        self.assertEqual(slots(state), ['footsteps'])
        # bumping a wall is silent
        state = arena()
        state.player.x = 1
        state.handle_action('move_w')
        self.assertEqual(slots(state), [])
        # stepping into a doorway plays the door
        state = arena()
        state.game_map[10][11] = DOOR
        state.handle_action('move_e')
        self.assertEqual(slots(state), ['footsteps', 'door'])

    def test_bump_attack_plays_the_weapon_sound(self):
        for kind, slot in (('dagger', 'attack_light'), ('war_axe', 'attack_heavy')):
            with self.subTest(kind=kind):
                state = arena()
                equip(state, kind)
                add_monster(state, 11, 10)
                state.handle_action('move_e')
                self.assertEqual(slots(state)[0], slot)
                self.assertNotIn('footsteps', slots(state))

    def test_great_sword_cleave_is_one_sound_and_rapier_plays_once_per_strike(self):
        state = arena()
        equip(state, 'great_sword')
        add_monster(state, 11, 10)
        add_monster(state, 10, 11)
        state.handle_action('move_e')
        state.resolve_player_phase()
        self.assertEqual(slots(state).count('attack_heavy'), 1)
        state = arena()
        equip(state, 'rapier')
        add_monster(state, 11, 10)
        state.handle_action('move_e')
        state.resolve_player_phase()
        self.assertEqual(slots(state).count('attack_light'), 2)

    def test_archer_shot_plays_bow_and_crossbow(self):
        state = arena('archer')
        equip(state, 'longbow')
        state.handle_action('shoot_e')
        self.assertEqual(slots(state), ['attack_bow'])
        state = arena('archer')
        equip(state, 'heavy_crossbow')
        state.handle_action('shoot_e')
        self.assertEqual(slots(state), ['attack_crossbow'])

    def test_refused_shot_is_silent(self):
        state = arena('archer')
        state.player.quiver = 0
        state.handle_action('shoot_e')
        self.assertEqual(slots(state), [])

    def test_chest_open_and_descend_play(self):
        state = arena()
        state.entities.append(Chest(11, 10, kind='potion'))
        state.player.hp = 1
        state.handle_action('move_e')
        self.assertEqual(slots(state)[:2], ['footsteps', 'chest_open'])
        state = arena()
        state.game_map[10][10] = STAIRS_DOWN
        state.handle_action('descend')
        self.assertIn('descend', slots(state))

    def test_monster_attack_slots(self):
        for kind, expected in (('goblin', 'monster_attack_goblin'), ('orc', 'monster_attack_orc')):
            state = arena()
            add_monster(state, 11, 10, kind)
            state.events = []
            state.end_turn()
            self.assertIn(expected, slots(state), kind)
        # a goblin archer's shot uses attack_bow
        state = arena()
        add_monster(state, 14, 10, 'goblin_archer')
        state.end_turn()
        self.assertIn('attack_bow', slots(state))

    def test_two_monsters_noticing_alert_once_and_a_chaser_does_not_alert(self):
        state = arena()
        add_monster(state, 14, 10)
        add_monster(state, 14, 12)
        state.end_turn()
        self.assertEqual(slots(state).count('enemy_alert'), 1)
        state = arena()
        m = add_monster(state, 14, 10)
        m.chasing = True
        state.end_turn()
        self.assertNotIn('enemy_alert', slots(state))

    def test_sound_events_cleared_when_the_player_acts(self):
        state = arena()
        state.handle_action('move_e')
        first = state.events_of(SoundEvent)[0].serial
        state.handle_action('move_e')
        self.assertEqual(slots(state), ['footsteps'])
        self.assertGreater(state.events_of(SoundEvent)[0].serial, first)

    def test_serials_only_grow_across_levels(self):
        state = arena()
        state.game_map[10][10] = STAIRS_DOWN
        state.handle_action('descend')
        last = state.events_of(SoundEvent)[-1].serial
        state.handle_action('wait')
        state.player.x, state.player.y = state.rooms[0].center()
        state.handle_action('move_e')
        for e in state.events_of(SoundEvent):
            self.assertGreater(e.serial, last)

    def test_sounds_and_hits_share_one_ordered_stream(self):
        # One serial counter for every record: the swing's sound comes
        # before its Hit, and the stream is in serial order.
        state = arena()
        add_monster(state, 11, 10)
        state.handle_action('move_e')
        swing = state.events_of(SoundEvent)[0]
        hit = state.hits()[0]
        self.assertLess(swing.serial, hit.serial)
        serials = [e.serial for e in state.events]
        self.assertEqual(serials, sorted(serials))
        self.assertEqual(len(set(serials)), len(serials))

    def test_hop_emits_one_footsteps(self):
        state = arena('archer')
        state.handle_action('ability')
        state.handle_action('move_e')
        self.assertEqual(slots(state), ['footsteps'])


if __name__ == '__main__':
    unittest.main()
