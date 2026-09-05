"""Execute native adapter helpers on the PC, without the player/interpreter."""

import random
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from a9288.compiler.boot import DEFAULT_ROME
from a9288.paths import DATA


def performance_globals(runtime):
    return (
        "static c6502_u32 c6502_last_frame_tick;"
        + runtime.split("static c6502_u32 c6502_last_frame_tick;", 1)[1].split(
            "static void bytes_set", 1
        )[0]
        + "\nstatic c6502_u32 native_clock(void){return 0;}\n"
    )


class NativeRuntimeHelpersTest(unittest.TestCase):
    def test_query_box_contract_artwork_and_restore_match_rom(self):
        if not DEFAULT_ROME.is_file():
            self.skipTest("Set A9288_ROME for optional firmware equivalence")
        from native_rom_reference import trace_rom_query_box

        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        helper = (
            '#include "c6502_native_query_assets.h"'
            + runtime.split('#include "c6502_native_query_assets.h"', 1)[1].split(
                "/* E.BIN bank 9 $8195", 1
            )[0]
        )
        translate = (
            "static c6502_u8 translate_key"
            + runtime.split("static c6502_u8 translate_key", 1)[1].split(
                "static void api_translate_message", 1
            )[0]
        )
        wrapper = (
            "static void query_box(c6502_u32 *r)"
            + runtime.split("static void query_box(c6502_u32 *r)", 1)[1].split(
                "static void api_graphics", 1
            )[0]
        )

        def draw_hash(calls):
            data = bytearray()
            for name, args in calls:
                if name == "clear":
                    for y in range(args[1], args[3] + 1):
                        data.extend((1, args[0], args[2], y, 0))
                elif name in ("rect", "fill"):
                    data.extend((2, *args, int(name == "fill")))
                elif name == "text":
                    data.extend((3, *args[:2]))
                    data.extend(bytes.fromhex(args[2]) + b"\0")
                elif name == "picture":
                    x, y, x1, y1, _, flag, pixels = args
                    self.assertEqual(flag, 0)
                    width = x1 - x + 1
                    stride = (width + 7) // 8
                    pixels = bytes.fromhex(pixels)
                    for row in range(y1 - y + 1):
                        data.extend((4, x, y + row, width))
                        data.extend(pixels[row * stride : (row + 1) * stride])
            h = 2166136261
            for v in data:
                h = ((h ^ v) * 16777619) & 0xFFFFFFFF
            return h

        text = "确定退出".encode("gbk")
        cases = []
        for selection in (0, 1):
            for keys in (
                (0x2F,),
                (0x2E,),
                (0x37, 0x2F),
                (0x38, 0x38, 0x2F),
                (0x35, 0x2F),
                (0x39, 0x2F),
                (2, 3, 0, 1, 0x2F),
                (0x15,),
                (0x26,),
            ):
                cases.append((text, selection, 0, keys, True))
        cases += [(b"", 0, 0, (0x2E,), True), (b"hello", 1, 0, (0x2F,), False)]
        # The nonzero infoType branch receives a six-byte picture descriptor.
        for info_type in (1, 255):
            cases.append((bytes((31, 8, 2, 8, 6, 0x26, 0x5A, 0xA5)), 0, info_type, (0x2E,), True))
        checks = []
        for index, (text, selection, info_type, keys, alloc_ok) in enumerate(cases):
            expected = trace_rom_query_box(text, selection, info_type, keys, alloc_ok=alloc_ok)
            expected_hash = draw_hash(expected["calls"])
            checks.append(
                "{ const unsigned char text[]={" + ",".join(map(str, text + b"\0")) + "};"
                "for(unsigned i=0;i<65536;++i)ram[i]=(i*29+17)&255;"
                "memcpy(ram+0x2600,text,sizeof(text));memcpy(before,ram,sizeof(ram));"
                "c6502_native_state.keyboard_state=0x1234;c6502_native_state.keyboard_type=7;c6502_native_state.input_filter=9;"
                "polls=0;presents=0;h=2166136261u;key_count="
                + str(len(keys))
                + ";alloc_ok="
                + str(int(alloc_ok))
                + ";"
                + "".join(f"keys[{i}]={key};" for i, key in enumerate(keys))
                + f"r[4]={selection};r[10]=0x1800;ram[0x1800]={info_type};ram[0x1801]=0;ram[0x1802]=0x26;query_box(r);"
                f"if(r[4]!={expected['result']}||h!={expected_hash}u||polls!={expected['messages']})"
                f'{{printf("query case {index}: result=%u hash=%08x polls=%u\\n",r[4],h,polls);return 1;}}'
                "assert(c6502_native_state.keyboard_state==0x1234&&c6502_native_state.keyboard_type==7&&c6502_native_state.input_filter==9);"
                "assert(r[10]==0x1800);assert(!memcmp(ram+0x400,before+0x400,1920));"
                f"assert(presents{'>=2' if alloc_ok else '==0'});" + "}"
            )
        source = (
            r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;typedef unsigned c6502_u32;
#define C6502_RESOURCE_SCRATCH_SIZE 1920u
static unsigned char ram[65536],before[65536],c6502_resource_scratch[1920],keys[20],c6502_timer_pending;
static unsigned h,polls,presents,key_count,alloc_ok;
static struct {unsigned char *ram;unsigned short keyboard_state;unsigned char keyboard_type,input_filter;} c6502_native_state={ram};
static void *checked_malloc(unsigned n){assert(n==18*59);return alloc_ok?malloc(n):NULL;}
#define malloc checked_malloc
static unsigned char guest_read(unsigned short a){return ram[a];}
static void guest_write(unsigned short a,unsigned char b){ram[a]=b;}
static unsigned short lcd_address(unsigned x,unsigned y){return 0x400+y*20+x;}
static unsigned char stack8(unsigned *r,unsigned n){return ram[r[10]+n];}
static unsigned short stack16(unsigned *r,unsigned n){return stack8(r,n)|(stack8(r,n+1)<<8);}
static void return8(unsigned *r,unsigned char v){r[4]=v;}
static void add(unsigned v){h=(h^(v&255))*16777619u;}
static void bit(unsigned x,unsigned y,unsigned value){unsigned char*m=ram+lcd_address(x/8,y);unsigned mask=128>>(x%8);*m=(*m&~mask)|(value?mask:0);}
static void horizontal_span(unsigned x,unsigned x1,unsigned y,int op){add(1);add(x);add(x1);add(y);add(op);for(;x<=x1;++x)bit(x,y,0);}
static void rectangle(unsigned x,unsigned y,unsigned x1,unsigned y1,int fill){add(2);add(x);add(y);add(x1);add(y1);add(fill);for(unsigned yy=y;yy<=y1;++yy)for(unsigned xx=x;xx<=x1;++xx)if(fill||yy==y||yy==y1||xx==x||xx==x1)bit(xx,yy,1);}
static void native_text(unsigned x,unsigned y,const unsigned char *s){add(3);add(x);add(y);do{add(*s);}while(*s++);bit(x,y,1);}
static void blit_packed_row(unsigned screen,unsigned x,unsigned y,unsigned width,const unsigned char *s){assert(screen==0x400);add(4);add(x);add(y);add(width);for(unsigned b=0;b<(width+7)/8;++b)add(s[b]);for(unsigned i=0;i<width;++i)bit(x+i,y,s[i/8]&(128>>(i%8)));}
static void native_picture(unsigned x,unsigned y,unsigned x1,unsigned y1,unsigned short source,unsigned flag){assert(!flag);unsigned width=x1-x+1;for(;y<=y1;++y){blit_packed_row(0x400,x,y,width,ram+source);source+=(width+7)/8;}}
static unsigned char native_window_key(int wait){assert(wait&&polls<key_count);assert(c6502_native_state.keyboard_type==2&&c6502_native_state.input_filter==2);return keys[polls++];}
static void c6502_native_present(void){++presents;}
static void native_update_timer(void){}
static void native_refresh_if_due(void){}
"""
            + translate
            + helper
            + wrapper
            + "int main(void){unsigned r[15]={0};"
            + "\n".join(checks)
            + """
/* Invalid selections would index beyond the ROM artwork table. */
for(unsigned selection=2;selection<256;++selection){
 polls=presents=0;query_box_run(r,selection,0,0x2600);
 assert(r[4]==255&&!polls&&!presents);
}
return 0;}
"""
        )
        with tempfile.TemporaryDirectory(prefix="c6502-query-rom-") as folder:
            path = Path(folder) / "test.c"
            exe = Path(folder) / "test.exe"
            path.write_text(source, encoding="utf-8")
            subprocess.run(
                [cc, "-O2", "-I", str(DATA / "runtime"), str(path), "-o", str(exe)], check=True
            )
            subprocess.run([str(exe)], check=True)

    def test_matrix_keys_are_edges_and_only_directions_repeat(self):
        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        constants = (
            "#define C6502_IO_BASE"
            + runtime.split("#define C6502_IO_BASE", 1)[1].split("extern const", 1)[0]
        )
        keys = (
            "static c6502_u8 c6502_key_previous[8];"
            + runtime.split("static c6502_u8 c6502_key_previous[8];", 1)[1].split(
                "static c6502_u32 c6502_last_frame_tick", 1
            )[0]
        )
        helper = (
            "static c6502_u8 poll_hardware_key"
            + runtime.split("static c6502_u8 poll_hardware_key", 1)[1].split(
                "static c6502_u32 native_clock", 1
            )[0]
        )
        source = (
            """
#include <assert.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned int c6502_u32;
static unsigned now,psr=0x10,c6502_validation_key_count,c6502_validation_keys[32][4];
static unsigned char matrix[8],rowreg=255,k5=0x43,port=0x12,factors,k5data,portdata;
static unsigned native_clock(void){return now;}
static unsigned read_psr(void){return psr;}
static void write_psr(unsigned p){psr=p;}
"""
            + constants
            + keys
            + """
static volatile unsigned char *hardware_byte(unsigned address){
 unsigned active=0;for(unsigned i=0;i<8;++i)if(!(rowreg&(1u<<i)))active|=matrix[i];
 switch(address){
 case C6502_KEY_ROW_SELECT_ADDRESS:return &rowreg;
 case C6502_K5_FUNCTION_ADDRESS:return &k5;
 case C6502_PORT0_IOCTRL_ADDRESS:return &port;
 case C6502_KEY_IRQ_FACTOR_ADDRESS:return &factors;
 case C6502_K5_DATA_ADDRESS:k5data=~active;return &k5data;
 case C6502_PORT0_DATA_ADDRESS:portdata=~active;return &portdata;
 default:assert(0);return &factors;
 }
}
"""
            + helper
            + """
int main(void){
 assert(poll_hardware_key()==255);
 now=1;matrix[1]=64;assert(poll_hardware_key()==0x2f);
 now=2;assert(poll_hardware_key()==255);
 now=1000;assert(poll_hardware_key()==255); /* Enter never auto-repeats */
 now=1001;matrix[1]=0;assert(poll_hardware_key()==255);
 now=1002;matrix[1]=64;assert(poll_hardware_key()==0x2f);
 now=1003;matrix[1]=0;matrix[7]=32;assert(poll_hardware_key()==0x37);
 now=1082;assert(poll_hardware_key()==255);
 now=1083;assert(poll_hardware_key()==0x37);
 now=1102;assert(poll_hardware_key()==255);
 now=1103;assert(poll_hardware_key()==0x37);
 now=1104;matrix[7]=0;assert(poll_hardware_key()==255);
 assert(psr==0x10 && rowreg==255 && k5==0x43 && port==0x12);
 return 0;
}
"""
        )
        with tempfile.TemporaryDirectory(prefix="c6502-matrix-") as folder:
            c = Path(folder) / "test.c"
            exe = Path(folder) / "test.exe"
            c.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_hardware_clock_keeps_seconds_and_rejects_invalid_samples(self):
        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        helper = (
            "static c6502_u32 native_clock(void)\n{"
            + runtime.split("static c6502_u32 native_clock(void)\n{", 1)[1].split(
                "static c6502_u8 native_window_key", 1
            )[0]
        )
        source = (
            """
#include <assert.h>
typedef unsigned char c6502_u8;
typedef unsigned int c6502_u32;
#define C6502_CTM_DIVIDER_ADDRESS 0x40153u
static unsigned char ctm[6]={254,59,59,23,1,0};
static volatile unsigned char *hardware_byte(unsigned address){assert(address==0x40153);return ctm;}
"""
            + helper
            + """
int main(void){
 unsigned a=native_clock();ctm[0]=2;ctm[1]=ctm[2]=ctm[3]=0;ctm[4]=2;
 unsigned b=native_clock();assert(b-a==4);
 ctm[1]=3;unsigned c=native_clock();assert(c-b==768);
 ctm[1]=99;assert(native_clock()==c);
 return 0;
}
"""
        )
        with tempfile.TemporaryDirectory(prefix="c6502-clock-") as folder:
            c = Path(folder) / "test.c"
            exe = Path(folder) / "test.exe"
            c.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_poll_never_waits_without_queued_messages(self):
        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        helpers = (
            "static c6502_u8 native_window_key"
            + runtime.split("static c6502_u8 native_window_key", 1)[1].split(
                "static void native_update_timer", 1
            )[0]
        )
        declarations = performance_globals(runtime).replace(
            "static c6502_u32 native_clock(void){return 0;}",
            "static unsigned now;static c6502_u32 native_clock(void){return now;}",
        )
        source = (
            """
#include <assert.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned int c6502_u32;
typedef unsigned T_GUI_HWND;
typedef struct {unsigned message,wParam;} T_GUI_Msg;
static struct {unsigned window;} c6502_native_state={1};
#define MSG_USER 2048
#define MSG_KEYDOWN 1
#define MSG_KEYUP 2
#define MSG_CHAR 3
#define LOUHWORD(x) (x)
static unsigned queue,gets,blocked,hardware_key=255,quit;
static unsigned fnGUI_HavePendingMessage(unsigned w){return queue!=0;}
static int fnGUI_GetMessage(T_GUI_Msg *m,unsigned w){++gets;if(!queue)++blocked;m->message=queue;m->wParam=42;queue=0;return !quit;}
static void fnGUI_DispatchMessage(T_GUI_Msg *m){}
static unsigned char map_key(unsigned x){return x;}
static unsigned char poll_hardware_key(void){unsigned key=hardware_key;hardware_key=255;return key;}
"""
            + declarations
            + helpers
            + """
int main(void){
 assert(native_poll_key()==255 && gets==0 && !blocked);
 hardware_key=42;assert(native_poll_key()==42 && gets==0 && !blocked);
 queue=MSG_KEYDOWN;assert(native_poll_key()==255 && gets==1 && !blocked);
 native_window_key(1);assert(blocked==1 && c6502_perf.waits==1);
 quit=1;assert(native_window_key(1)==0x2e);quit=0;
 return 0;
}
"""
        )
        with tempfile.TemporaryDirectory(prefix="c6502-input-timer-") as folder:
            c = Path(folder) / "test.c"
            exe = Path(folder) / "test.exe"
            c.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_timer_api_matches_rom_and_elapsed_irq_count(self):
        if not DEFAULT_ROME.is_file():
            self.skipTest("Set A9288_ROME for optional firmware equivalence")
        from native_rom_reference import FirmwareMemory, invoke_firmware

        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        helpers = (
            "static void native_update_timer"
            + runtime.split("static void native_update_timer", 1)[1].split(
                "static c6502_u8 translate_key", 1
            )[0]
        )
        globals_ = performance_globals(runtime).replace(
            "static c6502_u32 native_clock(void){return 0;}",
            "static unsigned now;static c6502_u32 native_clock(void){return now;}",
        )
        cases = []
        for number in (0, 1, 5, 200, 242, 255):
            memory = FirmwareMemory(7)
            invoke_firmware(memory, 0x7B4C, number, b"")
            expected = memory.ram[0x2018:0x201B]
            got = invoke_firmware(memory, 0x7B7D, 0, b"").a
            cases.append(
                f"memset(ram,0,sizeof(ram));now=c6502_timer_clock=0;c6502_timer_remaining=256;native_timer_open({number});"
                f"assert(ram[0x2018]=={expected[0]} && ram[0x2019]=={expected[1]} && ram[0x201a]=={expected[2]} && native_timer_number()=={got});"
            )
            invoke_firmware(memory, 0x7B4C, 17, b"")
            got = invoke_firmware(memory, 0x7B7D, 0, b"").a
            cases.append(
                f"native_timer_open(17);assert(native_timer_number()=={got});native_timer_close();assert(!native_timer_number() && !(ram[0x226]&1));"
            )
        # Batch advancement must match the actual INC/CMP IRQ routine, even
        # with a wrapped counter or zero written directly to firmware RAM.
        for number in (0, 1, 5, 200, 255):
            for count in (0, 4, 199, 254, 255):
                memory = FirmwareMemory(7)
                memory.ram[0x2018:0x201A] = bytes((count, number))
                memory.ram[0x201E] = 0xA0
                for _ in range(109):
                    invoke_firmware(memory, 0x7B8B, 0, b"")
                cases.append(
                    "memset(ram,0,sizeof(ram));ram[0x226]=1;ram[0x227]=166;"
                    f"ram[0x2018]={count};ram[0x2019]={number};ram[0x201e]=0xa0;"
                    "now=c6502_timer_clock=0;c6502_timer_remaining=256;c6502_timer_fraction=0;"
                    "c6502_timer_pending=0;now=256;native_update_timer();"
                    f"assert(ram[0x2018]=={memory.ram[0x2018]} && ram[0x201e]=={memory.ram[0x201E]});"
                )
        source = (
            """
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;typedef unsigned int c6502_u32;
#define C6502_TIMER_SOURCE_HZ 10000u
#define C6502_FRAME_TICKS 6u
static unsigned char ram[32768];static struct {unsigned char *ram;} c6502_native_state={ram};
static unsigned frames;static void c6502_native_present(void){++frames;}
"""
            + globals_
            + helpers
            + "int main(void){"
            + "\n".join(cases)
            + """
 memset(ram,0,sizeof(ram));memset(&c6502_perf,0,sizeof(c6502_perf));
 now=c6502_timer_clock=0;c6502_timer_remaining=256;c6502_timer_fraction=0;ram[0x227]=166;
 native_timer_open(5);now=256;native_update_timer();
 /* One second: (10000-256)/90 + 1 = 109 IRQs, 21 messages, count=4. */
 assert(c6502_perf.timer_irqs==109 && c6502_perf.timer_steps==21 && ram[0x2018]==4);
 assert(native_timer_number()==5 && c6502_timer_remaining==66 && (ram[0x201e]&1));
 native_timer_close();unsigned count=ram[0x2018],remaining=c6502_timer_remaining;
 now+=10000;native_update_timer();assert(ram[0x2018]==count && c6502_timer_remaining==remaining);
 /* A closed game timer must not stop physical-screen refresh. */
 c6502_last_frame_tick=now-7;native_refresh_if_due();assert(frames==1);
 native_timer_open(200);assert(native_timer_number()==200 && ram[0x2018]==0);
 now=0xfffffffc;c6502_timer_clock=now;c6502_timer_fraction=0;c6502_timer_remaining=256;
 memset(&c6502_perf,0,sizeof(c6502_perf));now=14;native_update_timer();
 assert(c6502_perf.timer_irqs==5 && ram[0x2018]==5 && c6502_timer_fraction==32);
 /* Many small samples and one large sample must give the same result. */
 memset(ram,0,sizeof(ram));ram[0x227]=166;now=c6502_timer_clock=0;
 c6502_timer_remaining=256;c6502_timer_fraction=0;native_timer_open(242);
 for(now=1;now<=1000;++now)native_update_timer();
 unsigned small_count=ram[0x2018],small_remaining=c6502_timer_remaining,small_fraction=c6502_timer_fraction;
 memset(ram,0,sizeof(ram));ram[0x227]=166;now=c6502_timer_clock=0;
 c6502_timer_remaining=256;c6502_timer_fraction=0;native_timer_open(242);now=1000;native_update_timer();
 assert(small_count==ram[0x2018] && small_remaining==c6502_timer_remaining && small_fraction==c6502_timer_fraction);
 return 0;}
"""
        )
        with tempfile.TemporaryDirectory(prefix="c6502-timer-rom-") as folder:
            path = Path(folder) / "test.c"
            exe = Path(folder) / "test.exe"
            path.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(path), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_message_box_layout_timeout_and_background_match_rom(self):
        if not DEFAULT_ROME.is_file():
            self.skipTest("Set A9288_ROME for optional firmware equivalence")
        from native_rom_reference import trace_rom_message_box

        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        timer = (
            "static void native_update_timer"
            + runtime.split("static void native_update_timer", 1)[1].split(
                "static c6502_u8 translate_key", 1
            )[0]
        )
        helper = (
            "static c6502_u8 message_box_layout"
            + runtime.split("static c6502_u8 message_box_layout", 1)[1].split(
                "static void query_box(", 1
            )[0]
        )
        globals_ = performance_globals(runtime).replace(
            "static c6502_u32 native_clock(void){return 0;}",
            "static unsigned now;static c6502_u32 native_clock(void){return now;}",
        )
        # Odd/even GBK boundary, exact multiples, five-line clamp, empty input.
        texts = [
            b"",
            "百草地".encode("gbk"),
            b"a" * 15 + "天地".encode("gbk"),
            b"0123456789abcdef",
            b"0" * 17,
            "天地玄黄宇宙洪荒日月盈昃辰宿列张".encode("gbk"),
            b"A" * 95,
            b"A" * 256,
        ]
        checks = []
        for text in texts:
            expected = trace_rom_message_box(text, 5)
            calls = [
                (name, args) for name, args in expected["calls"] if name in ("text", "rect", "fill")
            ]
            checks.append(
                "{ const unsigned char s[]={" + ",".join(map(str, text + b"\0")) + "};"
                "memset(ram,0x69,sizeof(ram));memcpy(ram+0x2600,s,sizeof(s));memcpy(before,ram,sizeof(ram));"
                "call=0;polls=0;key_after=0;expected_count=" + str(len(calls)) + ";"
            )
            for i, (name, args) in enumerate(calls):
                if name == "text":
                    vals = list(bytes.fromhex(args[2]))
                    checks.append(
                        f"expected[{i}][0]=0;expected[{i}][1]={args[0]};expected[{i}][2]={args[1]};"
                    )
                    for j, val in enumerate(vals + [0]):
                        checks.append(f"expected_text[{i}][{j}]={val};")
                else:
                    checks.append(
                        f"expected[{i}][0]={1 if name == 'rect' else 2};"
                        + "".join(f"expected[{i}][{j + 1}]={v};" for j, v in enumerate(args))
                    )
            checks.append(
                "ram[0x201a]=1;ram[0x2019]=7;ram[0x2018]=0;ram[0x226]=1;ram[0x227]=166;"
                "now=c6502_timer_clock=100;c6502_timer_remaining=90;c6502_timer_fraction=0;"
                "message_box(r,0x2600,5);"
                f"assert(r[4]=={expected['result']} && call==expected_count && native_timer_number()==7);"
                "for(unsigned y=0;y<96;++y)for(unsigned x=0;x<20;++x)assert(ram[lcd_address(x,y)]==before[lcd_address(x,y)]);"
            )
            if text and len(text) != 256:
                checks.append("assert(now-100>=12 && now-100<=15);")
            else:
                checks.append("assert(polls==0);")
            checks.append("}")
        source = (
            """
#include <assert.h>
#include <string.h>
#include <stdlib.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;typedef unsigned int c6502_u32;
#define C6502_TIMER_SOURCE_HZ 10000u
#define C6502_FRAME_TICKS 6u
#define C6502_RESOURCE_SCRATCH_SIZE 1920u
static unsigned char ram[32768],before[32768],c6502_resource_scratch[1920];
static struct {unsigned char *ram;} c6502_native_state={ram};
static unsigned expected[8][5],call,expected_count,polls,key_after;
static unsigned char expected_text[8][17];
static unsigned char guest_read(unsigned short a){return ram[a];}
static void guest_write(unsigned short a,unsigned char v){ram[a]=v;}
static unsigned short lcd_address(unsigned x,unsigned y){return 0x400+y*20+x;}
static void c6502_native_present(void){}
static void return8(unsigned *r,unsigned char v){r[4]=v;}
static void horizontal_span(unsigned x0,unsigned x1,unsigned y,int op){assert(x0==11&&x1==148&&op==0);memset(ram+lcd_address(1,y),0,18);}
static void native_text(unsigned char x,unsigned char y,const unsigned char *s){assert(call<expected_count);assert(expected[call][0]==0&&expected[call][1]==x&&expected[call][2]==y);assert(!strcmp((const char*)s,(const char*)expected_text[call]));++call;}
static void rectangle(unsigned char x,unsigned char y,unsigned char x1,unsigned char y1,int fill){assert(call<expected_count);assert(expected[call][0]==(fill?2:1)&&expected[call][1]==x&&expected[call][2]==y&&expected[call][3]==x1&&expected[call][4]==y1);++call;}
"""
            + globals_
            + """
static unsigned char native_window_key(int wait){assert(wait);now+=3;++polls;return key_after&&polls>=key_after?0x2f:255;}
"""
            + timer
            + helper
            + "int main(void){unsigned r[15]={0};"
            + "\n".join(checks)
            + """
 /* timeout=0 waits for a key; timeout>0 may also be dismissed by a key. */
 const unsigned char msg[]={0xb0,0xd9,0xb2,0xdd,0xb5,0xd8,0};memcpy(ram+0x2600,msg,7);
 call=0;expected_count=4;expected[0][0]=0;expected[0][1]=15;expected[0][2]=39;memcpy(expected_text[0],msg,7);
 const unsigned e[3][5]={{1,11,37,146,57},{2,14,57,146,59},{2,146,40,148,59}};memcpy(expected+1,e,sizeof(e));
 polls=0;key_after=3;unsigned start=now;message_box(r,0x2600,0);assert(polls==3&&now-start==9&&r[4]==1);
 call=0;polls=0;start=now;message_box(r,0x2600,1000);assert(polls==3&&now-start==9&&native_timer_number()==7);
 return 0;}
"""
        )
        with tempfile.TemporaryDirectory(prefix="c6502-msgbox-rom-") as folder:
            path = Path(folder) / "test.c"
            exe = Path(folder) / "test.exe"
            path.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(path), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_file_catalog_and_random_access_survive_reopen(self):
        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        helper = (
            "#define C6502_FILE_RECORDS"
            + runtime.split("#define C6502_FILE_RECORDS", 1)[1].split(
                "static c6502_u32 signed_div", 1
            )[0]
        )
        names = sorted(set(re.findall(r"C6502_BRIDGE_\w+", helper)))
        defines = "enum {" + ",".join(names) + "};\n"
        defines += (
            "\n".join(
                "#define " + name + " 1"
                for name in sorted(set(re.findall(r"C6502_NEEDS_\w+", helper)))
            )
            + "\n"
        )
        source = (
            """
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned int c6502_u32;
typedef FILE FS_FILE;
#define fs_fopen(p,m) fopen((p)+3,m)
#define fs_fread fread
#define fs_fwrite fwrite
#define fs_fseek fseek
#define fs_ftell ftell
#define fs_fclose fclose
#define fs_update fflush
#define fs_remove(p) remove((p)+3)
#define C6502_RESOURCE_SCRATCH_SIZE 1920u
static unsigned char ram[65536],c6502_resource_scratch[1920];
static unsigned char guest_read(unsigned short a){return ram[a];}
static void guest_write(unsigned short a,unsigned char v){ram[a]=v;}
static void bytes_set(unsigned char *p,unsigned char v,unsigned n){memset(p,v,n);}
static void put16(unsigned short a,unsigned short v){ram[a]=v;ram[a+1]=v>>8;}
static void guest_put32(unsigned short a,unsigned v){put16(a,v);put16(a+2,v>>16);}
static unsigned guest_get32(unsigned short a){return ram[a]|ram[a+1]<<8|ram[a+2]<<16|ram[a+3]<<24;}
static unsigned char stack8(unsigned *r,unsigned n){return ram[(unsigned short)(r[10]+n)];}
static unsigned short stack16(unsigned *r,unsigned n){return stack8(r,n)|(stack8(r,n+1)<<8);}
static void return8(unsigned *r,unsigned char v){r[4]=v;}
"""
            + defines
            + helper
            + """
int main(void){
 unsigned r[15]={0},name,h,i;
 r[10]=0x1000;load_file_index();
 for(i=0;i<10;++i)ram[0x2000+i]=(unsigned char)(0xa0+i);
 guest_put32(0x1000,3000);put16(0x1004,0x2000);put16(0x1006,0x2100);put16(0x1008,0x2102);
 r[4]=9;api_file(r,C6502_BRIDGE_c6502_adapter_filecreat);assert(r[4]==1);
 name=ram[0x2100]|ram[0x2101]<<8;h=ram[0x2102];
 guest_put32(0x1000,1024);ram[0x1004]=1;r[4]=h;api_file(r,C6502_BRIDGE_c6502_adapter_fileseek);assert(r[4]==1);
 for(i=0;i<256;++i)ram[0x2200+i]=(unsigned char)(i*29+17);
 ram[0x1000]=0;put16(0x1001,0x2200);r[4]=h;api_file(r,C6502_BRIDGE_c6502_adapter_filewrite);assert(r[4]==1);
 r[4]=h;api_file(r,C6502_BRIDGE_c6502_adapter_fileclose);assert(r[4]==1);
 memset(c6502_file_records,0,sizeof(c6502_file_records));load_file_index();
 put16(0x1000,0x2300);r[4]=9;api_file(r,C6502_BRIDGE_c6502_adapter_filenum);assert(r[4]==1 && ram[0x2300]==1 && ram[0x2301]==0);
 put16(0x1000,1);put16(0x1002,0x2302);put16(0x1004,0x2310);r[4]=9;api_file(r,C6502_BRIDGE_c6502_adapter_filesearch);assert(r[4]==1 && (ram[0x2302]|ram[0x2303]<<8)==name && !memcmp(ram+0x2000,ram+0x2310,10));
 put16(0x1000,name);ram[0x1002]=9;ram[0x1003]=1;put16(0x1004,0x2400);put16(0x1006,0x2404);api_file(r,C6502_BRIDGE_c6502_adapter_fileopen);assert(r[4]==1 && guest_get32(0x2404)==3000);h=ram[0x2400];
 guest_put32(0x1000,1024);ram[0x1004]=1;r[4]=h;api_file(r,C6502_BRIDGE_c6502_adapter_fileseek);assert(r[4]==1);
 ram[0x1000]=0;put16(0x1001,0x2500);r[4]=h;api_file(r,C6502_BRIDGE_c6502_adapter_fileread);assert(r[4]==1 && !memcmp(ram+0x2200,ram+0x2500,256));
 r[4]=h;api_file(r,C6502_BRIDGE_c6502_adapter_fileclose);assert(r[4]==1);
 return 0;
}
"""
        )
        with tempfile.TemporaryDirectory(prefix="c6502-files-") as folder:
            c = Path(folder) / "test.c"
            exe = Path(folder) / "test.exe"
            c.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], cwd=folder, check=True)

    def test_strcmp_returns_rom_int_not_stale_operand_pointer(self):
        if not DEFAULT_ROME.is_file():
            self.skipTest("Set A9288_ROME for optional firmware equivalence")
        from native_rom_reference import FirmwareMemory, invoke_firmware

        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        helper = (
            "static void native_strcmp"
            + runtime.split("static void native_strcmp", 1)[1].split(
                "#define C6502_FILE_RECORDS", 1
            )[0]
        )
        checks = []
        words = [
            b"",
            b"a",
            b"b",
            b"z",
            b"abc",
            b"abcd",
            b"\x01",
            b"\x7f",
            b"\x80",
            b"\xff",
            "伏魔记0".encode("gbk"),
            "伏魔记1".encode("gbk"),
        ]
        for left in words:
            for right in words:
                mem = FirmwareMemory(4)
                mem.ram[0x2200 : 0x2200 + len(left) + 1] = left + b"\0"
                mem.ram[0x2300 : 0x2300 + len(right) + 1] = right + b"\0"
                cpu = invoke_firmware(mem, 0x604F, 0, bytes.fromhex("00220023"))
                expected = int.from_bytes(mem.ram[0x20:0x22], "little")
                checks.append(
                    "{unsigned char l[]={"
                    + ",".join(map(str, left + b"\0"))
                    + "},b[]={"
                    + ",".join(map(str, right + b"\0"))
                    + "};"
                    "memset(ram,0,sizeof(ram));memcpy(ram+0x2200,l,sizeof(l));memcpy(ram+0x2300,b,sizeof(b));ram[0x20]=0xaa;ram[0x21]=0xbb;r[9]=0x30;native_strcmp(r,0x2200,0x2300);"
                    f"assert((ram[0x20]|ram[0x21]<<8)=={expected} && r[4]=={cpu.a} && r[6]=={cpu.y} && r[9]=={cpu.p});"
                    + "}"
                )
        source = (
            """
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned int c6502_u32;
#define C6502_FLAG_C 1u
#define C6502_FLAG_V 64u
static unsigned char ram[65536];
static unsigned char guest_read(unsigned short a){return ram[a];}
static void guest_write(unsigned short a,unsigned char v){ram[a]=v;}
static void put16(unsigned short a,unsigned short v){ram[a]=v;ram[a+1]=v>>8;}
static void return16(unsigned *r,unsigned short v){put16(0x20,v);r[4]=v>>8;r[8]=r[4];r[9]=(r[9]&~130u)|(r[4]?128u:2u);}
"""
            + helper
            + "int main(void){unsigned r[15]={0};"
            + "\n".join(checks)
            + "return 0;}"
        )
        with tempfile.TemporaryDirectory(prefix="c6502-strcmp-") as folder:
            c = Path(folder) / "test.c"
            exe = Path(folder) / "test.exe"
            c.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_native_output_centres_159_pixels_without_padding(self):
        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        helpers = (
            "static c6502_u16 lcd_address"
            + runtime.split("static c6502_u16 lcd_address", 1)[1].split(
                "static void rectangle(", 1
            )[0]
        )
        helpers += (
            "void c6502_native_present"
            + runtime.split("void c6502_native_present", 1)[1].split("static c6502_u8 map_key", 1)[
                0
            ]
        )
        source = (
            """
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned int c6502_u32;
static unsigned char ram[32768],host_frame[19200] __attribute__((aligned(4)));
static struct {unsigned char *ram;} c6502_native_state={ram};
#define C6502_FRAMEBUFFER host_frame
#define C6502_FRAME_STRIDE 80u
#define C6502_FRAME_HEIGHT 240u
#define C6502_GUEST_HEIGHT 96u
#define C6502_GUEST_STRIDE 20u
#define C6502_VIEW_Y 24u
"""
            + performance_globals(runtime)
            + helpers
            + """
int main(void){
 for(unsigned i=0;i<32768;++i)ram[i]=(i*29+17)&255;
 c6502_native_present();
 for(unsigned y=0;y<240;++y)for(unsigned x=0;x<320;++x){
  unsigned expected=3;
  if(y>=24 && y<216 && x>=1 && x<319){
   unsigned sx=(x-1)/2,sy=(y-24)/2;
   expected=(ram[lcd_address(sx/8,sy)]&(128>>(sx&7)))?0:3;
  }
  assert(((host_frame[y*80+x/4]>>(6-2*(x&3)))&3)==expected);
 }
 assert(c6502_perf.submissions==1 && c6502_perf.dirty_rows==96);
 /* A firmware repaint can change the screen without changing game RAM. */
 unsigned char saved_frame[19200];memcpy(saved_frame,host_frame,sizeof(host_frame));
 memset(host_frame,255,sizeof(host_frame));c6502_native_present();
 assert(!memcmp(host_frame,saved_frame,sizeof(host_frame)));
 assert(c6502_perf.submissions==2 && c6502_perf.dirty_rows==96);
 ram[lcd_address(3,42)]^=0x80;c6502_native_present();
 assert(c6502_perf.submissions==3 && c6502_perf.dirty_rows==97);
 c6502_native_invalidate_screen();c6502_native_present();
 assert(c6502_perf.submissions==4 && c6502_perf.dirty_rows==193);
 for(unsigned op=0;op<3;++op)for(unsigned y=0;y<96;++y){
  for(unsigned x0=0;x0<160;x0+=7){
   unsigned x1=x0+19;if(x1>159)x1=159;
   memset(ram,0x69,sizeof(ram));horizontal_span(x0,x1,y,op);
   for(unsigned x=0;x<160;++x){
    unsigned before=(0x69>>(7-(x&7)))&1;
    unsigned expected=(x<x0 || x>x1)?before:(op==0?0:op==1?1:!before);
    assert(((ram[lcd_address(x/8,y)]>>(7-(x&7)))&1)==expected);
   }
  }
 }
 memset(ram,0,sizeof(ram));line(10,10,15,13);
 const unsigned points[6][2]={{10,10},{11,11},{12,11},{13,12},{14,12},{15,13}};
 for(unsigned i=0;i<6;++i)assert(ram[lcd_address(points[i][0]/8,points[i][1])]&(128>>(points[i][0]&7)));
 return 0;
}
"""
        )
        with tempfile.TemporaryDirectory(prefix="c6502-output-") as folder:
            c = Path(folder) / "output.c"
            exe = Path(folder) / "output.exe"
            c.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_completed_picture_frames_publish_without_input_polling(self):
        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        helper = (
            "static void api_graphics"
            + runtime.split("static void api_graphics", 1)[1].split("static void native_strcmp", 1)[
                0
            ]
        )
        ids = sorted(set(re.findall(r"C6502_BRIDGE_\w+", helper)))
        source = (
            r"""
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;typedef unsigned c6502_u32;
#define C6502_RESOURCE_SCRATCH_SIZE 1920u
static unsigned char ram[65536],c6502_resource_scratch[1920],lcd[1920],visible[1920];
static unsigned copied,presents,due,c6502_last_frame_tick;
static struct {unsigned picture_frame_commits;} c6502_perf;
static unsigned native_clock(void){return 100;}
static unsigned char guest_read(unsigned short a){return ram[a];}
static unsigned char stack8(unsigned *r,unsigned n){return ram[r[10]+n];}
static unsigned short stack16(unsigned *r,unsigned n){return stack8(r,n)|(stack8(r,n+1)<<8);}
static void native_picture(unsigned x,unsigned y,unsigned x1,unsigned y1,unsigned src,unsigned flag){
 assert(src==0x3000 && !flag);memcpy(lcd,ram+src,1920);copied=1;
}
static void c6502_native_present(void){assert(copied);memcpy(visible,lcd,1920);copied=0;++presents;}
static void native_refresh_if_due(void){++due;}
static void native_text(unsigned x,unsigned y,const unsigned char*s){}
static void line(unsigned x,unsigned y,unsigned x1,unsigned y1){}
static void rectangle(unsigned x,unsigned y,unsigned x1,unsigned y1,int fill){}
static void rectangle_clear(unsigned x,unsigned y,unsigned x1,unsigned y1){}
static void horizontal_span(unsigned x,unsigned x1,unsigned y,int op){}
static void picture_dummy(unsigned*r){}
static void save_restore_screen(unsigned*r,int restore){}
"""
            + "enum {"
            + ",".join(ids)
            + "};\n"
            + helper
            + r"""
int main(void){
 unsigned r[15]={0},saved[15];r[10]=0x1800;
 unsigned char args[]={0,158,95,0,0x30,0};memcpy(ram+0x1800,args,6);memcpy(saved,r,sizeof(r));
 /* Eight animated pages, no key/message calls, not even one clock tick. */
 for(unsigned frame=0;frame<8;++frame){
  memset(ram+0x3000,frame*31,1920);
  api_graphics(r,C6502_BRIDGE_c6502_adapter_syspicture);
  assert(presents==frame+1 && !memcmp(visible,ram+0x3000,1920));
  assert(!memcmp(r,saved,sizeof(r)) && c6502_last_frame_tick==100);
 }
 assert(c6502_perf.picture_frame_commits==8 && !due);
 /* Also accept the 160-pixel API width, not just Fumo's 159 pixels. */
 ram[0x1801]=159;api_graphics(r,C6502_BRIDGE_c6502_adapter_syspicture);assert(presents==9);
 /* A partial draw may refresh when due, but is not a forced frame commit. */
 r[4]=16;api_graphics(r,C6502_BRIDGE_c6502_adapter_syspicture);assert(presents==9&&due==1);
 /* Compositing to an off-screen page must not publish an unfinished frame. */
 r[4]=0;api_graphics(r,C6502_BRIDGE_c6502_adapter_syspicturedummy);assert(presents==9&&due==1);
 return 0;
}
"""
        )
        with tempfile.TemporaryDirectory(prefix="c6502-frame-commit-") as folder:
            c = Path(folder) / "test.c"
            exe = Path(folder) / "test.exe"
            c.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_bitmap_adapters_match_original_firmware_bytes(self):
        if not DEFAULT_ROME.is_file():
            self.skipTest("Set A9288_ROME for optional firmware equivalence")
        from native_rom_reference import FirmwareMemory, invoke_firmware

        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        helpers = (
            "static c6502_u16 lcd_address"
            + runtime.split("static c6502_u16 lcd_address", 1)[1].split("static void line", 1)[0]
        )
        helpers += (
            "static c6502_u8 screen_bit"
            + runtime.split("static c6502_u8 screen_bit", 1)[1].split(
                "/* The 9288 font renderer", 1
            )[0]
        )
        helpers += (
            "static int picture_source_disjoint"
            + runtime.split("static int picture_source_disjoint", 1)[1].split(
                "static void integer_to_ascii", 1
            )[0]
        )
        checks = []
        shapes = [
            (0, 0, 159, 95),
            (16, 8, 31, 23),
            (1, 3, 8, 10),
            (7, 65, 19, 70),
            (152, 80, 159, 95),
            (0, 65, 7, 65),
            (2, 1, 5, 4),
            (31, 23, 16, 8),
        ]
        rng = random.Random(9288)
        for _ in range(32):
            x = rng.randrange(160)
            y = rng.randrange(96)
            shapes.append((x, y, rng.randrange(x, 160), rng.randrange(y, 96)))
        for dummy in (False, True):
            for flag in (0, 1):
                for x, y, x1, y1 in shapes:
                    mem = FirmwareMemory(6 if dummy else 5)
                    mem.ram[:] = bytes((i * 29 + 17) & 255 for i in range(65536))
                    args = (
                        bytes([y, x1, y1, 0, 0x90])
                        + (b"\x00\x30" if dummy else b"")
                        + bytes([flag])
                    )
                    invoke_firmware(mem, 0x5B18 if dummy else 0x682D, x, args)
                    start, end = (0x3000, 0x3780) if dummy else (0x401, 0x1001)
                    expected = 2166136261
                    for byte in mem.ram[start:end]:
                        expected = ((expected ^ byte) * 16777619) & 0xFFFFFFFF
                    call = (
                        "picture_dummy(r)"
                        if dummy
                        else f"native_picture({x},{y},{x1},{y1},0x9000,{flag})"
                    )
                    checks.append(
                        "{ unsigned char args[]={" + ",".join(map(str, args)) + "}; "
                        "for(unsigned i=0;i<65536;++i)ram[i]=(i*29+17)&255;memcpy(ram+0x1800,args,sizeof(args));"
                        f"r[4]={x};r[10]=0x1800;{call};unsigned h=2166136261u;"
                        f"for(unsigned i={start};i<{end};++i)h=(h^ram[i])*16777619u;"
                        f'if(h!={expected}u){{printf("bitmap case {len(checks)}: %08x != {expected:08x}\\n",h);++errors;}}'
                        + "}"
                    )
        source = (
            """
#include <stdio.h>
#include <string.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned int c6502_u32;
#define C6502_RAM_SIZE 32768u
#define C6502_RESOURCE_SCRATCH_SIZE 1920u
#define C6502_GUEST_STRIDE 20u
static unsigned char ram[65536],c6502_resource_scratch[1920];
static struct {unsigned char *ram;unsigned short banks[16];} c6502_native_state={ram};
static unsigned char guest_read(unsigned short a){return ram[a==0x400?0x1000:a];}
static void guest_write(unsigned short a,unsigned char v){ram[a==0x400?0x1000:a]=v;}
static unsigned char stack8(unsigned *r,unsigned n){return ram[(unsigned short)(r[10]+n)];}
static unsigned short stack16(unsigned *r,unsigned n){return stack8(r,n)|(stack8(r,n+1)<<8);}
"""
            + helpers
            + "\nint main(void){unsigned r[15]={0};int errors=0;\n"
            + "\n".join(checks)
            + "\nreturn errors!=0;}\n"
        )
        # Save/restore has its own ROM entry points; do not assume it is
        # identical to tightly packed SysPicture. Resolve the actual E.BIN
        # table, since test.map belongs to a different firmware revision.
        for restore in (0, 1):
            for x, y, x1, y1 in shapes:
                mem = FirmwareMemory(5)
                mem.ram[:] = bytes((i * 29 + 17) & 255 for i in range(65536))
                args = bytes([y, x1, y1, 0, 0x30])
                slot = 0xE87A if restore else 0xE877
                pc = mem[slot] | (mem[slot + 1] << 8)
                invoke_firmware(mem, pc, x, args)
                start, end = (0x401, 0x1001) if restore else (0x3000, 0x3780)
                expected = 2166136261
                for byte in mem.ram[start:end]:
                    expected = ((expected ^ byte) * 16777619) & 0xFFFFFFFF
                checks.append(
                    "{unsigned char args[]={" + ",".join(map(str, args)) + "};"
                    "for(unsigned i=0;i<65536;++i)ram[i]=(i*29+17)&255;memcpy(ram+0x1800,args,sizeof(args));"
                    f"r[4]={x};r[10]=0x1800;save_restore_screen(r,{restore});unsigned h=2166136261u;"
                    f"for(unsigned i={start};i<{end};++i)h=(h^ram[i])*16777619u;"
                    f'if(h!={expected}u){{printf("screen case {len(checks)}: %08x != {expected:08x}\\n",h);++errors;}}'
                    + "}"
                )
        # Reuse declarations/helpers from the picture harness with all cases.
        source = (
            source.split("int main(void)", 1)[0]
            + "int main(void){unsigned r[15]={0};int errors=0;for(unsigned i=0;i<16;++i)c6502_native_state.banks[i]=512;\n"
            + "\n".join(checks)
            + "\nreturn errors!=0;}\n"
        )
        with tempfile.TemporaryDirectory(prefix="c6502-bitmap-abi-") as folder:
            c = Path(folder) / "bitmap.c"
            exe = Path(folder) / "bitmap.exe"
            c.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_byte_division_and_shifts_match_rom_abi(self):
        if not DEFAULT_ROME.is_file():
            self.skipTest("Set A9288_ROME for optional firmware equivalence")
        from py65.devices.mpu65c02 import MPU

        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        helpers = (
            "static void return8"
            + runtime.split("static void return8", 1)[1].split("static void runtime_compare16", 1)[
                0
            ]
        )
        rom = DEFAULT_ROME.read_bytes()[0xA8000:0xAB000]
        checks = []
        cases = [
            (0xDA09, "runtime_shift(r,8,0)", 8),
            (0xDBE1, "runtime_shift(r,8,1)", 8),
            (0xDA1A, "runtime_shift(r,16,0)", 16),
            (0xDBF2, "runtime_shift(r,16,1)", 16),
            (0xDC7B, "runtime_divide8(r,0)", 8),
            (0xDCAB, "runtime_divide8(r,1)", 8),
        ]
        for pc, call, bits in cases:
            for value in [0, 1, 7, 0x7F, 0x80, 0xFF, 0x8000, 0xFFFF]:
                for count in [0, 1, 2, 7, 8, 9, 15, 16, 31, 255, 256, 0x1000]:
                    cpu = MPU()
                    cpu.memory[0xD000:] = rom
                    initial = [0x5A, 0xA5, 0x39, count & 255, count >> 8, 0x79, 0x41, 0x31]
                    if bits == 16:
                        initial[:2] = [value & 255, value >> 8]
                    cpu.memory[0x20:0x28] = initial
                    cpu.a = value & 255 if bits == 8 else 0xA5
                    cpu.x = 0x47
                    cpu.y = 0x79
                    cpu.p = 0x71
                    cpu.pc = pc
                    cpu.sp = 0xFD
                    cpu.memory[0x1FE:0x200] = [0xFF, 0x1F]
                    for _ in range(600):
                        if cpu.pc == 0x2000:
                            break
                        cpu.step()
                    self.assertEqual(cpu.pc, 0x2000)
                    checks.append(
                        "{ unsigned char init[8]={"
                        + ",".join(map(str, initial))
                        + "}; memcpy(ram+0x20,init,8); "
                        f"r[4]={value & 255 if bits == 8 else 0xA5};r[5]=0x47;r[6]=0x79;r[9]=0x71;{call}; "
                        f"assert(r[4]=={cpu.a} && r[5]=={cpu.x} && r[6]==0x79 && r[9]=={cpu.p}); "
                        + "".join(
                            f"assert(ram[{0x20 + i}]=={v});"
                            for i, v in enumerate(cpu.memory[0x20:0x28])
                        )
                        + "}"
                    )
        source = (
            """
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned int c6502_u32;
#define C6502_FLAG_C 1u
#define C6502_FLAG_V 64u
static unsigned char ram[32768];
static struct { unsigned char *ram; } c6502_native_state={ram};
static unsigned short get16(unsigned a){return ram[a]|(ram[a+1]<<8);}
static void put16(unsigned a,unsigned short v){ram[a]=v;ram[a+1]=v>>8;}
static void set_nz(unsigned *r,unsigned char v){r[8]=v;r[9]=(r[9]&~0x82u)|(v&0x80u)|(v?0:2);}
"""
            + helpers
            + "\nint main(void){unsigned r[15]={0};\n"
            + "\n".join(checks)
            + "\nreturn 0;}\n"
        )
        with tempfile.TemporaryDirectory(prefix="c6502-byte-abi-") as folder:
            c = Path(folder) / "arithmetic.c"
            exe = Path(folder) / "arithmetic.exe"
            c.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_text_wraps_at_a_series_width_and_erases_old_cell_pixels(self):
        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        helper = (
            "static const c6502_u8 *native_glyph"
            + runtime.split("static const c6502_u8 *native_glyph", 1)[1].split(
                "static int picture_source_disjoint", 1
            )[0]
        )
        source = (
            """
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned int c6502_u32;
static unsigned char c6502_text_surface[19200], target[96][160];
static struct { unsigned hdc; } c6502_native_state;
static unsigned calls;
static void bytes_set(unsigned char *p,unsigned char v,unsigned n){memset(p,v,n);}
static void blit_packed_row(unsigned short screen,unsigned char x,unsigned char y,unsigned char width,const unsigned char *row){
 assert(screen==0x400 && x+width<=160 && y<96);
 for(unsigned i=0;i<width;++i)target[y][x+i]=(row[i/8]>>(7-(i&7)))&1;
}
static void fake_font(unsigned dc,int x,int y,const unsigned char *glyph,unsigned char *dst){
  assert(x==0 && y==0); ++calls; dst[0]=0x3f;
}
#define NATIVE_GAME_GUI(name) fake_font
"""
            + performance_globals(runtime)
            + helper
            + """
int main(void){
  memset(target,1,sizeof(target));
  native_text(152,64,(const unsigned char *)"AB");
  assert(calls==2 && target[64][152] && !target[64][153]);
  assert(target[80][0] && !target[95][7] && target[80][8]);
  calls=0; memset(c6502_glyphs,0,sizeof(c6502_glyphs)); native_text(144,0,(const unsigned char *)"\\xcc\\xec" "A");
  assert(calls==2 && target[0][144] && !target[0][159] && target[16][0]);
  calls=0; native_text(159,80,(const unsigned char *)"A"); assert(!calls);
  native_text(144,0,(const unsigned char *)"\\xcc\\xec" "A");assert(!calls && c6502_perf.glyph_hits==2);
  return 0;
}
"""
        )
        with tempfile.TemporaryDirectory(prefix="c6502-text-test-") as folder:
            c = Path(folder) / "text.c"
            exe = Path(folder) / "text.exe"
            c.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_compare16_matches_c6502_rom_flags_and_register_results(self):
        if not DEFAULT_ROME.is_file():
            self.skipTest("Set A9288_ROME for optional firmware equivalence")
        from py65.devices.mpu65c02 import MPU

        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        helper = runtime.split("static void runtime_compare16", 1)[1].split(
            "static void *native_target", 1
        )[0]
        rom = DEFAULT_ROME.read_bytes()
        code = rom[0xA8340:0xA8362]
        self.assertEqual(code[:7], bytes.fromhex("a200a52038e523"))
        rng = random.Random(6502)
        edges = [0, 1, 0x7F, 0x80, 0xFF, 0x100, 0x7FFF, 0x8000, 0xFF00, 0xFFFF]
        pairs = [(a, b) for a in edges for b in edges]
        pairs += [(rng.randrange(65536), rng.randrange(65536)) for _ in range(300)]
        checks = []
        for left, right in pairs:
            cpu = MPU()
            cpu.memory[0xD340:0xD362] = code
            cpu.memory[0x20:0x22] = [left & 255, left >> 8]
            cpu.memory[0x23:0x25] = [right & 255, right >> 8]
            cpu.pc = 0xD340
            cpu.p = 0x34
            cpu.y = 0x79
            for _ in range(40):
                if cpu.pc == 0xD361:
                    break
                cpu.step()
            self.assertEqual(cpu.pc, 0xD361)
            nz = 0 if cpu.p & 2 else (128 if cpu.p & 128 else 1)
            checks.append(
                f"r[9]=0x34; r[6]=0x79; runtime_compare16(r,{left},{right}); "
                f"assert(r[4]=={cpu.a} && r[5]=={cpu.x} && r[6]==0x79 && r[8]=={nz} && r[9]=={cpu.p});"
            )
        source = (
            """
#include <assert.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned int c6502_u32;
#define C6502_FLAG_C 1u
#define C6502_FLAG_Z 2u
#define C6502_FLAG_V 64u
#define C6502_FLAG_N 128u
static void runtime_compare16"""
            + helper
            + "\nint main(void) { unsigned r[15]={0};\n"
            + "\n".join(checks)
            + "\nreturn 0;}\n"
        )
        with tempfile.TemporaryDirectory(prefix="c6502-compare-test-") as folder:
            c = Path(folder) / "compare.c"
            exe = Path(folder) / "compare.exe"
            c.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_heap_reuses_freed_blocks_and_lcd_mapping_matches_reference(self):
        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        heap = runtime.split("static void native_heap_init", 1)[1].split(
            "static int lzss_expand", 1
        )[0]
        lcd = runtime.split("static c6502_u16 lcd_address", 1)[1].split("static void pixel", 1)[0]
        source = (
            """
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned int c6502_u32;
static c6502_u16 c6502_heap_begin, c6502_heap_end;
static c6502_u16 c6502_allocations[128][2];
static struct { c6502_u32 heap_next; } c6502_native_state;
static void bytes_set(c6502_u8 *p,c6502_u8 v,c6502_u32 n) { memset(p,v,n); }
static void native_heap_init"""
            + heap
            + "\nstatic c6502_u16 lcd_address"
            + lcd
            + """
int main(void) {
  unsigned a,b,c,d,i,x,y,j;
  unsigned char seen[0x1001] = {0};
  native_heap_init(0x2c00,0x1400);
  a=native_heap_allocate(0x12e); b=native_heap_allocate(0x100);
  c=native_heap_allocate(0x794);
  assert(a==0x2c00 && b==a+0x12e && c==b+0x100);
  for(i=0;i<10000;++i) {
    d=native_heap_allocate(46); assert(d && d+46<=0x4000);
    native_heap_free(d);
  }
  native_heap_free(b); assert(native_heap_allocate(0xff)==b);
  assert(native_heap_allocate(0xffff)==0);
  for(y=0;y<96;++y) for(x=0;x<20;++x) {
    unsigned p=lcd_address(x,y), expect;
    if(x) { j=y<=65 ? 65-y : y; expect=0x400+j*32+x-1; }
    else if(y==65) expect=0xff3;
    else { j=y<65 ? 64-y : y-1; expect=0x413+j*32; }
    if(expect==0x400) expect=0x1000;
    assert(p==expect && p<=0x1000 && !seen[p]); seen[p]=1;
  }
  return 0;
}
"""
        )
        with tempfile.TemporaryDirectory(prefix="c6502-native-test-") as folder:
            path = Path(folder)
            c = path / "helpers.c"
            exe = path / "helpers.exe"
            c.write_text(source, encoding="utf-8")
            subprocess.run([cc, "-O2", "-Wall", "-Werror", str(c), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()
