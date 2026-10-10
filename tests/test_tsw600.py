"""The 600 is a distinct D300 target with a deliberately shared S runtime."""

import json
import struct
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from a9288.app_options import write_icons
from a9288.compiler.d300 import pack_d300
from a9288.compiler.kf2 import pack_kf2, prepare_sdk_headers
from a9288.gui import Conversion, ConverterApp
from a9288.targets import TARGETS, display_geometry, display_scale, target_profile


def test_600_package_differs_only_in_magic_and_category(tmp_path):
    payload = b"native-code\x00\xff"
    write_icons(tmp_path, target="tsw600")
    s = pack_d300(payload, app_name="魔塔".encode("gbk"), icon_root=tmp_path)
    converted = pack_d300(
        payload, app_name="魔塔".encode("gbk"), icon_root=tmp_path, target="tsw600"
    )
    assert converted[0x0C:0x14] == "游戏".encode("gbk").ljust(8, b"\0")
    assert struct.unpack_from("<I", converted, 0x50)[0] == 0xD500
    assert struct.unpack_from("<I", s, 0x50)[0] == 0x12345678
    normalized = bytearray(converted)
    normalized[0x0C:0x14] = s[0x0C:0x14]
    normalized[0x50:0x54] = s[0x50:0x54]
    assert normalized == s
    assert converted[0x310:].startswith(payload)
    with pytest.raises(ValueError, match="requires D300"):
        pack_kf2(payload, target="tsw600")
    with pytest.raises(ValueError, match="requires KF2"):
        pack_d300(payload, app_name=b"name", icon_root=tmp_path, target="9288t")


def test_600_sdk_geometry_and_command(tmp_path):
    host = target_profile("TSW600")
    assert (host.name, host.width, host.height, host.category) == ("听说王600", 160, 240, "游戏")
    assert display_geometry("tsw600") == (159, 96, 0, 12)
    with pytest.raises(ValueError):
        display_scale("tsw600", "1.5x")
    sdk = tmp_path / "sdk"
    (sdk / "Down_Include").mkdir(parents=True)
    (sdk / "include").mkdir()
    (sdk / "Down_Include/Dsys.h").write_text("shared S/600 headers")
    (sdk / "include/Dsys.h").write_text("wrong T headers")
    prepare_sdk_headers(sdk, tmp_path / "prepared", target="tsw600")
    assert (tmp_path / "prepared/Dsys.h").read_text() == "shared S/600 headers"
    conversion = Conversion(
        tmp_path / "g.gam",
        "游戏",
        None,
        tmp_path / "g.exe",
        sdk,
        tmp_path / "tools",
        target="tsw600",
        external_resources=True,
    )
    cmd = conversion.command(tmp_path / "work")
    assert cmd[cmd.index("--target") + 1] == "tsw600"
    assert cmd[cmd.index("--display-scale") + 1] == "1x"
    assert "--external-resources" in cmd


@pytest.mark.parametrize("target", list(TARGETS))
def test_gui_labels_are_mapped_to_ids(target):
    interpreter = tk.Tcl()
    app = SimpleNamespace(
        target_display=tk.StringVar(interpreter, TARGETS[target].name),
        target=tk.StringVar(interpreter, "9288"),
    )
    ConverterApp._select_target(app)
    assert app.target.get() == target


def test_gui_600_keeps_independent_sdk_and_reports_shared_layout():
    interpreter = tk.Tcl()
    app = SimpleNamespace(
        sdk_paths={"9288s": "sdkS", "tsw600": "sdk600"},
        current_target="9288s",
        sdk=tk.StringVar(interpreter, "sdkS-custom"),
        target=tk.StringVar(interpreter, "tsw600"),
        target_display=tk.StringVar(interpreter, "9288S"),
        target_hint=Mock(),
        display_scales={"9288s": "1x", "tsw600": "1x"},
        display_scale=tk.StringVar(interpreter, "1x"),
        scale_combo=Mock(),
        _scale_changed=Mock(),
        _preview=Mock(),
    )
    ConverterApp._target_changed(app)
    assert app.sdk_paths["9288s"] == "sdkS-custom"
    assert app.sdk.get() == "sdk600"
    assert app.target_display.get() == "听说王600"
    ConverterApp._scale_changed(app)
    assert "上屏游戏 / 下屏软键盘" in app.target_hint.configure.call_args.kwargs["text"]
    assert "真机待验证" in app.target_hint.configure.call_args.kwargs["text"]


def test_packaged_selftest_lists_all_targets(capsys):
    from a9288.selftest import main

    main()
    report = json.loads(capsys.readouterr().out)
    assert report["self_test"] == "PASS"
    assert report["targets"] == ["9288", "9288t", "9288s", "tsw600"]


def test_gui_600_combobox_event_smoke(tmp_path, monkeypatch):
    import a9288.gui as gui

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is unavailable")
    root.withdraw()
    monkeypatch.setattr(gui, "SETTINGS", tmp_path / "settings.json")
    try:
        app = ConverterApp(root)
        combo = next(
            widget
            for widget in app.inputs
            if widget.winfo_class() == "TCombobox" and "听说王600" in widget.cget("values")
        )
        combo.set("听说王600")
        combo.event_generate("<<ComboboxSelected>>")
        root.update_idletasks()
        assert app.target.get() == "tsw600"
        assert app.current_target == "tsw600"
        assert app.sdk.get() == app.sdk_paths["tsw600"]
        assert app.display_scale.get() == "1x"
        assert str(app.scale_combo.cget("state")) == "disabled"
        assert app.big_photo.width() == 160 and app.small_photo.width() == 32
    finally:
        root.destroy()
