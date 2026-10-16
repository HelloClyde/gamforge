"""Installed resources are read-only; all generated state lives in a work area."""

import os
import subprocess
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
ROOT = Path(__file__).resolve().parents[2]


def user_data_root() -> Path:
    """Do not write settings/work into a read-only or translocated Mac .app."""
    override = os.environ.get("A9288_USER_DATA")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/GAMForge"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "A9288"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "A9288"


USER_DATA = user_data_root()
WORK = Path(os.environ.get("A9288_WORKSPACE", USER_DATA / "work")).resolve()


def dependency_root() -> Path:
    """Explicit override, relocated portable bundle, then user installation."""
    override = os.environ.get("A9288_DEPENDENCIES")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        # Keep the full Mac distribution self-contained when Finder moves or
        # translocates the .app. The adjacent shell CLI is only a convenience.
        if (
            sys.platform == "darwin"
            and executable.parent.name == "MacOS"
            and executable.parent.parent.name == "Contents"
        ):
            portable = executable.parent.parent / "Resources/dependencies"
            if portable.is_dir():
                return portable
        portable = executable.parent / "dependencies"
        if portable.is_dir():
            return portable
    return USER_DATA / "dependencies"


DEPENDENCIES = dependency_root()


def dependency_setting(saved: str | None, default: Path) -> str:
    """A stale saved path must not break a newly relocated full bundle."""
    return str(saved) if saved and Path(saved).exists() else str(default)


def task_command(module: str, *arguments) -> list[str]:
    """Re-enter a frozen worker, never pretend the packaged program is Python."""
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        if sys.platform == "win32":
            executable = executable.with_name("GAMForge-CLI.exe")
        # macOS bundles use a console-capable bootloader for both Finder GUI
        # and captured workers. Do not rely on an external shell launcher.
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


def open_path(path: Path) -> None:
    """Open a local output directory/log with the host's normal desktop app."""
    resolved = str(path.resolve(strict=True))
    if sys.platform == "win32":
        os.startfile(resolved)
    else:
        subprocess.Popen(["/usr/bin/open" if sys.platform == "darwin" else "xdg-open", resolved])
