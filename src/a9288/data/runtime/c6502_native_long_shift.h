/* C6502 __sl_long / __u_sr_long (E.BIN $DA3D / $DC0E).
   BOTH operands are pointers to four-byte objects. In particular $23 is
   not the shift count, unlike the byte/word shift ABI. */
static void runtime_shift_long(c6502_u32 *r, int right)
{
    c6502_u16 base = get16(0x2au);
    c6502_u16 output = (c6502_u16)(base + 8u);
    c6502_u16 count_address;
    c6502_u32 value, count, high, i, a;
    /* The ROM clears its result scratch BEFORE reading either operand.
       Preserve that order even when an input aliases the scratch. */
    for (i = 0u; i < 4u; ++i)
        guest_write((c6502_u16)(output + i), 0u);
    count_address = get16(0x23u);
    high = guest_read((c6502_u16)(count_address + 3u));
    high |= guest_read((c6502_u16)(count_address + 2u));
    high |= guest_read((c6502_u16)(count_address + 1u));
    r[5] = 0u;
    if (high) {
        a = high;
        r[6] = 1u;
    } else {
        count = guest_read(count_address);
        a = count;
        r[6] = 0u;
        if (count < 32u) {
            c6502_u16 source = get16(0x20u);
            for (i = 0u; i < 4u; ++i) {
                a = guest_read((c6502_u16)(source + i));
                guest_write((c6502_u16)(output + i), (c6502_u8)a);
            }
            r[6] = 11u;
            if (!count) {
                /* CPX #0; RTS: the operand pointer is NOT redirected. */
                r[4] = a;
                r[9] |= C6502_FLAG_C;
                set_nz(r, 0u);
                return;
            }
            value = guest_get32(output);
            value = right ? value >> count : value << count;
            guest_put32(output, value);
            a = right ? (c6502_u8)value : (c6502_u8)(value >> 24);
            r[6] = right ? 8u : 11u;
        }
    }
    /* $D596 redirects $20 to temp_store+8, retaining A through PHA/PLA.
       Its 16-bit addition sets C/V; PLA supplies the final N/Z. Counts
       >=32 (including a nonzero upper byte) produce zero, never modulo 32. */
    put16(0x20u, output);
    r[9] = (r[9] & ~(C6502_FLAG_C | C6502_FLAG_V)) |
        ((c6502_u32)base + 8u > 0xffffu ? C6502_FLAG_C : 0u) |
        (base >= 0x7ff8u && base <= 0x7fffu ? C6502_FLAG_V : 0u);
    r[4] = a;
    set_nz(r, (c6502_u8)a);
}
