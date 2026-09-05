from __future__ import annotations

from a9288.compiler import cfg as native
from a9288.compiler import frontend as frontend

GAME_BANK_SIZE = 0x4000

GAME_VIRTUAL_BASE = 0x5000


def function_name(offset: int) -> str:
    return f"c6502_game_fn_{offset:05x}"


def far_call_table(instructions: list[native.aotgen.InstructionIR]) -> int | None:
    if len(instructions) < 5:
        return None
    window = instructions[-5:]
    if window[0].data[0] != 0xA2 or window[2].data[0] != 0xA2 or window[4].data[0] != 0x20:
        return None
    if (
        window[1].data not in (bytes((0x86, 0x26)), bytes((0x8E, 0x26, 0)))
        or window[3].data not in (bytes((0x86, 0x27)), bytes((0x8E, 0x27, 0)))
        or window[4].data[1:] != bytes((0xF6, 0xD2))
    ):
        return None
    return window[0].data[1] | window[2].data[1] << 8


def far_game_target(game: bytes, code_size: int, table: int) -> int | None:
    table_offset = native.game_far_table_offset(
        len(game),
        code_size,
        table,
    )
    if table_offset is None:
        return None
    target = game[table_offset] | game[table_offset + 1] << 8
    bank = game[table_offset + 2]
    if bank < 0xE0 or not GAME_VIRTUAL_BASE <= target < 0x9000:
        return None
    offset = (bank - 0xE0) * GAME_BANK_SIZE + target - GAME_VIRTUAL_BASE
    return offset if 0 <= offset < code_size else None


def discover_functions(
    game: bytes, records: list[tuple[int, ...]], stats: dict[str, int]
) -> tuple[set[int], dict[int, list[tuple[int, ...]]]]:
    entries = {stats["entry_pc"] - GAME_VIRTUAL_BASE}
    record_by_offset = {record[2]: record for record in records}
    for record in records:
        instructions = frontend.decode_record(game, record)
        for instruction in instructions:
            if instruction.data[0] != 0x20:
                continue
            target = instruction.data[1] | instruction.data[2] << 8
            offset = frontend.physical_target(record, target)
            if offset is not None and offset in record_by_offset:
                entries.add(offset)
        table = far_call_table(instructions)
        if table is not None:
            offset = far_game_target(game, stats["code_size"], table)
            if offset is not None and offset in record_by_offset:
                entries.add(offset)

    bodies: dict[int, list[tuple[int, ...]]] = {}
    for entry in sorted(entries):
        pending = [entry]
        visited: set[int] = set()
        while pending:
            offset = pending.pop()
            if offset in visited or offset not in record_by_offset:
                continue
            if offset != entry and offset in entries:
                continue
            visited.add(offset)
            pending.extend(frontend.block_successors(game, record_by_offset[offset]))
        if visited:
            bodies[entry] = [record_by_offset[item] for item in sorted(visited)]
    return entries, bodies
