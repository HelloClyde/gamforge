"""Compile the real input collectors with per-EXE physical-key overrides."""

import pytest
from test_9288t_input import input_source
from test_exit import run_c


def overrides(entries):
    values = ",".join(f"{{{source}u,{target}u}}" for source, target in entries)
    return f"#define C6502_KEYMAP_COUNT {len(entries)}\n#define C6502_KEYMAP_ENTRIES {{{values}}}\n"


def matrix_source(entries, target=""):
    return (
        overrides(entries)
        + (f"#define {target} 1\n" if target else "")
        + r"""
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned c6502_u32;
static struct {unsigned key_scans,key_scan_max_gap_ticks,key_edges,key_repeats,
 keys_consumed,key_queue_peak,key_queue_overflows;} c6502_perf;
#include "c6502_native_input.h"
static unsigned char rows[8];
static void scan(unsigned tick){native_key_snapshot(rows,tick);}
static void reset(void){memset(rows,0,8);memset(c6502_key_previous,0,8);
 memset(&c6502_perf,0,sizeof(c6502_perf));
 c6502_key_head=c6502_key_count=c6502_key_initialized=0;c6502_key_repeat=255;
 scan(0);}
static void press(unsigned source,unsigned tick){rows[source/8]|=1u<<(source%8);scan(tick);}
static void release(unsigned source,unsigned tick){rows[source/8]&=~(1u<<(source%8));scan(tick);}
"""
    )


def test_t_custom_functions_swap_disable_and_preserve_physical_edges(tmp_path):
    run_c(
        tmp_path,
        overrides([(59, 0x29), (116, 0x2B), (117, 0xFF), (118, 0x2D), (87, 0x2A)])
        + input_source()
        + r"""
int main(void){reset();unsigned source[]={59,116,118,87};
 unsigned code[]={0x29,0x2b,0x2d,0x2a};
 for(unsigned i=0;i<4;++i){unsigned kind=source[i]==87?MSG_HELP:MSG_HOTKEY;
  c6502_native_t_key_message(kind,source[i],0);
  c6502_native_t_key_message(MSG_SYSKEYDOWN,source[i],0);
  c6502_native_t_key_message(MSG_DT_KEYDOWN,source[i],0);
  assert(native_take_key()==code[i] && native_take_key()==255);
  now+=256;native_t_pump(now);assert(native_take_key()==255);
  c6502_native_t_key_message(MSG_KEYUP,source[i],0);
  tap(source[i],code[i]);
 }
 assert(map_key(117)==255);
 c6502_native_t_key_message(MSG_HOTKEY,117,0);
 c6502_native_t_key_message(MSG_KEYUP,117,0);assert(native_take_key()==255);
 tap(28,0x2f);tap(1,0x2e);tap(106,0x39);tap(30,0x18);
 assert(!c6502_native_t_key_message(MSG_KEYDOWN,88,0));
 assert(native_take_key()==255 && !c6502_perf.key_repeats);return 0;}
""",
    )


def test_t_remapped_guest_shift_does_not_latch_host_modifier(tmp_path):
    run_c(
        tmp_path,
        overrides([(59, 0x28), (116, 0x39)])
        + input_source()
        + r"""
int main(void){reset();
 c6502_native_t_key_message(MSG_HOTKEY,59,0);
 c6502_native_t_key_message(MSG_KEYDOWN,59,0);
 assert(native_take_key()==0x28 && native_take_key()==255 && !c6502_t_gui_shift);
 c6502_native_t_key_message(MSG_KEYUP,59,0);tap(59,0x28);
 assert(!c6502_t_gui_shift && !c6502_t_gui_shift_edges);
 tap(42,0x28);assert(c6502_t_gui_shift_edges==1 && !c6502_t_gui_shift);
 c6502_native_t_key_message(MSG_HOTKEY,116,0);assert(native_take_key()==0x39);
 now=40;native_t_pump(now);now=80;native_t_pump(now);
 assert(native_take_key()==0x39 && native_take_key()==255);
 /* Releasing one physical alias must not cancel another held source. */
 c6502_native_t_key_message(MSG_KEYDOWN,106,0);assert(native_take_key()==0x39);
 c6502_native_t_key_message(MSG_KEYUP,116,0);assert(c6502_key_repeat==0x39);
 c6502_native_t_key_message(MSG_KEYUP,106,0);assert(c6502_key_repeat==255);
 assert(native_take_key()==255);return 0;}
""",
    )


def test_9288_custom_matrix_start_functions_and_disabled_key(tmp_path):
    run_c(
        tmp_path,
        matrix_source([(5, 0x2B), (37, 0x2A), (45, 0x29), (53, 0xFF), (21, 0x2C)])
        + r"""
int main(void){reset();unsigned source[]={5,37,45,21},code[]={0x2b,0x2a,0x29,0x2c};
 for(unsigned i=0;i<4;++i){press(source[i],i*8+1);scan(i*8+2);
  release(source[i],i*8+3);assert(native_take_key()==code[i] && native_take_key()==255);}
 press(53,40);release(53,41);assert(native_take_key()==255);
 press(2,42);release(2,43);assert(native_take_key()==0x18);
 press(22,44);release(22,45);assert(native_take_key()==0x3a);
 press(6,46);press(14,47);assert(native_take_key()==0x2e && native_take_key()==0x2f);
 assert(native_take_key()==255);return 0;}
""",
    )


def test_9288_custom_actions_keep_launch_and_release_barriers(tmp_path):
    run_c(
        tmp_path,
        matrix_source([(37, 0x2F), (45, 0x2F), (21, 0x2E)])
        + r"""
int main(void){reset();c6502_key_initialized=0;press(37,1);scan(100);
 assert(native_take_key()==255);release(37,101);scan(105);press(37,106);
 assert(native_take_key()==0x2f && native_take_key()==255);
 press(45,107);release(37,108);assert(native_take_key()==255);
 release(45,109);press(45,111);assert(native_take_key()==255); /* bounce */
 release(45,112);scan(116);press(45,117);assert(native_take_key()==0x2f);
 press(21,118);scan(1000);assert(native_take_key()==0x2e && native_take_key()==255);
 assert(c6502_perf.key_edges==3 && !c6502_perf.key_repeats);return 0;}
""",
    )


def test_9288_repeat_tracks_physical_source_when_targets_alias(tmp_path):
    run_c(
        tmp_path,
        matrix_source([(37, 0x39), (45, 0x39)])
        + r"""
int main(void){reset();press(37,1);assert(native_take_key()==0x39);
 scan(40);scan(79);press(45,80);assert(native_take_key()==0x39);
 release(37,81);scan(120);scan(159);assert(native_take_key()==255);
 scan(160);assert(native_take_key()==0x39);release(45,161);
 scan(200);assert(native_take_key()==255);return 0;}
""",
    )


def test_9288_trace_toggle_stays_reserved_even_when_mapped_to_action(tmp_path):
    run_c(
        tmp_path,
        "#define C6502_CRASH_TRACE 1\n"
        + matrix_source([(18, 0x2F)])
        + r"""
static unsigned snapshots;
static void nd_key_snapshot(const unsigned char current[8]){++snapshots;}
int main(void){reset();press(18,1);release(18,2);
 assert(snapshots==3 && native_take_key()==255 && !c6502_perf.key_edges);
 press(14,3);assert(native_take_key()==0x2f);return 0;}
""",
    )


@pytest.mark.parametrize("target", ["C6502_TARGET_9288S", "C6502_TARGET_9288T"])
def test_non_9288_matrix_consumers_ignore_physical_9288_overrides(tmp_path, target):
    # S/TSW600 share C6502_TARGET_9288S. T's obsolete matrix helper is not
    # its input collector; GUI scan overrides must never affect that table.
    run_c(
        tmp_path,
        matrix_source([(37, 0x2B), (45, 0xFF), (53, 0x29)], target)
        + r"""
int main(void){reset();press(37,1);release(37,2);assert(native_take_key()==0x29);
 press(45,3);release(45,4);assert(native_take_key()==0x2d);
 press(53,5);release(53,6);assert(native_take_key()==0x36);
 assert(native_take_key()==255);return 0;}
""",
    )
