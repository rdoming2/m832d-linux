import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class DriverTests(unittest.TestCase):
    def test_drv_compiles_and_ppd_names_project_filter(self):
        if not shutil.which("ppdc") or not shutil.which("cupstestppd"):
            self.skipTest("CUPS development tools are unavailable")
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            subprocess.run(["ppdc", "-d", str(output), str(root / "cups/drv/m832d.drv")],
                           check=True, capture_output=True, text=True)
            ppd = output / "Phomemo-M832D.ppd"
            self.assertTrue(ppd.exists())
            text = ppd.read_text()
            self.assertIn("rastertom832d", text)
            self.assertNotIn("rastertoM08F", text)
            width = re.search(r"\*ParamCustomPageSize Width: 1 points 0 ([0-9.]+)", text)
            height = re.search(r"\*ParamCustomPageSize Height: 2 points 0 ([0-9.]+)", text)
            self.assertIsNotNone(width)
            self.assertIsNotNone(height)
            self.assertAlmostEqual(float(width.group(1)), 612.2835, places=1)
            self.assertAlmostEqual(float(height.group(1)), 0, places=1)
            letter = re.search(r'\*ImageableArea Letter/US Letter: "([^"]+)"', text)
            a4 = re.search(r'\*ImageableArea A4/A4: "([^"]+)"', text)
            self.assertIsNotNone(letter)
            self.assertIsNotNone(a4)
            letter_values = [float(value) for value in letter.group(1).split()]
            a4_values = [float(value) for value in a4.group(1).split()]
            self.assertAlmostEqual(letter_values[0], 14.17, places=1)
            self.assertAlmostEqual(letter_values[1], 30, places=1)
            self.assertAlmostEqual(letter_values[2], 597.83, places=1)
            self.assertAlmostEqual(letter_values[3], 762, places=1)
            self.assertAlmostEqual(a4_values[0], 14.17, places=1)
            self.assertAlmostEqual(a4_values[1], 30, places=1)
            self.assertAlmostEqual(a4_values[2], 580.83, places=1)
            self.assertAlmostEqual(a4_values[3], 812, places=1)
            subprocess.run(["cupstestppd", "-q", "-I", "filters", "-W", "sizes",
                             str(ppd)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
