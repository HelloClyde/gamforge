"""CMP constants use the EXT + immediate form supported by both target cores."""

import pytest

from a9288.compiler.backend import imm


@pytest.mark.parametrize(
    "value", [-0x80000000, -33, -32, -1, 0, 31, 32, 63, 255, 0xFFFF, 0x7FFFFFFF]
)
def test_cmp_immediate_preserves_32_bit_constant(value):
    emitted = imm("cmp", "r2", value)
    assert emitted[-1].startswith("    cmp %r2, ")
    operand = int(emitted[-1].split(", ")[1])
    if len(emitted) == 1:
        decoded = operand & 0xFFFFFFFF
    else:
        extension = 0
        for line in emitted[:-1]:
            assert line.startswith("    ext ")
            chunk = int(line.split()[-1])
            assert 0 <= chunk <= 0x1FFF
            extension = (extension << 13) | chunk
        decoded = ((extension << 6) | (operand & 63)) & 0xFFFFFFFF
    assert decoded == value & 0xFFFFFFFF
