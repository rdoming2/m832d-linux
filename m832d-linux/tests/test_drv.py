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
            subprocess.run(["cupstestppd", "-q", "-I", "filters", "-W", "sizes",
                             str(ppd)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
