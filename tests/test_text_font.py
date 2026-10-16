"""Presentation glyphs must preserve guest pixels and the shared SDK DC font."""

from test_exit import run_c


def test_native_24_dot_font_cache_and_verified_fallback(tmp_path):
    run_c(
        tmp_path,
        r"""
#include <assert.h>
#include <string.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned c6502_u32,T_WORD;
#define C6502_TARGET_9288T 1
#define C6502_T_FILTER_LINEAR 1
#define C6502_FRAME_STRIDE 60u
#define FONT_TYPE_24_NORMAL 8u
typedef struct T_GUI_LogFont T_GUI_LogFont;
typedef struct T_GUI_DevFont T_GUI_DevFont;
typedef T_GUI_LogFont *T_GUI_pLogFont;
typedef struct {unsigned (*get_font_height)(T_GUI_LogFont*,T_GUI_DevFont*);
 unsigned (*get_char_width)(T_GUI_LogFont*,T_GUI_DevFont*,const c6502_u8*,unsigned);
} T_GUI_FontOps;
struct T_GUI_DevFont {T_GUI_FontOps *font_ops;unsigned height,width;};
struct T_GUI_LogFont {unsigned size;T_GUI_DevFont *sbc_devfont,*mbc_devfont;};
static unsigned height(T_GUI_LogFont*f,T_GUI_DevFont*d){return d->height;}
static unsigned width(T_GUI_LogFont*f,T_GUI_DevFont*d,const c6502_u8*t,unsigned n){
 assert(n==(t[1]?2u:1u));return d->width;}
static T_GUI_FontOps ops={height,width};
static T_GUI_DevFont ascii={&ops,24,12},chinese={&ops,24,24};
static T_GUI_LogFont old={16,0,0},large={24,&ascii,&chinese};
static T_GUI_pLogFont current=&old,selection=&large;
static unsigned sets,restores,draws;
static struct {unsigned hdc;} c6502_native_state={77};
static c6502_u8 c6502_text_surface[9600],guest_lcd[1920];
static void bytes_set(void*p,unsigned v,unsigned n){memset(p,v,n);}
static T_GUI_pLogFont fnGUI_GetCurFont(unsigned h){assert(h==77);return current;}
static T_GUI_pLogFont fnGUI_SetHdcFont(unsigned h,unsigned kind){
 assert(h==77&&kind==8);++sets;current=selection;return (T_GUI_pLogFont)1;}
static T_GUI_pLogFont fnGUI_SelectFont(unsigned h,T_GUI_pLogFont f){
 assert(h==77&&f==&old);++restores;current=f;return f;}
static void print(unsigned h,unsigned x,unsigned y,const c6502_u8*t,c6502_u8*s){
 unsigned row,pixel,w=t[1]?24:12;
 assert(h==77&&!x&&!y&&current==&large&&t[2]==0);++draws;
 for(row=0;row<24;++row)for(pixel=0;pixel<w;++pixel){
  unsigned shift=6-2*(pixel&3);
  unsigned value=(row+pixel)&3;
  s[row*60+(pixel>>2)]&=~(3u<<shift);
  s[row*60+(pixel>>2)]|=value<<shift;
 }}
#define NATIVE_GAME_GUI(member) print
#include "c6502_native_text_font.h"
int main(void){
 const c6502_u8 *rows=(void*)1;
 c6502_u8 a[3]={'A',0,0},b[3]={'B',0,0},c[3]={0xd6,0xd0,0};
 unsigned y,x,prior;
 memset(guest_lcd,0xa5,sizeof(guest_lcd));
 memset(c6502_text_surface,0x5a,sizeof(c6502_text_surface));
 native_text_font_reset();assert(sizeof(c6502_text_fonts)==4864);
 assert(native_text_font24(a,8,&rows)&&rows&&current==&old);
 assert(sets==1&&restores==1&&draws==1);
 for(y=0;y<24;++y){assert(!(rows[y*2+1]&15));
  for(x=0;x<12;++x)assert(!!(rows[y*2+x/8]&(128>>(x&7)))==(((x+y)&3)<2));}
 assert(c6502_text_surface[24*60]==0x5a);
 assert(native_text_font24(a,8,&rows)&&sets==1&&draws==1);
 assert(native_text_font24(c,16,&rows)&&sets==2&&draws==2);
 for(y=0;y<24;++y)for(x=0;x<24;++x)
  assert(!!(rows[y*3+x/8]&(128>>(x&7)))==(((x+y)&3)<2));
 assert(c6502_text_font_perf.hits==1&&c6502_text_font_perf.misses==2);
 /* A logical24 descriptor backed by16 pixel glyphs is not native24. */
 ascii.height=16;
 assert(!native_text_font24(b,8,&rows)&&!rows&&current==&old);
 assert(sets==3&&restores==3&&draws==2);
 assert(!native_text_font24(b,8,&rows)&&sets==3); /* negativecache */
 ascii.height=24;ascii.width=8;native_text_font_reset();
 assert(!native_text_font24(a,8,&rows)&&current==&old&&draws==2);
 ascii.width=12;large.size=16;native_text_font_reset();
 assert(!native_text_font24(a,8,&rows)&&current==&old&&draws==2);
 large.size=24;selection=0;native_text_font_reset();
 assert(!native_text_font24(a,8,&rows)&&current==&old&&draws==2);
 selection=&large;current=0;native_text_font_reset();prior=sets;
 assert(!native_text_font24(a,8,&rows)&&!rows&&sets==prior);
 current=&old;native_text_font_reset();
 assert(!native_text_font24(a,9,&rows)&&!rows&&sets==prior);
 assert(native_text_font24(a,8,&rows)&&current==&old);
 for(x=0;x<sizeof(guest_lcd);++x)assert(guest_lcd[x]==0xa5);
 assert(c6502_text_font_perf.rasterized==1);
 return 0;
}
""",
    )
