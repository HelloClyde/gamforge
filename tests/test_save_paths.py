import re
import shutil
import subprocess
from pathlib import Path

import pytest
from save_test_support import SAVE_HOST_FS

from a9288.paths import DATA
from a9288.save_paths import MAX_COMPONENT_BYTES, c_save_config, game_save_directory, game_save_name


def test_paths_use_source_game_name_not_display_metadata():
    assert game_save_directory(Path("伏魔记.gam")) == "A:\\系统\\数据\\游戏\\伏魔记"
    assert game_save_name(Path("魔塔之怀旧终曲.gam")) == "魔塔之怀旧终曲"
    assert game_save_directory(Path("first/伏魔记.gam")) == game_save_directory(
        Path("second/伏魔记.gam")
    )
    assert game_save_directory(Path("伏魔记.gam")) != game_save_directory(Path("中国象棋.gam"))


@pytest.mark.parametrize("name", ["...", "", "a:b", "a?b", 'a"b', "bad\nname", "游戏😀", "魔" * 80])
def test_unsafe_names_are_bounded_and_do_not_escape_directory(name):
    game = Path(name + ".gam")
    result = game_save_name(game)
    assert result and result not in (".", "..")
    assert not any(c in result for c in '<>:"/\\|?*')
    assert len(result.encode("gbk")) <= MAX_COMPONENT_BYTES
    assert not result.endswith((".", " "))
    assert game_save_name(game) == result


def test_sanitization_and_truncation_do_not_merge_names():
    assert game_save_name(Path("a:b.gam")) != game_save_name(Path("a?b.gam"))
    assert game_save_name(Path("魔" * 80 + "甲.gam")) != game_save_name(Path("魔" * 80 + "乙.gam"))


def test_config_encodes_full_directory_as_safe_gbk_c_literals():
    config = c_save_config(Path("中国象棋.gam"))
    assert config.isascii()
    values = dict(re.findall(r'#define (\w+) "([^"]+)"', config))
    decode = lambda value: bytes(int(v, 16) for v in re.findall(r"\\x([0-9a-f]{2})", value)).decode(
        "gbk"
    )
    assert decode(values["C6502_SAVE_DIRECTORY"]) == "A:\\系统\\数据\\游戏\\中国象棋"
    assert decode(values["C6502_SAVE_PARENT_GAMES"]) == "A:\\系统\\数据\\游戏"


def test_native_save_namespaces_are_persistent_and_do_not_import_shared_root(tmp_path):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    helper = (
        "#define C6502_FILE_RECORDS"
        + runtime.split("#define C6502_FILE_RECORDS", 1)[1].split("static c6502_u32 signed_div", 1)[
            0
        ]
    )
    names = sorted(set(re.findall(r"C6502_BRIDGE_\w+", helper)))
    defines = "enum {" + ",".join(names) + "};\n"
    defines += (
        "\n".join(
            "#define " + name + " 1" for name in sorted(set(re.findall(r"C6502_NEEDS_\w+", helper)))
        )
        + "\n"
    )
    prefix = (
        r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;typedef unsigned c6502_u32;
typedef FILE FS_FILE;
"""
        + SAVE_HOST_FS
        + r"""
#define C6502_RESOURCE_SCRATCH_SIZE 1920u
static unsigned char ram[65536],c6502_resource_scratch[1920];
static unsigned char guest_read(unsigned short a){return ram[a];}
static void guest_write(unsigned short a,unsigned char v){ram[a]=v;}
static void bytes_set(unsigned char*p,unsigned char v,unsigned n){memset(p,v,n);}
static void put16(unsigned short a,unsigned short v){ram[a]=v;ram[a+1]=v>>8;}
static void guest_put32(unsigned short a,unsigned v){put16(a,v);put16(a+2,v>>16);}
static unsigned guest_get32(unsigned short a){return ram[a]|ram[a+1]<<8|ram[a+2]<<16|ram[a+3]<<24;}
static unsigned char stack8(unsigned*r,unsigned n){return ram[(unsigned short)(r[10]+n)];}
static unsigned short stack16(unsigned*r,unsigned n){return stack8(r,n)|(stack8(r,n+1)<<8);}
static void return8(unsigned*r,unsigned char v){r[4]=v;}
"""
    )
    main = r"""
static unsigned r[15];
static unsigned create(unsigned value){
 guest_put32(0x1000,256);put16(0x1004,0x2000);put16(0x1006,0x2100);put16(0x1008,0x2102);
 r[4]=9;api_file(r,C6502_BRIDGE_c6502_adapter_filecreat);assert(r[4]==1);
 assert((ram[0x2100]|ram[0x2101]<<8)==1);unsigned h=ram[0x2102];
 memset(ram+0x2200,value,256);ram[0x1000]=0;put16(0x1001,0x2200);
 r[4]=h;api_file(r,C6502_BRIDGE_c6502_adapter_filewrite);assert(r[4]==1);
 r[4]=h;api_file(r,C6502_BRIDGE_c6502_adapter_fileclose);assert(r[4]==1);return h;
}
static unsigned open_save(void){
 put16(0x1000,1);ram[0x1002]=9;ram[0x1003]=1;put16(0x1004,0x2400);put16(0x1006,0x2404);
 api_file(r,C6502_BRIDGE_c6502_adapter_fileopen);assert(r[4]==1&&guest_get32(0x2404)==256);return ram[0x2400];
}
int main(int argc,char**argv){
 assert(argc==3);unsigned value=(unsigned)atoi(argv[2]);r[10]=0x1000;
 /* Failed prepare/release cannot create/truncate any index. */
 save_file_index();assert(!c6502_files_initialized);
 if(!strcmp(argv[1],"blocked"))save_host_blocked=1;
 load_file_index();
 if(!strcmp(argv[1],"write")){
  for(unsigned i=0;i<8;++i)assert(!c6502_file_records[i].valid);
  create(value);return 0;
 }
 if(!strcmp(argv[1],"read")){
  unsigned h=open_save();ram[0x1000]=0;put16(0x1001,0x2500);
  r[4]=h;api_file(r,C6502_BRIDGE_c6502_adapter_fileread);assert(r[4]==1);
  for(unsigned i=0;i<256;++i)assert(ram[0x2500+i]==value);
  r[4]=h;api_file(r,C6502_BRIDGE_c6502_adapter_fileclose);return 0;
 }
 if(!strcmp(argv[1],"delete")){
  r[4]=open_save();api_file(r,C6502_BRIDGE_c6502_adapter_filedel);assert(r[4]==1);return 0;
 }
 if(!strcmp(argv[1],"blocked")){
  guest_put32(0x1000,256);r[4]=9;api_file(r,C6502_BRIDGE_c6502_adapter_filecreat);
  assert(r[4]==0);save_file_index();return 0;
 }
 if(!strcmp(argv[1],"corrupt")){
  assert(!c6502_files_initialized);save_file_index();
  guest_put32(0x1000,256);r[4]=9;api_file(r,C6502_BRIDGE_c6502_adapter_filecreat);assert(r[4]==0);return 0;
 }
 return 1;
}
"""
    executables = []
    for name in ("伏魔记", "魔塔之怀旧终曲", "中国象棋"):
        source = tmp_path / f"fixture-{len(executables)}.c"
        exe = source.with_suffix(".exe")
        source.write_text(
            prefix + c_save_config(Path(name + ".gam")) + defines + helper + main, encoding="utf-8"
        )
        subprocess.run(
            [cc, "-O2", "-I", str(DATA / "runtime"), str(source), "-o", str(exe)], check=True
        )
        executables.append(exe)
    legacy = {"G49NIDX.BIN": b"legacy-shared-index", "G49090001.DAT": b"legacy-shared-data"}
    for name, data in legacy.items():
        (tmp_path / name).write_bytes(data)
    for exe, value in zip(executables[:2], (41, 82)):
        subprocess.run([str(exe), "write", str(value)], cwd=tmp_path, check=True)
    for exe, value in zip(executables[:2], (41, 82)):
        subprocess.run([str(exe), "read", str(value)], cwd=tmp_path, check=True)
    subprocess.run([str(executables[0]), "delete", "41"], cwd=tmp_path, check=True)
    subprocess.run([str(executables[1]), "read", "82"], cwd=tmp_path, check=True)
    subprocess.run([str(executables[2]), "blocked", "0"], cwd=tmp_path, check=True)
    # A truncated catalog must survive a session unchanged, not be replaced
    # by an empty catalog that permits data-file reuse/overwrite.
    indexes = list(tmp_path.rglob("G49NIDX.BIN"))
    owned = next(
        p
        for p in indexes
        if p.parent != tmp_path and "G49090001.DAT" in {x.name for x in p.parent.iterdir()}
    )
    owned.write_bytes(b"truncated-index")
    subprocess.run([str(executables[1]), "corrupt", "0"], cwd=tmp_path, check=True)
    assert owned.read_bytes() == b"truncated-index"
    for name, data in legacy.items():
        assert (tmp_path / name).read_bytes() == data
    assert len([p for p in indexes if p.parent != tmp_path]) == 2
