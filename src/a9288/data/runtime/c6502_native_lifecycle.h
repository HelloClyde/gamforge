#ifndef C6502_NATIVE_LIFECYCLE_H
#define C6502_NATIVE_LIFECYCLE_H

/* Stable IDs in exit snapshots; separate from guest bridge IDs. */
enum {
    NATIVE_EXIT_PERF = 1,
    NATIVE_EXIT_TIMER_START,
    NATIVE_EXIT_INPUT_RELEASE,
    NATIVE_EXIT_TIMER_STOP,
    NATIVE_EXIT_ERROR_DIALOG,
    NATIVE_EXIT_RELEASE_DC,
    NATIVE_EXIT_RELEASE_GAME,
    NATIVE_EXIT_CLOSE_WINDOW,
    NATIVE_EXIT_DRAIN_WINDOW,
    NATIVE_EXIT_CLEANUP_WINDOW,
    NATIVE_EXIT_RESTORE_LAUNCHER,
    NATIVE_EXIT_RESTORE_FRAME,
    NATIVE_EXIT_FREE_DESKTOP,
    NATIVE_EXIT_RETURN,
    NATIVE_EXIT_DESTROY_WINDOW,
    NATIVE_EXIT_POST_QUIT
};

#ifdef C6502_CRASH_TRACE
void c6502_native_exit_begin(void);
void c6502_native_exit_checkpoint(c6502_u32 stage, c6502_u32 after, c6502_u32 detail);
void c6502_native_exit_complete(void);
#else
#define c6502_native_exit_begin() ((void)0)
#define c6502_native_exit_checkpoint(stage, after, detail) ((void)0)
#define c6502_native_exit_complete() ((void)0)
#endif

#endif
