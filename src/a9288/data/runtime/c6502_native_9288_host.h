#ifndef C6502_NATIVE_9288_HOST_H
#define C6502_NATIVE_9288_HOST_H

/* Independently verified in 9288 V1.5: GUI+0x64c resets the idle counter.
 * The SDK's ResetAutoCloseTimer (+0x6b8) is a DIFFERENT OS service here.
 * Resolve through the live table and check the complete leaf before use.
 * No direct writes to firmware globals, setting changes, or T task calls. */
#define C6502_9288_IDLE_GUI_OFFSET 0x64cu
#define C6502_9288_KEEPALIVE_TICKS 128u
#define C6502_9288_PUMP_TICKS 8u
typedef void (*Native9288ResetIdle)(void);
typedef struct Native9288HostSession {
    Native9288ResetIdle reset_idle;
    c6502_u32 last_reset, resets, max_gap;
    c6502_u8 verified, active;
} Native9288HostSession;
static Native9288HostSession c6502_9288_host;

static int native_9288_idle_body(const c6502_u8 *code)
{
    static const c6502_u8 expected[10] = {
        0x04u,0x6cu,0x77u,0xd2u,0x54u,0xcfu,0xf4u,0x3cu,0x40u,0x06u
    };
    c6502_u32 i;
    for (i=0u; i<sizeof(expected); ++i)
        if (code[i] != expected[i]) return 0;
    return 1;
}

static int native_9288_host_start(Native9288ResetIdle reset, c6502_u32 now)
{
    if (c6502_9288_host.active) return 1;
    c6502_9288_host.verified = reset != 0;
    c6502_9288_host.resets = c6502_9288_host.max_gap = 0u;
    if (!reset) return 0;
    c6502_9288_host.reset_idle = reset;
    c6502_9288_host.last_reset = now;
    c6502_9288_host.active = 1u;
    reset();
    c6502_9288_host.resets = 1u;
    return 1;
}

static void native_9288_host_pulse(c6502_u32 now)
{
    c6502_u32 gap = now - c6502_9288_host.last_reset;
    if (!c6502_9288_host.active || gap < C6502_9288_KEEPALIVE_TICKS ||
        (gap & 0x80000000u)) return;
    c6502_9288_host.reset_idle();
    c6502_9288_host.last_reset = now;
    ++c6502_9288_host.resets;
    if (gap > c6502_9288_host.max_gap) c6502_9288_host.max_gap = gap;
}

static void native_9288_host_stop(void)
{
    if (!c6502_9288_host.active) return;
    c6502_9288_host.reset_idle();
    ++c6502_9288_host.resets;
    c6502_9288_host.active = 0u;
}

#endif
