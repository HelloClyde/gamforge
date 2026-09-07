#ifndef C6502_NATIVE_CLOCK_H
#define C6502_NATIVE_CLOCK_H

/* Serial-number arithmetic, not a numeric max: a normal 32-bit wrap is
   forward. Calls must be less than 2^31 / 256 seconds apart (~97 days).
   Gameplay does not support setting the hardware calendar backwards. */
typedef struct NativeClockDiagnostics {
    c6502_u32 backwards, max_backstep, snapshot_retries, exhausted, wraps;
    c6502_u32 trace[8][4]; /* sequence, raw, previous, backward ticks */
} NativeClockDiagnostics;
static NativeClockDiagnostics c6502_clock_diagnostics;
static c6502_u32 c6502_clock_previous;
static c6502_u8 c6502_clock_initialized;

static int native_clock_accept(c6502_u32 candidate)
{
    c6502_u32 delta = candidate - c6502_clock_previous;
    if (c6502_clock_initialized && (delta & 0x80000000u)) {
        NativeClockDiagnostics *d = &c6502_clock_diagnostics;
        c6502_u32 back = c6502_clock_previous - candidate;
        c6502_u32 *row = d->trace[d->backwards & 7u];
        row[0] = ++d->backwards;
        row[1] = candidate; row[2] = c6502_clock_previous; row[3] = back;
        if (back > d->max_backstep) d->max_backstep = back;
        return 0;
    }
    if (c6502_clock_initialized && candidate < c6502_clock_previous)
        ++c6502_clock_diagnostics.wraps;
    c6502_clock_previous = candidate;
    c6502_clock_initialized = 1u;
    return 1;
}

#endif
