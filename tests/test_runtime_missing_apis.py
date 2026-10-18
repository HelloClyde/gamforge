"""Native contracts for two APIs encountered by additional C6502 games."""

import random
import shutil
import subprocess

import pytest

from a9288.compiler.boot import DEFAULT_ROME
from a9288.paths import DATA

RUNTIME = DATA / "runtime/c6502_native_runtime.c"
TYPES = """
#include <assert.h>
#include <stdint.h>
typedef uint8_t c6502_u8;
typedef uint16_t c6502_u16;
typedef uint32_t c6502_u32;
"""


def host_run(tmp_path, source):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    code, executable = tmp_path / "probe.c", tmp_path / "probe.exe"
    code.write_text(TYPES + source, encoding="utf-8")
    subprocess.run([cc, "-O2", str(code), "-o", str(executable)], check=True, timeout=30)
    subprocess.run([str(executable)], check=True, timeout=30)


def check_moduli(tmp_path, cases):
    runtime = RUNTIME.read_text(encoding="utf-8")
    helper = (
        "static c6502_u16 signed_mod16"
        + runtime.split("static c6502_u16 signed_mod16", 1)[1].split("\n#endif", 1)[0]
    )
    bridge = runtime.split("case C6502_BRIDGE_c6502_runtime_mod_int:", 1)[1].split("\n#endif", 1)[0]
    checks = []
    for left, right, expected in cases:
        checks.append(
            f"put16(0x20,{left & 65535});put16(0x23,{right & 65535});apply(r);"
            f"assert(get16(0x20)=={expected & 65535});assert(r[4]=={(expected & 65535) >> 8});"
        )
    host_run(
        tmp_path,
        """
static c6502_u8 ram[256];
static c6502_u16 get16(unsigned a){return ram[a]|(ram[a+1]<<8);}
static void put16(unsigned a,c6502_u16 v){ram[a]=v;ram[a+1]=v>>8;}
static void return16(c6502_u32 *r,c6502_u16 v){put16(0x20,v);r[4]=v>>8;}
"""
        + helper
        + "\nstatic void apply(c6502_u32 *r){"
        + bridge
        + "}\nint main(void){c6502_u32 r[15]={0};"
        + "\n".join(checks)
        + "return 0;}\n",
    )


def test_signed_remainder_sign_zero_and_minimum_integer(tmp_path):
    rng = random.Random(7251)
    values = [(a, b) for a in (-32768, -7, 0, 7, 32767) for b in (-32768, -3, -1, 0, 1, 3)]
    values += [(rng.randrange(-32768, 32768), rng.randrange(-32768, 32768)) for _ in range(256)]
    cases = []
    for left, right in values:
        remainder = abs(left) % abs(right) if right else 0
        cases.append((left, right, -remainder if left < 0 else remainder))
    check_moduli(tmp_path, cases)


def test_signed_remainder_matches_original_rom(tmp_path):
    if not DEFAULT_ROME.is_file():
        pytest.skip("Set A9288_ROME for original firmware equivalence")
    from native_rom_reference import FirmwareMemory, invoke_firmware

    rng = random.Random(6502)
    values = [(a, b) for a in (-32768, -7, 0, 7, 32767) for b in (-32768, -3, -1, 0, 1, 3)]
    values += [(rng.randrange(-32768, 32768), rng.randrange(-32768, 32768)) for _ in range(64)]
    cases = []
    for left, right in values:
        memory = FirmwareMemory(5)
        memory.ram[0x20:0x22] = (left & 65535).to_bytes(2, "little")
        memory.ram[0x23:0x25] = (right & 65535).to_bytes(2, "little")
        cpu = invoke_firmware(memory, 0xD5DC, 0x55, b"")
        result = int.from_bytes(memory.ram[0x20:0x22], "little")
        assert cpu.a == result >> 8
        cases.append((left, right, result))
    check_moduli(tmp_path, cases)


def chinese_cases():
    return [
        (0, 0, 0xBADA),
        (144, 80, 0xD6D0),
        (143, 79, 0xA1A1),
        (145, 0, 0xBADA),
        (0, 81, 0xBADA),
        (255, 0, 0xBADA),
        (0, 255, 0xBADA),
    ]


def check_chinese(tmp_path, cases):
    runtime = RUNTIME.read_text(encoding="utf-8")
    helper = (
        "static void native_chinese"
        + runtime.split("static void native_chinese", 1)[1].split("static void api_graphics", 1)[0]
    )
    checks = []
    for x, y, code, accepted in cases:
        checks.append(
            f"calls=0;r[4]={x};ram[0x1800]={y};ram[0x1801]={code & 255};"
            f"ram[0x1802]={code >> 8};native_chinese(r);assert(calls=={int(accepted)});"
        )
        if accepted:
            checks.append(
                f"assert(draw_x=={x}&&draw_y=={y}&&glyph[0]=={code >> 8}"
                f"&&glyph[1]=={code & 255}&&!glyph[2]);"
            )
    host_run(
        tmp_path,
        """
static c6502_u8 ram[65536],glyph[3],draw_x,draw_y;
static unsigned calls;
static c6502_u8 stack8(c6502_u32 *r,unsigned n){return ram[(c6502_u16)(r[10]+n)];}
static void native_text(c6502_u8 x,c6502_u8 y,const c6502_u8 *text){
 ++calls;draw_x=x;draw_y=y;for(unsigned i=0;i<3;++i)glyph[i]=text[i];
}
"""
        + helper
        + "int main(void){c6502_u32 r[15]={0};r[10]=0x1800;"
        + "\n".join(checks)
        + "return 0;}\n",
    )


def test_chinese_code_byte_order_and_cell_clipping(tmp_path):
    check_chinese(tmp_path, [(x, y, code, x <= 144 and y <= 80) for x, y, code in chinese_cases()])


def test_chinese_arguments_and_clipping_match_original_rom(tmp_path):
    if not DEFAULT_ROME.is_file():
        pytest.skip("Set A9288_ROME for original firmware equivalence")
    from native_rom_reference import FirmwareMemory
    from py65.devices.mpu65c02 import MPU

    cases = []
    for x, y, code in chinese_cases():
        memory = FirmwareMemory(5)
        memory.ram[0x28:0x2A] = (0x1800).to_bytes(2, "little")
        memory.ram[0x1800:0x1803] = bytes((y, code & 255, code >> 8))
        memory.ram[0x1FE:0x200] = b"\xff\x1f"
        cpu = MPU(memory=memory)
        cpu.pc = memory[0xE7BE] | memory[0xE7BF] << 8
        cpu.a, cpu.sp, cpu.p = x, 0xFD, 0x30
        for _ in range(100):
            if cpu.pc in (0x2000, 0x876B):
                break
            cpu.step()
        else:
            pytest.fail("Original SysChinese did not reach a glyph or clipped return")
        accepted = cpu.pc == 0x876B
        if accepted:
            assert memory.ram[0x2081:0x2083] == bytes((x, y))
            assert memory.ram[0x20AD:0x20AF] == code.to_bytes(2, "little")
        cases.append((x, y, code, accepted))
    check_chinese(tmp_path, cases)
