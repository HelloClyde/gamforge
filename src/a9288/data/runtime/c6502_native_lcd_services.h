/* A-series LCD services, not host SDK APIs. Annunciators occupy bit zero
   of scan-byte 18 and are outside the 159-pixel game viewport. Retain their
   RAM bits so full-screen picture copies preserve them exactly. */
static void native_icon_arrow(int up, c6502_u8 value)
{
    c6502_u16 address = (c6502_u16)(0x412u + (up ? 38u : 88u) * 32u);
    guest_write(address, (c6502_u8)((guest_read(address) & 0xfeu) | !!value));
}

static void native_icon_left_scroll(c6502_u8 percent)
{
    static const c6502_u8 scan_rows[38] = {
        36,33,30,27,25,24,22,21,18,15,14,12,11,10,9,5,4,3,2,1,
        66,67,69,70,71,72,73,74,75,77,79,80,81,83,84,85,86,87
    };
    c6502_u32 index, count = 0u;
    /* Use the ROM's integer thresholds, including equality behavior. */
    static const c6502_u8 thresholds[38] = {
        3,6,8,11,14,16,19,21,24,27,29,32,35,37,40,43,45,48,50,
        53,56,58,61,64,66,69,71,74,77,79,82,85,87,90,93,95,98,100
    };
    if (percent >= 100u) count = 38u;
    else if (percent) {
        while (count < 38u && percent >= thresholds[count]) ++count;
        ++count;
    }
    for (index = 0u; index < 38u; ++index) {
        c6502_u16 address = (c6502_u16)(0x412u + scan_rows[index] * 32u);
        guest_write(address, (c6502_u8)((guest_read(address) & 0xfeu) |
            (index < count)));
    }
}

#ifdef C6502_NEEDS_c6502_adapter_syslcdclear
static void native_lcd_clear(void)
{
    c6502_u32 address;
    /* E.BIN bank 5 $5762 clears the LCD envelope INCLUDING icon bits;
       virtual $0400 aliases $1000, and $03e8/$03e9 name the folded byte. */
    NATIVE_LINEAR_BEGIN();
    for (address = 0x400u; address < 0xff4u; ++address) {
        guest_write((c6502_u16)address, 0u);
        if (!(address & 127u)) native_capture_keys();
    }
    guest_write(0x1000u, 0u);
    guest_write(get16(0x3e8u), 0u);
    NATIVE_LINEAR_END();
}
#endif

#if defined(C6502_NEEDS_c6502_adapter_syspicturefill_direct) || \
    defined(C6502_NEEDS_c6502_adapter_syspicturefill)
static void native_picture_fill(c6502_u16 source)
{
    /* E.BIN bank 5 $66fd: 96 tightly packed 20-byte rows, with the final
       low bit (the physical annunciator) preserved on every row. */
    native_picture(0u, 0u, 158u, 95u, source, 0u);
    ++c6502_perf.picture_frame_commits;
}
#endif
