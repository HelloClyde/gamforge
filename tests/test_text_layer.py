"""Native 24-dot text compositing, independently checked at physical pixels."""

import shutil
import subprocess

import pytest

from a9288.paths import DATA

SOURCE = r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned c6502_u32;
#define C6502_VIEW_Y 8u
#define C6502_FRAME_STRIDE 60u
static c6502_u8 c6502_t_frame_shadow[9600];
static c6502_u8 guarded_frame[9632];
#define C6502_FRAMEBUFFER (guarded_frame+16)
static unsigned fail_allocation,allocations,frees;
static void *layer_malloc(size_t n){
    if(fail_allocation)return NULL;
    void *p=malloc(n);if(p)++allocations;return p;
}
static void layer_free(void *p){if(p)++frees;free(p);}
#define malloc layer_malloc
#define free layer_free
#include "c6502_native_text_layer.h"
#undef malloc
#undef free

/* Oracle stores individual physical pixels; no packed-mask implementation. */
static unsigned char base[160][240],coverage[144][239],ink[144][239];
static unsigned char glyph[24*3];
static unsigned char saved_coverage[144][239],saved_ink[144][239];
static unsigned scale(unsigned v){return (v*3+1)/2;}
static void set_pixel(unsigned char *p,unsigned x,unsigned y,unsigned v){
    unsigned a=y*60+x/4,s=6-(x%4)*2;
    p[a]=(unsigned char)((p[a]&~(3u<<s))|(v<<s));
}
static unsigned get_pixel(const unsigned char *p,unsigned x,unsigned y){
    return (p[y*60+x/4]>>(6-(x%4)*2))&3;
}
static unsigned background(unsigned x,unsigned y,unsigned salt){
    return (x*7+y*13+salt+(x/3))%4;
}
static void verify(void){
    unsigned active=0,pending=0;
    for(unsigned y=0;y<144;++y){
        unsigned count=0;for(unsigned x=0;x<239;++x){
            unsigned m=128u>>(x&7),at=y*30+x/8;
            count+=coverage[y][x]!=0;
            assert(!!(native_text_mask[at]&m)==!!coverage[y][x]);
            if(coverage[y][x])assert(!!(native_text_ink[at]&m)==!!ink[y][x]);
        }
        assert(!(native_text_mask[y*30+29]&1));
        assert(native_text_rows[y]==count);active+=count!=0;
    }
    assert(native_text_active_rows==active);
    for(unsigned i=0;i<1920;++i){assert(native_text_layer_dirty[i]<=1);pending+=native_text_layer_dirty[i]!=0;}
    assert(native_text_pending==pending);
    for(unsigned y=0;y<160;++y)for(unsigned x=0;x<240;++x){
        unsigned wanted=base[y][x];
        if(y>=8&&y<152&&x<239&&coverage[y-8][x])
            wanted=ink[y-8][x]?0:3;
        unsigned actual=get_pixel(C6502_FRAMEBUFFER,x,y);
        if(actual!=wanted){
            fprintf(stderr,"pixel (%u,%u): got %u, expected %u\n",x,y,actual,wanted);
            abort();
        }
        assert(get_pixel(c6502_t_frame_shadow,x,y)==wanted);
    }
    for(unsigned i=0;i<16;++i){assert(guarded_frame[i]==0xa5);assert(guarded_frame[9616+i]==0xa5);}
}
static void initialise(void){
    memset(guarded_frame,0xa5,sizeof(guarded_frame));
    memset(coverage,0,sizeof(coverage));memset(ink,0,sizeof(ink));
    native_text_layer_reset();
    for(unsigned y=0;y<160;++y)for(unsigned x=0;x<240;++x){
        base[y][x]=(unsigned char)background(x,y,1);
        set_pixel(C6502_FRAMEBUFFER,x,y,base[y][x]);
        set_pixel(c6502_t_frame_shadow,x,y,base[y][x]);
    }
    for(unsigned i=0;i<sizeof(glyph);++i)glyph[i]=(i*29+0x53)^(i>>2);
    fail_allocation=0;allocations=frees=0;
}
static void oracle_put(unsigned x,unsigned y,unsigned width,const unsigned char *bits,unsigned stride){
    /* A-series text skips a cell which cannot fit its 16 source rows. */
    if(x>=159||y>80||(width!=8&&width!=16)||!bits)return;
    unsigned x0=scale(x),y0=scale(y),w=width*3/2;
    for(unsigned row=0;row<24&&y0+row<144;++row)
        for(unsigned col=0;col<w&&x0+col<239;++col){
            coverage[y0+row][x0+col]=1;
            ink[y0+row][x0+col]=(bits[row*stride+col/8]>>(7-col%8))&1;
        }
}
static void put(unsigned x,unsigned y,unsigned width){
    unsigned stride=(width*3/2+7)/8;
    native_text_layer_put(x,y,width,glyph,stride);
    oracle_put(x,y,width,glyph,stride);
}
static void oracle_mask(unsigned column,unsigned y,unsigned mask,unsigned invert){
    for(unsigned bit=0;bit<8;++bit)if(mask&(128>>bit)){
        unsigned sx=column*8+bit;
        for(unsigned yy=scale(y);yy<scale(y+1)&&yy<144;++yy)
            for(unsigned xx=scale(sx);xx<scale(sx+1)&&xx<239;++xx){
                if(invert){if(coverage[yy][xx])ink[yy][xx]^=1;}
                else coverage[yy][xx]=0;
            }
    }
}
static void clear(unsigned column,unsigned y,unsigned mask){
    native_text_layer_clear(column,y,(c6502_u8)mask);oracle_mask(column,y,mask,0);
}
static void invert(unsigned column,unsigned y,unsigned mask){
    native_text_layer_invert(column,y,(c6502_u8)mask);oracle_mask(column,y,mask,1);
}
static void apply_all(unsigned physical){
    for(unsigned y=0;y<144;++y)native_text_layer_apply(0,19,y,physical);
}
static void redraw_all(unsigned salt){
    for(unsigned y=8;y<152;++y)for(unsigned x=0;x<239;++x){
        base[y][x]=(unsigned char)background(x,y,salt);
        set_pixel(C6502_FRAMEBUFFER,x,y,base[y][x]);
        set_pixel(c6502_t_frame_shadow,x,y,base[y][x]);
    }
    apply_all(1);
}
static void redraw_region(unsigned first,unsigned last,unsigned dy,unsigned salt){
    unsigned left=first?first*12-1:0,right=(last+1)*12;
    if(right>238)right=238;
    for(unsigned x=left;x<=right;++x){
        base[dy+8][x]=(unsigned char)background(x,dy+8,salt);
        set_pixel(C6502_FRAMEBUFFER,x,dy+8,base[dy+8][x]);
        set_pixel(c6502_t_frame_shadow,x,dy+8,base[dy+8][x]);
    }
    native_text_layer_apply(first,last,dy,1);
}
static void test_native_pixels(void){
    initialise();put(17,11,16);put(45,11,8);apply_all(1);verify();
    /* Opaque white background is as important as black strokes. */
    unsigned white=0,black=0;
    for(unsigned y=17;y<41;++y)for(unsigned x=26;x<50;++x){
        unsigned p=get_pixel(C6502_FRAMEBUFFER,x,y+8);
        assert(p==0||p==3);white+=p==3;black+=p==0;
    }
    assert(white&&black);
}
static void test_neighbour_redraw(void){
    initialise();put(7,20,16);put(23,20,8);apply_all(1);verify();
    for(unsigned y=29;y<55;++y){
        redraw_region(0,0,y,3);redraw_region(3,3,y,2);
    }
    verify();
}
static void test_masked_clear(void){
    initialise();put(8,8,16);apply_all(1);verify();
    assert(!native_text_layer_dirty[10*20+1]);
    /* Disjoint source bits remove only their own 1/2-column footprints. */
    clear(1,10,0xa5);clear(2,11,0x42);redraw_all(1);verify();
    assert(native_text_layer_dirty[10*20+1]&&native_text_layer_dirty[11*20+2]);
    /* Same-value guest stores must still clear an existing high-res glyph. */
    clear(1,10,0xa5);redraw_all(1);verify();
}
static void test_unknown_write_fallback(void){
    initialise();put(8,8,16);put(32,8,16);apply_all(1);verify();
    for(unsigned y=8;y<24;++y)for(unsigned column=1;column<=2;++column)clear(column,y,255);
    redraw_all(2);verify();
    for(unsigned y=12;y<36;++y)for(unsigned x=12;x<36;++x)
        assert(get_pixel(C6502_FRAMEBUFFER,x,y+8)==base[y+8][x]);
}
static void test_invert_twice(void){
    unsigned char original[9600];initialise();put(8,8,16);apply_all(1);
    memcpy(original,C6502_FRAMEBUFFER,sizeof(original));
    for(unsigned y=8;y<24;++y){invert(1,y,0xf3);invert(2,y,0x3c);}
    redraw_all(1);verify();
    for(unsigned y=8;y<24;++y){invert(1,y,0xf3);invert(2,y,0x3c);}
    redraw_all(1);verify();assert(!memcmp(original,C6502_FRAMEBUFFER,sizeof(original)));
}
static void test_snapshot(void){
    initialise();put(7,7,16);put(32,25,8);apply_all(1);verify();
    memcpy(saved_coverage,coverage,sizeof(coverage));memcpy(saved_ink,ink,sizeof(ink));
    NativeTextSnapshot *snapshot=native_text_layer_save(1,2,8,23);assert(snapshot);
    /* A dialog overwrites some text, but unrelated later text must survive. */
    for(unsigned y=8;y<=23;++y)for(unsigned column=1;column<=2;++column)clear(column,y,255);
    put(8,8,16);put(64,40,8);redraw_all(3);verify();
    native_text_layer_restore(snapshot);
    for(unsigned y=scale(8);y<scale(24);++y)for(unsigned x=12;x<36;++x){
        coverage[y][x]=saved_coverage[y][x];ink[y][x]=saved_ink[y][x];
    }
    redraw_all(3);verify();native_text_layer_free(snapshot);
    assert(allocations==frees);
    native_text_layer_restore(NULL);native_text_layer_free(NULL);verify();
}
static void test_allocation_failure(void){
    initialise();put(8,8,16);apply_all(1);verify();
    fail_allocation=1;assert(!native_text_layer_save(0,19,0,95));verify();
    fail_allocation=0;
}
static void test_clipped_edges(void){
    initialise();put(153,80,16);put(0,0,8);apply_all(1);verify();
    /* A cell below the last text baseline must be ignored, not overflow. */
    put(12,81,8);put(153,90,16);apply_all(1);verify();
    clear(19,95,0xff);invert(19,94,0xff);redraw_all(2);verify();
    /* The unused 240th host pixel and top/bottom system margins stay intact. */
}
static void test_shadow_only(void){
    unsigned char before[9600];initialise();put(8,8,16);
    memcpy(before,C6502_FRAMEBUFFER,sizeof(before));apply_all(0);
    assert(!memcmp(before,C6502_FRAMEBUFFER,sizeof(before)));
    assert(memcmp(before,c6502_t_frame_shadow,sizeof(before)));
    apply_all(1);verify();
}
static unsigned next(unsigned *seed){*seed=*seed*1664525u+1013904223u;return *seed;}
static void test_random_operations(void){
    unsigned seed=9288;initialise();
    for(unsigned i=0;i<400;++i){
        unsigned a=next(&seed),b=next(&seed),c=next(&seed);
        switch(a%3){
        case 0:put(b%159,c%96,(a&128)?8:16);break;
        case 1:clear(b%20,c%96,(a>>8)&255);break;
        default:invert(b%20,c%96,(a>>8)&255);break;
        }
        redraw_all(i);verify();
    }
}
static void test_empty_reset_and_invalid_bounds(void){
    initialise();apply_all(1);verify();
    native_text_layer_clear(20,95,255);native_text_layer_invert(0,96,255);
    native_text_layer_put(159,0,16,glyph,3);
    native_text_layer_put(0,81,16,glyph,3);
    native_text_layer_put(0,0,7,glyph,3);
    native_text_layer_put(0,0,16,NULL,3);
    assert(!native_text_layer_save(2,1,0,10));
    assert(!native_text_layer_save(0,20,0,10));
    assert(!native_text_layer_save(0,19,4,3));
    assert(!native_text_layer_save(0,19,0,96));
    apply_all(1);verify();
    assert(!allocations&&!frees);
    put(0,0,16);apply_all(1);verify();
    native_text_layer_reset();memset(coverage,0,sizeof(coverage));
    redraw_all(1);verify();
    for(unsigned i=0;i<1920;++i)assert(!native_text_layer_dirty[i]);
}
static void test_all_glyph_alignments(void){
    const unsigned ys[]={0,1,80};
    for(unsigned w=8;w<=16;w+=8)for(unsigned x=0;x<159;++x)
        for(unsigned yi=0;yi<3;++yi){
            initialise();put(x,ys[yi],w);apply_all(1);verify();
            /* Both black-to-white and white-to-black overwrites must update
             * existing coverage without inflating its row population. */
            for(unsigned i=0;i<sizeof(glyph);++i)glyph[i]^=255;
            put(x,ys[yi],w);apply_all(1);verify();
        }
}
static void verify_plane_rows(unsigned first,unsigned last){
    unsigned active=0;
    for(unsigned y=0;y<144;++y)active+=native_text_rows[y]!=0;
    assert(active==native_text_active_rows);
    for(unsigned y=first;y<last;++y){
        unsigned count=0;
        for(unsigned x=0;x<239;++x){
            unsigned at=y*30+x/8,m=128u>>(x&7);
            assert(!!(native_text_mask[at]&m)==!!coverage[y][x]);
            if(coverage[y][x])assert(!!(native_text_ink[at]&m)==!!ink[y][x]);
            count+=coverage[y][x]!=0;
        }
        assert(native_text_rows[y]==count);
        assert(!(native_text_mask[y*30+29]&1));
    }
}
static void test_all_byte_masks(void){
    const unsigned ys[]={0,1,94,95};
    initialise();
    for(unsigned inv=0;inv<2;++inv)for(unsigned col=0;col<20;++col)
        for(unsigned yi=0;yi<4;++yi)for(unsigned mask=0;mask<256;++mask){
            unsigned y=ys[yi],at=y*20+col;
            put(col*8,y>80?80:y,16);
            if(native_text_layer_dirty[at]){
                native_text_layer_dirty[at]=0;--native_text_pending;
            }
            if(inv)invert(col,y,mask);else clear(col,y,mask);
            /* The last guest bit has no visible target pixel. */
            assert(native_text_layer_dirty[at]==!!(mask&(col==19?254:255)));
            verify_plane_rows(scale(y),scale(y+1));
        }
    redraw_all(1);verify();
}
static void test_merge_word(void){
    unsigned seed=0x928824,expected_merges=0;
    unsigned char shadow_before[9600],frame_before[9600];
    initialise();
    for(unsigned i=0;i<120;++i){
        unsigned x=next(&seed)%159,y=next(&seed)%81;
        put(x,y,(i&1)?8:16);
    }
    for(unsigned i=0;i<100;++i)clear(next(&seed)%20,next(&seed)%96,next(&seed)&255);
    memcpy(shadow_before,c6502_t_frame_shadow,sizeof(shadow_before));
    memcpy(frame_before,C6502_FRAMEBUFFER,sizeof(frame_before));
    assert(!native_text_layer_merges);
    for(unsigned y=0;y<144;++y)for(unsigned byte=0;byte<60;++byte)
        for(unsigned count=1;count<=4&&byte+count<=60;++count){
            unsigned value=next(&seed),expected=value;
            for(unsigned i=0;i<count;++i){
                unsigned covered=0;
                for(unsigned p=0;p<4;++p){
                    unsigned x=(byte+i)*4+p,s=i*8+6-p*2;
                    if(x<239&&coverage[y][x]){
                        covered=1;
                        expected=(expected&~(3u<<s))|((ink[y][x]?0u:3u)<<s);
                    }
                }
                expected_merges+=covered;
            }
            assert(native_text_layer_merge_word(y,byte,value,count)==expected);
            assert(native_text_layer_merges==expected_merges);
        }
    assert(native_text_layer_merge_word(144,0,0x12345678,4)==0x12345678);
    assert(native_text_layer_merge_word(0,60,0x12345678,4)==0x12345678);
    assert(native_text_layer_merge_word(0,0,0x12345678,0)==0x12345678);
    assert(native_text_layer_merges==expected_merges);
    assert(!memcmp(shadow_before,c6502_t_frame_shadow,sizeof(shadow_before)));
    assert(!memcmp(frame_before,C6502_FRAMEBUFFER,sizeof(frame_before)));
    redraw_all(1);verify();
}
int main(int argc,char **argv){
    assert(argc==2);
    switch(atoi(argv[1])){
    case 0:test_native_pixels();break;
    case 1:test_neighbour_redraw();break;
    case 2:test_masked_clear();break;
    case 3:test_unknown_write_fallback();break;
    case 4:test_invert_twice();break;
    case 5:test_snapshot();break;
    case 6:test_allocation_failure();break;
    case 7:test_clipped_edges();break;
    case 8:test_shadow_only();break;
    case 9:test_random_operations();break;
    case 10:test_empty_reset_and_invalid_bounds();break;
    case 11:test_all_glyph_alignments();break;
    case 12:test_all_byte_masks();break;
    case 13:test_merge_word();break;
    default:abort();
    }
    return 0;
}
"""


@pytest.fixture(scope="module")
def text_layer_binary(tmp_path_factory):
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    directory = tmp_path_factory.mktemp("text-layer")
    source = directory / "text_layer.c"
    binary = directory / "text_layer.exe"
    source.write_text(SOURCE, encoding="utf-8")
    subprocess.run(
        [cc, "-std=c99", "-O2", "-I", str(DATA / "runtime"), str(source), "-o", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    )
    return binary


@pytest.mark.parametrize(
    "case",
    range(14),
    ids=[
        "native-24dot-opaque-black-and-white",
        "adjacent-bilinear-halos-preserve-text",
        "masked-and-same-value-clears",
        "unknown-byte-writes-fall-back-to-bitmap",
        "double-invert-is-lossless",
        "partial-snapshot-preserves-overlay-metadata",
        "allocation-failure-is-nondestructive",
        "right-and-bottom-edge-clipping",
        "shadow-composition-does-not-write-physical-frame",
        "randomized-overlaps-clears-and-inversions",
        "empty-reset-and-invalid-bounds-are-safe",
        "every-glyph-x-alignment-and-clipped-edge",
        "every-byte-mask-at-all-columns-and-row-parities",
        "packed-word-composition-matches-independent-pixels",
    ],
)
def test_text_overlay_pixels(text_layer_binary, case):
    subprocess.run([str(text_layer_binary), str(case)], check=True, capture_output=True, text=True)


@pytest.mark.parametrize(
    "source_byte,changed_mask,restore_mode",
    [(0, 0x1C, -1), (255, 0x1F, -1), (0, 0, 0), (0, 0, 1), (0, 0, 2)],
    ids=["masked-clear", "or-spill", "ordered-restore", "direct-restore", "staged-restore"],
)
def test_picture_preserves_text_metadata(tmp_path, source_byte, changed_mask, restore_mode):
    """ROM masks and flag-1 restores must preserve exactly the surviving text."""
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    lcd = (
        "static c6502_u16 lcd_address"
        + runtime.split("static c6502_u16 lcd_address", 1)[1].split(
            "#ifdef C6502_T_FILTER_LINEAR", 1
        )[0]
    )
    picture = (
        "static void native_picture"
        + runtime.split("static void native_picture", 1)[1].split(
            "static void integer_to_ascii", 1
        )[0]
    )
    source = (
        "#define C6502_T_FILTER_LINEAR 1\n"
        + SOURCE.split("int main(int argc", 1)[0]
        + lcd
        + r"""
#define NATIVE_LINEAR_BEGIN() ((void)0)
#define NATIVE_LINEAR_END() ((void)0)
static unsigned char probe_ram[32768];
static struct {unsigned char *ram;unsigned short banks[16];} c6502_native_state={probe_ram,{0}};
#define C6502_RAM_SIZE 32768u
static struct {unsigned picture_ordered_calls,picture_staged_bytes,picture_direct_bytes;} c6502_perf;
static unsigned char guest_read(unsigned short address){return probe_ram[address];}
static void guest_write(unsigned short address,unsigned char value){
 probe_ram[address]=value;
 for(unsigned y=0;y<96;++y)for(unsigned x=0;x<20;++x)
  if(lcd_address(x,y)==address)native_text_layer_clear(x,y,native_text_write_mask);
}
static int picture_source_disjoint(unsigned short p,unsigned n){return RESTORE_MODE>0;}
static const unsigned char *picture_direct_source(unsigned short p,unsigned n){return RESTORE_MODE==1?probe_ram+p:NULL;}
static void native_lcd_span(unsigned f,unsigned l,unsigned y,const unsigned char*p,unsigned char a,unsigned char b){
 assert(a==255&&b==255);for(unsigned x=f;x<=l;++x)guest_write(lcd_address(x,y),*p++);
}
static void blit_packed_row(unsigned short s,unsigned char x,unsigned char y,unsigned char w,const unsigned char*p){assert(0);}
static void pixel(unsigned char x,unsigned char y,int black){assert(0);}
static unsigned touches;
static void native_linear_touch(unsigned first,unsigned last,unsigned top,unsigned bottom){++touches;}
#define malloc layer_malloc
#define free layer_free
#include "c6502_native_text_saves.h"
#undef malloc
#undef free
"""
        + picture
        + r"""
int main(void){
 initialise();put(8,8,16);apply_all(1);verify();
#if RESTORE_MODE<0
 unsigned address=lcd_address(1,10);probe_ram[address]=0xa5;
 probe_ram[0x1800]=SOURCE_BYTE;
 native_picture(11,10,13,10,0x1800,0);
 assert(probe_ram[address]==((0xa5&0xe3)|(SOURCE_BYTE>>3)));
 oracle_mask(1,10,CHANGED_MASK,0);
 redraw_all(2);verify();assert(native_text_write_mask==255);
#else
 memcpy(saved_coverage,coverage,sizeof(coverage));memcpy(saved_ink,ink,sizeof(ink));
 for(unsigned i=0;i<32;++i)probe_ram[0x1800+i]=(i*31+17)&255;
 native_text_save_record(0x1800,1,2,8,23);assert(native_text_saved(0x1800,1,2,8,23));
 for(unsigned y=8;y<24;++y){clear(1,y,255);clear(2,y,255);}
 redraw_all(2);verify();
 native_picture(8,8,23,23,0x1800,1);
 memcpy(coverage,saved_coverage,sizeof(coverage));memcpy(ink,saved_ink,sizeof(ink));
 redraw_all(2);verify();assert(touches==1);
 for(unsigned i=0;i<32;++i)assert(probe_ram[lcd_address(1+i%2,8+i/2)]==probe_ram[0x1800+i]);
 /* Reused/corrupt raw screen bytes cannot revive stale text metadata. */
 probe_ram[0x1800]^=1;
 for(unsigned y=8;y<24;++y){clear(1,y,255);clear(2,y,255);}
 native_picture(8,8,23,23,0x1800,1);redraw_all(2);verify();assert(touches==1);
 native_text_saves_reset();assert(allocations==frees);
#endif
 return 0;
}
"""
    )
    c = tmp_path / "single_byte_picture.c"
    binary = tmp_path / "single_byte_picture.exe"
    c.write_text(source, encoding="utf-8")
    subprocess.run(
        [
            cc,
            "-std=c99",
            "-O2",
            f"-DSOURCE_BYTE={source_byte}",
            f"-DCHANGED_MASK={changed_mask}",
            f"-DRESTORE_MODE={restore_mode}",
            "-I",
            str(DATA / "runtime"),
            str(c),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)


def test_raw_ram_copy_drops_text_without_leaving_target_font_strokes(tmp_path):
    """An untracked RAM copy cannot identify pixels belonging to a 24-dot glyph."""
    cc = shutil.which("gcc")
    if not cc:
        pytest.skip("host gcc is not installed")
    runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
    lcd = (
        "static c6502_u16 lcd_address"
        + runtime.split("static c6502_u16 lcd_address", 1)[1].split(
            "#ifdef C6502_T_FILTER_LINEAR", 1
        )[0]
    )
    source = (
        SOURCE.split("int main(int argc", 1)[0]
        + lcd
        + r"""
#define C6502_HOST_FRAME_BYTES 9600u
static unsigned char c6502_previous_frame[1920],probe_ram[32768];
static unsigned char c6502_frame_valid=1;
static struct {unsigned linear_rows,t_packed_groups,framebuffer_bytes,linear_batches,
 linear_unchanged_spans;} c6502_perf;
#include "c6502_native_linear.h"
/* Independent 4-tap reference after the metadata has been discarded. */
static void expected_bitmap(void){
 for(unsigned y=0;y<144;++y)for(unsigned x=0;x<239;++x){
  int nx=(int)x*4-1,ny=(int)y*4-1;
  unsigned sx=nx<0?0:(unsigned)nx/6,sy=ny<0?0:(unsigned)ny/6;
  unsigned wx=nx<0?0:(unsigned)nx%6,wy=ny<0?0:(unsigned)ny%6;
  unsigned tx=sx<158?sx+1:sx,ty=sy<95?sy+1:sy;
  unsigned a=(probe_ram[lcd_address(sx/8,sy)]&(128>>(sx&7)))?0:3;
  unsigned b=(probe_ram[lcd_address(tx/8,sy)]&(128>>(tx&7)))?0:3;
  unsigned c=(probe_ram[lcd_address(sx/8,ty)]&(128>>(sx&7)))?0:3;
  unsigned d=(probe_ram[lcd_address(tx/8,ty)]&(128>>(tx&7)))?0:3;
  base[y+8][x]=(a*(6-wx)*(6-wy)+b*wx*(6-wy)+c*(6-wx)*wy+d*wx*wy+18)/36;
 }
}
int main(void){
 unsigned char before[9600];initialise();
 for(unsigned y=0;y<160;++y)for(unsigned x=0;x<240;++x)base[y][x]=3;
 memset(c6502_t_frame_shadow,255,sizeof(c6502_t_frame_shadow));
 memset(C6502_FRAMEBUFFER,255,9600);
 put(8,8,16);apply_all(1);verify();
 /* A tracked byte store updates the source cache and keeps the glyph. */
 probe_ram[lcd_address(18,90)]=128;native_t_write_byte(18,90,128);
 assert(native_linear_update_shadow(probe_ram)==0);
 assert(native_text_active_rows==24);
 unsigned glyphs=native_text_layer_glyphs,merges=native_text_layer_merges;
 /* Mutating RAM behind the writer's back elsewhere must remove ALL old
    glyph coverage, including strokes with an unchanged white source bit. */
 probe_ram[lcd_address(18,90)]=64;
 native_text_dirty_mark(95*20); /* an as-yet unconsumed dirty flag */
 memcpy(before,C6502_FRAMEBUFFER,sizeof(before));
 unsigned rows=c6502_perf.linear_rows;
 assert(native_linear_update_shadow(probe_ram)==96);
 assert(c6502_perf.linear_rows-rows==144);
 assert(!memcmp(before,C6502_FRAMEBUFFER,sizeof(before))); /* shadow audit */
 assert(!native_text_active_rows&&!native_text_pending);
 assert(native_text_layer_glyphs==glyphs&&native_text_layer_merges==merges);
 for(unsigned i=0;i<4320;++i)assert(!native_text_mask[i]);
 for(unsigned i=0;i<1920;++i)assert(!native_text_layer_dirty[i]);
 memset(coverage,0,sizeof(coverage));expected_bitmap();
 memcpy(C6502_FRAMEBUFFER,c6502_t_frame_shadow,9600);verify();
 /* The next audit returns to the unchanged bitmap-only fast path. */
 rows=c6502_perf.linear_rows;assert(!native_linear_update_shadow(probe_ram));
 assert(c6502_perf.linear_rows==rows);
 put(8,8,16);apply_all(1);verify(); /* discarded ink cannot leak into new text */
 return 0;
}
"""
    )
    c = tmp_path / "untracked_copy.c"
    binary = tmp_path / "untracked_copy.exe"
    c.write_text(source, encoding="utf-8")
    subprocess.run(
        [cc, "-std=c99", "-O2", "-I", str(DATA / "runtime"), str(c), "-o", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
