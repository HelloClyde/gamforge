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


def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-object", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--calls", type=int, default=33)
    args = parser.parse_args()
    if not 2 <= args.calls <= 128:
        parser.error("--calls must be between 2 and 128")
    args.output.mkdir(parents=True, exist_ok=True)
    clang = args.toolchain / "bin/clang.exe"
    objcopy = args.toolchain / "bin/llvm-objcopy.exe"
    runtime = args.output / "runtime.o"
    run(
        [str(objcopy), "--globalize-symbol=native_lcd_span", str(args.runtime_object), str(runtime)]
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
    for scenario in ("audit", "blit"):
        for calls in (1, args.calls):
            stem = f"{scenario}-{calls}"
            source, elf = args.output / f"{stem}.c", args.output / f"{stem}.elf"
            operation = (
                "c6502_native_present(); ++completed;"
                if scenario == "audit"
                else "for(y=0;y<96;++y) { native_lcd_span(0,19,y,row,255,255); ++completed; }"
            )
            source.write_text(
                f"""typedef unsigned char u8; typedef unsigned long u32;
extern struct {{ u8 *ram; }} c6502_native_state;
extern void c6502_native_present(void);
extern void native_lcd_span(u32,u32,u32,const u8*,u8,u8);
static u8 ram[32768], row[20]; static volatile u32 completed;
u32 probe(void) {{
    u32 i,y;
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
            expected_calls = calls if scenario == "audit" else calls * 96
            if int(state["r"][4], 16) != expected_calls:
                raise RuntimeError(f"{stem}: completed fewer calls than requested")
            state["framebuffer_sha256"] = hashlib.sha256(frame.read_bytes()).hexdigest()
            (args.output / f"{stem}.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
            results[stem] = state
        first, repeated = results[f"{scenario}-1"], results[f"{scenario}-{args.calls}"]
        if first["framebuffer_sha256"] != repeated["framebuffer_sha256"]:
            raise RuntimeError(f"{scenario}: final frame changed with repetitions")
        results[scenario] = {
            "calls_measured": args.calls - 1,
            "cycles": repeated["cycles"] - first["cycles"],
            "framebuffer_sha256": first["framebuffer_sha256"],
        }
    summary = {
        "scope": "CPU-only; excludes startup; not wall time or game FPS",
        "runtime_object": str(args.runtime_object.resolve()),
        "audit": results["audit"],
        "blit": results["blit"],
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
