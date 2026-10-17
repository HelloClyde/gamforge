"""External resource format and the actual target paging implementation."""

import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from a9288.compiler.build import generate_bridges
from a9288.gui import Conversion
from a9288.paths import DATA
from a9288.resources import HEADER, c_resource_config, pack_resources


class ResourcesTest(unittest.TestCase):
    def test_format_identity_checksums_and_gui_option(self):
        game = bytes(range(256)) * 33 + b"tail"
        name, blob = pack_resources(game)
        self.assertRegex(name, r"^R[0-9A-F]{7}\.RES$")
        expected_path = "".join(f"\\x{b:02x}" for b in ("a:\\系统\\数据\\" + name).encode("gbk"))
        self.assertIn(
            f'#define C6502_RESOURCE_PATH "{expected_path}"', c_resource_config(name, blob)
        )
        h = HEADER.unpack_from(blob)
        self.assertEqual(h[:5], (b"A9288RES", 1, 4096, len(game), 3))
        self.assertEqual(h[6], hashlib.sha256(game).digest())
        self.assertEqual(blob[h[5] :], game)
        self.assertEqual(zlib.crc32(blob[64 : h[5]]), h[7])
        for page in range(h[4]):
            self.assertEqual(
                struct.unpack_from("<I", blob, 64 + page * 4)[0],
                zlib.crc32(game[page * 4096 : (page + 1) * 4096]),
            )
        config = Conversion(Path("x.gam"), "x", None, Path("x.exe"), Path("sdk"), Path("tools"))
        self.assertNotIn("--external-resources", config.command(Path("work")))
        config = Conversion(
            Path("x.gam"),
            "x",
            None,
            Path("x.exe"),
            Path("sdk"),
            Path("tools"),
            external_resources=True,
        )
        self.assertIn("--external-resources", config.command(Path("work")))
        with self.assertRaises(ValueError):
            pack_resources(b"")

    def test_external_abort_is_opt_in_and_restores_entry_stack(self):
        with tempfile.TemporaryDirectory() as folder:
            _, assembly = generate_bridges([], Path(folder), external_resources=True)
            source = assembly.read_text()
            self.assertIn("c6502_native_resource_abort:", source)
            self.assertIn("ld.w %sp, %r1", source)
            self.assertIn("c6502_resource_entry_sp", source)
            _, assembly = generate_bridges([], Path(folder))
            self.assertNotIn("c6502_native_resource_abort:", assembly.read_text())

    def test_target_has_no_crc_code_and_reports_disabled_crc(self):
        source = (DATA / "runtime/c6502_native_resources.h").read_text(encoding="utf-8")
        for name in ("nr_crc", "nr_crcs", "nr_u32"):
            self.assertNotRegex(source, rf"\b{name}\b")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        self.assertRegex(runtime, r'native_log_value\(file,\s*"resource_crc_enabled",\s*0u\s*\)')

    def test_target_cache_skips_crc_preserves_io_checks_cow_and_tail_page(self):
        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc unavailable")
        game = bytes((i * 29 + i // 4096) & 255 for i in range(70 * 4096 + 17))
        name, blob = pack_resources(game)
        with tempfile.TemporaryDirectory(prefix="a9288-res-") as folder:
            base = Path(folder)
            resource = base / name
            resource.write_bytes(blob)
            config = c_resource_config(name, blob[:64])
            # Cache, reads, writes and cleanup are the production C header.
            # Host FS adapters count I/O and inject errors without changing
            # the unchanged RES v1 header/checksum-table/data layout.
            config += (
                "\n#undef C6502_RESOURCE_PATH\n#define C6502_RESOURCE_PATH "
                + json.dumps(str(resource))
                + "\n"
            )
            c = (
                r"""
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
#include <assert.h>
typedef uint8_t c6502_u8; typedef uint32_t c6502_u32;
#define FS_FILE FILE
#define fs_fopen fopen
#define fs_fclose fclose
static unsigned read_calls, seek_calls, malloc_calls;
static size_t read_bytes, malloc_bytes, last_read_requested;
static long last_read_offset, data_offset;
static unsigned short_read_next, fail_seek_next, fail_tell_next, fail_malloc_at;
static size_t host_read(void *p,size_t size,size_t count,FILE *f){
    last_read_offset=ftell(f);last_read_requested=size*count;++read_calls;
    /* The table between the fixed header and data is never read at runtime. */
    assert(last_read_offset==0 || last_read_offset>=data_offset);
    if(short_read_next && count){short_read_next=0;--count;}
    size_t result=fread(p,size,count,f);read_bytes+=result*size;return result;
}
static int host_seek(FILE *f,long offset,int origin){
    ++seek_calls;
    if(fail_seek_next){fail_seek_next=0;return -1;}
    return fseek(f,offset,origin);
}
static long host_tell(FILE *f){
    if(fail_tell_next){fail_tell_next=0;return -1;}
    return ftell(f);
}
static void *host_malloc(size_t bytes){
    ++malloc_calls;malloc_bytes+=bytes;
    if(fail_malloc_at==malloc_calls)return NULL;
    return malloc(bytes);
}
static void reset_io(void){
    read_calls=seek_calls=malloc_calls=0;read_bytes=malloc_bytes=0;
    last_read_offset=-1;last_read_requested=0;
    short_read_next=fail_seek_next=fail_tell_next=fail_malloc_at=0;
}
#define fs_fread host_read
#define fs_fseek host_seek
#define fs_ftell host_tell
#define malloc host_malloc
static void bytes_set(uint8_t *p,uint8_t v,uint32_t n){memset(p,v,n);}
static void bytes_copy(uint8_t *p,const uint8_t *s,uint32_t n){memcpy(p,s,n);}
static jmp_buf escape;
void c6502_native_resource_abort(void) {longjmp(escape,1);}
"""
                + f"#define C6502_GAME_SIZE {len(game)}u\n"
                + config
                + r"""
#include "c6502_native_resources.h"
#undef malloc
static uint8_t original(unsigned i){return (i*29+i/4096)&255;}
static void closed(void){assert(!nr_file && !nr_cache && !nr_dirty);}
static uint8_t *archive;
static size_t archive_size;
static void restore_file(size_t size){
    FILE *f=fopen(C6502_RESOURCE_PATH,"wb");assert(f);
    size_t amount=size<archive_size?size:archive_size;
    assert(fwrite(archive,1,amount,f)==amount);
    for(size_t i=amount;i<size;++i)assert(fputc(0,f)!=EOF);
    assert(!fclose(f));
}
static void open_header_only(void){
    reset_io();assert(nr_open());
    assert(read_calls==1 && read_bytes==64);
    assert(last_read_offset==0 && last_read_requested==64);
    assert(malloc_calls==2);
    assert(malloc_bytes==NR_SLOTS*NR_PAGE+nr_pages*sizeof(*nr_dirty));
}
int main(void){
    FILE *f=fopen(C6502_RESOURCE_PATH,"rb");assert(f);
    assert(!fseek(f,0,SEEK_END));archive_size=(size_t)ftell(f);
    archive=(uint8_t *)malloc(archive_size);assert(archive);
    assert(!fseek(f,0,SEEK_SET));assert(fread(archive,1,archive_size,f)==archive_size);
    assert(!fclose(f));data_offset=64+((C6502_GAME_SIZE+4095)/4096)*4;
    open_header_only();
    assert(nr_read(0)==original(0));
    assert(read_calls==2 && read_bytes==64+4096);
    assert(last_read_offset==data_offset && last_read_requested==4096);
    assert(nr_read(1)==original(1) && read_calls==2);
    for(unsigned i=0;i<C6502_GAME_SIZE;i+=31) assert(nr_read(i)==original(i));
    assert(nr_read(C6502_GAME_SIZE-1)==original(C6502_GAME_SIZE-1));
    /* The short final page reads only its payload and zero-fills its remainder. */
    assert(last_read_requested==17);
    const uint8_t *tail=nr_page(C6502_GAME_SIZE-1);
    for(unsigned i=17;i<NR_PAGE;++i)assert(tail[i]==0);
    nr_write(C6502_GAME_SIZE-1,original(C6502_GAME_SIZE-1)^1);
    assert(nr_dirty_count==1 && nr_read(C6502_GAME_SIZE-1)==(original(C6502_GAME_SIZE-1)^1));
    tail=nr_page(C6502_GAME_SIZE-1);
    for(unsigned i=17;i<NR_PAGE;++i)assert(tail[i]==0);
    assert(nr_misses>32);
    assert(!nr_span(0,0));assert(!nr_span(4095,2));
    assert(!nr_span(C6502_GAME_SIZE-1,2));assert(!nr_span(1,0xffffffffu));
    const uint8_t *p=nr_span(4090,6); assert(p && p[5]==original(4095));
    nr_close();closed();open_header_only();
    nr_write(7,original(7));assert(!nr_dirty_count);
    nr_write(7,original(7)^1);assert(nr_dirty_count==1);
    for(unsigned i=0;i<C6502_GAME_SIZE;i+=4096) (void)nr_read(i);
    assert(nr_read(7)==(original(7)^1));
    assert(nr_read(8)==original(8));
    nr_close();closed();open_header_only();assert(nr_read(7)==original(7));
    assert(nr_read(C6502_GAME_SIZE-1)==original(C6502_GAME_SIZE-1));
    /* All 64 dirty pages stay live across clean-cache replacement. */
    for(unsigned i=0;i<64;++i) nr_write(i*4096,original(i*4096)^1);
    assert(nr_dirty_count==64);
    for(unsigned i=0;i<64;++i) assert(nr_read(i*4096)==(original(i*4096)^1));
    c6502_resource_entry_sp=1;
    if(!setjmp(escape)){nr_write(64*4096,original(64*4096)^1);assert(0);}
    assert(nr_error==6);nr_close();closed();
    open_header_only();c6502_resource_entry_sp=1;
    if(!setjmp(escape)){nr_read(C6502_GAME_SIZE);assert(0);}
    assert(nr_error==4);nr_close();closed();
    /* A failed seek or short read never exposes a partially filled cache slot. */
    open_header_only();c6502_resource_entry_sp=1;fail_seek_next=1;
    if(!setjmp(escape)){nr_read(4096);assert(0);}
    assert(nr_error==4 && read_calls==1 && nr_tags[1]==0xffffffffu);
    nr_close();closed();
    open_header_only();c6502_resource_entry_sp=1;short_read_next=1;
    if(!setjmp(escape)){nr_read(4096);assert(0);}
    assert(nr_error==4 && read_bytes==64+4095 && nr_tags[1]==0xffffffffu);
    nr_close();closed();
    /* Copy-on-write allocation failure aborts rather than altering clean data. */
    open_header_only();c6502_resource_entry_sp=1;fail_malloc_at=malloc_calls+1;
    if(!setjmp(escape)){nr_write(7,original(7)^1);assert(0);}
    assert(nr_error==3 && !nr_dirty_count && !nr_dirty[0]);
    assert(nr_cache[7]==original(7));nr_close();closed();
    /* Startup failures retain error codes and can all be cleaned/reopened. */
    reset_io();short_read_next=1;assert(!nr_open() && nr_error==2);
    assert(read_calls==1 && read_bytes==63);nr_close();closed();
    reset_io();fail_seek_next=1;assert(!nr_open() && nr_error==2);nr_close();closed();
    reset_io();fail_tell_next=1;assert(!nr_open() && nr_error==2);nr_close();closed();
    for(unsigned allocation=1;allocation<=2;++allocation){
        reset_io();fail_malloc_at=allocation;
        assert(!nr_open() && nr_error==3);nr_close();closed();
    }
    /* RES v1 tables remain present but deliberately are not checked or loaded. */
    f=fopen(C6502_RESOURCE_PATH,"r+b");assert(f);assert(!fseek(f,64,SEEK_SET));
    for(long i=64;i<data_offset;++i)assert(fputc(archive[i]^0xff,f)!=EOF);
    assert(!fclose(f));open_header_only();
    assert(nr_read(4096)==original(4096) && !nr_error);
    assert(last_read_offset==data_offset+4096);nr_close();closed();
    /* Same-length data corruption is now read verbatim, with no CRC error. */
    f=fopen(C6502_RESOURCE_PATH,"r+b");assert(f);
    assert(!fseek(f,data_offset+4096,SEEK_SET));
    assert(fputc(original(4096)^1,f)!=EOF);assert(!fclose(f));
    open_header_only();assert(nr_read(4096)==(original(4096)^1) && !nr_error);
    nr_close();closed();restore_file(archive_size);
    /* Header identity and the exact length are still mandatory. */
    restore_file(archive_size-1);reset_io();assert(!nr_open() && nr_error==2);
    nr_close();closed();restore_file(archive_size+1);reset_io();
    assert(!nr_open() && nr_error==2);nr_close();closed();restore_file(archive_size);
    /* Wrong header rejected before exposing any data. */
    f=fopen(C6502_RESOURCE_PATH,"r+b");assert(f);fputc(0,f);fclose(f);
    assert(!nr_open() && nr_error==2);nr_close();closed();
    /* Even checksum bytes inside the fixed header participate in identity. */
    restore_file(archive_size);f=fopen(C6502_RESOURCE_PATH,"r+b");assert(f);
    assert(!fseek(f,60,SEEK_SET));fputc(archive[60]^1,f);fclose(f);
    assert(!nr_open() && nr_error==2);nr_close();closed();
    restore_file(archive_size);open_header_only();
    assert(nr_read(4096)==original(4096));nr_close();closed();
    assert(remove(C6502_RESOURCE_PATH)==0);
    assert(!nr_open() && nr_error==1);nr_close();closed();
    free(archive);
    return 0;
}
"""
            )
            src = base / "test.c"
            exe = base / "test.exe"
            src.write_text(c, encoding="utf-8")
            subprocess.run(
                [cc, "-O2", "-I", str(DATA / "runtime"), str(src), "-o", str(exe)],
                check=True,
                timeout=30,
            )
            subprocess.run([str(exe)], check=True, timeout=10)
