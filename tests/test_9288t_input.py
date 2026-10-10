"""The 9288T physical matrix must not leak into the 9288 logical key ABI."""

import shutil
import subprocess

import pytest

from a9288.paths import DATA


def test_9288t_matrix_normalizes_all_six_controls(tmp_path):
    gcc = shutil.which("gcc")
    if not gcc:
        pytest.skip("host GCC is not installed")
    source = tmp_path / "matrix.c"
    source.write_text(
        r"""
#include <assert.h>
typedef unsigned char c6502_u8;
typedef unsigned int c6502_u32;
#define C6502_TARGET_9288T 1
#define C6502_K5_DATA_ADDRESS 1
#define C6502_PORT0_DATA_ADDRESS 2
#define C6502_KEY_ROW_SELECT_ADDRESS 3
static c6502_u8 matrix[8], selected=255, k5, port0;
static volatile c6502_u8 *hardware_byte(unsigned address) {
    unsigned bits=0, row;
    for (row=0; row<8; ++row) if (!(selected & (1u<<row))) bits |= matrix[row];
    if (address==3) return &selected;
    k5=(c6502_u8)~bits; port0=(c6502_u8)~bits;
    return address==1 ? &k5 : &port0;
}
#include "c6502_native_matrix.h"
int main(void) {
    unsigned i,j;
    c6502_u8 current[8];
    const unsigned mapping[6][4]={
        {7,128,7,64},{6,16,7,32},{7,16,7,16},
        {6,32,7,8},{4,16,0,64},{5,16,1,64}
    };
    for (i=0;i<6;++i) {
        for(j=0;j<8;++j) matrix[j]=0;
        matrix[mapping[i][0]]=mapping[i][1];
        native_matrix_snapshot(current,i);
        for(j=0;j<8;++j)
            assert(current[j]==(j==mapping[i][2] ? mapping[i][3] : 0));
        assert(selected==255);
    }
    /* Physical row 1/column 6 is not Enter on 9288T. */
    for(j=0;j<8;++j) matrix[j]=0;
    matrix[1]=64;
    native_matrix_snapshot(current,6);
    for(j=0;j<8;++j) assert(current[j]==0);
    assert(!c6502_matrix_unstable_rows);
    return 0;
}
""",
        encoding="utf-8",
    )
    exe = tmp_path / "matrix.exe"
    subprocess.run(
        [gcc, "-O2", "-I", str(DATA / "runtime"), str(source), "-o", str(exe)],
        check=True,
    )
    subprocess.run([str(exe)], check=True)
