"""Measure actual S1C33 runtime objects in a CPU-only framebuffer probe.

Use baseline and candidate objects from real 9288T builds. The one-call run
is subtracted from the repeated run to exclude initialization. This measures
CPU cycles, NOT hardware wall time or game FPS. No GAM or ROM is
needed; generated probe artifacts belong in a work directory, not the repo.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from a9288.compiler.backend import imm
from a9288.compiler.s1c33_compat import preserve_comparison_flags


def reference_frame(scenario, calls, scale, changing):
    """Independent scalar reference, including linear clamp/4-tap rounding."""
    bits = [[0] * 159 for _ in range(96)]
    if scenario != "audit":
        tile = scenario in ("tile", "picture_tile")
        rows = range(16, 32) if tile else range(96)
        first, count = (4, 2) if tile else (0, 20)
        for y in rows:
            for k in range(count):
                value = (
                    ((y * 17 + k * 31 + 17) ^ (255 if (calls - 1) & 1 else 0)) & 255
                    if changing
                    else (k * 31 + 17) & 255
                )
                for bit in range(8):
                    x = (first + k) * 8 + bit
                    if x < 159:
                        bits[y][x] = int(bool(value & (128 >> bit)))
    frame = bytearray(b"\xff" * 9600)
    for y in range(96 if scale == "1x" else 144):
        for x in range(159 if scale == "1x" else 239):
            if scale == "1.5x-linear":
                nx, ny = 4 * x - 1, 4 * y - 1
                sx, sy = max(nx, 0) // 6, max(ny, 0) // 6
                wx, wy = max(nx, 0) % 6, max(ny, 0) % 6
                tx, ty = min(sx + 1, 158), min(sy + 1, 95)
                a, b = 3 * (1 - bits[sy][sx]), 3 * (1 - bits[sy][tx])
                c, d = 3 * (1 - bits[ty][sx]), 3 * (1 - bits[ty][tx])
                color = (
                    a * (6 - wx) * (6 - wy)
                    + b * wx * (6 - wy)
                    + c * (6 - wx) * wy
                    + d * wx * wy
                    + 18
                ) // 36
            else:
                sx, sy = (x, y) if scale == "1x" else (x * 2 // 3, y * 2 // 3)
                color = 3 * (1 - bits[sy][sx])
            px, py = (x + 40, y + 32) if scale == "1x" else (x, y + 8)
            at, shift = py * 60 + px // 4, 6 - 2 * (px & 3)
            frame[at] = (frame[at] & ~(3 << shift)) | (color << shift)
    return bytes(frame)


def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-object", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--calls", type=int, default=33)
    parser.add_argument("--display-scale", choices=("1x", "1.5x", "1.5x-linear"))
    parser.add_argument(
        "--changing-input",
        action="store_true",
        help="alternate textured frames; avoids benchmarking only no-change skips",
    )
    parser.add_argument("--include-tiles", action="store_true")
    parser.add_argument(
        "--include-pictures", action="store_true", help="call the actual bitmap API"
    )
    args = parser.parse_args()
    if not 2 <= args.calls <= 128:
        parser.error("--calls must be between 2 and 128")
    if args.changing_input and not args.calls & 1:
        parser.error("--changing-input requires odd --calls for identical final-frame comparison")
    args.output.mkdir(parents=True, exist_ok=True)
    clang = args.toolchain / "bin/clang.exe"
    objcopy = args.toolchain / "bin/llvm-objcopy.exe"
    runtime = args.output / "runtime.o"
    run(
        [
            str(objcopy),
            "--globalize-symbol=native_lcd_span",
            "--globalize-symbol=native_picture",
            str(args.runtime_object),
            str(runtime),
        ]
    )
    startup = args.output / "start.S"
    startup.write_text(
        "\n".join(
            [
                "    .text",
                "    .globl _start",
                "_start:",
                *imm("ld.w", "r5", 0x02200000),
                "    ld.w %sp, %r5",
                "    call probe",
                "    halt",
                "",
            ]
        ),
        encoding="utf-8",
    )
    results = {}
    scenarios = ("audit", "blit", "tile") if args.include_tiles else ("audit", "blit")
    if args.include_pictures:
        scenarios += ("picture", "picture_tile")
    for scenario in scenarios:
        for calls in (1, args.calls):
            stem = f"{scenario}-{calls}"
            source, elf = args.output / f"{stem}.c", args.output / f"{stem}.elf"
            operation = (
                "c6502_native_present(); ++completed;"
                if scenario == "audit"
                else "for(y=0;y<96;++y) { native_lcd_span(0,19,y,row,255,255); ++completed; }"
            )
            if scenario == "tile":
                operation = (
                    "for(y=16;y<32;++y) { native_lcd_span(4,5,y,row,255,255); ++completed; }"
                )
            if args.changing_input and scenario != "audit":
                start, end, first, last = (16, 32, 4, 5) if scenario == "tile" else (0, 96, 0, 19)
                operation = (
                    f"for(y={start};y<{end};++y) {{ for(k=0;k<{last - first + 1};++k) "
                    f"row[k]=(u8)((y*17+k*31+17)^((i&1)?255:0)); "
                    f"native_lcd_span({first},{last},y,row,255,255); ++completed; }}"
                )
            if scenario in ("picture", "picture_tile"):
                start, end, x0, x1, width = (
                    (16, 32, 32, 47, 2) if scenario == "picture_tile" else (0, 96, 0, 159, 20)
                )
                value = (
                    "(u8)((y*17+k*31+17)^((i&1)?255:0))" if args.changing_input else "(u8)(k*31+17)"
                )
                operation = (
                    f"for(y={start};y<{end};++y) for(k=0;k<{width};++k) "
                    f"ram[0x2000+(y-{start})*{width}+k]={value}; "
                    f"native_picture({x0},{start},{x1},{end - 1},0x2000,1); ++completed;"
                )
            source.write_text(
                f"""typedef unsigned char u8; typedef unsigned long u32;
extern struct {{ u8 *ram; }} c6502_native_state;
extern void c6502_native_present(void);
extern void native_lcd_span(u32,u32,u32,const u8*,u8,u8);
extern void native_picture(u8,u8,u8,u8,unsigned short,u8);
static u8 ram[32768], row[20]; static volatile u32 completed;
u32 probe(void) {{
    u32 i,y,k;
    c6502_native_state.ram=ram;
    for(i=0;i<20;++i) row[i]=(u8)(i*31+17);
    c6502_native_present();
    for(i=0;i<{calls};++i) {{ {operation} }}
    return completed;
}}
""",
                encoding="utf-8",
            )
            assembly = args.output / f"{stem}.S"
            run(
                [
                    str(clang),
                    "--target=s1c33-none-elf",
                    "-Os",
                    "-ffreestanding",
                    "-fno-builtin",
                    "-fno-strict-aliasing",
                    "-ffunction-sections",
                    "-S",
                    str(source),
                    "-o",
                    str(assembly),
                ]
            )
            guarded, _ = preserve_comparison_flags(assembly.read_text(encoding="utf-8"))
            assembly.write_text(guarded, encoding="utf-8")
            run(
                [
                    str(clang),
                    "--target=s1c33-none-elf",
                    "-Os",
                    "-ffreestanding",
                    "-fno-builtin",
                    "-fno-strict-aliasing",
                    "-ffunction-sections",
                    "-nostdlib",
                    "-Wl,--gc-sections",
                    "-Wl,-Ttext=0x02700000",
                    str(startup),
                    str(assembly),
                    str(runtime),
                    "-o",
                    str(elf),
                ]
            )
            frame = args.output / f"{stem}.fb.bin"
            state = json.loads(
                run(
                    [
                        str(args.emulator),
                        "--steps",
                        "100000000",
                        "--state-json",
                        "--load-elf",
                        str(elf),
                        "--entry",
                        "0x02700000",
                        "--ram-size",
                        "0x100000",
                        "--sdram-size",
                        "0x2000000",
                        "--force-lcdc-240x160-2bpp",
                        "--dump-bin",
                        "0x003c0000:0x2580",
                        str(frame),
                    ]
                ).stdout
            )
            if not state["halted"] or state["faulted"] or state["unknown_accesses"]:
                raise RuntimeError(f"{stem}: probe did not finish cleanly: {state}")
            expected_calls = (
                calls
                if scenario in ("audit", "picture", "picture_tile")
                else calls * (16 if scenario == "tile" else 96)
            )
            if int(state["r"][4], 16) != expected_calls:
                raise RuntimeError(f"{stem}: completed fewer calls than requested")
            state["framebuffer_sha256"] = hashlib.sha256(frame.read_bytes()).hexdigest()
            if args.display_scale and frame.read_bytes() != reference_frame(
                scenario, calls, args.display_scale, args.changing_input
            ):
                raise RuntimeError(
                    f"{stem}: framebuffer differs from the independent scalar oracle"
                )
            (args.output / f"{stem}.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
            results[stem] = state
        first, repeated = results[f"{scenario}-1"], results[f"{scenario}-{args.calls}"]
        if first["framebuffer_sha256"] != repeated["framebuffer_sha256"]:
            raise RuntimeError(f"{scenario}: final frame changed with repetitions")
        results[scenario] = {
            "calls_measured": args.calls - 1,
            "cycles": repeated["cycles"] - first["cycles"],
            "cycles_per_operation": (repeated["cycles"] - first["cycles"]) // (args.calls - 1),
            "framebuffer_sha256": first["framebuffer_sha256"],
        }
    summary = {
        "scope": "CPU-only; excludes startup; not wall time or game FPS",
        "runtime_object": str(args.runtime_object.resolve()),
        "display_scale": args.display_scale,
        "changing_input": args.changing_input,
        **{scenario: results[scenario] for scenario in scenarios},
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
