"""Keep comparison flags alive on the current 9288T preview CPU core.

S1C33 LD instructions preserve PSR flags, but Dream9288T's c33emu currently
updates N/Z for immediate/memory loads. LLVM legitimately spills/reloads
between CMP and a branch. Save the *full* PSR only at those sites, without
using R15 (reserved by the firmware) or changing the public register ABI.
This is also semantically neutral on hardware with the documented LD behavior.
"""

from __future__ import annotations

import re

CONDITIONAL = re.compile(r"jr(?:eq|ne|lt|le|gt|ge|ult|ule|ugt|uge|c|nc)\b")
LOAD = re.compile(r"ld\.(w|h|uh|b|ub)\s+%r\d+,\s*(.+)")
STACK = re.compile(r"\[%sp\+(\d+)\]")


def _guard_load(lines: list[str]) -> list[str]:
    instruction = lines[-1].split(";", 1)[0].strip()
    match = LOAD.fullmatch(instruction)
    assert match is not None
    stack = STACK.search(instruction)
    extensions = lines[:-1]
    if stack:
        # LLVM spells word/halfword SP offsets in elements, not bytes.
        scale = 4 if match[1] == "w" else 2 if match[1] in ("h", "uh") else 1
        high = 0
        for extension in extensions:
            token = extension.strip().split()[1]
            if not token.isdecimal():
                raise ValueError("symbolic EXT on a stack load is unsupported")
            high = (high << 13) | int(token)
        offset = (high << 6) | int(stack[1])
        offset += 8 // scale
        instruction = STACK.sub(f"[%sp+{offset & 63}]", instruction)
        high = offset >> 6
        chunks = []
        while high:
            chunks.append(high & 8191)
            high >>= 13
        extensions = [f"    ext {chunk}" for chunk in reversed(chunks)]
    return [
        "    pushn %r0",
        "    ld.w %r0, %psr",
        "    sub %sp, 1",
        "    ld.w [%sp+0], %r0",
        "    ld.w %r0, [%sp+1]",
        *extensions,
        "    " + instruction,
        # Preserve the original load's R0 result, including when it is R0.
        "    ld.w [%sp+1], %r0",
        "    ld.w %r0, [%sp+0]",
        "    add %sp, 1",
        "    ld.w %psr, %r0",
        "    popn %r0",
    ]


def preserve_comparison_flags(assembly: str) -> tuple[str, int]:
    """Protect loads in a straight-line CMP -> conditional branch interval.

    Calls/arithmetic/new labels terminate the interval. Store instructions
    and register moves need no protection: the preview bug affects only
    immediate/memory loads. EXT is bundled with its consumer, never split.
    """
    source = assembly.splitlines()
    guards: dict[int, int] = {}
    comparison = False
    candidates: list[tuple[int, int]] = []
    extension_start: int | None = None
    for index, line in enumerate(source):
        code = line.split(";", 1)[0].strip()
        if not code or code.startswith(".") and not code.endswith(":"):
            continue
        if code.startswith("ext ") or code.startswith("ext\t"):
            if extension_start is None:
                extension_start = index
            continue
        start = extension_start if extension_start is not None else index
        extension_start = None
        if re.match(r"cmp\s", code):
            comparison = True
            candidates = []
        elif CONDITIONAL.match(code):
            if comparison:
                for begin, end in candidates:
                    guards[begin] = end
            comparison = False
            candidates = []
        else:
            load = LOAD.fullmatch(code)
            if comparison and load:
                if not load[2].startswith("%"):
                    candidates.append((start, index))
            elif not re.match(r"ld\.(?:w|h|b)\s+\[", code):
                comparison = False
                candidates = []
    output: list[str] = []
    index = 0
    while index < len(source):
        end = guards.get(index)
        if end is None:
            output.append(source[index])
            index += 1
        else:
            output.extend(_guard_load(source[index : end + 1]))
            index = end + 1
    return "\n".join(output) + "\n", len(guards)
