"""Output host selection must reach both SDK preparation and KF2 metadata."""

import struct
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from a9288.app_options import icon_images
from a9288.compiler.kf2 import pack_kf2, prepare_sdk_headers
from a9288.gui import Conversion, ConverterApp
from a9288.icons import encode_icon
from a9288.targets import display_geometry, display_scale, target_profile


@pytest.mark.parametrize(
    "target,width,height,directory,module",
    [("9288", 320, 240, "Down_Include", 8), ("9288T", 240, 160, "include", 0x0208)],
)
def test_host_profile_and_kf2(target, width, height, directory, module):
    host = target_profile(target)
    assert (host.width, host.height, host.sdk_directory) == (width, height, directory)
    packed = pack_kf2(b"native-code", target=target)
    header = struct.unpack_from("<IIHH16sIIIII", packed)
    assert header[2:4] == (1, module)
    assert packed[header[5] :] == b"native-code"


def test_sdk_selection_does_not_mix_hosts(tmp_path):
    sdk, include = tmp_path / "sdk", tmp_path / "prepared"
    for directory, marker in [("Down_Include", b"9288"), ("include", b"9288T")]:
        root = sdk / directory
        root.mkdir(parents=True)
        (root / "Dsys.h").write_bytes(marker + b'\n#include "GUI\\Window.h"\n')
    prepare_sdk_headers(sdk, include, target="9288t")
    assert (include / "Dsys.h").read_bytes() == b'9288T\n#include "GUI/Window.h"\n'
    prepare_sdk_headers(sdk, include)
    assert (include / "dsys.h").read_bytes().startswith(b"9288\n")
    with pytest.raises(SystemExit, match="9288T SDK headers not found"):
        prepare_sdk_headers(tmp_path / "missing", include, target="9288t")


def test_gui_target_forwarded_without_changing_resources(tmp_path):
    conversion = Conversion(
        tmp_path / "game.gam",
        "游戏",
        None,
        tmp_path / "game.exe",
        tmp_path / "sdk",
        tmp_path / "tools",
        external_resources=True,
        target="9288T",
    )
    command = conversion.command(tmp_path / "work")
    assert command[command.index("--target") + 1] == "9288t"
    assert command[command.index("--display-scale") + 1] == "1x"
    assert "--external-resources" in command


def test_unknown_host_is_rejected():
    with pytest.raises(ValueError, match="不支持的输出机型"):
        target_profile("9588")


def test_kf2_default_9288t_icon_matches_unframed_preview():
    packed = pack_kf2(b"native-code", target="9288t")
    header = struct.unpack_from("<IIHH16sIIIII", packed)
    big, small = icon_images(target="9288t")
    for image, offset, size in (
        (big, header[6], header[7]),
        (small, header[6] + header[7], header[8]),
    ):
        expected = encode_icon(image.width, image.height, [v // 85 for v in image.tobytes()])
        assert packed[offset : offset + size] == expected


def test_gui_target_switch_refreshes_icon_without_resetting_selection(tmp_path):
    interpreter = tk.Tcl()
    app = SimpleNamespace(
        sdk_paths={"9288": "sdk8", "9288t": "sdkT"},
        current_target="9288",
        sdk=tk.StringVar(interpreter, "sdk8-custom"),
        target=tk.StringVar(interpreter, "9288t"),
        target_display=tk.StringVar(interpreter, "9288"),
        target_hint=Mock(),
        display_scales={"9288": "2x", "9288t": "1x"},
        display_scale=tk.StringVar(interpreter, "2x"),
        scale_combo=Mock(),
        _scale_changed=Mock(),
        icon_path=tmp_path / "my-icon.png",
        _preview=Mock(),
    )
    ConverterApp._target_changed(app)
    assert app.sdk_paths["9288"] == "sdk8-custom"
    assert app.sdk.get() == "sdkT"
    assert app.target_display.get() == "9288T"
    assert app.display_scale.get() == "1x"
    assert app.icon_path == tmp_path / "my-icon.png"
    app._preview.assert_called_once_with()


@pytest.mark.parametrize(
    "target,requested,expected,geometry",
    [
        ("9288", None, "2x", (318, 192, 1, 24)),
        ("9288T", None, "1x", (159, 96, 40, 32)),
        ("9288t", "1.5x", "1.5x", (239, 144, 0, 8)),
    ],
)
def test_display_scale_defaults_and_geometry(target, requested, expected, geometry):
    assert display_scale(target, requested) == expected
    assert display_geometry(target, requested) == geometry


@pytest.mark.parametrize("target,scale", [("9288", "1x"), ("9288t", "2x"), ("9288t", "3x")])
def test_reject_incompatible_scales(target, scale):
    with pytest.raises(ValueError, match="不支持画面缩放"):
        display_scale(target, scale)


def test_gui_optional_1_5x_is_forwarded(tmp_path):
    conversion = Conversion(
        tmp_path / "g.gam",
        "游戏",
        None,
        tmp_path / "g.exe",
        tmp_path / "sdk",
        tmp_path / "tools",
        target="9288t",
        display_scale="1.5x",
    )
    command = conversion.command(tmp_path / "work")
    assert command[command.index("--display-scale") + 1] == "1.5x"


def test_gui_remembers_t_scale_across_targets():
    interpreter = tk.Tcl()
    app = SimpleNamespace(
        sdk_paths={"9288": "sdk8", "9288t": "sdkT"},
        current_target="9288t",
        sdk=tk.StringVar(interpreter, "sdkT"),
        target=tk.StringVar(interpreter, "9288"),
        target_display=tk.StringVar(interpreter, "9288T"),
        target_hint=Mock(),
        display_scales={"9288": "2x", "9288t": "1x"},
        display_scale=tk.StringVar(interpreter, "1.5x"),
        scale_combo=Mock(),
        _scale_changed=Mock(),
        _preview=Mock(),
    )
    ConverterApp._target_changed(app)
    assert app.display_scale.get() == "2x"
    assert app.display_scales["9288t"] == "1.5x"
    app.target.set("9288t")
    ConverterApp._target_changed(app)
    assert app.display_scale.get() == "1.5x"


def test_gui_pixel_perfect_hint():
    interpreter = tk.Tcl()
    app = SimpleNamespace(
        target=tk.StringVar(interpreter, "9288t"),
        display_scale=tk.StringVar(interpreter, "1x"),
        target_hint=Mock(),
    )
    ConverterApp._scale_changed(app)
    assert "159 × 96 · 1x 点对点居中" in app.target_hint.configure.call_args.kwargs["text"]


def test_gui_scale_widget_smoke(tmp_path, monkeypatch):
    import a9288.gui as gui

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is unavailable")
    root.withdraw()
    monkeypatch.setattr(gui, "SETTINGS", tmp_path / "settings.json")
    try:
        app = ConverterApp(root)
        assert app.display_scale.get() == "2x"
        assert str(app.scale_combo.cget("state")) == "disabled"
        app.target.set("9288t")
        assert app.display_scale.get() == "1x"
        assert tuple(app.scale_combo.cget("values")) == ("1x", "1.5x")
        assert str(app.scale_combo.cget("state")) == "readonly"
        app.display_scale.set("1.5x")
        assert "239 × 144" in app.target_hint.cget("text")
        app.target.set("9288")
        assert app.display_scale.get() == "2x"
        app.target.set("9288t")
        assert app.display_scale.get() == "1.5x"
        root.update_idletasks()
    finally:
        root.destroy()


@pytest.mark.parametrize("target", ["9288", "9288t"])
def test_gui_preview_uses_selected_target(target):
    interpreter = tk.Tcl()
    app = SimpleNamespace(
        icon_path=None,
        target=tk.StringVar(interpreter, target),
        large=Mock(),
        small=Mock(),
        icon_label=Mock(),
        icon_hint=Mock(),
    )
    with (
        patch("a9288.gui.icon_images", wraps=icon_images) as images,
        patch("a9288.gui.ImageTk.PhotoImage", side_effect=lambda image: image),
    ):
        ConverterApp._preview(app)
    images.assert_called_once_with(None, target=target)
    big, small = icon_images(target=target)
    assert app.big_photo.tobytes() == big.resize((160, 160), Image.Resampling.NEAREST).tobytes()
    assert app.small_photo.tobytes() == small.resize((32, 32), Image.Resampling.NEAREST).tobytes()
    assert app.icon_hint.configure.call_args.kwargs["text"].endswith(
        "保留系统边框" if target == "9288" else "不加白框背景"
    )
