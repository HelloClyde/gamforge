"""Official T foreground idle-reset and paired task-3 ownership."""

import json
import os
import subprocess

import pytest
from test_exit import run_c

from a9288.compiler.s1c33_compat import preserve_comparison_flags
from a9288.paths import DATA


def test_verified_reset_body_rejects_wrong_sdk_slot_and_changed_firmware(tmp_path):
    run_c(
        tmp_path,
        r"""
#include <assert.h>
#include <string.h>
#include <stdint.h>
typedef uint8_t c6502_u8;typedef uint32_t c6502_u32;
#include "c6502_native_9288t_host.h"
int main(void) {
 unsigned char code[10]={4,0x6c,0x77,0xd2,0xfc,0xd7,0xf4,0x3c,0x40,6};
 /* Original SDK+0x6b8 actually reads a flag; it must not be called. */
 unsigned char wrong[10]={1,0xd2,0x10,0xc4,0xf4,0x30,0x40,6,0,0};
 assert(C6502_T_AUTOCLOSE_GUI_OFFSET==0x64c);
 assert(native_t_idle_reset_body(code) && !native_t_idle_reset_body(wrong));
 for(unsigned i=0;i<10;++i)for(unsigned bit=0;bit<8;++bit){
  code[i]^=1u<<bit;assert(!native_t_idle_reset_body(code));code[i]^=1u<<bit;
 }
 return 0;
}
""",
    )


def test_no_input_keepalive_passes_one_minute_and_does_not_double_suspend(tmp_path):
    run_c(
        tmp_path,
        r"""
#include <assert.h>
#include <stdint.h>
typedef uint8_t c6502_u8;typedef uint32_t c6502_u32;
static unsigned resets,suspends,resumes,idle_count,closed,irq_enabled=1;
static int reset_seen;
static void reset(void){assert(irq_enabled);idle_count=0;++resets;reset_seen=1;}
static int suspend(int id){assert(id==3);++suspends;return 0;}
static int resume(int id){assert(id==3 && reset_seen);++resumes;return 0;}
#include "c6502_native_9288t_host.h"
int main(void){
 assert(native_t_host_start(reset,suspend,resume,0));
 assert(native_t_host_start(reset,suspend,resume,0));
 assert(suspends==1 && resets==1);
 /* Synthetic 1-minute idle threshold: no key events at all. This tests
    keepalive cadence, not the real firmware interrupt period. */
 for(unsigned tick=1;tick<=3*60*256;++tick){
  if(!(tick&255u) && ++idle_count>=60)closed=1;
  native_t_host_pulse(tick);
 }
 assert(!closed && c6502_t_host.resets==361);
 assert(c6502_t_host.max_gap==128 && c6502_t_host.active);
 native_t_host_stop();native_t_host_stop();
 assert(!c6502_t_host.active && resumes==1 && resets==362);
 assert(c6502_t_host.task_resumed);
 native_t_host_pulse(999999);assert(resets==362);
 assert(native_t_host_start(reset,suspend,resume,999999));
 native_t_host_stop();assert(resumes==2 && suspends==2);
 return 0;
}
""",
    )


def test_failed_suspend_invalid_api_and_clock_wrap_keep_ownership_correct(tmp_path):
    run_c(
        tmp_path,
        r"""
#include <assert.h>
#include <stdint.h>
typedef uint8_t c6502_u8;typedef uint32_t c6502_u32;
static unsigned resets,suspends,resumes;static int fail_suspend,fail_resume;
static void reset(void){++resets;}
static int suspend(int id){assert(id==3);++suspends;return fail_suspend?-17:0;}
static int resume(int id){assert(id==3);++resumes;return fail_resume?-18:0;}
#include "c6502_native_9288t_host.h"
int main(void){
 assert(!native_t_host_start(0,suspend,resume,0));
 assert(!native_t_host_start(reset,0,resume,0));
 assert(!native_t_host_start(reset,suspend,0,0));
 native_t_host_stop();assert(!resets && !suspends && !resumes);
 fail_suspend=1;assert(native_t_host_start(reset,suspend,resume,0));
 native_t_host_pulse(128);native_t_host_stop();assert(suspends==1 && !resumes);
 assert(c6502_t_host.suspend_result==-17 && !c6502_t_host.task_owned);
 fail_suspend=0;assert(native_t_host_start(reset,suspend,resume,0xffffffc0u));
 unsigned before=resets;
 native_t_host_pulse(0xffffffbfu);assert(resets==before); /* backwards */
 native_t_host_pulse(63);assert(resets==before);
 native_t_host_pulse(64);assert(resets==before+1); /* forward uint32 wrap */
 assert(c6502_t_host.max_gap==128);
 fail_resume=1;native_t_host_stop();native_t_host_stop();
 assert(resumes==1 && c6502_t_host.resume_result==-18 && !c6502_t_host.task_resumed);
 return 0;
}
""",
    )


def test_t_host_restore_precedes_filesystem_and_gui_handoff():
    app = (DATA / "runtime/c6502_native_9288.c").read_text(encoding="utf-8")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    leave = app.split("c6502_native_enter(c6502_entry_regs);", 1)[1]
    assert leave.index("c6502_native_t_host_end();") < leave.index("c6502_native_perf_end();")
    assert leave.index("c6502_native_t_host_end();") < leave.index("fnGUI_SetTimer")
    assert leave.index("c6502_native_t_host_end();") < leave.index("c6502_native_finish_input();")
    capture = runtime.split("static void native_capture_keys(void)\n{", 1)[1].split(
        "static c6502_u32 native_clock(void)\n{", 1
    )[0]
    assert capture.index("native_t_host_pulse(now);") < capture.index(
        "write_psr(saved_psr & ~C6502_PSR_IE);"
    )
    assert "ResetAutoCloseTimer" not in runtime
    assert "0x024ef7fc" not in runtime  # No direct writes to firmware globals.


@pytest.mark.parametrize("valid", [True, False])
def test_actual_s1c33_runtime_resolves_and_calls_verified_firmware_body(tmp_path, valid):
    clang, emulator = os.getenv("A9288_TEST_CLANG"), os.getenv("A9288_TEST_C33EMU")
    if not clang or not emulator:
        pytest.skip("optional S1C33 compiler/preview core are not configured")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    functions = runtime.split('#include "c6502_native_9288t_host.h"\n', 1)[1].split(
        "#endif\n#ifdef C6502_CRASH_TRACE", 1
    )[0]
    source = tmp_path / "probe.c"
    source.write_text(
        r"""
typedef unsigned char c6502_u8;typedef unsigned long c6502_u32;
static c6502_u32 gui[512],tick;
static c6502_u32 *tpDL_GUITable=gui;
static unsigned suspends,resumes;
static int suspend(int id){if(id!=3)return -1;++suspends;return 0;}
static int resume(int id){if(id!=3)return -1;++resumes;return 0;}
static struct {int(*ros33_sus_tsk)(int);int(*ros33_rsm_tsk)(int);} os={suspend,resume};
#define tpDL_ROS33Table (&os)
static unsigned native_clock(void){return tick;}
#include "c6502_native_9288t_host.h"
"""
        + functions
        + f"\n#define VALID {int(valid)}\n"
        + r"""
int probe(void){
 volatile unsigned *idle=(volatile unsigned*)0x024ef7fcu;
 *idle=123;gui[0x64c/4]=VALID?0x02136604u:0x0213660eu;
 int started=c6502_native_t_host_begin();
 if(!VALID)return !started && *idle==123 && !suspends && !resumes;
 if(!started || *idle || suspends!=1)return 0;
 *idle=50;tick=128;native_t_host_pulse(tick);if(*idle)return 0;
 c6502_native_t_host_end();c6502_native_t_host_end();
 return resumes==1 && c6502_t_host.task_resumed && !c6502_t_host.active;
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
 call probe
 halt
.section .idle_api,"ax",@progbits
.byte 4,108,119,210,252,215,244,60,64,6
.byte 1,210,16,196,244,48,64,6,0,0
""",
        encoding="utf-8",
    )
    script = tmp_path / "link.ld"
    script.write_text(
        "SECTIONS { .idle_api 0x02136604 : { *(.idle_api) } "
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
    assert state["halted"] and not state["faulted"], state
    assert not state["unknown_accesses"], state
