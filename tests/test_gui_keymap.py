"""Desktop key mappings stay per model and become compile-time CLI options."""

import json
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import a9288.gui as gui
from a9288.keymap import GUEST_KEYS, HOST_KEYS, default_keymap


def conversion(target, mapping=None):
    return gui.Conversion(
        Path("game.gam"),
        "游戏",
        None,
        Path("game.exe"),
        Path("sdk"),
        Path("tools"),
        target=target,
        key_mapping=mapping,
    )


@pytest.mark.parametrize("target", ["9288", "9288t"])
def test_conversion_forwards_only_custom_mappings(target, tmp_path):
    mapping = {HOST_KEYS[target][0].id: "none", "help": "search"}
    command = conversion(target, mapping).command(tmp_path)
    values = [command[index + 1] for index, item in enumerate(command) if item == "--key-map"]
    assert set(values) == {f"{source}={destination}" for source, destination in mapping.items()}
    assert "--key-map" not in conversion(target, default_keymap(target)).command(tmp_path)
    assert "--key-map" not in conversion(target).command(tmp_path)


@pytest.mark.parametrize("target", ["9288s", "tsw600"])
def test_soft_keyboard_conversion_has_no_physical_mapping(target, tmp_path):
    assert "--key-map" not in conversion(target).command(tmp_path)
    with pytest.raises(ValueError):
        conversion(target, {"help": "search"}).command(tmp_path)


def test_saved_mappings_ignore_stale_and_soft_keyboard_entries():
    settings = {
        "key_mappings": {
            "9288": {"help": "search", "bogus": "insert"},
            "9288t": {"start": "none", "translate": "bogus"},
            "9288s": {"help": "search"},
        }
    }
    assert gui.saved_key_mappings(settings) == {
        "9288": {"help": "search"},
        "9288t": {"start": "none"},
    }
    assert gui.saved_key_mappings({"key_mappings": []}) == {"9288": {}, "9288t": {}}
    assert gui.saved_key_mappings({"key_mappings": {"9288": "invalid"}}) == {
        "9288": {},
        "9288t": {},
    }


def test_dialog_reset_and_apply_do_not_modify_saved_state_until_apply():
    interpreter = tk.Tcl()
    dialog = gui.KeyMappingDialog.__new__(gui.KeyMappingDialog)
    dialog.target = "9288t"
    dialog.window = Mock()
    dialog.apply_callback = Mock(return_value=True)
    dialog.destination_labels = {key: value.label for key, value in GUEST_KEYS.items()}
    dialog.destination_ids = {label: key for key, label in dialog.destination_labels.items()}
    dialog.variables = {
        key: tk.StringVar(interpreter, dialog.destination_labels[value])
        for key, value in default_keymap("9288t").items()
    }
    dialog.variables["start"].set(dialog.destination_labels["none"])
    dialog.reset()
    assert dialog.variables["start"].get() == dialog.destination_labels["search"]
    dialog.apply_callback.assert_not_called()
    dialog.variables["start"].set(dialog.destination_labels["none"])
    dialog.apply()
    dialog.apply_callback.assert_called_once_with({"start": "none"})
    dialog.window.destroy.assert_called_once_with()


@pytest.fixture
def app(tmp_path, monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is unavailable")
    root.withdraw()
    monkeypatch.setattr(gui, "SETTINGS", tmp_path / "settings.json")
    result = gui.ConverterApp(root)
    yield result
    root.destroy()


def test_gui_persists_independent_maps_and_hides_touch_controls(app):
    assert app.keymap_row.winfo_manager() == "grid"
    assert app._apply_key_mapping("9288", {"help": "search"})
    app.target.set("9288t")
    assert app.key_mappings["9288t"] == {}
    assert app._apply_key_mapping("9288t", {"start": "none", "exam": "help"})
    assert "自定义 2 键" in app.keymap_hint.cget("text")
    saved = json.loads(gui.SETTINGS.read_text(encoding="utf-8"))
    assert saved["key_mappings"] == {
        "9288": {"help": "search"},
        "9288t": {"start": "none", "exam": "help"},
    }
    assert gui.saved_key_mappings(saved) == app.key_mappings
    for target in ("9288s", "tsw600"):
        app.target.set(target)
        assert app.keymap_row.winfo_manager() == ""
        app.configure_keys()  # no dialog is opened for a soft keyboard
    app.target.set("9288")
    assert app.keymap_row.winfo_manager() == "grid"
    assert app.key_mappings["9288"] == {"help": "search"}
    assert "自定义 1 键" in app.keymap_hint.cget("text")
    app.target.set("9288t")
    assert app._apply_key_mapping("9288t", default_keymap("9288t"))
    assert app.key_mappings["9288t"] == {}
    assert app.key_mappings["9288"] == {"help": "search"}


def test_mapping_dialog_widget_smoke(app):
    save = Mock(return_value=True)
    dialog = gui.KeyMappingDialog(app.root, "9288t", {"start": "help"}, save)
    try:
        assert len(dialog.variables) == len(HOST_KEYS["9288t"])
        assert dialog.variables["start"].get() == dialog.destination_labels["help"]
        dialog.reset()
        assert dialog.variables["start"].get() == dialog.destination_labels["search"]
        dialog.variables["exam"].set(dialog.destination_labels["none"])
        dialog.apply()
        save.assert_called_once_with({"exam": "none"})
    finally:
        if dialog.window.winfo_exists():
            dialog.window.destroy()


def test_gui_loads_saved_maps_at_startup(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"target": "9288t", "key_mappings": {"9288t": {"start": "none"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(gui, "SETTINGS", settings)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display is unavailable")
    root.withdraw()
    try:
        app = gui.ConverterApp(root)
        assert app.key_mappings["9288t"] == {"start": "none"}
        assert "自定义 1 键" in app.keymap_hint.cget("text")
    finally:
        root.destroy()


def test_mapping_save_failure_preserves_previous_configuration(monkeypatch):
    app = SimpleNamespace(
        root=None,
        key_mappings={"9288t": {"start": "none"}},
        _save_settings=Mock(side_effect=OSError("read only")),
        _update_keymap_controls=Mock(),
    )
    error = Mock()
    monkeypatch.setattr(gui.messagebox, "showerror", error)
    assert not gui.ConverterApp._apply_key_mapping(app, "9288t", {"start": "help"})
    assert app.key_mappings["9288t"] == {"start": "none"}
    app._update_keymap_controls.assert_not_called()
    error.assert_called_once()
