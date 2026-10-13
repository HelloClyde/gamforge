import json
import os
import subprocess

import pytest

from a9288.compiler.backend import imm
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
    text, _ = preserve_comparison_flags("cmp %r1, %r2\next 1\nld.w %r0, [%sp+60]\njrne .Ldone\n")
    # Extended displacement is 124 bytes, not 124 words; +8 is 132 bytes.
    assert "ld.w %r0, [%sp+33]" in text
    text, _ = preserve_comparison_flags("cmp %r1, %r2\nld.w %r0, [%sp+63]\njrne .Ldone\n")
    # Crossing the scaled imm6 limit switches to raw-byte EXT encoding.
    assert "ext 4\n    ld.w %r0, [%sp+4]" in text


def test_frame_address_add_keeps_original_compare_and_restores_sp_base():
    original = "cmp %r12, 0\nld.w %r12, %sp\nadd %r12, 28\njrne .Lprefix\n"
    text, count = preserve_comparison_flags(original, protect_loads=False)
    assert count == 1
    assert "add %r12, 8\nadd %r12, 28" in text
    assert text.index("ld.w %psr, %r0") < text.index("jrne .Lprefix")
    assert "%r15" not in text
    again, count = preserve_comparison_flags(text, protect_loads=False)
    assert again == text and count == 0


def test_frame_ext_bundle_and_preview_spill_are_guarded_together():
    original = (
        "cmp %r1, %r2\nld.w %r0, [%sp+5]\n"
        "ld.w %r12, %sp\next 1\nadd %r12, 0\n"
        "ld.w %r14, 0\njrlt .Ldone\n"
    )
    fixed, count = preserve_comparison_flags(original)
    assert count == 3
    assert "add %r12, 8\next 1\nadd %r12, 0" in fixed
    assert "ld.w %r0, [%sp+7]" in fixed
    assert "jrlt .Ldone" in fixed
    fixed, count = preserve_comparison_flags(original, protect_loads=False)
    assert count == 1  # Hardware repair doesn't add optional preview guards.


def test_no_address_repair_for_real_alu_flags_calls_labels_or_wrong_register():
    for middle in (
        "ld.w %r12, %sp\nadd %r11, 28",
        "ld.w %r12, %sp\nadd %r12, %r9",
        "ld.w %r12, %sp\n.Lnext:\nadd %r12, 28",
        "ld.w %r12, %sp\ncall other\nadd %r12, 28",
        "ld.w %r12, %sp\nadd %r12, 28\nsub %r3, 1",
    ):
        original = f"cmp %r1, %r2\n{middle}\njrne .Ldone\n"
        fixed, count = preserve_comparison_flags(original, protect_loads=False)
        assert fixed == original and count == 0


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
        [
            clang,
            "--target=s1c33-none-elf",
            "-nostdlib",
            "-Wl,-Ttext=0x02700000",
            str(source),
            "-o",
            str(elf),
        ],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        [
            emulator,
            "--steps",
            "100",
            "--state-json",
            "--load-elf",
            str(elf),
            "--entry",
            "0x02700000",
            "--ram-size",
            "0x100000",
            "--sdram-size",
            "0x2000000",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    state = json.loads(result.stdout)
    assert state["halted"] and not state["faulted"]
    assert not state["unknown_accesses"]
    assert int(state["r"][4], 16) == 1
    assert int(state["r"][0], 16) == r0_expected
    assert int(state["sp"], 16) == int(state["r"][5], 16)
    assert int(state["r"][15], 16) == 0


def run_core(tmp_path, body, *, protect_loads=True):
    clang, emulator = os.getenv("A9288_TEST_CLANG"), os.getenv("A9288_TEST_C33EMU")
    if not clang or not emulator:
        pytest.skip("optional S1C33 toolchain/9288T preview core are not configured")
    assembly = "\n".join(
        [
            "    .text",
            "    .globl _start",
            "_start:",
            *imm("ld.w", "r5", 0x02300000),
            "    ld.w %sp, %r5",
            *body,
            "",
        ]
    )
    fixed, count = preserve_comparison_flags(assembly, protect_loads=protect_loads)
    source, elf = tmp_path / "flags.S", tmp_path / "flags.elf"
    source.write_text(fixed, encoding="utf-8")
    subprocess.run(
        [
            clang,
            "--target=s1c33-none-elf",
            "-nostdlib",
            "-Wl,-Ttext=0x02700000",
            str(source),
            "-o",
            str(elf),
        ],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        [
            emulator,
            "--steps",
            "300",
            "--state-json",
            "--load-elf",
            str(elf),
            "--entry",
            "0x02700000",
            "--ram-size",
            "0x100000",
            "--sdram-size",
            "0x2000000",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    state = json.loads(result.stdout)
    assert state["halted"] and not state["faulted"] and not state["unknown_accesses"]
    assert int(state["sp"], 16) == 0x02300000
    assert int(state["r"][15], 16) == 0
    return state, count


@pytest.mark.parametrize(
    "register,offset,equal", [(12, 28, True), (0, 28, True), (12, 380, False), (0, 256, False)]
)
def test_real_frame_address_keeps_pointer_full_psr_and_branch(tmp_path, register, offset, equal):
    body = [
        "    ld.w %r0, 23",
        "    ld.w %r1, 0",
        f"    ld.w %r2, {0 if equal else 1}",
        "    ld.w %r3, 16",
        "    ld.w %psr, %r3",
        "    cmp %r1, %r2",
        "    ld.w %r13, %psr",
        f"    ld.w %r{register}, %sp",
        *imm("add", f"r{register}", offset),
        "    ld.w %r14, %psr",
        "    jreq taken",
        "    ld.w %r4, 0",
        "    halt",
        "taken:",
        "    ld.w %r4, 1",
        "    halt",
    ]
    state, count = run_core(tmp_path, body, protect_loads=False)
    assert count == 1
    assert int(state["r"][4], 16) == int(equal)
    assert int(state["r"][register], 16) == 0x02300000 + offset
    assert state["r"][13] == state["r"][14]
    assert int(state["r"][14], 16) & 16  # IE preserved, not just N/Z.
    if register != 0:
        assert int(state["r"][0], 16) == 23


@pytest.mark.parametrize(
    "operation,offset", [("w", 252), ("w", 256), ("w", 380), ("uh", 126), ("uh", 256), ("ub", 255)]
)
def test_real_extended_sp_load_uses_byte_offsets_and_keeps_flags(tmp_path, operation, offset):
    scale = 4 if operation == "w" else 2 if operation == "uh" else 1
    extensions = [] if offset // scale < 64 else [f"    ext {offset >> 6}"]
    encoded = offset // scale if not extensions else offset & 63
    body = [
        "    ld.w %r0, 23",
        "    ld.w %r1, 0",
        "    ld.w %r2, 0",
        *imm("ld.w", "r12", 0x12345678),
        "    ld.w %r11, %sp",
        *imm("add", "r11", offset),
        f"    ld.{'h' if operation == 'uh' else 'b' if operation == 'ub' else 'w'} [%r11], %r12",
        "    cmp %r1, %r2",
        "    ld.w %r13, %psr",
        *extensions,
        f"    ld.{operation} %r0, [%sp+{encoded}]",
        "    ld.w %r14, %psr",
        "    jreq taken",
        "    ld.w %r4, 0",
        "    halt",
        "taken:",
        "    ld.w %r4, 1",
        "    halt",
    ]
    state, count = run_core(tmp_path, body)
    assert count == 1 and int(state["r"][4], 16) == 1
    assert int(state["r"][0], 16) == 0x12345678 & ((1 << (scale * 8)) - 1)
    assert state["r"][13] == state["r"][14]
