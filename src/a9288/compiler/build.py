#!/usr/bin/env python3
"""Build the direct C6502 -> S1C33 translation as a BBK 9288 KF2."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from a9288.app_options import c_name_definition, default_app_name, encode_app_name, write_icons
from a9288.compiler import kf2 as build_9288
from a9288.compiler.boot import DEFAULT_ROM8, DEFAULT_ROME
from a9288.compiler.fast_helpers import fast_helper
from a9288.paths import DATA, WORK, child_environment, task_command


def runtime_supported_bridges() -> tuple[str, ...]:
    """Return the bridges that have an explicit native implementation.

    The old builder assigned IDs only to the symbols used by the current
    game.  That made the runtime header game-dependent and, more seriously,
    allowed a newly encountered SDK/runtime function to reach the generic
    default branch.  Derive the contract from explicit switch cases instead:
    a symbol without a real case is a compile-time error, never a silent
    no-op in the generated game.
    """

    runtime = (DATA / "runtime" / "c6502_native_runtime.c").read_text(encoding="utf-8")
    return tuple(sorted(set(re.findall(r"\bcase\s+C6502_BRIDGE_([A-Za-z0-9_]+)\s*:", runtime))))


SUPPORTED_BRIDGES = runtime_supported_bridges()


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, env=child_environment(), check=True)


def undefined_symbols(readelf: str, obj: Path) -> list[str]:
    text = subprocess.check_output([readelf, "-s", str(obj)], text=True, errors="replace")
    result = []
    for line in text.splitlines():
        match = re.search(r"\bUND\s+(\S+)\s*$", line)
        if match and match.group(1) != "0":
            result.append(match.group(1))
    return sorted(set(result))


def verify_9288_abi(clang: str) -> None:
    """Reject a P/ECE compiler even if it accepts S1C33 assembly."""
    source = (
        "unsigned int abi_first(unsigned int a) { return a; }\n"
        "unsigned int abi_fourth(unsigned int a, unsigned int b, "
        "unsigned int c, unsigned int d) { return d; }\n"
        "void abi_stack(void (*use)(unsigned int *)) { "
        "unsigned int message[7]; use(message); use(message); }\n"
    )
    result = subprocess.run(
        [
            clang,
            "--target=s1c33-none-elf",
            "-Os",
            "-ffreestanding",
            "-S",
            "-x",
            "c",
            "-",
            "-o",
            "-",
        ],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    )
    if not all(re.search(r"ld\.w\s+%r4,\s*%r" + str(reg) + r"\b", result.stdout) for reg in (6, 9)):
        raise SystemExit(
            "S1C33 compiler does not implement the 9288 GNU33 ABI "
            "(arguments R6-R9, result R4). Apply "
            "toolchain/9288-gnu33-abi.patch and rebuild clang."
        )
    # CALL.D changes SP before the delay slot. Passing the address of a
    # local object in that slot corrupts every SDK API taking stack structs.
    instructions = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.lstrip().startswith((".", "#"))
    ]
    for previous, following in zip(instructions, instructions[1:]):
        if re.match(r"(?:call|ret)\.d\b", previous) and "%sp" in following:
            raise SystemExit(
                "S1C33 compiler has the unsafe SP-read delay-slot bug; "
                "apply toolchain/9288-gnu33-abi.patch and rebuild clang"
            )
    print("9288 GNU33 ABI verified: arguments R6-R9, result R4")


def symbol_address(register: str, symbol: str) -> list[str]:
    return [
        f"    ext {symbol}@h",
        f"    ext {symbol}@m",
        f"    ld.w %{register}, {symbol}@l",
    ]


def generate_bridges(
    symbols: list[str], output: Path, profile_other: bool = False
) -> tuple[Path, Path]:
    unsupported = sorted(set(symbols) - set(SUPPORTED_BRIDGES))
    if unsupported:
        raise ValueError(
            "native runtime has no explicit implementation for: " + ", ".join(unsupported)
        )

    header = output / "c6502_native_bridge_ids.h"
    assembly = output / "c6502_native_bridges.S"
    enum_lines = [
        "#ifndef C6502_NATIVE_BRIDGE_IDS_H",
        "#define C6502_NATIVE_BRIDGE_IDS_H",
        "enum {",
    ]
    bridge_ids = {symbol: index for index, symbol in enumerate(SUPPORTED_BRIDGES, 1)}
    for symbol, index in bridge_ids.items():
        enum_lines.append(f"    C6502_BRIDGE_{symbol} = {index},")
    enum_lines.append("};")
    enum_lines.append("")
    for symbol in symbols:
        if symbol in bridge_ids:
            enum_lines.append(f"#define C6502_NEEDS_{symbol} 1")
    enum_lines.append(f"#define C6502_BRIDGE_COUNT {len(bridge_ids) + 1}u")
    if profile_other:
        enum_lines.append("static const char *const c6502_profile_names[] = {")
        enum_lines.append('    "session",')
        enum_lines.extend(f'    "{symbol}",' for symbol in bridge_ids)
        enum_lines.append("};")
    enum_lines.extend(["#endif", ""])
    header.write_text("\n".join(enum_lines), encoding="utf-8")

    lines = [
        '    .section ".text.c6502_bridges","ax",@progbits',
        "    .p2align 1",
        "    .extern c6502_bridge_regs",
        "    .extern c6502_bridge_target",
        "    .extern c6502_host_dp",
        "    .extern c6502_native_bridge",
        "    .extern c6502_game_fn_00046",
        "",
    ]

    def save_registers(symbol: str, ident: int) -> list[str]:
        body = [
            f"    .globl {symbol}",
            f"    .type {symbol},@function",
            f"{symbol}:",
            "    sub %sp, 4",
            "    ld.w [%sp+0], %r3",
        ]
        body += symbol_address("r3", "c6502_bridge_regs")
        for register in range(15):
            if register == 3:
                continue  # original R3 is in the explicit stack slot
            if register:
                body.append(f"    ext {register * 4}")
            body.append(f"    ld.w [%r3], %r{register}")
        body += ["    ld.w %r11, [%sp+0]", "    ext 12", "    ld.w [%r3], %r11"]
        if profile_other:
            # R8 has already been saved. Before PUSHN, SP+4 is the native
            # return PC (SP+0 contains original R3). Never guess a C frame
            # layout or scan arbitrary stack memory for return addresses.
            body.append("    ld.w %r8, [%sp+4]")
        body.append("    pushn %r3")
        low = ident & 0x3F
        shown_low = low if low < 32 else low - 64
        # Guest Y/SP were saved above.  GNU33 uses R6/R7 for host arguments,
        # R4 for results, and R15 as the firmware data pointer.
        body.append("    ld.w %r6, %r3")
        if ident > 31:
            body.append(f"    ext {ident >> 6}")
        body.append(f"    ld.w %r7, {shown_low}")
        # Interrupts remain enabled in the native app. R15 MUST keep the
        # firmware DP even between C calls; it is not a guest scratch reg.
        body.append(
            "    call c6502_native_bridge_profiled"
            if profile_other
            else "    call c6502_native_bridge"
        )
        return body

    def reload_registers() -> list[str]:
        body: list[str] = []
        for register in range(4, 15):
            if register:
                body.append(f"    ext {register * 4}")
            body.append(f"    ld.w %r{register}, [%r3]")
        return body

    def fast_dynamic_ram_prefix(symbol: str, ident: int) -> list[str]:
        """Keep ordinary indirect RAM traffic entirely in native code.

        Compiler-generated pointer loops are extremely common.  Routing each
        byte through the C bridge used to save all fifteen registers, call C,
        and reload the shared guest ABI.  R12 already contains the 16-bit
        guest address and R14 is the resident RAM base, so normal RAM is a
        single native load/store after a few cheap range checks.

        Page-zero DATA channels and bank registers must retain their side
        effects.  Writes to $021b and $2028 also retain the two compatibility
        rules in guest_write().
        """

        if symbol not in ("c6502_direct_read8", "c6502_direct_write8"):
            return []
        slow = f".Lbridge_slow_{ident}"
        fast = f".Lbridge_fast_{ident}"
        result = [
            f"    .globl {symbol}",
            f"    .type {symbol},@function",
            f"{symbol}:",
            # Work on the address page: pages $40-$ff are banked ROM/data,
            # while only page zero needs special-register checks.  S1C33's
            # immediate shift form is limited to eight bits, so this also
            # avoids a needlessly synthesized shift-by-15 sequence.
            "    ld.w %r0, %r12",
            "    srl %r0, 8",
            "    ext 63",
            "    cmp %r0, %r0",
            f"    jrugt {slow}",
            "    cmp %r0, 0",
            f"    jrne {fast}",
            "    cmp %r12, 3",
            f"    jrule {slow}",
            "    cmp %r12, 12",
            f"    jrult {fast}",
            "    cmp %r12, 14",
            f"    jrule {slow}",
            f"{fast}:",
        ]
        if symbol == "c6502_direct_write8":
            # These ordinary-looking RAM addresses have required firmware
            # post-write values in the existing player compatibility model.
            result += [
                # $0401-$1000 contains folded LCD RAM. It must reach the
                # mirrored framebuffer store, including $0ff3/$1000.
                # Padding in this range is filtered by the C adapter.
                "    cmp %r0, 4",
                f"    jrult .Lbridge_not_lcd_{ident}",
                "    ext 64",
                "    ld.w %r0, 0",  # $1000 inclusive
                "    cmp %r12, %r0",
                f"    jrule {slow}",
                f".Lbridge_not_lcd_{ident}:",
                "    ld.w %r0, %r12",
                "    srl %r0, 8",
                "    cmp %r0, 3",  # read-only firmware page $0300
                f"    jreq {slow}",
                "    ext 8",
                "    ld.w %r0, 27",  # $021b
                "    cmp %r12, %r0",
                f"    jreq {slow}",
                "    ext 128",
                "    ld.w %r0, -24",  # $2028
                "    cmp %r12, %r0",
                f"    jreq {slow}",
            ]
        result += [
            "    ld.w %r0, %r14",
            "    add %r0, %r12",
        ]
        if symbol == "c6502_direct_read8":
            result += ["    ld.ub %r12, [%r0]", "    ret"]
        else:
            result += ["    ld.b [%r0], %r13", "    ret"]
        result += [f"{slow}:"]
        # R0-R3 hold already-recovered source call arguments.  A memory load
        # used to evaluate a later argument must not overwrite an earlier one.
        # Preserve R11 in an explicit slot. R15 must remain the host DP at
        # every instruction boundary, including while firmware IRQs run.
        fixed = [line.replace("%r0", "%r11") for line in result[:3]]
        fixed += ["    sub %sp, 4", "    ld.w [%sp+0], %r11"]
        for line in result[3:]:
            if line == "    ret":
                fixed += ["    ld.w %r11, [%sp+0]", "    add %sp, 4"]
            fixed.append(line.replace("%r0", "%r11"))
        fixed += ["    ld.w %r11, [%sp+0]", "    add %sp, 4"]
        return fixed

    for symbol in symbols:
        ident = bridge_ids[symbol]
        fast_prefix, complete = fast_helper(symbol, ident)
        if complete:
            lines.extend(fast_prefix)
            continue
        if not fast_prefix:
            fast_prefix = fast_dynamic_ram_prefix(symbol, ident)
        lines.extend(fast_prefix)
        if fast_prefix:
            # The public symbol and type were emitted by the fast prefix; the
            # generic slow bridge begins at its private label.
            slow_body = save_registers(symbol, ident)
            lines.extend(slow_body[3:])
        else:
            lines.extend(save_registers(symbol, ident))
        if symbol in (
            "c6502_runtime_switch_comparison",
            "c6502_runtime_banked_function_call",
            "c6502_runtime_indirect_call",
        ):
            lines += reload_registers()
            lines += symbol_address("r11", "c6502_bridge_target")
            lines.append("    ld.w %r11, [%r11]")
            lines.extend(
                ["    popn %r3", "    ld.w %r3, [%sp+0]", "    add %sp, 4", "    cmp %r11, 0"]
            )
            if symbol == "c6502_runtime_switch_comparison":
                lines.extend(
                    [
                        "    jreq .Lbridge_return_%d" % ident,
                        "    jp %r11",
                        ".Lbridge_return_%d:" % ident,
                        "    ret",
                    ]
                )
            else:
                lines.extend(
                    [
                        "    jreq .Lbridge_return_%d" % ident,
                        "    call %r11",
                        ".Lbridge_return_%d:" % ident,
                        "    ret",
                    ]
                )
        else:
            lines += reload_registers()
            lines.extend(["    popn %r3", "    ld.w %r3, [%sp+0]", "    add %sp, 4", "    ret"])
        lines.extend([f"    .size {symbol}, .-{symbol}", ""])

    lines.extend(
        [
            "    .globl c6502_native_enter",
            "    .type c6502_native_enter,@function",
            "c6502_native_enter:",
            "    pushn %r3",
            "    ld.w %r0, %r6",
        ]
    )
    lines += symbol_address("r1", "c6502_host_dp")
    lines.append("    ld.w [%r1], %r15")
    for register in range(4, 15):
        lines.append(f"    ext {register * 4}")
        lines.append(f"    ld.w %r{register}, [%r0]")
    lines.append("    call c6502_game_fn_00046")
    lines += symbol_address("r0", "c6502_host_dp")
    lines.extend(
        [
            "    ld.w %r15, [%r0]",
            "    popn %r3",
            "    ret",
            "    .size c6502_native_enter, .-c6502_native_enter",
            "",
        ]
    )
    assembly.write_text("\n".join(lines), encoding="utf-8")
    return header, assembly


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--app-name")
    parser.add_argument("--icon", type=Path)
    parser.add_argument(
        "--profile-other",
        action="store_true",
        help="diagnostic native-boundary and sampled helper attribution",
    )
    parser.add_argument("--work-dir", type=Path, default=WORK / "cli")
    parser.add_argument("--rom8", type=Path, default=DEFAULT_ROM8)
    parser.add_argument("--rome", type=Path, default=DEFAULT_ROME)
    args = parser.parse_args()

    app_name = args.app_name if args.app_name is not None else default_app_name(args.game.stem)
    name_bytes = encode_app_name(app_name)
    print("[GAM9288_STAGE] prepare|检查 9288 SDK 与工具链", flush=True)

    clang = build_9288.find_tool(args.toolchain, "clang")
    verify_9288_abi(clang)
    ld = build_9288.find_tool(args.toolchain, "ld.lld")
    objcopy = build_9288.find_tool(args.toolchain, "llvm-objcopy")
    readelf = build_9288.find_tool(args.toolchain, "llvm-readelf")
    direct = args.work_dir / "c6502-s1c33-direct"
    sdk_include = args.work_dir / "sdk-include-native"
    runtime_build = args.work_dir / "c6502-native-runtime"
    runtime_build.mkdir(parents=True, exist_ok=True)
    build_9288.prepare_sdk_headers(args.sdk.resolve(), sdk_include)
    config = runtime_build / "c6502_native_app_config.h"
    config.write_text(c_name_definition(app_name), encoding="ascii")
    icons = runtime_build / "icons"
    write_icons(icons, args.icon)

    run(
        task_command(
            "compiler.backend",
            str(args.game.resolve()),
            "--clang",
            clang,
            "--objcopy",
            objcopy,
            "--output",
            str(direct),
            "--jobs",
            "4",
            "--rom8",
            str(args.rom8),
            "--rome",
            str(args.rome),
        )
    )
    combined = runtime_build / "game-combined.o"
    generated_objects = sorted(direct.glob("*.o"))
    generated_objects = [item for item in generated_objects if item.name != "combined.o"]
    run([ld, "-r", "-o", str(combined), *(str(item) for item in generated_objects)])
    external = undefined_symbols(readelf, combined)
    if "c6502_runtime_banked_function_call" in external:
        raise SystemExit(
            "Unresolved FAR call in native game: recover its target "
            "before linking; no silent no-op/fallback is permitted."
        )
    header, bridge_s = generate_bridges(external, runtime_build, args.profile_other)
    print("[GAM9288_STAGE] runtime|编译公共运行库与程序元数据", flush=True)

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
        f"-DC6502_GAME_SIZE={args.game.stat().st_size}u",
        "-Wno-pointer-to-int-cast",
        "-Wno-int-to-pointer-cast",
        "-I",
        str(DATA / "runtime" / "9288_compat"),
        "-I",
        str(sdk_include),
        "-I",
        str(DATA / "runtime"),
        "-I",
        str(runtime_build),
        "-include",
        str(config),
    ]
    objects = [combined]
    if args.profile_other:
        flags.append("-DC6502_PROFILE_OTHER=1")
    for source in (
        DATA / "runtime" / "c6502_native_9288_start.c",
        DATA / "runtime" / "c6502_native_9288.c",
        DATA / "runtime" / "c6502_native_runtime.c",
        DATA / "runtime" / "gam4980_9288_runtime.c",
        bridge_s,
    ):
        obj = runtime_build / (source.stem + ".o")
        run([clang, *flags, "-c", str(source), "-o", str(obj)])
        objects.append(obj)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    elf = args.output.with_suffix(".elf")
    map_path = args.output.with_suffix(".map")
    print("[GAM9288_STAGE] link|链接 S1C33 原生程序", flush=True)
    run(
        [
            clang,
            "--target=s1c33-none-elf",
            "-nostdlib",
            "-Wl,-T," + str(DATA / "runtime" / "c6502_native_9288.ld"),
            "-Wl,-Map," + str(map_path),
            "-Wl,--gc-sections",
            *(str(obj) for obj in objects),
            "-o",
            str(elf),
        ]
    )
    remaining = undefined_symbols(readelf, elf)
    if remaining:
        raise SystemExit("unresolved native symbols: " + ", ".join(remaining))
    raw = runtime_build / "FUMO-NATIVE.bin"
    run([objcopy, "-O", "binary", str(elf), str(raw)])
    payload_end = build_9288.read_map_symbol(map_path, "__payload_end")
    payload = raw.read_bytes()
    expected = payload_end - build_9288.APP_LOAD_ADDRESS
    if len(payload) != expected:
        raise SystemExit(f"payload size mismatch: {len(payload)} != {expected}")
    print("[GAM9288_STAGE] pack|生成名称、图标与 KF2 EXE", flush=True)
    app = build_9288.pack_kf2(payload, app_name=name_bytes, icon_root=icons)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(app)
    digest = hashlib.sha256(app).hexdigest()
    if args.profile_other:
        symbols = []
        symbol_text = subprocess.check_output([readelf, "-s", str(elf)], text=True)
        for line in symbol_text.splitlines():
            match = re.match(
                r"\s*\d+:\s+([0-9a-fA-F]+)\s+(\d+)\s+FUNC\s+\S+\s+\S+\s+\S+\s+(\S+)", line
            )
            if match:
                symbols.append(
                    {"address": int(match[1], 16), "size": int(match[2]), "name": match[3]}
                )
        args.output.with_suffix(".profile-symbols.json").write_text(
            json.dumps(
                {
                    "build": "OTHER-PROFILE-1",
                    "exe_sha256": digest,
                    "game_sha256": hashlib.sha256(args.game.read_bytes()).hexdigest(),
                    "symbols": sorted(symbols, key=lambda item: item["address"]),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    print(f"KF2: {args.output.resolve()} ({len(app)} bytes)")
    print(f"SHA256: {digest}")
    print(f"guest external bridge symbols: {len(external)}")


if __name__ == "__main__":
    main()
