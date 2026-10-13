"""Native C6502 library coverage, independently checked against the A ROM."""

import random
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from a9288.compiler.boot import DEFAULT_ROME
from a9288.paths import DATA


def run_c(source):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    with tempfile.TemporaryDirectory(prefix="c6502-library-") as directory:
        c = Path(directory) / "test.c"
        exe = Path(directory) / "test.exe"
        c.write_text(source, encoding="utf-8")
        subprocess.run([cc, "-O2", "-I", str(DATA / "runtime"), str(c), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


def test_native_semantic_arithmetic16_preserves_byte_flags_and_aliases():
    from py65.devices.mpu65c02 import MPU

    rng = random.Random(9288)
    checks = []
    for subtract in (0, 1):
        for immediate in (0, 1):
            for preserve in (0, 1):
                for _ in range(64):
                    memory = bytearray(65536)
                    initial = bytes(rng.randrange(256) for _ in range(64))
                    memory[:64] = initial
                    left, right, dest = rng.choice(
                        (
                            (0x20, 0x23, 0x20),
                            (0x28, 0x23, 0x28),
                            (0x20, 0x23, 0x21),
                            (0x20, 0x23, 0x24),
                            (0x28, 0x23, 0x29),
                        )
                    )
                    value = rng.randrange(65536)
                    code = [0x38 if subtract else 0x18]
                    for i in range(2):
                        code += [0xA5, left + i]
                        code += (
                            [0xE9 if subtract else 0x69, (value >> (8 * i)) & 255]
                            if immediate
                            else [0xE5 if subtract else 0x65, right + i]
                        )
                        code += [0x85, dest + i]
                    if preserve:
                        code = [0x08, 0x78, *code, 0x28]
                    memory[0x4000 : 0x4000 + len(code)] = bytes(code)
                    cpu = MPU(memory=memory)
                    cpu.pc, cpu.p = 0x4000, 0x30 | rng.randrange(256) & 0xC7
                    status = cpu.p
                    while cpu.pc < 0x4000 + len(code):
                        cpu.step()
                    # Lazy NZ can retain the original producer under PHP/PLP.
                    old_nz = 0 if status & 2 else 128 if status & 128 else 1
                    checks.append(
                        "{const unsigned char init[]={" + ",".join(map(str, initial)) + "};"
                        "memcpy(ram,init,64);unsigned r[15]={0};"
                        f"r[9]={status};r[8]={old_nz};r[10]=ram[40]|(ram[41]<<8);r[11]={left};"
                        f"r[12]={dest if immediate else right};r[13]={value if immediate else dest};"
                        f"semantic_arithmetic16(r,{subtract},{immediate},{preserve});"
                        f"assert(r[4]=={cpu.a}&&r[9]=={cpu.p});"
                        + (f"assert(r[8]=={old_nz});" if preserve else f"assert(r[8]=={cpu.a});")
                        + f"assert(r[10]=={memory[40] | memory[41] << 8});"
                        + "const unsigned char want[]={"
                        + ",".join(map(str, memory[:64]))
                        + "};"
                        + "for(unsigned j=0;j<64;++j)if(j!=40&&j!=41)assert(ram[j]==want[j]);}"
                    )
    run_c(
        r"""
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;typedef unsigned c6502_u32;
#define C6502_FLAG_C 1u
#define C6502_FLAG_Z 2u
#define C6502_FLAG_V 64u
#define C6502_FLAG_N 128u
static unsigned char ram[65536];
static struct {unsigned char *ram;} c6502_native_state={ram};
static void set_nz(unsigned*r,unsigned char v){r[8]=v;r[9]=(r[9]&~130u)|(v&128u)|(!v?2u:0);}
#include "c6502_native_arithmetic16.h"
int main(void){
"""
        + "\n".join(checks)
        + "return 0;}"
    )


@pytest.mark.skipif(
    not DEFAULT_ROME.is_file(), reason="Set A9288_ROME for optional ROM equivalence"
)
def test_native_menu_navigation_and_drawing_match_firmware():
    from native_rom_reference import trace_rom_menu

    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    translate = (
        "static c6502_u8 translate_key"
        + runtime.split("static c6502_u8 translate_key", 1)[1].split(
            "static void api_translate_message", 1
        )[0]
    )
    mapping = {
        0x27: 0x2F,
        0x28: 0x2E,
        0x22: 0x35,
        0x23: 0x38,
        0x24: 0x37,
        0x25: 0x39,
        0x20: 0x3A,
        0x21: 0x3B,
    }
    cases = [
        (5, 1, 0, 0, 0, (0x27,)),
        (5, 1, 0, 0, 0, (0x28,)),
        (5, 1, 0, 0, 0, (0x23, 0x27)),
        (5, 1, 0, 0, 0, (0x22, 0x27)),
        (5, 1, 0, 0, 2, (0x22, 0x27)),
        (5, 1, 0, 0, 0, (0x24, 0x27)),
        (5, 1, 0, 0, 0, (0x25, 0x27)),
        (10, 2, 0, 0, 0, (0x23, 0x25, 0x27)),
        (12, 2, 11, 0, 0, (0x28,)),
        (12, 2, 3, 4, 0, (0x27,)),
        (5, 1, 20, 0, 0, (0x27,)),
        (5, 1, 0, 0, 1, (0x27,)),
        (7, 1, 0, 0, 0, (0x23,) * 5 + (0x27,)),
        (7, 1, 0, 0, 0, (0x21, 0x27)),
        (7, 1, 6, 0, 0, (0x20, 0x27)),
    ]
    rng = random.Random(4980)
    for _ in range(48):
        count, columns = rng.choice(((7, 1), (12, 2), (13, 2)))
        keys = tuple(rng.choice((0x20, 0x21, 0x22, 0x23, 0x24, 0x25)) for _ in range(5))
        cases.append((count, columns, rng.randrange(count), 0, rng.randrange(4), keys + (0x28,)))
    checks = []
    ids = {
        "SysLcdPartClear": 1,
        "SysPrintString": 2,
        "SysLcdReverse": 3,
        "SysPicture": 4,
        "SysIconSetLeftScrollBar": 5,
        "SysIconScrollBarUpArrow": 6,
        "SysIconScrollBarDownArrow": 7,
    }
    for count, columns, sel, start, style, keys in cases:
        expected = trace_rom_menu(count, columns, sel, start, style, tuple((5, k) for k in keys))
        data = []
        for name, args in expected["calls"]:
            data.append(ids[name])
            if name == "SysPrintString":
                data += args[:2] + list(bytes.fromhex(args[2])) + [0]
            else:
                data += args
        h = 2166136261
        for v in data:
            h = ((h ^ v) * 16777619) & 0xFFFFFFFF
        checks.append(
            f"init({count},{columns},{sel},{start},{style});key_count={len(keys)};"
            + "".join(f"keys[{i}]={mapping[key]};" for i, key in enumerate(keys))
            + "menu_run(r,0x2600,0x2608);"
            + f'if(r[4]!={expected["result"]}||h!={h}u){{printf("case {len(checks)} ({count},{columns},{sel},{style},{keys}): result=%u hash=%08x wanted {h:08x}\\n",r[4],h);for(unsigned j=0;j<used;++j)printf("%u,",observed[j]);puts("");return 1;}}'
            + "const unsigned char want[]={"
            + ",".join(map(str, expected["env"]))
            + "};"
            + "assert(!memcmp(ram+0x2608,want,8));"
            + f"assert(polls=={expected['messages']});"
            + "assert(r[10]==0x1800&&c6502_native_state.keyboard_type==7&&"
            + "c6502_native_state.input_filter==9&&c6502_native_state.keyboard_state==0x1234);"
            + "for(unsigned i=0;i<96;++i)assert((ram[0x412+i*32]&1)==(i&1));"
        )
    source = (
        r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;typedef unsigned c6502_u32;
#define C6502_RESOURCE_SCRATCH_SIZE 1920u
#define C6502_NEEDS_c6502_adapter_guimenu 1
#define NATIVE_LINEAR_BEGIN() ((void)0)
#define NATIVE_LINEAR_END() ((void)0)
static unsigned char ram[65536],c6502_resource_scratch[1920],keys[64],c6502_timer_pending;
static unsigned h,polls,key_count,observed[8192],used;
static struct {unsigned char *ram;unsigned short keyboard_state;unsigned char keyboard_type,input_filter;} c6502_native_state={ram};
static unsigned char guest_read(unsigned short a){return ram[a];}
static void guest_write(unsigned short a,unsigned char v){ram[a]=v;}
static unsigned short guest_get16(unsigned short a){return ram[a]|(ram[(a+1)&65535]<<8);}
static void return8(unsigned*r,unsigned char v){r[4]=v;}
static void add(unsigned v){assert(used<8192);observed[used++]=v&255;h=(h^(v&255))*16777619u;}
static void horizontal_span(unsigned char x,unsigned char x1,unsigned char y,int op){
 if(op==0)return;assert(op==2);
 /* Reverse is observed as one rectangle, not sixteen identical rows. */
 if(!(y%16)){add(3);add(x);add(y);add(x1);add(y+15);}
}
static void native_text(unsigned char x,unsigned char y,const unsigned char*s){add(2);add(x);add(y);do{add(*s);}while(*s++);}
static void native_picture(unsigned char x,unsigned char y,unsigned char x1,unsigned char y1,unsigned short src,unsigned char flag){add(4);add(x);add(y);add(x1);add(y1);add(src);add(src>>8);add(flag);}
static void native_icon_left_scroll(unsigned char percent){add(5);add(percent);}
static void native_icon_arrow(int up,unsigned char on){add(up?6:7);add(on);}
static unsigned char native_window_key(int wait){assert(wait&&polls<key_count);assert(c6502_native_state.keyboard_type==2&&c6502_native_state.input_filter==3);return keys[polls++];}
static void native_update_timer(void){}
static void native_refresh_if_due(void){}
static void c6502_native_present(void){}
"""
        + translate
        + r"""
#include "c6502_native_menu.h"
static unsigned r[15];
static void init(unsigned count,unsigned cols,unsigned sel,unsigned start,unsigned style){
 memset(ram,0,sizeof(ram));memset(r,0,sizeof(r));r[4]=sel;r[10]=0x1800;
 unsigned char m[]={count,cols,0x10,0x26,style,0x20,0x26};memcpy(ram+0x2600,m,7);
 unsigned char env[]={10,149,0,79,start,0,0,0};memcpy(ram+0x2608,env,8);
 for(unsigned i=0;i<cols;++i)ram[0x2610+i]=i*70;
 for(unsigned i=0;i<count;++i){unsigned a=0x2700+i*7,text=0x3000+i*16;
  ram[0x2620+i*2]=a;ram[0x2621+i*2]=a>>8;
  unsigned char item[]={4,text,text>>8,0,64,0,65};memcpy(ram+a,item,7);memcpy(ram+text,"item",5);
 }
 for(unsigned i=0;i<96;++i)ram[0x412+i*32]=i&1;
 polls=used=0;h=2166136261u;c6502_native_state.keyboard_state=0x1234;c6502_native_state.keyboard_type=7;c6502_native_state.input_filter=9;
 /* menu_draw clears the same fixed rectangle in these fixtures. */
 add(1);add(10);add(0);add(149);add(79);
}
int main(void){
"""
    )
    # To observe EVERY page clear without changing production code, intercept
    # the first horizontal clear row rather than counting at fixture init.
    source = source.replace(
        "if(op==0)return;", "if(op==0){if(y==0){add(1);add(x);add(0);add(x1);add(79);}return;}"
    )
    source = source.replace("add(1);add(10);add(0);add(149);add(79);", "")
    run_c(source + "\n".join("{" + c + "}" for c in checks) + "return 0;}")


@pytest.mark.skipif(
    not DEFAULT_ROME.is_file(), reason="Set A9288_ROME for optional ROM equivalence"
)
def test_native_lcd_clear_fill_and_annunciators_match_firmware():
    from native_rom_reference import FirmwareMemory, invoke_firmware

    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    helpers = (
        "static c6502_u16 lcd_address"
        + runtime.split("static c6502_u16 lcd_address", 1)[1].split("static void line", 1)[0]
    )
    helpers += (
        "static c6502_u8 screen_bit"
        + runtime.split("static c6502_u8 screen_bit", 1)[1].split("/* The 9288 font renderer", 1)[0]
    )
    helpers += (
        "static int picture_source_disjoint"
        + runtime.split("static int picture_source_disjoint", 1)[1].split(
            "static void integer_to_ascii", 1
        )[0]
    )
    cases = [
        (5, 0xE7F7, 0, b"", "native_lcd_clear()"),
        (5, 0xE791, 0, bytes.fromhex("0030"), "native_picture_fill(0x3000)"),
    ]
    for value in range(256):
        cases.append((6, 0xE8E3, value, b"", f"native_icon_left_scroll({value})"))
    for up, slot in ((0, 0xE812), (1, 0xE815)):
        for value in (0, 1, 2, 255):
            cases.append((6, slot, value, b"", f"native_icon_arrow({up},{value})"))
    checks = []
    for bank, slot, a, args, call in cases:
        mem = FirmwareMemory(bank)
        mem.ram[:] = bytes((i * 29 + 17) & 255 for i in range(65536))
        mem.ram[0x3E5:0x3EA] = bytes.fromhex("0100040010")
        pc = mem[slot] | mem[slot + 1] << 8
        invoke_firmware(mem, pc, a, args)
        h = 2166136261
        for v in mem.ram[0x401:0x1001]:
            h = ((h ^ v) * 16777619) & 0xFFFFFFFF
        checks.append(
            "for(unsigned i=0;i<65536;++i)ram[i]=(i*29+17)&255;"
            'memcpy(ram+0x3e5,"\1\0\4\0\20",5);'
            + call
            + ";unsigned h=2166136261u;"
            + "for(unsigned i=0x401;i<0x1001;++i)h=(h^ram[i])*16777619u;"
            + f'if(h!={h}u){{printf("LCD case {len(checks)}: %08x != {h:08x}\\n",h);return 1;}}'
        )
    run_c(
        r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;typedef unsigned c6502_u32;
#define C6502_RAM_SIZE 32768u
#define C6502_RESOURCE_SCRATCH_SIZE 1920u
#define C6502_GUEST_STRIDE 20u
#define C6502_GAME_PHYSICAL_BASE 0x20d000u
#define C6502_VIEW_Y 24u
#define C6502_FRAME_STRIDE 80u
#define C6502_NEEDS_c6502_adapter_syslcdclear 1
#define C6502_NEEDS_c6502_adapter_syspicturefill_direct 1
#define NATIVE_LINEAR_BEGIN() ((void)0)
#define NATIVE_LINEAR_END() ((void)0)
static unsigned char ram[65536],c6502_resource_scratch[1920],fb[19200],c6502_previous_frame[1920],c6502_output_ready;
static unsigned c6502_expand_2x[256];
#define C6502_FRAMEBUFFER fb
static struct {unsigned lcd_span_rows,lcd_span_bytes,mapped_lcd_bytes,framebuffer_bytes;
 unsigned picture_direct_bytes,picture_staged_bytes,picture_ordered_calls,picture_frame_commits;} c6502_perf;
static void native_capture_keys(void){}
static struct {unsigned char *ram;unsigned short banks[16];unsigned char *game;unsigned game_size;} c6502_native_state={ram};
static unsigned char guest_read(unsigned short a){return ram[a==0x400?0x1000:a];}
static void guest_write(unsigned short a,unsigned char v){ram[a==0x400?0x1000:a]=v;}
static unsigned short get16(unsigned a){return ram[a]|(ram[a+1]<<8);}
static unsigned char stack8(unsigned*r,unsigned n){return ram[(unsigned short)(r[10]+n)];}
static unsigned short stack16(unsigned*r,unsigned n){return stack8(r,n)|(stack8(r,n+1)<<8);}
"""
        + helpers
        + '\n#include "c6502_native_lcd_services.h"\nint main(void){'
        + "\n".join("{" + c + "}" for c in checks)
        + "return 0;}"
    )
