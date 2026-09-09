"""Installed resources are read-only; all generated state lives in a work area."""

import os
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
ROOT = Path(__file__).resolve().parents[2]
USER_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "A9288"
WORK = Path(os.environ.get("A9288_WORKSPACE", USER_DATA / "work")).resolve()


def dependency_root() -> Path:
    """Explicit override, relocated portable bundle, then user installation."""
    override = os.environ.get("A9288_DEPENDENCIES")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        portable = Path(sys.executable).resolve().parent / "dependencies"
        if portable.is_dir():
            return portable
    return USER_DATA / "dependencies"


DEPENDENCIES = dependency_root()


def dependency_setting(saved: str | None, default: Path) -> str:
    """A stale saved path must not break a newly relocated full bundle."""
    return str(saved) if saved and Path(saved).exists() else str(default)


def task_command(module: str, *arguments) -> list[str]:
    """Use the console companion in frozen builds, never pretend it is Python."""
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).with_name("A9288-CLI.exe")
        return [str(executable), "--worker", module, *map(str, arguments)]
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    return [str(executable), "-u", "-m", "a9288", "--worker", module, *map(str, arguments)]


def child_environment() -> dict[str, str]:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if not getattr(sys, "frozen", False):
        source = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
    return env
