"""Replay translated SysPicture on the S1C33 CPU, without a firmware UI.

Uses the actual converter-produced runtime objects, not a patched/replaced
blitter. The source bitmap may be a user's GAM; no game asset is distributed.
This checks memory/alignment/output correctness, not device performance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from a9288.compiler.backend import imm
from a9288.compiler.s1c33_compat import preserve_comparison_flags

PROBE = """
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned long u32;
extern struct {
    u8 *ram, *game; u32 game_size; u16 banks[16]; u8 bank_select;
    long window, hdc; u32 heap_next, random_state;
    u16 keyboard_state; u8 keyboard_type,input_filter,key_sound,running;
} c6502_native_state;
extern const u8 game_image_start[];
extern void c6502_native_present(void);
extern void native_picture(u8,u8,u8,u8,u16,u8);
static u8 guarded_ram[32768+64];
void *tpDL_FSTable; /* Debug trace is inactive; firmware FS is never entered. */
u32 probe(void) {
    u32 i;
    u8 *ram=guarded_ram+32;
    for(i=0;i<sizeof(guarded_ram);++i) guarded_ram[i]=0;
    for(i=0;i<32;++i) guarded_ram[i]=guarded_ram[32768+32+i]=0x5a;
    c6502_native_state.ram=ram;
    c6502_native_state.game=(u8*)game_image_start;
    c6502_native_state.game_size=GAME_SIZE;
    for(i=0;i<16;++i) c6502_native_state.banks[i]=(u16)i;
    for(i=0;i<4;++i) {
        c6502_native_state.banks[5+i]=(u16)(0x20d+i);
        c6502_native_state.banks[9+i]=(u16)(DATA_BANK+i);
    }
    c6502_native_present();
    native_picture(RECT_X0,RECT_Y0,RECT_X1,RECT_Y1,PICTURE_ADDRESS,0);
    for(i=0;i<32;++i)
        if(guarded_ram[i]!=0x5a || guarded_ram[32768+32+i]!=0x5a) return 2;
    return 1;
}
"""


def run(*command: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(arg) for arg in command], check=True, capture_output=True, text=True, timeout=60
    )


def rectangle(text: str) -> tuple[int, int, int, int]:
    values = tuple(int(value, 0) for value in text.split(","))
    if len(values) != 4 or not (0 <= values[0] <= values[2] < 159):
        raise argparse.ArgumentTypeError("expected x0,y0,x1,y1 within 159x96")
    if not 0 <= values[1] <= values[3] < 96:
        raise argparse.ArgumentTypeError("expected x0,y0,x1,y1 within 159x96")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--data-bank", type=lambda s: int(s, 0), default=0x21D)
    parser.add_argument("--picture-address", type=lambda s: int(s, 0), default=0xAE82)
    parser.add_argument("--rect", type=rectangle, action="append")
    args = parser.parse_args()
    image = args.game.read_bytes()
    if not 0x9000 <= args.picture_address < 0xD000 or args.data_bank < 0x20D:
        parser.error("this ROM-source replay requires contiguous data banks 9..12")
    source_offset = (args.data_bank - 0x20D) * 4096 + args.picture_address - 0x9000
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    tools = args.toolchain / "bin"
    runtime = args.runtime_dir / "c6502_native_runtime.o"
    support = args.runtime_dir / "gam4980_9288_runtime.o"
    blitter = output / "runtime.o"
    run(tools / "llvm-objcopy.exe", "--globalize-symbol=native_picture", runtime, blitter)
    assembly = [
        "    .text",
        "    .globl _start",
        "_start:",
        *imm("ld.w", "r5", 0x02300000),
        "    ld.w %sp, %r5",
        "    call probe",
        "    halt",
        '    .section .rodata.game_probe,"a",@progbits',
        "    .globl game_image_start",
        "game_image_start:",
        f'    .incbin "{args.game.resolve().as_posix()}"',
        "",
    ]
    startup = output / "probe-start.S"
    startup.write_text("\n".join(assembly), encoding="utf-8")
    source = output / "probe.c"
    source.write_text(PROBE, encoding="utf-8")
    results = []
    for index, rect in enumerate(args.rect or [(8, 14, 119, 81)]):
        x0, y0, x1, y1 = rect
        stride = (x1 - x0 + 8) // 8
        if source_offset + stride * (y1 - y0 + 1) > len(image):
            parser.error("source bitmap exceeds the supplied game")
        code, elf = output / f"probe-{index}.S", output / f"probe-{index}.elf"
        run(
            tools / "clang.exe",
            "--target=s1c33-none-elf",
            "-Os",
            "-ffreestanding",
            "-fno-builtin",
            "-ffunction-sections",
            f"-DGAME_SIZE={len(image)}u",
            f"-DDATA_BANK={args.data_bank}",
            f"-DPICTURE_ADDRESS={args.picture_address}",
            *(f"-DRECT_{name}={value}" for name, value in zip(("X0", "Y0", "X1", "Y1"), rect)),
            "-S",
            source,
            "-o",
            code,
        )
        fixed, _ = preserve_comparison_flags(code.read_text(encoding="utf-8"))
        code.write_text(fixed, encoding="utf-8")
        run(
            tools / "clang.exe",
            "--target=s1c33-none-elf",
            "-nostdlib",
            "-Wl,--gc-sections",
            "-Wl,-Ttext=0x02700000",
            startup,
            code,
            blitter,
            support,
            "-o",
            elf,
        )
        frame = output / f"frame-{index}.bin"
        state = json.loads(
            run(
                args.emulator,
                "--steps",
                "3000000",
                "--state-json",
                "--load-elf",
                elf,
                "--entry",
                "0x02700000",
                "--ram-size",
                "0x100000",
                "--sdram-size",
                "0x2000000",
                "--force-lcdc-240x160-2bpp",
                "--dump-bin",
                "0x003c0000:0x2580",
                frame,
            ).stdout
        )
        (output / f"cpu-{index}.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        assert state["halted"] and not state["faulted"] and not state["unknown_accesses"], state
        assert int(state["r"][4], 16) == 1, "RAM canary overwritten"
        assert int(state["sp"], 16) == 0x02300000, "SP not restored"
        expected = bytearray(b"\xff" * 9600)
        for y in range(y1 - y0 + 1):
            for x in range(x1 - x0 + 1):
                black = image[source_offset + y * stride + x // 8] & (128 >> (x & 7))
                if black:
                    px, py = 40 + x0 + x, 32 + y0 + y
                    expected[py * 60 + px // 4] &= ~(3 << ((3 - (px & 3)) * 2))
        actual = frame.read_bytes()
        assert len(actual) == len(expected)
        differences = sum(a != b for a, b in zip(actual, expected))
        assert differences == 0, f"{differences} framebuffer bytes differ in {rect}"
        result = {
            "rect": rect,
            "returned": True,
            "ram_canaries_ok": True,
            "framebuffer_different_bytes": differences,
            "framebuffer_sha256": hashlib.sha256(actual).hexdigest(),
            "cpu_cycles": state["cycles"],
        }
        results.append(result)
        print(json.dumps(result))
    (output / "results.json").write_text(
        json.dumps(
            {
                "scope": "CPU-only 9288T 1x SysPicture; contiguous ROM banks; no firmware tasks/FS",
                "runtime_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
                "game_sha256": hashlib.sha256(image).hexdigest(),
                "cases": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
