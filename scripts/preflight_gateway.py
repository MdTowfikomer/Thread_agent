"""
Standalone deployment preflight validation script for Thread Discord Gateway Worker.
"""
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.channels.run_gateway import run_preflight

if __name__ == "__main__":
    sys.exit(run_preflight())
