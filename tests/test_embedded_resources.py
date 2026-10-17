"""Embedded resources are loader-owned writable bytes, never a heap duplicate."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from a9288.compiler import backend, build, kf2
from a9288.paths import DATA


class EmbeddedResourcesTest(unittest.TestCase):
    def test_old_oversized_map_does_not_mask_a_new_linker_error(self):
        with tempfile.TemporaryDirectory(prefix="a9288-link-map-") as folder:
            path = Path(folder) / "program.map"
            size = kf2.APP_LOAD_ADDRESS + kf2.max_kf2_payload_size("9288t") + 1
            path.write_text(f"{size:x} 0 0 __payload_end = .\n", encoding="utf-8")
            failure = subprocess.CalledProcessError(17, ["linker", "missing.o"])
            with (
                patch.object(build, "run", side_effect=failure),
                self.assertRaises(subprocess.CalledProcessError) as error,
            ):
                build.link_native_image([], path, "9288t", False)
            self.assertIs(error.exception, failure)
            self.assertFalse(path.exists())

    def test_link_success_does_not_inspect_a_stale_map(self):
        command = ["target-linker", "image.o"]
        with (
            patch.object(build, "run") as linker,
            patch.object(build.build_9288, "read_map_symbol") as symbol,
        ):
            build.link_native_image(command, Path("image.map"), "9288t", False)
        linker.assert_called_once_with(command)
        symbol.assert_not_called()

    def test_link_size_failures_explain_uncompressed_external_option(self):
        for target in ("9288", "9288t"):
            for external in (False, True):
                with self.subTest(target=target, external=external):
                    size = kf2.max_kf2_payload_size(target) + 1
                    failure = subprocess.CalledProcessError(1, ["target-linker"])
                    with (
                        patch.object(build, "run", side_effect=failure),
                        patch.object(
                            build.build_9288,
                            "read_map_symbol",
                            return_value=kf2.APP_LOAD_ADDRESS + size,
                        ),
                        self.assertRaises(SystemExit) as error,
                    ):
                        build.link_native_image([], Path("image.map"), target, external)
                    text = str(error.exception)
                    self.assertIn(str(size), text)
                    self.assertIn("未替换原输出 EXE", text)
                    if external:
                        self.assertIn("缩减代码", text)
                        self.assertNotIn("--external-resources", text)
                    else:
                        self.assertIn("--external-resources", text)
                        self.assertIn("同样不压缩", text)

    def test_non_size_link_failure_preserves_original_exception(self):
        failure = subprocess.CalledProcessError(17, ["target-linker", "missing.o"])
        for value in (kf2.APP_LOAD_ADDRESS + 128, OSError("no map"), SystemExit("no symbol")):
            with self.subTest(value=value):
                effect = (
                    {"side_effect": value}
                    if isinstance(value, BaseException)
                    else {"return_value": value}
                )
                with (
                    patch.object(build, "run", side_effect=failure),
                    patch.object(build.build_9288, "read_map_symbol", **effect),
                    self.assertRaises(subprocess.CalledProcessError) as error,
                ):
                    build.link_native_image([], Path("image.map"), "9288t", False)
                self.assertIs(error.exception, failure)

    def test_game_image_is_byte_exact_writable_section(self):
        # Include zeros, repeated bytes and every byte value: all must survive
        # untouched, even when compression would have made a smaller object.
        game = bytes(range(256)) * 17 + b"\0" * 8192 + b"unaligned-tail"
        with tempfile.TemporaryDirectory(prefix="a9288-embedded-") as folder:
            output = Path(folder)
            with patch.object(backend.subprocess, "run") as compile_call:
                result = backend.compile_resource_image("target-clang", output, game)
            raw = output / "c6502_game_image.bin"
            assembly = output / "c6502_game_image.S"
            self.assertEqual(raw.read_bytes(), game)
            self.assertEqual(result["raw_bytes"], len(game))
            self.assertEqual(result["stored_bytes"], len(game))
            self.assertEqual(result["compression"], "none")
            source = assembly.read_text(encoding="utf-8")
            self.assertIn('.section ".data.c6502_game_image","aw",@progbits', source)
            self.assertIn('    .incbin "' + raw.resolve().as_posix() + '"', source)
            self.assertIn("c6502_game_image_start:", source)
            self.assertIn("c6502_game_image_end:", source)
            self.assertNotIn("lzss", source)
            self.assertFalse(list(output.glob("*.lzss")))
            compile_call.assert_called_once_with(
                [
                    "target-clang",
                    "--target=s1c33-none-elf",
                    "-c",
                    str(assembly),
                    "-o",
                    result["object"],
                ],
                check=True,
            )

    def test_boot_snapshot_is_exported_once_and_embedded_without_transform(self):
        snapshot = b"C65" + bytes((i * 17 + 91) & 255 for i in range(32829))
        with tempfile.TemporaryDirectory(prefix="a9288-snapshot-") as folder:
            output = Path(folder)
            game, rom8, rome = (output / name for name in ("test.gam", "8.BIN", "E.BIN"))

            def export(game_path, raw_path, rom8_path, rome_path):
                self.assertEqual((game_path, rom8_path, rome_path), (game, rom8, rome))
                raw_path.write_bytes(snapshot)

            with (
                patch.object(
                    backend.boot_export, "export_snapshot", side_effect=export
                ) as exporter,
                patch.object(backend.subprocess, "run") as compiler,
            ):
                result = backend.compile_boot_snapshot("target-clang", output, game, rom8, rome)
            exporter.assert_called_once()
            self.assertEqual((output / "c6502_boot_snapshot.bin").read_bytes(), snapshot)
            self.assertEqual(result["raw_bytes"], len(snapshot))
            self.assertEqual(result["stored_bytes"], len(snapshot))
            self.assertEqual(result["compression"], "none")
            source = (output / "c6502_boot_snapshot.S").read_text(encoding="utf-8")
            self.assertIn('.section ".rodata.c6502_boot_snapshot","a",@progbits', source)
            self.assertIn("c6502_boot_snapshot_start:", source)
            self.assertIn("c6502_boot_snapshot_end:", source)
            self.assertNotIn("lzss", source)
            self.assertFalse(list(output.glob("*.lzss")))
            self.assertEqual(compiler.call_args.args[0][-1], result["object"])

    def test_target_prepare_banked_reads_writes_and_release_need_no_heap_copy(self):
        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc unavailable")
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        state_header = (DATA / "runtime/c6502_native_runtime.h").read_text(encoding="utf-8")
        state_type = (
            "typedef struct C6502_NativeState {"
            + state_header.split("typedef struct C6502_NativeState {", 1)[1].split(
                "extern volatile", 1
            )[0]
        )
        memory = (
            "static c6502_u8 physical_read"
            + runtime.split("static c6502_u8 physical_read", 1)[1].split("static void set_nz", 1)[0]
        )
        span = (
            "static const c6502_u8 *picture_direct_source"
            + runtime.split("static const c6502_u8 *picture_direct_source", 1)[1].split(
                "static void native_picture", 1
            )[0]
        )
        prepare = (
            "int c6502_native_prepare(void)"
            + runtime.split("int c6502_native_prepare(void)", 1)[1].split(
                "void c6502_native_perf_begin", 1
            )[0]
        )
        release = (
            "void c6502_native_release(void)"
            + runtime.split("void c6502_native_release(void)", 1)[1].split(
                "const char *c6502_native_resource_error", 1
            )[0]
        )
        # These are the production functions, not a reimplementation. Only OS
        # services, linker symbols and unrelated display/input globals are fake.
        source = (
            r"""
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t c6502_u8;
typedef uint16_t c6502_u16;
typedef uint32_t c6502_u32;
typedef unsigned T_GUI_HWND;
typedef unsigned T_GUI_HDC;
#define C6502_RAM_SIZE 32768u
#define C6502_BOOT_RAW_SIZE 32832u
#define C6502_GAME_SIZE 1966080u
#define C6502_GAME_PHYSICAL_BASE 0x20d000u
#define C6502_FLAG_Z 2u
#define C6502_FLAG_N 128u
#define C6502_OPEN_FILES 4u
static c6502_u8 image[C6502_GAME_SIZE], snapshot_bytes[C6502_BOOT_RAW_SIZE];
static unsigned linked_game_size=C6502_GAME_SIZE, linked_snapshot_size=C6502_BOOT_RAW_SIZE;
#define c6502_game_image_start image
#define c6502_game_image_end (image + linked_game_size)
#define c6502_boot_snapshot_start snapshot_bytes
#define c6502_boot_snapshot_end (snapshot_bytes + linked_snapshot_size)
static c6502_u8 c6502_boot_raw[C6502_BOOT_RAW_SIZE];
#define c6502_ram (c6502_boot_raw + 64u)
static unsigned malloc_calls, free_calls, index_loads, index_saves, lcd_writes;
static unsigned file_updates, file_closes;
static void *reject_malloc(size_t size){(void)size;++malloc_calls;return NULL;}
static void reject_free(void *pointer){(void)pointer;++free_calls;assert(0);}
#define malloc reject_malloc
#define free reject_free
static void bytes_set(c6502_u8 *p,c6502_u8 v,c6502_u32 n){memset(p,v,n);}
static void bytes_copy(c6502_u8 *p,const c6502_u8 *s,c6502_u32 n){memcpy(p,s,n);}
static void native_lcd_write(c6502_u16 address){(void)address;++lcd_writes;}
static void load_file_index(void){++index_loads;}
static void save_file_index(void){++index_saves;}
static unsigned fs_update(void *f){assert(f);++file_updates;return 0;}
static unsigned fs_fclose(void *f){assert(f);++file_closes;return 0;}
static c6502_u32 native_clock(void){return 123;}
static unsigned c6502_files_initialized,c6502_key_initialized,c6502_input_active;
static unsigned c6502_key_head,c6502_key_count,c6502_key_repeat;
static unsigned c6502_clock_initialized,c6502_clock_previous,c6502_clock_diagnostics;
static unsigned c6502_last_frame_tick,c6502_timer_clock,c6502_timer_fraction;
static unsigned c6502_timer_remaining,c6502_timer_pending,c6502_frame_valid;
static unsigned c6502_output_ready,c6502_glyphs[10],c6502_missing_bridge_count;
static c6502_u32 c6502_entry_regs[15];
static struct {void *stream;} c6502_open_files[C6502_OPEN_FILES];
#ifdef C6502_EXTERNAL_RESOURCES
static unsigned external_open_result,external_opens,external_closes;
static int nr_open(void){++external_opens;return external_open_result;}
static void nr_close(void){++external_closes;}
static c6502_u8 nr_read(c6502_u32 a){return image[a];}
static void nr_write(c6502_u32 a,c6502_u8 v){image[a]=v;}
static const c6502_u8 *nr_span(c6502_u32 a,c6502_u32 n){(void)n;return image+a;}
#endif
void c6502_native_release(void);
"""
            + state_type
            + r"""
static C6502_NativeState c6502_native_state;
static c6502_u16 get16(c6502_u32 a){return c6502_ram[a]|(c6502_ram[a+1]<<8);}
"""
            + memory
            + span
            + prepare
            + release
            + r"""
static c6502_u8 original(unsigned i){return (i*29u+i/4096u)&255;}
static void map(unsigned slot,unsigned bank){
    guest_write(0x0c,slot);guest_write(0x0d,bank);guest_write(0x0e,bank>>8);
}
int main(void){
#ifdef C6502_EXTERNAL_RESOURCES
    external_open_result=0;
    assert(!c6502_native_prepare());
    assert(external_opens==1 && external_closes==1);
    assert(!c6502_native_state.game && !malloc_calls && !free_calls && !index_loads);
    assert(!c6502_boot_raw[0]);
    external_open_result=1;memcpy(snapshot_bytes,"C65",3);
    assert(c6502_native_prepare());
    assert(external_opens==2 && external_closes==1);
    assert(!c6502_native_state.game && !malloc_calls && !free_calls && index_loads==1);
    assert(!memcmp(c6502_boot_raw,snapshot_bytes,C6502_BOOT_RAW_SIZE));
    c6502_native_release();assert(external_closes==2 && !free_calls);
#else
    for(unsigned i=0;i<C6502_GAME_SIZE;++i)image[i]=original(i);
    for(unsigned i=0;i<C6502_BOOT_RAW_SIZE;++i)snapshot_bytes[i]=(i*17u+91u)&255;
    memcpy(snapshot_bytes,"C65",3);
    snapshot_bytes[20]=0x11;snapshot_bytes[21]=0x22;
    snapshot_bytes[22]=0x33;snapshot_bytes[23]=0x44;snapshot_bytes[24]=0x82;
    snapshot_bytes[64+0x28]=0x34;snapshot_bytes[64+0x29]=0x12;
    assert(c6502_native_prepare());
    assert(!malloc_calls && !free_calls && index_loads==1);
    assert(c6502_native_state.game==image);
    assert(c6502_native_state.game_size==C6502_GAME_SIZE);
    assert(!memcmp(c6502_boot_raw,snapshot_bytes,C6502_BOOT_RAW_SIZE));
    assert(c6502_entry_regs[4]==0x11 && c6502_entry_regs[5]==0x22);
    assert(c6502_entry_regs[6]==0x33 && c6502_entry_regs[7]==0x44);
    assert(c6502_entry_regs[8]==0 && c6502_entry_regs[9]==0x82);
    assert(c6502_entry_regs[10]==0x1234 && c6502_native_state.running);
    for(unsigned i=0;i<C6502_GAME_SIZE;i+=997)
        assert(physical_read(C6502_GAME_PHYSICAL_BASE+i)==original(i));
    /* The bank API changes actual native memory helpers, including crossing
       two contiguous windows and deliberately noncontiguous banks. */
    map(9,0x20d);map(10,0x20e);
    assert(guest_read(0x9fff)==image[4095] && guest_read(0xa000)==image[4096]);
    assert(guest_get16(0x9fff)==(image[4095]|(image[4096]<<8)));
    const c6502_u8 *p=picture_direct_source(0x9ff0,32);
    assert(p==image+4080 && !memcmp(p,image+4080,32));
    guest_write(0x9fff,0x5a);guest_write(0xa000,0xa5);
    assert(image[4095]==0x5a && image[4096]==0xa5 && p[15]==0x5a && p[16]==0xa5);
    map(10,0x214);assert(guest_read(0xa000)==image[7*4096]);
    assert(!picture_direct_source(0x9ff0,32));
    map(10,0x20e);
    /* DATA channel increment remains sequenced across a resource page. */
    unsigned address=C6502_GAME_PHYSICAL_BASE+8191;
    c6502_ram[0x207]=1;c6502_ram[0x208]=address;
    c6502_ram[0x209]=address>>8;c6502_ram[0x20a]=address>>16;
    guest_write(0,0x73);assert(image[8191]==0x73);
    assert(guest_read(0)==image[8192]);
    assert(data_address(0,0)==address+2);
    physical_write(C6502_GAME_PHYSICAL_BASE+C6502_GAME_SIZE-1,0xc7);
    assert(image[C6502_GAME_SIZE-1]==0xc7);
    assert(!physical_read(C6502_GAME_PHYSICAL_BASE+C6502_GAME_SIZE));
    physical_write(C6502_GAME_PHYSICAL_BASE+C6502_GAME_SIZE,0);
    assert(image[C6502_GAME_SIZE-1]==0xc7);
    map(15,(C6502_GAME_PHYSICAL_BASE+C6502_GAME_SIZE-4096)>>12);
    assert(picture_direct_source(0xffff,1)==image+C6502_GAME_SIZE-1);
    assert(!picture_direct_source(0xffff,2));
    assert(!picture_direct_source(0x9000,0));
    c6502_open_files[1].stream=(void *)(uintptr_t)1;
    c6502_native_release();
    assert(!c6502_native_state.game && !malloc_calls && !free_calls);
    assert(file_updates==1 && file_closes==1 && index_saves==1);
    assert(!c6502_open_files[1].stream && image[8191]==0x73);
    c6502_native_release();assert(!free_calls && file_closes==1);
    /* A malformed embedded snapshot fails cleanly, with no heap ownership. */
    snapshot_bytes[0]='X';assert(!c6502_native_prepare());
    assert(!c6502_native_state.game && !malloc_calls && !free_calls);
    snapshot_bytes[0]='C';linked_game_size=C6502_GAME_SIZE-1;
    assert(!c6502_native_prepare() && !c6502_native_state.game);
    linked_game_size=C6502_GAME_SIZE;linked_snapshot_size=C6502_BOOT_RAW_SIZE-1;
    assert(!c6502_native_prepare() && !c6502_native_state.game);
    assert(!malloc_calls && !free_calls);
#endif
    return 0;
}
"""
        )
        with tempfile.TemporaryDirectory(prefix="a9288-embedded-runtime-") as folder:
            base = Path(folder)
            c, exe = base / "test.c", base / "test.exe"
            c.write_text(source, encoding="utf-8")
            for flags in ([], ["-DC6502_EXTERNAL_RESOURCES=1"]):
                subprocess.run([cc, "-O2", *flags, str(c), "-o", str(exe)], check=True, timeout=30)
                subprocess.run([str(exe)], check=True, timeout=10)
