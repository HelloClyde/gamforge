#!/usr/bin/env python3
"""Emit direct S1C33 functions from recovered C6502 code.

This is the first back end with an explicitly controlled guest-state ABI:

    R4=A, R5=X, R6=Y, R7=SP, R8=lazy N/Z value,
    R9=P, R10=C6502 software-stack pointer, R14=guest RAM base.

Game calls are real S1C33 calls and branches are native jumps.  There is no
guest PC dispatcher, cycle scheduler, opcode fetch, or interpreter fallback.
Rare memory/ALU operations call one shared semantic primitive; those calls do
not identify or dispatch an opcode and preserve the register ABI above.

The generated objects are a back-end/code-density contract.  They are not a
standalone KF2 until the named semantic primitives and 9288 API adapters are
linked by the native runtime stage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable

from a9288.compiler import boot as boot_export
from a9288.compiler import cfg as native
from a9288.compiler import compression as c6502_lzss
from a9288.compiler import frontend as frontend
from a9288.compiler import functions as functions
from a9288.compiler import semantics as semantic
from a9288.paths import WORK

GAME_BANK_SIZE = 0x4000
RUNTIME_FIRST = 0xD000
RUNTIME_LAST = 0xE534

FLAG_C = 0x01
FLAG_Z = 0x02
FLAG_I = 0x04
FLAG_V = 0x40
FLAG_N = 0x80


def symbol_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_").lower()
    return clean or "unknown"


def imm(op: str, register: str, value: int) -> list[str]:
    value &= 0xFFFFFFFF
    shown = value if value <= 0x7FFFFFFF else value - 0x100000000
    if -32 <= shown <= 31:
        return [f"    {op} %{register}, {shown}"]
    if op == "ld.w":
        low = value & 0x3F
        shown_low = low if low < 32 else low - 64
        high = value >> 6
        chunks: list[int] = []
        while high:
            chunks.append(high & 0x1FFF)
            high >>= 13
        if not chunks:
            chunks.append(0)
        return [
            *(f"    ext {chunk}" for chunk in reversed(chunks)),
            f"    ld.w %{register}, {shown_low}",
        ]
    chunks = []
    remaining = value
    while remaining:
        chunks.append(remaining & 0x1FFF)
        remaining >>= 13
    if not chunks:
        chunks.append(0)
    return [
        *(f"    ext {chunk}" for chunk in reversed(chunks)),
        f"    {op} %{register}, %{register}",
    ]


def ext_prefix(value: int) -> list[str]:
    """Encode the full immediate consumed by a following register-form op."""

    value &= 0xFFFFFFFF
    chunks: list[int] = []
    while value:
        chunks.append(value & 0x1FFF)
        value >>= 13
    if not chunks:
        return []
    return [f"    ext {chunk}" for chunk in reversed(chunks)]


def ram_pointer(address: int, register: str = "r12") -> list[str]:
    result = [f"    ld.w %{register}, %r14"]
    result.extend(imm("add", register, address))
    return result


def direct_ram(address: int, write: bool = False) -> bool:
    if address < 0x100:
        special = native.aotgen.PAGE0_SPECIAL_WRITE if write else native.aotgen.PAGE0_SPECIAL_READ
        return address not in special
    # 4980.cfg places game uninitialized data at $1800-$1fff and the normal
    # guest RAM window at $2000-$2fff.  A standalone native program owns both;
    # only $2028 retains the firmware side effect inherited from the player.
    return 0x1800 <= address < 0x3000 and address != 0x2028


def load_memory(address: int, destination: str) -> list[str]:
    # $28/$29 are not ordinary zero-page memory in compiler-generated code.
    # They are the little-endian C software-stack pointer.  Keep that value in
    # R10 for the whole native session so parameter/local accesses do not keep
    # reloading and rewriting two emulated bytes.
    if address in (0x28, 0x29):
        result = [f"    ld.w %{destination}, %r10"]
        if address == 0x29:
            result.append(f"    srl %{destination}, 8")
        result.append(f"    ld.ub %{destination}, %{destination}")
        return result
    if direct_ram(address):
        return ext_prefix(address) + [f"    ld.ub %{destination}, [%r14]"]
    result = imm("ld.w", "r12", address)
    result.append("    call c6502_direct_read8")
    if destination != "r12":
        result.append(f"    ld.w %{destination}, %r12")
    return result


def store_memory(address: int, source: str) -> list[str]:
    if address == 0x28:
        result = ["    ld.w %r12, %r10"]
        result.extend(imm("and", "r12", 0xFFFFFF00))
        result.extend([f"    ld.ub %r13, %{source}", "    or %r12, %r13", "    ld.uh %r10, %r12"])
        return result
    if address == 0x29:
        return [
            "    ld.ub %r10, %r10",
            f"    ld.ub %r12, %{source}",
            "    sll %r12, 8",
            "    or %r10, %r12",
            "    ld.uh %r10, %r10",
        ]
    if direct_ram(address, write=True):
        return ext_prefix(address) + [f"    ld.b [%r14], %{source}"]
    result = imm("ld.w", "r12", address)
    if source != "r13":
        result.append(f"    ld.w %r13, %{source}")
    result.append("    call c6502_direct_write8")
    return result


def set_lazy_nz(register: str, live_writes: int) -> list[str]:
    if not (live_writes & (FLAG_N | FLAG_Z)):
        return []
    return [f"    ld.ub %r8, %{register}"]


def clear_status(mask: int) -> list[str]:
    result = imm("and", "r9", mask)
    return result


def indexed_indirect_address(zp: int) -> list[str]:
    if zp == 0x28:
        return ["    ld.w %r12, %r10", "    add %r12, %r6", "    ld.uh %r12, %r12"]
    if direct_ram(zp) and direct_ram((zp + 1) & 0xFF):
        result = ext_prefix(zp) + ["    ld.ub %r11, [%r14]"]
        result.extend(ext_prefix((zp + 1) & 0xFF))
        result.extend(
            [
                "    ld.ub %r12, [%r14]",
                "    sll %r12, 8",
                "    or %r12, %r11",
                "    add %r12, %r6",
                "    ld.uh %r12, %r12",
            ]
        )
        return result
    result = imm("ld.w", "r12", zp)
    result.extend(
        ["    call c6502_direct_read16_wrap", "    add %r12, %r6", "    ld.uh %r12, %r12"]
    )
    return result


def indexed_absolute_address(base: int, index_register: str) -> list[str]:
    result = imm("ld.w", "r12", base)
    result.extend([f"    add %r12, %{index_register}", "    ld.uh %r12, %r12"])
    return result


def read_indirect_y(zp: int, destination: str) -> list[str]:
    result = indexed_indirect_address(zp)
    if zp == 0x28:
        # C6502's software stack is fixed in the game RAM region.  The pointer
        # value is already a guest RAM offset, so no bank/MMIO helper is needed.
        result.extend(["    add %r12, %r14", "    ld.ub %r12, [%r12]"])
    else:
        result.append("    call c6502_direct_read8")
    if destination != "r12":
        result.append(f"    ld.w %{destination}, %r12")
    return result


def write_indirect_y(zp: int, source: str) -> list[str]:
    result = indexed_indirect_address(zp)
    if zp == 0x28:
        result.append("    add %r12, %r14")
        result.append(f"    ld.b [%r12], %{source}")
        return result
    if source != "r13":
        result.append(f"    ld.w %r13, %{source}")
    result.append("    call c6502_direct_write8")
    return result


def emit_semantic_phrase(line: str) -> list[str]:
    match = re.fullmatch(r"C6502_([A-Z0-9_]+)\((.*)\);", line)
    if match is None:
        raise ValueError(f"unknown semantic phrase: {line}")
    name = match.group(1).lower()
    values = [int(item.strip().rstrip("u"), 0) for item in match.group(2).split(",")]
    # Lift the C6502 software stack to a real resident native value.  These
    # cases are compiler ABI operations, not 6502 instructions, so lowering
    # them here removes both helper calls and the load/modify/store traffic.
    if name in ("add16_preserve", "sub16_preserve"):
        source, destination, value = values
        operation = "add" if name == "add16_preserve" else "sub"
        if source == 0x28 and destination == 0x28:
            return imm(operation, "r10", value) + [
                "    ld.uh %r10, %r10",
                "    ld.w %r4, %r10",
                "    srl %r4, 8",
                "    ld.ub %r4, %r4",
            ]
    if name == "store16_imm" and values[0] == 0x28:
        value = values[1]
        return (
            imm("ld.w", "r10", value)
            + ["    ld.uh %r10, %r10"]
            + imm("ld.w", "r4", (value >> 8) & 0xFF)
            + ["    ld.ub %r8, %r4"]
        )
    if name == "copy16" and values[1] == 0x28:
        source = values[0]
        if source == 0x28:
            return [
                "    ld.w %r4, %r10",
                "    srl %r4, 8",
                "    ld.ub %r4, %r4",
                "    ld.ub %r8, %r4",
            ]
        result = load_memory(source, "r10")
        result.extend(load_memory((source + 1) & 0xFF, "r12"))
        result.extend(
            [
                "    ld.w %r4, %r12",
                "    sll %r12, 8",
                "    or %r10, %r12",
                "    ld.uh %r10, %r10",
                "    ld.ub %r8, %r4",
            ]
        )
        return result
    if name in ("load_stack8", "store_stack8"):
        offset = values[0]
        result = ["    ld.w %r13, %r14", "    add %r13, %r10"]
        result.extend(imm("ld.w", "r6", offset))
        if name == "load_stack8":
            result.extend(ext_prefix(offset))
            result.extend(["    ld.ub %r4, [%r13]", "    ld.ub %r8, %r4"])
        else:
            result.extend(ext_prefix(offset))
            result.extend(["    ld.b [%r13], %r4", "    ld.ub %r8, %r6"])
        return result
    registers = ("r11", "r12", "r13")
    result: list[str] = []
    for register, value in zip(registers, values):
        result.extend(imm("ld.w", register, value))
    result.append(f"    call c6502_sem_{name}")
    return result


def outline_symbol(line: str) -> str:
    name = line.split("(", 1)[0].removeprefix("C6502_").lower()
    digest = hashlib.sha1(line.encode("ascii")).hexdigest()[:10]
    return f"c6502_outline_{name}_{digest}"


def collect_semantic_outlines(
    game: bytes,
    bodies: dict[int, list[tuple[int, ...]]],
) -> dict[str, str]:
    """Select repeated compiler-semantic operations for native outlining.

    A repeated C6502 expression is emitted once as an S1C33 helper and call
    sites use a normal native call.  This is code-size optimization after
    semantic recovery, not an opcode interpreter or a guest-PC dispatch path.
    """

    counts: Counter[str] = Counter()
    for body in bodies.values():
        for record in body:
            instructions = frontend.decode_record(game, record)
            index = 0
            while index < len(instructions):
                phrase = semantic._semantic_peephole(instructions, index)
                if phrase is None:
                    index += 1
                    continue
                counts[phrase[0]] += 1
                index += phrase[1]

    selected: dict[str, str] = {}
    for line, count in counts.items():
        body = emit_semantic_phrase(line)
        # One call remains at each site and the outlined body needs one RET.
        # Count assembly operations rather than source characters; S1C33's
        # compact encodings make this a reliable conservative size proxy.
        inline_ops = len(body)
        if count >= 3 and count * inline_ops > count + inline_ops + 1:
            selected[line] = outline_symbol(line)
    return selected


def complete_function_partition(
    game: bytes,
    records: list[tuple[int, ...]],
    entries: set[int],
    bodies: dict[int, list[tuple[int, ...]]],
) -> tuple[set[int], dict[int, list[tuple[int, ...]]], dict[int, set[int]]]:
    """Turn callback/unreached CFG islands into native function groups.

    C6502 programs publish callbacks through data tables, so not every code
    root appears as a direct JSR target.  The block recovery pass has already
    validated these islands instruction by instruction.  Group each remaining
    weak CFG component once and export every predecessor-free root as a native
    entry alias.  This completes native coverage without duplicating shared
    tails or retaining an interpreter fallback.
    """

    record_by_offset = {record[2]: record for record in records}
    owned = {record[2] for body in bodies.values() for record in body}
    remaining = set(record_by_offset) - owned
    aliases: dict[int, set[int]] = {entry: {entry} for entry in bodies}
    if not remaining:
        # A branch is allowed to enter a shared tail owned by another native
        # function group.  Export every recovered block label so that such a
        # transfer remains a direct S1C33 jump instead of falling through the
        # old control trap.  ELF symbol strings disappear from the flat KF2;
        # this adds no executable bytes.
        entries.update(record[2] for record in records)
        for owner, body in bodies.items():
            aliases[owner].update(record[2] for record in body)
        return entries, bodies, aliases

    successors: dict[int, tuple[int, ...]] = {}
    predecessors: Counter[int] = Counter()
    adjacency: defaultdict[int, set[int]] = defaultdict(set)
    for offset in remaining:
        targets = tuple(
            target
            for target in frontend.block_successors(game, record_by_offset[offset])
            if target in remaining
        )
        successors[offset] = targets
        for target in targets:
            predecessors[target] += 1
            adjacency[offset].add(target)
            adjacency[target].add(offset)

    visited: set[int] = set()
    for start in sorted(remaining):
        if start in visited:
            continue
        pending = [start]
        component: set[int] = set()
        visited.add(start)
        while pending:
            offset = pending.pop()
            component.add(offset)
            for target in adjacency[offset]:
                if target not in visited:
                    visited.add(target)
                    pending.append(target)
        roots = {offset for offset in component if predecessors[offset] == 0}
        if not roots:
            roots = {min(component)}
        primary = min(roots)
        bodies[primary] = [record_by_offset[item] for item in sorted(component)]
        aliases[primary] = roots
        entries.update(roots)
    entries.update(record[2] for record in records)
    for owner, body in bodies.items():
        aliases[owner].update(record[2] for record in body)
    return entries, bodies, aliases


def compile_semantic_outlines(
    clang: str,
    objcopy: str,
    output: Path,
    outlines: dict[str, str],
) -> dict[str, object]:
    section = ".text.c6502_outlines"
    lines = [
        "/* Generated C6502 semantic outlines; no opcode dispatcher. */",
        f'    .section "{section}","ax",@progbits',
    ]
    for phrase, symbol in sorted(outlines.items(), key=lambda item: item[1]):
        lines.extend(
            [
                "    .p2align 1",
                f"    .globl {symbol}",
                f"    .type {symbol},@function",
                f"{symbol}:",
                *emit_semantic_phrase(phrase),
                "    ret",
                f"    .size {symbol}, .-{symbol}",
                "",
            ]
        )
    s_path = output / "c6502_semantic_outlines.S"
    o_path = output / "c6502_semantic_outlines.o"
    b_path = output / "c6502_semantic_outlines.bin"
    s_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(
        [clang, "--target=s1c33-none-elf", "-c", str(s_path), "-o", str(o_path)],
        check=True,
    )
    subprocess.run(
        [objcopy, "-O", "binary", f"--only-section={section}", str(o_path), str(b_path)],
        check=True,
    )
    return {
        "functions": len(outlines),
        "native_bytes": b_path.stat().st_size,
        "object": str(o_path),
    }


def compile_resource_image(
    clang: str,
    output: Path,
    game: bytes,
) -> dict[str, object]:
    """Compress the exact GAM image and wrap it in a linkable ELF section."""

    packed = c6502_lzss.compress(game)
    if c6502_lzss.decompress(packed, len(game)) != game:
        raise RuntimeError("internal LZSS resource verification failed")
    packed_path = output / "c6502_game_image.lzss"
    source_path = output / "c6502_game_image.S"
    object_path = output / "c6502_game_image.o"
    packed_path.write_bytes(packed)
    include_path = packed_path.resolve().as_posix().replace('"', '\\"')
    source_path.write_text(
        "\n".join(
            [
                "/* Exact original GAM bytes, compressed as non-executable data. */",
                '    .section ".rodata.c6502_game_image","a",@progbits',
                "    .p2align 2",
                "    .globl c6502_game_image_lzss_start",
                "c6502_game_image_lzss_start:",
                f'    .incbin "{include_path}"',
                "    .globl c6502_game_image_lzss_end",
                "c6502_game_image_lzss_end:",
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [clang, "--target=s1c33-none-elf", "-c", str(source_path), "-o", str(object_path)],
        check=True,
    )
    return {
        "raw_bytes": len(game),
        "packed_bytes": len(packed),
        "object": str(object_path),
    }


def compile_boot_snapshot(
    clang: str,
    output: Path,
    game_path: Path,
    rom8: Path,
    rome: Path,
) -> dict[str, object]:
    """Export the firmware-prepared entry state and embed it compactly.

    The reference firmware runs only on the PC at build time.  The KF2 starts
    from this RAM/register/bank snapshot and never contains or executes either
    6502 firmware image.
    """

    raw_path = output / "c6502_boot_snapshot.bin"
    packed_path = output / "c6502_boot_snapshot.lzss"
    source_path = output / "c6502_boot_snapshot.S"
    object_path = output / "c6502_boot_snapshot.o"
    boot_export.export_snapshot(game_path, raw_path, rom8, rome)
    raw = raw_path.read_bytes()
    packed = c6502_lzss.compress(raw)
    if c6502_lzss.decompress(packed, len(raw)) != raw:
        raise RuntimeError("internal boot snapshot compression verification failed")
    packed_path.write_bytes(packed)
    include_path = packed_path.resolve().as_posix().replace('"', '\\"')
    source_path.write_text(
        "\n".join(
            [
                "/* PC-exported 6502 firmware boot state; data only. */",
                '    .section ".rodata.c6502_boot_snapshot","a",@progbits',
                "    .p2align 2",
                "    .globl c6502_boot_snapshot_lzss_start",
                "c6502_boot_snapshot_lzss_start:",
                f'    .incbin "{include_path}"',
                "    .globl c6502_boot_snapshot_lzss_end",
                "c6502_boot_snapshot_lzss_end:",
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [clang, "--target=s1c33-none-elf", "-c", str(source_path), "-o", str(object_path)],
        check=True,
    )
    return {
        "raw_bytes": len(raw),
        "packed_bytes": len(packed),
        "object": str(object_path),
    }


def indirect_target_working_set(game, records, emitted_entries, modules):
    """Keep source-language indirect targets, not every sequential block.

    A game with a genuine unknown function pointer keeps the conservative
    complete map.  When switches are its only indirect transfers, their
    linked descriptors provide the exact complete target set at PC compile
    time.  This is metadata elimination, not a runtime cache or fallback.
    """
    for module in modules:
        if any(
            "indirect_call" in key or "banked_function_call" in key for key in module["call_kinds"]
        ):
            return set(emitted_entries), "conservative-function-pointers"
    targets = set()
    for record in records:
        jump = record[2] + record[3] - 3
        if game[jump : jump + 3] == b"\x4c\x5c\xdb":
            found = native.game_switch_targets(game, jump)
            if found is None:
                raise ValueError(f"unresolved switch at GAM+0x{jump:x}")
            targets.update(found)
    if not targets.issubset(emitted_entries):
        missing = sorted(targets - set(emitted_entries))
        raise ValueError(f"native switch targets were not emitted: {missing}")
    return targets, "statically-linked-switch-targets"


def compile_dispatch_table(
    clang: str,
    output: Path,
    offsets: Iterable[int],
) -> dict[str, object]:
    """Create a compact physical-block -> native-address lookup table.

    This is used only by source-language indirect control flow such as C
    switch statements.  It dispatches already translated native blocks; it is
    not an opcode/PC interpreter.  Offsets and pointers are split into aligned
    arrays, costing six bytes per recovered block.
    """

    # Only publish labels that survived semantic call-transaction fusion.
    # Interior argument-transport blocks have one sequential predecessor and
    # can never be a legal indirect C target.  Including every recovered
    # basic block here created references to intentionally folded labels.
    ordered = sorted(set(offsets))
    bank_starts: list[int] = []
    cursor = 0
    for bank in range((ordered[-1] // GAME_BANK_SIZE) + 2 if ordered else 1):
        while cursor < len(ordered) and ordered[cursor] // GAME_BANK_SIZE < bank:
            cursor += 1
        bank_starts.append(cursor)
    lines = [
        "/* Native block lookup for dynamic C switch/callback targets. */",
        '    .section ".rodata.c6502_dispatch","a",@progbits',
        "    .p2align 2",
        "    .globl c6502_dispatch_bank_starts",
        "c6502_dispatch_bank_starts:",
        *(f"    .short {value}" for value in bank_starts),
        "    .globl c6502_dispatch_bank_starts_end",
        "c6502_dispatch_bank_starts_end:",
        "    .globl c6502_dispatch_offsets",
        "c6502_dispatch_offsets:",
        *(f"    .short 0x{value % GAME_BANK_SIZE:04x}" for value in ordered),
        "    .p2align 2",
        "    .globl c6502_dispatch_targets",
        "c6502_dispatch_targets:",
        *(f"    .long {functions.function_name(value)}" for value in ordered),
        "    .globl c6502_dispatch_targets_end",
        "c6502_dispatch_targets_end:",
        "",
    ]
    source_path = output / "c6502_dispatch_table.S"
    object_path = output / "c6502_dispatch_table.o"
    source_path.write_text("\n".join(lines), encoding="utf-8")
    subprocess.run(
        [clang, "--target=s1c33-none-elf", "-c", str(source_path), "-o", str(object_path)],
        check=True,
    )
    # The section contains 16-bit bank starts, 16-bit offsets and aligned
    # 32-bit target pointers.  The final linked size is deterministic.
    raw_bytes = len(bank_starts) * 2 + len(ordered) * 6
    raw_bytes = (raw_bytes + 3) & ~3
    return {
        "entries": len(ordered),
        "banks": max(0, len(bank_starts) - 1),
        "bytes": raw_bytes,
        "object": str(object_path),
    }


ARG_PUSH_RUNTIME = {
    0xDAAA: ("char", 1),
    0xDACA: ("int", 2),
}


def immediate_argument(
    instructions: list[native.aotgen.InstructionIR],
    kind: str,
) -> int | None:
    """Recover a literal source argument, not its 6502 transport sequence."""

    body = instructions[:-1]
    if kind == "char" and len(body) == 1 and body[0].data[0] == 0xA9:
        return body[0].data[1]
    if kind == "int":
        phrase = semantic._semantic_peephole(body, 0) if body else None
        if phrase is None or phrase[1] != len(body):
            return None
        match = re.fullmatch(r"C6502_STORE16_IMM\(0x20u, 0x([0-9a-f]+)u\);", phrase[0])
        if match is not None:
            return int(match.group(1), 16)
    return None


def native_call_transaction(
    game: bytes,
    code_size: int,
    records: list[tuple[int, ...]],
    start: int,
    predecessor_counts: Counter[int],
    entries: set[int],
    firmware_table: dict[int, str],
    direct_symbols: dict[int, str],
) -> dict[str, object] | None:
    """Recognize literal arguments + compiler push helpers + one API call.

    The old machine sequence only implements a C call.  Emit each recovered
    source expression once into R0..R3 and call the 9288 adapter directly;
    literal expressions need no guest-state materialization at all.
    """

    arguments: list[dict[str, object]] = []
    widths: list[int] = []
    index = start
    while index < len(records) and len(arguments) < 4:
        record = records[index]
        instructions = frontend.decode_record(game, record)
        terminal = instructions[-1]
        if terminal.data[0] != 0x20:
            break
        target_pc = terminal.data[1] | terminal.data[2] << 8
        pushed = ARG_PUSH_RUNTIME.get(target_pc)
        if pushed is None:
            break
        kind, width = pushed
        value = immediate_argument(instructions, kind)
        arguments.append(
            {
                "record_index": index,
                "kind": kind,
                "value": value,
            }
        )
        widths.append(width)
        next_offset = record[2] + record[3]
        index += 1
        if (
            index >= len(records)
            or records[index][2] != next_offset
            or predecessor_counts[next_offset] != 1
        ):
            return None

    if not arguments or index >= len(records):
        return None
    call_record = records[index]
    call_instructions = frontend.decode_record(game, call_record)
    table = functions.far_call_table(call_instructions)
    api: str | None = None
    if table is not None and len(call_instructions) == 5:
        if functions.far_game_target(game, code_size, table) in entries:
            return None
        api = firmware_table.get(table)
    elif len(call_instructions) == 1 and call_instructions[0].data[0] == 0x20:
        target_pc = call_instructions[0].data[1] | call_instructions[0].data[2] << 8
        target = frontend.physical_target(call_record, target_pc)
        if target is not None and target in entries:
            return None
        api = direct_symbols.get(target_pc)
    if api is None:
        return None

    cleanup_index = index + 1
    next_offset = call_record[2] + call_record[3]
    if (
        cleanup_index >= len(records)
        or records[cleanup_index][2] != next_offset
        or predecessor_counts[next_offset] != 1
    ):
        return None
    cleanup_instructions = frontend.decode_record(game, records[cleanup_index])
    cleanup = semantic._semantic_peephole(cleanup_instructions, 0)
    if cleanup is None:
        return None
    total = sum(widths)
    if cleanup[0] != f"C6502_ADD16_PRESERVE(0x28u, 0x28u, 0x{total:04x}u);":
        return None
    return {
        "arguments": arguments,
        "widths": widths,
        "api": api,
        "last_call_index": index,
        "cleanup_offset": next_offset,
        "cleanup_instructions": cleanup[1],
    }


def emit_transaction_argument(
    game: bytes,
    record: tuple[int, ...],
    argument_index: int,
    kind: str,
    immediate_value: int | None,
    outlines: dict[str, str],
) -> list[str]:
    """Lower one recovered source argument into native ABI R0..R3."""

    destination = f"r{argument_index}"
    # Preserve the expression's register effects too.  C6502 can reuse an
    # operand register across successive argument expressions, even when the
    # first expression happens to be a literal.
    instructions = frontend.decode_record(game, record)
    body_end = len(instructions) - 1
    result: list[str] = []
    index = 0
    while index < body_end:
        phrase = semantic._semantic_peephole(instructions, index)
        if phrase is not None and index + phrase[1] <= body_end:
            outlined = outlines.get(phrase[0])
            if outlined is not None:
                result.append(f"    call {outlined}")
            else:
                result.extend(emit_semantic_phrase(phrase[0]))
            index += phrase[1]
            continue
        result.extend(emit_instruction(instructions[index]))
        index += 1

    if kind == "char":
        result.extend([f"    ld.ub %{destination}, %r4", "    ld.w %r5, %r4", "    ld.w %r6, 0"])
        return result
    if kind == "int":
        result.extend(ext_prefix(0x20))
        result.append(f"    ld.ub %{destination}, [%r14]")
        result.extend(ext_prefix(0x21))
        result.extend(
            [
                "    ld.ub %r13, [%r14]",
                "    ld.w %r4, %r13",
                "    sll %r13, 8",
                f"    or %{destination}, %r13",
                f"    ld.uh %{destination}, %{destination}",
                "    ld.ub %r4, %r4",
                "    ld.w %r6, 1",
            ]
        )
        return result
    raise ValueError(kind)


def emit_rmw_helper(
    name: str, address: int, live_writes: int, indexed_x: bool = False
) -> list[str]:
    result = imm("ld.w", "r12", address)
    if indexed_x:
        result.extend(["    add %r12, %r5", "    ld.uh %r12, %r12"])
    result.append(f"    call c6502_sem_{name}")
    if live_writes & (FLAG_N | FLAG_Z):
        result.append("    ld.ub %r8, %r13")
    return result


def emit_alu_value(name: str, value_lines: list[str], live_writes: int) -> list[str]:
    result = list(value_lines)
    if name == "and":
        result.extend(["    and %r4, %r12", "    ld.ub %r4, %r4"])
        result.extend(set_lazy_nz("r4", live_writes))
    elif name == "ora":
        result.extend(["    or %r4, %r12", "    ld.ub %r4, %r4"])
        result.extend(set_lazy_nz("r4", live_writes))
    elif name == "eor":
        result.extend(["    xor %r4, %r12", "    ld.ub %r4, %r4"])
        result.extend(set_lazy_nz("r4", live_writes))
    elif name in ("adc", "sbc"):
        result.append(f"    call c6502_sem_{name}8")
    else:
        raise ValueError(name)
    return result


def emit_compare(register: str, value_lines: list[str]) -> list[str]:
    result = list(value_lines)
    result.append(f"    ld.w %r13, %{register}")
    result.append("    call c6502_sem_cmp8")
    return result


def emit_instruction(ir: native.aotgen.InstructionIR) -> list[str]:
    data = ir.data
    opcode = data[0]
    byte = data[1] if len(data) > 1 else 0
    word = byte | (data[2] << 8) if len(data) > 2 else 0
    live = int(ir.live_writes)

    if opcode in (0xA9, 0xA2, 0xA0):
        register = {0xA9: "r4", 0xA2: "r5", 0xA0: "r6"}[opcode]
        result = imm("ld.w", register, byte)
        return result + set_lazy_nz(register, live)
    if opcode in (0xA5, 0xA6, 0xA4, 0xAD, 0xAE, 0xAC):
        register = {0xA5: "r4", 0xA6: "r5", 0xA4: "r6", 0xAD: "r4", 0xAE: "r5", 0xAC: "r6"}[opcode]
        address = byte if len(data) == 2 else word
        result = load_memory(address, register)
        return result + set_lazy_nz(register, live)
    if opcode == 0xB5:
        result = imm("ld.w", "r12", byte)
        result.extend(
            [
                "    add %r12, %r5",
                "    ld.ub %r12, %r12",
                "    add %r12, %r14",
                "    ld.ub %r4, [%r12]",
            ]
        )
        return result + set_lazy_nz("r4", live)
    if opcode in (0xBD, 0xB9):
        register = "r5" if opcode == 0xBD else "r6"
        result = indexed_absolute_address(word, register)
        result.append("    call c6502_direct_read8")
        result.append("    ld.w %r4, %r12")
        return result + set_lazy_nz("r4", live)
    if opcode == 0xB1:
        result = read_indirect_y(byte, "r4")
        return result + set_lazy_nz("r4", live)

    if opcode in (0x85, 0x86, 0x84, 0x8D, 0x8E, 0x8C):
        register = {0x85: "r4", 0x86: "r5", 0x84: "r6", 0x8D: "r4", 0x8E: "r5", 0x8C: "r6"}[opcode]
        address = byte if len(data) == 2 else word
        return store_memory(address, register)
    if opcode in (0x9D, 0x99):
        index_register = "r5" if opcode == 0x9D else "r6"
        result = indexed_absolute_address(word, index_register)
        result.extend(["    ld.w %r13, %r4", "    call c6502_direct_write8"])
        return result
    if opcode == 0x95:
        result = imm("ld.w", "r12", byte)
        result.extend(
            [
                "    add %r12, %r5",
                "    ld.ub %r12, %r12",
                "    add %r12, %r14",
                "    ld.b [%r12], %r4",
            ]
        )
        return result
    if opcode == 0x91:
        return write_indirect_y(byte, "r4")

    immediate_alu = {0x09: "ora", 0x29: "and", 0x49: "eor", 0x69: "adc", 0xE9: "sbc"}
    zp_alu = {0x05: "ora", 0x25: "and", 0x45: "eor", 0x65: "adc", 0xE5: "sbc"}
    abs_alu = {0x0D: "ora", 0x2D: "and", 0x6D: "adc", 0xED: "sbc"}
    indy_alu = {0x11: "ora", 0x31: "and", 0x51: "eor", 0x71: "adc", 0xF1: "sbc"}
    if opcode in immediate_alu:
        return emit_alu_value(immediate_alu[opcode], imm("ld.w", "r12", byte), live)
    if opcode in zp_alu:
        return emit_alu_value(zp_alu[opcode], load_memory(byte, "r12"), live)
    if opcode in abs_alu:
        return emit_alu_value(abs_alu[opcode], load_memory(word, "r12"), live)
    if opcode in indy_alu:
        return emit_alu_value(indy_alu[opcode], read_indirect_y(byte, "r12"), live)
    if opcode == 0x1D:
        value = indexed_absolute_address(word, "r5") + ["    call c6502_direct_read8"]
        return emit_alu_value("ora", value, live)

    if opcode in (0xC9, 0xC0, 0xE0):
        register = {0xC9: "r4", 0xC0: "r6", 0xE0: "r5"}[opcode]
        return emit_compare(register, imm("ld.w", "r12", byte))
    if opcode in (0xC5, 0xC4, 0xCD, 0xEC):
        register = {0xC5: "r4", 0xC4: "r6", 0xCD: "r4", 0xEC: "r5"}[opcode]
        address = byte if len(data) == 2 else word
        return emit_compare(register, load_memory(address, "r12"))

    if opcode in (0x18, 0x38, 0x78):
        if opcode == 0x18:
            return clear_status(0xFE)
        if opcode == 0x38:
            return ["    or %r9, 1"]
        return ["    or %r9, 4"]
    if opcode in (0xAA, 0xA8, 0x8A, 0x98, 0xBA):
        destination, source = {
            0xAA: ("r5", "r4"),
            0xA8: ("r6", "r4"),
            0x8A: ("r4", "r5"),
            0x98: ("r4", "r6"),
            0xBA: ("r5", "r7"),
        }[opcode]
        result = [f"    ld.w %{destination}, %{source}"]
        return result + set_lazy_nz(destination, live)
    if opcode == 0x9A:
        return ["    ld.w %r7, %r5"]
    if opcode in (0xC8, 0x88, 0xE8, 0xCA):
        register, operation = {
            0xC8: ("r6", "add"),
            0x88: ("r6", "sub"),
            0xE8: ("r5", "add"),
            0xCA: ("r5", "sub"),
        }[opcode]
        result = [f"    {operation} %{register}, 1", f"    ld.ub %{register}, %{register}"]
        return result + set_lazy_nz(register, live)

    if opcode in (0x48, 0x08):
        result: list[str] = []
        source = "r4"
        if opcode == 0x08:
            result.append("    call c6502_sem_materialize_nz")
            result.append("    ld.w %r13, %r9")
            result.extend(imm("or", "r13", 0x30))
            source = "r13"
        result.extend(ram_pointer(0x100, "r12"))
        result.extend(
            [
                "    add %r12, %r7",
                f"    ld.b [%r12], %{source}",
                "    sub %r7, 1",
                "    ld.ub %r7, %r7",
            ]
        )
        return result
    if opcode in (0x68, 0x28):
        result = ["    add %r7, 1", "    ld.ub %r7, %r7"]
        result.extend(ram_pointer(0x100, "r12"))
        result.extend(["    add %r12, %r7", "    ld.ub %r12, [%r12]"])
        if opcode == 0x68:
            result.append("    ld.w %r4, %r12")
            result.extend(set_lazy_nz("r4", live))
        else:
            result.extend(imm("or", "r12", 0x30))
            result.extend(["    ld.ub %r9, %r12", "    call c6502_sem_status_to_nz"])
        return result

    if opcode in (0x0A, 0x2A, 0x4A, 0x6A):
        helper = {0x0A: "asl_a", 0x2A: "rol_a", 0x4A: "lsr_a", 0x6A: "ror_a"}[opcode]
        return [f"    call c6502_sem_{helper}"]
    rmw = {
        0x06: ("asl_m", False),
        0x0E: ("asl_m", False),
        0x1E: ("asl_m", True),
        0x26: ("rol_m", False),
        0x2E: ("rol_m", False),
        0x3E: ("rol_m", True),
        0x46: ("lsr_m", False),
        0x4E: ("lsr_m", False),
        0x66: ("ror_m", False),
        0x6E: ("ror_m", False),
        0xC6: ("dec_m", False),
        0xCE: ("dec_m", False),
        0xDE: ("dec_m", True),
        0xE6: ("inc_m", False),
        0xEE: ("inc_m", False),
    }
    if opcode in rmw:
        name, indexed = rmw[opcode]
        address = byte if len(data) == 2 else word
        return emit_rmw_helper(name, address, live, indexed)
    if opcode == 0x76:
        result = imm("ld.w", "r12", byte)
        result.extend(["    add %r12, %r5", "    ld.ub %r12, %r12"])
        result.append("    call c6502_sem_ror_m")
        if live & (FLAG_N | FLAG_Z):
            result.append("    ld.ub %r8, %r13")
        return result
    if opcode == 0xEA:
        return []
    raise ValueError(f"unsupported non-control opcode 0x{opcode:02x} at 0x{ir.pc:04x}")


def condition_lines(
    opcode: int,
    unique: str,
    target: str,
    fallthrough: str,
    fallthrough_is_next: bool,
) -> list[str]:
    take_when_set = opcode in (0x30, 0x70, 0xB0, 0xF0)
    flag = {
        0x10: FLAG_N,
        0x30: FLAG_N,
        0x50: FLAG_V,
        0x70: FLAG_V,
        0x90: FLAG_C,
        0xB0: FLAG_C,
        0xD0: FLAG_Z,
        0xF0: FLAG_Z,
    }[opcode]
    result: list[str] = []
    if flag == FLAG_Z:
        # R8 is always the byte that produced the current guest N/Z pair.
        result.extend(
            [
                "    cmp %r8, 0",
                f"    {'jreq' if take_when_set else 'jrne'} .Ltake_{unique}",
            ]
        )
    elif flag == FLAG_N:
        result.extend(["    ld.w %r12, %r8"] + imm("and", "r12", FLAG_N))
        result.extend(
            [
                "    cmp %r12, 0",
                f"    {'jrne' if take_when_set else 'jreq'} .Ltake_{unique}",
            ]
        )
    else:
        result.extend(["    ld.w %r12, %r9"] + imm("and", "r12", flag))
        result.extend(
            [
                "    cmp %r12, 0",
                f"    {'jrne' if take_when_set else 'jreq'} .Ltake_{unique}",
            ]
        )
    result.append(f".Lnot_taken_{unique}:")
    result.append(
        f"    jp .Lfallthrough_{unique}" if fallthrough_is_next else f"    jp {fallthrough}"
    )
    result.extend([f".Ltake_{unique}:", f"    jp {target}"])
    if fallthrough_is_next:
        result.append(f".Lfallthrough_{unique}:")
    return result


def emit_lifted_runtime_call(api: str) -> list[str] | None:
    """Inline compiler ABI transport that has no source-level call meaning."""

    if api == "store_char_funct_arg":
        # __store_char_funct_arg: *--software_sp=A; X=A; Y=0.  PHP/SEI/PLP
        # only protected the two-byte pointer update in the 6502 runtime.
        return [
            "    sub %r10, 1",
            "    ld.uh %r10, %r10",
            "    ld.w %r12, %r14",
            "    add %r12, %r10",
            "    ld.b [%r12], %r4",
            "    ld.w %r5, %r4",
            "    ld.w %r6, 0",
        ]
    if api == "store_int_funct_arg":
        # __store_int_funct_arg: push OPER1 ($20/$21), leaving A=high,Y=1.
        result = ["    sub %r10, 2", "    ld.uh %r10, %r10"]
        result.extend(ext_prefix(0x20))
        result.append("    ld.ub %r12, [%r14]")
        result.extend(["    ld.w %r13, %r14", "    add %r13, %r10", "    ld.b [%r13], %r12"])
        result.extend(ext_prefix(0x21))
        result.append("    ld.ub %r4, [%r14]")
        result.extend(["    add %r13, 1", "    ld.b [%r13], %r4", "    ld.w %r6, 1"])
        return result
    return None


def transfer_label(target: int | None, local: set[int], entries: set[int]) -> str:
    if target is None:
        return "c6502_native_trap_control"
    if target in local:
        return f".Lblock_{target:05x}"
    if target in entries:
        return functions.function_name(target)
    return "c6502_native_trap_control"


def emit_transfer(
    target: int | None, local: set[int], entries: set[int], next_record: int | None
) -> list[str]:
    if target is not None and target == next_record:
        return []
    return [f"    jp {transfer_label(target, local, entries)}"]


def emit_function(
    game: bytes,
    code_size: int,
    entry: int,
    records: list[tuple[int, ...]],
    entries: set[int],
    runtime_symbols: dict[int, str],
    firmware_table: dict[int, str],
    direct_symbols: dict[int, str],
    outlines: dict[str, str],
    aliases: set[int],
) -> tuple[list[str], Counter[str]]:
    local = {record[2] for record in records}
    predecessor_counts: Counter[int] = Counter()
    for record in records:
        for successor in frontend.block_successors(game, record):
            if successor in local:
                predecessor_counts[successor] += 1
    skipped_prefixes: dict[int, int] = {}
    calls: Counter[str] = Counter()
    name = functions.function_name(entry)
    lines = ["    .p2align 1", f"    .globl {name}", f"    .type {name},@function", f"{name}:"]
    if records and records[0][2] != entry:
        lines.append(f"    jp .Lblock_{entry:05x}")
    record_index = 0
    while record_index < len(records):
        transaction = native_call_transaction(
            game,
            code_size,
            records,
            record_index,
            predecessor_counts,
            entries,
            firmware_table,
            direct_symbols,
        )
        if transaction is not None:
            record = records[record_index]
            if record[2] in aliases and record[2] != entry:
                alias = functions.function_name(record[2])
                lines.extend(
                    [
                        f"    .globl {alias}",
                        f"    .type {alias},@function",
                        f"{alias}:",
                    ]
                )
            lines.append(f".Lblock_{record[2]:05x}:")
            for argument_index, argument in enumerate(transaction["arguments"]):
                argument_record = records[int(argument["record_index"])]
                value = argument["value"]
                lines.extend(
                    emit_transaction_argument(
                        game,
                        argument_record,
                        len(transaction["arguments"]) - 1 - argument_index,
                        str(argument["kind"]),
                        None if value is None else int(value),
                        outlines,
                    )
                )
                # Arguments are evaluated right-to-left.  Later expressions
                # address local variables relative to the already-adjusted
                # software SP.  Removing these pushes without rebasing those
                # expressions read the wrong locals.  Keep the tiny native
                # stores and the original cleanup; only eliminate the runtime
                # transport calls, not their observable stack layout.
                arg_reg = len(transaction["arguments"]) - 1 - argument_index
                width = int(transaction["widths"][argument_index])
                lines.extend(
                    [
                        f"    sub %r10, {width}",
                        "    ld.uh %r10, %r10",
                        "    ld.w %r12, %r14",
                        "    add %r12, %r10",
                        f"    ld.b [%r12], %r{arg_reg}",
                    ]
                )
                if width == 2:
                    lines.extend(
                        [
                            f"    ld.w %r13, %r{arg_reg}",
                            "    srl %r13, 8",
                            "    add %r12, 1",
                            "    ld.b [%r12], %r13",
                        ]
                    )
            api = str(transaction["api"])
            # Recovered source-order arguments also live in R0..R3.  Keep
            # a distinct native symbol so the 9288 adapter never has to guess
            # which ABI a call site used.
            lines.append(f"    call c6502_adapter_{symbol_name(api)}_direct")
            calls[f"firmware:{api}"] += 1
            calls["lifted_call_transaction"] += 1
            calls["lifted_call_arguments"] += len(transaction["arguments"])
            record_index = int(transaction["last_call_index"]) + 1
            continue

        current_index = record_index
        record = records[current_index]
        record_index += 1
        next_record = records[current_index + 1][2] if current_index + 1 < len(records) else None
        instructions = frontend.decode_record(game, record)
        terminal = instructions[-1]
        opcode = terminal.data[0]
        next_offset = record[2] + record[3]
        if record[2] in aliases and record[2] != entry:
            alias = functions.function_name(record[2])
            lines.extend(
                [
                    f"    .globl {alias}",
                    f"    .type {alias},@function",
                    f"{alias}:",
                ]
            )
        lines.append(f".Lblock_{record[2]:05x}:")
        table = functions.far_call_table(instructions)
        terminal_is_control = opcode in native.aotgen.TERMINATORS
        body_end = len(instructions) - (5 if table is not None else 1 if terminal_is_control else 0)
        index = skipped_prefixes.get(record[2], 0)
        while index < body_end:
            phrase = semantic._semantic_peephole(instructions, index)
            if phrase is not None and index + phrase[1] <= body_end:
                outlined = outlines.get(phrase[0])
                if outlined is not None:
                    lines.append(f"    call {outlined}")
                    calls["semantic_outlined"] += 1
                else:
                    lines.extend(emit_semantic_phrase(phrase[0]))
                calls[f"semantic:{phrase[0].split('(', 1)[0]}"] += 1
                index += phrase[1]
                continue
            lines.extend(emit_instruction(instructions[index]))
            index += 1

        if table is not None:
            target = functions.far_game_target(game, code_size, table)
            if target is not None and target in entries:
                lines.append(f"    call .Lc6502_far_{target:05x}")
                calls["game_far"] += 1
            else:
                # A descriptor whose target/bank bytes are the compiler's
                # $ff sentinel is an optional callback, not a new firmware
                # API named after the table address.  Keep it explicit and
                # deterministic without inventing a game-specific bridge.
                api = firmware_table.get(table, "invalid_far_call")
                lines.append(f"    call c6502_adapter_{symbol_name(api)}")
                calls[f"firmware:{api}"] += 1
            lines.extend(emit_transfer(next_offset, local, entries, next_record))
            continue

        if not terminal_is_control:
            lines.extend(emit_transfer(next_offset, local, entries, next_record))
            continue

        if opcode == 0x20:
            target_pc = terminal.data[1] | terminal.data[2] << 8
            target = frontend.physical_target(record, target_pc)
            if target is not None and target in entries:
                callee = functions.function_name(target)
                calls["game_direct"] += 1
            elif target_pc in runtime_symbols:
                api = runtime_symbols[target_pc]
                lifted = emit_lifted_runtime_call(api)
                if lifted is not None:
                    lines.extend(lifted)
                    calls[f"lifted_runtime:{api}"] += 1
                    lines.extend(emit_transfer(next_offset, local, entries, next_record))
                    continue
                callee = f"c6502_runtime_{symbol_name(api)}"
                calls[f"runtime:{api}"] += 1
            else:
                api = direct_symbols.get(target_pc, f"direct_{target_pc:04x}")
                callee = f"c6502_adapter_{symbol_name(api)}"
                calls[f"firmware:{api}"] += 1
            lines.append(f"    call {callee}")
            lines.extend(emit_transfer(next_offset, local, entries, next_record))
            continue
        if opcode in native.aotgen.BRANCH_FLAG_READS:
            target_pc = native.aotgen.branch_target(terminal.pc, terminal.data[1])
            target = frontend.physical_target(record, target_pc)
            lines.extend(
                condition_lines(
                    opcode,
                    f"{record[2]:05x}",
                    transfer_label(target, local, entries),
                    transfer_label(next_offset, local, entries),
                    next_offset == next_record,
                )
            )
            continue
        if opcode in (0x4C, 0x80):
            target_pc = (
                (terminal.data[1] | terminal.data[2] << 8)
                if opcode == 0x4C
                else native.aotgen.branch_target(terminal.pc, terminal.data[1])
            )
            target = frontend.physical_target(record, target_pc)
            if target is not None:
                lines.extend(emit_transfer(target, local, entries, next_record))
            elif opcode == 0x4C and target_pc in runtime_symbols:
                # C6502 lowers switch statements to a tail jump into
                # __switch_comparison.  Preserve the tail-call shape so the
                # selected native case target returns to the original caller.
                api = runtime_symbols[target_pc]
                if (
                    api == "switch_comparison"
                    and native.game_switch_targets(game, record[2] + record[3] - 3) is None
                ):
                    raise ValueError(f"unresolved C6502 switch descriptor at GAM+0x{record[2]:x}")
                lines.append(f"    jp c6502_runtime_{symbol_name(api)}")
                calls[f"runtime_tail:{api}"] += 1
            elif opcode == 0x4C and target_pc in direct_symbols:
                api = direct_symbols[target_pc]
                lines.append(f"    jp c6502_adapter_{symbol_name(api)}")
                calls[f"firmware_tail:{api}"] += 1
            else:
                lines.append("    jp c6502_native_trap_control")
            continue
        if opcode == 0x60:
            lines.append("    ret")
            continue
        if opcode == 0x40:
            lines.extend(["    call c6502_adapter_rti", "    ret"])
            calls["firmware:rti"] += 1
            continue
        raise ValueError(f"unsupported control opcode 0x{opcode:02x}")
    lines.extend([f"    .size {name}, .-{name}", ""])
    return lines, calls


def runtime_symbols(map_path: Path) -> dict[int, str]:
    symbols = frontend.symbols_by_address(map_path)
    result: dict[int, str] = {}
    for address, name in symbols.items():
        if RUNTIME_FIRST <= address <= RUNTIME_LAST:
            result[address] = name.lower().lstrip("_")
    return result


def compile_bank(
    clang: str,
    objcopy: str,
    output: Path,
    bank: int,
    game: bytes,
    code_size: int,
    entries: set[int],
    records: list[tuple[int, list[tuple[int, ...]]]],
    runtime: dict[int, str],
    firmware: dict[int, str],
    direct: dict[int, str],
    outlines: dict[str, str],
    aliases: dict[int, set[int]],
) -> dict[str, object]:
    section = f".text.c6502_direct_{bank:02d}"
    lines = [
        "/* Generated direct S1C33; no guest opcode dispatcher. */",
        f'    .section "{section}","ax",@progbits',
    ]
    calls: Counter[str] = Counter()
    for entry, body in records:
        body_lines, body_calls = emit_function(
            game,
            code_size,
            entry,
            body,
            entries,
            runtime,
            firmware,
            direct,
            outlines,
            aliases.get(entry, {entry}),
        )
        lines.extend(body_lines)
        calls.update(body_calls)
    # Native direct control flow removes the firmware's bank-call dispatcher,
    # but not its observable data-window semantics.  Save/restore the caller's
    # code window once per FAR call; constants in $5000-$8fff then address the
    # correct game's native function bank.  This is a native linkage thunk,
    # not a guest opcode dispatcher or interpreter fallback.
    far_targets = sorted(
        {
            int(match.group(1), 16)
            for line in lines
            if (match := re.fullmatch(r"    call \.Lc6502_far_([0-9a-f]+)", line))
        }
    )
    for target in far_targets:
        lines.extend([f".Lc6502_far_{target:05x}:", "    pushn %r0"])
        lines.extend(imm("ld.w", "r11", 0x20D + (target // GAME_BANK_SIZE) * 4))
        lines.extend(
            [
                "    call c6502_native_set_codebank",
                "    ld.w %r0, %r11",
                "    pushn %r0",
                f"    call {functions.function_name(target)}",
                "    popn %r0",
                "    ld.w %r11, %r0",
                "    call c6502_native_set_codebank",
                "    popn %r0",
                "    ret",
            ]
        )
    s_path = output / f"c6502_direct_bank_{bank:02d}.S"
    o_path = output / f"c6502_direct_bank_{bank:02d}.o"
    b_path = output / f"c6502_direct_bank_{bank:02d}.bin"
    s_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(
        [clang, "--target=s1c33-none-elf", "-c", str(s_path), "-o", str(o_path)], check=True
    )
    subprocess.run(
        [objcopy, "-O", "binary", f"--only-section={section}", str(o_path), str(b_path)], check=True
    )
    return {
        "bank": bank,
        "functions": len(records),
        "guest_blocks": sum(len(body) for _entry, body in records),
        "guest_bytes": sum(record[3] for _entry, body in records for record in body),
        "guest_instructions": sum(record[4] for _entry, body in records for record in body),
        "native_bytes": b_path.stat().st_size,
        "native_call_sites": sum(
            value for key, value in calls.items() if not key.startswith("lifted_")
        ),
        "lifted_runtime_calls": sum(
            value for key, value in calls.items() if key.startswith("lifted_runtime:")
        ),
        "lifted_call_transactions": calls["lifted_call_transaction"],
        "lifted_call_arguments": calls["lifted_call_arguments"],
        "call_kinds": dict(calls),
        "object": str(o_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    parser.add_argument("--clang", required=True)
    parser.add_argument("--objcopy", required=True)
    parser.add_argument("--map", type=Path, default=frontend.DEFAULT_MAP)
    parser.add_argument("--rom8", type=Path, default=boot_export.DEFAULT_ROM8)
    parser.add_argument("--rome", type=Path, default=boot_export.DEFAULT_ROME)
    parser.add_argument("--output", type=Path, default=WORK / "backend")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()

    game = args.game.read_bytes()
    print("[GAM9288_STAGE] analyze|分析 GAM 函数与控制流", flush=True)
    recovered, stats = native.recover_game_blocks(game)
    recovered = frontend.canonicalize_records(game, recovered)
    entries, bodies = functions.discover_functions(game, recovered, stats)
    direct_function_count = len(bodies)
    entries, bodies, aliases = complete_function_partition(
        game,
        recovered,
        entries,
        bodies,
    )
    grouped: dict[int, list[tuple[int, list[tuple[int, ...]]]]] = {}
    for entry, body in bodies.items():
        grouped.setdefault(entry // GAME_BANK_SIZE, []).append((entry, body))
    runtime = runtime_symbols(args.map)
    firmware = frontend.firmware_table_symbols(args.map)
    direct = frontend.symbols_by_address(args.map)
    args.output.mkdir(parents=True, exist_ok=True)
    for pattern in ("c6502_direct_bank_*.S", "c6502_direct_bank_*.o", "c6502_direct_bank_*.bin"):
        for path in args.output.glob(pattern):
            path.unlink()
    for pattern in (
        "c6502_semantic_outlines.S",
        "c6502_semantic_outlines.o",
        "c6502_semantic_outlines.bin",
    ):
        for path in args.output.glob(pattern):
            path.unlink()
    for pattern in ("c6502_game_image.S", "c6502_game_image.o", "c6502_game_image.lzss"):
        for path in args.output.glob(pattern):
            path.unlink()
    for pattern in ("c6502_boot_snapshot.*", "c6502_dispatch_table.*"):
        for path in args.output.glob(pattern):
            path.unlink()
    outlines = collect_semantic_outlines(game, bodies)
    print("[GAM9288_STAGE] translate|翻译原生代码、压缩资源与准备启动状态", flush=True)
    outline_module = compile_semantic_outlines(
        args.clang,
        args.objcopy,
        args.output,
        outlines,
    )
    resource_image = compile_resource_image(args.clang, args.output, game)
    boot_snapshot = compile_boot_snapshot(
        args.clang,
        args.output,
        args.game,
        args.rom8,
        args.rome,
    )
    work = [(bank, sorted(items)) for bank, items in sorted(grouped.items())]
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [
            pool.submit(
                compile_bank,
                args.clang,
                args.objcopy,
                args.output,
                bank,
                game,
                stats["code_size"],
                entries,
                items,
                runtime,
                firmware,
                direct,
                outlines,
                aliases,
            )
            for bank, items in work
        ]
        modules = [future.result() for future in futures]
    modules.sort(key=lambda item: int(item["bank"]))
    emitted_entry_pattern = re.compile(
        r"^\s*\.globl\s+c6502_game_fn_([0-9a-f]+)\s*$",
        re.MULTILINE,
    )
    emitted_entries: set[int] = set()
    for module in modules:
        source = Path(str(module["object"])).with_suffix(".S")
        emitted_entries.update(
            int(match.group(1), 16)
            for match in emitted_entry_pattern.finditer(source.read_text(encoding="utf-8"))
        )
    indirect_entries, indirect_scope = indirect_target_working_set(
        game,
        recovered,
        emitted_entries,
        modules,
    )
    dispatch_table = compile_dispatch_table(
        args.clang,
        args.output,
        indirect_entries,
    )
    report: dict[str, object] = {
        "format": "c6502-direct-s1c33-v1",
        "game": str(args.game.resolve()),
        "game_bytes": len(game),
        "declared_code_bytes": stats["code_size"],
        "resource_bytes": len(game) - stats["code_size"],
        "recovered_code_bytes": sum(record[3] for record in recovered),
        "preserved_game_data_bytes": (len(game) - sum(record[3] for record in recovered)),
        "native_functions": len(bodies),
        "direct_call_function_groups": direct_function_count,
        "callback_function_groups": len(bodies) - direct_function_count,
        "native_entry_aliases": sum(len(value) for value in aliases.values()),
        "native_code_bytes": (
            sum(int(item["native_bytes"]) for item in modules) + int(outline_module["native_bytes"])
        ),
        "compiled_guest_bytes": sum(int(item["guest_bytes"]) for item in modules),
        "compiled_guest_instructions": sum(int(item["guest_instructions"]) for item in modules),
        "register_abi": {
            "A": "R4",
            "X": "R5",
            "Y": "R6",
            "SP": "R7",
            "lazy_nz": "R8",
            "P": "R9",
            "software_stack": "R10",
            "RAM": "R14",
        },
        "pc_dispatch_tables": 0,
        "opcode_fetches": 0,
        "cycle_scheduler": False,
        "interpreter_fallbacks": 0,
        "standalone_link_complete": False,
        "semantic_outline_functions": len(outlines),
        "semantic_outline_sites": sum(
            int(item["call_kinds"].get("semantic_outlined", 0)) for item in modules
        ),
        "semantic_outline_bytes": outline_module["native_bytes"],
        "semantic_outline_object": outline_module["object"],
        "compressed_game_image_bytes": resource_image["packed_bytes"],
        "compressed_game_image_object": resource_image["object"],
        "compressed_boot_snapshot_bytes": boot_snapshot["packed_bytes"],
        "compressed_boot_snapshot_object": boot_snapshot["object"],
        "native_dispatch_entries": dispatch_table["entries"],
        "native_dispatch_scope": indirect_scope,
        "native_dispatch_table_bytes": dispatch_table["bytes"],
        "native_dispatch_table_object": dispatch_table["object"],
        "modules": modules,
    }
    instructions = int(report["compiled_guest_instructions"])
    report["native_bytes_per_guest_instruction_x1000"] = (
        int(report["native_code_bytes"]) * 1000 // instructions
    )
    report["uncompiled_recovered_code_bytes"] = int(report["recovered_code_bytes"]) - int(
        report["compiled_guest_bytes"]
    )
    report["native_plus_preserved_data_bytes"] = int(report["native_code_bytes"]) + int(
        report["preserved_game_data_bytes"]
    )
    report["native_plus_compressed_game_bytes"] = (
        int(report["native_code_bytes"])
        + int(report["compressed_game_image_bytes"])
        + int(report["compressed_boot_snapshot_bytes"])
        + int(report["native_dispatch_table_bytes"])
    )
    report_path = args.output / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
