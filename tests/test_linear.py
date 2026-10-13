"""Bilinear 3:2 quantization contracts, no game assets or float runtime."""

import pytest

from a9288.compiler.linear import lut_header, packed_column_tables, triplet_tables
from a9288.gui import Conversion
from a9288.paths import DATA
from a9288.targets import display_filter, display_geometry, display_scale


def test_runtime_lut_is_the_exact_deterministic_generator_output():
    assert (DATA / "runtime/c6502_native_linear_lut.h").read_text() == lut_header()
    assert sum(map(len, triplet_tables())) == 768
    assert sum(len(t) * 4 for phase in packed_column_tables() for t in phase) == 12288


def test_prepositioned_words_match_packed_2bpp_pixel_order():
    for phase, columns in zip(triplet_tables(), packed_column_tables(), strict=True):
        for position, table in enumerate(columns):
            for index, word in enumerate(table):
                upper = sum(((index >> (7 - p * 2)) & 1) << (3 - p) for p in range(4))
                lower = sum(((index >> (6 - p * 2)) & 1) << (3 - p) for p in range(4))
                triplet = phase[upper * 16 + lower]
                pixels = [(word >> ((x // 4) * 8 + 6 - (x % 4) * 2)) & 3 for x in range(12)]
                expected = [0] * 12
                expected[position * 3 : position * 3 + 3] = [
                    (triplet >> (4 - p * 2)) & 3 for p in range(3)
                ]
                assert pixels == expected


def test_all_768_triplets_against_an_independent_four_tap_oracle():
    tables = triplet_tables()
    values = set()
    for phase, wy in enumerate((5, 3, 1)):
        for index in range(256):
            expected = 0
            upper = [0 if index & (128 >> x) else 3 for x in range(4)]
            lower = [0 if index & (8 >> x) else 3 for x in range(4)]
            for x, wx in enumerate((5, 3, 1)):
                value = (
                    upper[x] * (6 - wx) * (6 - wy)
                    + upper[x + 1] * wx * (6 - wy)
                    + lower[x] * (6 - wx) * wy
                    + lower[x + 1] * wx * wy
                    + 18
                ) // 36
                values.add(value)
                expected = (expected << 2) | value
            assert tables[phase][index] == expected
    assert values == {0, 1, 2, 3}


def test_linear_option_is_t_only_and_keeps_existing_defaults(tmp_path):
    assert display_scale("9288t") == "1x"
    assert display_geometry("9288t", "1.5x-linear") == (239, 144, 0, 8)
    assert display_filter("1.5x-linear") == "bilinear-4gray"
    for target in ("9288", "9288s", "tsw600"):
        with pytest.raises(ValueError):
            display_scale(target, "1.5x-linear")
    option = Conversion(
        tmp_path / "test.gam",
        "游戏",
        None,
        tmp_path / "test.exe",
        tmp_path,
        tmp_path,
        target="9288t",
        display_scale="1.5x-linear",
    )
    command = option.command(tmp_path)
    assert command[command.index("--display-scale") + 1] == "1.5x-linear"
