"""Run the actual bounded timing recorder and log serializer on the host."""

import shutil
import subprocess

import pytest

from a9288.paths import DATA


def compile_and_run(tmp_path, source):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    c, exe = tmp_path / "timing.c", tmp_path / "timing.exe"
    c.write_text(source, encoding="utf-8")
    subprocess.run(
        [cc, "-std=c99", "-O2", "-Wall", "-I", str(DATA / "runtime"), str(c), "-o", str(exe)],
        check=True,
    )
    return subprocess.run([str(exe)], check=True, capture_output=True, text=True, timeout=10).stdout


PREFIX = r"""
#include <assert.h>
#include <stdio.h>
typedef unsigned char c6502_u8;typedef unsigned c6502_u32;
#include "c6502_native_timing.h"
static unsigned total(void){unsigned n=0;for(unsigned i=0;i<NT_PHASES;++i)n+=c6502_timing.phase[i].ticks;return n;}
"""


def test_exclusive_attribution_wrap_histogram_and_windows(tmp_path):
    compile_and_run(
        tmp_path,
        PREFIX
        + r"""
int main(void){
 nt_begin(100);unsigned s=nt_enter(110);nt_leave(NT_PICTURE,s,120);
 s=nt_enter(123);nt_leave(NT_GETMSG,s,140);nt_charge(NT_OTHER,150);
 assert(total()==50 && c6502_timing.phase[NT_OTHER].ticks==23);
 assert(c6502_timing.phase[NT_PICTURE].ticks==10);
 assert(c6502_timing.phase[NT_GETMSG].ticks==17);
 assert(c6502_timing.phase[NT_GETMSG].bins[5]==1);
 s=nt_enter(150);nt_leave(NT_GETKEY,s,150);
 assert(c6502_timing.phase[NT_GETKEY].calls==1 && c6502_timing.phase[NT_GETKEY].bins[0]==1);
 nt_begin(0xfffffff0u);s=nt_enter(0xfffffff8u);nt_leave(NT_PICTURE,s,8u);
 assert(total()==24 && !c6502_timing.invalid_deltas);
 nt_begin(0);s=nt_enter(3);nt_leave(NT_GETMSG,s,NT_WINDOW_TICKS*2+9);
 assert(total()==NT_WINDOW_TICKS*2+9 && c6502_timing.window_count==2);
 assert(c6502_timing.windows[0].phases[NT_OTHER]==3);
 assert(c6502_timing.windows[0].phases[NT_GETMSG]==NT_WINDOW_TICKS-3);
 assert(c6502_timing.windows[1].phases[NT_GETMSG]==NT_WINDOW_TICKS);
 assert(c6502_timing.current.start==NT_WINDOW_TICKS*2 && c6502_timing.current.elapsed==9);
 nt_begin(100);nt_charge(NT_OTHER,99);assert(c6502_timing.invalid_deltas==1 && !total());
 nt_begin(0);nt_charge(NT_OTHER,NT_WINDOW_TICKS*70);
 assert(c6502_timing.window_count==NT_WINDOWS);
 unsigned first=(c6502_timing.window_head+NT_WINDOWS-c6502_timing.window_count)%NT_WINDOWS;
 assert(c6502_timing.windows[first].start==6*NT_WINDOW_TICKS);
 return 0;
}
""",
    )


def test_interval_records_first_event_zero_gap_and_bounded_history(tmp_path):
    compile_and_run(
        tmp_path,
        PREFIX
        + r"""
int main(void){
 nt_begin(100);nt_charge(NT_OTHER,120);nt_frame(1,120,3,166,1,2,1,1);
 assert(!c6502_timing.first[0].gap_valid && c6502_timing.frame[0].intervals==0);
 nt_frame(1,120,0,166,1,2,1,1);
 assert(c6502_timing.first[1].gap_valid && c6502_timing.first[1].gap==0);
 assert(c6502_timing.frame[0].bins[0]==1);
 nt_charge(NT_OTHER,128);nt_frame(2,128,0,166,10,4,2,2);
 nt_charge(NT_OTHER,130);nt_frame(1,130,4,166,1,5,3,2);
 assert(c6502_timing.first[3].gap==10 && c6502_timing.first[3].phases[NT_OTHER]==10);
 assert(c6502_timing.first[3].timer_steps==3 && c6502_timing.first[3].timer_coalesced==1);
 assert(c6502_timing.frame[1].events==1 && c6502_timing.frame[1].intervals==0);
 for(unsigned i=0;i<300;++i){nt_charge(NT_OTHER,131+i);nt_frame(1,131+i,1,166,1,6+i,4+i,2);}
 assert(c6502_timing.sample_count==304 && c6502_timing.recent_count==NT_RECENT);
 unsigned first=(c6502_timing.recent_head+NT_RECENT-c6502_timing.recent_count)%NT_RECENT;
 assert(c6502_timing.first[0].seq==1);
 for(unsigned i=0;i<NT_RECENT;++i)assert(c6502_timing.recent[(first+i)%NT_RECENT].seq==305-NT_RECENT+i);
 nt_begin(0xfffffff0);nt_frame(1,0xfffffff8,1,166,1,0,0,0);nt_charge(NT_OTHER,8);nt_frame(1,8,1,166,1,0,0,0);
 assert(c6502_timing.first[1].gap==16 && c6502_timing.first[1].gap_valid);
 return 0;
}
""",
    )


def test_large_forward_gap_keeps_exact_tail_with_bounded_work(tmp_path):
    compile_and_run(
        tmp_path,
        PREFIX
        + r"""
int main(void){
 /* Roughly 97 days of wrapping CTM ticks must cost <= 65 window writes,
    not 838860 writes. Start with a mixed/partial window and wrapped ring. */
 for(unsigned offset=0;offset<NT_WINDOW_TICKS;offset+=79){
  nt_begin(0);nt_charge(NT_OTHER,70*NT_WINDOW_TICKS+offset);
  c6502_timing.current.full=3;c6502_timing.current.batches=7;
  unsigned start=70*NT_WINDOW_TICKS+offset,span=0x7fffffffu;
  nt_charge(NT_PICTURE,start+span);
  assert(c6502_timing.window_count==NT_WINDOWS);
  assert(c6502_timing.window_fast_forwards>800000);
  assert(total()==start+span);
  unsigned end=start+span,completed=end/NT_WINDOW_TICKS;
  unsigned first=(c6502_timing.window_head+NT_WINDOWS-c6502_timing.window_count)%NT_WINDOWS;
  for(unsigned i=0;i<NT_WINDOWS;++i){
   NativeTimingWindow*w=&c6502_timing.windows[(first+i)%NT_WINDOWS];
   assert(w->start==(completed-NT_WINDOWS+i)*NT_WINDOW_TICKS);
   assert(w->elapsed==NT_WINDOW_TICKS && w->phases[NT_PICTURE]==NT_WINDOW_TICKS);
   assert(!w->full && !w->batches);
   for(unsigned j=0;j<NT_PHASES;++j)if(j!=NT_PICTURE)assert(!w->phases[j]);
  }
  assert(c6502_timing.current.start==completed*NT_WINDOW_TICKS);
  assert(c6502_timing.current.elapsed==end%NT_WINDOW_TICKS);
  assert(c6502_timing.current.phases[NT_PICTURE]==end%NT_WINDOW_TICKS);
 }
 return 0;
}
""",
    )


def test_log_schema_chronological_samples_and_tick_conservation(tmp_path):
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    log = (
        "static void native_log_value"
        + runtime.split("static void native_log_value", 1)[1].split(
            '#include "c6502_native_log.h"', 1
        )[0]
    )
    text = compile_and_run(
        tmp_path,
        PREFIX
        + "typedef FILE FS_FILE;\n#define fs_fwrite fwrite\n"
        + "static struct {unsigned elapsed;} c6502_perf;\n"
        + log
        + r"""
int main(void){
 nt_begin(0);
 for(unsigned i=0;i<300;++i){unsigned s=nt_enter(i*16);nt_leave(NT_PICTURE,s,i*16+4);nt_frame(1,i*16+4,4,166,1,i*2,i,i);}
 nt_charge(NT_OTHER,4800);c6502_perf.elapsed=4800;native_log_timing(stdout);
 unsigned big[24];for(unsigned i=0;i<24;++i)big[i]=0xffffffffu;
 native_log_csv(stdout,"max_values",big,24);
 return 0;
}
""",
    )
    lines = text.splitlines()
    assert "phase_elapsed_match=1" in lines
    assert "phase_ticks_sum=4800" in lines
    assert "timing_samples_omitted=172" in lines
    samples = [list(map(int, line.split(",")[1:])) for line in lines if line.startswith("sample,")]
    assert all(len(row) == 20 for row in samples)
    assert [row[0] for row in samples] == list(range(1, 33)) + list(range(205, 301))
    windows = [list(map(int, line.split(",")[1:])) for line in lines if line.startswith("window,")]
    assert sum(row[1] for row in windows) == 4800
    assert all(sum(row[2:11]) == row[1] for row in windows)
    assert all(sum(row[8:17]) == row[4] for row in samples if row[3])
    assert "max_values," + ",".join(["4294967295"] * 24) in lines


def test_instrumentation_does_not_change_timer_or_framebuffer_policy():
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    assert 'fs_fopen("a:\\\\NATIVE.TMP", "wb")' in runtime
    assert "if (log_ok) (void)native_log_commit();" in runtime
    assert "ROM has one pending bit, not a queue" in runtime
    assert "native_timing_frame(1u, i, i - result)" in runtime
    # No per-pixel timestamps or file output were added to the LCD mapper.
    lcd = runtime.split("static void native_lcd_write(c6502_u16 address)\n{", 1)[1].split(
        "#include", 1
    )[0]
    assert "nt_frame" not in lcd and "native_clock()" not in lcd and "fs_fwrite" not in lcd
