#ifndef C6502_NATIVE_9288T_HOST_H
#define C6502_NATIVE_9288T_HOST_H

/* Official 9288T Fumo calls GUI+0x64c, NOT this SDK's +0x6b8.
 * The supported firmware implements it as a ten-byte idle-counter reset.
 * Resolve through the live table and verify that body before calling it;
 * never assume that a different firmware shares its table layout. */
#define C6502_T_AUTOCLOSE_GUI_OFFSET 0x64cu
#define C6502_T_KEEPALIVE_TICKS 128u /* 500 ms, independent of guest Timer */
typedef void (*NativeTResetIdle)(void);
typedef int (*NativeTTaskService)(int);
typedef struct NativeTHostSession {
    NativeTResetIdle reset_idle;
    NativeTTaskService resume_task;
    c6502_u32 last_reset, resets, max_gap;
    int suspend_result, resume_result;
    c6502_u8 verified, active, task_owned, task_resumed;
} NativeTHostSession;
static NativeTHostSession c6502_t_host;

static int native_t_idle_reset_body(const c6502_u8 *code)
{
    static const c6502_u8 expected[10] = {
        0x04u, 0x6cu, 0x77u, 0xd2u, 0xfcu, 0xd7u, 0xf4u, 0x3cu, 0x40u, 0x06u
    };
    c6502_u32 i;
    for (i = 0u; i < sizeof(expected); ++i)
        if (code[i] != expected[i]) return 0;
    return 1;
}

static void native_t_host_pulse(c6502_u32 now)
{
    c6502_u32 gap;
    if (!c6502_t_host.active) return;
    gap = now - c6502_t_host.last_reset;
    if (gap < C6502_T_KEEPALIVE_TICKS || (gap & 0x80000000u)) return;
    c6502_t_host.reset_idle();
    c6502_t_host.last_reset = now;
    ++c6502_t_host.resets;
    if (gap > c6502_t_host.max_gap) c6502_t_host.max_gap = gap;
}

static int native_t_host_start(NativeTResetIdle reset,
    NativeTTaskService suspend, NativeTTaskService resume, c6502_u32 now)
{
    if (c6502_t_host.active) return 1; /* No double suspend. */
    c6502_t_host.verified = reset != 0;
    c6502_t_host.resets = c6502_t_host.max_gap = 0u;
    c6502_t_host.task_owned = c6502_t_host.task_resumed = 0u;
    c6502_t_host.suspend_result = c6502_t_host.resume_result = -1;
    if (!reset || !suspend || !resume) return 0;
    c6502_t_host.reset_idle = reset;
    c6502_t_host.resume_task = resume;
    /* Official GUI+0x6f4/0x6f8 wrap ROS33 sus_tsk/rsm_tsk(3).
     * Use the correctly declared OS table, not another late GUI offset.
     * Only undo a suspend that this invocation successfully acquired. */
    c6502_t_host.suspend_result = suspend(3);
    c6502_t_host.task_owned = c6502_t_host.suspend_result == 0;
    c6502_t_host.last_reset = now;
    c6502_t_host.active = 1u;
    reset();
    c6502_t_host.resets = 1u;
    return 1;
}

static void native_t_host_stop(void)
{
    if (!c6502_t_host.active) return;
    /* Leave a fresh system idle interval before handing input back. */
    c6502_t_host.reset_idle();
    ++c6502_t_host.resets;
    c6502_t_host.active = 0u;
    if (c6502_t_host.task_owned) {
        c6502_t_host.resume_result = c6502_t_host.resume_task(3);
        c6502_t_host.task_resumed = c6502_t_host.resume_result == 0;
        c6502_t_host.task_owned = 0u;
    }
}

#endif
