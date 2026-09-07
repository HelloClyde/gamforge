"""Small S1C33 leaves for the compiler's shared-register semantic ABI.

No guest dispatch, C frame, global state spill, or firmware-DP change. R0-R3
may contain partially evaluated API arguments, so even scratch registers are
saved. R15 is never touched (firmware IRQs remain enabled). The C bridge stays
the reference and the slow path for side-effecting read/modify/write memory.
"""

from a9288.compiler.backend import imm

PURE = frozenset(
    "c6502_" + name
    for name in (
        "sem_cmp8",
        "sem_adc8",
        "sem_sbc8",
        "sem_asl_a",
        "sem_lsr_a",
        "sem_store16_imm",
        "runtime_cmp_int",
    )
)
RMW = frozenset(
    "c6502_sem_" + name + "_m"
    for name in (
        "inc",
        "dec",
        "asl",
        "lsr",
        "rol",
        "ror",
    )
)


def _clear_p(mask: int) -> list[str]:
    # Register-form EXT has only 26 payload bits on the target. Encoding a
    # 32-bit complement as three EXTs silently clears P's upper bits. Small
    # positive OR/XOR masks preserve the entire shared-register value.
    if mask == 1:
        return ["    and %r9, -2"]
    return imm("or", "r9", mask) + imm("xor", "r9", mask)


def _nz(value: str, label: str) -> list[str]:
    return (
        [f"    ld.ub %r8, %{value}", "    ld.w %r0, %r8"]
        + imm("and", "r0", 0x80)
        + _clear_p(0x82)
        + [
            "    or %r9, %r0",
            "    cmp %r8, 0",
            f"    jrne {label}",
            "    or %r9, 2",
            f"{label}:",
        ]
    )


def _compare16(tag: str) -> list[str]:
    # Byte loads also work for the unaligned OPER2 word at $23.
    result = (
        ["    ld.w %r2, %r14"]
        + imm("add", "r2", 0x20)
        + [
            "    ld.ub %r0, [%r2]",
            "    add %r2, 1",
            "    ld.ub %r1, [%r2]",
            "    sll %r1, 8",
            "    or %r0, %r1",
            "    add %r2, 2",
            "    ld.ub %r1, [%r2]",
            "    add %r2, 1",
            "    ld.ub %r2, [%r2]",
            "    sll %r2, 8",
            "    or %r1, %r2",
            "    ld.w %r2, %r0",
            "    sub %r2, %r1",
            "    ld.uh %r2, %r2",
        ]
        + _clear_p(0xC3)
        + imm("or", "r9", 0x30)
        + [
            "    cmp %r0, %r1",
            f"    jrult {tag}_nc",
            "    or %r9, 1",
            f"{tag}_nc:",
            "    xor %r1, %r0",
            "    xor %r0, %r2",
            "    and %r0, %r1",
            "    srl %r0, 8",
            "    srl %r0, 1",
        ]
        + imm("and", "r0", 0x40)
        + [
            "    or %r9, %r0",
            "    ld.w %r1, %r2",
            "    srl %r1, 8",
            "    ld.w %r0, %r1",
        ]
        + imm("and", "r0", 0x80)
        + [
            "    or %r9, %r0",
            "    ld.w %r8, %r0",
            "    ld.w %r5, 0",
            "    cmp %r1, 0",
            f"    jreq {tag}_high_zero",
            "    add %r5, 1",
            f"{tag}_high_zero:",
            "    ld.ub %r0, %r2",
            "    cmp %r0, 0",
            f"    jreq {tag}_low_zero",
            "    add %r5, 1",
            f"{tag}_low_zero:",
            "    cmp %r2, 0",
            f"    jrne {tag}_nonzero",
            "    or %r9, 2",
            f"    jp {tag}_done",
            f"{tag}_nonzero:",
            "    cmp %r8, 0",
            f"    jrne {tag}_done",
            "    ld.w %r8, 1",
            f"{tag}_done:",
            "    ld.w %r4, %r9",
        ]
    )
    return result


def fast_helper(symbol: str, ident: int) -> tuple[list[str], bool]:
    """Return assembly prefix and whether it implements the complete helper.

    Guard failures restore scratch *before* entering the existing C bridge.
    Profile mode counts slow bridges only, just like direct_read8/write8.
    """
    if symbol not in PURE | RMW:
        return [], False
    tag = f".Lalu_{ident}"
    body = [
        f"    .globl {symbol}",
        f"    .type {symbol},@function",
        f"{symbol}:",
        "    pushn %r3",
    ]
    if symbol == "c6502_sem_cmp8":
        body += [
            "    ld.ub %r0, %r13",
            "    ld.ub %r1, %r12",
            "    ld.w %r8, %r0",
            "    sub %r8, %r1",
        ]
        body += _clear_p(1)
        body += [
            "    cmp %r0, %r1",
            f"    jrult {tag}_nc",
            "    or %r9, 1",
            f"{tag}_nc:",
        ] + _nz("r8", tag + "_nz")
    elif symbol in ("c6502_sem_adc8", "c6502_sem_sbc8"):
        adc = symbol == "c6502_sem_adc8"
        body += [
            "    ld.ub %r0, %r4",
            "    ld.ub %r1, %r12",
            "    ld.w %r2, %r0",
            "    ld.w %r3, %r9",
            "    and %r3, 1",
        ]
        body += (
            ["    add %r2, %r1", "    add %r2, %r3"]
            if adc
            else ["    sub %r2, %r1", "    sub %r2, 1", "    add %r2, %r3"]
        )
        body += _clear_p(0x41)
        if adc:
            body += ["    ld.w %r3, %r2", "    srl %r3, 8", "    or %r9, %r3"]
        else:
            body += imm("cmp", "r2", 255) + [
                f"    jrugt {tag}_nc",
                "    or %r9, 1",
                f"{tag}_nc:",
            ]
        body += ["    xor %r1, %r0"]
        if adc:
            body += imm("xor", "r1", 0x80)
        body += ["    xor %r0, %r2", "    and %r0, %r1", "    srl %r0, 1"]
        body += imm("and", "r0", 0x40)
        body += ["    or %r9, %r0", "    ld.ub %r4, %r2"] + _nz("r4", tag + "_nz")
    elif symbol in ("c6502_sem_asl_a", "c6502_sem_lsr_a"):
        left = symbol == "c6502_sem_asl_a"
        body += ["    ld.w %r0, %r4"]
        if left:
            body += ["    srl %r0, 7"]
        body += ["    and %r0, 1"] + _clear_p(1)
        body += [
            "    or %r9, %r0",
            f"    {'sll' if left else 'srl'} %r4, 1",
            "    ld.ub %r4, %r4",
        ] + _nz("r4", tag + "_nz")
    elif symbol == "c6502_sem_store16_imm":
        # semantic_put16 intentionally writes raw compiler temporaries, not
        # guest MMIO. $28 is register-resident; $ff's high byte is at $100.
        body += [
            "    ld.ub %r0, %r11",
            "    ld.w %r4, %r12",
            "    srl %r4, 8",
            "    ld.ub %r4, %r4",
        ] + imm("cmp", "r0", 0x28)
        body += [
            f"    jreq {tag}_sp",
            "    add %r0, %r14",
            "    ld.b [%r0], %r12",
            "    add %r0, 1",
            "    ld.b [%r0], %r4",
            f"    jp {tag}_stored",
            f"{tag}_sp:",
            "    ld.uh %r10, %r12",
            f"{tag}_stored:",
        ]
        body += _nz("r4", tag + "_nz")
    elif symbol == "c6502_runtime_cmp_int":
        body += _compare16(tag)
    else:
        # Reject side effects BEFORE the read. Address truncation matches the
        # C reference, while R12 itself remains unchanged for the caller.
        slow = tag + "_slow"
        body += [
            "    ld.uh %r0, %r12",
            "    cmp %r0, 4",
            f"    jrult {slow}",
            "    cmp %r0, 12",
            f"    jrult {tag}_page",
            "    cmp %r0, 14",
            f"    jrule {slow}",
            f"{tag}_page:",
        ]
        body += imm("cmp", "r0", 0x4000) + [f"    jruge {slow}"]
        body += imm("cmp", "r0", 0x300) + [f"    jrult {tag}_special"]
        body += imm("cmp", "r0", 0x1000) + [f"    jrule {slow}", f"{tag}_special:"]
        for address in (0x21B, 0x2028):
            body += imm("cmp", "r0", address) + [f"    jreq {slow}"]
        body += ["    ld.w %r1, %r14", "    add %r1, %r0", "    ld.ub %r2, [%r1]"]
        operation = symbol.removeprefix("c6502_sem_").removesuffix("_m")
        if operation in ("inc", "dec"):
            body += [f"    {'add' if operation == 'inc' else 'sub'} %r2, 1"]
        else:
            left = operation in ("asl", "rol")
            body += ["    ld.w %r3, %r9", "    and %r3, 1", "    ld.w %r0, %r2"]
            if left:
                body += ["    srl %r0, 7"]
            body += ["    and %r0, 1"] + _clear_p(1)
            body += ["    or %r9, %r0", f"    {'sll' if left else 'srl'} %r2, 1"]
            if operation == "ror":
                body += ["    sll %r3, 7"]
            if operation in ("rol", "ror"):
                body += ["    or %r2, %r3"]
        body += ["    ld.ub %r13, %r2", "    ld.b [%r1], %r13"] + _nz("r13", tag + "_nz")
    body += ["    popn %r3", "    ret"]
    complete = symbol in PURE
    if complete:
        body += [f"    .size {symbol}, .-{symbol}", ""]
    else:
        body += [tag + "_slow:", "    popn %r3"]
    return body, complete
