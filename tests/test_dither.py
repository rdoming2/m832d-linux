import unittest

from m832d_filter.dither import render


class DitherTests(unittest.TestCase):
    def test_threshold_uses_configured_cutoff(self):
        self.assertEqual([list(row) for row in render([[127, 128, 159, 160]],
                                                       "threshold", 160)],
                         [[1, 1, 1, 0]])

    def test_floyd_steinberg_is_serpentine_and_deterministic(self):
        rows = [[64, 128, 192, 128], [128, 128, 128, 128],
                [128, 128, 128, 128]]
        self.assertEqual([list(row) for row in render(rows, "floyd-steinberg")],
                         [[1, 0, 0, 1], [0, 1, 1, 0], [1, 0, 0, 1]])

    def test_atkinson_is_deterministic_and_propagates_two_rows(self):
        rows = [[64, 128, 192, 128], [128, 128, 128, 128],
                [128, 128, 128, 128]]
        self.assertEqual([list(row) for row in render(rows, "atkinson")],
                         [[1, 0, 0, 1], [0, 1, 1, 0], [0, 1, 0, 0]])

    def test_dither_midpoint_is_fixed(self):
        rows = [[128, 128, 128, 128]]
        expected = [[0, 1, 0, 1]]
        self.assertEqual([list(row) for row in render(rows, "floyd-steinberg", 32)],
                         expected)
        self.assertEqual([list(row) for row in render(rows, "atkinson", 224)],
                         [[0, 1, 1, 0]])

    def test_empty_and_narrow_rows(self):
        self.assertEqual(render([], "atkinson"), [])
        self.assertEqual([list(row) for row in render([[127], [128]],
                                                       "floyd-steinberg")],
                         [[1], [0]])


if __name__ == "__main__":
    unittest.main()
