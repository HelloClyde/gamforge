"""One catalog feeds GUI, CLI, generated C config and build reports."""

import json
import sys
from unittest.mock import Mock

import pytest
from test_executable_limits import make_conversion

from a9288 import cli
from a9288.keymap import (
    GUEST_KEYS,
    HOST_KEYS,
    c_keymap_config,
    custom_keymap,
    default_keymap,
    keymap_arguments,
    normalize_keymap,
    parse_keymap,
)


def test_catalog_is_unique_and_has_all_alphanumeric_keys():
    for target, keys in HOST_KEYS.items():
        assert len({key.id for key in keys}) == len(keys)
        assert len({key.code for key in keys}) == len(keys)
        assert {key.id for key in keys if key.id.startswith("letter_")} == {
            f"letter_{c}" for c in "abcdefghijklmnopqrstuvwxyz"
        }
        assert {key.id for key in keys if key.id.startswith("digit_")} == {
            f"digit_{c}" for c in "0123456789"
        }
        assert all(key.default in GUEST_KEYS for key in keys)
        assert default_keymap(target) == normalize_keymap(target)
        assert custom_keymap(target, default_keymap(target)) == {}
        assert keymap_arguments(target, default_keymap(target)) == []
        assert "COUNT 0u" in c_keymap_config(target)


def test_t_defaults_and_two_distinct_input_abis():
    defaults = default_keymap("9288T")
    assert [defaults[k] for k in ("start", "translate", "longman", "exam")] == [
        "search",
        "insert",
        "modify",
        "delete",
    ]
    t = {key.id: key.code for key in HOST_KEYS["9288t"]}
    m = {key.id: key.code for key in HOST_KEYS["9288"]}
    assert [t[k] for k in ("start", "translate", "longman", "exam")] == [59, 116, 117, 118]
    assert m["help"] == 4 * 8 + 5 and m["delete"] == 5 * 8 + 5
    assert m["start"] == 5 and t["start"] != m["start"]
    # Existing 9288 defaults intentionally preserved, physical labels are not
    # reverse-engineered from a guest code that already had an old mapping.
    assert default_keymap("9288")["help"] == "insert"
    assert default_keymap("9288")["delete"] == "help"


@pytest.mark.parametrize("target", ["9288", "9288t"])
def test_protected_physical_keys_are_not_remappable(target):
    for source in ("power", "shift", "enter", "escape", "up", "down", "left", "right"):
        with pytest.raises(ValueError, match="实体键"):
            normalize_keymap(target, {source: "none"})


@pytest.mark.parametrize("target", ["9288s", "tsw600"])
def test_touch_targets_use_only_fixed_soft_keyboard(target):
    assert default_keymap(target) == {}
    assert keymap_arguments(target) == []
    assert "COUNT 0u" in c_keymap_config(target)
    with pytest.raises(ValueError, match="软键盘"):
        normalize_keymap(target, {"start": "search"})
    with pytest.raises(ValueError, match="软键盘"):
        parse_keymap(target, ["start=search"])


def test_strict_validation_never_embeds_user_c():
    for item in (
        "start",
        "start=help=delete",
        "power=none",
        "start=not_a_key",
        "start=0x2b;system(x)",
    ):
        with pytest.raises(ValueError):
            parse_keymap("9288t", [item])
    with pytest.raises(ValueError, match="重复"):
        parse_keymap("9288t", ["start=help", "start=search"])
    for bad in ([], {"start": []}, {None: "help"}):
        with pytest.raises(ValueError):
            normalize_keymap("9288t", bad)
    with pytest.raises(ValueError):
        normalize_keymap("9588")
    assert parse_keymap("9288T", [" START = HELP "]) == {"start": "help"}


def test_partial_overrides_are_nonrecursive_and_deterministic():
    mapping = {"start": "insert", "translate": "search", "exam": "none"}
    assert keymap_arguments("9288t", mapping) == [
        "--key-map",
        "start=insert",
        "--key-map",
        "translate=search",
        "--key-map",
        "exam=none",
    ]
    expected = (
        "#define C6502_KEYMAP_COUNT 3u\n"
        "#define C6502_KEYMAP_ENTRIES {{59u, 41u}, {116u, 43u}, {118u, 255u}}\n"
    )
    assert c_keymap_config("9288t", mapping) == expected
    assert c_keymap_config("9288t", dict(reversed(list(mapping.items())))) == expected
    # Different build/host always regenerates its own config. No global edits.
    assert "59u" not in c_keymap_config("9288", {"start": "search"})
    assert "COUNT 0u" in c_keymap_config("9288t", {})


@pytest.mark.parametrize("target", ["9288", "9288t"])
def test_cli_propagates_mapping_to_compiler_and_report(tmp_path, monkeypatch, target):
    args = make_conversion(tmp_path, target, 64)
    args.key_map = ["start=help", "letter_a=modify"]
    runner = Mock()
    monkeypatch.setattr(cli.subprocess, "run", runner)
    cli.convert(args)
    command = runner.call_args.args[0]
    assert command.count("--key-map") == 2
    assert "start=help" in command and "letter_a=modify" in command
    report = json.loads(args.output.with_suffix(".report.json").read_text(encoding="utf-8"))
    assert report["key_mapping_supported"] is True
    assert report["key_mapping_overrides"] == {"start": "help", "letter_a": "modify"}
    assert report["key_mapping"]["space"] == "space"


def test_invalid_cli_mapping_fails_before_build_and_keeps_output(tmp_path, monkeypatch):
    args = make_conversion(tmp_path, "9288s", 64)
    args.key_map = ["start=help"]
    args.output.write_bytes(b"old-executable")
    runner = Mock()
    monkeypatch.setattr(cli.subprocess, "run", runner)
    with pytest.raises(ValueError, match="软键盘"):
        cli.convert(args)
    runner.assert_not_called()
    assert args.output.read_bytes() == b"old-executable"


def test_cli_lists_names_without_game_or_sdk(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["gamforge", "--target", "9288t", "--list-key-maps"])
    cli.main()
    text = capsys.readouterr().out
    assert "start: 开始 -> search" in text and "none:" in text
