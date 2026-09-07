"""Actual recorder/wrapper, deterministic host clock and native bridge ABI."""

from test_timing import PREFIX, compile_and_run

from a9288.compiler import build
from a9288.paths import DATA

PROFILE = (
    PREFIX
    + r"""
#define C6502_BRIDGE_COUNT 160u
#define C6502_BRIDGE_c6502_direct_read8 80u
#include "c6502_native_profile.h"
"""
)


def test_gap_other_conservation_sampling_and_wrap(tmp_path):
    compile_and_run(
        tmp_path,
        PROFILE
        + r"""
int main(void){
 np_begin(0); nt_begin(0);
 assert(np_select(2,1)); nt_charge(NT_OTHER,10);np_gap(10,10,2,100);
 unsigned s=nt_enter(10);nt_leave(NT_PICTURE,s,15);
 np_leave(2,100,10,10,15,10);
 nt_charge(NT_OTHER,25);np_gap(25,20,90,200);
 nt_charge(NT_OTHER,29);np_leave(90,200,25,20,29,24);
 nt_charge(NT_OTHER,40);np_gap(40,35,0,0);
 assert(c6502_profile.gap_other==31 && c6502_profile.bridge_other==4);
 assert(c6502_profile.bridge[2].ticks==5 && c6502_profile.bridge[2].other==0);
 assert(c6502_profile.gap_other+c6502_profile.bridge_other==c6502_timing.phase[0].ticks);
 unsigned samples=0;for(unsigned i=0;i<64000;++i)samples+=np_select(90,0);
 assert(samples>850 && samples<1150 && c6502_profile.bridge[90].calls==64000);
 np_begin(0xfffffff0u);np_gap(8u,24u,2,100);
 assert(c6502_profile.gap_other==24 && !c6502_profile.invalid);
 np_begin(100);np_gap(99,1,2,100);assert(c6502_profile.invalid==1);
 np_begin(0);np_key(1);np_key(350);assert(c6502_profile.key_events==1);
 assert(c6502_profile.keys[0].wall==349);
 return 0;
}
""",
    )


def test_bounded_edges_and_longest_spikes(tmp_path):
    compile_and_run(
        tmp_path,
        PROFILE
        + r"""
int main(void){
 np_begin(0);unsigned total=0,expected=0;
 for(unsigned i=1;i<2000;++i){
  total+=i; np_gap(total,total,1,100+i*8);
  np_leave(1,100+i*8,total,total,total,total);
  expected+=i;
 }
 unsigned sum=c6502_profile.edge_overflow_ticks;
 for(unsigned i=0;i<NP_EDGES;++i)sum+=c6502_profile.edges[i].other;
 assert(sum==expected && c6502_profile.edge_overflow_calls>0);
 for(unsigned i=0;i<NP_SPIKES;++i)assert(c6502_profile.spikes[i].wall>=1984);
 assert(sizeof(c6502_profile)<20000);
 return 0;
}
""",
    )


def test_wrapper_preserves_state_and_exclusive_phase_accounting(tmp_path):
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    wrapper = (
        "void c6502_native_bridge_profiled"
        + runtime.split("void c6502_native_bridge_profiled", 1)[1].split("#endif", 1)[0]
    )
    compile_and_run(
        tmp_path,
        PROFILE
        + r"""
static unsigned clock_now;
static unsigned native_clock(void){return clock_now;}
static void c6502_native_bridge(unsigned*r,unsigned id){
 r[4]+=id;r[8]=123;r[10]-=2;
 if(id==2){unsigned s=nt_enter(clock_now);clock_now+=5;nt_leave(NT_PICTURE,s,clock_now);}
 else clock_now+=4;
}
"""
        + wrapper
        + r"""
int main(void){
 unsigned r[15]={0};r[10]=512;
 nt_begin(0);np_begin(0);clock_now=10;
 c6502_native_bridge_profiled(r,2,0x02701234);
 assert(r[4]==2 && r[8]==123 && r[10]==510);
 clock_now=25;c6502_native_bridge_profiled(r,90,0x02702345);
 assert(r[4]==92 && r[10]==508);
 nt_charge(NT_OTHER,40);np_gap(40,c6502_timing.phase[0].ticks,0,0);
 assert(total()==40 && c6502_timing.phase[NT_PICTURE].ticks==5);
 assert(c6502_profile.bridge_other==4 && c6502_profile.gap_other==31);
 assert(c6502_profile.bridge[90].samples==1 && c6502_profile.clock_reads==4);
 return 0;
}
""",
    )


def test_diagnostic_bridge_captures_return_pc_after_saving_r8(tmp_path):
    symbols = ["c6502_direct_read8", "c6502_adapter_sysgetkey"]
    _, assembly = build.generate_bridges(symbols, tmp_path, profile_other=True)
    text = assembly.read_text()
    assert text.count("ld.w %r8, [%sp+4]") == 2
    assert text.count("call c6502_native_bridge_profiled") == 2
    for body in text.split("    sub %sp, 4")[1:]:
        if "ld.w %r8, [%sp+4]" in body:
            assert body.index("ld.w [%r3], %r8") < body.index("ld.w %r8, [%sp+4]")
    assert text.index(".Lbridge_fast_") < text.index("call c6502_native_bridge_profiled")
    _, assembly = build.generate_bridges(symbols, tmp_path)
    text = assembly.read_text()
    assert "native_bridge_profiled" not in text and "[%sp+4]" not in text


def test_profile_log_serializes_real_rows_and_conserves_other(tmp_path):
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    serializers = (
        "static void native_log_value"
        + runtime.split("static void native_log_value", 1)[1].split(
            '#include "c6502_native_log.h"', 1
        )[0]
    )
    profile_log = (
        "static void native_log_profile"
        + runtime.split("static void native_log_profile", 1)[1].split("#endif", 1)[0]
    )
    result = compile_and_run(
        tmp_path,
        PROFILE
        + r"""
typedef FILE FS_FILE;
#define fs_fwrite fwrite
static struct {unsigned elapsed;} c6502_perf;
static const char *c6502_profile_names[160]={[2]="test_picture"};
"""
        + serializers
        + profile_log
        + r"""
int main(void){
 nt_begin(0);np_begin(0);np_select(2,1);
 nt_charge(NT_OTHER,20);np_gap(20,20,2,0x02701234);
 unsigned s=nt_enter(20);nt_leave(NT_PICTURE,s,25);
 np_leave(2,0x02701234,20,20,25,20);
 nt_charge(NT_OTHER,90);np_gap(90,85,0,0);
 np_key(1);np_key(90);c6502_perf.elapsed=90;
 native_log_timing(stdout);native_log_profile(stdout);return 0;
}
""",
    )
    assert "profile_other_sum=85\n" in result
    assert "profile_other_match=1\n" in result
    assert "phase_elapsed_match=1\n" in result
    assert "profile_bridge,2,1,1,5,0,5\n" in result
    assert "profile_name_id,2\nprofile_name=test_picture\n" in result
    assert "\x00" not in result
    for line in result.splitlines():
        if line.startswith(("profile_edge,", "profile_spike,", "profile_keygap,")):
            assert len(line.split(",")) == 8
