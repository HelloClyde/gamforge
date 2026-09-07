"""Public-runtime regressions: action bounce, teardown keys, log rotation."""

import shutil
import subprocess

import pytest

from a9288.paths import DATA


def run_c(tmp_path, source):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    c, exe = tmp_path / "probe.c", tmp_path / "probe.exe"
    c.write_text(source, encoding="utf-8")
    subprocess.run(
        [cc, "-std=c99", "-O2", "-I", str(DATA / "runtime"), str(c), "-o", str(exe)], check=True
    )
    subprocess.run([str(exe)], cwd=tmp_path, check=True, timeout=10)


def test_confirm_exit_bounce_and_real_second_tap(tmp_path):
    run_c(
        tmp_path,
        r"""
#include <assert.h>
typedef unsigned char c6502_u8;typedef unsigned c6502_u32;
static struct {unsigned key_scans,key_scan_max_gap_ticks,key_edges,key_repeats,
 keys_consumed,key_queue_peak,key_queue_overflows;} c6502_perf;
#include "c6502_native_input.h"
int main(void){unsigned char rows[8]={0};native_key_snapshot(rows,0);
 rows[1]=64;native_key_snapshot(rows,1);assert(native_take_key()==0x2f);
 rows[1]=0;native_key_snapshot(rows,2); /* a single-scan release glitch */
 rows[1]=64;native_key_snapshot(rows,3);assert(native_take_key()==255);
 native_key_snapshot(rows,1000);assert(native_take_key()==255); /* held, no repeat */
 rows[1]=0;native_key_snapshot(rows,1001);native_key_snapshot(rows,1005);
 rows[1]=64;native_key_snapshot(rows,1006);rows[1]=0;native_key_snapshot(rows,1007);
 assert(native_take_key()==0x2f && native_take_key()==255); /* short second tap */
 rows[0]=64;rows[5]=64;native_key_snapshot(rows,1008);
 assert(native_take_key()==0x2e && native_take_key()==255); /* Exit aliases */
 rows[0]=rows[5]=0;native_key_snapshot(rows,1009);
 rows[5]=64;native_key_snapshot(rows,1010);assert(native_take_key()==255);
 assert(c6502_action_bounces==2 && c6502_perf.key_edges==3);
 c6502_key_initialized=0;rows[1]=64;native_key_snapshot(rows,0xfffffff0u);
 rows[1]=rows[5]=0;native_key_snapshot(rows,0xfffffffeu);
 native_key_snapshot(rows,2);rows[1]=64;native_key_snapshot(rows,3);
 assert(native_take_key()==0x2f && native_take_key()==255); /* wrap, launch baseline */
 return 0;}
""",
    )


def test_teardown_does_not_dispatch_or_translate_keys(tmp_path):
    run_c(
        tmp_path,
        r"""
#include <assert.h>
typedef unsigned T_WORD;typedef struct {unsigned message;} T_GUI_Msg;
enum {MSG_FIRSTKEYMSG=0x10,MSG_LASTKEYMSG=0x1f,
 MSG_KEYDOWN=0x10,MSG_CHAR=0x11,MSG_KEYUP=0x12,MSG_SYSKEYDOWN=0x13,MSG_SYSCHAR=0x14,MSG_SYSKEYUP=0x15,
 MSG_DT_KEYOFF=0xda,MSG_DT_KEYDOWN=0xea,MSG_DT_CHAR=0xeb,MSG_DT_KEYUP=0xec,
 MSG_DT_SYSKEYDOWN=0xed,MSG_DT_SYSCHAR=0xee,MSG_DT_SYSKEYUP=0xef,
 MSG_TIMER=0x30,MSG_PAINT=0x40,MSG_CLOSE=0x50};
static unsigned translated,dispatched,launches;
static void fnGUI_TranslateMessage(T_GUI_Msg*m){++translated;if(m->message==MSG_KEYDOWN)++launches;}
static void fnGUI_DispatchMessage(T_GUI_Msg*m){++dispatched;if(m->message==MSG_CHAR)++launches;}
#include "c6502_native_exit.h"
int main(void){unsigned keys[]={MSG_KEYDOWN,MSG_CHAR,MSG_KEYUP,MSG_SYSKEYDOWN,MSG_SYSCHAR,MSG_SYSKEYUP,
 MSG_DT_KEYOFF,MSG_DT_KEYDOWN,MSG_DT_CHAR,MSG_DT_KEYUP,MSG_DT_SYSKEYDOWN,MSG_DT_SYSCHAR,MSG_DT_SYSKEYUP};
 for(unsigned i=0;i<sizeof(keys)/sizeof(keys[0]);++i){T_GUI_Msg m={keys[i]};
  assert(native_is_key_message(m.message));native_dispatch_teardown(&m);}
 assert(!translated && !dispatched && !launches);
 unsigned other[]={MSG_TIMER,MSG_PAINT,MSG_CLOSE,0xd9,0xdb,0xe9,0xf0};
 for(unsigned i=0;i<sizeof(other)/sizeof(other[0]);++i){T_GUI_Msg m={other[i]};
  assert(!native_is_key_message(m.message));native_dispatch_teardown(&m);}
 assert(!launches && translated==7 && dispatched==7);return 0;}
""",
    )


def test_exit_waits_for_release_with_gui_alive(tmp_path):
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    finish = (
        "void c6502_native_finish_input(void)"
        + runtime.split("void c6502_native_finish_input(void)", 1)[1].split(
            "static c6502_u8 native_window_key", 1
        )[0]
    )
    run_c(
        tmp_path,
        r"""
#include <assert.h>
typedef unsigned T_GUI_HWND;typedef unsigned T_WORD;
typedef unsigned char c6502_u8;typedef unsigned c6502_u32;
typedef struct {unsigned message,hWnd,wParam;} T_GUI_Msg;
enum {MSG_FIRSTKEYMSG=0x10,MSG_LASTKEYMSG=0x1f,MSG_KEYDOWN=0x10,MSG_KEYUP=0x12,MSG_CHAR=0x11,
 MSG_DT_KEYOFF=0xda,MSG_DT_KEYDOWN=0xea,MSG_DT_SYSKEYUP=0xef,MSG_TIMER=0x30};
static struct {unsigned window;} c6502_native_state={123};
static unsigned c6502_key_scan_tick,dispatches,last_message_tick,scenario;
static unsigned char c6502_key_previous[8],c6502_input_active=1,
 c6502_key_head=3,c6502_key_count=2,c6502_timer_key_deferred=1;
#define C6502_ACTION_RELEASE_TICKS 4u
static void native_capture_keys(void){++c6502_key_scan_tick;assert(c6502_input_active);
 assert(c6502_key_scan_tick<100);
 c6502_key_previous[1]=(c6502_key_scan_tick<10 || c6502_key_scan_tick==11)?64:0;}
static int fnGUI_HavePendingMessage(unsigned w){assert(w==123);
 return scenario==4?0:last_message_tick<c6502_key_scan_tick;}
static int fnGUI_GetMessage(T_GUI_Msg*m,unsigned w){assert(w==123);last_message_tick=c6502_key_scan_tick;
 m->message=(c6502_key_scan_tick==30)?MSG_DT_KEYDOWN:MSG_TIMER;m->hWnd=w;m->wParam=1;
 if(scenario==1 && c6502_key_scan_tick<70)m->hWnd=999; /* foreign timer is not our barrier */
 if(scenario==2 && c6502_key_scan_tick<70)m->wParam=2; /* wrong timer ID */
 if(scenario==3 && c6502_key_scan_tick==20)return 0; /* Quit still terminates */
 return 1;}
static void fnGUI_TranslateMessage(T_GUI_Msg*m){assert(m->message==MSG_TIMER);}
static void fnGUI_DispatchMessage(T_GUI_Msg*m){++dispatches;}
#include "c6502_native_exit.h"
"""
        + finish
        + r"""
int main(void){for(scenario=0;scenario<5;++scenario){
 c6502_key_scan_tick=dispatches=last_message_tick=0;c6502_input_active=1;
 c6502_key_head=3;c6502_key_count=2;c6502_timer_key_deferred=1;
 c6502_native_finish_input();
 assert(c6502_key_scan_tick==(scenario==3?20:(scenario==1 || scenario==2)?71:62));
 assert(!c6502_input_active && !c6502_key_count && !c6502_key_head && !c6502_timer_key_deferred);
 }return 0;}
""",
    )


def test_log_rotation_preserves_previous_and_rolls_back_failed_promotion(tmp_path):
    run_c(
        tmp_path,
        r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef FILE FS_FILE;
static int fail_promotion;
static FILE*fs_fopen(const char*p,const char*m){return fopen(p+3,m);}
static int fs_fclose(FILE*f){return fclose(f);}
static int fs_remove(const char*p){return remove(p+3);}
static int fs_rename(const char*a,const char*b){
 if(fail_promotion && !strcmp(a+3,"NATIVE.TMP"))return -1;
 return rename(a+3,b+3);}
#include "c6502_native_log.h"
static void put(const char*p,const char*s){FILE*f=fopen(p,"wb");assert(f);fputs(s,f);fclose(f);}
static void equal(const char*p,const char*s){char b[64]={0};FILE*f=fopen(p,"rb");assert(f);
 fread(b,1,63,f);fclose(f);assert(!strcmp(b,s));}
int main(void){
 put("NATIVE.TMP","first game [END]");assert(native_log_commit());
 equal("NATIVE.LOG","first game [END]");
 put("NATIVE.TMP","short relaunch [END]");assert(native_log_commit());
 equal("NATIVE.BAK","first game [END]");equal("NATIVE.LOG","short relaunch [END]");
 put("NATIVE.TMP","third game [END]");fail_promotion=1;assert(!native_log_commit());
 equal("NATIVE.LOG","short relaunch [END]");equal("NATIVE.TMP","third game [END]");
 fail_promotion=0;assert(native_log_commit());equal("NATIVE.LOG","third game [END]");
 equal("NATIVE.BAK","short relaunch [END]");return 0;}
""",
    )


def test_exit_order_and_launcher_filter_are_kept():
    app = (DATA / "runtime/c6502_native_9288.c").read_text(encoding="utf-8")
    exit_path = app.split("c6502_native_enter(c6502_entry_regs);", 1)[1]
    assert "fnGUI_SetTimer" not in app.split("c6502_native_enter(c6502_entry_regs);", 1)[0]
    assert exit_path.index("fnGUI_SetTimer") < exit_path.index("c6502_native_finish_input();")
    assert exit_path.index("c6502_native_finish_input();") < exit_path.index("fnGUI_KillTimer")
    assert exit_path.index("c6502_native_finish_input();") < exit_path.index("fnGUI_SetFocus")
    assert "fnGUI_TranslateMessage" not in exit_path
    assert "fnGUI_DispatchMessage" not in exit_path
    assert "fnGUI_GetMessage(&message, launcher)" in exit_path
    assert "round < 2u" in exit_path and "0x0004822cu" in exit_path
