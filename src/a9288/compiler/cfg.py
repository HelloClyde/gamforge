from __future__ import annotations

from a9288.compiler import isa as aotgen

GAME_PHYSICAL_BASE = 0x20D000

GAME_BANK_SIZE = 0x4000

GAME_VIRTUAL_BASE = 0x5000

GAME_VIRTUAL_END = 0x9000

FAR_CALL_BYTES = bytes.fromhex("a2 00 86 26 a2 00 86 27 20 f6 d2")

FAR_CALL_MASK = bytes.fromhex("ff 00 ff ff ff 00 ff ff ff ff ff")


def game_far_table_offset(
    game_size: int,
    code_size: int,
    table_address: int,
) -> int | None:
    """Map a C6502 `.bf_call` descriptor to its GAM file offset.

    Larger games may place the three-byte descriptor in the tail of bank E0
    ($5000-$8fff), while compact games place it in the appended constant-data
    image ($9000-$cfff).  Treating every table address as `$5000`-relative
    accidentally decoded another code bank for the latter layout.
    """

    if GAME_VIRTUAL_BASE <= table_address < GAME_VIRTUAL_END:
        offset = table_address - GAME_VIRTUAL_BASE
    elif 0x9000 <= table_address < 0xD000:
        offset = code_size + table_address - 0x9000
    else:
        return None
    return offset if 0 <= offset <= game_size - 3 else None


def game_far_call_at(data: bytes, offset: int) -> bool:
    if offset < 0 or offset + len(FAR_CALL_BYTES) > len(data):
        return False
    return all(
        not mask or (data[offset + index] & mask) == (expected & mask)
        for index, (expected, mask) in enumerate(zip(FAR_CALL_BYTES, FAR_CALL_MASK))
    )


def game_switch_targets(game: bytes, jump_offset: int) -> tuple[int, ...] | None:
    """Decode C6502's statically linked __switch_comparison descriptor.

    Match instructions, not arbitrary pointer-looking words in game data.
    Cases/default are intra-function CFG successors of JMP $DB5C.
    """
    if jump_offset < 20 or game[jump_offset : jump_offset + 3] != b"\x4c\x5c\xdb":
        return None
    setup = game[jump_offset - 20 : jump_offset]
    for index, value in (
        (0, 0xA9),
        (2, 0x85),
        (3, 0x26),
        (4, 0xA9),
        (6, 0x85),
        (7, 0x27),
        (8, 0xA2),
        (10, 0xA0),
        (12, 0xA9),
        (14, 0x85),
        (15, 0x20),
        (16, 0xA9),
        (18, 0x85),
        (19, 0x21),
    ):
        if setup[index] != value:
            return None
    table = setup[1] | setup[5] << 8
    count = setup[9] | setup[11] << 8
    default = setup[13] | setup[17] << 8
    base = jump_offset & ~(GAME_BANK_SIZE - 1)
    data = base + table - GAME_VIRTUAL_BASE
    if not count or data < base or data + 4 * count > min(base + GAME_BANK_SIZE, len(game)):
        raise ValueError(f"invalid C6502 switch table at GAM+0x{jump_offset:x}")
    targets = [default] + [
        int.from_bytes(game[data + count * 2 + i * 2 : data + count * 2 + i * 2 + 2], "little")
        for i in range(count)
    ]
    if any(not GAME_VIRTUAL_BASE <= pc < GAME_VIRTUAL_END for pc in targets):
        raise ValueError(f"out-of-bank C6502 switch target at GAM+0x{jump_offset:x}")
    return tuple(dict.fromkeys(base + pc - GAME_VIRTUAL_BASE for pc in targets))


def recover_game_blocks(game: bytes) -> tuple[list[tuple[int, ...]], dict[str, int]]:
    """Recover every statically reachable C6502 basic block in a GAM.

    C6502 maps each 16 KiB code bank into guest $5000-$8fff.  Direct calls
    stay in the current physical bank, while the compiler's .bf_call template
    names a three-byte target/bank record in bank E0.  Unknown indirect
    targets deliberately remain runtime fallbacks; no guessed data bytes are
    published as executable entry points.
    """

    if len(game) < 0x46:
        raise SystemExit("GAM is shorter than its 0x46-byte header")
    entry_pc = game[0x40] | game[0x41] << 8
    code_size = int.from_bytes(game[0x42:0x46], "little")
    if code_size < 0x46 or code_size > len(game):
        code_size = len(game)
    code = game[:code_size]
    if not GAME_VIRTUAL_BASE <= entry_pc < GAME_VIRTUAL_END:
        raise SystemExit(f"GAM entry is outside $5000-$8fff: 0x{entry_pc:04x}")

    queued: set[int] = set()
    queue: list[tuple[int, int]] = []
    blocks: list[tuple[int, ...]] = []
    unsupported: dict[int, int] = {}
    far_calls = 0
    far_targets = 0
    direct_targets = 0

    def enqueue(offset: int, virtual_pc: int) -> None:
        if (
            offset < 0
            or offset >= code_size
            or offset in queued
            or not GAME_VIRTUAL_BASE <= virtual_pc < GAME_VIRTUAL_END
            or (offset & (GAME_BANK_SIZE - 1)) != virtual_pc - GAME_VIRTUAL_BASE
        ):
            return
        queued.add(offset)
        queue.append((offset, virtual_pc))

    enqueue(entry_pc - GAME_VIRTUAL_BASE, entry_pc)
    # Every exact .bf_call template is itself an instruction-aligned compiler
    # landmark.  Seeding all of them discovers functions selected through
    # data-driven menus and callback tables that are not reachable from the
    # initial entry by ordinary direct edges.  The eleven fixed opcode bytes
    # make accidental matches in picture/data payloads vanishingly unlikely;
    # target records still receive strict virtual/bank/range validation.
    for offset in range(0, code_size - len(FAR_CALL_BYTES) + 1):
        if not game_far_call_at(code, offset):
            continue
        enqueue(
            offset,
            GAME_VIRTUAL_BASE + (offset & (GAME_BANK_SIZE - 1)),
        )
        table_address = code[offset + 1] | code[offset + 5] << 8
        table_offset = game_far_table_offset(
            len(game),
            code_size,
            table_address,
        )
        if table_offset is None:
            continue
        target = game[table_offset] | game[table_offset + 1] << 8
        bank = game[table_offset + 2]
        if not (GAME_VIRTUAL_BASE <= target < GAME_VIRTUAL_END and bank >= 0xE0):
            continue
        target_offset = (bank - 0xE0) * GAME_BANK_SIZE + target - GAME_VIRTUAL_BASE
        if target_offset < code_size:
            enqueue(target_offset, target)

    head = 0
    while head < len(queue):
        block_offset, block_pc = queue[head]
        head += 1
        offset = block_offset
        pc = block_pc
        instruction_count = 0
        while offset < code_size and GAME_VIRTUAL_BASE <= pc < GAME_VIRTUAL_END:
            opcode = code[offset]
            length = aotgen.OPCODE_LENGTHS[opcode]
            if not length or offset + length > code_size:
                break
            instruction = code[offset : offset + length]
            reads, writes = aotgen.flag_effects(opcode)
            try:
                aotgen.emit_instruction(aotgen.InstructionIR(pc, instruction, reads, writes))
            except ValueError:
                unsupported[opcode] = unsupported.get(opcode, 0) + 1
                break
            instruction_count += 1
            next_offset = offset + length
            next_pc = (pc + length) & 0xFFFF

            if game_far_call_at(code, offset):
                far_calls += 1
                table_address = code[offset + 1] | code[offset + 5] << 8
                table_offset = game_far_table_offset(
                    len(game),
                    code_size,
                    table_address,
                )
                if table_offset is not None:
                    target = game[table_offset] | game[table_offset + 1] << 8
                    bank = game[table_offset + 2]
                    if GAME_VIRTUAL_BASE <= target < GAME_VIRTUAL_END and bank >= 0xE0:
                        target_offset = (bank - 0xE0) * GAME_BANK_SIZE + target - GAME_VIRTUAL_BASE
                        if target_offset < code_size:
                            enqueue(target_offset, target)
                            far_targets += 1

            terminal = opcode in aotgen.TERMINATORS
            if opcode == 0x20:
                target = instruction[1] | instruction[2] << 8
                if GAME_VIRTUAL_BASE <= target < GAME_VIRTUAL_END:
                    enqueue(
                        (offset & ~(GAME_BANK_SIZE - 1)) + target - GAME_VIRTUAL_BASE,
                        target,
                    )
                    direct_targets += 1
                enqueue(next_offset, next_pc)
            elif opcode in aotgen.BRANCH_FLAG_READS:
                target = aotgen.branch_target(pc, instruction[1])
                signed = instruction[1] if instruction[1] < 0x80 else instruction[1] - 0x100
                enqueue(next_offset + signed, target)
                enqueue(next_offset, next_pc)
            elif opcode == 0x4C:
                target = instruction[1] | instruction[2] << 8
                if target == 0xDB5C:
                    for case_offset in game_switch_targets(game, offset) or ():
                        enqueue(
                            case_offset, GAME_VIRTUAL_BASE + (case_offset & (GAME_BANK_SIZE - 1))
                        )
                if GAME_VIRTUAL_BASE <= target < GAME_VIRTUAL_END:
                    enqueue(
                        (offset & ~(GAME_BANK_SIZE - 1)) + target - GAME_VIRTUAL_BASE,
                        target,
                    )
            elif opcode == 0x80:
                target = aotgen.branch_target(pc, instruction[1])
                signed = instruction[1] if instruction[1] < 0x80 else instruction[1] - 0x100
                enqueue(next_offset + signed, target)

            offset = next_offset
            pc = next_pc
            if terminal:
                break

        if instruction_count and offset > block_offset:
            blocks.append(
                (
                    GAME_PHYSICAL_BASE + block_offset,
                    block_pc,
                    block_offset,
                    offset - block_offset,
                    instruction_count,
                    0,
                )
            )

    blocks.sort(key=lambda record: (record[0], record[1]))
    if unsupported:
        detail = ", ".join(
            f"0x{opcode:02x}x{count}" for opcode, count in sorted(unsupported.items())
        )
        raise SystemExit(f"reachable GAM code uses unsupported opcodes: {detail}")
    return blocks, {
        "entry_pc": entry_pc,
        "code_size": code_size,
        "far_calls": far_calls,
        "far_targets": far_targets,
        "direct_targets": direct_targets,
        "queued_entries": len(queued),
    }
