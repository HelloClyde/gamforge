"""3:2 picture quantization contracts, no game assets or float runtime."""

import random
import shutil
import subprocess

import pytest

from a9288.compiler.linear import (
    lut_header,
    packed_column_tables,
    sharp_byte_tables,
    triplet_tables,
)
from a9288.gui import Conversion
from a9288.paths import DATA
from a9288.targets import display_filter, display_geometry, display_scale


def test_runtime_lut_is_the_exact_deterministic_generator_output():
    assert (DATA / "runtime/c6502_native_linear_lut.h").read_text() == lut_header()
    assert sum(map(len, triplet_tables())) == 768
    assert sum(len(t) * 4 for phase in packed_column_tables() for t in phase) == 12288
    single, mixed = sharp_byte_tables()
    assert (len(single) + sum(map(len, mixed))) * 4 == 3072


def test_compact_sharp_tables_exhaust_every_upper_lower_byte_pair():
    single, mixed = sharp_byte_tables()
    old = packed_column_tables(sharp=True)
    for upper in range(256):
        for lower in range(256):
            interleaved = sum(
                (((upper >> bit) & 1) * 2 + ((lower >> bit) & 1)) << (bit * 2) for bit in range(8)
            )
            indices = (
                interleaved >> 10,
                (interleaved >> 6) & 255,
                (interleaved >> 2) & 255,
                (interleaved & 63) << 2,
            )
            words = [
                tables[0][indices[0]]
                | tables[1][indices[1]]
                | tables[2][indices[2]]
                | tables[3][indices[3]]
                for tables in old
            ]
            assert single[lower] == words[0]
            assert (
                mixed[0][(upper & 240) | (lower >> 4)]
                | mixed[1][((upper & 15) << 4) | (lower & 15)]
                == words[1]
            )
            assert single[upper] == words[2]


@pytest.mark.parametrize("sharp", [False, True])
def test_prepositioned_words_match_packed_2bpp_pixel_order(sharp):
    for phase, columns in zip(
        triplet_tables(sharp=sharp), packed_column_tables(sharp=sharp), strict=True
    ):
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


@pytest.mark.parametrize("sharp,weights", [(False, (5, 3, 1)), (True, (6, 3, 0))])
def test_all_768_triplets_against_an_independent_four_tap_oracle(sharp, weights):
    tables = triplet_tables(sharp=sharp)
    values = set()
    for phase, wy in enumerate(weights):
        for index in range(256):
            expected = 0
            upper = [0 if index & (128 >> x) else 3 for x in range(4)]
            lower = [0 if index & (8 >> x) else 3 for x in range(4)]
            for x, wx in enumerate(weights):
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


def _sharp_lut_image(source):
    """Use the runtime's clamped four-column/three-phase addressing."""
    height, width = len(source), len(source[0])
    tables = triplet_tables(sharp=True)
    output = []
    for y in range((height * 3 + 1) // 2):
        phase, pair_y = y % 3, y // 3 * 2
        top = pair_y - 1 if phase == 0 else pair_y + (phase == 2)
        bottom = pair_y if phase == 0 else top + 1
        top, bottom = max(0, top), min(height - 1, bottom)
        row = []
        for x in range((width * 3 + 1) // 2):
            pair_x = x // 3 * 2
            index = 0
            for sy in (top, bottom):
                for sx in range(pair_x - 1, pair_x + 3):
                    index = index * 2 + source[sy][max(0, min(width - 1, sx))]
            row.append((tables[phase][index] >> (4 - 2 * (x % 3))) & 3)
        output.append(row)
    return output


def _area_oracle(source):
    """Integrate overlapping rectangles, independent of triplet/phase weights.

    A source pixel has side 3 and a destination pixel has side 2. Duplicate
    the final edge only for the fractional last destination of odd sizes.
    Black coverage is 0..4 and is converted to four gray levels exactly once.
    """
    height, width = len(source), len(source[0])
    output = []
    for y in range((height * 3 + 1) // 2):
        row = []
        for x in range((width * 3 + 1) // 2):
            black = 0
            for sy in range(y * 2 // 3, (y * 2 + 1) // 3 + 1):
                overlap_y = min(y * 2 + 2, sy * 3 + 3) - max(y * 2, sy * 3)
                for sx in range(x * 2 // 3, (x * 2 + 1) // 3 + 1):
                    overlap_x = min(x * 2 + 2, sx * 3 + 3) - max(x * 2, sx * 3)
                    black += overlap_x * overlap_y * source[min(sy, height - 1)][min(sx, width - 1)]
            row.append(((4 - black) * 3 + 2) // 4)
        output.append(row)
    return output


def test_sharp_all_2x2_patterns_match_independent_area_coverage():
    for pattern in range(16):
        source = [[(pattern >> (y * 2 + x)) & 1 for x in range(2)] for y in range(2)]
        assert _sharp_lut_image(source) == _area_oracle(source)


@pytest.mark.parametrize("width,height", [(1, 1), (7, 7), (8, 8), (159, 96)])
def test_sharp_clamped_edges_and_complete_lcd_match_independent_area_oracle(width, height):
    randomizer = random.Random(9288)
    source = [[randomizer.randrange(2) for _ in range(width)] for _ in range(height)]
    assert _sharp_lut_image(source) == _area_oracle(source)


def test_sharp_single_pixel_lines_keep_a_black_core_without_neighbour_bleed():
    source = [[int(x == 2) for x in range(8)] for _ in range(8)]
    expected_row = [3, 3, 3, 0, 2, 3, 3, 3, 3, 3, 3, 3]
    assert _sharp_lut_image(source) == [expected_row] * 12
    horizontal = [list(row) for row in zip(*source, strict=True)]
    assert _sharp_lut_image(horizontal) == [[gray] * 12 for gray in expected_row]


def test_sharp_even_sized_image_has_horizontal_vertical_and_diagonal_symmetry():
    randomizer = random.Random(33)
    source = [[randomizer.randrange(2) for _ in range(8)] for _ in range(6)]
    output = _sharp_lut_image(source)
    assert _sharp_lut_image([row[::-1] for row in source]) == [row[::-1] for row in output]
    assert _sharp_lut_image(source[::-1]) == output[::-1]
    assert _sharp_lut_image([list(row) for row in zip(*source, strict=True)]) == [
        list(row) for row in zip(*output, strict=True)
    ]


@pytest.mark.parametrize("sharp", [False, True])
def test_preprocessor_keeps_only_the_requested_filter_tables(sharp):
    compiler = shutil.which("gcc")
    if compiler is None:
        pytest.skip("host GCC required for C preprocessor contract")
    source = ("#define C6502_T_FILTER_SHARP 1\n" if sharp else "") + lut_header()
    output = subprocess.run(
        [compiler, "-E", "-P", "-x", "c", "-"],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    if sharp:
        assert "c6502_linear_lut" not in output
        assert "c6502_linear_spread" not in output
        assert output.count("static const c6502_u32 c6502_sharp_single[256]") == 1
        assert output.count("static const c6502_u32 c6502_sharp_mixed[2][256]") == 1
        assert output.count("0x") == 3 * 256
    else:
        assert "c6502_sharp_single" not in output
        assert "c6502_sharp_mixed" not in output
        assert output.count("static const c6502_u32 c6502_linear_lut[3][1024]") == 1
        assert output.count("static const c6502_u16 c6502_linear_spread[256]") == 1
        assert output.count("0x") == 3 * 4 * 256 + 256


def test_compiled_sharp_dirty_ranges_include_text_only_changes(tmp_path):
    compiler = shutil.which("gcc")
    if compiler is None:
        pytest.skip("host GCC required for actual sharp row scheduling")
    source = tmp_path / "sharp_dirty.c"
    source.write_text(
        r"""
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;typedef unsigned c6502_u32;
#define C6502_T_FILTER_SHARP 1
#define C6502_VIEW_Y 8u
#define C6502_FRAME_STRIDE 60u
#define C6502_HOST_FRAME_BYTES 9600u
static c6502_u8 frame[9600] __attribute__((aligned(4)));
static c6502_u8 c6502_t_frame_shadow[9600] __attribute__((aligned(4)));
static c6502_u8 c6502_previous_frame[1920],native_text_rows[144],native_text_layer_dirty[1920];
static c6502_u32 native_text_pending,native_text_active_rows,c6502_frame_valid=1;
static struct {c6502_u32 linear_rows,t_packed_groups,framebuffer_bytes,linear_batches,
 linear_unchanged_spans;} c6502_perf;
#define C6502_FRAMEBUFFER frame
static void native_text_layer_apply(unsigned first,unsigned last,unsigned y,unsigned physical){}
static unsigned native_text_layer_merge_word(unsigned y,unsigned byte,unsigned word,unsigned count){return word;}
static void native_text_layer_discard(void){
 native_text_pending=native_text_active_rows=0;
 memset(native_text_rows,0,sizeof(native_text_rows));
 memset(native_text_layer_dirty,0,sizeof(native_text_layer_dirty));
}
static unsigned lcd_address(unsigned x,unsigned y){return y*20+x;}
#include "c6502_native_linear.h"
int main(void){
 unsigned y,top,bottom;unsigned char ram[1920],one=0xa5;
 memset(frame,255,sizeof(frame));memset(c6502_t_frame_shadow,255,sizeof(c6502_t_frame_shadow));
 for(y=0;y<96;++y){
  unsigned before=c6502_perf.linear_rows;
  native_t_write_byte(8,y,one);assert(c6502_perf.linear_rows-before==2);
  before=c6502_perf.linear_rows;
  native_text_layer_dirty[y*20+8]=1;++native_text_pending;
  native_t_write_byte(8,y,one);assert(c6502_perf.linear_rows-before==2);
  assert(!native_text_pending);
 }
 for(top=0;top<96;++top)for(bottom=top;bottom<96;++bottom){
  unsigned before=c6502_perf.linear_rows;
  native_linear_begin();native_linear_touch(8,8,top,bottom);native_linear_end();
  assert(c6502_perf.linear_rows-before==bottom*3/2+2-top*3/2);
 }
 memcpy(ram,c6502_previous_frame,sizeof(ram));
 for(y=0;y<96;++y){
  unsigned before=c6502_perf.linear_rows;
  ram[y*20+8]^=1;assert(native_linear_update_shadow(ram)==1);
  assert(c6502_perf.linear_rows-before==2);
  before=c6502_perf.linear_rows;
  native_text_layer_dirty[y*20+8]=1;++native_text_pending;
  assert(native_linear_update_shadow(ram)==1);
  assert(c6502_perf.linear_rows-before==2&&!native_text_pending);
 }
 native_text_active_rows=1;native_text_rows[0]=1;ram[0]^=1;
 y=c6502_perf.linear_rows;assert(native_linear_update_shadow(ram)==96);
 assert(c6502_perf.linear_rows-y==144&&!native_text_active_rows);
 return 0;
}
""",
        encoding="utf-8",
    )
    exe = tmp_path / "sharp_dirty.exe"
    subprocess.run(
        [compiler, "-O2", "-I", str(DATA / "runtime"), str(source), "-o", str(exe)], check=True
    )
    subprocess.run([str(exe)], check=True, timeout=20)


def test_linear_option_is_t_only_and_preserves_sharp_default(tmp_path):
    assert display_scale("9288t") == "1.5x-sharp"
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
