"""Model row-line settling and transient columns using the actual scanner."""

import shutil
import subprocess

import pytest

from a9288.paths import DATA


def test_row_settling_short_taps_chords_and_transient_action(tmp_path):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc unavailable")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    constants = (
        "#define C6502_IO_BASE"
        + runtime.split("#define C6502_IO_BASE", 1)[1].split("extern const", 1)[0]
    )
    capture = (
        "static void native_capture_keys(void)\n{"
        + runtime.split("static void native_capture_keys(void)\n{", 1)[1].split(
            "static c6502_u32 native_clock", 1
        )[0]
    )
    source = (
        r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned c6502_u32;
static struct {unsigned key_scans,key_scan_max_gap_ticks,key_edges,key_repeats,
 keys_consumed,key_queue_peak,key_queue_overflows;} c6502_perf;
static unsigned now,psr=16,lag,remaining,read_index,entries,noise;
static unsigned char matrix[8],rowreg=255,last_row=255,old_columns,pending_columns;
static unsigned char k5mode=0x43,portmode=0x12,k5data,portdata,factors;
static unsigned native_clock(void){return now;}
static unsigned read_psr(void){return psr;}
static void write_psr(unsigned v){psr=v;}
"""
        + constants
        + r"""
#include "c6502_native_input.h"
static unsigned char active(void){unsigned char bits=0;
 for(unsigned r=0;r<8;r++)if(!(rowreg&(1u<<r)))bits|=matrix[r];return bits;}
static volatile unsigned char* hardware_byte(unsigned a){
 switch(a){
 case C6502_CTM_DIVIDER_ADDRESS:{static unsigned char t;t=now;return &t;}
 case C6502_KEY_ROW_SELECT_ADDRESS:return &rowreg;
 case C6502_K5_FUNCTION_ADDRESS:return &k5mode;
 case C6502_PORT0_IOCTRL_ADDRESS:return &portmode;
 case C6502_KEY_IRQ_FACTOR_ADDRESS:return &factors;
 default:break;
 }
 assert(a==C6502_K5_DATA_ADDRESS||a==C6502_PORT0_DATA_ADDRESS);
 if(rowreg!=last_row){
  last_row=rowreg;pending_columns=active();remaining=lag;read_index=0;
  if(rowreg==0xfe)entries++;
 }
 unsigned char b;
 if(remaining){b=old_columns;if(!--remaining)old_columns=pending_columns;}
 else{old_columns=active();b=old_columns;}
 read_index++;
 /* noise 1: one bad P0 sample. noise 2: two consistently bad samples on
    the first selection, gone during the independent action recheck. */
 if(rowreg==0xfe && ((noise==1&&read_index==10)||
     (noise==2&&entries==1&&(read_index==10||read_index==12)))) b|=64;
 if(a==C6502_K5_DATA_ADDRESS){k5data=~b;return &k5data;}
 portdata=~b;return &portdata;
}
#include "c6502_native_matrix.h"
"""
        + capture
        + r"""
#include "c6502_native_key_checkpoint.h"
static void scan(void){native_capture_keys();
 assert(psr==16&&rowreg==255&&k5mode==0x43&&portmode==0x12);}
static void reset(unsigned delay){
 memset(matrix,0,8);memset(c6502_key_previous,0,8);memset(&c6502_perf,0,sizeof(c6502_perf));
 now=0;lag=delay;remaining=read_index=entries=noise=0;rowreg=last_row=255;
 old_columns=pending_columns=0;psr=16;k5mode=0x43;portmode=0x12;factors=0;
 c6502_key_initialized=c6502_key_head=c6502_key_count=0;c6502_key_repeat=255;
 c6502_matrix_unstable_rows=c6502_matrix_action_checks=c6502_matrix_action_rejected=0;
 native_key_diagnostics_reset();c6502_key_bridge_calls=0;
 c6502_key_checkpoint_checks=c6502_key_checkpoint_scans=0;
 c6502_input_active=1;scan();
}
static void seed_previous_right_row(void){
 /* A firmware ISR can leave row 7 selected before the private scan. */
 rowreg=last_row=0x7f;old_columns=pending_columns=64;remaining=0;
}
static void legacy_snapshot(unsigned char out[8]){
 for(unsigned r=0;r<8;r++){
  rowreg=(unsigned char)~(1u<<r);
  unsigned char k=*hardware_byte(C6502_K5_DATA_ADDRESS);
  unsigned char p=*hardware_byte(C6502_PORT0_DATA_ADDRESS);
  out[r]=((unsigned char)~k&15)|((unsigned char)~p&0x70);
 }
 rowreg=255;
}
int main(void){
 unsigned char old[8];reset(2);matrix[7]=64;seed_previous_right_row();
 legacy_snapshot(old);native_key_snapshot(old,1);
 assert(native_take_key()==0x2e); /* Old row7 -> row0 carryover reproduces Exit. */
 for(unsigned delay=0;delay<=8;delay++){
  reset(delay);
  for(unsigned tap=0;tap<200;tap++){
   matrix[7]=64;now++;seed_previous_right_row();native_capture_keys();
   assert(rowreg==0x7f&&psr==16&&k5mode==0x43&&portmode==0x12);rowreg=255;
   matrix[7]=0;now++;scan();
   assert(native_take_key()==0x39&&native_take_key()==255); /* captured short tap */
  }
  matrix[7]=64;now++;scan();assert(native_take_key()==0x39);
  for(unsigned t=0;t<2000;t++){now++;scan();unsigned char k=native_take_key();assert(k==255||k==0x39);}
  assert(c6502_perf.key_repeats>0);
  /* Real Right+Exit or Right+Enter is not globally masked. Both Exit aliases work. */
  for(unsigned row=0;row<6;row++)if(row==0||row==1||row==5){
   matrix[row]=64;now++;scan();assert(native_take_key()==(row==1?0x2f:0x2e));
   while(native_take_key()!=255){}
   matrix[row]=0;for(unsigned t=0;t<5;t++){now++;scan();while(native_take_key()!=255){}}
  }
 }
 reset(0);noise=1;matrix[7]=64;now++;scan();
 assert(native_take_key()==0x39&&native_take_key()==255&&c6502_matrix_unstable_rows);
 reset(0);noise=2;entries=0;matrix[7]=64;now++;scan();
 assert(native_take_key()==0x39&&native_take_key()==255);
 assert(c6502_matrix_action_checks==1&&c6502_matrix_action_rejected==1);
 assert(c6502_matrix_actions[0][2]==0&&c6502_matrix_actions[0][3]==64&&
        c6502_matrix_actions[0][4]==0&&c6502_matrix_actions[0][5]==64);
 reset(2);matrix[1]=64;c6502_key_initialized=0;now++;scan();assert(native_take_key()==255);
 matrix[1]=0;for(unsigned t=0;t<5;t++){now++;scan();}matrix[1]=64;now++;scan();
 assert(native_take_key()==0x2f); /* launch key still suppressed, next Enter valid */
 /* A tap entirely between two game polls is invisible without checkpoints. */
 reset(0);now=20;matrix[7]=64;now=30;matrix[7]=0;now=148;scan();
 assert(native_take_key()==255&&c6502_perf.key_scan_max_gap_ticks==148);
 assert(c6502_key_gap_bins[5]==1&&c6502_key_gaps[0][2]==148);
 /* Long native work repeatedly calling an existing C helper: capture both
    press AND release, do not consume until the game queries after tick 148. */
 reset(0);
 for(now=1;now<=148;now++){
  matrix[7]=(now>=20&&now<30)||(now>=60&&now<70)?64:0;
  for(unsigned c=0;c<32;c++)native_key_checkpoint(123);
  assert(c6502_perf.keys_consumed==0);
 }
 assert(c6502_key_checkpoint_checks==148&&c6502_key_checkpoint_scans==148);
 assert(c6502_key_bridge_calls==148*32&&c6502_perf.key_scan_max_gap_ticks==1);
 assert(native_take_key()==0x39&&native_take_key()==0x39&&native_take_key()==255);
 assert(c6502_key_code_counts[0x39][0]==2&&c6502_key_code_counts[0x39][1]==0&&
        c6502_key_code_counts[0x39][2]==2);
 assert(c6502_key_events[0][1]==20&&c6502_key_events[1][1]==60);
 /* Same-tick work is cheap-gated; no extra matrix scan or repeat. */
 now=148;for(unsigned c=0;c<320;c++)native_key_checkpoint(124);
 assert(c6502_key_checkpoint_checks==158&&c6502_key_checkpoint_scans==148);
 /* Input inactive means no hardware polling, even at a checkpoint. */
 c6502_input_active=0;now=149;
 for(unsigned c=0;c<32;c++)native_key_checkpoint(125);
 assert(c6502_key_checkpoint_scans==148&&c6502_perf.key_scans==149);
 puts("row settling: old Exit reproduced; short/held Right, chords and spikes passed");
 return 0;
}
"""
    )
    c, exe = tmp_path / "matrix.c", tmp_path / "matrix.exe"
    c.write_text(source, encoding="utf-8")
    subprocess.run(
        [cc, "-O2", "-std=c99", "-I", str(DATA / "runtime"), str(c), "-o", str(exe)], check=True
    )
    subprocess.run([str(exe)], check=True, timeout=15)


def test_memory_checkpoints_preserve_copy_fill_and_bounds(tmp_path):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc unavailable")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    cases = (
        "case C6502_BRIDGE_c6502_adapter_sysmemcpy_direct:"
        + runtime.split("case C6502_BRIDGE_c6502_adapter_sysmemcpy_direct:", 1)[1].split(
            "case C6502_BRIDGE_c6502_adapter_sysmeminit_direct:", 1
        )[0]
    )
    source = (
        r"""
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;
typedef unsigned c6502_u32;
enum {C6502_BRIDGE_c6502_adapter_sysmemcpy_direct=1,
 C6502_BRIDGE_c6502_adapter_fillmem_direct=2,C6502_BRIDGE_c6502_adapter_fillmem=3};
static unsigned char ram[65536],expected[65536];
static unsigned scans,now;
static unsigned char guest_read(unsigned short a){return ram[a];}
static void guest_write(unsigned short a,unsigned char v){ram[a]=v;now++;}
static void native_capture_keys(void){scans++;}
static unsigned native_clock(void){return now;}
static unsigned nt_enter(unsigned t){return t;}
static void nt_leave(unsigned phase,unsigned begin,unsigned end){}
#define NT_MEMORY 5
static unsigned short stack16(unsigned*r,unsigned i){return r[i/2];}
static unsigned char stack8(unsigned*r,unsigned i){return r[i/2];}
static void run(unsigned*r,unsigned id){unsigned left32,address,i,result;
switch(id){
"""
        + cases
        + r"""
}}
int main(void){unsigned r[16]={0};
 const unsigned starts[]={0,1,127,129,65500},counts[]={0,1,128,129,4096};
 for(unsigned op=1;op<=3;op++)for(unsigned s=0;s<5;s++)for(unsigned n=0;n<5;n++){
  for(unsigned j=0;j<65536;j++)ram[j]=expected[j]=(unsigned char)(j*37+13);
  unsigned a=starts[s],cnt=counts[n],boundary=0;scans=now=0;
  r[0]=a;r[1]=op==1?10000:cnt;r[2]=op==1?cnt:0xa7;
  for(unsigned j=0;j<cnt;j++){
   expected[(unsigned short)(a+j)]=op==1?expected[(unsigned short)(10000+j)]:0xa7;
   if(!((a+j+1)&127))boundary++;
  }
  run(r,op);assert(memcmp(ram,expected,65536)==0);
  assert(scans==boundary&&now==cnt);
 }
 return 0;}
"""
    )
    c, exe = tmp_path / "memory.c", tmp_path / "memory.exe"
    c.write_text(source, encoding="utf-8")
    subprocess.run([cc, "-O2", "-std=c99", str(c), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=15)
