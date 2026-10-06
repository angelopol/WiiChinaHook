from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

if str(SRC) in sys.path:
    sys.path.remove(str(SRC))
sys.path.insert(0, str(SRC))

# Keep imports working when the checkout's launcher shadows the installed package.
if __name__ == "wiichinahook":
    __path__ = [str(SRC / "wiichinahook")]

from wiichinahook.cli import main


if __name__ == "__main__":
    main()
