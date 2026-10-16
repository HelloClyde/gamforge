/* 9288T target-resolution text. Guest LCD RAM remains byte-for-byte original.
 * Two 1-bpp planes cover only the 239x144 game view, never desktop margins.
 * Unknown game writes invalidate coverage; no stale reconstructed text survives.
 * This header has no SDK dependencies so the actual compositor is host-tested. */
static c6502_u8 native_text_mask[4320], native_text_ink[4320];
/* Each row holds an exact coverage count (at most 239). Clearing the last
 * text pixel restores the bitmap-only fast path, including after dialogs. */
static c6502_u8 native_text_rows[144], native_text_layer_dirty[1920];
static c6502_u32 native_text_active_rows, native_text_pending;
static c6502_u8 native_text_write_mask = 255u, native_text_write_keep;
static c6502_u32 native_text_layer_glyphs, native_text_layer_merges;
static const c6502_u8 native_text_expand4[16] = {
    0,3,12,15,48,51,60,63,192,195,204,207,240,243,252,255
};
/* Four guest pixels occupy 2,1,2,1 target pixels at this 3:2 scale. */
static const c6502_u8 native_text_expand6[16] = {
    0,1,6,7,8,9,14,15,48,49,54,55,56,57,62,63
};

static inline __attribute__((always_inline)) c6502_u32 native_text_popcount8(c6502_u32 v)
{
    v-=((v>>1)&0x55u);
    v=(v&0x33u)+((v>>2)&0x33u);
    return (v+(v>>4))&15u;
}

typedef struct NativeTextSnapshot {
    c6502_u16 first, last, top, bottom, xbyte, width, y, height;
    c6502_u8 planes[1];
} NativeTextSnapshot;

static void native_text_layer_reset(void)
{
    c6502_u32 i;
    for (i=0u;i<4320u;++i) native_text_mask[i]=native_text_ink[i]=0u;
    for (i=0u;i<144u;++i) native_text_rows[i]=0u;
    for (i=0u;i<1920u;++i) native_text_layer_dirty[i]=0u;
    native_text_write_mask=255u; native_text_write_keep=0u;
    native_text_layer_glyphs=native_text_layer_merges=0u;
    native_text_active_rows=native_text_pending=0u;
}

/* A raw guest RAM copy has no character provenance. Drop presentation
 * coverage without flushing the font cache or resetting session counters.
 * Ink can stay: every newly covered pixel is explicitly assigned by put. */
static void native_text_layer_discard(void)
{
    c6502_u32 i;
    for(i=0u;i<4320u;++i) native_text_mask[i]=0u;
    for(i=0u;i<144u;++i) native_text_rows[i]=0u;
    for(i=0u;i<1920u;++i) native_text_layer_dirty[i]=0u;
    native_text_active_rows=native_text_pending=0u;
}

static inline __attribute__((always_inline)) void native_text_dirty_mark(c6502_u32 at)
{
    if(!native_text_layer_dirty[at]) {
        native_text_layer_dirty[at]=1u;
        ++native_text_pending;
    }
}

/* Touch only selected guest pixels, including partial-byte primitives. */
static void native_text_layer_change(c6502_u32 column,c6502_u32 y,
    c6502_u8 mask,int invert)
{
    c6502_u32 sy,ey,dy,at,expanded,changed=0u;
    c6502_u8 first,last;
    if (!native_text_active_rows || !mask || column>=20u || y>=96u) return;
    sy=(y*3u+1u)/2u;ey=((y+1u)*3u+1u)/2u;
    /* An entire guest byte spans twelve target bits in two packed bytes.
     * Expand once, then touch each affected row/byte exactly once. */
    expanded=((c6502_u32)native_text_expand6[mask>>4]<<6) |
        native_text_expand6[mask&15u];
    expanded<<=(column&1u)?0u:4u;
    first=(c6502_u8)(expanded>>8);last=(c6502_u8)expanded;
    if(column==19u) last&=254u; /* target pixel 239 is desktop padding */
    at=sy*30u+column*12u/8u;
    for (dy=sy;dy<ey;++dy) if (native_text_rows[dy]) {
        c6502_u32 row_at=at+(dy-sy)*30u;
        c6502_u8 a=native_text_mask[row_at]&first;
        c6502_u8 b=native_text_mask[row_at+1u]&last;
        if(a|b) {
            changed=1u;
            if(invert) {
                native_text_ink[row_at]^=a;
                native_text_ink[row_at+1u]^=b;
            } else {
                native_text_mask[row_at]&=(c6502_u8)~a;
                native_text_mask[row_at+1u]&=(c6502_u8)~b;
                native_text_rows[dy]-=(c6502_u8)(native_text_popcount8(a)+native_text_popcount8(b));
                if(!native_text_rows[dy]) --native_text_active_rows;
            }
        }
    }
    if(changed) native_text_dirty_mark(y*20u+column);
}
static void native_text_layer_clear(c6502_u32 column,c6502_u32 y,c6502_u8 mask)
{ native_text_layer_change(column,y,mask,0); }
static void native_text_layer_invert(c6502_u32 column,c6502_u32 y,c6502_u8 mask)
{ native_text_layer_change(column,y,mask,1); }

static void native_text_layer_put(c6502_u32 x,c6502_u32 y,c6502_u32 width,
    const c6502_u8 *rows,c6502_u32 stride)
{
    c6502_u32 sx,sy,w,shift,bytes,dy,i;
    c6502_u8 masks[4];
    if(!rows || x>=159u || y>80u || (width!=8u && width!=16u)) return;
    sx=(x*3u+1u)/2u;sy=(y*3u+1u)/2u;w=width*3u/2u;
    if(w>239u-sx) w=239u-sx;
    shift=sx&7u;bytes=(shift+w+7u)/8u;
    for(i=0u;i<bytes;++i) masks[i]=255u;
    masks[0]=(c6502_u8)(255u>>shift);
    if((shift+w)&7u) masks[bytes-1u]&=(c6502_u8)(255u<<(8u-((shift+w)&7u)));
    for(dy=0u;dy<24u;++dy) {
        const c6502_u8 *source=rows+dy*stride;
        c6502_u32 bits=((c6502_u32)source[0]<<24)|((c6502_u32)source[1]<<16);
        c6502_u32 at=(sy+dy)*30u+sx/8u,added=0u;
        if(width==16u) bits|=(c6502_u32)source[2]<<8;
        bits>>=shift;
        for(i=0u;i<bytes;++i) {
            c6502_u8 m=masks[i],old=native_text_mask[at+i];
            added+=native_text_popcount8(m & (c6502_u8)~old);
            native_text_mask[at+i]=old|m;
            native_text_ink[at+i]=(native_text_ink[at+i] & (c6502_u8)~m) |
                ((c6502_u8)(bits>>24)&m);
            bits<<=8;
        }
        if(!native_text_rows[sy+dy]) ++native_text_active_rows;
        native_text_rows[sy+dy]+=(c6502_u8)added;
    }
    ++native_text_layer_glyphs;
}

/* Compose 1..4 packed 2-bpp bytes before the caller's single final store.
 * Low word bits correspond to the first framebuffer byte. Neither shadow
 * nor VRAM is accessed; unused word bytes and uncovered pixels stay intact. */
static inline __attribute__((always_inline)) c6502_u32 native_text_layer_merge_word(
    c6502_u32 dy,c6502_u32 byte,c6502_u32 word,c6502_u32 count)
{
    c6502_u32 i,mask=0u,ink=0u;
    if(dy>=144u || byte>=60u || !native_text_rows[dy]) return word;
    if(count>4u) count=4u;
    if(count>60u-byte) count=60u-byte;
    for(i=0u;i<count;++i) {
        c6502_u32 at=dy*30u+(byte+i)/2u,shift=((byte+i)&1u)?0u:4u;
        c6502_u32 m=native_text_expand4[(native_text_mask[at]>>shift)&15u];
        if(m) {
            mask|=m<<(i*8u);
            ink|=(c6502_u32)native_text_expand4[(native_text_ink[at]>>shift)&15u]<<(i*8u);
            ++native_text_layer_merges;
        }
    }
    return (word & ~mask) | (~ink & mask);
}

/* The filter has already regenerated the underlying bitmap. Merge opaque
 * text into its packed shadow as well as VRAM, so audit repairs stay sharp. */
static __attribute__((noinline)) void native_text_layer_apply(c6502_u32 first,c6502_u32 last,
    c6502_u32 dy,c6502_u32 physical)
{
    c6502_u32 a,b,byte,offset;
    if(dy>=144u || !native_text_rows[dy]) return;
    a=first?first*3u-1u:0u;b=(last+1u)*3u;
    if(b>59u) b=59u;
    offset=(C6502_VIEW_Y+dy)*C6502_FRAME_STRIDE;
    for(byte=a;byte<=b;++byte) {
        c6502_u32 at=dy*30u+byte/2u,shift=(byte&1u)?0u:4u;
        c6502_u8 m=native_text_expand4[(native_text_mask[at]>>shift)&15u];
        if(m) {
            c6502_u8 ink=native_text_expand4[(native_text_ink[at]>>shift)&15u];
            c6502_u8 value=(c6502_t_frame_shadow[offset+byte] & (c6502_u8)~m) |
                ((c6502_u8)~ink & m);
            c6502_t_frame_shadow[offset+byte]=value;
            if(physical) C6502_FRAMEBUFFER[offset+byte]=value;
            ++native_text_layer_merges;
        }
    }
}

/* Snapshot the byte-aligned A-series region. Packed host half-byte edges
 * are masked on restore, preserving neighbouring glyphs outside the save. */
static NativeTextSnapshot *native_text_layer_save(c6502_u32 first,c6502_u32 last,
    c6502_u32 top,c6502_u32 bottom)
{
    NativeTextSnapshot *s;
    c6502_u32 x0=first*12u,x1=(last+1u)*12u,sy=(top*3u+1u)/2u;
    c6502_u32 ey=((bottom+1u)*3u+1u)/2u,width,i,yy;
    if(first>last || last>=20u || top>bottom || bottom>=96u) return 0;
    if(x1>239u) x1=239u;
    width=(x1+7u)/8u-x0/8u;
    s=(NativeTextSnapshot *)malloc(sizeof(*s)+width*(ey-sy)*2u);
    if(!s) return 0;
    s->first=(c6502_u16)first;s->last=(c6502_u16)last;
    s->top=(c6502_u16)top;s->bottom=(c6502_u16)bottom;
    s->xbyte=(c6502_u16)(x0/8u);s->width=(c6502_u16)width;
    s->y=(c6502_u16)sy;s->height=(c6502_u16)(ey-sy);
    for(yy=0u;yy<ey-sy;++yy) for(i=0u;i<width;++i) {
        c6502_u32 n=yy*width+i,at=(sy+yy)*30u+x0/8u+i;
        s->planes[n]=native_text_mask[at];
        s->planes[width*(ey-sy)+n]=native_text_ink[at];
    }
    return s;
}
static void native_text_layer_restore(const NativeTextSnapshot *s)
{
    c6502_u32 x,yy,size,x0,x1;
    if(!s) return;
    x0=s->first*12u;x1=(s->last+1u)*12u;if(x1>239u)x1=239u;
    size=s->width*s->height;
    for(yy=0u;yy<s->height;++yy) {
        for(x=0u;x<s->width;++x) {
            c6502_u32 n=yy*s->width+x,at=(s->y+yy)*30u+s->xbyte+x;
            c6502_u8 m=255u;
            if(!x) m&=(c6502_u8)(255u>>(x0&7u));
            if(x+1u==s->width && (x1&7u)) m&=(c6502_u8)(255u<<(8u-(x1&7u)));
            native_text_mask[at]=(native_text_mask[at] & (c6502_u8)~m) | (s->planes[n]&m);
            native_text_ink[at]=(native_text_ink[at] & (c6502_u8)~m) | (s->planes[size+n]&m);
        }
        /* Snapshot restores can add or remove all coverage on a row. A
         * bytewise population count costs little on this infrequent path. */
        {
            c6502_u32 count=0u,at=(s->y+yy)*30u;
            for(x=0u;x<30u;++x) {
                c6502_u32 v=native_text_mask[at+x];
                v-=((v>>1)&0x55u);
                v=(v&0x33u)+((v>>2)&0x33u);
                count+=(v+(v>>4))&15u;
            }
            if(!native_text_rows[s->y+yy] && count) ++native_text_active_rows;
            else if(native_text_rows[s->y+yy] && !count) --native_text_active_rows;
            native_text_rows[s->y+yy]=(c6502_u8)count;
        }
    }
    for(yy=s->top;yy<=s->bottom;++yy)
        for(x=s->first;x<=s->last;++x) native_text_dirty_mark(yy*20u+x);
}
static void native_text_layer_free(NativeTextSnapshot *s) { if(s)free(s); }

static void native_text_nearest24(const c6502_u8 *source,c6502_u32 width,
    c6502_u8 *out)
{
    c6502_u32 x,y,stride=(width*3u/2u+7u)/8u;
    for(y=0u;y<24u;++y) {
        c6502_u8 *row=out+y*stride;
        for(x=0u;x<stride;++x)row[x]=0u;
        for(x=0u;x<width*3u/2u;++x) {
            c6502_u32 sx=x*2u/3u;
            if(source[(y*2u/3u)*(width/8u)+sx/8u] & (128u>>(sx&7u)))
                row[x/8u]|=(c6502_u8)(128u>>(x&7u));
        }
    }
}
