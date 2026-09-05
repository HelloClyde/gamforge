#include "gam4980_types.h"

/*
 * The freestanding KF2 has no compiler runtime library.  S1C33 lowers the
 * few variable 32-bit divisions in the core to these standard ABI helpers.
 */
static u32 divide_unsigned(u32 dividend, u32 divisor, u32 *remainder)
{
    u32 quotient = 0;
    u32 bit = 1;

    if (!divisor) {
        if (remainder)
            *remainder = dividend;
        return 0;
    }
    while (divisor < dividend && !(divisor & 0x80000000u)) {
        divisor <<= 1;
        bit <<= 1;
    }
    while (bit) {
        if (dividend >= divisor) {
            dividend -= divisor;
            quotient |= bit;
        }
        divisor >>= 1;
        bit >>= 1;
    }
    if (remainder)
        *remainder = dividend;
    return quotient;
}

u32 __udivsi3(u32 dividend, u32 divisor)
{
    return divide_unsigned(dividend, divisor, 0);
}

u32 __umodsi3(u32 dividend, u32 divisor)
{
    u32 remainder;

    (void)divide_unsigned(dividend, divisor, &remainder);
    return remainder;
}

s32 __divsi3(s32 dividend, s32 divisor)
{
    int negative = (dividend < 0) != (divisor < 0);
    u32 left = dividend < 0 ? 0u - (u32)dividend : (u32)dividend;
    u32 right = divisor < 0 ? 0u - (u32)divisor : (u32)divisor;
    u32 quotient = divide_unsigned(left, right, 0);

    return negative ? (s32)(0u - quotient) : (s32)quotient;
}

s32 __modsi3(s32 dividend, s32 divisor)
{
    int negative = dividend < 0;
    u32 left = negative ? 0u - (u32)dividend : (u32)dividend;
    u32 right = divisor < 0 ? 0u - (u32)divisor : (u32)divisor;
    u32 remainder;

    (void)divide_unsigned(left, right, &remainder);
    return negative ? (s32)(0u - remainder) : (s32)remainder;
}
