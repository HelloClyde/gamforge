"""Check cache read behavior through the real target header, at fixed capacity."""

import json
import shutil
import subprocess

import pytest

from a9288.paths import DATA
from a9288.resources import c_resource_config, pack_resources


@pytest.mark.parametrize("ways", [None, 1, 2], ids=["default", "direct", "two-way"])
def test_resource_cache_policy_retains_identity_lru_and_fixed_capacity(tmp_path, ways):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc unavailable")
    game = bytes((i // 4096 * 29 + i) & 255 for i in range(185 * 4096))
    name, resource = pack_resources(game)
    path = tmp_path / name
    path.write_bytes(resource)
    config = c_resource_config(name, resource)
    config += (
        "\n#undef C6502_RESOURCE_PATH\n#define C6502_RESOURCE_PATH " + json.dumps(str(path)) + "\n"
    )
    policy = "" if ways is None else f"#define C6502_RESOURCE_CACHE_WAYS {ways}\n"
    source = tmp_path / "policy.c"
    source.write_text(
        r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t c6502_u8; typedef uint32_t c6502_u32;
#define FS_FILE FILE
#define fs_fopen fopen
#define fs_fclose fclose
#define fs_fseek fseek
#define fs_ftell ftell
static unsigned payload_reads, allocations;
static size_t first_allocation;
static size_t host_read(void *p,size_t size,size_t n,FILE *f){
 if(ftell(f)>64)++payload_reads;return fread(p,size,n,f);
}
static void *host_malloc(size_t n){if(!allocations++)first_allocation=n;return malloc(n);}
#define fs_fread host_read
#define malloc host_malloc
static void bytes_set(c6502_u8*p,c6502_u8 v,c6502_u32 n){memset(p,v,n);}
static void bytes_copy(c6502_u8*p,const c6502_u8*s,c6502_u32 n){memcpy(p,s,n);}
void c6502_native_resource_abort(void){abort();}
"""
        + f"#define C6502_GAME_SIZE {len(game)}u\n"
        + config
        + policy
        + r"""
#include "c6502_native_resources.h"
static void page(unsigned n){assert(nr_read(n*4096)==(uint8_t)(n*29));}
int main(void){
 assert(nr_open());assert(first_allocation==131072 && allocations==2);
 for(unsigned i=0;i<260;++i)page(i&1?184:24);
#if C6502_RESOURCE_CACHE_WAYS == 1
 assert(payload_reads==260);
#else
 assert(payload_reads==2);
#endif
 nr_close();allocations=payload_reads=0;assert(nr_open());
 /* Same set: hit A before loading C, so B is the least recent page. */
 page(24);page(184);page(24);page(40);
#if C6502_RESOURCE_CACHE_WAYS == 2
 assert(payload_reads==3);page(24);assert(payload_reads==3);
 page(184);assert(payload_reads==4);
#else
 assert(payload_reads==4);page(24);assert(payload_reads==4);
 page(184);assert(payload_reads==5);
#endif
 assert(!nr_error);nr_close();return 0;
}
""",
        encoding="utf-8",
    )
    executable = tmp_path / "policy.exe"
    subprocess.run(
        [cc, "-O2", "-I", str(DATA / "runtime"), str(source), "-o", str(executable)], check=True
    )
    subprocess.run([str(executable)], check=True)
