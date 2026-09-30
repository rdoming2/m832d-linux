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
            self.assertIn("M832DPagePause", text)
            self.assertIn("M832DRendering", text)
            self.assertIn("*DefaultM832DRendering: Atkinson", text)
            for value, label in (("Atkinson", "Atkinson"),
                                 ("FloydSteinberg", "Floyd-Steinberg"),
                                 ("Threshold", "Binary threshold")):
                self.assertIn(f"*M832DRendering {value}/{label}", text)
            self.assertIn("*DefaultM832DPagePause: 0", text)
            for value, label in (("0", "Off"), ("5", "5 seconds"),
                                 ("10", "10 seconds"), ("20", "20 seconds"),
                                 ("30", "30 seconds")):
                self.assertIn(f"*M832DPagePause {value}/{label}", text)
            self.assertNotIn("rastertoM08F", text)
            hardware_margins = re.search(r'\*HWMargins: ([^\n]+)', text)
            self.assertIsNotNone(hardware_margins)
            self.assertEqual(hardware_margins.group(1), "0 0 0 0")
            width = re.search(r"\*ParamCustomPageSize Width: 1 points 0 ([0-9.]+)", text)
            height = re.search(r"\*ParamCustomPageSize Height: 2 points 0 ([0-9.]+)", text)
            self.assertIsNotNone(width)
            self.assertIsNotNone(height)
            maximum_width = float(width.group(1))
            self.assertAlmostEqual(maximum_width, 612.2835, places=1)
            self.assertLessEqual(2.25 * 72, maximum_width)
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
            for name in ("w53h70", "w80h106", "w110h146"):
                imageable = re.search(rf'\*ImageableArea {name}/[^:]+: "([^\"]+)"', text)
                self.assertIsNotNone(imageable)
                values = [float(value) for value in imageable.group(1).split()]
                self.assertEqual(values[0:2], [0, 0])
                self.assertGreater(values[2], 0)
                self.assertGreater(values[3], 0)
            subprocess.run(["cupstestppd", "-q", "-I", "filters", "-W", "sizes",
                             str(ppd)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
