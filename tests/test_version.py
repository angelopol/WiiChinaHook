import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_package_and_project_versions_match():
    # The release workflow publishes v<version> when it changes; both must agree.
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    init = re.search(r'^__version__ = "(.+)"', (ROOT / "src/wiichinahook/__init__.py").read_text(encoding="utf-8"),
                     re.M).group(1)
    assert init == project
