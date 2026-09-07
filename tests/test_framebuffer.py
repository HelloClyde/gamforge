"""Real LCD stores must reach the 9288 surface without a present or timer."""

import shutil
import subprocess

import pytest

from a9288.compiler import backend, build
from a9288.paths import DATA


def test_compiled_lcd_stores_cannot_bypass_mirror(tmp_path):
    for address in (0x401, 0x413, 0x800, 0xFF3, 0x1000):
        assert not backend.direct_ram(address, write=True)
        assert "call c6502_direct_write8" in "\n".join(backend.store_memory(address, "r4"))
    assert backend.direct_ram(0x1800, write=True)
    # Inspect generated native guards, including the inclusive $1000 limit.
    build.generate_bridges(["c6502_direct_write8", "c6502_direct_read8"], tmp_path)
    source = (tmp_path / "c6502_native_bridges.S").read_text(encoding="utf-8")
    writes = source.split("c6502_direct_write8:\n", 1)[1].split("    call c6502_native_bridge", 1)[
        0
    ]
    assert "    cmp %r11, 4\n    jrult .Lbridge_not_lcd_" in writes
    assert "    ext 64\n    ld.w %r11, 0\n    cmp %r12, %r11\n    jrule .Lbridge_slow_" in writes
    assert writes.index(".Lbridge_not_lcd_") < writes.index("    ld.b [%r11], %r13")
    assert "    ld.w %r11, [%sp+0]\n    add %sp, 4\n    ret" in writes


def test_direct_framebuffer_matches_reference_for_writes_and_graphics(tmp_path):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")

    def part(start, end):
        return start + runtime.split(start, 1)[1].split(end, 1)[0]

    helpers = part("static c6502_u8 physical_read", "static void set_nz")
    helpers += part("static c6502_u16 lcd_address", "static c6502_u8 map_key")
    helpers += part("static c6502_u8 screen_bit", "/* The 9288 font renderer")
    helpers += part("static void native_text", "static void integer_to_ascii")
    helpers += part("static void native_refresh_if_due", "static c6502_u8 translate_key")
    perf = (
        "typedef struct C6502_Perf"
        + runtime.split("typedef struct C6502_Perf", 1)[1].split("static void bytes_set", 1)[0]
    )
    source = (
        r"""
#include <assert.h>
#include <string.h>
#include <stdio.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;typedef unsigned c6502_u32;
#define C6502_RAM_SIZE 32768u
#define C6502_GAME_PHYSICAL_BASE 0x20d000u
#define C6502_VIEW_Y 24u
#define C6502_GUEST_STRIDE 20u
#define C6502_GUEST_HEIGHT 96u
#define C6502_FRAME_STRIDE 80u
#define C6502_FRAME_HEIGHT 240u
#define C6502_FRAME_TICKS 64u
#define C6502_RESOURCE_SCRATCH_SIZE 1920u
static unsigned char ram[32768],game[12288],c6502_resource_scratch[1920];
static unsigned char host_frame[19200] __attribute__((aligned(4)));
static unsigned char expected[19200],before[19200];
#define C6502_FRAMEBUFFER host_frame
static struct {unsigned char *ram,*game;unsigned game_size;unsigned short banks[16];unsigned char bank_select;}
 c6502_native_state={ram,game,12288};
static unsigned char c6502_frame_valid,c6502_output_ready,c6502_previous_frame[1920];
static unsigned c6502_expand_2x[256],c6502_last_frame_tick,clock_value;
static void guest_write(unsigned short a,unsigned char v);
static void native_lcd_write(unsigned short a);
static void native_capture_keys(void){}
static unsigned char stack8(unsigned *r,unsigned n){return ram[(r[10]+n)&32767];}
static unsigned short stack16(unsigned *r,unsigned n){return stack8(r,n)|(stack8(r,n+1)<<8);}
/* Only font rasterisation is stubbed; the actual glyph blitter is tested. */
static const unsigned char* native_glyph(const unsigned char*g,unsigned char width){
 static unsigned char bits[32];for(unsigned i=0;i<32;++i)bits[i]=(g[0]+i*17)^g[1];return bits;
}
"""
        + perf
        + "\nstatic unsigned native_clock(void){return clock_value;}\n"
        + helpers
        + r"""
static void reference(void){
 memset(expected,255,sizeof(expected));
 for(unsigned y=0;y<96;++y)for(unsigned x=0;x<159;++x){
  unsigned bit=ram[lcd_address(x/8,y)]&(128>>(x%8));
  if(bit)for(unsigned yy=24+y*2;yy<26+y*2;++yy)for(unsigned xx=1+x*2;xx<3+x*2;++xx)
   expected[yy*80+xx/4]&=~(3<<(6-2*(xx%4)));
 }
 assert(!memcmp(host_frame,expected,sizeof(expected)));
}
/* Independent pixel/byte oracle, including observable overlapping reads. */
static void picture_oracle(unsigned x0,unsigned y0,unsigned x1,unsigned y1,unsigned src,unsigned flag){
 unsigned t,stride;
 if(x1>=160||y1>=96)return;
 if(x1<x0){t=x0;x0=x1;x1=t;}if(y1<y0){t=y0;y0=y1;y1=t;}
 stride=flag==1?(x1/8-x0/8+1):(x1-x0+8)/8;
 for(unsigned y=y0;y<=y1;++y){
  if(flag==1){for(unsigned x=x0/8;x<=x1/8;++x)guest_write(lcd_address(x,y),guest_read(src++));}
  else if(x0/8==x1/8){
   unsigned a=lcd_address(x0/8,y),mask=(unsigned char)((255u<<(8-(x0&7)))|(127u>>(x1&7)));
   guest_write(a,(guest_read(a)&mask)|(guest_read(src++)>>(x0&7)));
  }else for(unsigned x=x0;x<=x1;++x){
   unsigned v=guest_read((unsigned short)(src+(y-y0)*stride+(x-x0)/8));
   pixel(x,y,(v&(128>>((x-x0)&7)))!=0);
  }
 }
}
static void differential_pictures(void){
 static unsigned char initial[32768],oracle[32768];
 unsigned sources[]={0x1800,0x3000,0x3ff0,0x4000,0x4800,0x4ff8,0x7800,0x8ff8,0x9000,0x9ff8,0xb000,
                     0xfff8,0,0x00fe,0x0401,0x0800,0x0ff3,0x1000};
 unsigned seed=9288;
 for(unsigned i=0;i<sizeof(game);++i)game[i]=(i*43+17)&255;
 for(unsigned s=0;s<sizeof(sources)/sizeof(sources[0]);++s)for(unsigned n=0;n<80;++n){
  for(unsigned i=0;i<sizeof(ram);++i)ram[i]=(i*29+n*37+17)&255;
  /* Static banks include LCD aliases, contiguous ROM and noncontiguous windows. */
  for(unsigned i=0;i<16;++i)c6502_native_state.banks[i]=0;
  c6502_native_state.banks[4]=n%8;
  c6502_native_state.banks[5]=(n&1)?(n%7+1):2;
  c6502_native_state.banks[7]=7;
  c6502_native_state.banks[8]=0x20f;c6502_native_state.banks[9]=0x20d;
  c6502_native_state.banks[10]=(n&1)?0x20e:0x20f;c6502_native_state.banks[11]=0x20f;
  c6502_native_state.bank_select=0;
  /* DATA0 points into RAM and increments, testing side effects on the slow path. */
  ram[0x208]=0;ram[0x209]=0x18;ram[0x20a]=0;ram[0x207]=1;
  seed=seed*1664525u+1013904223u;unsigned x=seed%160;
  seed=seed*1664525u+1013904223u;unsigned y=seed%96;
  seed=seed*1664525u+1013904223u;unsigned x1=x+seed%(160-x);
  seed=seed*1664525u+1013904223u;unsigned y1=y+seed%(96-y);
  if(!n){x=0;y=0;x1=159;y1=95;}
  memcpy(initial,ram,sizeof(ram));c6502_native_present();
  picture_oracle(x,y,x1,y1,sources[s],n&1);memcpy(oracle,ram,sizeof(ram));
  memcpy(ram,initial,sizeof(ram));c6502_native_present();
  native_picture(x,y,x1,y1,sources[s],n&1);
  if(memcmp(ram,oracle,sizeof(ram))){printf("picture mismatch source=%04x case=%u\n",sources[s],n);assert(0);}
  reference();
 }
 /* Direct resolver must not treat cross-bank, wrapped or MMIO reads as flat RAM. */
 c6502_native_state.banks[9]=0x20d;c6502_native_state.banks[10]=0x20e;
 assert(picture_direct_source(0x9ff8,16)==game+4088);
 c6502_native_state.banks[10]=0x20f;assert(!picture_direct_source(0x9ff8,16));
 assert(!picture_direct_source(0xfff8,16)&&!picture_direct_source(0,16));
 assert(!picture_direct_source(0x0401,16)&&!picture_direct_source(0x1000,16));
 assert(picture_direct_source(0x3000,1920)==ram+0x3000);
 /* The actual Sanguo 159x96 source is $4800, bank 4 -> physical $4800. */
 c6502_native_state.banks[4]=4;
 assert(picture_source_disjoint(0x4800,1920));
 assert(picture_direct_source(0x4800,1920)==ram+0x4800);
 c6502_native_state.banks[5]=5;
 assert(picture_direct_source(0x4ff8,16)==ram+0x4ff8);
 c6502_native_state.banks[5]=2;
 assert(picture_source_disjoint(0x4ff8,16)&&!picture_direct_source(0x4ff8,16));
 c6502_native_state.banks[5]=1;
 assert(!picture_source_disjoint(0x4ff8,16)&&!picture_direct_source(0x4ff8,16));
 c6502_native_state.banks[4]=0;
 assert(!picture_source_disjoint(0x4800,1920)&&!picture_direct_source(0x4800,1920));
 assert(picture_source_disjoint(0x4004,16)&&picture_direct_source(0x4004,16)==ram+4);
 c6502_native_state.banks[4]=1;
 assert(!picture_source_disjoint(0x4000,1)&&!picture_direct_source(0x4000,1));
 assert(picture_source_disjoint(0x4001,16)&&picture_direct_source(0x4001,16)==ram+0x1001);
 c6502_native_state.banks[4]=7;c6502_native_state.banks[5]=8;
 assert(picture_source_disjoint(0x4ff8,16)&&!picture_direct_source(0x4ff8,16));
 assert(!picture_source_disjoint(0,0)&&!picture_direct_source(0x4800,0));
 /* Exact whole-RAM and framebuffer equality with the conservative path;
    quantifiable output work, not a claim of physical device speed. */
 for(unsigned i=0;i<32768;++i)ram[i]=(i*71+37)&255;
 c6502_native_state.banks[4]=4;memcpy(initial,ram,sizeof(ram));
 picture_oracle(0,0,158,95,0x4800,0);memcpy(oracle,ram,sizeof(ram));
 memcpy(ram,initial,sizeof(ram));c6502_native_present();
 unsigned stores=c6502_perf.mapped_lcd_bytes,bytes=c6502_perf.framebuffer_bytes;
 unsigned rows=c6502_perf.lcd_span_rows,ordered=c6502_perf.picture_ordered_calls;
 native_picture(0,0,158,95,0x4800,0);
 assert(!memcmp(ram,oracle,sizeof(ram)));reference();
 assert(c6502_perf.mapped_lcd_bytes-stores==1920&&c6502_perf.framebuffer_bytes-bytes==15360);
 assert(c6502_perf.lcd_span_rows-rows==96&&c6502_perf.picture_ordered_calls==ordered);
}
int main(void){
 unsigned r[15]={0};r[10]=0x1800;
 memset(host_frame,0x69,sizeof(host_frame));memcpy(before,host_frame,sizeof(before));
 guest_write(0x413,0xaa);assert(!memcmp(before,host_frame,sizeof(before))); /* before attach */
 c6502_native_present();reference();
 unsigned presents=c6502_perf.presents;
 /* Every address in the LCD envelope, including holes and folded row 65. */
 for(unsigned a=0x401;a<=0x1000;++a){guest_write(a,(a*29+71)&255);reference();}
 assert(c6502_perf.mapped_lcd_bytes==1920 && c6502_perf.presents==presents);
 /* Byte values, cross-word neighbour carry, hidden x=159 and reversed order. */
 unsigned xs[]={0,1,18,19},ys[]={0,64,65,66,95};
 for(unsigned v=0;v<256;++v)for(unsigned xi=0;xi<4;++xi)for(unsigned yi=0;yi<5;++yi){
  guest_write(lcd_address(xs[xi],ys[yi]),v);reference();
 }
 /* Banked aliases and DATA physical channels go through the same mirror. */
 for(unsigned y=0;y<96;++y){
  unsigned a=lcd_address(y%20,y);c6502_native_state.banks[4]=a>>12;
  guest_write(0x4000|(a&4095),y^0xa6);reference();
  ram[0x208]=a;ram[0x209]=a>>8;ram[0x20a]=0;ram[0x207]=1;
  guest_write(0,y^0x51);reference();assert((ram[0x208]|ram[0x209]<<8)==a+1);
 }
 /* Fused 16x16 tile: 32 LCD bytes, 2*8+2 host bytes/row (one edge repair). */
 memset(ram+0x3000,0x99,1920);
 unsigned stores=c6502_perf.mapped_lcd_bytes,bytes=c6502_perf.framebuffer_bytes;
 native_picture(16,8,31,23,0x3000,0);reference();
 assert(c6502_perf.mapped_lcd_bytes-stores==32);
 assert(c6502_perf.framebuffer_bytes-bytes==288 && c6502_perf.presents==presents);
 assert(c6502_perf.lcd_span_rows==16 && c6502_perf.picture_direct_bytes==32);
 /* Masked/unaligned pictures, reverse coordinates, both firmware flags. */
 for(unsigned flag=0;flag<2;++flag)for(unsigned y=0;y<96;y+=5){
  native_picture(1,y,8,y,0x3000,flag);reference();
  native_picture(159,y,152,y,0x3000,flag);reference();
 }
 /* Off-screen drawing changes no physical pixel; copying it to LCD does. */
 unsigned char args[]={8,31,23,0,0x30,0,0x28,0};memcpy(ram+0x1800,args,sizeof(args));r[4]=16;
 memcpy(before,host_frame,sizeof(before));picture_dummy(r);assert(!memcmp(before,host_frame,sizeof(before)));
 native_picture(0,0,158,95,0x2800,0);reference();
 /* Consecutive animation pages must show immediately at a frozen clock. */
 for(unsigned i=0;i<8;++i){
  memset(ram+0x3000,31*i,1920);bytes=c6502_perf.framebuffer_bytes;
  native_picture(0,0,158,95,0x3000,0);reference();
  assert(c6502_perf.framebuffer_bytes-bytes==15360); /* formerly 19008 */
 }
 for(unsigned op=0;op<3;++op){horizontal_span(3,154,65,op);reference();}
 line(10,10,37,63);reference();rectangle(0,0,158,95,0);reference();rectangle_clear(0,0,158,95);reference();
 unsigned char text[]={0xd6,0xd0,'1','2',0};native_text(7,64,text);reference();
 /* Save reads shadow RAM; restoring mirrors back to the real surface. */
 unsigned char save_args[]={0,158,95,0,0x30};memcpy(ram+0x1800,save_args,5);r[4]=0;
 save_restore_screen(r,0);memcpy(before,host_frame,sizeof(before));rectangle(0,0,158,95,1);reference();
 save_restore_screen(r,1);reference();assert(!memcmp(before,host_frame,sizeof(before)));
 assert(c6502_perf.presents==presents); /* no frame/timer flush for any drawing */
 /* Silent GUI/DMA corruption: repair compares physical bytes, not only shadow. */
 memset(host_frame+12,0,7);memset(host_frame+80*90+9,255,24);
 clock_value=64;native_refresh_if_due();reference();
 bytes=c6502_perf.framebuffer_bytes;clock_value=128;native_refresh_if_due();
 assert(c6502_perf.framebuffer_bytes==bytes); /* unchanged audit writes nothing */
 host_frame[19200-1]=0;c6502_native_invalidate_screen();native_refresh_if_due();reference();
 differential_pictures();
 puts("DIRECT-FB: all LCD addresses, values, aliases, primitives, animation and repair PASS");
 return 0;
}
"""
    )
    c = tmp_path / "mirror.c"
    exe = tmp_path / "mirror.exe"
    c.write_text(source, encoding="utf-8")
    subprocess.run([cc, "-O2", "-Wall", str(c), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=30)
