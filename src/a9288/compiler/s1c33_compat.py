"""Protect comparison flags against late S1C33 frame-address expansion.

Older toolchains model ADJFI as flag-neutral, then expand it into LD SP + ADD
after scheduling. ADD overwrites the flags consumed by a following branch.
Protect those proven frame-address sequences on every target. Optionally
also protect immediate/memory loads for the existing 9288T preview core.
Never use R15 or change the public register ABI, and never suppress genuine
arithmetic whose flags are the intended input to a conditional branch.
"""

from __future__ import annotations

import re

CONDITIONAL = re.compile(r"jr(?:eq|ne|lt|le|gt|ge|ult|ule|ugt|uge|c|nc)\b")
LOAD = re.compile(r"ld\.(w|h|uh|b|ub)\s+%r\d+,\s*(.+)")
STACK = re.compile(r"\[%sp\+(\d+)\]")
FRAME_ADDRESS = re.compile(r"ld\.w\s+(%r\d+),\s*%sp$")
ADD_IMMEDIATE = re.compile(r"add\s+(%r\d+),\s*-?(?:0x[\da-fA-F]+|\d+)$")


def _save_flags() -> list[str]:
    return [
        "    pushn %r0",
        "    ld.w %r0, %psr",
        "    sub %sp, 1",
        "    ld.w [%sp+0], %r0",
        "    ld.w %r0, [%sp+1]",
    ]


def _restore_flags() -> list[str]:
    return [
        # R0 may itself be the destination of the protected instruction.
        "    ld.w [%sp+1], %r0",
        "    ld.w %r0, [%sp+0]",
        "    add %sp, 1",
        "    ld.w %psr, %r0",
        "    popn %r0",
    ]


def _guard_load(lines: list[str]) -> list[str]:
    instruction = lines[-1].split(";", 1)[0].strip()
    match = LOAD.fullmatch(instruction)
    assert match is not None
    stack = STACK.search(instruction)
    extensions = lines[:-1]
    if stack:
        # No EXT: SP displacement is scaled by the access width. With
        # EXT: the combined displacement is already in BYTES. Crossing
        # the inline imm6 limit must switch to the latter representation.
        scale = 4 if match[1] == "w" else 2 if match[1] in ("h", "uh") else 1
        high = 0
        for extension in extensions:
            token = extension.strip().split()[1]
            if not token.isdecimal():
                raise ValueError("symbolic EXT on a stack load is unsupported")
            high = (high << 13) | int(token)
        offset = ((high << 6) | int(stack[1])) if extensions else int(stack[1]) * scale
        offset += 8
        if offset % scale:
            raise ValueError("unaligned SP displacement in protected S1C33 load")
        if offset // scale < 64:
            instruction = STACK.sub(f"[%sp+{offset // scale}]", instruction)
            high = 0
        else:
            instruction = STACK.sub(f"[%sp+{offset & 63}]", instruction)
            high = offset >> 6
        chunks = []
        while high:
            chunks.append(high & 8191)
            high >>= 13
        extensions = [f"    ext {chunk}" for chunk in reversed(chunks)]
    return _save_flags() + extensions + ["    " + instruction] + _restore_flags()


def _guard_address(lines: list[str]) -> list[str]:
    address = FRAME_ADDRESS.fullmatch(lines[0].split(";", 1)[0].strip())
    assert address is not None
    # Our two temporary words lower SP by eight bytes. Compensate before
    # executing the unchanged offset ADD/EXT bundle, including R0 results.
    return (
        ["    ; GAMForge: preserve CMP across late frame-address expansion"]
        + _save_flags()
        + [lines[0], f"    add {address[1]}, 8"]
        + lines[1:]
        + _restore_flags()
    )


def _address_add(source: list[str], index: int, register: str) -> int | None:
    """Only the compiler's contiguous LD-SP / EXT* / ADD-immediate idiom."""
    for end in range(index + 1, len(source)):
        code = source[end].split(";", 1)[0].strip()
        if not code or code.startswith("ext ") or code.startswith("ext\t"):
            continue
        addition = ADD_IMMEDIATE.fullmatch(code)
        return end if addition and addition[1] == register else None
    return None


def preserve_comparison_flags(assembly: str, *, protect_loads: bool = True) -> tuple[str, int]:
    """Repair proven hazards in a straight-line CMP -> conditional branch.

    A late frame-address expansion is flag-neutral at the LLVM pseudo level,
    unlike ordinary arithmetic. Calls, unrelated arithmetic and new labels
    still terminate the interval; do not guess which earlier flags they want.
    EXT prefixes remain attached to their consumer, and no delay slot moves.
    """
    source = assembly.splitlines()
    guards: dict[int, tuple[int, str]] = {}
    comparison = False
    candidates: list[tuple[int, int, str]] = []
    extension_start: int | None = None
    index = 0
    while index < len(source):
        line = source[index]
        code = line.split(";", 1)[0].strip()
        if not code or code.startswith(".") and not code.endswith(":"):
            index += 1
            continue
        if code.startswith("ext ") or code.startswith("ext\t"):
            if extension_start is None:
                extension_start = index
            index += 1
            continue
        start = extension_start if extension_start is not None else index
        extension_start = None
        address = FRAME_ADDRESS.fullmatch(code)
        end = _address_add(source, index, address[1]) if address and comparison else None
        if end is not None and start == index:
            candidates.append((index, end, "address"))
            index = end + 1
            continue
        if re.match(r"cmp\s", code):
            comparison = True
            candidates = []
        elif CONDITIONAL.match(code):
            if comparison:
                for begin, end, kind in candidates:
                    guards[begin] = (end, kind)
            comparison = False
            candidates = []
        else:
            load = LOAD.fullmatch(code)
            if comparison and load:
                if protect_loads and not load[2].startswith("%"):
                    candidates.append((start, index, "load"))
            elif not re.match(r"ld\.(?:w|h|b)\s+\[", code):
                comparison = False
                candidates = []
        index += 1
    output: list[str] = []
    index = 0
    while index < len(source):
        guard = guards.get(index)
        if guard is None:
            output.append(source[index])
            index += 1
        else:
            end, kind = guard
            repair = _guard_address if kind == "address" else _guard_load
            output.extend(repair(source[index : end + 1]))
            index = end + 1
    return "\n".join(output) + "\n", len(guards)
