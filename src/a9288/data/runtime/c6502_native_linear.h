/* Optional 9288T 3:2 bilinear scaler. Packed four-grey pixels, no float,
 * division or allocation in the byte kernel. Source cache is the existing
 * 1,920-byte visible-LCD cache. Preserve exact guest RAM and hidden bit.
 * LUT rounds once AFTER both dimensions, not once per separable pass. */
#include "c6502_native_linear_lut.h"

static inline __attribute__((always_inline)) c6502_u16 native_linear_sample(
    const c6502_u8 *upper, const c6502_u8 *lower, c6502_u32 x)
{
    c6502_u32 u = upper[x], l = lower[x];
    if (x == 19u) {
        /* Pixel 159 is padding: interpolate against CLAMP(158). */
        u = (u & 0xfeu) | ((u >> 1) & 1u);
        l = (l & 0xfeu) | ((l >> 1) & 1u);
    }
    return (c6502_u16)((c6502_linear_spread[u] << 1) | c6502_linear_spread[l]);
}

/* A row-local interleaved sample buffer hoists vertical reads and border
   checks out of the four-triplet kernel; indices need only shifts/masks. */
static inline __attribute__((always_inline)) c6502_u32 native_linear_column(
    const c6502_u16 *in, const c6502_u32 *table)
{
    c6502_u32 v = in[0];
    return table[((in[-1] & 3u) << 6) | (v >> 10)] |
        table[256u + ((v >> 6) & 255u)] |
        table[512u + ((v >> 2) & 255u)] |
        table[768u + (((v & 63u) << 2) | (in[1] >> 14))];
}

static inline __attribute__((always_inline)) void native_linear_store3(
    c6502_u8 *shadow, volatile c6502_u8 *out, c6502_u32 word, c6502_u32 physical)
{
    shadow[0] = (c6502_u8)word; shadow[1] = (c6502_u8)(word >> 8);
    shadow[2] = (c6502_u8)(word >> 16);
    if (physical) {
        out[0] = (c6502_u8)word; out[1] = (c6502_u8)(word >> 8);
        out[2] = (c6502_u8)(word >> 16);
    }
}

/* At most one dependent pixel beyond each horizontal byte edge. Modify
   only its two bits; do not repaint whole neighbouring source bytes. */
static void native_linear_render_row(c6502_u32 first, c6502_u32 last,
    c6502_u32 dy, c6502_u32 upper_y, c6502_u32 lower_y,
    c6502_u32 phase, c6502_u32 physical)
{
    const c6502_u8 *upper = c6502_previous_frame + upper_y * 20u;
    const c6502_u8 *lower = c6502_previous_frame + lower_y * 20u;
    const c6502_u32 *table = c6502_linear_lut[phase];
    c6502_u32 offset = (C6502_VIEW_Y + dy) * C6502_FRAME_STRIDE;
    c6502_u8 *shadow = c6502_t_frame_shadow + offset + first * 3u;
    volatile c6502_u8 *out = C6502_FRAMEBUFFER + offset + first * 3u;
    c6502_u32 column = first, count = last - first + 1u, remaining = count, groups = 0u;
    c6502_u16 samples[22];
    const c6502_u16 *in = samples + 1u;
    c6502_u32 i;
    for (i = 0u; i < count; ++i)
        samples[i+1u] = native_linear_sample(upper,lower,first+i);
    samples[0] = first ? native_linear_sample(upper,lower,first-1u) : samples[1] >> 14;
    samples[count+1u] = last < 19u ? native_linear_sample(upper,lower,last+1u) :
        (c6502_u16)(samples[count] << 14);
    if (first) {
        c6502_u8 v = (c6502_u8)((shadow[-1] & 0xfcu) |
            ((table[768u + (((samples[0] & 63u) << 2) | (samples[1] >> 14))] >> 16) & 3u));
        shadow[-1] = v;
        if (physical) out[-1] = v;
    }
    while ((column & 3u) && remaining) {
        native_linear_store3(shadow, out,
            native_linear_column(in, table), physical);
        shadow += 3u; out += 3u; ++in; ++column; --remaining;
    }
    while (remaining >= 4u) {
        c6502_u32 a = native_linear_column(in, table);
        c6502_u32 b = native_linear_column(in+1u, table);
        c6502_u32 c = native_linear_column(in+2u, table);
        c6502_u32 d = native_linear_column(in+3u, table);
        c6502_u32 w0 = a | (b << 24), w1 = (b >> 8) | (c << 16);
        c6502_u32 w2 = (c >> 16) | (d << 8);
        ((c6502_u32 *)shadow)[0] = w0; ((c6502_u32 *)shadow)[1] = w1;
        ((c6502_u32 *)shadow)[2] = w2;
        if (physical) {
            ((volatile c6502_u32 *)out)[0] = w0;
            ((volatile c6502_u32 *)out)[1] = w1;
            ((volatile c6502_u32 *)out)[2] = w2;
        }
        shadow += 12u; out += 12u; in += 4u; column += 4u; remaining -= 4u; ++groups;
    }
    while (remaining--) {
        native_linear_store3(shadow, out,
            native_linear_column(in++, table), physical);
        shadow += 3u; out += 3u;
    }
    if (last < 19u) {
        c6502_u32 index = ((samples[count] & 3u) << 6) | (samples[count+1u] >> 10);
        c6502_u8 v = (c6502_u8)((shadow[0] & 0x3fu) | (table[index] & 0xc0u));
        shadow[0] = v;
        if (physical) out[0] = v;
    } else {
        /* The 240th host pixel is outside the visible 159-pixel source. */
        shadow[-1] |= 3u;
        if (physical) out[-1] = shadow[-1];
    }
    ++c6502_perf.linear_rows;
    c6502_perf.t_packed_groups += groups;
    if (physical) c6502_perf.framebuffer_bytes += count * 3u + (first != 0u) + (last < 19u);
}

/* Only inside a proven disjoint bitmap / snapshotted glyph call. Guest RAM
   still changes in the original order, but shared filter rows are resolved
   once before that call returns, never deferred to present/game-frame. */
static c6502_u32 native_linear_depth, native_linear_first, native_linear_last;
static c6502_u32 native_linear_top, native_linear_bottom;

static void native_linear_begin(void)
{
    if (!native_linear_depth++) {
        native_linear_first = 20u; native_linear_last = 0u;
        native_linear_top = 96u; native_linear_bottom = 0u;
    }
}

static void native_linear_end(void)
{
    c6502_u32 first_y, last_y, pair, dy;
    if (--native_linear_depth || native_linear_first == 20u) return;
    first_y = (native_linear_top * 3u + 1u) / 2u;
    if (first_y) --first_y;
    last_y = (native_linear_bottom * 3u + 1u) / 2u + 1u;
    if (last_y > 143u) last_y = 143u;
    dy = (first_y / 3u) * 3u;
    for (pair = (first_y / 3u) * 2u; dy <= last_y; pair += 2u, dy += 3u) {
        if (dy >= first_y)
            native_linear_render_row(native_linear_first,native_linear_last,
                dy,pair ? pair-1u : 0u,pair,0u,1u);
        if (dy+1u >= first_y && dy+1u <= last_y)
            native_linear_render_row(native_linear_first,native_linear_last,
                dy+1u,pair,pair+1u,1u,1u);
        if (dy+2u <= last_y)
            native_linear_render_row(native_linear_first,native_linear_last,
                dy+2u,pair+1u,pair+2u < 96u ? pair+2u : 95u,2u,1u);
    }
    ++c6502_perf.linear_batches;
}

#define NATIVE_LINEAR_BEGIN() native_linear_begin()
#define NATIVE_LINEAR_END() native_linear_end()

static void native_t_write_span(c6502_u32 first, c6502_u32 last,
    c6502_u32 y, const c6502_u8 *source)
{
    c6502_u8 *previous = c6502_previous_frame + y * 20u;
    c6502_u32 x, low = 20u, high = 0u, other = y+1u < 96u ? y+1u : y;
    c6502_u32 before = y ? y-1u : y, dy = (y >> 1) * 3u;
    for (x = first; x <= last; ++x) {
        c6502_u8 bits = source[x-first];
        if (x == 19u) bits &= 0xfeu;
        if (bits != previous[x]) {
            previous[x] = bits; if (low == 20u) low = x; high = x;
        }
    }
    if (low == 20u) { ++c6502_perf.linear_unchanged_spans; return; }
    if (native_linear_depth) {
        if (low < native_linear_first) native_linear_first = low;
        if (high > native_linear_last) native_linear_last = high;
        if (y < native_linear_top) native_linear_top = y;
        if (y > native_linear_bottom) native_linear_bottom = y;
        return;
    }
    if (!(y & 1u)) {
        if (y) native_linear_render_row(low, high, dy-1u, before, y, 2u, 1u);
        native_linear_render_row(low, high, dy, before, y, 0u, 1u);
        native_linear_render_row(low, high, dy+1u, y, other, 1u, 1u);
    } else {
        native_linear_render_row(low, high, dy+1u, before, y, 1u, 1u);
        native_linear_render_row(low, high, dy+2u, y, other, 2u, 1u);
        if (y < 95u) native_linear_render_row(low, high, dy+3u, y, other, 0u, 1u);
    }
}

static void native_t_write_byte(c6502_u32 x, c6502_u32 y, c6502_u8 bits)
{
    native_t_write_span(x, x, y, &bits);
}

/* Two passes: capture ALL changed RAM first, then filter affected host
   rows. Otherwise the upper rows would sample stale lower neighbours.
   Coalesce overlapping dependencies during full-screen audits/startup. */
static c6502_u32 native_linear_update_shadow(const c6502_u8 *ram)
{
    c6502_u8 dirty[144];
    c6502_u32 y, x, changed = 0u;
    for (y = 0u; y < 144u; ++y) dirty[y] = 0u;
    if (!c6502_frame_valid) {
        c6502_u32 *words = (c6502_u32 *)c6502_t_frame_shadow;
        for (x = 0u; x < C6502_HOST_FRAME_BYTES / 4u; ++x) words[x] = 0xffffffffu;
    }
    for (y = 0u; y < 96u; ++y) {
        c6502_u8 *previous = c6502_previous_frame + y * 20u;
        c6502_u32 modified = !c6502_frame_valid, dy = (y*3u+1u)/2u;
        c6502_u32 base = lcd_address(2u, y) - 2u;
        for (x = 0u; x < 20u; ++x) {
            c6502_u8 bits = ram[x < 2u ? lcd_address(x,y) : base+x];
            if (x == 19u) bits &= 0xfeu;
            modified |= bits != previous[x]; previous[x] = bits;
        }
        if (modified) {
            ++changed;
            if (dy) dirty[dy-1u] = 1u;
            if (dy < 144u) dirty[dy] = 1u;
            if (dy+1u < 144u) dirty[dy+1u] = 1u;
        }
    }
    for (y = 0u; y < 144u; ++y) if (dirty[y]) {
        c6502_u32 pair = (y/3u)*2u, phase = y%3u, top, bottom;
        top = phase == 0u ? (pair ? pair-1u : 0u) : pair + (phase == 2u);
        bottom = phase == 0u ? pair : top+1u;
        if (bottom > 95u) bottom = 95u;
        native_linear_render_row(0u,19u,y,top,bottom,phase,0u);
    }
    return changed;
}
