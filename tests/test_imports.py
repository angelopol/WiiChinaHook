import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.mark.parametrize("module", ["wiichinahook.gamepad.pc", "wiichinahook.gamepad.mapping",
                                    "wiichinahook.gamepad.xbox", "wiichinahook.dsu", "wiichinahook.app"])
def test_each_module_imports_first_in_a_fresh_interpreter(module):
    # Import cycles only show up when a module is the first one imported (the test
    # suite imports mapping early, the release executable may not).
    result = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=SRC, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
