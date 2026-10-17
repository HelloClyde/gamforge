"""Whole-file target limits and the corresponding load-span linker ceilings."""

import argparse
import json
import os
import struct
import subprocess
from pathlib import Path

import pytest

from a9288 import cli
from a9288.compiler import build, kf2
from a9288.paths import DATA
from a9288.targets import target_profile


def test_only_9288t_expands_the_historical_file_boundary():
    assert target_profile("9288T").max_exe_bytes == 2621440
    for target in ("9288", "9288s", "tsw600"):
        assert target_profile(target).max_exe_bytes == 1024 * 1024 - 1
    # D300 imports this legacy payload constant; do not expand its window.
    assert kf2.APP_MAX_PAYLOAD_SIZE == cli.MAX_KF2_BYTES == 1024 * 1024


@pytest.mark.parametrize("target", ["9288", "9288t"])
def test_kf2_exact_total_file_limit_includes_both_icons_and_header(target):
    maximum = target_profile(target).max_exe_bytes
    payload_size = kf2.max_kf2_payload_size(target)
    packed = kf2.pack_kf2(b"x" * payload_size, target=target)
    header = struct.unpack_from("<IIHH16sIIIII", packed)
    assert header[5] == kf2.KF2_OVERHEAD_SIZE == 536
    assert header[9] == len(packed) == maximum
    assert len(packed[header[5] :]) == payload_size
    with pytest.raises(SystemExit, match=f"maximum {maximum}"):
        kf2.pack_kf2(b"x" * (payload_size + 1), target=target)


def test_payload_size_alone_cannot_bypass_total_file_limit():
    for target in ("9288", "9288t"):
        with pytest.raises(SystemExit, match="including header and icons"):
            kf2.pack_kf2(b"x" * target_profile(target).max_exe_bytes, target=target)


@pytest.mark.parametrize("target", ["9288s", "tsw600"])
def test_d300_does_not_acquire_a_kf2_payload_override(target):
    assert build.linker_payload_args(target) == []
    with pytest.raises(ValueError, match="not KF2"):
        kf2.max_kf2_payload_size(target)


@pytest.mark.parametrize("target", ["9288", "9288t"])
def test_kf2_link_limit_reserves_exact_container_overhead(target):
    ceiling = kf2.APP_LOAD_ADDRESS + kf2.max_kf2_payload_size(target)
    assert build.linker_payload_args(target) == [f"-Wl,--defsym=__app_payload_limit={ceiling:#x}"]
    source = (DATA / "runtime/c6502_native_9288.ld").read_text()
    assert "PROVIDE(__app_payload_limit = 0x02800000);" in source
    assert "ASSERT(__payload_end <= __app_payload_limit," in source
    assert source.index(".bss (NOLOAD)") < source.index("__payload_end = .;")
    assert source.index(".noinit (NOLOAD)") < source.index("__payload_end = .;")
    builder = Path(build.__file__).read_text(encoding="utf-8")
    assert "*linker_payload_args(args.target)," in builder


def make_conversion(tmp_path, target, size):
    game = tmp_path / "limit.gam"
    data = bytearray(128)
    data[:4] = b"GAM\0"
    struct.pack_into("<HI", data, 0x40, 0x5046, 96)
    game.write_bytes(data)
    work = tmp_path / "work"
    stage = work / "native-result/program.exe"
    stage.parent.mkdir(parents=True)
    stage.write_bytes(b"x" * size)
    for suffix in (".elf", ".map"):
        stage.with_suffix(suffix).write_bytes(b"size-test-fixture")
    report = work / "c6502-s1c33-direct/report.json"
    report.parent.mkdir()
    report.write_text("{}")
    return argparse.Namespace(
        game=game,
        target=target,
        app_name="边界",
        icon=None,
        sdk=tmp_path,
        toolchain=tmp_path,
        output=tmp_path / "result.exe",
        work_dir=work,
        rom8=tmp_path / "8.BIN",
        rome=tmp_path / "E.BIN",
    )


@pytest.mark.parametrize("target", ["9288", "9288t", "9288s", "tsw600"])
def test_cli_accepts_exact_target_maximum_and_reports_it(tmp_path, monkeypatch, target):
    maximum = target_profile(target).max_exe_bytes
    args = make_conversion(tmp_path, target, maximum)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: None)
    cli.convert(args)
    assert args.output.stat().st_size == maximum
    report = json.loads(args.output.with_suffix(".report.json").read_text(encoding="utf-8"))
    assert report["output_exe_bytes"] == report["output_exe_max_bytes"] == maximum
    assert report["output_exe_limit_includes_header_icons"] is True
    assert report["output_exe_limit_experimental"] is (target == "9288t")


@pytest.mark.parametrize("target", ["9288", "9288t", "9288s", "tsw600"])
def test_cli_rejects_one_extra_byte_without_replacing_output(tmp_path, monkeypatch, target):
    maximum = target_profile(target).max_exe_bytes
    args = make_conversion(tmp_path, target, maximum + 1)
    args.output.write_bytes(b"existing-output")
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: None)
    with pytest.raises(ValueError, match=str(maximum)):
        cli.convert(args)
    assert args.output.read_bytes() == b"existing-output"
    assert not args.output.with_suffix(".report.json").exists()


@pytest.mark.parametrize("target", [None, "9288", "9288t"])
@pytest.mark.parametrize("extra", [0, 1])
def test_actual_s1c33_linker_counts_bss_and_noinit(tmp_path, target, extra):
    """Optional tiny link-only probe; never compiles or executes a game."""
    configured = os.environ.get("A9288_TEST_TOOLCHAIN")
    if not configured:
        pytest.skip("Set A9288_TEST_TOOLCHAIN to run actual S1C33 linker boundary tests")
    tools = Path(configured)
    clang = kf2.find_tool(tools, "clang")
    linker = kf2.find_tool(tools, "ld.lld")
    ceiling = (
        kf2.APP_RAM_END
        if target is None
        else kf2.APP_LOAD_ADDRESS + kf2.max_kf2_payload_size(target)
    )
    # .text at +0x1800 (4B), .bss (16B), .noinit, final 1-byte payload tail.
    noinit_size = ceiling - (kf2.APP_LOAD_ADDRESS + 0x1814) - 1 + extra
    assembly = tmp_path / "probe.s"
    assembly.write_text(
        '.section .text.startup,"ax",@progbits\n'
        ".global DL_AppMain\nDL_AppMain:\n.byte 0\n"
        '.section .text,"ax",@progbits\n.byte 0,0,0,0\n'
        '.section .bss,"aw",@nobits\n.space 16\n'
        f'.section .noinit,"aw",@nobits\n.space {noinit_size}\n'
    )
    obj = tmp_path / "probe.o"
    subprocess.run(
        [clang, "--target=s1c33-none-elf", "-c", str(assembly), "-o", str(obj)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    map_path = tmp_path / "probe.map"
    command = [linker]
    if target:
        command += [build.linker_payload_args(target)[0].removeprefix("-Wl,")]
    command += [
        "-T",
        str(DATA / "runtime/c6502_native_9288.ld"),
        "-Map=" + str(map_path),
        str(obj),
        "-o",
        str(tmp_path / "probe.elf"),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if extra:
        assert result.returncode != 0
        assert "including BSS/noinit exceeds" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert kf2.read_map_symbol(map_path, "__payload_end") == ceiling
