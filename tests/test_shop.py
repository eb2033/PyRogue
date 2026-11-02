"""The shop (game/shop.py): offers, prices, half boons, the shop room, buying."""

import os
import random
import sys
import unittest
from typing import cast

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game import archery, shop, shrine
from game.entity import Player
from game.item import ARCHER_WEAPONS, WARRIOR_WEAPONS, Chest, Item
from game.monster import Monster, is_boss_level
from game.rect import Rect
from game.state import GameState
from game.tiles import FLOOR, STAIRS_DOWN
from render.base import Action


def in_room(e, room):
    return room.x1 <= e.x < room.x2 and room.y1 <= e.y < room.y2


def weapons(s):
    return [o for o in s.offers if o.kind == 'weapon']


def boons(s):
    return [o for o in s.offers if o.kind == 'boon']


def floor_at(depth, seed, char_class='warrior'):
    state = GameState(50, 20, char_class=char_class, seed=seed)
    while state.depth < depth:
        state.next_level()
    return state


def shop_arena(char_class='warrior', depth=4):
    """An open floor with the player at (10, 10), a shopkeeper east of it and
    a rolled shop."""
    state = GameState(50, 20, char_class=char_class, seed=7)
    state.depth = depth
    for y in range(1, 19):
        for x in range(1, 49):
            state.game_map[y][x] = FLOOR
    p = state.player
    p.x, p.y = 10, 10
    keeper = shop.Shopkeeper(11, 10)
    state.shopkeeper = keeper
    state.shop = shop.roll_shop(depth, char_class, rng=random.Random(1))
    state.shop_open = False
    state.entities = [p, keeper]
    state.update_fov()
    return state


class RulesTests(unittest.TestCase):
    def test_shop_floors(self):
        self.assertEqual([d for d in range(1, 17) if shop.is_shop_level(d)], [4, 8, 12, 16])

    def test_prices_and_rarity_caps(self):
        self.assertEqual(shop.weapon_price(4, 'uncommon'), 120)
        self.assertEqual(shop.weapon_price(4, 'common'), 60)
        self.assertEqual(shop.weapon_price(8, 'rare'), 320)
        self.assertEqual(shop.weapon_price(12, 'rare'), 480)
        self.assertEqual(shop.boon_price(4), 53)
        self.assertEqual(shop.boon_price(8), 106)
        self.assertEqual(shop.boon_price(12), 160)
        p = Player(0, 0, '@')
        p.max_hp, p.hp = 60, 41
        self.assertEqual(shop.heal_price(p), 95)
        # rarity caps
        self.assertEqual(shop.rarity_cap(4), 'uncommon')
        self.assertEqual(shop.rarity_cap(8), 'rare')
        self.assertEqual(shop.cap_rarity('epic', 4), 'uncommon')
        self.assertEqual(shop.cap_rarity('rare', 4), 'uncommon')
        self.assertEqual(shop.cap_rarity('common', 4), 'common')
        self.assertEqual(shop.cap_rarity('epic', 8), 'rare')
        self.assertEqual(shop.cap_rarity('uncommon', 12), 'uncommon')

    def test_five_offers_in_key_order(self):
        s = shop.roll_shop(4, 'warrior', rng=random.Random(0))
        self.assertEqual([o.kind for o in s.offers], ['weapon', 'weapon', 'boon', 'boon', 'heal'])
        for o in weapons(s):
            self.assertEqual(o.price, shop.weapon_price(4, cast(str, cast(Item, o.item).rarity)))
        for o in boons(s):
            self.assertEqual(o.price, shop.boon_price(4))
        self.assertFalse(any(o.sold for o in s.offers))

    def test_weapon_rarity_is_capped_never_epic_and_rolls_normally_below_the_cap(self):
        def rarities(depth):
            out = set()
            for seed in range(300):
                s = shop.roll_shop(depth, 'warrior', rng=random.Random(seed))
                got = {cast(Item, o.item).rarity for o in weapons(s)}
                self.assertNotIn('epic', got, (depth, seed))
                out |= got
            return out

        self.assertEqual(rarities(4), {'common', 'uncommon'})
        self.assertEqual(rarities(20), {'common', 'uncommon', 'rare'})
        for depth in (8, 40):
            self.assertTrue(rarities(depth) <= {'common', 'uncommon', 'rare'}, depth)

    def test_two_different_class_weapons(self):
        for char_class, kinds in (('warrior', WARRIOR_WEAPONS), ('archer', ARCHER_WEAPONS)):
            for seed in range(100):
                s = shop.roll_shop(4, char_class, rng=random.Random(seed))
                got = [cast(Item, o.item).kind for o in weapons(s)]
                self.assertEqual(len(got), 2)
                self.assertEqual(len(set(got)), 2)
                self.assertTrue(set(got) <= set(kinds))

    def test_two_different_half_boons(self):
        for seed in range(100):
            s = shop.roll_shop(4, 'warrior', rng=random.Random(seed))
            keys = [cast(shrine.Boon, o.boon).key for o in boons(s)]
            self.assertEqual(len(set(keys)), 2)
            self.assertTrue(set(keys) <= set(shrine.HALF_BOONS))

    def test_pick_shop_room_skips_start_stairs_and_boss(self):
        rooms = [Rect(1, 1, 4, 4), Rect(10, 1, 4, 4)]
        self.assertIsNone(shop.pick_shop_room(rooms, None, random.Random(0)))
        rooms = [Rect(1 + 8 * i, 1, 4, 4) for i in range(4)]
        for seed in range(50):
            room = shop.pick_shop_room(rooms, rooms[1], random.Random(seed))
            self.assertIs(room, rooms[2])
        self.assertIsNone(shop.pick_shop_room(rooms[:3], rooms[1], random.Random(0)))


class HalfBoonTests(unittest.TestCase):
    def test_half_boon_values(self):
        h = shrine.HALF_BOONS
        self.assertEqual((h['blood_pact_half'].power, h['blood_pact_half'].max_hp), (2, 0))
        self.assertEqual((h['iron_skin_half'].defense, h['iron_skin_half'].heal), (1, 1.0))
        self.assertEqual((h['quick_hands_half'].belt, h['quick_hands_half'].heal), (1, 1.0))
        self.assertAlmostEqual(h['keen_eye_half'].crit, 0.05)
        self.assertEqual(h['keen_eye_half'].max_hp, 0)
        self.assertEqual((h['stone_heart_half'].max_hp, h['stone_heart_half'].power), (8, 0))

    def test_half_boon_text(self):
        h = shrine.HALF_BOONS
        self.assertEqual(h['blood_pact_half'].benefit, '+2 power')
        self.assertEqual(h['iron_skin_half'].benefit, '+1 defence')
        self.assertEqual(h['quick_hands_half'].benefit, '+1 belt slot')
        self.assertEqual(h['keen_eye_half'].benefit, '+5% crit')
        self.assertEqual(h['stone_heart_half'].benefit, '+8 max HP')
        b = h['blood_pact_half']
        self.assertEqual((b.name, b.short, b.cost), ('Lesser blood pact', 'Blood½', ''))

    def test_a_potion_boost_is_halved_and_half_boons_count_toward_stats(self):
        boon = shrine.Boon('x', 'X', 'X', '', '', heal=1.5)
        self.assertAlmostEqual(shrine.half_boon(boon).heal, 1.25)
        p = Player(0, 0, '@')
        p.boons = ['blood_pact', 'blood_pact_half']
        self.assertEqual(shrine.boon_total(p, 'power'), 5)
        self.assertEqual(len(shrine.held_boons(p)), 2)

    def test_shrines_never_offer_half_boons(self):
        for seed in range(200):
            for boon in shrine.roll_boons(rng=random.Random(seed)):
                self.assertIn(boon.key, shrine.BOONS)
                self.assertNotIn(boon.key, shrine.HALF_BOONS)


class ShopFloorTests(unittest.TestCase):
    def check_shop_floor(self, state):
        self.assertTrue(shop.is_shop_level(state.depth))
        keeper = state.shopkeeper
        self.assertIsNotNone(keeper)
        self.assertIsNotNone(state.shop)
        self.assertFalse(state.shop_open)
        self.assertIn(keeper, state.entities)
        room = next(r for r in state.rooms if r.center() == (keeper.x, keeper.y))
        self.assertIsNot(room, state.rooms[0])
        self.assertIsNot(room, state.rooms[-1])
        self.assertIsNot(room, state.boss_arena)
        for e in state.entities:
            if isinstance(e, (Monster, Chest, shrine.Shrine)):
                self.assertFalse(in_room(e, room), e)
        self.assertNotEqual(state.game_map[keeper.y][keeper.x], STAIRS_DOWN)
        return room

    def test_shop_floor_has_shopkeeper_in_an_empty_room_also_on_a_boss_floor(self):
        for seed in range(15):
            self.check_shop_floor(floor_at(4, seed))
        for seed in range(8):
            state = floor_at(8, seed)
            self.assertTrue(is_boss_level(8))
            self.assertTrue(any(isinstance(e, Monster) and e.is_boss for e in state.entities))
            self.check_shop_floor(state)

    def test_no_shop_off_shop_floors(self):
        state = floor_at(3, 0)
        self.assertIsNone(state.shop)
        self.assertIsNone(state.shopkeeper)
        self.assertFalse(state.shop_open)
        self.assertFalse(any(isinstance(e, shop.Shopkeeper) for e in state.entities))

    def test_descending_clears_the_shop(self):
        state = floor_at(4, 1)
        state.shop_open = True
        state.next_level()
        self.assertIsNone(state.shop)
        self.assertIsNone(state.shopkeeper)
        self.assertFalse(state.shop_open)


class ShopTradeTests(unittest.TestCase):
    def setUp(self):
        self.state = shop_arena()
        self.p = self.state.player

    def open_shop(self):
        self.state.handle_action('move_e')
        self.state.end_turn()

    def test_walking_into_shopkeeper_opens_shop_without_moving(self):
        turn = self.state.turn
        self.assertTrue(self.state.handle_action('move_e'))
        self.assertEqual((self.p.x, self.p.y), (10, 10))
        self.assertTrue(self.state.shop_open)
        self.assertIn('The shopkeeper shows you their wares.', self.state.messages)
        self.assertEqual(self.state.turn, turn + 1)
        self.assertTrue(self.state.shopkeeper.alive)

    def test_buy_weapon_equips_and_charges(self):
        self.open_shop()
        offer = self.state.shop.offers[0]
        self.p.gold = offer.price + 5
        self.assertTrue(self.state.buy(0))
        self.assertIs(self.p.weapon, offer.item)
        self.assertEqual(self.p.gold, 5)
        self.assertTrue(offer.sold)

    def test_buy_boon_adds_half_boon_and_charges(self):
        self.open_shop()
        offer = self.state.shop.offers[2]
        offer.boon = shrine.HALF_BOONS['blood_pact_half']
        power, max_hp = self.p.power, self.p.max_hp
        self.p.gold = 100
        self.assertTrue(self.state.buy(2))
        self.assertEqual(self.p.boons, ['blood_pact_half'])
        self.assertEqual(self.p.power, power + 2)
        self.assertEqual(self.p.max_hp, max_hp)
        self.assertEqual(self.p.gold, 100 - 53)
        self.assertTrue(offer.sold)
        self.assertIn('You buy the Lesser blood pact: +2 power.', self.state.messages)
        self.assertNotIn('The shrine crumbles to dust.', self.state.messages)

    def test_heal_costs_missing_hp_times_5_and_stays_available(self):
        self.open_shop()
        self.p.max_hp, self.p.hp, self.p.gold = 60, 41, 200
        self.assertTrue(self.state.buy(4))
        self.assertEqual(self.p.hp, 60)
        self.assertEqual(self.p.gold, 105)
        self.assertFalse(self.state.shop.offers[4].sold)
        self.p.hp = 50
        self.assertTrue(self.state.buy(4))
        self.assertEqual((self.p.hp, self.p.gold), (60, 55))

    def test_heal_at_full_hp_is_refused(self):
        self.open_shop()
        self.p.hp = self.p.max_hp
        self.p.gold = 100
        logged = len(self.state.messages)
        self.assertFalse(self.state.buy(4))
        self.assertEqual(self.p.gold, 100)
        self.assertGreater(len(self.state.messages), logged)

    def test_cannot_buy_what_you_cannot_afford(self):
        self.open_shop()
        offer = self.state.shop.offers[0]
        weapon = self.p.weapon
        self.p.gold = offer.price - 1
        logged = len(self.state.messages)
        self.assertFalse(self.state.buy(0))
        self.assertIs(self.p.weapon, weapon)
        self.assertEqual(self.p.gold, offer.price - 1)
        self.assertFalse(offer.sold)
        self.assertGreater(len(self.state.messages), logged)
        self.p.hp, self.p.gold = 1, 0
        self.assertFalse(self.state.buy(4))
        self.assertEqual(self.p.hp, 1)

    def test_sold_offer_cannot_be_bought_again(self):
        self.open_shop()
        self.p.gold = 1000
        self.assertTrue(self.state.buy(3))
        gold, boons = self.p.gold, list(self.p.boons)
        self.assertFalse(self.state.buy(3))
        self.assertEqual((self.p.gold, self.p.boons), (gold, boons))

    def test_shop_actions_take_no_turn(self):
        self.open_shop()
        self.p.gold = 1000
        turn, pos = self.state.turn, (self.p.x, self.p.y)
        keys = (
            Action.CHOOSE_1,
            Action.CHOOSE_2,
            Action.CHOOSE_3,
            Action.CHOOSE_4,
            Action.CHOOSE_5,
        )
        for action in keys:
            self.assertFalse(self.state.handle_action(action))
        self.assertTrue(all(o.sold for o in self.state.shop.offers[:4]))
        for action in ('move_w', 'wait', 'drink', 'ability', 'shoot_w'):
            self.assertFalse(self.state.handle_action(action))
        self.assertEqual((self.state.turn, (self.p.x, self.p.y)), (turn, pos))
        self.assertTrue(self.state.shop_open)
        self.assertFalse(self.state.handle_action('skip'))
        self.assertFalse(self.state.shop_open)
        self.assertIn('You leave the shop.', self.state.messages)
        self.assertEqual(self.state.turn, turn)

    def test_choose_4_and_5_still_do_nothing_outside_the_shop(self):
        self.p.gold = 1000
        self.assertFalse(self.state.handle_action(Action.CHOOSE_4))
        self.assertFalse(self.state.handle_action(Action.CHOOSE_5))
        self.assertEqual(self.p.gold, 1000)

    def test_leaving_and_coming_back(self):
        self.open_shop()
        self.p.gold = 1000
        self.state.handle_action('choose_1')
        self.state.handle_action('skip')
        self.state.handle_action('move_w')
        self.state.end_turn()
        self.assertFalse(self.state.shop_open)
        self.state.handle_action('move_e')
        self.state.end_turn()
        self.state.handle_action('move_e')
        self.state.end_turn()
        self.assertTrue(self.state.shop_open)
        self.assertTrue(self.state.shop.offers[0].sold)
        self.assertFalse(self.state.shop.offers[1].sold)

    def test_monsters_never_step_onto_the_shopkeeper(self):
        state = self.state
        # The player behind the shopkeeper, a goblin chasing from beyond it.
        self.p.x, self.p.y = 12, 10
        self.p.hp = self.p.max_hp = 10_000
        goblin = Monster(5, 10, 'goblin')
        state.entities.append(goblin)
        state.update_fov()
        for _ in range(50):
            state.handle_action('wait')
            state.end_turn()
            self.assertNotEqual((goblin.x, goblin.y), (11, 10))
        self.assertEqual((state.shopkeeper.x, state.shopkeeper.y), (11, 10))

    def test_hop_stops_before_the_shopkeeper(self):
        state = shop_arena('archer')
        self.assertTrue(state.hop(1, 0) is False)
        self.assertEqual((state.player.x, state.player.y), (10, 10))
        state.player.x = 9
        self.assertTrue(state.hop(1, 0))
        self.assertEqual((state.player.x, state.player.y), (10, 10))

    def test_arrows_fly_past_the_shopkeeper(self):
        state = shop_arena('archer')
        self.assertIsNone(state.monster_at(11, 10))
        goblin = Monster(13, 10, 'goblin')
        state.entities.append(goblin)
        state.update_fov()
        hp = goblin.hp
        state.shoot_arrow(1, 0)
        self.assertLess(goblin.hp, hp)


class NothingLandsOnTheShopkeeperTests(unittest.TestCase):
    def test_knockback_toward_the_shopkeeper_stops_short(self):
        state = shop_arena('archer')
        # The shopkeeper at (11, 10); a goblin two tiles east, pushed west.
        goblin = Monster(13, 10, 'goblin')
        state.entities.append(goblin)
        archery._knock_back(state, goblin, -1, 0, 3)
        self.assertEqual((goblin.x, goblin.y), (12, 10))
        archery._knock_back(state, goblin, -1, 0, 3)
        self.assertEqual((goblin.x, goblin.y), (12, 10))

    def test_sling_shot_never_knocks_onto_the_shopkeeper(self):
        state = shop_arena('archer')
        state.player.x = 15
        state.player.weapon = Item(0, 0, 'sling', 'epic')
        # The player at (15, 10) shoots west: goblin at (13, 10), shopkeeper at (11, 10).
        goblin = Monster(13, 10, 'goblin')
        goblin.hp = goblin.max_hp = 10_000
        state.entities.append(goblin)
        state.update_fov()
        for _ in range(5):
            state.shoot_arrow(-1, 0)
            self.assertNotEqual((goblin.x, goblin.y), (11, 10))
        self.assertEqual((goblin.x, goblin.y), (12, 10))

    def test_summons_never_land_on_the_shopkeeper(self):
        for seed in range(40):
            state = shop_arena(depth=8)
            # Only three floor tiles near the boss: its own, the shopkeeper's
            # and one more -- the boss calls two goblins.
            for y in range(1, 19):
                for x in range(1, 49):
                    state.game_map[y][x] = '#'
            for x in (20, 21, 22):
                state.game_map[10][x] = FLOOR
            boss = Monster(20, 10, 'orc', depth=8)
            state.entities.append(boss)
            state.shopkeeper.x, state.shopkeeper.y = 21, 10
            state.player.x, state.player.y = 30, 5
            state.rng.seed(seed)
            state._summon_goblins(boss)
            summoned = [e for e in state.entities if isinstance(e, Monster) and e is not boss]
            self.assertEqual([(m.x, m.y) for m in summoned], [(22, 10)])


if __name__ == '__main__':
    unittest.main()
