from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag

OPCODE_LENGTHS = (
    1,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    2,
    1,
    1,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    3,
    1,
    1,
    3,
    3,
    3,
    3,
    3,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    2,
    1,
    1,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    3,
    1,
    1,
    3,
    3,
    3,
    3,
    1,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    2,
    1,
    1,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    3,
    1,
    1,
    3,
    3,
    3,
    3,
    1,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    2,
    1,
    1,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    3,
    1,
    1,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    2,
    1,
    1,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    3,
    1,
    1,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    2,
    1,
    1,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    3,
    1,
    1,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    2,
    1,
    1,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    3,
    1,
    1,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    2,
    1,
    1,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    1,
    2,
    2,
    2,
    2,
    1,
    3,
    1,
    1,
    3,
    3,
    3,
    3,
)

TERMINATORS = {
    0x00,
    0x20,
    0x40,
    0x4C,
    0x60,
    0x6C,
    0x7C,
    0x80,
    0x10,
    0x30,
    0x50,
    0x70,
    0x90,
    0xB0,
    0xD0,
    0xF0,
    0x0F,
    0x1F,
    0x2F,
    0x3F,
    0x4F,
    0x5F,
    0x6F,
    0x7F,
    0x8F,
    0x9F,
    0xAF,
    0xBF,
    0xCF,
    0xDF,
    0xEF,
    0xFF,
}

PAGE0_SPECIAL_READ = {0x00, 0x01, 0x02, 0x03, 0x0C, 0x0D, 0x0E}

PAGE0_SPECIAL_WRITE = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x0C, 0x0D, 0x0E}


class CpuFlag(IntFlag):
    """6502 status bits tracked by the offline AOT IR."""

    C = 0x01
    Z = 0x02
    I = 0x04
    D = 0x08
    B = 0x10
    U = 0x20
    V = 0x40
    N = 0x80

    NZ = N | Z
    NZC = N | Z | C
    NZCV = N | Z | C | V
    ALL = 0xFF


@dataclass
class InstructionIR:
    """One decoded 6502 operation plus its status data-flow contract."""

    pc: int
    data: bytes
    reads: CpuFlag
    writes: CpuFlag
    live_writes: CpuFlag = CpuFlag.ALL


BRANCH_FLAG_READS = {
    0x10: CpuFlag.N,
    0x30: CpuFlag.N,
    0x50: CpuFlag.V,
    0x70: CpuFlag.V,
    0x90: CpuFlag.C,
    0xB0: CpuFlag.C,
    0xD0: CpuFlag.Z,
    0xF0: CpuFlag.Z,
}

NZ_WRITERS = {
    0x05,
    0x09,
    0x0D,
    0x11,
    0x1D,  # ORA
    0x25,
    0x29,
    0x2D,
    0x31,  # AND
    0x45,
    0x49,
    0x51,  # EOR
    0x68,  # PLA
    0x88,
    0x8A,
    0x98,  # DEY/TXA/TYA
    0xA0,
    0xA2,
    0xA4,
    0xA5,
    0xA6,
    0xA8,  # loads/transfers
    0xA9,
    0xAA,
    0xAC,
    0xAD,
    0xAE,
    0xB1,
    0xB5,
    0xB9,
    0xBA,
    0xBD,
    0xC6,
    0xC8,
    0xCA,
    0xCE,
    0xDE,  # DEC/INY/DEX
    0xE6,
    0xE8,
    0xEE,  # INC/INX
}

NZC_WRITERS = {
    0x06,
    0x0A,
    0x0E,
    0x1E,  # ASL
    0x26,
    0x2A,
    0x2E,
    0x3E,  # ROL
    0x46,
    0x4A,
    0x4E,  # LSR
    0x66,
    0x6A,
    0x6E,
    0x76,  # ROR
    0xC0,
    0xC4,
    0xC5,
    0xC9,
    0xCD,  # CMP/CPY
    0xE0,
    0xEC,  # CPX
}

ARITHMETIC_WRITERS = {0x65, 0x69, 0x6D, 0x71, 0xE5, 0xE9, 0xED, 0xF1}

ROTATE_READERS = {0x26, 0x2A, 0x2E, 0x3E, 0x66, 0x6A, 0x6E, 0x76}


def flag_effects(opcode: int) -> tuple[CpuFlag, CpuFlag]:
    """Return status bits read and written by a supported opcode."""

    reads = BRANCH_FLAG_READS.get(opcode, CpuFlag(0))
    writes = CpuFlag(0)
    if opcode in NZ_WRITERS:
        writes = CpuFlag.NZ
    elif opcode in NZC_WRITERS:
        writes = CpuFlag.NZC
    elif opcode in ARITHMETIC_WRITERS:
        reads |= CpuFlag.C | CpuFlag.D
        writes = CpuFlag.NZCV
    elif opcode == 0x18 or opcode == 0x38:
        writes = CpuFlag.C
    elif opcode == 0x78:
        writes = CpuFlag.I
    elif opcode == 0x08:
        reads = CpuFlag.ALL
    elif opcode == 0x28 or opcode == 0x40:
        writes = CpuFlag.ALL
    if opcode in ROTATE_READERS:
        reads |= CpuFlag.C
    return reads, writes


def analyze_flag_liveness(instructions: list[InstructionIR]) -> None:
    """Remove status writes hidden by a later write inside one basic block.

    All status bits are conservatively live at every block exit because the
    dispatcher, an interrupt, or an unchained successor can observe them.  N
    and Z share one compact materialization in the native backend, so retain
    them as a pair whenever either result remains live.
    """

    live = CpuFlag.ALL
    for instruction in reversed(instructions):
        needed = instruction.writes & live
        if needed & CpuFlag.NZ:
            needed |= instruction.writes & CpuFlag.NZ
        instruction.live_writes = needed
        live = (live & ~instruction.writes) | instruction.reads


def u16(data: bytes) -> int:
    return data[0] | data[1] << 8


def branch_target(pc: int, displacement: int) -> int:
    signed = displacement if displacement < 0x80 else displacement - 0x100
    return (pc + 2 + signed) & 0xFFFF


def read_expr(addr: int) -> str:
    if addr < 0x100 and addr not in PAGE0_SPECIAL_READ:
        return f"S6502_AOT_ZP_READ(0x{addr:02x}u)"
    if 0x2000 <= addr < 0x3000:
        return f"S6502_AOT_RAM_READ(0x{addr:04x}u)"
    if 0x0300 <= addr < 0x0400:
        return f"S6502_AOT_PAGE3_READ(0x{addr:04x}u)"
    return f"READ8(0x{addr:04x}u)"


def indirect_base_expr(zp: int) -> str:
    next_zp = (zp + 1) & 0xFF
    if zp not in PAGE0_SPECIAL_READ and next_zp not in PAGE0_SPECIAL_READ:
        return f"S6502_AOT_ZP16(0x{zp:02x}u)"
    return f"READ16W(0x{zp:02x}u)"


def store_line(register: str, addr: int, cost: int) -> str:
    if addr < 0x100 and addr not in PAGE0_SPECIAL_WRITE:
        return f"S6502_AOT_ST{register}_ZP(0x{addr:02x}u, {cost});"
    if 0x2000 <= addr < 0x3000 and addr not in {0x2028}:
        return f"S6502_AOT_ST{register}_RAM(0x{addr:04x}u, {cost});"
    return f"S6502_AOT_ST{register}(0x{addr:04x}u, {cost});"


def rmw_line(
    operation: str,
    addr: int,
    flags: str,
    cost: int | None = None,
) -> str:
    suffix = f", {cost}, {flags}" if cost is not None else f", {flags}"
    if 0x2000 <= addr < 0x3000 and addr not in {0x2028}:
        return f"S6502_AOT_{operation}_RAM(0x{addr:04x}u{suffix});"
    return f"S6502_AOT_{operation}(0x{addr:04x}u{suffix});"


def emit_instruction(ir: InstructionIR) -> tuple[list[str], bool]:
    pc = ir.pc
    instruction = ir.data
    opcode = instruction[0]
    byte = instruction[1] if len(instruction) > 1 else 0
    word = u16(instruction[1:3]) if len(instruction) > 2 else 0
    flags = f"0x{int(ir.live_writes):02x}u"
    line: str

    if opcode == 0x05:
        line = f"S6502_AOT_ORA({read_expr(byte)}, 3, {flags});"
    elif opcode == 0x06:
        line = f"S6502_AOT_ASL_ZP(0x{byte:02x}u, {flags});"
    elif opcode == 0x08:
        line = "S6502_AOT_PHP();"
    elif opcode == 0x09:
        line = f"S6502_AOT_ORA(0x{byte:02x}u, 2, {flags});"
    elif opcode == 0x0A:
        line = f"S6502_AOT_ASL_A({flags});"
    elif opcode == 0x0D:
        line = f"S6502_AOT_ORA({read_expr(word)}, 4, {flags});"
    elif opcode == 0x0E:
        line = rmw_line("ASL_M", word, flags)
    elif opcode == 0x10:
        target = branch_target(pc, byte)
        line = f"S6502_AOT_BRANCH(!NEGATIVE_p, 0x{(pc + 2) & 0xFFFF:04x}u, 0x{target:04x}u);"
    elif opcode == 0x11:
        line = f"S6502_AOT_ORA_INDY({indirect_base_expr(byte)}, {flags});"
    elif opcode == 0x18:
        line = f"S6502_AOT_CLC({flags});"
    elif opcode == 0x1E:
        line = f"S6502_AOT_ASL_ABSX(0x{word:04x}u, {flags});"
    elif opcode == 0x1D:
        line = f"S6502_AOT_ORA_ABSX(0x{word:04x}u, {flags});"
    elif opcode == 0x20:
        line = f"S6502_AOT_JSR(0x{(pc + 2) & 0xFFFF:04x}u, 0x{word:04x}u);"
    elif opcode == 0x25:
        line = f"S6502_AOT_AND({read_expr(byte)}, 3, {flags});"
    elif opcode == 0x26:
        line = f"S6502_AOT_ROL_ZP(0x{byte:02x}u, {flags});"
    elif opcode == 0x28:
        line = "S6502_AOT_PLP();"
    elif opcode == 0x29:
        line = f"S6502_AOT_AND(0x{byte:02x}u, 2, {flags});"
    elif opcode == 0x2A:
        line = f"S6502_AOT_ROL_A({flags});"
    elif opcode == 0x2D:
        line = f"S6502_AOT_AND({read_expr(word)}, 4, {flags});"
    elif opcode == 0x2E:
        line = rmw_line("ROL_M", word, flags)
    elif opcode == 0x30:
        target = branch_target(pc, byte)
        line = f"S6502_AOT_BRANCH(NEGATIVE_p, 0x{(pc + 2) & 0xFFFF:04x}u, 0x{target:04x}u);"
    elif opcode == 0x31:
        line = f"S6502_AOT_AND_INDY({indirect_base_expr(byte)}, {flags});"
    elif opcode == 0x38:
        line = f"S6502_AOT_SEC({flags});"
    elif opcode == 0x3E:
        line = f"S6502_AOT_ROL_ABSX(0x{word:04x}u, {flags});"
    elif opcode == 0x40:
        line = "S6502_AOT_RTI();"
    elif opcode == 0x45:
        line = f"S6502_AOT_EOR({read_expr(byte)}, 3, {flags});"
    elif opcode == 0x46:
        line = f"S6502_AOT_LSR_ZP(0x{byte:02x}u, {flags});"
    elif opcode == 0x48:
        line = "S6502_AOT_PHA();"
    elif opcode == 0x49:
        line = f"S6502_AOT_EOR(0x{byte:02x}u, 2, {flags});"
    elif opcode == 0x51:
        line = f"S6502_AOT_EOR_INDY({indirect_base_expr(byte)}, {flags});"
    elif opcode == 0x4A:
        line = f"S6502_AOT_LSR_A({flags});"
    elif opcode == 0x4E:
        line = rmw_line("LSR_M", word, flags)
    elif opcode == 0x4C:
        line = f"S6502_AOT_JMP(0x{word:04x}u);"
    elif opcode == 0x50:
        target = branch_target(pc, byte)
        line = f"S6502_AOT_BRANCH(!OVERFLOW_p, 0x{(pc + 2) & 0xFFFF:04x}u, 0x{target:04x}u);"
    elif opcode == 0x60:
        line = "S6502_AOT_RTS();"
    elif opcode == 0x65:
        line = f"S6502_AOT_ADC({read_expr(byte)}, 3, {flags});"
    elif opcode == 0x66:
        line = f"S6502_AOT_ROR_ZP(0x{byte:02x}u, {flags});"
    elif opcode == 0x68:
        line = f"S6502_AOT_PLA({flags});"
    elif opcode == 0x69:
        line = f"S6502_AOT_ADC(0x{byte:02x}u, 2, {flags});"
    elif opcode == 0x6A:
        line = f"S6502_AOT_ROR_A({flags});"
    elif opcode == 0x6C:
        line = f"S6502_AOT_JMP_INDIRECT(0x{word:04x}u);"
    elif opcode == 0x6D:
        line = f"S6502_AOT_ADC({read_expr(word)}, 4, {flags});"
    elif opcode == 0x6E:
        line = rmw_line("ROR_M", word, flags)
    elif opcode == 0x70:
        target = branch_target(pc, byte)
        line = f"S6502_AOT_BRANCH(OVERFLOW_p, 0x{(pc + 2) & 0xFFFF:04x}u, 0x{target:04x}u);"
    elif opcode == 0x71:
        line = f"S6502_AOT_ADC_INDY({indirect_base_expr(byte)}, {flags});"
    elif opcode == 0x76:
        line = f"S6502_AOT_ROR_ZP((uint8_t)(0x{byte:02x}u + ix), {flags});"
    elif opcode == 0x78:
        line = f"S6502_AOT_SEI({flags});"
    elif opcode == 0x84:
        line = f"S6502_AOT_STY(0x{byte:02x}u, 3);"
    elif opcode == 0x85:
        line = store_line("A", byte, 3)
    elif opcode == 0x86:
        line = store_line("X", byte, 3)
    elif opcode == 0x88:
        line = f"S6502_AOT_DEY({flags});"
    elif opcode == 0x8A:
        line = f"S6502_AOT_TXA({flags});"
    elif opcode == 0x8C:
        line = f"S6502_AOT_STY(0x{word:04x}u, 4);"
    elif opcode == 0x8D:
        line = store_line("A", word, 4)
    elif opcode == 0x8E:
        line = store_line("X", word, 4)
    elif opcode == 0x90:
        target = branch_target(pc, byte)
        line = f"S6502_AOT_BRANCH(!CARRY_p, 0x{(pc + 2) & 0xFFFF:04x}u, 0x{target:04x}u);"
    elif opcode == 0x91:
        line = f"S6502_AOT_STA_INDY({indirect_base_expr(byte)});"
    elif opcode == 0x95:
        line = f"S6502_AOT_STA_ZPX(0x{byte:02x}u);"
    elif opcode == 0x98:
        line = f"S6502_AOT_TYA({flags});"
    elif opcode == 0x99:
        line = f"S6502_AOT_STA_ABSY(0x{word:04x}u);"
    elif opcode == 0x9A:
        line = "S6502_AOT_TXS();"
    elif opcode == 0x9D:
        line = f"S6502_AOT_STA_ABSX(0x{word:04x}u);"
    elif opcode == 0xA0:
        line = f"S6502_AOT_LDY(0x{byte:02x}u, 2, {flags});"
    elif opcode == 0xA2:
        line = f"S6502_AOT_LDX(0x{byte:02x}u, 2, {flags});"
    elif opcode == 0xA4:
        line = f"S6502_AOT_LDY({read_expr(byte)}, 3, {flags});"
    elif opcode == 0xA5:
        line = f"S6502_AOT_LDA({read_expr(byte)}, 3, {flags});"
    elif opcode == 0xA6:
        line = f"S6502_AOT_LDX({read_expr(byte)}, 3, {flags});"
    elif opcode == 0xA8:
        line = f"S6502_AOT_TAY({flags});"
    elif opcode == 0xA9:
        line = f"S6502_AOT_LDA(0x{byte:02x}u, 2, {flags});"
    elif opcode == 0xAA:
        line = f"S6502_AOT_TAX({flags});"
    elif opcode == 0xAC:
        line = f"S6502_AOT_LDY({read_expr(word)}, 4, {flags});"
    elif opcode == 0xAD:
        line = f"S6502_AOT_LDA({read_expr(word)}, 4, {flags});"
    elif opcode == 0xAE:
        line = f"S6502_AOT_LDX({read_expr(word)}, 4, {flags});"
    elif opcode == 0xB1:
        line = f"S6502_AOT_LDA_INDY({indirect_base_expr(byte)}, {flags});"
    elif opcode == 0xB5:
        line = f"S6502_AOT_LDA(READ8((uint8_t)(0x{byte:02x}u + ix)), 4, {flags});"
    elif opcode == 0xB9:
        line = f"S6502_AOT_LDA_ABSY(0x{word:04x}u, {flags});"
    elif opcode == 0xBA:
        line = f"S6502_AOT_TSX({flags});"
    elif opcode == 0xBD:
        line = f"S6502_AOT_LDA_ABSX(0x{word:04x}u, {flags});"
    elif opcode == 0xB0:
        target = branch_target(pc, byte)
        line = f"S6502_AOT_BRANCH(CARRY_p, 0x{(pc + 2) & 0xFFFF:04x}u, 0x{target:04x}u);"
    elif opcode == 0xC0:
        line = f"S6502_AOT_COMPARE(iy, 0x{byte:02x}u, 2, {flags});"
    elif opcode == 0xC4:
        line = f"S6502_AOT_COMPARE(iy, {read_expr(byte)}, 3, {flags});"
    elif opcode == 0xC5:
        line = f"S6502_AOT_COMPARE(ac, {read_expr(byte)}, 3, {flags});"
    elif opcode == 0xC6:
        line = rmw_line("DEC", byte, flags, 5)
    elif opcode == 0xC8:
        line = f"S6502_AOT_INY({flags});"
    elif opcode == 0xC9:
        line = f"S6502_AOT_COMPARE(ac, 0x{byte:02x}u, 2, {flags});"
    elif opcode == 0xCA:
        line = f"S6502_AOT_DEX({flags});"
    elif opcode == 0xCD:
        line = f"S6502_AOT_COMPARE(ac, {read_expr(word)}, 4, {flags});"
    elif opcode == 0xCE:
        line = rmw_line("DEC", word, flags, 6)
    elif opcode == 0xD0:
        target = branch_target(pc, byte)
        line = f"S6502_AOT_BRANCH(!ZERO_p, 0x{(pc + 2) & 0xFFFF:04x}u, 0x{target:04x}u);"
    elif opcode == 0xDE:
        line = f"S6502_AOT_DEC_ABSX(0x{word:04x}u, {flags});"
    elif opcode == 0xE0:
        line = f"S6502_AOT_COMPARE(ix, 0x{byte:02x}u, 2, {flags});"
    elif opcode == 0xE5:
        line = f"S6502_AOT_SBC({read_expr(byte)}, 3, {flags});"
    elif opcode == 0xE6:
        line = f"S6502_AOT_INC(0x{byte:02x}u, 5, {flags});"
    elif opcode == 0xE8:
        line = f"S6502_AOT_INX({flags});"
    elif opcode == 0xE9:
        line = f"S6502_AOT_SBC(0x{byte:02x}u, 2, {flags});"
    elif opcode == 0xEA:
        line = "S6502_AOT_NOP();"
    elif opcode == 0xEC:
        line = f"S6502_AOT_COMPARE(ix, {read_expr(word)}, 4, {flags});"
    elif opcode == 0xED:
        line = f"S6502_AOT_SBC({read_expr(word)}, 4, {flags});"
    elif opcode == 0xEE:
        line = rmw_line("INC", word, flags, 6)
    elif opcode == 0xF0:
        target = branch_target(pc, byte)
        line = f"S6502_AOT_BRANCH(ZERO_p, 0x{(pc + 2) & 0xFFFF:04x}u, 0x{target:04x}u);"
    elif opcode == 0xF1:
        line = f"S6502_AOT_SBC_INDY({indirect_base_expr(byte)}, {flags});"
    else:
        raise ValueError(f"unsupported opcode 0x{opcode:02x} at 0x{pc:04x}")
    return [line], opcode in TERMINATORS
