"""Execute real S1C33 checks for byte-exact, potentially unaligned GAM tails."""

import json
import os
import re
import subprocess

import pytest

from a9288.compiler.backend import compile_resource_image
from a9288.paths import DATA


@pytest.mark.parametrize("tail", [0, 1, 2, 3])
@pytest.mark.parametrize("wrong_size", [False, True])
def test_actual_s1c33_embedded_image_length_guard(tmp_path, tail, wrong_size):
    clang, emulator = os.getenv("A9288_TEST_CLANG"), os.getenv("A9288_TEST_C33EMU")
    if not clang or not emulator:
        pytest.skip("optional native S1C33 compiler and CPU core are not configured")
    game = bytes((i * 29 + 17) & 255 for i in range(0x4000 + tail))
    image = compile_resource_image(clang, tmp_path, game)
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    declarations = "\n".join(re.findall(r"extern c6502_u8 c6502_game_image_.*;", runtime))
    guard = (
        "if ((c6502_u32)c6502_game_image_end"
        + runtime.split("if ((c6502_u32)c6502_game_image_end", 1)[1].split("return 0;", 1)[0]
        + "return 0;"
    )
    code = tmp_path / "probe.c"
    code.write_text(
        "typedef unsigned char c6502_u8;typedef unsigned long c6502_u32;\n"
        + declarations
        + f"\n#define C6502_GAME_SIZE {len(game) + int(wrong_size)}u\n"
        + "int verify(void){"
        + guard
        + f"return c6502_game_image_start[0]=={game[0]} && "
        + f"c6502_game_image_start[{len(game) - 1}]=={game[-1]};}}\n",
        encoding="utf-8",
    )
    entry = tmp_path / "entry.S"
    entry.write_text(
        ".text\n.globl _start\n_start:\n ext 69\n ext 0\n ld.w %r5, 0\n"
        " ld.w %sp, %r5\n call verify\n halt\n",
        encoding="utf-8",
    )
    script = tmp_path / "link.ld"
    script.write_text(
        "ENTRY(_start)\nSECTIONS { .text 0x02700000 : { *(.text*) } "
        ".rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) } }\n",
        encoding="utf-8",
    )
    elf = tmp_path / "probe.elf"
    subprocess.run(
        [
            clang,
            "--target=s1c33-none-elf",
            "-Os",
            "-ffreestanding",
            "-fno-builtin",
            "-nostdlib",
            f"-Wl,-T,{script}",
            str(entry),
            str(code),
            image["object"],
            "-o",
            str(elf),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    result = subprocess.run(
        [
            emulator,
            "--load-elf",
            str(elf),
            "--entry",
            "0x02700000",
            "--steps",
            "10000",
            "--max-unknown-accesses",
            "0",
            "--ram-size",
            "0x100000",
            "--sdram-size",
            "0x2000000",
            "--state-json",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    state = json.loads(result.stdout[result.stdout.index("{") :])
    assert state["halted"] and not state["faulted"] and not state["unknown_accesses"]
    assert int(state["r"][4], 16) == int(not wrong_size), state
