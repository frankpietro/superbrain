"""``python -m superbrain.scheduler`` entry point."""

from __future__ import annotations

import sys

from superbrain.scheduler.cli import main

if __name__ == "__main__":
    sys.exit(main())
