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

TEXT_SCENARIOS = ("text24", "text12", "text_redraw")


def glyph_byte(y, column, target, inverted):
    """Fixed probe glyphs, deliberately unlike a scaled guest glyph."""
    return (
        (y * (29 if target else 17) + column * (53 if target else 43) + 17)
        ^ (255 if inverted else 0)
    ) & 255


def reference_frame(scenario, calls, scale, changing):
    """Independent scalar reference, including filter support and edge clamps."""
    bits = [[0] * 159 for _ in range(96)]
    text = scenario in TEXT_SCENARIOS
    inverted = changing and bool((calls - 1) & 1)
    if text:
        gx, gy, width = (9, 32, 8) if scenario == "text12" else (7, 16, 16)
        for y in range(16):
            for x in range(width):
                bits[gy + y][gx + x] = int(
                    bool(glyph_byte(y, x // 8, False, inverted) & (128 >> (x & 7)))
                )
        if scenario == "text_redraw":
            for y in range(16, 32):
                for x in range(16, 32):
                    value = ((y * 17 + ((x - 16) // 8) * 31 + 17) ^ (255 if inverted else 0)) & 255
                    bits[y][x] = int(bool(value & (128 >> (x & 7))))
    elif scenario != "audit":
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
            if scale == "1.5x-sharp":
                # Exact area overlap, expressed in thirds of a source pixel.
                # A destination pixel occupies a 2x2 square in these units;
                # source pixels occupy 3x3 squares. No production LUT is used.
                white_area = 0
                for sy in range(2 * y // 3, (2 * y + 1) // 3 + 1):
                    wy = min(2 * y + 2, 3 * sy + 3) - max(2 * y, 3 * sy)
                    for sx in range(2 * x // 3, (2 * x + 1) // 3 + 1):
                        wx = min(2 * x + 2, 3 * sx + 3) - max(2 * x, 3 * sx)
                        white_area += (1 - bits[min(sy, 95)][min(sx, 158)]) * wx * wy
                color = (3 * white_area + 2) // 4
            elif scale == "1.5x-linear":
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
    if text:
        # Opaque target-resolution glyph. The redraw removes coverage for
        # every guest pixel touched by the bitmap, not a blurred mask.
        left, top = (gx * 3 + 1) // 2, (gy * 3 + 1) // 2
        for y in range(24):
            for x in range(width * 3 // 2):
                px, py = left + x, top + y
                if scenario == "text_redraw" and 24 <= px < 48 and 24 <= py < 48:
                    continue
                black = bool(glyph_byte(y, x // 8, True, inverted) & (128 >> (x & 7)))
                at, shift = (py + 8) * 60 + px // 4, 6 - 2 * (px & 3)
                frame[at] = (frame[at] & ~(3 << shift)) | ((0 if black else 3) << shift)
    return bytes(frame)


def run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout or f"command failed: {command}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-object", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--calls", type=int, default=33)
    parser.add_argument("--display-scale", choices=("1x", "1.5x", "1.5x-linear", "1.5x-sharp"))
    parser.add_argument(
        "--changing-input",
        action="store_true",
        help="alternate textured frames; avoids benchmarking only no-change skips",
    )
    parser.add_argument("--include-tiles", action="store_true")
    parser.add_argument(
        "--include-pictures", action="store_true", help="call the actual bitmap API"
    )
    parser.add_argument(
        "--include-text",
        action="store_true",
        help="cached 24x24/12x24 glyph output and bitmap-over-text redraw; no GUI font calls",
    )
    args = parser.parse_args()
    if not 2 <= args.calls <= 128:
        parser.error("--calls must be between 2 and 128")
    if args.changing_input and not args.calls & 1:
        parser.error("--changing-input requires odd --calls for identical final-frame comparison")
    if args.include_text and args.display_scale not in ("1.5x-linear", "1.5x-sharp"):
        parser.error("--include-text requires a filtered 1.5x --display-scale")
    args.output.mkdir(parents=True, exist_ok=True)
    clang = args.toolchain / "bin/clang.exe"
    objcopy = args.toolchain / "bin/llvm-objcopy.exe"
    runtime = args.output / "runtime.o"
    run(
        [
            str(objcopy),
            "--globalize-symbol=native_lcd_span",
            "--globalize-symbol=native_picture",
            *(
                [
                    "--globalize-symbol=native_text",
                    "--globalize-symbol=c6502_glyphs",
                    "--globalize-symbol=c6502_text_fonts",
                    "--globalize-symbol=c6502_text_font_perf",
                ]
                if args.include_text
                else []
            ),
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
    if args.include_text:
        scenarios += TEXT_SCENARIOS
    for scenario in scenarios:
        for calls in (1, args.calls):
            stem = f"{scenario}-{calls}"
            source, elf = args.output / f"{stem}.c", args.output / f"{stem}.elf"
            text_setup, text_declarations, text_finish = "", "", ""
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
            if scenario in TEXT_SCENARIOS:
                # native_text_layer_put is inlined into native_text in release
                # objects. Prime BOTH real glyph caches to enter the actual
                # glyph blitter/compositor without depending on GUI firmware.
                text_declarations = """
extern void native_text(u8,u8,const u8*);
extern struct { unsigned short code; u8 rows[32]; } c6502_glyphs[64];
extern struct { unsigned short code; u8 width,status,rows[72]; } c6502_text_fonts[64];
extern struct { u32 hits,misses,rasterized,unavailable; } c6502_text_font_perf;
static const u8 probe_codes[4][3]={{0xd6,0xd0,0},{0xd7,0xd0,0},{'A',0,0},{'B',0,0}};
static void prime_probe_fonts(void) {
 u32 n,y,k,width,s,t;
 for(n=0;n<4;++n) {
  width=n<2?16:8; s=(probe_codes[n][0]^probe_codes[n][1])&63;
  t=(probe_codes[n][0]^probe_codes[n][1]^width)&63;
  c6502_glyphs[s].code=probe_codes[n][0]|((unsigned short)probe_codes[n][1]<<8);
  c6502_text_fonts[t].code=c6502_glyphs[s].code;
  c6502_text_fonts[t].width=width; c6502_text_fonts[t].status=1;
  for(y=0;y<16;++y) for(k=0;k<width/8;++k)
   c6502_glyphs[s].rows[y*(width/8)+k]=(u8)((y*17+k*43+17)^((n&1)?255:0));
  for(y=0;y<24;++y) for(k=0;k<(width==16?3:2);++k)
   c6502_text_fonts[t].rows[y*(width==16?3:2)+k]=(u8)((y*29+k*53+17)^((n&1)?255:0));
 }
}
"""
                text_setup = "prime_probe_fonts();"
                index = "(i&1)" if args.changing_input else "0"
                index = f"2+{index}" if scenario == "text12" else index
                x, y = (9, 32) if scenario == "text12" else (7, 16)
                operation = f"native_text({x},{y},probe_codes[{index}]); ++completed;"
                if scenario == "text_redraw":
                    invert = "((i&1)?255:0)" if args.changing_input else "0"
                    operation += (
                        "for(y=16;y<32;++y) for(k=0;k<2;++k) "
                        f"ram[0x2000+(y-16)*2+k]=(u8)((y*17+k*31+17)^{invert}); "
                        "native_picture(16,16,31,31,0x2000,1);"
                    )
                text_finish = (
                    f"if(c6502_text_font_perf.hits!={calls} || c6502_text_font_perf.misses "
                    "|| c6502_text_font_perf.rasterized || c6502_text_font_perf.unavailable) return 0;"
                )
            source.write_text(
                f"""typedef unsigned char u8; typedef unsigned long u32;
extern struct {{ u8 *ram; }} c6502_native_state;
extern void c6502_native_present(void);
extern void native_lcd_span(u32,u32,u32,const u8*,u8,u8);
extern void native_picture(u8,u8,u8,u8,unsigned short,u8);
/* The linked runtime now contains the GUI input collector. This CPU-only
   probe leaves input inactive and its window zero; no GUI call is allowed. */
void *tpDL_GUITable;
static u8 ram[32768], row[20]; static volatile u32 completed;
{text_declarations}
u32 probe(void) {{
    u32 i,y,k;
    c6502_native_state.ram=ram;
    for(i=0;i<20;++i) row[i]=(u8)(i*31+17);
    c6502_native_present();
    {text_setup}
    for(i=0;i<{calls};++i) {{ {operation} }}
    {text_finish}
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
                if scenario in ("audit", "picture", "picture_tile", *TEXT_SCENARIOS)
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
        "text_scope": "warm fixed glyph caches; no GUI font rasterization"
        if args.include_text
        else None,
        **{scenario: results[scenario] for scenario in scenarios},
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
