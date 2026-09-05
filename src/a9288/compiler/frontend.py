#!/usr/bin/env python3
"""Recover compiler-level structure from a C6502 GAM image.

This is the front end of the real GAM-to-S1C33 recompiler.  It deliberately
does not emit an interpreter or per-PC dispatch table.  Its output describes
functions, direct calls, compiler-runtime calls, firmware API calls, and
semantic instruction phrases that a native back end can lower to S1C33.
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
from collections import Counter
from pathlib import Path

from a9288.compiler import cfg as native
from a9288.compiler import semantics as semantic
from a9288.paths import DATA

GAME_BANK_SIZE = 0x4000
GAME_VIRTUAL_BASE = 0x5000
DEFAULT_MAP = DATA / "c6502_symbols.json"
MAP_RE = re.compile(r"^([^\s*][^\s]*)\s+([0-9A-Fa-f]{8})\s*$")


def read_legacy_text(path: Path) -> str:
    return path.read_bytes().replace(b"\0", b"").decode("gb18030", errors="replace")


def firmware_table_symbols(path: Path) -> dict[int, str]:
    """Map C6502 `&Function` bank-table addresses to public names."""

    if path.suffix == ".json":
        return {
            int(k): v for k, v in json.loads(path.read_text(encoding="utf-8"))["firmware"].items()
        }
    result: dict[int, str] = {}
    for line in read_legacy_text(path).splitlines():
        match = MAP_RE.match(line)
        if not match or not match.group(1).startswith("&"):
            continue
        address = int(match.group(2), 16)
        if 0xE700 <= address <= 0xF1FF:
            result.setdefault(address, match.group(1)[1:])
    return result


def symbols_by_address(path: Path) -> dict[int, str]:
    """Return the most useful linker-map symbol at each logical address."""

    if path.suffix == ".json":
        return {
            int(k): v for k, v in json.loads(path.read_text(encoding="utf-8"))["symbols"].items()
        }
    candidates: dict[int, list[str]] = {}
    for line in read_legacy_text(path).splitlines():
        match = MAP_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        if name.startswith("&"):
            continue
        candidates.setdefault(int(match.group(2), 16), []).append(name)
    result: dict[int, str] = {}
    for address, names in candidates.items():
        # Public wrapper names are more meaningful than internal local labels.
        result[address] = min(
            names,
            key=lambda item: (
                0 if item.startswith("_Sys") else 1 if item.startswith("__") else 2,
                len(item),
                item,
            ),
        ).lstrip("_")
    return result


def decode_record(game: bytes, record: tuple[int, ...]) -> list[native.aotgen.InstructionIR]:
    _physical, virtual, offset, size, expected_count, _bank2 = record
    cursor = offset
    end = offset + size
    pc = virtual
    result: list[native.aotgen.InstructionIR] = []
    while cursor < end:
        opcode = game[cursor]
        length = native.aotgen.OPCODE_LENGTHS[opcode]
        raw = game[cursor : cursor + length]
        reads, writes = native.aotgen.flag_effects(opcode)
        result.append(native.aotgen.InstructionIR(pc, raw, reads, writes))
        pc = (pc + length) & 0xFFFF
        cursor += length
    if len(result) != expected_count:
        raise RuntimeError("decoded block does not match recovered CFG")
    native.aotgen.analyze_flag_liveness(result)
    return result


def canonicalize_records(
    game: bytes,
    records: list[tuple[int, ...]],
) -> list[tuple[int, ...]]:
    """Split overlapping recovered blocks at every known entry boundary.

    Static discovery may first decode a long fall-through block and later
    discover a branch/callback entry in its middle.  Keeping both records
    duplicates their common tail in native output.  C6502 targets observed in
    the supported GAMs are real instruction boundaries, so truncate the
    predecessor and represent the suffix exactly once.
    """

    starts = sorted(record[2] for record in records)
    result: list[tuple[int, ...]] = []
    for record in records:
        physical, virtual, offset, size, instruction_count, bank2 = record
        index = bisect.bisect_right(starts, offset)
        if index >= len(starts) or starts[index] >= offset + size:
            result.append(record)
            continue
        end = starts[index]
        cursor = offset
        count = 0
        while cursor < end:
            length = native.aotgen.OPCODE_LENGTHS[game[cursor]]
            if not length or cursor + length > end:
                raise RuntimeError(
                    f"overlapping block entry 0x{end:x} is not an instruction boundary"
                )
            cursor += length
            count += 1
        if cursor != end:
            raise RuntimeError(f"overlapping block entry 0x{end:x} splits an instruction")
        result.append((physical, virtual, offset, end - offset, count, bank2))
    return result


def physical_target(record: tuple[int, ...], virtual: int) -> int | None:
    if not GAME_VIRTUAL_BASE <= virtual < GAME_VIRTUAL_BASE + GAME_BANK_SIZE:
        return None
    # Return a GAM file/code offset.  Using the emulated physical Flash base
    # here would mix two address spaces with far-call table offsets.
    bank_base = record[2] & ~(GAME_BANK_SIZE - 1)
    return bank_base + virtual - GAME_VIRTUAL_BASE


def block_successors(game: bytes, record: tuple[int, ...]) -> tuple[int, ...]:
    """Return intra-game non-call CFG successors as GAM file offsets."""

    instructions = decode_record(game, record)
    last = instructions[-1]
    opcode = last.data[0]
    offset = record[2]
    next_offset = offset + record[3]
    if opcode == 0x20:
        return (next_offset,)
    if opcode in native.aotgen.BRANCH_FLAG_READS:
        target = native.aotgen.branch_target(last.pc, last.data[1])
        physical = physical_target(record, target)
        return tuple(item for item in (physical, next_offset) if item is not None)
    if opcode in (0x4C, 0x80):
        if opcode == 0x4C and last.data == b"\x4c\x5c\xdb":
            return native.game_switch_targets(game, next_offset - 3) or ()
        target = (
            last.data[1] | last.data[2] << 8
            if opcode == 0x4C
            else native.aotgen.branch_target(last.pc, last.data[1])
        )
        physical = physical_target(record, target)
        return (physical,) if physical is not None else ()
    if opcode not in native.aotgen.TERMINATORS:
        return (next_offset,)
    # RTS/RTI and every other terminal leave the current C function.
    return ()


def analyze(game: bytes, map_path: Path) -> dict[str, object]:
    records, stats = native.recover_game_blocks(game)
    records = canonicalize_records(game, records)
    table_symbols = firmware_table_symbols(map_path)
    direct_symbols = symbols_by_address(map_path)
    phrase_counts: Counter[str] = Counter()
    phrase_guest_instructions = 0
    raw_guest_instructions = 0
    runtime_calls: Counter[str] = Counter()
    firmware_calls: Counter[str] = Counter()
    direct_firmware_calls: Counter[str] = Counter()
    direct_game_targets: Counter[int] = Counter()
    far_game_targets: Counter[int] = Counter()
    unresolved_far_tables: Counter[int] = Counter()
    unresolved_direct_targets: Counter[int] = Counter()
    remaining_opcodes: Counter[int] = Counter()
    indirect_jumps = 0

    runtime_by_address: dict[int, str] = {}
    generated = (DATA / "runtime" / "s6502_c6502_spec_generated.h").read_text(encoding="utf-8")
    for name, value in re.findall(r"#define C6502_RT_([A-Z0-9_]+) 0x([0-9a-fA-F]{4})u", generated):
        runtime_by_address[int(value, 16)] = name.lower()

    for record in records:
        instructions = decode_record(game, record)
        raw_guest_instructions += len(instructions)
        index = 0
        while index < len(instructions):
            phrase = semantic._semantic_peephole(instructions, index)
            if phrase is not None:
                line, consumed = phrase
                name = line.split("(", 1)[0].removeprefix("C6502_").lower()
                phrase_counts[name] += 1
                phrase_guest_instructions += consumed
                index += consumed
                continue

            instruction = instructions[index]
            opcode = instruction.data[0]
            remaining_opcodes[opcode] += 1
            if opcode == 0x6C:
                indirect_jumps += 1
            if opcode == 0x20:
                target = instruction.data[1] | instruction.data[2] << 8
                # $D2F6 is only the transport used by .bf_call.  The second
                # pass classifies its real game/API destination instead of
                # exposing the transport as a source-level call.
                if target == 0xD2F6:
                    pass
                elif target in runtime_by_address:
                    runtime_calls[runtime_by_address[target]] += 1
                else:
                    target_physical = physical_target(record, target)
                    if target_physical is not None:
                        direct_game_targets[target_physical] += 1
                    elif target in direct_symbols:
                        direct_firmware_calls[direct_symbols[target]] += 1
                    else:
                        unresolved_direct_targets[target] += 1
            index += 1

        # A .bf_call sequence is five decoded instructions and ends in JSR
        # $D2F6.  Read the compiler's address-register constants directly.
        for index in range(max(0, len(instructions) - 4)):
            window = instructions[index : index + 5]
            if tuple(item.data[0] for item in window) != (0xA2, 0x86, 0xA2, 0x86, 0x20):
                continue
            if (
                window[1].data[1] != 0x26
                or window[3].data[1] != 0x27
                or window[4].data[1:] != bytes((0xF6, 0xD2))
            ):
                continue
            table = window[0].data[1] | window[2].data[1] << 8
            symbol = table_symbols.get(table)
            if symbol is not None:
                firmware_calls[symbol] += 1
                continue
            table_offset = native.game_far_table_offset(
                len(game),
                stats["code_size"],
                table,
            )
            if table_offset is not None:
                target = game[table_offset] | game[table_offset + 1] << 8
                bank = game[table_offset + 2]
                target_offset = (bank - 0xE0) * GAME_BANK_SIZE + target - GAME_VIRTUAL_BASE
                if (
                    bank >= 0xE0
                    and GAME_VIRTUAL_BASE <= target < GAME_VIRTUAL_BASE + GAME_BANK_SIZE
                    and 0 <= target_offset < stats["code_size"]
                ):
                    far_game_targets[target_offset] += 1
                    continue
            unresolved_far_tables[table] += 1

    function_entries = {
        stats["entry_pc"] - GAME_VIRTUAL_BASE,
        *direct_game_targets.keys(),
        *far_game_targets.keys(),
    }
    record_by_offset = {record[2]: record for record in records}
    owned_blocks: set[int] = set()
    ownership_visits = 0
    for entry in function_entries:
        pending = [entry]
        local: set[int] = set()
        while pending:
            offset = pending.pop()
            if offset in local or offset not in record_by_offset:
                continue
            # A jump/fallthrough into a known function entry is a native tail
            # call, not part of the caller's body.
            if offset != entry and offset in function_entries:
                continue
            local.add(offset)
            pending.extend(block_successors(game, record_by_offset[offset]))
        ownership_visits += len(local)
        owned_blocks.update(local)
    owned_guest_bytes = sum(record_by_offset[item][3] for item in owned_blocks)
    owned_guest_instructions = sum(record_by_offset[item][4] for item in owned_blocks)
    semantic_calls = (
        sum(runtime_calls.values())
        + sum(firmware_calls.values())
        + sum(direct_firmware_calls.values())
    )
    far_call_sites = sum(far_game_targets.values()) + sum(firmware_calls.values())
    # Each .bf_call is the five-instruction compiler transport sequence
    # LDX/STX/LDX/STX/JSR.  Runtime helpers are represented by their JSR here;
    # argument preparation is folded by the phrase recognizer separately.
    call_transport_guest_instructions = (
        far_call_sites * 5 + sum(runtime_calls.values()) + sum(direct_firmware_calls.values())
    )
    known_semantic_guest_instructions = (
        phrase_guest_instructions + call_transport_guest_instructions
    )
    report: dict[str, object] = {
        "format": "c6502-recompiler-front-end-v1",
        "game_bytes": len(game),
        "declared_code_bytes": stats["code_size"],
        "non_code_and_resource_bytes": len(game) - stats["code_size"],
        "entry_pc": stats["entry_pc"],
        "recovered_blocks": len(records),
        "recovered_guest_bytes": sum(record[3] for record in records),
        "recovered_guest_instructions": raw_guest_instructions,
        "function_entries": len(function_entries),
        "function_owned_blocks": len(owned_blocks),
        "function_owned_guest_bytes": owned_guest_bytes,
        "function_owned_guest_instructions": owned_guest_instructions,
        "function_body_duplicate_block_visits": ownership_visits - len(owned_blocks),
        "orphan_recovered_blocks": len(records) - len(owned_blocks),
        "direct_game_call_sites": sum(direct_game_targets.values()),
        "direct_game_call_targets": len(direct_game_targets),
        "far_game_call_sites": sum(far_game_targets.values()),
        "far_game_call_targets": len(far_game_targets),
        "runtime_call_sites": sum(runtime_calls.values()),
        "firmware_api_call_sites": sum(firmware_calls.values()),
        "direct_firmware_call_sites": sum(direct_firmware_calls.values()),
        "semantic_call_sites": semantic_calls,
        "unresolved_far_call_sites": sum(unresolved_far_tables.values()),
        "unresolved_direct_call_sites": sum(unresolved_direct_targets.values()),
        "indirect_jumps": indirect_jumps,
        "phrase_guest_instructions": phrase_guest_instructions,
        "phrase_instruction_coverage_percent_x100": (
            phrase_guest_instructions * 10000 // raw_guest_instructions
        ),
        "call_transport_guest_instructions": call_transport_guest_instructions,
        "known_semantic_guest_instructions": known_semantic_guest_instructions,
        "known_semantic_instruction_coverage_percent_x100": (
            known_semantic_guest_instructions * 10000 // raw_guest_instructions
        ),
        "phrase_counts": dict(phrase_counts.most_common()),
        "remaining_opcodes": {
            f"0x{opcode:02x}": count for opcode, count in remaining_opcodes.most_common()
        },
        "runtime_calls": dict(runtime_calls.most_common()),
        "firmware_calls": dict(firmware_calls.most_common()),
        "direct_firmware_calls": dict(direct_firmware_calls.most_common()),
        "unresolved_far_tables": {
            f"0x{key:04x}": value for key, value in unresolved_far_tables.most_common()
        },
        "unresolved_direct_targets": {
            f"0x{key:04x}": value for key, value in unresolved_direct_targets.most_common()
        },
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = analyze(args.game.read_bytes(), args.map)
    report["game"] = str(args.game.resolve())
    report["map"] = str(args.map.resolve())
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
