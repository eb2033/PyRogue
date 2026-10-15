"""Headless tests for the menu/banner UI primitives (no window needed --
these are the pure pieces the renderer draws, kept separate on purpose).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from render.banner import FONT_HEIGHT, render_banner
from render.menu import Menu


class BannerTests(unittest.TestCase):
    def test_pyrogue_banner_has_correct_shape(self):
        lines = render_banner('PyRogue')
        self.assertEqual(len(lines), FONT_HEIGHT)
        widths = {len(line) for line in lines}
        self.assertEqual(len(widths), 1, 'every row should be the same width')

    def test_banner_is_case_insensitive(self):
        self.assertEqual(render_banner('pyrogue'), render_banner('PYROGUE'))

    def test_unsupported_letter_raises(self):
        with self.assertRaises(KeyError):
            render_banner('Zebra')  # Z/B/A not in the font


class MenuTests(unittest.TestCase):
    def test_starts_at_first_option(self):
        menu = Menu(['Start', 'Quit'])
        self.assertEqual(menu.selected(), 'Start')

    def test_move_advances_and_wraps(self):
        menu = Menu(['Start', 'Quit'])
        menu.move(1)
        self.assertEqual(menu.selected(), 'Quit')
        menu.move(1)
        self.assertEqual(menu.selected(), 'Start')  # wrapped

    def test_move_backward_wraps(self):
        menu = Menu(['Start', 'Quit'])
        menu.move(-1)
        self.assertEqual(menu.selected(), 'Quit')

    def test_empty_options_rejected(self):
        with self.assertRaises(ValueError):
            Menu([])


if __name__ == '__main__':
    unittest.main()
