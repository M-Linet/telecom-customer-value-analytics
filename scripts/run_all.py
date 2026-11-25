"""Rebuild the whole project from nothing, on Windows, macOS or Linux.

    python scripts/run_all.py            # data -> database -> SQL -> notebooks -> Power BI extract + project -> tests
    python scripts/run_all.py --skip-notebooks
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = [
    ("Generate synthetic raw data", [sys.executable, "-m", "src.generate_data"]),
    ("Build PostgreSQL database", [sys.executable, "-m", "src.pipeline"]),
    ("Run SQL analysis library", [sys.executable, "-m", "src.run_sql"]),
    ("Execute notebooks", [sys.executable, "scripts/build_notebooks.py"]),
    ("Export Power BI tables + reconciliation", [sys.executable, "-m", "src.export_powerbi"]),
    ("Generate Power BI project (points at this folder's data)", [sys.executable, "scripts/build_pbip.py"]),
    ("Run tests", [sys.executable, "-m", "pytest", "-q"]),
]

if __name__ == "__main__":
    t0 = time.time()
    for name, cmd in STEPS:
        if "--skip-notebooks" in sys.argv and "notebooks" in name:
            continue
        print(f"\n=== {name} ===", flush=True)
        subprocess.run(cmd, cwd=ROOT, check=True)
    print(f"\nDone in {time.time() - t0:.0f}s")
