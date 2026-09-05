"""Fail before publication if the pushed tag does not describe this source."""

import re
import sys
import tomllib
from pathlib import Path

from a9288 import __version__


def check(tag):
    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:rc\d+)?", tag):
        raise ValueError("Expected a version tag such as v0.1.0")
    if tag[1:] != __version__ or project["project"]["version"] != __version__:
        raise ValueError("Tag, package version and pyproject version must match")
    print(f"Release version verified: {tag}")


if __name__ == "__main__":
    check(sys.argv[1])
