"""High-resolution save metadata must never alter guest save-buffer semantics."""

import shutil
import subprocess

import pytest

from a9288.paths import DATA


@pytest.fixture(scope="module")
def text_saves_binary(tmp_path_factory):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    directory = tmp_path_factory.mktemp("text-saves")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    memory = (
        "static c6502_u8 physical_read"
        + runtime.split("static c6502_u8 physical_read", 1)[1].split("static void set_nz", 1)[0]
    )
    source = (
        r"""
#include <assert.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned c6502_u32;
#define C6502_RAM_SIZE 32768u
#define C6502_GAME_PHYSICAL_BASE 0x20d000u
#define C6502_VIEW_Y 8u
#define C6502_FRAME_STRIDE 60u
static unsigned char c6502_t_frame_shadow[9600],host_frame[9600],ram[32768],game[4096];
#define C6502_FRAMEBUFFER host_frame
static struct {unsigned char *ram,*game;unsigned game_size;unsigned short banks[16];unsigned char bank_select;}
 c6502_native_state={ram,game,4096};
static void native_lcd_write(unsigned short address){(void)address;}
static unsigned attempts,allocations,frees,fail_at;
static void *test_malloc(size_t n){
 ++attempts;if(fail_at&&attempts==fail_at)return NULL;
 void *p=malloc(n);if(p)++allocations;return p;
}
static void test_free(void *p){if(p)++frees;free(p);}
#define malloc test_malloc
#define free test_free
#include "c6502_native_text_layer.h"
"""
        + memory
        + r"""
#include "c6502_native_text_saves.h"
#undef malloc
#undef free
static void initialise(void){
 native_text_layer_reset();
 for(unsigned i=0;i<32768;++i)ram[i]=(i*29+71)&255;
 for(unsigned i=0;i<16;++i)c6502_native_state.banks[i]=i;
 unsigned char glyph[72];for(unsigned i=0;i<72;++i)glyph[i]=(i*53+7)&255;
 native_text_layer_put(8,8,16,glyph,3);
 memset(c6502_t_frame_shadow,255,sizeof(c6502_t_frame_shadow));
 for(unsigned y=0;y<144;++y)native_text_layer_apply(0,19,y,1);
}
static const NativeTextSnapshot *saved(unsigned buffer){
 return native_text_saved((unsigned short)buffer,1,2,8,23);
}
static void check_count(void){
 unsigned count=0;for(unsigned i=0;i<4;++i){
  assert((native_text_saves[i].layer!=NULL)==(native_text_saves[i].bytes!=NULL));
  count+=native_text_saves[i].layer!=NULL;
 }
 assert(native_text_save_count==count);
}
static void record(unsigned buffer){native_text_save_record((unsigned short)buffer,1,2,8,23);check_count();}
static void finish(void){native_text_saves_reset();check_count();assert(!native_text_save_count);assert(allocations==frees);}
static void test_restore(void){
 unsigned char before[9600];initialise();memcpy(before,host_frame,sizeof(before));record(0x1800);
 const NativeTextSnapshot *s=saved(0x1800);assert(s);
 for(unsigned y=8;y<24;++y){native_text_layer_clear(1,y,255);native_text_layer_clear(2,y,255);}
 native_text_layer_restore(s);memset(c6502_t_frame_shadow,255,sizeof(c6502_t_frame_shadow));
 for(unsigned y=0;y<144;++y)native_text_layer_apply(0,19,y,1);
 assert(!memcmp(host_frame,before,sizeof(before)));finish();
}
static void test_tamper(void){
 initialise();record(0x1800);assert(saved(0x1800));
 for(unsigned i=0;i<32;++i){ram[0x1800+i]^=1;assert(!saved(0x1800));ram[0x1800+i]^=1;}
 assert(saved(0x1800));assert(!native_text_saved(0x1800,1,3,8,23));
 assert(!native_text_saved(0x1800,1,2,9,23));finish();
}
static void test_bank_identity(void){
 initialise();c6502_native_state.banks[5]=2;record(0x5000);assert(saved(0x5000));
 memcpy(ram+0x3000,ram+0x2000,32);c6502_native_state.banks[5]=3;assert(!saved(0x5000));
 c6502_native_state.banks[5]=2;assert(saved(0x5000));finish();
}
static void test_reuse_and_eviction(void){
 initialise();record(0x1800);assert(saved(0x1800));ram[0x1800]^=255;record(0x1800);assert(saved(0x1800));
 for(unsigned i=0;i<5;++i)record(0x1800+i*64);
 assert(!saved(0x1800));for(unsigned i=1;i<5;++i)assert(saved(0x1800+i*64));finish();
}
static void test_failed_allocations(void){
 initialise();fail_at=attempts+1;record(0x1800);assert(!saved(0x1800));
 fail_at=attempts+2;record(0x1800);assert(!saved(0x1800));
 fail_at=0;record(0x1800);assert(saved(0x1800));
 fail_at=attempts+2;record(0x1800);assert(!saved(0x1800));finish();
}
static void test_data_port_is_not_read_twice(void){
 initialise();ram[0x207]=15;
 for(unsigned i=0;i<4;++i){ram[0x208+i*3]=0;ram[0x209+i*3]=0x18;ram[0x20a+i*3]=0;}
 unsigned char before[32768];memcpy(before,ram,sizeof(ram));
 record(0);assert(!saved(0));assert(!memcmp(before,ram,sizeof(ram)));finish();
}
static void test_aliases_and_wrap_are_not_retained(void){
 initialise();
 /* A destination touching the LCD can overwrite the picture being saved. */
 record(0x800);assert(!saved(0x800));
 c6502_native_state.banks[5]=0;record(0x5800);assert(!saved(0x5800));
 /* Wrapping into DATA ports must not add a second side-effecting read. */
 record(0xfff0);assert(!saved(0xfff0));
 /* Page-3 writes are discarded by guest_write, not ordinary save storage. */
 record(0x300);assert(!saved(0x300));
 /* Special direct RAM writes mutate the value; ROM is not save storage. */
 record(0x210);assert(!saved(0x210));record(0x2020);assert(!saved(0x2020));
 c6502_native_state.banks[5]=0x20d;record(0x5000);assert(!saved(0x5000));
 /* Check the entire span, not just its first safe byte. */
 c6502_native_state.banks[4]=0;record(0x43f0);assert(!saved(0x43f0));
 c6502_native_state.banks[4]=1;c6502_native_state.banks[5]=2;
 record(0x4ff0);assert(saved(0x4ff0));
 c6502_native_state.banks[5]=0x20d;assert(!saved(0x4ff0));
 finish();
}
static void test_empty_layer_skips_metadata_and_reuse_forgets(void){
 initialise();record(0x1800);record(0x1900);assert(native_text_save_count==2);
 for(unsigned y=8;y<24;++y){native_text_layer_clear(1,y,255);native_text_layer_clear(2,y,255);}
 assert(!native_text_active_rows);unsigned before=attempts;
 record(0x1800);assert(!saved(0x1800));assert(native_text_save_count==1);
 assert(saved(0x1900)); /* An unrelated older dialog save remains usable. */
 record(0x1a00);assert(!saved(0x1a00));assert(native_text_save_count==1&&attempts==before);
 record(0x1900);assert(!native_text_save_count&&attempts==before);
 /* No active snapshots: ordinary flag-1 pictures take the zero-record path. */
 assert(!native_text_saved(0,0,19,0,95));finish();
}
int main(int argc,char **argv){
 assert(argc==2);switch(atoi(argv[1])){
 case 0:test_restore();break;case 1:test_tamper();break;case 2:test_bank_identity();break;
 case 3:test_reuse_and_eviction();break;case 4:test_failed_allocations();break;
 case 5:test_data_port_is_not_read_twice();break;case 6:test_aliases_and_wrap_are_not_retained();break;
 case 7:test_empty_layer_skips_metadata_and_reuse_forgets();break;
 default:abort();}return 0;
}
"""
    )
    c = directory / "text_saves.c"
    binary = directory / "text_saves.exe"
    c.write_text(source, encoding="utf-8")
    subprocess.run(
        [cc, "-std=c99", "-O2", "-I", str(DATA / "runtime"), str(c), "-o", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    )
    return binary


@pytest.mark.parametrize(
    "case",
    range(8),
    ids=[
        "restores-original-metadata",
        "tampered-buffer-or-rectangle-rejects-metadata",
        "bank-remap-rejects-even-identical-data",
        "buffer-reuse-and-bounded-eviction",
        "both-allocation-failures-free-everything",
        "data-port-has-no-extra-read-side-effects",
        "lcd-aliases-page3-and-wrapped-buffers-fall-back",
        "empty-layer-fast-path-keeps-slot-counts-consistent",
    ],
)
def test_saved_text_metadata(text_saves_binary, case):
    subprocess.run([str(text_saves_binary), str(case)], check=True, capture_output=True, text=True)
