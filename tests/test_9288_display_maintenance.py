"""Run the actual ordinary9288 pump, paint callback and framebuffer repair."""

from test_exit import run_c

from a9288.paths import DATA


def test_actual_pump_preserves_immediate_drawing_paint_and_periodic_physical_audit(tmp_path):
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    app = (DATA / "runtime/c6502_native_9288.c").read_text(encoding="utf-8")

    def part(start, end):
        return start + runtime.split(start, 1)[1].split(end, 1)[0]

    perf = part("typedef struct C6502_Perf", "static void bytes_set")
    lcd = part("static c6502_u16 lcd_address", "#ifdef C6502_T_FILTER_LINEAR")
    present = part("void c6502_native_present(void)", "static c6502_u8 map_key")
    refresh = part("static void native_refresh_if_due(void)\n{", "static c6502_u8 translate_key")
    pump = part("static void native_9288_pump", "#endif\n#ifdef C6502_TARGET_9288T")
    callback = (
        "static T_WORD native_window_proc"
        + app.split("static T_WORD native_window_proc", 1)[1].split("T_WORD App_Main", 1)[0]
    )
    run_c(
        tmp_path,
        r"""
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;typedef unsigned short c6502_u16;
typedef unsigned c6502_u32,T_WORD,T_GUI_HWND,T_GUI_HDC,T_GUI_WPARAM,T_GUI_LPARAM;
typedef struct {unsigned message,hWnd,wParam,lParam;} T_GUI_Msg;
#define C6502_TARGET_9288_GUI 1
#define C6502_GUEST_STRIDE 20u
#define C6502_GUEST_HEIGHT 96u
#define C6502_FRAME_STRIDE 80u
#define C6502_FRAME_HEIGHT 240u
#define C6502_HOST_FRAME_BYTES 19200u
#define C6502_VIEW_Y 24u
#define C6502_FRAME_TICKS 64u
#define C6502_9288_PUMP_TICKS 8u
enum {MSG_CLOSE=1,MSG_PAINT,MSG_ERASEBKGND,MSG_TIMER,MSG_KEYDOWN};
enum {NATIVE_EXIT_DESTROY_WINDOW,NATIVE_EXIT_POST_QUIT};
static unsigned char ram[32768],host_frame[19200] __attribute__((aligned(4))),expected[19200];
#define C6502_FRAMEBUFFER host_frame
static struct {unsigned char *ram;unsigned window;}c6502_native_state={ram,77};
static unsigned char c6502_frame_valid,c6502_output_ready,c6502_previous_frame[1920];
static unsigned c6502_expand_2x[256],c6502_last_frame_tick,now,advance_on_read,advance_by;
static unsigned native_clock(void){if(advance_on_read && !--advance_on_read)now+=advance_by;return now;}
static void native_capture_keys(void){}
static void native_refresh_if_due(void);
static unsigned c6502_native_host_stop_requested,c6502_native_9288_quit_received;
static unsigned c6502_9288_gui_last_pump,c6502_9288_gui_batches,c6502_9288_gui_messages,c6502_9288_gui_keys;
static unsigned char c6502_9288_gui_pumping;
static struct {unsigned active;}c6502_9288_host={1};
static unsigned messages,translations,dispatches,keepalives,begun,ended,defaults,queued;
static unsigned next_message=MSG_TIMER,white_without_paint;
static unsigned native_game_active=1,native_window_closed;
static int native_is_key_message(unsigned m){return m==MSG_KEYDOWN;}
static int c6502_native_resource_error(void){return 0;}
static unsigned fnGUI_BeginPaint(unsigned w){assert(w==77);++begun;memset(host_frame,255,sizeof(host_frame));return 88;}
static void fnGUI_EndPaint(unsigned w,unsigned dc){assert(w==77 && dc==88);++ended;}
static void c6502_native_exit_checkpoint(unsigned stage,unsigned done,unsigned w){(void)stage;(void)done;(void)w;}
static void fnGUI_DestroyMainWindow(unsigned w){(void)w;assert(0);}
static void fnGUI_PostQuitMessage(unsigned w){(void)w;assert(0);}
static unsigned fnGUI_DefaultMainWinProc(unsigned w,unsigned m,unsigned p,unsigned l){
 (void)w;(void)m;(void)p;(void)l;++defaults;return 0;
}
static int fnGUI_HavePendingMessage(unsigned w){assert(w==77);return queued;}
static int fnGUI_GetMessage(T_GUI_Msg*m,unsigned w){assert(w==77);++messages;queued=0;*m=(T_GUI_Msg){next_message,77,1,0};return 1;}
static void fnGUI_TranslateMessage(T_GUI_Msg*m){(void)m;++translations;}
static T_WORD native_window_proc(T_GUI_HWND,T_WORD,T_GUI_WPARAM,T_GUI_LPARAM);
static void fnGUI_DispatchMessage(T_GUI_Msg*m){
 ++dispatches;if(white_without_paint){memset(host_frame,255,sizeof(host_frame));white_without_paint=0;}
 native_window_proc(m->hWnd,m->message,m->wParam,m->lParam);
}
static void native_9288_host_pulse(unsigned tick){assert(tick==now);++keepalives;}
"""
        + perf
        + lcd
        + present
        + refresh
        + pump
        + callback
        + r"""
static void reference(void){
 memset(expected,255,sizeof(expected));
 for(unsigned y=0;y<96;++y)for(unsigned x=0;x<159;++x)
  if(ram[lcd_address(x/8,y)]&(128u>>(x&7)))
   for(unsigned yy=24+y*2;yy<26+y*2;++yy)for(unsigned xx=1+x*2;xx<3+x*2;++xx)
    expected[yy*80+xx/4]&=~(3u<<(6-2*(xx&3)));
}
static void batch(unsigned tick,unsigned message){now=tick;queued=1;next_message=message;native_9288_pump(now);}
int main(void){
 for(unsigned y=0;y<96;++y)for(unsigned x=0;x<20;++x)ram[lcd_address(x,y)]=(x*17+y*37+11)&255;
 c6502_native_present();reference();assert(!memcmp(host_frame,expected,sizeof(expected)));
 unsigned initial=c6502_perf.presents;
 /* Startup chrome can remain outside an already-correct guest view.
    The first real GUI batch must clear it before periodic gating. */
 memset(host_frame,0,24*80);memset(host_frame+216*80,0,24*80);
 assert(!memcmp(host_frame+24*80,expected+24*80,192*80));
 batch(8,MSG_TIMER);assert(c6502_perf.presents==initial+1);
 assert(!memcmp(host_frame,expected,sizeof(expected)));
 unsigned presents=c6502_perf.presents;
 batch(16,MSG_KEYDOWN);
 assert(c6502_perf.presents==presents && messages==2 && translations==2 && dispatches==2 && keepalives==2);
 /* A real LCD write remains immediately visible, without a frame/clock/pump. */
 unsigned address=lcd_address(4,65);ram[address]^=0xa5;native_lcd_write(address);
 reference();assert(!memcmp(host_frame,expected,sizeof(expected)));
 batch(17,MSG_TIMER);assert(c6502_perf.presents==presents);
 /* Real Begin/EndPaint white submission is reconciled in the same batch. */
 batch(18,MSG_PAINT);assert(begun==1 && ended==1 && c6502_frame_valid);
 assert(c6502_perf.presents==presents+1 && !memcmp(host_frame,expected,sizeof(expected)));
 /* No MSG_PAINT: compare physical LCD on the shared 64-tick fallback even
    when no SysGetKey/GetMsg API is called. Intermediate corruption is an
    explicit limitation of this candidate, not evidence of flicker safety. */
 white_without_paint=1;batch(19,MSG_TIMER);
 assert(memcmp(host_frame,expected,sizeof(expected)) && c6502_perf.presents==presents+1);
 batch(81,MSG_TIMER);assert(c6502_perf.presents==presents+1);
 batch(82,MSG_TIMER);assert(c6502_perf.presents==presents+2 && !memcmp(host_frame,expected,sizeof(expected)));
 /* Maintenance deadlines retain unsigned CTM wrap semantics. */
 c6502_last_frame_tick=0xfffffff0u;batch(47,MSG_TIMER);assert(c6502_perf.presents==presents+2);
 batch(48,MSG_TIMER);assert(c6502_perf.presents==presents+3);
 /* A slow physical reconciliation paces the next audit from completion. */
 c6502_last_frame_tick=200;advance_on_read=3;advance_by=80;batch(264,MSG_TIMER);
 assert(now==344 && c6502_last_frame_tick==344 && c6502_perf.presents==presents+4);
 batch(344,MSG_TIMER);assert(c6502_perf.presents==presents+4);
 assert(messages==11 && translations==messages && dispatches==messages && keepalives==messages);
 return 0;
}
""",
    )
