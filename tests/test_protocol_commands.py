import unittest

from m832d_protocol import FOOTER, build_setup, feed


class CommandTests(unittest.TestCase):
    def test_default_setup_is_the_captured_raw_sequence(self):
        self.assertEqual(
            build_setup(),
            bytes.fromhex("1f1108 1f1137 37 aaabac02 1f1102 02 1f110b 1f1135 00"),
        )

    def test_darkness_changes_only_the_density_byte(self):
        expected = bytes.fromhex(
            "1f1108 1f1137 37 aaabac02 1f1102 04 1f110b 1f1135 00"
        )
        self.assertEqual(build_setup(4), expected)

    def test_feed_and_footer_are_fixed_protocol_commands(self):
        self.assertEqual(feed(), bytes.fromhex("1b6402"))
        self.assertEqual(FOOTER, bytes.fromhex("1b6402 1b6402"))


if __name__ == "__main__":
    unittest.main()
