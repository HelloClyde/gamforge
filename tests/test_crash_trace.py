"""Actual debug recorder, restart survival, checksums and bridge ABI contracts."""

import json
import os
import shutil
import subprocess

import pytest

from a9288.compiler.backend import imm
from a9288.compiler.build import SUPPORTED_BRIDGES, generate_bridges
from a9288.compiler.s1c33_compat import preserve_comparison_flags
from a9288.crash_trace import describe, latest_snapshot, read_snapshot
from a9288.gui import Conversion
from a9288.paths import DATA


def test_generated_bridges_preserve_guest_regs_before_debug_arguments(tmp_path):
    for profile in (False, True):
        header, asm = generate_bridges(
            ["c6502_adapter_syspicture", "c6502_sem_adc8"],
            tmp_path,
            profile_other=profile,
            crash_trace=True,
        )
        text = asm.read_text()
        slow = text.split("c6502_adapter_syspicture:", 1)[1].split("    ret", 1)[0]
        assert slow.index("ld.w [%r3], %r9") < slow.index("ld.w %r8, [%sp+4]")
        assert slow.index("add %r9, 16") < slow.index("pushn %r3")
        assert "call c6502_native_bridge_traced" in slow
        assert "%r15" not in slow
        # The original fast native leaves are not replaced by C emulation.
        fast = text.split("c6502_sem_adc8:", 1)[1].split(".size", 1)[0]
        assert "c6502_native_bridge" not in fast
        assert "c6502_crash_checkpoints" in header.read_text()
    generate_bridges(["c6502_adapter_syspicture"], tmp_path)
    assert "bridge_traced" not in asm.read_text()
    assert "crash_checkpoints" not in header.read_text()


def test_gui_propagates_optional_trace_and_startup(tmp_path):
    arguments = (tmp_path / "test.gam", "魔塔", None, tmp_path / "test.exe", tmp_path, tmp_path)
    assert "--crash-trace" not in Conversion(*arguments).command(tmp_path)
    command = Conversion(*arguments, crash_trace=True).command(tmp_path)
    assert "--crash-trace" in command and "--trace-on-start" not in command
    command = Conversion(*arguments, trace_on_start=True).command(tmp_path)
    assert "--crash-trace" in command and "--trace-on-start" in command


@pytest.fixture
def recorder(tmp_path):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host GCC is not installed")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    wrapper = (
        "void c6502_native_bridge_traced("
        + runtime.split("void c6502_native_bridge_traced(", 1)[1].split("\n}\n#endif", 1)[0]
        + "\n}\n"
    )
    source = (
        r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char c6502_u8; typedef unsigned c6502_u32;
#define C6502_CRASH_TRACE 1
#define C6502_TRACE_TARGET "9288t"
#define C6502_TRACE_GAME_SHA256 "test-hash"
#define C6502_GAME_SIZE 81559u
#define C6502_RAM_SIZE 32768u
#define C6502_HOST_WIDTH 240u
#define C6502_HOST_HEIGHT 160u
#define C6502_HOST_STRIDE 60u
#define C6502_HOST_FRAME_BYTES 9600u
#define C6502_HOST_PACKED_1X 1
static unsigned char framebuffer[9600], c6502_t_frame_shadow[9600], ram[32768];
#define C6502_FRAMEBUFFER framebuffer
static struct {unsigned key_scans,key_scan_max_gap_ticks,key_edges,key_repeats,
 keys_consumed,key_queue_peak,key_queue_overflows;} c6502_perf;
static struct {c6502_u8 *ram; unsigned banks[16];} c6502_native_state;
static unsigned now, updates, closes, fail_write, fail_flush, toggle_inside_wait;
static volatile c6502_u32 c6502_bridge_regs[15];
static c6502_u32 native_clock(void){return now;}
static unsigned get16(unsigned at){return ram[at]|((unsigned)ram[at+1]<<8);}
static const unsigned char c6502_crash_checkpoints[]={0,1,0};
static const char *const c6502_profile_names[]={"session","c6502_runtime_uns_div_long","idle"};
#define C6502_BRIDGE_COUNT 3u
#define FS_FILE FILE
static FILE *trace_open(const char *name,const char *mode){return fopen(name+3,mode);}
static size_t trace_write(const void *p,size_t size,size_t count,FILE *f){
 if(fail_write){fwrite(p,size,count/2,f);return count/2;}return fwrite(p,size,count,f);}
static int trace_update(FILE *f){++updates;fflush(f);return fail_flush?-1:0;}
static int trace_close(FILE *f){++closes;return fclose(f);}
#define fs_fopen trace_open
#define fs_fwrite trace_write
#define fs_ferror ferror
#define fs_update trace_update
#define fs_fclose trace_close
#include "c6502_native_input.h"
#include "c6502_native_lifecycle.h"
#include "c6502_native_debug.h"
static void c6502_native_bridge(c6502_u32 *r,c6502_u32 id){
 if(id==2 && toggle_inside_wait){nd_pending=1;nd_capture_service();assert(nd_active);}
 r[4]=99;
}
"""
        + wrapper
        + r"""
int main(int argc,char **argv){
 unsigned r[15]={0}, old[15], mode=argc>1?(unsigned)atoi(argv[1]):0;
 unsigned char keys[8]={0};
 c6502_native_state.ram=ram;
 memset(framebuffer,255,sizeof(framebuffer));memset(c6502_t_frame_shadow,255,sizeof(c6502_t_frame_shadow));
 for(unsigned i=0;i<15;++i)r[i]=100+i;
 r[10]=0x2000;r[14]=0x2700000;memcpy(old,r,sizeof(r));
 ram[0x2000]=17;ram[0x2001]=34;ram[0x2002]=51;ram[0x2003]=68;
 now=100;nd_reset();nd_indicator();
 assert(!nd_active && !updates && !closes); /* Restart never writes files. */
 if(mode==2)return 0;
 /* A held launcher D is ignored; then an actual edge toggles once. */
 keys[2]=4;native_key_snapshot(keys,100);assert(!nd_pending);
 keys[2]=0;native_key_snapshot(keys,101);
 keys[2]=4;native_key_snapshot(keys,102);assert(nd_pending);
 native_key_snapshot(keys,200);assert(nd_pending && native_take_key()==255);
 nd_service(r,0,0,0);assert(nd_active && updates==2 && closes==2);
 assert(!memcmp(r,old,sizeof(r)));
 for(unsigned i=0;i<20;++i){now=201+i;nd_record(ND_LEAVE,r,2,0x2700010,0x201ff00-i*4);}
 c6502_native_bridge_traced(r,1,0x2700080,0x201ff00);
 assert(r[4]==99 && r[10]==old[10] && nd_writes==4);
 assert(!memcmp(framebuffer,c6502_t_frame_shadow,sizeof(framebuffer)));
 if(mode==1){
  nd_record(ND_ENTER,r,1,0x2700080,0x201fe00);assert(nd_snapshot("before_call"));
  _Exit(99); /* No finish/destructor: log must already be closed/persisted. */
 }
 if(mode==3){
  fail_write=1;nd_record(ND_ENTER,r,1,0x2700080,0x201fe00);
  assert(!nd_snapshot("before_call") && !nd_active && nd_errors==1 && closes==5);
  return 0;
 }
 if(mode==4){
  fail_flush=1;nd_record(ND_ENTER,r,1,0x2700080,0x201fe00);
  assert(!nd_snapshot("before_call") && !nd_active && closes==5);return 0;
 }
 if(mode==6 || mode==7){
  c6502_native_exit_begin();assert(!nd_session_running && nd_teardown_active);
  assert(!nd_active);memset(framebuffer,0x69,sizeof(framebuffer));
  c6502_native_exit_checkpoint(NATIVE_EXIT_CLEANUP_WINDOW,0,123);
  for(unsigned i=0;i<sizeof(framebuffer);++i)assert(framebuffer[i]==0x69);
  if(mode==6)_Exit(99); /* Reset inside the actual host cleanup call. */
  c6502_native_exit_checkpoint(NATIVE_EXIT_CLEANUP_WINDOW,1,123);
  c6502_native_exit_complete();assert(!nd_teardown_active);
  unsigned writes=nd_writes;nd_reset();
  c6502_native_exit_begin();c6502_native_exit_checkpoint(NATIVE_EXIT_PERF,0,0);
  assert(nd_writes==0 && writes>0); /* Off launch never overwrites exit evidence. */
  return 0;
 }
 if(mode==5){
  nd_active=0;toggle_inside_wait=1;c6502_native_bridge_traced(r,2,0x2700080,0x201fe00);
  assert(nd_active && nd_writes==6 && !nd_current_regs);return 0;
 }
 r[10]=0xffff;nd_record(ND_ENTER,r,1,0x2700080,0x201fe00);
 assert(nd_events[(nd_event_count-1)&15][23]==0);
 assert(nd_events[(nd_event_count-1)&15][24]==0);
 /* Pausing survives return/another launch: no surprise overwrite. */
 keys[2]=0;native_key_snapshot(keys,250);keys[2]=4;native_key_snapshot(keys,251);
 nd_service(r,0,0,0);assert(!nd_active);
 unsigned writes=nd_writes;nd_finish();assert(nd_writes==writes);
 return 0;
}
"""
    )
    c, exe = tmp_path / "debug.c", tmp_path / "debug.exe"
    c.write_text(source, encoding="utf-8")
    subprocess.run(
        [
            cc,
            "-std=c99",
            "-O2",
            "-Wall",
            "-Werror",
            "-I",
            str(DATA / "runtime"),
            "-Wno-unused-variable",
            "-Wno-unused-function",
            str(c),
            "-o",
            str(exe),
        ],
        check=True,
    )
    return exe


def test_recorder_closed_before_abrupt_process_exit_and_restart_keeps_it(recorder, tmp_path):
    run = subprocess.run([str(recorder), "1"], cwd=tmp_path)
    assert run.returncode == 99
    paths = [tmp_path / f"GAMDBG{i}.LOG" for i in (0, 1)]
    snapshots = [read_snapshot(path) for path in paths]
    latest = latest_snapshot(snapshots)
    assert latest["metadata"]["status"] == "before_call"
    assert len(latest["events"]) == 16
    last = latest["events"][-1]
    assert last[1] == 0 and last[4] == 0x2700080 and last[5] == 0x201FE00
    assert last[24] == 0x44332211
    assert max(path.stat().st_size for path in paths) <= 8192
    before = [path.read_bytes() for path in paths]
    subprocess.run([str(recorder), "2"], cwd=tmp_path, check=True)
    assert before == [path.read_bytes() for path in paths]
    symbols = {
        "game_sha256": "test-hash",
        "bridge_names": {"1": "uns_div_long"},
        "symbols": [{"address": 0x2700040, "size": 128, "name": "game_fn"}],
    }
    description = describe(latest, symbols)
    assert description["pending_call"] and description["native_caller_symbol"] == "game_fn"
    assert not description["exact_fault_pc_available"]
    with pytest.raises(ValueError, match="指纹"):
        describe(latest, {"game_sha256": "wrong"})
    latest["metadata"]["build_id"] = "this-build"
    with pytest.raises(ValueError, match="构建不匹配"):
        describe(latest, symbols)
    latest["metadata"]["build_id"] = "unknown"
    (tmp_path / "symbols.json").write_text(json.dumps(symbols), encoding="utf-8")


def test_short_write_keeps_other_valid_slot_and_stops_trace(recorder, tmp_path):
    subprocess.run([str(recorder), "3"], cwd=tmp_path, check=True)
    # Snapshot 5 overwrote slot 1 only; complete after_call is still slot 0.
    with pytest.raises(ValueError):
        read_snapshot(tmp_path / "GAMDBG1.LOG")
    complete = read_snapshot(tmp_path / "GAMDBG0.LOG")
    assert complete["metadata"]["status"] == "after_call"


def test_pause_invalid_stack_and_flush_failure(recorder, tmp_path):
    subprocess.run([str(recorder), "0"], cwd=tmp_path, check=True)
    snapshots = [read_snapshot(tmp_path / f"GAMDBG{i}.LOG") for i in (0, 1)]
    assert latest_snapshot(snapshots)["metadata"]["status"] == "paused"
    subprocess.run([str(recorder), "4"], cwd=tmp_path, check=True)


def test_reserved_d_can_enable_tracing_inside_blocking_input_without_another_key(
    recorder, tmp_path
):
    subprocess.run([str(recorder), "5"], cwd=tmp_path, check=True)
    snapshots = [read_snapshot(tmp_path / f"GAMDBG{i}.LOG") for i in (0, 1)]
    assert latest_snapshot(snapshots)["metadata"]["status"] == "enabled"


def test_checksum_rejects_complete_but_modified_text(recorder, tmp_path):
    subprocess.run([str(recorder), "1"], cwd=tmp_path)
    path = tmp_path / "GAMDBG1.LOG"
    path.write_bytes(path.read_bytes().replace(b"before_call", b"after_call"))
    with pytest.raises(ValueError, match="校验失败"):
        read_snapshot(path)


def test_clock_wrap_selects_the_newer_session():
    a = {"metadata": {"session_tick": 0xFFFFFFF0, "snapshot_sequence": 900}}
    b = {"metadata": {"session_tick": 16, "snapshot_sequence": 1}}
    assert latest_snapshot([a, b]) is b
    assert latest_snapshot([b, a]) is b
    assert "c6502_runtime_uns_div_long" in SUPPORTED_BRIDGES


def test_trace_covers_host_cleanup_and_does_not_repaint_the_desktop(recorder, tmp_path):
    result = subprocess.run([str(recorder), "6"], cwd=tmp_path)
    assert result.returncode == 99
    latest = latest_snapshot([read_snapshot(tmp_path / f"GAMDBG{i}.LOG") for i in (0, 1)])
    description = describe(latest)
    assert description["phase"] == "host_exit" and description["pending_call"]
    assert description["exit_stage"] == "cleanup_app_window"
    assert description["exit_detail"] == "0000007B"
    assert description["last_bridge"] is None
    symbols = {"game_sha256": "test-hash", "bridge_names": {"10": "not_a_bridge"}}
    assert describe(latest, symbols)["last_bridge"] is None
    subprocess.run([str(recorder), "7"], cwd=tmp_path, check=True)
    latest = latest_snapshot([read_snapshot(tmp_path / f"GAMDBG{i}.LOG") for i in (0, 1)])
    description = describe(latest)
    assert description["exit_stage"] == "return_to_host"
    assert description["exit_step_returned"] and not description["pending_call"]


def test_real_s1c33_debug_bridge_keeps_regs_caller_and_byte_sp(tmp_path):
    clang, emulator = os.getenv("A9288_TEST_CLANG"), os.getenv("A9288_TEST_C33EMU")
    if not clang or not emulator:
        pytest.skip("optional S1C33 toolchain/9288T preview core are not configured")
    header, bridges = generate_bridges(["c6502_adapter_sysrand_direct"], tmp_path, crash_trace=True)
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    wrapper = (
        "void c6502_native_bridge_traced("
        + runtime.split("void c6502_native_bridge_traced(", 1)[1].split("\n}\n#endif", 1)[0]
        + "\n}\n"
    )
    source = (
        r"""
typedef unsigned char c6502_u8; typedef unsigned long c6502_u32;
#define C6502_CRASH_TRACE 1
#define C6502_GAME_SIZE 81559u
#define C6502_RAM_SIZE 32768u
#define C6502_HOST_WIDTH 240u
#define C6502_HOST_STRIDE 60u
static unsigned char framebuffer[9600],ram[32768];
#define C6502_FRAMEBUFFER framebuffer
static struct {unsigned long key_scans,key_scan_max_gap_ticks,key_edges,key_repeats,
 keys_consumed,key_queue_peak,key_queue_overflows;} c6502_perf;
static struct {c6502_u8 *ram; unsigned banks[16];} c6502_native_state;
volatile c6502_u32 c6502_bridge_regs[15],c6502_bridge_target;
c6502_u32 c6502_host_dp;
c6502_u32 trace_after[11], trace_expected_sp;
extern const unsigned char trace_probe_return[];
void run_guest_probe(void);
static c6502_u32 native_clock(void){return 1u;}
static unsigned get16(unsigned at){return ram[at]|((unsigned)ram[at+1]<<8);}
typedef int FS_FILE;
static FS_FILE *fs_fopen(const char *name,const char *mode){(void)name;(void)mode;return (FS_FILE*)0;}
static unsigned long fs_fwrite(const void *p,unsigned long size,unsigned long count,FS_FILE*f){
 (void)p;(void)size;(void)f;return count;}
static int fs_ferror(FS_FILE*f){(void)f;return 0;}
static int fs_update(FS_FILE*f){(void)f;return 0;}
static int fs_fclose(FS_FILE*f){(void)f;return 0;}
#include "c6502_native_bridge_ids.h"
#include "c6502_native_input.h"
#include "c6502_native_lifecycle.h"
#include "c6502_native_debug.h"
static void c6502_native_bridge(c6502_u32 *r,c6502_u32 id){
 if(id==C6502_BRIDGE_c6502_adapter_sysrand_direct)r[4]=99u;
}
"""
        + wrapper
        + r"""
unsigned long probe(void){
 c6502_native_state.ram=ram;nd_reset();nd_active=1;
 run_guest_probe();
 if(nd_errors || nd_event_count!=2)return 2;
 if(nd_events[0][4]!=(c6502_u32)trace_probe_return || nd_events[1][4]!=nd_events[0][4])return 3;
 if(nd_events[0][5]!=trace_expected_sp || nd_events[1][5]!=trace_expected_sp)return 4;
 if(nd_events[0][10]!=104 || nd_events[1][10]!=99)return 5;
 for(unsigned long i=4;i<15;++i){
  unsigned long expected=i==4?99u:i==10?0x2000u:i==14?(c6502_u32)ram:100u+i;
  if(trace_after[i-4]!=expected)return 6;
 }
 return 1;
}
"""
    )
    code = [
        "    .text",
        "    .globl _start",
        "_start:",
        *imm("ld.w", "r5", 0x02300000),
        "    ld.w %sp, %r5",
        "    call probe",
        "    halt",
        "    .globl run_guest_probe",
        "run_guest_probe:",
        "    pushn %r3",
    ]
    for register in range(15):
        if register == 14:
            # Expose RAM address through the state rather than requiring
            # a guessed host C local/frame layout.
            code += ["    ext ram@h", "    ext ram@m", "    ld.w %r14, ram@l"]
        else:
            code += imm("ld.w", f"r{register}", 0x2000 if register == 10 else 100 + register)
    code += [
        "    ld.w %r2, %sp",
        "    sub %r2, 4",
        "    ext trace_expected_sp@h",
        "    ext trace_expected_sp@m",
        "    ld.w %r3, trace_expected_sp@l",
        "    ld.w [%r3], %r2",
        "    call c6502_adapter_sysrand_direct",
        "    .globl trace_probe_return",
        "trace_probe_return:",
        "    ext trace_after@h",
        "    ext trace_after@m",
        "    ld.w %r3, trace_after@l",
    ]
    for register in range(4, 15):
        if register != 4:
            code += [f"    ext {(register - 4) * 4}"]
        code += [f"    ld.w [%r3], %r{register}"]
    code += [
        "    popn %r3",
        "    ret",
        "    .globl c6502_game_fn_00046",
        "c6502_game_fn_00046:",
        "    ret",
        "",
    ]
    c, assembly, start, elf = [
        tmp_path / name for name in ("probe.c", "probe.S", "start.S", "probe.elf")
    ]
    # ram is referenced by assembly, so make its symbol externally visible.
    c.write_text(
        source.replace(
            "static unsigned char framebuffer[9600],ram[32768];",
            "static unsigned char framebuffer[9600]; unsigned char ram[32768];",
        ),
        encoding="utf-8",
    )
    start.write_text("\n".join(code), encoding="utf-8")
    subprocess.run(
        [
            clang,
            "--target=s1c33-none-elf",
            "-Os",
            "-ffreestanding",
            "-fno-builtin",
            "-fno-jump-tables",
            "-fno-strict-aliasing",
            "-I",
            str(DATA / "runtime"),
            "-I",
            str(header.parent),
            "-S",
            str(c),
            "-o",
            str(assembly),
        ],
        check=True,
        capture_output=True,
    )
    fixed, _ = preserve_comparison_flags(assembly.read_text(encoding="utf-8"))
    assembly.write_text(fixed, encoding="utf-8")
    subprocess.run(
        [
            clang,
            "--target=s1c33-none-elf",
            "-nostdlib",
            "-Wl,-Ttext=0x02700000",
            str(start),
            str(assembly),
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
            "--steps",
            "100000",
            "--state-json",
            "--load-elf",
            str(elf),
            "--entry",
            "0x02700000",
            "--ram-size",
            "0x100000",
            "--sdram-size",
            "0x2000000",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    state = json.loads(result.stdout)
    assert state["halted"] and not state["faulted"] and not state["unknown_accesses"]
    assert int(state["r"][4], 16) == 1
    assert int(state["sp"], 16) == 0x02300000
    assert int(state["r"][15], 16) == 0
