from __future__ import annotations

from a9288.compiler import cfg as native


def _direct_zp(address: int) -> bool:
    return address < 0x100 and address not in (
        native.aotgen.PAGE0_SPECIAL_READ | native.aotgen.PAGE0_SPECIAL_WRITE
    )


def _zp_pair(low: int, high: int) -> bool:
    return _direct_zp(low) and high == ((low + 1) & 0xFF) and _direct_zp(high)


def _semantic_peephole(
    instructions: list[native.aotgen.InstructionIR],
    index: int,
) -> tuple[str, int] | None:
    """Recover high-level C6502 operations before native lowering."""

    remaining = instructions[index:]
    opcodes = tuple(item.data[0] for item in remaining[:10])

    # PHP/SEI are emitted by C6502 only to preserve flags while changing one
    # 16-bit software-stack/pointer value.  The native operation has no need
    # to touch the 6502 interrupt/status model at all.
    if len(remaining) >= 10 and opcodes[:10] in (
        (0x08, 0x78, 0x18, 0xA5, 0x69, 0x85, 0xA5, 0x69, 0x85, 0x28),
        (0x08, 0x78, 0x38, 0xA5, 0xE9, 0x85, 0xA5, 0xE9, 0x85, 0x28),
    ):
        src0 = remaining[3].data[1]
        src1 = remaining[6].data[1]
        dst0 = remaining[5].data[1]
        dst1 = remaining[8].data[1]
        if _zp_pair(src0, src1) and _zp_pair(dst0, dst1):
            value = remaining[4].data[1] | (remaining[7].data[1] << 8)
            name = "ADD16_PRESERVE" if remaining[2].data[0] == 0x18 else "SUB16_PRESERVE"
            return f"C6502_{name}(0x{src0:02x}u, 0x{dst0:02x}u, 0x{value:04x}u);", 10

    # General 16-bit pointer/integer add and subtract.  Keep final ADC/SBC
    # flags because a following branch may consume them.
    if len(remaining) >= 7 and opcodes[:7] in (
        (0x18, 0xA5, 0x69, 0x85, 0xA5, 0x69, 0x85),
        (0x38, 0xA5, 0xE9, 0x85, 0xA5, 0xE9, 0x85),
    ):
        src0 = remaining[1].data[1]
        src1 = remaining[4].data[1]
        dst0 = remaining[3].data[1]
        dst1 = remaining[6].data[1]
        if _zp_pair(src0, src1) and _zp_pair(dst0, dst1):
            value = remaining[2].data[1] | (remaining[5].data[1] << 8)
            name = "ADD16" if remaining[0].data[0] == 0x18 else "SUB16"
            return f"C6502_{name}(0x{src0:02x}u, 0x{dst0:02x}u, 0x{value:04x}u);", 7

    # C6502's canonical 16-bit binary expression.  Seven 6502 operations are
    # one typed IR operation; the second ADC/SBC supplies the observable
    # N/Z/C/V result exactly as an unsigned/signed 16-bit C expression does.
    if len(remaining) >= 7 and opcodes[:7] in (
        (0x18, 0xA5, 0x65, 0x85, 0xA5, 0x65, 0x85),
        (0x38, 0xA5, 0xE5, 0x85, 0xA5, 0xE5, 0x85),
    ):
        left0 = remaining[1].data[1]
        right0 = remaining[2].data[1]
        dst0 = remaining[3].data[1]
        left1 = remaining[4].data[1]
        right1 = remaining[5].data[1]
        dst1 = remaining[6].data[1]
        if _zp_pair(left0, left1) and _zp_pair(right0, right1) and _zp_pair(dst0, dst1):
            name = "ADD16_REGS" if remaining[0].data[0] == 0x18 else "SUB16_REGS"
            return (
                f"C6502_{name}(0x{left0:02x}u, 0x{right0:02x}u, 0x{dst0:02x}u);",
                7,
            )

    # 16-bit immediate assignment and zero-page copy.
    if len(remaining) >= 4 and opcodes[:4] == (0xA9, 0x85, 0xA9, 0x85):
        dst0 = remaining[1].data[1]
        dst1 = remaining[3].data[1]
        if _zp_pair(dst0, dst1):
            value = remaining[0].data[1] | (remaining[2].data[1] << 8)
            return f"C6502_STORE16_IMM(0x{dst0:02x}u, 0x{value:04x}u);", 4
    if len(remaining) >= 4 and opcodes[:4] == (0xA5, 0x85, 0xA5, 0x85):
        src0 = remaining[0].data[1]
        src1 = remaining[2].data[1]
        dst0 = remaining[1].data[1]
        dst1 = remaining[3].data[1]
        if _zp_pair(src0, src1) and _zp_pair(dst0, dst1):
            return f"C6502_COPY16(0x{src0:02x}u, 0x{dst0:02x}u);", 4

    # Compiler's canonical 16-bit indirect load/store.
    if len(remaining) >= 6 and opcodes[:6] == (0xA0, 0xB1, 0x85, 0xC8, 0xB1, 0x85):
        index0 = remaining[0].data[1]
        pointer0 = remaining[1].data[1]
        pointer1 = remaining[4].data[1]
        dst0 = remaining[2].data[1]
        dst1 = remaining[5].data[1]
        if pointer0 == pointer1 and _zp_pair(dst0, dst1):
            return f"C6502_LOAD16_INDIRECT(0x{pointer0:02x}u, 0x{dst0:02x}u, 0x{index0:02x}u);", 6
    if len(remaining) >= 6 and opcodes[:6] == (0xA0, 0xA5, 0x91, 0xC8, 0xA5, 0x91):
        index0 = remaining[0].data[1]
        src0 = remaining[1].data[1]
        src1 = remaining[4].data[1]
        pointer0 = remaining[2].data[1]
        pointer1 = remaining[5].data[1]
        if pointer0 == pointer1 and _zp_pair(src0, src1):
            return f"C6502_STORE16_INDIRECT(0x{pointer0:02x}u, 0x{src0:02x}u, 0x{index0:02x}u);", 6

    # Constant-offset accesses through $28 are C locals/arguments, not
    # arbitrary 6502 indirect addressing.  Preserve Y and the final N/Z
    # producer while exposing the stack slot to the native back end.
    if len(remaining) >= 2 and opcodes[:2] == (0xA0, 0xB1):
        if remaining[1].data[1] == 0x28:
            return f"C6502_LOAD_STACK8(0x{remaining[0].data[1]:02x}u);", 2
    if len(remaining) >= 2 and opcodes[:2] == (0xA0, 0x91):
        if remaining[1].data[1] == 0x28:
            return f"C6502_STORE_STACK8(0x{remaining[0].data[1]:02x}u);", 2
    return None
