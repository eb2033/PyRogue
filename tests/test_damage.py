import random
import unittest

from game import damage
from game.damage import mitigate, plain_round, reduction, round_damage


class FakeRng:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


class MitigateTests(unittest.TestCase):
    def test_k_constant(self):
        self.assertEqual(damage.DEFENSE_K, 10)

    def test_zero_defense(self):
        self.assertEqual(mitigate(8, 0), 8.0)

    def test_defense_equal_k_halves(self):
        self.assertEqual(mitigate(8, 10), 4.0)

    def test_defense_six(self):
        self.assertAlmostEqual(mitigate(8, 6), 5.0)

    def test_floor_of_one(self):
        self.assertEqual(mitigate(1.2, 10 ** 6), 1.0)

    def test_negative_defense_no_reduction(self):
        self.assertEqual(mitigate(8, -5), 8)
        self.assertEqual(reduction(-5), 0.0)

    def test_reduction_zero(self):
        self.assertEqual(reduction(0), 0.0)
        self.assertEqual(reduction(defense=0, k=0), 0.0)

    def test_explicit_k(self):
        self.assertEqual(mitigate(8, 10, k=10), 4.0)
        self.assertAlmostEqual(mitigate(8, 10, k=20), 16 / 3)

    def test_returns_float(self):
        self.assertIsInstance(mitigate(8, 0), float)


class RoundingTests(unittest.TestCase):
    def test_fake_rng_threshold(self):
        self.assertEqual(round_damage(6.7, FakeRng(0.69)), 7)
        self.assertEqual(round_damage(6.7, FakeRng(0.71)), 6)

    def test_mean_preserved(self):
        rng = random.Random(0)
        n = 20000
        mean = sum(round_damage(6.7, rng) for _ in range(n)) / n
        self.assertAlmostEqual(mean, 6.7, delta=0.05)

    def test_exact_integer(self):
        rng = random.Random(1)
        for _ in range(200):
            self.assertEqual(round_damage(5.0, rng), 5)
        self.assertEqual(round_damage(5.0, FakeRng(0.0)), 5)

    def test_plain_round(self):
        self.assertEqual(plain_round(6.7), 7)
        self.assertIsInstance(plain_round(6.7), int)


if __name__ == "__main__":
    unittest.main()
