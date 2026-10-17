#ifndef C6502_NATIVE_KEYMAP_H
#define C6502_NATIVE_KEYMAP_H

/* The PC compiler supplies only validated physical-source / guest-raw-code
 * overrides. Sources are GUI scan codes on T, row*8+column on 9288. No
 * remapping is ever applied to the 9288S / TSW600 touch keyboard. */
#ifndef C6502_KEYMAP_COUNT
#define C6502_KEYMAP_COUNT 0
#endif

#if C6502_KEYMAP_COUNT > 0 && !defined(C6502_TARGET_9288S)
static const c6502_u8 c6502_custom_keymap[C6502_KEYMAP_COUNT][2] = C6502_KEYMAP_ENTRIES;

static c6502_u32 native_keymap_lookup(c6502_u32 source, c6502_u32 fallback)
{
    c6502_u32 i;
    for (i = 0u; i < C6502_KEYMAP_COUNT; ++i)
        if (c6502_custom_keymap[i][0] == source) return c6502_custom_keymap[i][1];
    return fallback;
}
#else
#define native_keymap_lookup(source, fallback) (fallback)
#endif

#endif
