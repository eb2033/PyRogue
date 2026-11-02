import random
import unittest

from game import damage
from game.damage import mitigate, reduction, round_damage


class FakeRng(random.Random):
    def __init__(self, value):
        super().__init__()
        self.value = value

    def random(self):
        return self.value


class MitigateTests(unittest.TestCase):
    def test_mitigation_values(self):
        self.assertEqual(damage.DEFENSE_K, 10)
        self.assertEqual(mitigate(8, 0), 8.0)
        self.assertEqual(mitigate(8, 10), 4.0)  # defence equal to k halves
        self.assertAlmostEqual(mitigate(8, 6), 5.0)
        self.assertEqual(mitigate(8, 10, k=10), 4.0)
        self.assertAlmostEqual(mitigate(8, 10, k=20), 16 / 3)
        self.assertIsInstance(mitigate(8, 0), float)

    def test_floor_and_no_reduction_edges(self):
        self.assertEqual(mitigate(1.2, 10**6), 1.0)
        self.assertEqual(mitigate(8, -5), 8)
        self.assertEqual(reduction(-5), 0.0)
        self.assertEqual(reduction(0), 0.0)
        self.assertEqual(reduction(defense=0, k=0), 0.0)


class RoundingTests(unittest.TestCase):
    def test_fake_rng_threshold_and_exact_integers(self):
        self.assertEqual(round_damage(6.7, FakeRng(0.69)), 7)
        self.assertEqual(round_damage(6.7, FakeRng(0.71)), 6)
        rng = random.Random(1)
        for _ in range(200):
            self.assertEqual(round_damage(5.0, rng), 5)
        self.assertEqual(round_damage(5.0, FakeRng(0.0)), 5)

    def test_mean_preserved(self):
        rng = random.Random(0)
        n = 20000
        mean = sum(round_damage(6.7, rng) for _ in range(n)) / n
        self.assertAlmostEqual(mean, 6.7, delta=0.05)


if __name__ == '__main__':
    unittest.main()
