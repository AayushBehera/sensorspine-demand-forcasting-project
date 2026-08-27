"""Compatibility alias for scripts/run_pipeline.py (the canonical entrypoint).

    python scripts/run_demo.py

Kept so existing docs, habits and automation keep working; new code should
call run_pipeline.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run_pipeline import main  # noqa: E402,F401

if __name__ == "__main__":
    main()
