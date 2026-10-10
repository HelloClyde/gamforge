"""S host packing, geometry, isolated SDK selection and touch keyboard."""

import shutil
import struct
import subprocess

import pytest

from a9288.app_options import icon_images, write_icons
from a9288.compiler.d300 import ICON_DESCRIPTOR, pack_d300
from a9288.compiler.kf2 import pack_kf2, prepare_sdk_headers
from a9288.gui import Conversion
from a9288.paths import DATA
from a9288.targets import display_geometry, display_scale, target_profile


def test_s_package(tmp_path):
    host = target_profile("9288S")
    assert (host.width, host.height, host.executable_format) == (160, 240, "D300")
    assert display_geometry("9288s") == (159, 96, 0, 12)
    assert all(image.size == (32, 32) for image in icon_images(target="9288s"))
    write_icons(tmp_path, target="9288s")
    raw = b"native-payload"
    padded = raw + b"\0" * (-len(raw) & 3)
    packed = pack_d300(raw, app_name="魔塔".encode("gbk"), icon_root=tmp_path)
    assert packed[:4] == b"D300"
    assert struct.unpack_from("<II", packed, 4) == (0x80, len(packed))
    assert packed[0x0C:0x14] == "娱乐".encode("gbk").ljust(8, b"\0")
    assert packed[0x80:0x84] == b"EXE\0"
    assert struct.unpack_from("<7I", packed, 0x84) == (0x80, 0x100, 528, 0, 0, 0x310, len(padded))
    assert packed[0x100:0x110] == ICON_DESCRIPTOR
    assert packed[0x110:0x210] == packed[0x210:0x310]
    assert packed[0x310:] == padded
    assert packed[0xB0:0xD0].rstrip(b"\0") == "魔塔".encode("gbk")
    with pytest.raises(ValueError, match="requires D300"):
        pack_kf2(raw, target="9288s")
    with pytest.raises(ValueError):
        display_scale("9288s", "1.5x")


def test_s_sdk_and_conversion(tmp_path):
    sdk = tmp_path / "sdk"
    (sdk / "Down_Include").mkdir(parents=True)
    (sdk / "Down_Include/Dsys.h").write_text("/* S-only */")
    prepare_sdk_headers(sdk, tmp_path / "include", target="9288s")
    assert (tmp_path / "include/Dsys.h").read_text() == "/* S-only */"
    conversion = Conversion(
        tmp_path / "g.gam",
        "游戏",
        None,
        tmp_path / "g.exe",
        sdk,
        tmp_path / "toolchain",
        target="9288s",
    )
    command = conversion.command(tmp_path / "work")
    assert command[command.index("--target") + 1] == "9288s"
    assert command[command.index("--display-scale") + 1] == "1x"


def test_s_keyboard_and_fifo(tmp_path):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc unavailable")
    source = r"""
#include <assert.h>
#include <string.h>
#include <stdio.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned c6502_u32;
#define C6502_TARGET_9288S 1
#include "c6502_native_host.h"
#include "c6502_native_softkeys.h"
static struct {unsigned key_queue_overflows,key_queue_peak,key_repeats,key_edges,
 keys_consumed,key_scan_max_gap_ticks,key_scans;} c6502_perf;
#include "c6502_native_input.h"
static void snapshot(unsigned k5,unsigned p0,unsigned now){
 unsigned char current[8];native_s_matrix(current,k5,p0);native_key_snapshot(current,now);
}
int main(void){
 unsigned char surface[C6502_HOST_FRAME_BYTES+32];
 memset(surface,0xa5,sizeof(surface));native_s_keyboard_paint(surface);
 for(unsigned i=0;i<120*40;++i)assert(surface[i]==0xa5);
 for(unsigned i=9600;i<sizeof(surface);++i)assert(surface[i]==0xa5);
 /* Every lower-screen pixel belongs to exactly one key, none to the game. */
 for(int y=0;y<240;++y)for(int x=0;x<160;++x){
  unsigned hits=0;
  for(unsigned i=0;i<C6502_S_KEY_COUNT;++i){const C6502_S_Key*k=c6502_s_keys+i;
   hits+=x>=k->x&&x<k->x+k->width&&y>=k->y&&y<k->y+20;}
  assert(hits==(y>=120));assert((native_s_hit_key(x,y)!=255)==(y>=120));
 }
 assert(native_s_hit_key(-1,200)==255&&native_s_hit_key(160,200)==255);
 snapshot(255,255,0);assert(native_take_key()==255);
 /* Down and up within the same tick retain one short-tap edge. */
 c6502_s_touch_key=native_s_hit_key(135,210);snapshot(255,255,1);
 c6502_s_touch_key=255;snapshot(255,255,1);assert(native_take_key()==0x39);
 assert(native_take_key()==255);
 /* Same logical physical/touch key is never delivered twice. */
 c6502_s_touch_key=native_s_hit_key(135,210);snapshot(254,255,2);
 assert(native_take_key()==0x39);assert(native_take_key()==255);
 c6502_s_touch_key=255;snapshot(255,255,3);
 c6502_s_touch_key=native_s_hit_key(30,230);snapshot(255,255,4);
 assert(native_take_key()==0x2f);
 for(unsigned t=5;t<200;++t)snapshot(255,255,t);
 assert(native_take_key()==255); /* ENTER cannot auto-repeat. */
 c6502_s_touch_key=255;snapshot(255,255,200);snapshot(255,255,204);
 snapshot(255,239,205);assert(native_take_key()==0x2e); /* physical ESC */
 puts("S-SOFTKEY: bounds, rendering, GPIO, taps and action FIFO PASS");
}
"""
    c = tmp_path / "softkeys.c"
    c.write_text(source, encoding="utf-8")
    exe = tmp_path / "softkeys.exe"
    subprocess.run(
        [cc, "-O2", "-Wall", "-I", str(DATA / "runtime"), str(c), "-o", str(exe)], check=True
    )
    subprocess.run([str(exe)], check=True, timeout=15)


def test_s_pointer_events_keep_short_edges_and_only_repaint_keyboard(tmp_path):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc unavailable")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    pointer = (
        "void c6502_native_pointer"
        + runtime.split("void c6502_native_pointer", 1)[1].split("static void native_s_pump", 1)[0]
    )
    source = (
        r"""
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;
typedef unsigned c6502_u32;typedef unsigned T_WORD;typedef unsigned T_GUI_LPARAM;
#define C6502_TARGET_9288S 1
#include "c6502_native_host.h"
#include "c6502_native_softkeys.h"
static struct {unsigned key_queue_overflows,key_queue_peak,key_repeats,key_edges,
 keys_consumed,key_scan_max_gap_ticks,key_scans;} c6502_perf;
#include "c6502_native_input.h"
enum {MSG_LBUTTONDOWN=1,MSG_LBUTTONUP=2,MSG_LBUTTONDBLCLK=3,MSG_MOUSEMOVE=4};
#define C6502_K5_DATA_ADDRESS 1
#define C6502_PORT0_DATA_ADDRESS 2
static unsigned now;
static unsigned c6502_s_last_pointer_message,c6502_s_last_pointer_position,c6502_s_last_pointer_down;
static unsigned char c6502_input_active,c6502_output_ready;
static unsigned char c6502_t_frame_shadow[C6502_HOST_FRAME_BYTES] __attribute__((aligned(4)));
static unsigned framebuffer[C6502_HOST_FRAME_BYTES/4];
#define C6502_FRAMEBUFFER framebuffer
static unsigned char ports[3]={255,255,255};
static unsigned char *hardware_byte(unsigned address){return ports+address;}
static unsigned native_clock(void){return now;}
"""
        + pointer
        + r"""
int main(void){unsigned char rows[8]={0};native_key_snapshot(rows,0);
 c6502_native_pointer(MSG_LBUTTONDOWN,(230u<<16)|40u); /* prelaunch ignored */
 assert(c6502_s_touch_key==255 && native_take_key()==255);
 c6502_native_pointer(MSG_LBUTTONUP,0);c6502_input_active=1;now=10;
 c6502_output_ready=1;memset(framebuffer,0xa5,sizeof(framebuffer));
 c6502_native_pointer(MSG_LBUTTONDOWN,(230u<<16)|40u);
 c6502_native_pointer(MSG_LBUTTONUP,(230u<<16)|40u);
 assert(native_take_key()==0x2f && native_take_key()==255);
 for(unsigned i=0;i<120*40/4;++i)assert(framebuffer[i]==0xa5a5a5a5u);
 now=20;native_key_snapshot(rows,now);
 c6502_native_pointer(MSG_LBUTTONDBLCLK,(230u<<16)|40u);
 c6502_native_pointer(MSG_LBUTTONUP,(230u<<16)|40u);
 assert(native_take_key()==0x2f && native_take_key()==255);
 now=30;c6502_native_pointer(MSG_LBUTTONDOWN,(210u<<16)|135u);
 assert(native_take_key()==0x39); /* RIGHT */
 c6502_native_pointer(MSG_MOUSEMOVE,(210u<<16)|5u);
 assert(native_take_key()==0x37); /* slide LEFT */
 c6502_native_pointer(MSG_MOUSEMOVE,(10u<<16)|5u);
 assert(c6502_s_touch_key==255 && native_take_key()==255);
 c6502_native_pointer(MSG_LBUTTONUP,0);
 assert(c6502_s_touch_presses==4);return 0;}
"""
    )
    c = tmp_path / "pointer.c"
    c.write_text(source, encoding="utf-8")
    exe = tmp_path / "pointer.exe"
    subprocess.run([cc, "-O2", "-I", str(DATA / "runtime"), str(c), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=15)
