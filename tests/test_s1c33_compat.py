import json
import os
import subprocess

import pytest

from a9288.compiler.s1c33_compat import preserve_comparison_flags


def test_guard_spill_between_compare_and_branch():
    text, count = preserve_comparison_flags(
        "cmp %r12, %r14\nld.w %r14, [%sp+5]\nld.w %r3, %r10\njrlt .Ldone\n"
    )
    assert count == 1
    assert "ld.w %r14, [%sp+7]" in text
    assert text.index("ld.w %psr, %r0") < text.index("jrlt .Ldone")
    assert "popn %r0" in text
    assert "%r15" not in text


def test_r0_destination_is_preserved_and_symbol_extensions_are_not_split():
    text, count = preserve_comparison_flags(
        "cmp %r1, %r2\next thing@h\next thing@m\nld.w %r0, thing@l\njreq .Ldone\n"
    )
    assert count == 1
    assert "ext thing@h\next thing@m\n    ld.w %r0, thing@l" in text
    assert text.index("ld.w [%sp+1], %r0") > text.index("ld.w %r0, thing@l")


def test_byte_halfword_word_stack_offsets_account_for_two_saved_words():
    for operation, before, after in (("ub", 55, 63), ("uh", 59, 63), ("w", 61, 63)):
        text, count = preserve_comparison_flags(
            f"cmp %r1, %r2\nld.{operation} %r0, [%sp+{before}]\njrne .Ldone\n"
        )
        assert count == 1
        assert f"ld.{operation} %r0, [%sp+{after}]" in text
    text, _ = preserve_comparison_flags(
        "cmp %r1, %r2\next 1\nld.w %r0, [%sp+63]\njrne .Ldone\n"
    )
    assert "ext 2\n    ld.w %r0, [%sp+1]" in text


def test_no_guard_when_flags_are_replaced_or_at_another_block():
    original = (
        "cmp %r1, %r2\nld.w %r0, 0\nadd %r3, 1\njrne .Ldone\n"
        "cmp %r1, %r2\nld.w %r0, 0\n.Lnext:\njrne .Ldone\n"
        "cmp %r1, %r2\nld.w %r0, %r3\njrne .Ldone\n"
    )
    text, count = preserve_comparison_flags(original)
    assert count == 0
    assert text == original


@pytest.mark.parametrize(
    "load,r0_expected",
    [
        ("ld.w %r14, 0", 23),
        ("ld.w %r14, [%sp+5]", 23),
        ("ld.ub %r14, [%sp+20]", 23),
        ("ld.uh %r14, [%sp+10]", 23),
        ("ld.w %r0, 17", 17),
        ("ext 1\nld.w %r0, 0", 64),
    ],
)
def test_real_preview_core_keeps_flags_registers_and_stack(tmp_path, load, r0_expected):
    clang, emulator = os.getenv("A9288_TEST_CLANG"), os.getenv("A9288_TEST_C33EMU")
    if not clang or not emulator:
        pytest.skip("optional S1C33 toolchain/9288T preview core are not configured")
    assembly = f"""    .text
    .globl _start
_start:
    ext 69
    ext 0
    ld.w %r5, 0
    ld.w %sp, %r5
    ld.w %r0, 23
    ld.w %r1, 0
    ld.w [%sp+5], %r1
    ld.w %r12, -20
    ld.w %r14, -10
    cmp %r12, %r14
    {load}
    jrlt taken
    ld.w %r4, 0
    halt
taken:
    ld.w %r4, 1
    halt
"""
    fixed, count = preserve_comparison_flags(assembly)
    assert count == 1
    source, elf = tmp_path / "probe.S", tmp_path / "probe.elf"
    source.write_text(fixed, encoding="utf-8")
    subprocess.run(
        [clang, "--target=s1c33-none-elf", "-nostdlib", "-Wl,-Ttext=0x02700000",
         str(source), "-o", str(elf)], check=True, capture_output=True,
    )
    result = subprocess.run(
        [emulator, "--steps", "100", "--state-json", "--load-elf", str(elf),
         "--entry", "0x02700000", "--ram-size", "0x100000", "--sdram-size", "0x2000000"],
        check=True, capture_output=True, text=True,
    )
    state = json.loads(result.stdout)
    assert state["halted"] and not state["faulted"]
    assert not state["unknown_accesses"]
    assert int(state["r"][4], 16) == 1
    assert int(state["r"][0], 16) == r0_expected
    assert int(state["sp"], 16) == int(state["r"][5], 16)
    assert int(state["r"][15], 16) == 0
