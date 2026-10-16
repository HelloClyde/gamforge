"""Execute the T GUI collector: SDK scan codes, IAL, power and native unwind."""

import json
import os
import subprocess

import pytest
from test_exit import run_c

from a9288.compiler.build import generate_bridges
from a9288.compiler.s1c33_compat import preserve_comparison_flags
from a9288.paths import DATA


def test_9288t_matrix_normalizes_all_six_controls(tmp_path):
    # Retain the historical matrix-helper regression. The current T game
    # input path no longer calls this helper, but its logical ABI must not
    # contaminate the original 9288/S implementations in the shared file.
    run_c(
        tmp_path,
        r"""
#include <assert.h>
typedef unsigned char c6502_u8;typedef unsigned c6502_u32;
#define C6502_TARGET_9288T 1
#define C6502_K5_DATA_ADDRESS 1
#define C6502_PORT0_DATA_ADDRESS 2
#define C6502_KEY_ROW_SELECT_ADDRESS 3
static c6502_u8 matrix[8],selected=255,k5,port0;
static volatile c6502_u8 *hardware_byte(unsigned address){
 unsigned bits=0;for(unsigned row=0;row<8;++row)if(!(selected&(1u<<row)))bits|=matrix[row];
 if(address==3)return &selected;k5=(c6502_u8)~bits;port0=(c6502_u8)~bits;
 return address==1?&k5:&port0;}
#include "c6502_native_matrix.h"
int main(void){unsigned i,j;c6502_u8 current[8];
 const unsigned mapping[6][4]={{7,128,7,64},{6,16,7,32},{7,16,7,16},
 {6,32,7,8},{4,16,0,64},{5,16,1,64}};
 for(i=0;i<6;++i){for(j=0;j<8;++j)matrix[j]=0;
  matrix[mapping[i][0]]=mapping[i][1];native_matrix_snapshot(current,i);
  for(j=0;j<8;++j)assert(current[j]==(j==mapping[i][2]?mapping[i][3]:0));
  assert(selected==255);}
 for(j=0;j<8;++j)matrix[j]=0;matrix[1]=64;native_matrix_snapshot(current,6);
 for(j=0;j<8;++j)assert(!current[j]);assert(!c6502_matrix_unstable_rows);return 0;}
""",
    )


def input_source():
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    mapping = (
        "static c6502_u8 map_key"
        + runtime.split("static c6502_u8 map_key", 1)[1].split(
            "static volatile c6502_u8 *hardware_byte", 1
        )[0]
    )
    translate = (
        "static c6502_u8 translate_key"
        + runtime.split("static c6502_u8 translate_key", 1)[1].split(
            "static void api_translate_message", 1
        )[0]
    )
    # Public SDK guiCommon.h scan-code contract, not private matrix bits.
    scans = {
        "ESCAPE": 1,
        "ENTER": 28,
        "KEYPADENTER": 96,
        "LEFTSHIFT": 42,
        "RIGHTSHIFT": 54,
        "SHIFT": 66,
        "HELP": 87,
        "POWER_OFF_ON": 88,
        "F12": 88,
        "SPACE": 57,
        "PAGEUP": 104,
        "PAGEDOWN": 109,
        "CURSORUP": 72,
        "CURSORLEFT": 75,
        "CURSORDOWN": 80,
        "CURSORRIGHT": 77,
        "CURSORBLOCKUP": 103,
        "CURSORBLOCKLEFT": 105,
        "CURSORBLOCKDOWN": 108,
        "CURSORBLOCKRIGHT": 106,
        "INPUTMETHORD": 120,
        "INSERT": 110,
        "MODIFY": 65,
        "SEARCH": 67,
        "REMOVE": 111,
        "BACKSPACE": 14,
        "CATALOG": 63,
        "SPEECH": 64,
        "0": 11,
    }
    scans.update({str(i): i + 1 for i in range(1, 10)})
    scans.update({key: 16 + i for i, key in enumerate("QWERTYUIOP")})
    scans.update({key: 30 + i for i, key in enumerate("ASDFGHJKL")})
    scans.update({key: 44 + i for i, key in enumerate("ZXCVBNM")})
    prelude = r"""
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;
typedef unsigned short T_UHWORD;
typedef unsigned c6502_u32,T_WORD,T_GUI_HWND,T_GUI_WPARAM,T_GUI_LPARAM;
typedef struct {unsigned message,hWnd,wParam,lParam;} T_GUI_Msg;
#define C6502_TARGET_9288T 1
#define KS_SHIFT 3u
static unsigned char shift_pin=255;
static volatile unsigned char *hardware_byte(unsigned a){assert(a==0x402c4);return &shift_pin;}
enum {MSG_FIRSTKEYMSG=0x10,MSG_LASTKEYMSG=0x1f,MSG_KEYDOWN=0x10,MSG_CHAR=0x11,
 MSG_KEYUP=0x12,MSG_SYSKEYDOWN=0x13,MSG_SYSCHAR=0x14,MSG_SYSKEYUP=0x15,
 MSG_DT_KEYOFF=0xda,MSG_DT_KEYDOWN=0xea,MSG_DT_CHAR=0xeb,MSG_DT_KEYUP=0xec,
 MSG_DT_SYSKEYDOWN=0xed,MSG_DT_SYSCHAR=0xee,MSG_DT_SYSKEYUP=0xef,
 MSG_TIMER=0x144,MSG_CLOSE=0x67,MSG_PAINT=0x66,MSG_HELP=0x7fd};
static struct {unsigned window;} c6502_native_state={77};
static struct {unsigned key_scans,key_scan_max_gap_ticks,key_edges,key_repeats,
 keys_consumed,key_queue_peak,key_queue_overflows;} c6502_perf;
static unsigned now,gets,dispatches,translated,power,closes,recursion;
static unsigned c6502_native_host_stop_requested;
static unsigned char c6502_native_t_quit_received;
static T_GUI_Msg messages[64];static unsigned head,count,quit;
static unsigned native_clock(void){return now;}
static int fnGUI_HavePendingMessage(unsigned w){assert(w==77);return count!=0;}
static int fnGUI_GetMessage(T_GUI_Msg*m,unsigned w){assert(w==77);++gets;
 if(quit){quit=0;return 0;}
 if(count){*m=messages[head++];--count;return 1;}
 now+=7;*m=(T_GUI_Msg){MSG_TIMER,77,1,0};return 1;}
static void native_t_pump(unsigned tick);
int c6502_native_t_key_message(T_WORD,T_GUI_WPARAM,T_GUI_LPARAM);
static void fnGUI_TranslateMessage(T_GUI_Msg*m){++translated;}
static void fnGUI_DispatchMessage(T_GUI_Msg*m){++dispatches;
 if(m->hWnd==77)(void)c6502_native_t_key_message(m->message,m->wParam,m->lParam);
 if(m->wParam==88)++power;
 if(m->message==MSG_CLOSE){++closes;c6502_native_host_stop_requested=1;}
 if(recursion)native_t_pump(now);}
static void push(unsigned m,unsigned k){messages[head+count++]=(T_GUI_Msg){m,77,k,0};}
"""
    return (
        prelude
        + "\n".join(f"#define SCANCODE_{k} {v}" for k, v in scans.items())
        + '\n#include "c6502_native_input.h"\n'
        + mapping
        + translate
        + '\n#include "c6502_native_exit.h"\n'
        + '#include "c6502_native_9288t_input.h"\n'
        + r"""
static void reset(void){memset(&c6502_perf,0,sizeof(c6502_perf));
 now=gets=dispatches=translated=power=closes=recursion=head=count=quit=0;shift_pin=255;
 native_key_diagnostics_reset();c6502_native_t_input_reset();
 c6502_input_active=c6502_t_gui_accept=1;}
static void tap(unsigned scan,unsigned raw){unsigned char type;
 assert(c6502_native_t_key_message(MSG_KEYDOWN,scan,0));
 assert(c6502_native_t_key_message(MSG_CHAR,scan,0)); /* duplicate CHAR ignored */
 assert(c6502_native_t_key_message(MSG_KEYUP,scan,0));
 assert(native_take_key()==raw && native_take_key()==255);
 (void)translate_key(raw,&type);assert(type);}
"""
    )


def test_all_letters_digits_space_pages_help_and_shift(tmp_path):
    run_c(
        tmp_path,
        input_source()
        + r"""
int main(void){reset();
 unsigned scan[]={30,48,46,32,18,33,34,35,23,36,37,38,50,49,24,25,16,19,31,20,22,47,17,45,21,44};
 unsigned raw[]={24,37,35,26,18,27,28,29,23,30,31,52,39,38,50,51,16,19,25,20,22,36,17,34,21,33};
 for(unsigned i=0;i<26;++i){unsigned char type;tap(scan[i],raw[i]);
  assert(translate_key(raw[i],&type)=='a'+i && type==2);}
 for(unsigned i=1;i<=9;++i)tap(i+1,i<9?7+i:0x30);tap(11,0x31);
 tap(57,0x36);tap(104,0x3a);tap(109,0x3b);tap(87,0x2d);
 tap(42,0x28);tap(54,0x28);tap(66,0x28);tap(120,0x20);
 tap(111,0x2c);tap(14,0x2c);tap(110,0x29);tap(65,0x2a);tap(67,0x2b);
 tap(63,1);tap(64,7);tap(1,0x2e);tap(28,0x2f);tap(96,0x2f);
 unsigned char type;assert(translate_key(map_key(87),&type)==0x26 && type==5);
 assert(map_key(88)==255 && native_take_key()==255);return 0;}
""",
    )


def test_taps_duplicates_repeats_ial_power_close_and_quit(tmp_path):
    run_c(
        tmp_path,
        input_source()
        + r"""
int main(void){reset();
 push(MSG_KEYDOWN,106);push(MSG_DT_KEYDOWN,106);push(MSG_CHAR,'6');
 push(MSG_KEYUP,106);push(MSG_KEYDOWN,106);push(MSG_KEYUP,106);
 native_t_pump(0);assert(gets==6 && c6502_perf.key_edges==2);
 assert(native_take_key()==0x39 && native_take_key()==0x39 && native_take_key()==255);
 /* System repeats do not spam action keys; real release permits next tap. */
 tap(28,0x2f);push(MSG_KEYDOWN,28);push(MSG_KEYDOWN,28);push(MSG_KEYDOWN,28);
 native_t_pump(now);assert(native_take_key()==0x2f && native_take_key()==255);
 now+=256;native_t_pump(now);assert(native_take_key()==255);
 push(MSG_KEYUP,28);push(MSG_KEYDOWN,28);push(MSG_KEYUP,28);
 native_t_pump(now);assert(native_take_key()==0x2f);
 reset();tap(106,0x39);push(MSG_KEYDOWN,106);native_t_pump(now);
 assert(native_take_key()==0x39);now=79;native_t_pump(now);assert(native_take_key()==0x39);
 now+=20;native_t_pump(now);native_t_pump(now+20);assert(c6502_key_count==1);
 push(MSG_KEYUP,106);native_t_pump(now);assert(native_take_key()==0x39);
 /* No key/CHAR byte becomes power accidentally; F12 reaches host exactly once. */
 reset();push(MSG_KEYDOWN,88);push(MSG_CHAR,'x');push(MSG_KEYUP,88);
 native_t_pump(now);assert(power==2 && dispatches==3 && translated==3 && !c6502_key_count);
 /* HavePending=false still enters GetMessage once for IAL; bounded/reentrant. */
 reset();recursion=1;native_t_pump(0);assert(gets==1 && dispatches==1);
 native_t_pump(now);assert(gets==1);now+=8;native_t_pump(now);assert(gets==2);
 reset();for(unsigned i=0;i<24;++i)push(MSG_TIMER,2);
 native_t_pump(0);assert(gets==16 && count==8);native_t_pump(now);assert(!count);
 reset();push(MSG_CLOSE,0);push(MSG_KEYDOWN,28);native_t_pump(0);
 assert(closes==1 && c6502_native_host_stop_requested && gets==1 && !c6502_key_count);
 native_t_pump(0);assert(gets==1);reset();quit=1;native_t_pump(0);
 assert(c6502_native_t_quit_received && c6502_native_host_stop_requested);
 return 0;}
""",
    )


def test_launch_and_exit_release_barriers_keep_power_and_clear_game_keys(tmp_path):
    run_c(
        tmp_path,
        input_source()
        + r"""
int main(void){reset();c6502_t_gui_accept=0;
 push(MSG_KEYDOWN,28);push(MSG_CHAR,13);push(MSG_KEYUP,28);
 native_t_finish_input();assert(!c6502_key_count && !c6502_input_active && now>=32);
 c6502_input_active=c6502_t_gui_accept=1;tap(28,0x2f);
 push(MSG_KEYDOWN,106);push(MSG_KEYUP,106);push(MSG_KEYDOWN,88);push(MSG_KEYUP,88);
 native_t_finish_input();assert(power==2 && !c6502_key_count && !c6502_input_active);
 reset();quit=1;native_t_finish_input();assert(c6502_native_t_quit_received && !c6502_key_count);
 return 0;}
""",
    )


def test_standalone_shift_modifier_chord_and_fresh_launch_letter(tmp_path):
    run_c(
        tmp_path,
        input_source()
        + r"""
int main(void){reset();
 /* Physical Shift alone has no IAL KEYDOWN. Sample its independent K6 pin. */
 shift_pin=239;native_t_pump(now);assert(native_take_key()==0x28);
 now+=8;native_t_pump(now);assert(native_take_key()==255);
 /* A genuine Shift+A carries GUI modifier flags, and follows Shift once. */
 push(MSG_KEYDOWN,30);messages[head].lParam=KS_SHIFT;
 native_t_pump(now);assert(native_take_key()==0x18 && native_take_key()==255);
 push(MSG_KEYUP,30);native_t_pump(now);
 shift_pin=255;now+=8;native_t_pump(now);shift_pin=239;now+=8;
 native_t_pump(now);assert(native_take_key()==0x28 && native_take_key()==255);
 shift_pin=255;now+=8;native_t_pump(now);
 /* A real C press is NOT blacklisted because it launched the application. */
 tap(46,0x23);assert(c6502_t_gui_shift_edges==2);
 return 0;}
""",
    )


def test_real_t_help_notification_is_a_key_once(tmp_path):
    run_c(
        tmp_path,
        input_source()
        + r"""
int main(void){reset();push(MSG_HELP,87);push(MSG_KEYDOWN,87);push(MSG_KEYUP,87);
 native_t_pump(now);assert(native_take_key()==0x2d && native_take_key()==255);
 push(MSG_HELP,87);push(MSG_KEYUP,87);native_t_pump(now);
 assert(native_take_key()==0x2d && native_take_key()==255);
 assert(c6502_key_code_counts[0x2d][0]==2);return 0;}
""",
    )


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("preclosed", [False, True])
def test_s1c33_gui_close_unwinds_only_after_c_returns(tmp_path, external, preclosed):
    clang, emulator = os.getenv("A9288_TEST_CLANG"), os.getenv("A9288_TEST_C33EMU")
    if not clang or not emulator:
        pytest.skip("optional S1C33 tools not configured")
    _, bridges = generate_bridges(
        ["c6502_adapter_sysgetkey"],
        tmp_path,
        external_resources=external,
        host_gui_input=True,
    )
    assembly = tmp_path / "probe.S"
    # C's public entry simulates a native -> bridge -> GUI callback stack;
    # the C return must complete, then all guest call frames are abandoned.
    assembly.write_text(
        """.text
.globl _start
_start:
 ext 69
 ext 0
 ld.w %r5, 0
 ld.w %sp, %r5
 ld.w %r15, 17
 call probe
 halt
.globl c6502_game_fn_00046
c6502_game_fn_00046:
 sub %sp, 12
 call c6502_adapter_sysgetkey
 ld.w %r4, 0
 ret
.globl c6502_native_bridge
c6502_native_bridge:
 sub %sp, 12
 ext c6502_native_host_stop_requested@h
 ext c6502_native_host_stop_requested@m
 ld.w %r0, c6502_native_host_stop_requested@l
 ld.w %r1, 1
 ld.w [%r0], %r1
 ext callback_complete@h
 ext callback_complete@m
 ld.w %r0, callback_complete@l
 ld.w [%r0], %r1
 add %sp, 12
 ret
""",
        encoding="utf-8",
    )
    c = tmp_path / "probe.c"
    c.write_text(
        "typedef unsigned long U;\n"
        "volatile U c6502_bridge_regs[15],c6502_bridge_target;\n"
        "U c6502_host_dp,c6502_native_entry_sp,c6502_resource_entry_sp,callback_complete;\n"
        f"volatile U c6502_native_host_stop_requested={int(preclosed)};\n"
        "extern void c6502_native_enter(U*);static U r[15];\n"
        "int probe(void){U before,after,dp;"
        '__asm__ volatile("ld.w %0,%%sp":"=r"(before));'
        "c6502_native_enter(r);"
        '__asm__ volatile("ld.w %0,%%sp":"=r"(after));'
        '__asm__ volatile("ld.w %0,%%r15":"=r"(dp));'
        f"return before==after && dp==17 && callback_complete=={int(not preclosed)} && "
        "c6502_native_entry_sp==0 && c6502_native_host_stop_requested==1;}\n",
        encoding="utf-8",
    )
    c_asm = tmp_path / "c.S"
    subprocess.run(
        [clang, "--target=s1c33-none-elf", "-Os", "-ffreestanding", "-S", str(c), "-o", str(c_asm)],
        check=True,
        capture_output=True,
    )
    fixed, _ = preserve_comparison_flags(c_asm.read_text(encoding="utf-8"))
    c_asm.write_text(fixed, encoding="utf-8")
    script = tmp_path / "link.ld"
    script.write_text(
        "SECTIONS { .text 0x02700000 : { *(.text*) } "
        ".data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }",
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
            str(assembly),
            str(c_asm),
            str(bridges),
            "-o",
            str(elf),
        ],
        check=True,
        capture_output=True,
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
    assert state["halted"] and not state["faulted"], state
    assert int(state["r"][4], 16) == 1 and not state["unknown_accesses"], state
