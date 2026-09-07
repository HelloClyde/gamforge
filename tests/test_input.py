"""Exercise the actual shared input state machine, independently of game code."""

import shutil
import subprocess

import pytest

from a9288.compiler.boot import DEFAULT_ROME
from a9288.paths import DATA


def test_short_taps_repeat_launch_and_queue_overflow(tmp_path):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    source = r"""
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned c6502_u32;
static struct {unsigned key_scans,key_scan_max_gap_ticks,key_edges,key_repeats,
 keys_consumed,key_queue_peak,key_queue_overflows;} c6502_perf;
#include "c6502_native_input.h"
static unsigned char rows[8];static unsigned now;
static void scan(unsigned t){now=t;native_key_snapshot(rows,t);}
static void reset(void){
 memset(rows,0,8);memset(c6502_key_previous,0,8);memset(&c6502_perf,0,sizeof(c6502_perf));
 c6502_key_head=c6502_key_count=c6502_key_initialized=0;c6502_key_repeat=255;
 scan(0);
}
int main(void){
 reset();
 /* Captured while drawing, released before the game asks for a key. */
 rows[7]=8;scan(1);rows[7]=0;scan(3);
 assert(native_take_key()==0x35 && native_take_key()==255);
 /* Two taps of the SAME direction are two events, not an autorepeat. */
 rows[7]=8;scan(4);rows[7]=0;scan(6);rows[7]=8;scan(8);rows[7]=0;scan(10);
 assert(native_take_key()==0x35 && native_take_key()==0x35 && native_take_key()==255);
 /* Simultaneous different keys are all retained in deterministic order. */
 rows[1]=64;rows[7]=64;scan(12);memset(rows,0,8);scan(13);
 assert(native_take_key()==0x2f && native_take_key()==0x39 && native_take_key()==255);
 /* Confirm and Exit never auto-repeat, even after several seconds. */
 scan(17);rows[1]=64;rows[0]=64;scan(18);scan(500);scan(800);
 assert(native_take_key()==0x2e && native_take_key()==0x2f && native_take_key()==255);
 reset();rows[7]=8;scan(1);assert(native_take_key()==0x35);
 scan(40);scan(80);assert(native_take_key()==255);scan(81);assert(native_take_key()==0x35);
 scan(100);assert(native_take_key()==255);scan(101);assert(native_take_key()==0x35);
 scan(121);scan(141);scan(161); /* Do not bank three stale repeats while busy. */
 assert(c6502_key_count==1 && native_take_key()==0x35 && native_take_key()==255);
 rows[7]=0;scan(162);rows[7]=8;scan(163);assert(native_take_key()==0x35);
 reset();
 /* Entry baseline suppresses launcher Enter, but the next short Enter works. */
 c6502_key_initialized=0;rows[1]=64;scan(1);scan(500);assert(native_take_key()==255);
 rows[1]=0;scan(501);scan(505);rows[1]=64;scan(506);rows[1]=0;scan(507);
 assert(native_take_key()==0x2f && native_take_key()==255);
 reset();
 for(unsigned i=0;i<20;++i){rows[7]=8;scan(2*i+1);rows[7]=0;scan(2*i+2);}
 assert(c6502_key_count==16 && c6502_perf.key_queue_overflows==4);
 for(unsigned i=0;i<16;++i)assert(native_take_key()==0x35);
 assert(native_take_key()==255 && c6502_perf.keys_consumed==16);
 reset();scan(0xfffffff0);rows[7]=8;scan(0xfffffff1);assert(native_take_key()==0x35);
 scan(0x20);scan(0x41);assert(native_take_key()==0x35); /* CTM unsigned wrap */
 reset();rows[7]=8;scan(1);assert(native_take_key()==0x35);
 scan(258);assert(native_take_key()==255); /* no false repeat after a long gap */
 return 0;
}
"""
    c = tmp_path / "input.c"
    exe = tmp_path / "input.exe"
    c.write_text(source, encoding="utf-8")
    subprocess.run([cc, "-O2", "-I", str(DATA / "runtime"), str(c), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)


def test_long_blits_and_api_boundaries_capture_without_consuming():
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    lcd = runtime.split("static void native_lcd_write(c6502_u16 address)\n{", 1)[1].split(
        "static c6502_u8 map_key", 1
    )[0]
    graphics = runtime.split("static void api_graphics", 1)[1].split(
        "static void native_strcmp", 1
    )[0]
    assert "native_capture_keys();" in lcd
    assert graphics.count("native_capture_keys();") == 2
    assert "native_take_key" not in lcd + graphics
    begin = runtime.split("void c6502_native_perf_begin", 1)[1].split(
        "static void native_log_value", 1
    )[0]
    assert "native_capture_keys();" in begin


def test_pending_timer_leaves_raw_key_queued_rom_and_native(tmp_path):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    if DEFAULT_ROME.is_file():
        from native_rom_reference import FirmwareMemory, invoke_firmware

        memory = FirmwareMemory(8)
        memory.ram[0x201E] = 1
        memory.ram[0x2003] = 1  # hardware keyboard ring has an Enter
        memory.ram[0x2008] = 0x2F
        cpu = invoke_firmware(memory, 0x5088, 0, b"\x00\x26")
        assert cpu.a == 1
        assert memory.ram[0x2600:0x2603] == b"\x06\x00\x00"
        assert memory.ram[0x2004] == 0  # not consumed by the timer wait
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    helper = (
        "static void api_get_message"
        + runtime.split("static void api_get_message", 1)[1].split("static void api_get_key", 1)[0]
    )
    source = (
        r"""
#include <assert.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;typedef unsigned c6502_u32;
static unsigned char ram[32768],key=0x2f,c6502_timer_pending;
static unsigned char c6502_key_count=1,c6502_timer_key_deferred;
static struct {unsigned timer_messages_delivered,key_messages_delivered,timer_key_yields,timer_key_deferrals;} c6502_perf;
static struct {unsigned char*ram;} c6502_native_state={ram};
static unsigned short stack16(unsigned*r,unsigned off){return 0x2600;}
static void native_update_timer(void){}static void native_refresh_if_due(void){}
static void native_capture_keys(void){}
static unsigned char native_window_key(int w){unsigned char k=key;key=255;c6502_key_count=c6502_timer_key_deferred=0;return k;}
static void return8(unsigned*r,unsigned char a){r[4]=a;}
"""
        + helper
        + r"""
int main(void){unsigned r[15]={0};ram[0x201e]=1;
 api_get_message(r);assert(r[4]==1 && ram[0x2600]==6 && key==0x2f && !ram[0x201e]);
 api_get_message(r);assert(r[4]==1 && ram[0x2600]==1 && ram[0x2601]==0x2f && key==255);
 c6502_timer_pending=1;key=0x35;c6502_key_count=1;api_get_message(r);
 assert(!c6502_timer_pending && ram[0x2600]==6 && key==0x35);
 assert(c6502_perf.timer_messages_delivered==2 && c6502_perf.key_messages_delivered==1);
 return 0;}
"""
    )
    c = tmp_path / "priority.c"
    exe = tmp_path / "priority.exe"
    c.write_text(source, encoding="utf-8")
    subprocess.run([cc, "-O2", str(c), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)


def test_continuously_pending_timer_does_not_starve_captured_keys(tmp_path):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    helper = (
        "static void api_get_message"
        + runtime.split("static void api_get_message", 1)[1].split("static void api_get_key", 1)[0]
    )
    source = (
        r"""
#include <assert.h>
#include <stdio.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;typedef unsigned c6502_u32;
static struct {unsigned key_scans,key_scan_max_gap_ticks,key_edges,key_repeats,
 keys_consumed,key_queue_peak,key_queue_overflows,timer_messages_delivered,
 key_messages_delivered,timer_key_deferrals,timer_key_yields;} c6502_perf;
#include "c6502_native_input.h"
static unsigned char ram[32768],c6502_timer_pending;
static struct {unsigned char *ram;} c6502_native_state={ram};
static unsigned short stack16(unsigned*r,unsigned off){return 0x2600;}
/* Force an expired timer on EVERY query, as when each animation/render
   callback takes longer than the guest timer period on real hardware. */
static void native_update_timer(void){ram[0x201e]|=1;c6502_timer_pending=1;}
static void native_refresh_if_due(void){}static void native_capture_keys(void){}
static unsigned char native_window_key(int wait){return native_take_key();}
static void return8(unsigned*r,unsigned char a){r[4]=a;}
"""
        + helper
        + r"""
int main(void){unsigned r[15]={0};
 for(unsigned i=0;i<16;++i)native_queue_key(0x35+(i&1),0);
 for(unsigned i=0;i<16;++i){
  api_get_message(r);assert(ram[0x2600]==6 && c6502_key_count==16-i);
  api_get_message(r);
  if(ram[0x2600]!=1){fprintf(stderr,"key starved: timer keeps winning, queued=%u consumed=%u\n",c6502_key_count,c6502_perf.keys_consumed);return 2;}
  assert(ram[0x2601]==0x35+(i&1) && c6502_key_count==15-i);
  assert(c6502_timer_pending && (ram[0x201e]&1)); /* Do not discard the pending timer. */
 }
 for(unsigned i=0;i<5;++i){api_get_message(r);assert(ram[0x2600]==6);}
 assert(c6502_perf.timer_messages_delivered==21 && c6502_perf.keys_consumed==16);
 assert(c6502_perf.timer_key_deferrals==16 && c6502_perf.timer_key_yields==16);
 /* SysGetKey consuming a deferred key cancels the arbitration token;
    a different, newly queued key still gets ordinary first-Timer priority. */
 native_queue_key(0x35,0);api_get_message(r);assert(ram[0x2600]==6);
 assert(native_take_key()==0x35);native_queue_key(0x37,0);
 api_get_message(r);assert(ram[0x2600]==6 && c6502_key_count==1);
 api_get_message(r);assert(ram[0x2600]==1 && ram[0x2601]==0x37);
 return 0;
}
"""
    )
    c, exe = tmp_path / "starvation.c", tmp_path / "starvation.exe"
    c.write_text(source, encoding="utf-8")
    subprocess.run([cc, "-O2", "-I", str(DATA / "runtime"), str(c), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=10)
