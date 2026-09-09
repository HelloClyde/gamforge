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

    def test_target_cache_crc_cow_limits_and_failure_cleanup(self):
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
            # Only path binding differs; cache, reads, CRC, writes and cleanup
            # are the production C header, compiled with host FS adapters.
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
#define fs_fread fread
#define fs_fseek fseek
#define fs_ftell ftell
#define fs_fclose fclose
static void bytes_set(uint8_t *p,uint8_t v,uint32_t n){memset(p,v,n);}
static void bytes_copy(uint8_t *p,const uint8_t *s,uint32_t n){memcpy(p,s,n);}
static jmp_buf escape;
void c6502_native_resource_abort(void) {longjmp(escape,1);}
"""
                + f"#define C6502_GAME_SIZE {len(game)}u\n"
                + config
                + r"""
#include "c6502_native_resources.h"
static uint8_t original(unsigned i){return (i*29+i/4096)&255;}
static void closed(void){assert(!nr_file && !nr_cache && !nr_crcs && !nr_dirty);}
int main(void){
    assert(nr_open());
    for(unsigned i=0;i<C6502_GAME_SIZE;i+=31) assert(nr_read(i)==original(i));
    assert(nr_read(C6502_GAME_SIZE-1)==original(C6502_GAME_SIZE-1));
    assert(nr_misses>32);
    assert(!nr_span(4095,2)); assert(!nr_span(C6502_GAME_SIZE-1,2));
    const uint8_t *p=nr_span(4090,6); assert(p && p[5]==original(4095));
    nr_write(7,original(7));assert(!nr_dirty_count);
    nr_write(7,original(7)^1);assert(nr_dirty_count==1);
    for(unsigned i=0;i<C6502_GAME_SIZE;i+=4096) (void)nr_read(i);
    assert(nr_read(7)==(original(7)^1));
    assert(nr_read(8)==original(8));
    nr_close();closed();assert(nr_open());assert(nr_read(7)==original(7));
    /* All 64 dirty pages stay live across clean-cache replacement. */
    for(unsigned i=0;i<64;++i) nr_write(i*4096,original(i*4096)^1);
    assert(nr_dirty_count==64);
    for(unsigned i=0;i<64;++i) assert(nr_read(i*4096)==(original(i*4096)^1));
    c6502_resource_entry_sp=1;
    if(!setjmp(escape)){nr_write(64*4096,original(64*4096)^1);assert(0);}
    assert(nr_error==6);nr_close();closed();
    assert(nr_open());c6502_resource_entry_sp=1;
    if(!setjmp(escape)){nr_read(C6502_GAME_SIZE);assert(0);}
    assert(nr_error==4);nr_close();closed();
    /* Corrupt a data page without changing header/table. */
    FILE *f=fopen(C6502_RESOURCE_PATH,"r+b");assert(f);
    fseek(f,64+71*4+4096,SEEK_SET);fputc(original(4096)^1,f);fclose(f);
    assert(nr_open());c6502_resource_entry_sp=1;
    if(!setjmp(escape)){nr_read(4096);assert(0);}
    assert(nr_error==5);nr_close();closed();
    /* Wrong header rejected before exposing any data. */
    f=fopen(C6502_RESOURCE_PATH,"r+b");fputc(0,f);fclose(f);
    assert(!nr_open() && nr_error==2);nr_close();closed();
    assert(remove(C6502_RESOURCE_PATH)==0);
    assert(!nr_open() && nr_error==1);nr_close();closed();
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
