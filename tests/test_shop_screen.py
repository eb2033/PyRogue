"""The shop overlay: text, keys, painting (pygame; skips without it)."""

import os
import unittest

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

try:
    import pygame
except ImportError:  # pragma: no cover
    pygame = None

from game.item import Item
from game.paths import resource_path
from game.shop import heal_price, weapon_price
from game.state import GameState
from render import shop_text
from render.base import Action
from tests.test_ui import SIZES

if pygame is not None:
    from render import input_map, palette, screens
    from render.pygame_render import PygameRenderer
    from render.tileset import Tileset

WIDTH, HEIGHT = 40, 20


def key_event(char):
    return pygame.event.Event(pygame.KEYDOWN, key=ord(char), unicode=char, mod=0, scancode=0)


def make_shop_state(gold=130):
    state = GameState(WIDTH, HEIGHT, seed=5)
    state.depth = 3
    state.next_level()
    assert state.shop is not None
    state.player.gold = gold
    state.shop_open = True
    return state


class OfferTextTest(unittest.TestCase):
    def setUp(self):
        self.state = make_shop_state()
        self.player = self.state.player
        self.offers = self.state.shop.offers

    def test_constants(self):
        self.assertEqual(shop_text.TITLE, 'Shop')
        self.assertEqual(shop_text.HINT, 'press 1-5 to buy; space leaves')
        self.assertEqual(shop_text.gold_line(self.player), f'Your gold: {self.player.gold}')

    def test_weapon_and_boon_lines(self):
        weapon, boon = self.offers[0], self.offers[2]
        lines = shop_text.offer_lines(1, weapon, self.player)
        self.assertEqual(lines[0], f'[1] {weapon.item.name} ({weapon.item.rarity})')
        self.assertTrue(lines[1].endswith(f'{weapon.price} gold'))
        lines = shop_text.offer_lines(3, boon, self.player)
        self.assertEqual(lines[0], f'[3] {boon.boon.name}')
        self.assertEqual(lines[1], f'{boon.boon.benefit}   {boon.price} gold')

    def test_heal_lines_price_text_and_sold_line(self):
        heal = self.offers[4]
        self.assertEqual(shop_text.offer_lines(5, heal, self.player)[1], '(at full HP)')
        self.player.hp -= 4
        lines = shop_text.offer_lines(5, heal, self.player)
        self.assertEqual(lines, ['[5] Heal to full', f'{heal_price(self.player)} gold'])
        self.player.hp += 4
        weapon, heal = self.offers[0], self.offers[4]
        self.assertEqual(shop_text.price_text(weapon, self.player), f'{weapon.price} gold')
        lines = shop_text.offer_lines(1, weapon, self.player)
        self.assertTrue(lines[1].endswith(f'{weapon.price} gold'))
        self.assertIsNone(shop_text.price_text(heal, self.player))  # at full HP
        self.player.hp -= 3
        self.assertEqual(
            shop_text.price_text(heal, self.player), f'{heal_price(self.player)} gold'
        )
        weapon.sold = True
        self.assertIsNone(shop_text.price_text(weapon, self.player))
        self.offers[2].sold = True
        self.assertEqual(shop_text.offer_lines(3, self.offers[2], self.player)[1], 'sold')

    def test_affordable(self):
        weapon = self.offers[0]
        self.player.gold = weapon.price
        self.assertTrue(shop_text.affordable(weapon, self.player))
        self.player.gold = weapon.price - 1
        self.assertFalse(shop_text.affordable(weapon, self.player))
        weapon.sold = True
        self.player.gold = 9999
        self.assertFalse(shop_text.affordable(weapon, self.player))
        heal = self.offers[4]
        self.assertFalse(shop_text.affordable(heal, self.player))  # full HP
        self.player.hp -= 2
        self.assertTrue(shop_text.affordable(heal, self.player))
        self.player.gold = 5
        self.assertFalse(shop_text.affordable(heal, self.player))


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class ShopKeysTest(unittest.TestCase):
    def test_shop_keys_only_while_shopping(self):
        four, five = key_event('4'), key_event('5')
        self.assertIsNone(input_map.lookup(four))
        self.assertIsNone(input_map.lookup(five))
        self.assertEqual(input_map.lookup(four, shopping=True), Action.CHOOSE_4)
        self.assertEqual(input_map.lookup(five, shopping=True), Action.CHOOSE_5)
        self.assertEqual(input_map.lookup(key_event(' '), shopping=True), Action.SKIP)
        self.assertEqual(input_map.lookup(key_event('1'), shopping=True), Action.CHOOSE_1)
        self.assertEqual(input_map.lookup(key_event('w'), shopping=True), Action.MOVE_N)


@unittest.skipUnless(pygame, 'pygame-ce not installed')
class ShopPaintTest(unittest.TestCase):
    tiles = False

    def renderer_at(self, size):
        renderer = PygameRenderer(WIDTH, HEIGHT)
        renderer._set_mode(size, pygame.RESIZABLE)
        renderer._relayout()
        return renderer

    def paint(self, renderer, state):
        renderer.canvas.surface.fill((1, 2, 3))
        screens.paint_shop(renderer.canvas, state)

    def painted_rect(self, renderer):
        surface = renderer.canvas.surface
        bounds = pygame.mask.from_threshold(surface, (1, 2, 3), (1, 1, 1, 255))
        bounds.invert()
        rect = bounds.get_bounding_rects()
        return rect[0].unionall(rect[1:]) if rect else pygame.Rect(0, 0, 0, 0)

    def test_paint_shop_draws_centred_on_the_map_inside_the_window(self):
        renderer = self.renderer_at((1600, 900))
        self.addCleanup(renderer.close)
        state = make_shop_state()
        self.paint(renderer, state)
        painted = self.painted_rect(renderer)
        self.assertGreater(painted.width, 0)
        self.assertTrue(pygame.Rect(0, 0, 1600, 900).contains(painted), painted)
        self.assertLessEqual(abs(painted.centerx - renderer.layout.map_rect().centerx), 1)
        # and the gold line has space above the first offer
        window = pygame.Rect(0, 0, 1600, 900)
        placed = dict(screens.shop_line_rects(renderer.layout, state, window))
        gold = placed[shop_text.gold_line(state.player)]
        first = screens.shop_row_rects(renderer.layout, state, window)[0]
        line_h = renderer.layout.font.get_linesize()
        self.assertGreaterEqual(first.top - gold.bottom, line_h // 2 - 1)

    def test_glyph_mode_shop_text_is_never_cut(self):
        """Glyph mode's map is far smaller than the shop's text needs: the box
        grows past the map (over the boards), clamped to the window, so every
        line -- each offer's price and the hint included -- is whole."""
        for size in [(1920, 1080), (1280, 720), (700, 1300)]:
            with self.subTest(size=size):
                renderer = self.renderer_at(size)
                self.addCleanup(renderer.close)
                self.assertIsNone(renderer.layout.tile)  # glyph mode
                state = make_shop_state()
                window = pygame.Rect((0, 0), size)
                box = screens.shop_rect(renderer.layout, state, window)
                self.assertTrue(window.contains(box), box)
                placed = screens.shop_line_rects(renderer.layout, state, window)
                texts = [text for text, _ in placed]
                self.assertIn(shop_text.HINT, texts)
                for number, offer in enumerate(state.shop.offers, start=1):
                    for line in shop_text.offer_lines(number, offer, state.player):
                        self.assertIn(line, texts)
                for text, rect in placed:
                    self.assertTrue(box.contains(rect), (text, rect, box))
                    self.assertTrue(window.contains(rect), (text, rect))
                rows = screens.shop_row_rects(renderer.layout, state, window)
                at = dict(placed)
                for number, (offer, row) in enumerate(zip(state.shop.offers, rows), start=1):
                    self.assertTrue(box.contains(row), (row, box))
                    for line in shop_text.offer_lines(number, offer, state.player):
                        self.assertTrue(row.contains(at[line]), (line, at[line], row))

    def test_shop_overlay_fits_small_windows(self):
        for size in SIZES + [(320, 240)]:
            with self.subTest(size=size):
                renderer = self.renderer_at(size)
                self.addCleanup(renderer.close)
                state = make_shop_state()
                self.paint(renderer, state)  # must not raise
                window = pygame.Rect((0, 0), size)
                self.assertTrue(window.contains(screens.shop_rect(renderer.layout, state, window)))

    def ink_colours(self, renderer, rect):
        surface = renderer.canvas.surface
        return {
            tuple(surface.get_at((x, y)))[:3]
            for x in range(rect.left, rect.right)
            for y in range(rect.top, rect.bottom)
        }

    def test_tile_mode_box_still_fits_in_the_map(self):
        renderer = PygameRenderer(WIDTH, HEIGHT, tileset=Tileset(resource_path('assets')))
        self.addCleanup(renderer.close)
        renderer._set_mode((1920, 1080), pygame.RESIZABLE)
        renderer._relayout()
        self.assertIsNotNone(renderer.layout.tile)
        state = make_shop_state()
        box = screens.shop_rect(renderer.layout, state, pygame.Rect(0, 0, 1920, 1080))
        self.assertTrue(renderer.layout.map_rect().contains(box), box)
        self.assertEqual(box.center, renderer.layout.map_rect().center)

    def line_rects(self, renderer, state):
        """{text: rect} for the shop's painted lines."""
        window = pygame.Rect((0, 0), renderer.canvas.surface.get_size())
        return dict(screens.shop_line_rects(renderer.layout, state, window))

    def uncommon_shop(self, gold):
        """A shop whose first weapon is Uncommon (120 gold on floor 4), the
        second Common (60), boons 53: with `gold` between, some rows are
        unaffordable."""
        state = make_shop_state(gold=gold)
        weapon = state.shop.offers[0]
        weapon.item = Item(0, 0, weapon.item.kind, 'uncommon')
        weapon.price = weapon_price(state.depth, 'uncommon')
        return state

    def test_unaffordable_weapon_keeps_its_rarity_ink_and_inks_its_price_red(self):
        renderer = self.renderer_at((1600, 900))
        self.addCleanup(renderer.close)
        state = self.uncommon_shop(gold=55)
        weapon = state.shop.offers[0]
        self.assertFalse(shop_text.affordable(weapon, state.player))
        rarity_ink = palette.ink(weapon.item.color)
        self.assertNotEqual(rarity_ink, palette.INK)
        self.paint(renderer, state)
        at = self.line_rects(renderer, state)
        name, detail = shop_text.offer_lines(1, weapon, state.player)
        name_ink = self.ink_colours(renderer, at[name])
        self.assertIn(rarity_ink, name_ink)
        self.assertNotIn(palette.SEEN, name_ink)
        detail_ink = self.ink_colours(renderer, at[detail])
        self.assertIn(palette.INK_DANGER, detail_ink)
        self.assertNotIn(palette.SEEN, detail_ink)
        # Only the price is red: the stat text before it keeps its ink.
        price = shop_text.price_text(weapon, state.player)
        assert price is not None
        stat_w = renderer.layout.font.size(detail[: -len(price)])[0]
        stats = at[detail].copy()
        stats.width = stat_w
        self.assertNotIn(palette.INK_DANGER, self.ink_colours(renderer, stats))

    def test_unaffordable_heal_price_is_red(self):
        renderer = self.renderer_at((1600, 900))
        self.addCleanup(renderer.close)
        state = self.uncommon_shop(gold=1)
        state.player.hp -= 3  # a heal now costs more than 1 gold
        heal = state.shop.offers[4]
        self.assertFalse(shop_text.affordable(heal, state.player))
        self.paint(renderer, state)
        at = self.line_rects(renderer, state)
        name, detail = shop_text.offer_lines(5, heal, state.player)
        self.assertIn(palette.INK, self.ink_colours(renderer, at[name]))
        self.assertNotIn(palette.INK_DANGER, self.ink_colours(renderer, at[name]))
        self.assertIn(palette.INK_DANGER, self.ink_colours(renderer, at[detail]))

    def test_affordable_offer_has_no_red_price(self):
        renderer = self.renderer_at((1600, 900))
        self.addCleanup(renderer.close)
        state = self.uncommon_shop(gold=55)
        boon = state.shop.offers[2]
        self.assertTrue(shop_text.affordable(boon, state.player))
        self.paint(renderer, state)
        at = self.line_rects(renderer, state)
        name, detail = shop_text.offer_lines(3, boon, state.player)
        self.assertIn(palette.ink(boon.boon.color), self.ink_colours(renderer, at[name]))
        self.assertNotIn(palette.INK_DANGER, self.ink_colours(renderer, at[detail]))

    def test_unaffordable_rows_are_never_grey(self):
        renderer = self.renderer_at((1600, 900))
        self.addCleanup(renderer.close)
        state = make_shop_state(gold=0)
        self.paint(renderer, state)
        rows = screens.shop_row_rects(renderer.layout, state, pygame.Rect(0, 0, 1600, 900))
        self.assertEqual(len(rows), 5)
        for rect in rows:
            self.assertNotIn(palette.SEEN, self.ink_colours(renderer, rect))

    def test_sold_offer_is_greyed(self):
        renderer = self.renderer_at((1600, 900))
        self.addCleanup(renderer.close)
        state = self.uncommon_shop(gold=10_000)
        state.shop.offers[0].sold = True
        self.paint(renderer, state)
        at = self.line_rects(renderer, state)
        for line in shop_text.offer_lines(1, state.shop.offers[0], state.player):
            colours = self.ink_colours(renderer, at[line])
            self.assertIn(palette.SEEN, colours)
            self.assertNotIn(palette.INK_DANGER, colours)
        rows = screens.shop_row_rects(renderer.layout, state, pygame.Rect(0, 0, 1600, 900))
        self.assertNotIn(palette.SEEN, self.ink_colours(renderer, rows[1]))

    def test_renderer_opens_overlay_and_routes_keys(self):
        renderer = self.renderer_at((1600, 900))
        self.addCleanup(renderer.close)
        state = make_shop_state()
        renderer.draw(state)
        pygame.event.clear()
        pygame.event.post(key_event('5'))
        self.assertEqual(renderer.get_action(), Action.CHOOSE_5)
        pygame.event.post(key_event(' '))
        self.assertEqual(renderer.get_action(), Action.SKIP)
        state.shop_open = False
        renderer.draw(state)
        pygame.event.post(key_event('5'))
        self.assertIsNone(renderer.get_action())  # '5' means nothing outside the shop
        pygame.event.post(key_event('w'))
        self.assertEqual(renderer.get_action(), Action.MOVE_N)


if __name__ == '__main__':
    unittest.main()
