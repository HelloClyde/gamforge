"""Long shift ABI: indirect count, saturation, scratch and live registers."""

import random
import shutil
import subprocess

import pytest

from a9288.compiler.boot import DEFAULT_ROME
from a9288.paths import DATA


@pytest.fixture(scope="module")
def shift_runner(tmp_path_factory):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    folder = tmp_path_factory.mktemp("long-shift")
    source = folder / "shift.c"
    executable = folder / "shift.exe"
    source.write_text(
        r"""
#include <stdio.h>
#include <string.h>
#include <stdint.h>
typedef uint8_t c6502_u8;
typedef uint16_t c6502_u16;
typedef uint32_t c6502_u32;
#define C6502_FLAG_C 1u
#define C6502_FLAG_Z 2u
#define C6502_FLAG_V 64u
#define C6502_FLAG_N 128u
static unsigned char ram[65536];
static unsigned char guest_read(unsigned short a){return ram[a];}
static void guest_write(unsigned short a,unsigned char v){ram[a]=v;}
static unsigned short get16(unsigned a){return ram[a]|ram[(a+1)&65535]<<8;}
static void put16(unsigned a,unsigned short v){ram[a]=v;ram[(a+1)&65535]=v>>8;}
static unsigned guest_get32(unsigned short a){
 return get16(a)|((unsigned)get16((unsigned short)(a+2))<<16);
}
static void guest_put32(unsigned short a,unsigned v){
 put16(a,v);put16((unsigned short)(a+2),v>>16);
}
static void set_nz(unsigned *r,unsigned char a){
 r[8]=a;r[9]=(r[9]&~130u)|(a&128u)|(a?0u:2u);
}
#include "c6502_native_long_shift.h"
int main(void){
 unsigned right,value,count,source,operand2,base,p,r[15];
 while(scanf("%u %u %u %u %u %u %u",&right,&value,&count,&source,&operand2,&base,&p)==7){
  memset(ram,0xa5,sizeof(ram));memset(r,0,sizeof(r));
  put16(0x20,source);put16(0x23,operand2);put16(0x2a,base);
  guest_put32(source,value);guest_put32(operand2,count);
  r[4]=0x55;r[5]=0x66;r[6]=0x77;r[7]=0xfd;r[9]=p;
  runtime_shift_long(r,right);
  printf("%u %u %u %u %u %u %u %u %u %u\n",r[4],r[5],r[6],r[9],
   get16(0x20),guest_get32(base+8),guest_get32(source),guest_get32(operand2),r[8],r[7]);
 }
 return 0;
}
""",
        encoding="utf-8",
    )
    subprocess.run(
        [cc, "-O2", "-I", str(DATA / "runtime"), str(source), "-o", str(executable)],
        check=True,
    )

    def run(cases):
        result = subprocess.run(
            [str(executable)],
            input="\n".join(" ".join(map(str, case)) for case in cases) + "\n",
            text=True,
            capture_output=True,
            check=True,
        )
        return [list(map(int, row.split())) for row in result.stdout.splitlines()]

    return run


def test_long_shift_count_is_an_indirect_long_not_pointer_low_byte(shift_runner):
    cases = [
        (right, 0x80026A02, count, 0x2600, pointer, 0x2400, 0x71)
        for right in (0, 1)
        for pointer in (0x2800, 0x7D2B, 0x7DFF)
        for count in (0, 1, 8, 14, 31, 32, 33, 256, 0x1000000, 0xFFFFFFFF)
    ]
    for case, result in zip(cases, shift_runner(cases), strict=True):
        right, value, count, source, _, base, _ = case
        expected = 0 if count >= 32 else (value >> count if right else value << count) & 0xFFFFFFFF
        assert result[5] == expected, case
        assert result[4] == (source if count == 0 else base + 8), case
        assert result[6:8] == [value, count], case
        assert result[9] == 0xFD
    # The resource-bank formula exposed by the reported white screen:
    result = shift_runner([(1, 0x26A02, 14, 0x2600, 0x7D2B, 0x2400, 0x31)])[0]
    assert 0x275 + (result[5] << 2) == 0x299


@pytest.mark.rom
def test_long_shift_full_abi_matches_firmware(shift_runner):
    if not DEFAULT_ROME.is_file():
        pytest.skip("Set A9288_ROME for optional firmware equivalence")
    from py65.devices.mpu65c02 import MPU

    rom = DEFAULT_ROME.read_bytes()

    class Memory:
        def __init__(self):
            self.ram = bytearray([0xA5]) * 65536

        def __getitem__(self, a):
            return rom[0xA8000 + a - 0xD000] if a >= 0xD000 else self.ram[a]

        def __setitem__(self, a, value):
            self.ram[a] = value

    rng = random.Random(9288)
    cases = [
        (right, rng.getrandbits(32), count, 0x2600, 0x7D2B, base, 0x30 | flags)
        for right in (0, 1)
        for count in (0, 1, 8, 14, 31, 32, 255, 256, 0x10000, 0x80000000)
        for base in (0x2400, 0x24FB, 0x7FFA)
        for flags in (0, 0xC3)
    ]
    # The ROM deliberately clears scratch first; inputs may alias it.
    cases += [
        (right, 0x87654321, 14, source, operand2, 0x2400, 0x71)
        for right in (0, 1)
        for source, operand2 in ((0x2408, 0x2800), (0x2409, 0x2800), (0x2600, 0x2408))
    ]
    for case, got in zip(cases, shift_runner(cases), strict=True):
        right, value, count, source, operand2, base, p = case
        mem = Memory()
        ram = mem.ram
        for address, data, size in (
            (0x20, source, 2),
            (0x23, operand2, 2),
            (0x2A, base, 2),
            (source, value, 4),
            (operand2, count, 4),
        ):
            ram[address : address + size] = data.to_bytes(size, "little")
        cpu = MPU(memory=mem)
        cpu.pc = 0xDC0E if right else 0xDA3D
        cpu.a, cpu.x, cpu.y, cpu.sp, cpu.p = 0x55, 0x66, 0x77, 0xFD, p
        ram[0x1FE:0x200] = b"\xff\x1f"
        for _ in range(10000):
            if cpu.pc == 0x2000:
                break
            cpu.step()
        else:
            pytest.fail(f"ROM did not return at {cpu.pc:x}: {case}")
        expected = [cpu.a, cpu.x, cpu.y, cpu.p]
        expected += [
            int.from_bytes(ram[a : a + size], "little")
            for a, size in ((0x20, 2), (base + 8, 4), (source, 4), (operand2, 4))
        ]
        assert got[:8] == expected, case
        assert (got[8] == 0) == bool(cpu.p & 2)
        assert got[8] & 128 == cpu.p & 128
