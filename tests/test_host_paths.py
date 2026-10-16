"""Native Mac paths and worker launches, without requiring a Mac to test routing."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from a9288 import paths
from a9288.compiler import kf2


def test_macos_user_state_never_uses_windows_profile_or_bundle(tmp_path):
    with (
        patch.object(sys, "platform", "darwin"),
        patch.object(Path, "home", return_value=tmp_path),
        patch.dict(os.environ, {"LOCALAPPDATA": "wrong", "XDG_DATA_HOME": "wrong"}),
    ):
        assert paths.user_data_root() == tmp_path / "Library/Application Support/GAMForge"


def test_windows_user_data_remains_backward_compatible(tmp_path):
    with (
        patch.object(sys, "platform", "win32"),
        patch.dict(os.environ, {"LOCALAPPDATA": str(tmp_path)}),
    ):
        assert paths.user_data_root() == tmp_path / "A9288"


def test_isolated_user_data_does_not_require_changing_home(tmp_path):
    with patch.dict(os.environ, {"A9288_USER_DATA": str(tmp_path)}):
        assert paths.user_data_root() == tmp_path


def test_linux_respects_xdg_data_home(tmp_path):
    with (
        patch.object(sys, "platform", "linux"),
        patch.dict(os.environ, {"XDG_DATA_HOME": str(tmp_path)}),
    ):
        assert paths.user_data_root() == tmp_path / "A9288"


@pytest.mark.parametrize("location", ["应用程序", "AppTranslocation/random/d"])
def test_macos_full_bundle_relocates_with_embedded_dependencies(tmp_path, location):
    contents = tmp_path / location / "GAMForge.app/Contents"
    executable = contents / "MacOS/GAMForge"
    dependencies = contents / "Resources/dependencies"
    dependencies.mkdir(parents=True)
    with (
        patch.object(sys, "platform", "darwin"),
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", str(executable)),
        patch.dict(os.environ, {}, clear=True),
    ):
        assert paths.dependency_root() == dependencies.resolve()
        with patch.dict(os.environ, {"A9288_DEPENDENCIES": str(tmp_path / "override")}):
            assert paths.dependency_root() == tmp_path / "override"


def test_mac_light_bundle_falls_back_to_user_dependencies(tmp_path):
    executable = tmp_path / "GAMForge.app/Contents/MacOS/GAMForge"
    with (
        patch.object(sys, "platform", "darwin"),
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", str(executable)),
        patch.dict(os.environ, {}, clear=True),
    ):
        assert paths.dependency_root() == paths.USER_DATA / "dependencies"


@pytest.mark.parametrize("module", ["cli", "compiler.build", "compiler.backend"])
def test_mac_frozen_worker_reenters_the_bundle_not_a_windows_exe(tmp_path, module):
    executable = tmp_path / "目录 with spaces/GAMForge.app/Contents/MacOS/GAMForge"
    with (
        patch.object(sys, "platform", "darwin"),
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", str(executable)),
    ):
        assert paths.task_command(module, "中文 游戏.gam") == [
            str(executable),
            "--worker",
            module,
            "中文 游戏.gam",
        ]


def test_windows_frozen_worker_keeps_console_companion(tmp_path):
    with (
        patch.object(sys, "platform", "win32"),
        patch.object(sys, "frozen", True, create=True),
        patch.object(sys, "executable", str(tmp_path / "GAMForge.exe")),
    ):
        assert paths.task_command("cli", "game.gam") == [
            str(tmp_path / "GAMForge-CLI.exe"),
            "--worker",
            "cli",
            "game.gam",
        ]


@pytest.mark.parametrize("platform,opener", [("darwin", "/usr/bin/open"), ("linux", "xdg-open")])
def test_open_local_paths_without_shell_interpolation(tmp_path, platform, opener):
    log = tmp_path / "中文 ' $ log.txt"
    log.write_text("test", encoding="utf-8")
    with patch.object(sys, "platform", platform), patch.object(paths.subprocess, "Popen") as popen:
        paths.open_path(log)
    popen.assert_called_once_with([opener, str(log.resolve())])


def test_open_missing_file_does_not_launch_anything(tmp_path):
    with patch.object(paths.subprocess, "Popen") as popen, pytest.raises(FileNotFoundError):
        paths.open_path(tmp_path / "missing")
    popen.assert_not_called()


def test_macos_prefers_native_tools_and_rejects_windows_only_bundle(tmp_path):
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "clang.exe").write_bytes(b"MZ")
    with patch.object(sys, "platform", "darwin"), patch.object(kf2.shutil, "which") as which:
        with pytest.raises(SystemExit, match="Windows toolchain"):
            kf2.find_tool(tmp_path, "clang")
        which.assert_not_called()
        (tools / "clang").write_bytes(b"native")
        assert kf2.find_tool(tmp_path, "clang") == str(tools / "clang")


def test_windows_prefers_native_exe_when_mixed_toolchains_exist(tmp_path):
    (tmp_path / "clang").write_bytes(b"Mac")
    (tmp_path / "clang.exe").write_bytes(b"MZ")
    with patch.object(sys, "platform", "win32"):
        assert kf2.find_tool(tmp_path, "clang") == str(tmp_path / "clang.exe")


def test_gui_smoke_dispatch_does_not_enter_interactive_main():
    from a9288 import __main__, selftest

    with (
        patch.object(sys, "argv", ["GAMForge", "--gui-smoke-test"]),
        patch.object(selftest, "gui_smoke_test") as smoke,
    ):
        __main__.main()
    smoke.assert_called_once_with()
