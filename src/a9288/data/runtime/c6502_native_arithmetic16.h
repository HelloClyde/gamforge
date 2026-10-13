/* C6502 canonical two-byte arithmetic. The final flags are those of the
   HIGH byte ADC/SBC, not a host 16-bit comparison. Read the high operands
   after storing the low result: overlapping zero-page pairs are legal. */
static c6502_u8 semantic_byte(c6502_u32 *r, c6502_u32 address)
{
    address = (c6502_u8)address;
    if (address == 0x28u) return (c6502_u8)r[10];
    if (address == 0x29u) return (c6502_u8)(r[10] >> 8);
    return c6502_native_state.ram[address];
}

static void semantic_store_byte(c6502_u32 *r, c6502_u32 address, c6502_u8 value)
{
    address = (c6502_u8)address;
    if (address == 0x28u) r[10] = (r[10] & 0xff00u) | value;
    else if (address == 0x29u) r[10] = (r[10] & 0xffu) | ((c6502_u32)value << 8);
    else c6502_native_state.ram[address] = value;
}

static void semantic_arithmetic16(c6502_u32 *r, int subtract,
    int immediate, int preserve)
{
    c6502_u32 old_status = r[9], old_nz = r[8];
    c6502_u32 source = r[11], destination = immediate ? r[12] : r[13];
    c6502_u32 operand = r[13], carry = subtract ? 1u : 0u, i;
    for (i = 0u; i < 2u; ++i) {
        c6502_u32 left = semantic_byte(r, source + i);
        c6502_u32 right = immediate ? (operand >> (i * 8u)) & 0xffu :
            semantic_byte(r, r[12] + i);
        c6502_u32 value = subtract ? left - right - (1u - carry) :
            left + right + carry;
        carry = subtract ? left >= right + (1u - carry) : value > 255u;
        r[9] = (r[9] & ~(C6502_FLAG_C | C6502_FLAG_V)) | carry |
            (((subtract ? left ^ right : ~(left ^ right)) &
              (left ^ value) & 0x80u) ? C6502_FLAG_V : 0u);
        r[4] = (c6502_u8)value;
        semantic_store_byte(r, destination + i, (c6502_u8)value);
    }
    if (preserve) { r[9] = old_status; r[8] = old_nz; }
    else set_nz(r, (c6502_u8)r[4]);
}
