"""Build a standalone, finite 9288T 16-gray LCD transaction probe.

This is a hardware experiment, not a production game display option.
Its CPU-only tests do not prove physical LCD grayscale response or exit safety.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from a9288.compiler.backend import imm
from a9288.compiler.kf2 import pack_kf2, prepare_sdk_headers
from a9288.compiler.s1c33_compat import preserve_comparison_flags
from a9288.paths import DATA


def run(command):
    return subprocess.run(command, check=True, text=True, capture_output=True, timeout=60)


def tables():
    text = []
    for levels in (4, 16):
        bits = 2 if levels == 4 else 4
        rows = []
        for wy in (0, 1, 3, 5):
            values = []
            for pat in range(64):
                top = [(pat >> (2 - j)) & 1 for j in range(3)]
                bot = [(pat >> (5 - j)) & 1 for j in range(3)]
                packed = 0
                for sx, wx in ((0, 3), (1, 1), (1, 5)):
                    white = (
                        (1 - top[sx]) * (6 - wx) * (6 - wy)
                        + (1 - top[sx + 1]) * wx * (6 - wy)
                        + (1 - bot[sx]) * (6 - wx) * wy
                        + (1 - bot[sx + 1]) * wx * wy
                    )
                    packed = (packed << bits) | ((white * (levels - 1) + 18) // 36)
                values.append(str(packed))
            rows.append("{" + ",".join(values) + "}")
        text.append(f"static const u16 table{levels}[4][64]={{" + ",".join(rows) + "};")
    row, nxt, phase = [], [], []
    for y in range(144):
        sy, wy = divmod(max(4 * y - 1, 0), 6)
        row.append(str(sy))
        nxt.append(str(min(sy + 1, 95)))
        phase.append(str((0, 1, 3, 5).index(wy)))
    for name, values in (("yrow", row), ("ynext", nxt), ("yphase", phase)):
        text.append(f"static const u8 {name}[144]={{" + ",".join(values) + "};")
    return "\n".join(text) + "\n"


def reference(depth):
    stride, maximum = (60, 3) if depth == 2 else (120, 15)
    frame = bytearray(b"\xff" * (stride * 160))
    for y in range(8):
        for x in range(stride):
            frame[y * stride + x] = (
                (x // 15) * 85 if depth == 2 else ((x * 2 // 15) << 4) | ((x * 2 + 1) // 15)
            )

    def bit(x, y):
        return ((y * 17 + (x // 8) * 31 + 17) >> (7 - x % 8)) & 1

    for y in range(144):
        sy, wy = divmod(max(4 * y - 1, 0), 6)
        for x in range(239):
            sx, wx = divmod(max(4 * x - 1, 0), 6)
            tx, ty = min(sx + 1, 158), min(sy + 1, 95)
            white = (1 - bit(sx, sy)) * (6 - wx) * (6 - wy)
            white += (1 - bit(tx, sy)) * wx * (6 - wy)
            white += (1 - bit(sx, ty)) * (6 - wx) * wy
            white += (1 - bit(tx, ty)) * wx * wy
            color = (white * maximum + 18) // 36
            at, shift = (y + 8) * stride + x * depth // 8, 8 - depth - x * depth % 8
            frame[at] = (frame[at] & ~(maximum << shift)) | (color << shift)
    return bytes(frame)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sdk", type=Path, required=True)
    p.add_argument("--toolchain", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--emulator", type=Path)
    args = p.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sdk = out / "sdk-include"
    prepare_sdk_headers(args.sdk, sdk, target="9288t")
    (out / "gray16_tables.h").write_text(tables(), encoding="ascii")
    clang = args.toolchain / "bin/clang.exe"
    flags = [
        "--target=s1c33-none-elf",
        "-Os",
        "-ffreestanding",
        "-fno-builtin",
        "-fno-jump-tables",
        "-fomit-frame-pointer",
        "-fdata-sections",
        "-ffunction-sections",
        "-fno-strict-aliasing",
        "-DDL_DOWN",
        "-D_RLS_",
        "-Wno-int-to-pointer-cast",
        "-Wno-pointer-to-int-cast",
    ]
    for directory in (DATA / "runtime/9288_compat", sdk, DATA / "runtime", out):
        flags += ["-I", str(directory)]
    source = Path(__file__).parent / "probes/9288t_gray16.c"
    objects = []
    for src in (
        DATA / "runtime/c6502_native_9288_start.c",
        source,
        DATA / "runtime/gam4980_9288_runtime.c",
    ):
        asm, obj = out / (src.stem + ".S"), out / (src.stem + ".o")
        run([str(clang), *flags, "-S", str(src), "-o", str(asm)])
        guarded, _ = preserve_comparison_flags(asm.read_text(encoding="utf-8"))
        asm.write_text(guarded, encoding="utf-8")
        run([str(clang), "--target=s1c33-none-elf", "-c", str(asm), "-o", str(obj)])
        objects.append(obj)
    elf, raw = out / "GRAY16.elf", out / "GRAY16.bin"
    run(
        [
            str(clang),
            "--target=s1c33-none-elf",
            "-nostdlib",
            "-Wl,--gc-sections",
            "-Wl,-T," + str(DATA / "runtime/c6502_native_9288.ld"),
            *map(str, objects),
            "-o",
            str(elf),
        ]
    )
    run([str(clang.with_name("llvm-objcopy.exe")), "-O", "binary", str(elf), str(raw)])
    payload = pack_kf2(raw.read_bytes(), app_name=b"GRAY16 PROBE", target="9288t")
    args.output.write_bytes(payload)
    report = {
        "exe": str(args.output),
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "cpu_tests": {},
        "hardware_validated": False,
    }
    if args.emulator:
        for depth, suffix in ((2, 4), (4, 16)):
            start = out / f"cpu{suffix}-start.S"
            start.write_text(
                "\n".join(
                    [
                        ".text",
                        ".globl _start",
                        "_start:",
                        *imm("ld.w", "r5", 0x02200000),
                        "ld.w %sp,%r5",
                        f"call cpu{suffix}",
                        "halt",
                        "",
                    ]
                ),
                encoding="ascii",
            )
            cpu_elf, fb = out / f"cpu{suffix}.elf", out / f"cpu{suffix}.fb"
            run(
                [
                    str(clang),
                    "--target=s1c33-none-elf",
                    "-nostdlib",
                    "-Wl,--gc-sections",
                    "-Wl,-Ttext=0x02700000",
                    str(start),
                    str(objects[1]),
                    str(objects[2]),
                    "-o",
                    str(cpu_elf),
                ]
            )
            state = json.loads(
                run(
                    [
                        str(args.emulator),
                        "--steps",
                        "10000000",
                        "--state-json",
                        "--load-elf",
                        str(cpu_elf),
                        "--entry",
                        "0x02700000",
                        "--ram-size",
                        "0x100000",
                        "--sdram-size",
                        "0x2000000",
                        "--dump-bin",
                        f"0x003c0000:{19200 if depth == 4 else 9600}",
                        str(fb),
                    ]
                ).stdout
            )
            assert state["halted"] and not state["faulted"] and not state["unknown_accesses"], state
            expected = reference(depth)
            if fb.read_bytes() != expected:
                actual = fb.read_bytes()
                mismatch = next(i for i in range(len(expected)) if actual[i] != expected[i])
                raise RuntimeError(
                    f"{suffix}-gray raster mismatch @{mismatch}: {actual[mismatch]} != {expected[mismatch]}"
                )
            report["cpu_tests"][str(suffix)] = {
                "cycles": state["cycles"],
                "framebuffer_sha256": hashlib.sha256(expected).hexdigest(),
                "oracle_equal": True,
            }
        transaction_asm = out / "transaction.S"
        run(
            [
                str(clang),
                *flags,
                "-DGRAY16_TRANSACTION_TEST",
                "-S",
                str(source),
                "-o",
                str(transaction_asm),
            ]
        )
        guarded, _ = preserve_comparison_flags(transaction_asm.read_text(encoding="utf-8"))
        transaction_asm.write_text(guarded, encoding="utf-8")
        start = out / "transaction-start.S"
        start.write_text(
            "\n".join(
                [
                    ".text",
                    ".globl _start",
                    "_start:",
                    *imm("ld.w", "r5", 0x02200000),
                    "ld.w %sp,%r5",
                    "call cpu_transaction",
                    "halt",
                    "",
                ]
            ),
            encoding="ascii",
        )
        transaction_elf = out / "transaction.elf"
        run(
            [
                str(clang),
                "--target=s1c33-none-elf",
                "-nostdlib",
                "-Wl,--gc-sections",
                "-Wl,-Ttext=0x02700000",
                str(start),
                str(transaction_asm),
                str(objects[2]),
                "-o",
                str(transaction_elf),
            ]
        )
        state = json.loads(
            run(
                [
                    str(args.emulator),
                    "--steps",
                    "10000000",
                    "--state-json",
                    "--load-elf",
                    str(transaction_elf),
                    "--entry",
                    "0x02700000",
                    "--ram-size",
                    "0x100000",
                    "--sdram-size",
                    "0x2000000",
                ]
            ).stdout
        )
        assert state["halted"] and not state["faulted"] and not state["unknown_accesses"], state
        assert int(state["r"][4], 16) == 1, state
        report["cpu_tests"]["transaction"] = {
            "cycles": state["cycles"],
            "mode_lut_start_full_vram_restored": True,
            "bounded_without_clock": True,
        }
        start.write_text(
            "\n".join(
                [
                    ".text",
                    ".globl _start",
                    "_start:",
                    *imm("ld.w", "r5", 0x02200000),
                    "ld.w %sp,%r5",
                    *imm("ld.w", "r15", 0x123456),
                    "call cpu_app_lifecycle",
                    "halt",
                    "",
                ]
            ),
            encoding="ascii",
        )
        lifecycle_elf = out / "app-lifecycle.elf"
        run(
            [
                str(clang),
                "--target=s1c33-none-elf",
                "-nostdlib",
                "-Wl,--gc-sections",
                "-Wl,-Ttext=0x02700000",
                str(start),
                str(transaction_asm),
                str(objects[2]),
                "-o",
                str(lifecycle_elf),
            ]
        )
        state = json.loads(
            run(
                [
                    str(args.emulator),
                    "--steps",
                    "10000000",
                    "--state-json",
                    "--load-elf",
                    str(lifecycle_elf),
                    "--entry",
                    "0x02700000",
                    "--ram-size",
                    "0x100000",
                    "--sdram-size",
                    "0x2000000",
                ]
            ).stdout
        )
        assert state["halted"] and not state["faulted"] and not state["unknown_accesses"], state
        assert int(state["r"][4], 16) == 1 and int(state["r"][15], 16) == 0x123456, state
        report["cpu_tests"]["session_lifecycle"] = {
            "cycles": state["cycles"],
            "task3_resumed_once": True,
            "fs_only_after_restore": True,
            "gui_requires_full_firmware_test": True,
            "dp_preserved": True,
        }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
