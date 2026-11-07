"""9288's own idle-reset leaf, bounded system pump and retained game FIFO."""

import json
import os
import subprocess

import pytest
from test_exit import run_c

from a9288.compiler.s1c33_compat import preserve_comparison_flags
from a9288.paths import DATA


def test_9288_body_rejects_t_firmware_and_wrong_sdk_slot(tmp_path):
    run_c(
        tmp_path,
        r"""
#include <assert.h>
#include <stdint.h>
typedef uint8_t c6502_u8;typedef uint32_t c6502_u32;
#include "c6502_native_9288_host.h"
int main(void){
 unsigned char body[]={4,0x6c,0x77,0xd2,0x54,0xcf,0xf4,0x3c,0x40,6};
 unsigned char t[]={4,0x6c,0x77,0xd2,0xfc,0xd7,0xf4,0x3c,0x40,6};
 assert(C6502_9288_IDLE_GUI_OFFSET==0x64c && native_9288_idle_body(body));
 assert(!native_9288_idle_body(t));
 for(unsigned i=0;i<10;++i)for(unsigned b=0;b<8;++b){
  body[i]^=1u<<b;assert(!native_9288_idle_body(body));body[i]^=1u<<b;
 }
 return 0;
}
""",
    )


def test_idle_keepalive_owns_no_tasks_and_handles_clock_wrap(tmp_path):
    run_c(
        tmp_path,
        r"""
#include <assert.h>
#include <stdint.h>
typedef uint8_t c6502_u8;typedef uint32_t c6502_u32;
static unsigned resets,idle,closed,irq=1;
static void reset(void){assert(irq);++resets;idle=0;}
#include "c6502_native_9288_host.h"
int main(void){
 assert(!native_9288_host_start(0,0));native_9288_host_stop();assert(!resets);
 assert(native_9288_host_start(reset,0));assert(native_9288_host_start(reset,0));
 assert(resets==1);
 for(unsigned tick=1;tick<=3*60*256;++tick){
  if(!(tick&1023u) && ++idle>=15u)closed=1;
  native_9288_host_pulse(tick);
 }
 assert(!closed && c6502_9288_host.max_gap==128 && resets==361);
 native_9288_host_stop();native_9288_host_stop();assert(resets==362);
 native_9288_host_pulse(999999);assert(resets==362);
 assert(native_9288_host_start(reset,0xffffffc0u));
 unsigned before=resets;
 native_9288_host_pulse(0xffffffbfu);native_9288_host_pulse(63);
 assert(resets==before);native_9288_host_pulse(64);assert(resets==before+1);
 native_9288_host_stop();return 0;
}
""",
    )


def pump_source():
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    return (
        "static void native_9288_pump"
        + runtime.split("static void native_9288_pump", 1)[1].split(
            "#endif\n#ifdef C6502_TARGET_9288T", 1
        )[0]
    )


def test_message_pump_collects_ial_caps_batches_and_never_queues_game_keys(tmp_path):
    run_c(
        tmp_path,
        r"""
#include <assert.h>
#include <stdint.h>
typedef uint8_t c6502_u8;typedef uint32_t c6502_u32;
typedef unsigned T_GUI_HWND;
typedef struct {unsigned message,hWnd,wParam,lParam;} T_GUI_Msg;
static struct {unsigned window;} c6502_native_state={77};
static unsigned now,gets,translations,dispatches,remaining,reenter,quit,close_event;
static unsigned c6502_native_host_stop_requested,c6502_native_9288_quit_received;
static unsigned c6502_9288_gui_last_pump,c6502_9288_gui_batches;
static unsigned c6502_9288_gui_messages,c6502_9288_gui_keys;
static unsigned char c6502_9288_gui_pumping;
static unsigned c6502_output_ready=1,repairs;
static void c6502_native_present(void){++repairs;}
static void native_refresh_if_due(void){++repairs;}
static unsigned native_clock(void){return now;}
static int native_is_key_message(unsigned m){return m==16;}
static int fnGUI_HavePendingMessage(unsigned w){assert(w==77);return remaining!=0;}
static int fnGUI_GetMessage(T_GUI_Msg*m,unsigned w){
 assert(w==77);++gets;if(quit)return 0;
 *m=(T_GUI_Msg){remaining?16u:0x144u,77,1,0};if(remaining)--remaining;return 1;
}
static void native_9288_pump(unsigned);
static void fnGUI_TranslateMessage(T_GUI_Msg*m){++translations;}
static void fnGUI_DispatchMessage(T_GUI_Msg*m){
 ++dispatches;if(reenter)native_9288_pump(now);
 if(close_event)c6502_native_host_stop_requested=1;
}
static void reset_idle(void){}
#include "c6502_native_9288_host.h"
"""
        + pump_source()
        + r"""
int main(void){
 native_9288_host_start(reset_idle,0);
 native_9288_pump(7);assert(!gets);now=8;
 native_9288_pump(now);assert(gets==1 && dispatches==1 && translations==1 && repairs==1);
 /* Even an empty queue enters real GetMessage to collect hardware IAL. */
 remaining=100;reenter=1;native_9288_pump(now);
 assert(gets==17 && dispatches==17 && remaining==84);
 assert(!c6502_9288_gui_pumping && c6502_9288_gui_keys==16);
 close_event=1;native_9288_pump(now);assert(gets==18 && remaining==83);
 native_9288_pump(now);assert(gets==18);
 c6502_native_host_stop_requested=0;quit=1;native_9288_pump(now);
 assert(c6502_native_9288_quit_received && c6502_native_host_stop_requested);
 assert(!c6502_9288_gui_pumping);
 return 0;
}
""",
    )
    source = pump_source()
    assert "native_queue_key" not in source and "native_key_snapshot" not in source


def test_host_calls_outside_matrix_irq_guard_and_lifecycle_is_bounded():
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    app = (DATA / "runtime/c6502_native_9288.c").read_text(encoding="utf-8")
    capture = runtime.split("static void native_capture_keys(void)\n{", 1)[1].split(
        "static c6502_u32 native_clock(void)\n{", 1
    )[0]
    masked = capture.index("write_psr(saved_psr & ~C6502_PSR_IE)")
    assert capture.index("native_9288_host_pulse(now)") < masked
    assert capture.index("native_9288_pump(now)") < masked
    assert capture.rindex("native_key_snapshot(current, now)") > capture.index(
        "write_psr(saved_psr)"
    )
    assert "ResetAutoCloseTimer" not in runtime  # never call the wrong SDK member
    assert "0x024eef54" not in runtime  # no writes to private system state
    before, after = app.split("c6502_native_enter(c6502_entry_regs);", 1)
    assert "c6502_native_9288_host_begin()" in before
    assert "fnGUI_SetTimer(window, 2, 1)" in before
    assert after.index("c6502_native_9288_host_end()") < after.index("c6502_native_perf_end()")
    assert "c6502_native_9288_quit_received" in after
    builder = (DATA.parent / "compiler/build.py").read_text(encoding="utf-8")
    assert 'host_gui_input=args.target in ("9288", "9288t")' in builder


def test_9288_window_close_defers_destroy_until_native_stack_returns(tmp_path):
    app = (DATA / "runtime/c6502_native_9288.c").read_text(encoding="utf-8")
    callback = (
        "static T_WORD native_window_proc"
        + app.split("static T_WORD native_window_proc", 1)[1].split("T_WORD App_Main", 1)[0]
    )
    run_c(
        tmp_path,
        r"""
#include <assert.h>
typedef unsigned T_WORD,T_GUI_HWND,T_GUI_HDC,T_GUI_WPARAM,T_GUI_LPARAM,c6502_u32;
#define C6502_TARGET_9288_GUI 1
enum {MSG_CLOSE=1,MSG_PAINT,MSG_ERASEBKGND};
enum {NATIVE_EXIT_DESTROY_WINDOW,NATIVE_EXIT_POST_QUIT};
static unsigned native_game_active=1,native_window_closed;
static unsigned c6502_native_host_stop_requested,c6502_native_9288_quit_received;
static unsigned destroyed,posted,defaults,begun,ended,invalidated;
static struct {unsigned window;} c6502_native_state={77};
static int c6502_native_resource_error(void){return 0;}
static unsigned fnGUI_BeginPaint(unsigned w){assert(w==77);++begun;return 88;}
static void fnGUI_EndPaint(unsigned w,unsigned dc){assert(w==77 && dc==88);++ended;}
static void c6502_native_invalidate_screen(void){++invalidated;}
static void c6502_native_exit_checkpoint(unsigned stage,unsigned done,unsigned w){}
static void fnGUI_DestroyMainWindow(unsigned w){assert(w==77);++destroyed;}
static void fnGUI_PostQuitMessage(unsigned w){assert(w==77);++posted;}
static unsigned fnGUI_DefaultMainWinProc(unsigned w,unsigned m,unsigned p,unsigned l){
 ++defaults;return 123;
}
"""
        + callback
        + r"""
int main(void){
 assert(native_window_proc(77,MSG_CLOSE,0,0)==0);
 assert(c6502_native_host_stop_requested && !native_window_closed && !destroyed && !posted);
 assert(native_window_proc(77,MSG_PAINT,0,0)==0);
 assert(begun==1 && ended==1 && invalidated==1);
 assert(native_window_proc(77,1234,0,0)==123 && defaults==1);
 native_game_active=0;c6502_native_9288_quit_received=1;
 native_window_proc(77,MSG_CLOSE,0,0);native_window_proc(77,MSG_CLOSE,0,0);
 assert(native_window_closed && destroyed==1 && !posted);
 return 0;
}
""",
    )


@pytest.mark.parametrize("valid", [True, False])
def test_actual_9288_resolver_and_leaf_execute_on_s1c33(tmp_path, valid):
    clang, emulator = os.getenv("A9288_TEST_CLANG"), os.getenv("A9288_TEST_C33EMU")
    if not clang or not emulator:
        pytest.skip("optional S1C33 compiler/preview core are not configured")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    functions = runtime.split('#include "c6502_native_9288_host.h"\n', 1)[1].split(
        "static void native_9288_pump", 1
    )[0]
    source = tmp_path / "probe.c"
    source.write_text(
        r"""
typedef unsigned char c6502_u8;typedef unsigned long c6502_u32;
static c6502_u32 gui[512],tick;
static c6502_u32 *tpDL_GUITable=gui;
static unsigned c6502_native_host_stop_requested,c6502_native_9288_quit_received;
static unsigned native_clock(void){return tick;}
#include "c6502_native_9288_host.h"
"""
        + functions
        + f"\n#define VALID {int(valid)}\n"
        + r"""
int probe(void){
 volatile unsigned *idle=(volatile unsigned*)0x024eef54u;
 *idle=123;gui[0x64c/4]=VALID?0x0213024cu:0x02130256u;
 int started=c6502_native_9288_host_begin();
 if(!VALID)return !started && *idle==123;
 if(!started || *idle)return 0;
 *idle=50;tick=128;native_9288_host_pulse(tick);if(*idle)return 0;
 c6502_native_9288_host_end();c6502_native_9288_host_end();
 return c6502_9288_host.resets==3 && !c6502_9288_host.active;
}
""",
        encoding="utf-8",
    )
    assembly = tmp_path / "probe.S"
    subprocess.run(
        [
            clang,
            "--target=s1c33-none-elf",
            "-Os",
            "-ffreestanding",
            "-fno-builtin",
            "-S",
            "-I",
            str(DATA / "runtime"),
            str(source),
            "-o",
            str(assembly),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    fixed, _ = preserve_comparison_flags(assembly.read_text(encoding="utf-8"))
    assembly.write_text(fixed, encoding="utf-8")
    entry = tmp_path / "entry.S"
    entry.write_text(
        """.text
.globl _start
_start:
 ext 69
 ext 0
 ld.w %r5, 0
 ld.w %sp, %r5
 ld.w %r15, 0
 call probe
 halt
.section .idle_api,"ax",@progbits
.byte 4,108,119,210,84,207,244,60,64,6
.byte 1,210,16,196,244,48,64,6,0,0
""",
        encoding="utf-8",
    )
    script = tmp_path / "link.ld"
    script.write_text(
        "SECTIONS { .idle_api 0x0213024c : { *(.idle_api) } "
        ".text 0x02700000 : { *(.text*) } .rodata : { *(.rodata*) } "
        ".data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n",
        encoding="utf-8",
    )
    elf = tmp_path / "probe.elf"
    subprocess.run(
        [
            clang,
            "--target=s1c33-none-elf",
            "-nostdlib",
            f"-Wl,-T,{script}",
            "-Wl,-e,_start",
            str(entry),
            str(assembly),
            "-o",
            str(elf),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    result = subprocess.run(
        [
            emulator,
            "--load-elf",
            str(elf),
            "--entry",
            "0x02700000",
            "--steps",
            "100000",
            "--max-unknown-accesses",
            "0",
            "--ram-size",
            "0x100000",
            "--sdram-size",
            "0x2000000",
            "--state-json",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    state = json.loads(result.stdout[result.stdout.index("{") :])
    assert int(state["r"][4], 16) == 1, state
    assert state["halted"] and not state["faulted"] and not state["unknown_accesses"], state
