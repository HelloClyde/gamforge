"""Full-width constants must not generate an illegal third EXT prefix."""

import json
import os
import subprocess

import pytest

from a9288.compiler.backend import ext_prefix, imm


@pytest.mark.parametrize("op", ["ld.w", "cmp", "and", "or", "xor", "add", "sub"])
@pytest.mark.parametrize("value", [-0x80000000, -256, -33, -32, -1, 0, 31, 32, 63,
                                   64, 255, 0xFFFF, 0x3FFFF, 0x40000, 0x7FFFF,
                                   0x80000, 0x7FFFFFFF, 0xFFFFFFFF])
def test_immediate_full_width(op, value):
    emitted = imm(op, "r2", value)
    assert len(emitted) <= 3  # two EXT prefixes plus the operation
    operand = int(emitted[-1].split(", ")[1])
    assert 0 <= operand <= 63 if op in ("add", "sub") else -32 <= operand <= 31
    if len(emitted) == 1:
        decoded = operand & 0xFFFFFFFF
    else:
        extension = 0
        for line in emitted[:-1]:
            assert line.startswith("    ext ")
            chunk = int(line.split()[-1])
            assert 0 <= chunk <= 0x1FFF
            extension = (extension << 13) | chunk
        decoded = (extension << 6) | (operand & 63)
        bits = 6 + 13 * (len(emitted) - 1)
        if op not in ("add", "sub") and decoded & (1 << (bits - 1)):
            decoded -= 1 << bits
        decoded &= 0xFFFFFFFF
    assert decoded == value & 0xFFFFFFFF


def test_register_extensions_reject_out_of_range_constants():
    assert len(ext_prefix(0x3FFFFFF)) == 2
    for value in (-1, 0x4000000, 0xFFFFFF00):
        with pytest.raises(ValueError, match="exceeds 26 bits"):
            ext_prefix(value)


@pytest.mark.parametrize(
    "operation,constant,initial,expected",
    [
        ("and", 0xFFFFFF00, 0x12345678, 0x12345600),
        ("and", 0xFFFFFF7F, 0x123456FF, 0x1234567F),
        ("or", 0x80, 0x12345600, 0x12345680),
        ("xor", 0x80000000, 0x12345678, 0x92345678),
        ("add", -1, 0x12345678, 0x12345677),
        ("add", 63, 0x12345678, 0x123456B7),
        ("sub", -1, 0x12345678, 0x12345679),
        ("ld.w", 0x40000, 0, 0x40000),
        ("ld.w", 0x7FFFF, 0, 0x7FFFF),
        ("and", 0x7FFFF, 0xFFFFFFFF, 0x7FFFF),
    ],
)
def test_real_preview_core_full_width(tmp_path, operation, constant, initial, expected):
    clang, emulator = os.getenv("A9288_TEST_CLANG"), os.getenv("A9288_TEST_C33EMU")
    if not clang or not emulator:
        pytest.skip("optional S1C33 toolchain/9288T preview core are not configured")
    assembly = "\n".join([
        "    .text", "    .globl _start", "_start:",
        *imm("ld.w", "r2", initial), *imm(operation, "r2", constant), "    halt", "",
    ])
    source, elf = tmp_path / "probe.S", tmp_path / "probe.elf"
    source.write_text(assembly, encoding="utf-8")
    subprocess.run(
        [clang, "--target=s1c33-none-elf", "-nostdlib", "-Wl,-Ttext=0x02700000",
         str(source), "-o", str(elf)], check=True, capture_output=True,
    )
    result = subprocess.run(
        [emulator, "--steps", "30", "--state-json", "--load-elf", str(elf),
         "--entry", "0x02700000", "--ram-size", "0x100000", "--sdram-size", "0x2000000"],
        check=True, capture_output=True, text=True,
    )
    state = json.loads(result.stdout)
    assert state["halted"] and not state["faulted"]
    assert not state["unknown_accesses"]
    assert int(state["r"][2], 16) == expected
