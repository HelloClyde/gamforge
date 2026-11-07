"""Exercise real external cache and real picture/framebuffer C together.

Reuse the established framebuffer scalar oracle, injecting disk-backed resources
into its generated C rather than replacing the cache or drawing implementation.
No host timing here is reported as target performance.
"""

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_framebuffer


def test_external_cache_picture_matches_framebuffer_oracle(tmp_path, monkeypatch):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")

    def replace_once(source, old, new):
        assert source.count(old) == 1, old
        return source.replace(old, new, 1)

    path = json.dumps(str(tmp_path / "picture.RES"))
    fixture = r"""
#define C6502_EXTERNAL_RESOURCES 1
#define C6502_GAME_SIZE 139264u
#define C6502_RESOURCE_HEADER {0}
#define C6502_RESOURCE_PATH RESOURCE_FILE_PATH
#define FS_FILE FILE
#define fs_fopen fopen
#define fs_fclose fclose
#define fs_fseek fseek
#define fs_ftell ftell
static c6502_u32 test_resource_clock;
#define NR_CLOCK() (++test_resource_clock)
static unsigned injected_short_read;
static size_t resource_read(void*p,size_t size,size_t n,FILE*f){
 if(injected_short_read && ftell(f)>=64){injected_short_read=0;return 0;}
 return fread(p,size,n,f);
}
#define fs_fread resource_read
static void bytes_set(c6502_u8*p,c6502_u8 v,c6502_u32 n){memset(p,v,n);}
static void bytes_copy(c6502_u8*p,const c6502_u8*s,c6502_u32 n){memcpy(p,s,n);}
#include <setjmp.h>
static jmp_buf resource_escape;
void c6502_native_resource_abort(void){longjmp(resource_escape,1);}
#include "c6502_native_resources.h"
static void resource_fixture(void){
 nr_close();FILE*f=fopen(C6502_RESOURCE_PATH,"wb");assert(f);
 unsigned char header[64+((sizeof(game)+4095)/4096)*4]={0};
 assert(fwrite(header,1,sizeof(header),f)==sizeof(header));
 assert(fwrite(game,1,sizeof(game),f)==sizeof(game));assert(!fclose(f));assert(nr_open());
}
""".replace("RESOURCE_FILE_PATH", path)

    extra_cases = r"""
/* The conservative pixel oracle and candidate share only production memory
   semantics; the byte/pixel operations and framebuffer oracle are independent. */
static unsigned external_cases;
static unsigned external_query_min=0xffffffffu,external_query_max;
static void external_compare(unsigned source,unsigned flag,unsigned offset,
                             unsigned mapping,unsigned cow){
 static unsigned char initial[32768],oracle_ram[32768],oracle_frame[sizeof(host_frame)];
 for(unsigned i=0;i<32768;++i)ram[i]=(i*47+source*13+flag*37)&255;
 for(unsigned i=0;i<16;++i)c6502_native_state.banks[i]=0;
 c6502_native_state.banks[9]=0x20d;c6502_native_state.banks[10]=0x20e;
 c6502_native_state.banks[15]=0x20d;
 if(mapping==1)c6502_native_state.banks[10]=0x20f; /* noncontiguous */
 if(mapping==2)c6502_native_state.banks[10]=5;     /* RAM next to RES */
 if(mapping==3)c6502_native_state.banks[9]=0;     /* LCD alias */
 if(mapping==4)c6502_native_state.banks[10]=0x22d; /* same cache slot, +128 KiB */
 c6502_native_state.bank_select=0;
 ram[0x208]=0xff;ram[0x209]=0xdf;ram[0x20a]=0x20;ram[0x207]=1;
 resource_fixture();
 if(cow)nr_write(offset,game[offset]^0xa5u);
 memcpy(initial,ram,sizeof(ram));c6502_native_present();
 picture_oracle(0,0,159,95,source,flag);
 memcpy(oracle_ram,ram,sizeof(ram));memcpy(oracle_frame,host_frame,sizeof(host_frame));
 memcpy(ram,initial,sizeof(ram));resource_fixture();
 if(cow)nr_write(offset,game[offset]^0xa5u);
 c6502_native_present();unsigned queries=nr_hits+nr_misses;
 unsigned ordered=c6502_perf.picture_ordered_calls;
 native_picture(0,0,159,95,source,flag);
 if(memcmp(ram,oracle_ram,sizeof(ram))||memcmp(host_frame,oracle_frame,sizeof(host_frame))){
  fprintf(stderr,"external mismatch src=%04x flag=%u map=%u cow=%u\n",source,flag,mapping,cow);assert(0);
 }
 reference();
 if(mapping==0 && source>=0x9000 && source<0xa000){
  /* Read the immutable fixture array independently of guest_read/cache. */
  for(unsigned y=0;y<96;++y)for(unsigned x=0;x<20;++x){
   unsigned at=source-0x9000+y*20+x;
   unsigned char wanted=game[at];if(cow && at==offset)wanted^=0xa5u;
   assert(ram[lcd_address(x,y)]==wanted);
  }
 }
 if(mapping==0 && source>=0x9000 && source<0xa000){
  unsigned cost=nr_hits+nr_misses-queries;
  if((source&4095u)+1920u>4096u){
   assert(cost>=96 && cost<=115);
   if(cost<external_query_min)external_query_min=cost;
   if(cost>external_query_max)external_query_max=cost;
  }
  else assert(cost==1);
 }
 if(mapping==3||source<0x4000||source==0xfff8)
  assert(c6502_perf.picture_ordered_calls==ordered+1);
 if(cow){assert(nr_dirty_count==1);assert(nr_read(offset)==(game[offset]^0xa5u));}
 assert(!nr_error);++external_cases;
}
static void external_picture_cases(void){
 unsigned offsets[]={0,2176,2177,2190,3072,3076,4088,4090,4095};
 for(unsigned flag=0;flag<2;++flag){
  for(unsigned i=0;i<sizeof(offsets)/sizeof(offsets[0]);++i)
   external_compare(0x9000+offsets[i],flag,4095,0,0);
  external_compare(0x9ff8,flag,4095,0,1);
  external_compare(0x9ff8,flag,4095,1,0);
  external_compare(0x9ff8,flag,8192,1,1);
  external_compare(0x9ff8,flag,4095,2,0);
  external_compare(0x9ff8,flag,4095,3,0);
  external_compare(0x9ff8,flag,4095,4,0);
  external_compare(0,flag,4095,0,0);
  external_compare(0xfff8,flag,4095,0,0);
 }
 /* First data read fails: stop before any LCD mutation, never turn an I/O
    failure into a silently successful row of zeros. */
 resource_fixture();memset(ram,0x5a,sizeof(ram));
 c6502_native_state.banks[9]=0x20d;c6502_native_state.banks[10]=0x20e;
 c6502_native_present();memcpy(before,host_frame,sizeof(before));
 injected_short_read=1;c6502_resource_entry_sp=1;
 if(!setjmp(resource_escape)){native_picture(0,0,159,95,0x9ff8,1);assert(0);}
 assert(nr_error==4 && !memcmp(before,host_frame,sizeof(before)));
 nr_close();
 printf("EXTERNAL-PICTURE: %u cache/COW/bank/alias/DATA/wrap cases + short-read abort PASS; cross-page queries=%u..%u\n",
        external_cases,external_query_min,external_query_max);
}
"""

    real_run = subprocess.run

    def run(command, **kwargs):
        if command[0] == cc:
            cfile = Path(next(x for x in command if str(x).endswith("mirror.c")))
            source = cfile.read_text(encoding="utf-8")
            source = replace_once(source, "game[12288]", "game[139264]")
            source = replace_once(
                source,
                "c6502_native_state={ram,game,12288};",
                "c6502_native_state={ram,game,139264};",
            )
            source = replace_once(
                source, "static c6502_u8 physical_read", fixture + "\nstatic c6502_u8 physical_read"
            )
            source = replace_once(source, "int main(void){", extra_cases + "\nint main(void){")
            source = replace_once(
                source,
                "unsigned r[15]={0};r[10]=0x1800;",
                "unsigned r[15]={0};r[10]=0x1800;resource_fixture();",
            )
            source = replace_once(
                source,
                "for(unsigned i=0;i<sizeof(game);++i)game[i]=(i*43+17)&255;",
                "for(unsigned i=0;i<sizeof(game);++i)game[i]=(i*43+17)&255;\n resource_fixture();",
            )
            source = replace_once(
                source,
                "assert(picture_direct_source(0x9ff8,16)==game+4088);",
                "assert(!picture_direct_source(0x9ff8,16));",
            )
            source = replace_once(
                source,
                " differential_pictures();",
                " differential_pictures();external_picture_cases();",
            )
            cfile.write_text(source, encoding="utf-8")
        return real_run(command, **kwargs)

    monkeypatch.setattr(test_framebuffer, "subprocess", SimpleNamespace(run=run))
    test_framebuffer.test_direct_framebuffer_matches_reference_for_writes_and_graphics(
        tmp_path, "9288", "2x"
    )
