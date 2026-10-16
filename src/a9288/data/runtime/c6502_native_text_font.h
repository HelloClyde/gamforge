#ifndef C6502_NATIVE_TEXT_FONT_H
#define C6502_NATIVE_TEXT_FONT_H

/* Included after NATIVE_GAME_GUI and the host-sized text staging surface.
   The game still receives its original 8x16 / 16x16 glyph in monochrome RAM.
   These cached 12x24 / 24x24 glyphs are presentation-only, never guest data. */
#if defined(C6502_TARGET_9288T) && defined(C6502_T_FILTER_LINEAR)

typedef struct C6502_TextFontEntry {
    c6502_u16 code;
    c6502_u8 width, status; /* 0 empty, 1 native 24-dot, 2 unavailable */
    c6502_u8 rows[72];
} C6502_TextFontEntry;

typedef struct C6502_TextFontPerf {
    c6502_u32 hits, misses, rasterized, unavailable;
} C6502_TextFontPerf;

static C6502_TextFontEntry c6502_text_fonts[64];
static C6502_TextFontPerf c6502_text_font_perf;

static void native_text_font_reset(void)
{
    bytes_set((c6502_u8 *)c6502_text_fonts, 0u, sizeof(c6502_text_fonts));
    bytes_set((c6502_u8 *)&c6502_text_font_perf, 0u, sizeof(c6502_text_font_perf));
}

/* Convert eight 2-bpp SDK pixels to eight black-is-one monochrome pixels.
   SDK drawing remains two-bit even when the final LCD is in 16-gray mode. */
static c6502_u8 native_text_font_pack(const c6502_u8 *source)
{
    c6502_u8 a = (c6502_u8)~source[0];
    c6502_u8 b = (c6502_u8)~source[1];
    return (a & 0x80u) | ((a & 0x20u) << 1) |
        ((a & 8u) << 2) | ((a & 2u) << 3) |
        ((b & 0x80u) >> 4) | ((b & 0x20u) >> 3) |
        ((b & 8u) >> 2) | ((b & 2u) >> 1);
}

/* Success: *rows is packed MSB-first 1-bpp, height 24, stride 2 for guest
   width 8 or stride 3 for width 16. A miss returns zero and NULL so callers
   can use crisp nearest-neighbor guest pixels instead of blurred text.

   These early GUI entries use the SDK offsets unchanged (+4a4/+4a8/+544).
   Only SysPrintString needs NATIVE_GAME_GUI's verified late-table offset.
   SetHdcFont's firmware return is a status, despite its SDK pointer type;
   always save GetCurFont and restore with SelectFont. */
static int native_text_font24(const c6502_u8 *glyph,
    c6502_u8 guest_width, const c6502_u8 **rows)
{
    c6502_u16 code;
    c6502_u32 slot, stride, row, byte, target_width;
    c6502_u8 text[3];
    C6502_TextFontEntry *entry;
    T_GUI_pLogFont saved, selected;
    T_GUI_DevFont *device;
    *rows = (const c6502_u8 *)0;
    if (guest_width != 8u && guest_width != 16u) return 0;
    text[0] = glyph[0]; text[1] = glyph[1]; text[2] = 0u;
    code = (c6502_u16)(text[0] | ((c6502_u16)text[1] << 8));
    slot = (text[0] ^ text[1] ^ guest_width) & 63u;
    entry = c6502_text_fonts + slot;
    if (entry->status && entry->code == code && entry->width == guest_width) {
        ++c6502_text_font_perf.hits;
        if (entry->status != 1u) return 0;
        *rows = entry->rows;
        return 1;
    }
    ++c6502_text_font_perf.misses;
    entry->code = code; entry->width = guest_width; entry->status = 2u;
    saved = fnGUI_GetCurFont(c6502_native_state.hdc);
    /* Without a restorable old font, leave the shared DC untouched. */
    if (!saved) {
        ++c6502_text_font_perf.unavailable;
        return 0;
    }
    (void)fnGUI_SetHdcFont(c6502_native_state.hdc, FONT_TYPE_24_NORMAL);
    selected = fnGUI_GetCurFont(c6502_native_state.hdc);
    device = selected ? (text[1] ? selected->mbc_devfont :
        selected->sbc_devfont) : (T_GUI_DevFont *)0;
    target_width = (c6502_u32)guest_width * 3u / 2u;
    if (!selected || selected->size != 24u || !device ||
        !device->font_ops || !device->font_ops->get_font_height ||
        !device->font_ops->get_char_width ||
        device->font_ops->get_font_height(selected, device) != 24u ||
        device->font_ops->get_char_width(selected, device, text,
            text[1] ? 2u : 1u) != (T_WORD)target_width) {
        (void)fnGUI_SelectFont(c6502_native_state.hdc, saved);
        ++c6502_text_font_perf.unavailable;
        return 0;
    }
    /* Clear only the 24 rendered rows; never clear or touch guest LCD RAM. */
    bytes_set(c6502_text_surface, 0xffu, C6502_FRAME_STRIDE * 24u);
    NATIVE_GAME_GUI(SysPrintString)(c6502_native_state.hdc, 0, 0,
        text, c6502_text_surface);
    (void)fnGUI_SelectFont(c6502_native_state.hdc, saved);
    stride = (target_width + 7u) >> 3;
    for (row = 0u; row < 24u; ++row) {
        for (byte = 0u; byte < stride; ++byte)
            entry->rows[row * stride + byte] = native_text_font_pack(
                c6502_text_surface + row * C6502_FRAME_STRIDE + byte * 2u);
        if (stride == 2u) entry->rows[row * stride + 1u] &= 0xf0u;
    }
    entry->status = 1u;
    ++c6502_text_font_perf.rasterized;
    *rows = entry->rows;
    return 1;
}

#endif
#endif
