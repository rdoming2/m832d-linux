"""Test package setup."""
from pathlib import Path
import sys


SOURCE = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SOURCE))
