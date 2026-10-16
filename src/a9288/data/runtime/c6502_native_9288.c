#include "Dsys.h"
#include "CRTL/malloc.h"
#include "c6502_native_runtime.h"
#include "c6502_native_exit.h"
#include "c6502_native_host.h"

#ifndef NATIVE_TITLE
#define NATIVE_TITLE "GAM NATIVE"
#endif

/* DestroyMainWindow leaves queue cleanup to App_Main. Remember a close
   delivered by the release barrier: its Quit may already be consumed. */
static c6502_u8 native_window_closed;
#ifdef C6502_TARGET_9288T
static c6502_u8 native_game_active;
#endif

static T_WORD native_window_proc(T_GUI_HWND window, T_WORD message,
    T_GUI_WPARAM wparam, T_GUI_LPARAM lparam)
{
#ifdef C6502_TARGET_9288T
    (void)c6502_native_t_key_message(message, wparam, lparam);
#endif
#ifdef C6502_TARGET_9288S
    if (message == MSG_LBUTTONDOWN || message == MSG_LBUTTONDBLCLK || message == MSG_LBUTTONUP ||
        message == MSG_MOUSEMOVE) {
        c6502_native_pointer(message, lparam);
        /* Preserve firmware capture/release, essential for the next tap. */
        return fnGUI_DefaultMainWinProc(window, message, wparam, lparam);
    }
#endif
    /* After a resource failure, let the host acknowledge repaint requests
       from its modal dialog. The direct-LCD game paint path intentionally
       does not paint a host client DC and would keep those requests pending. */
    if (message == MSG_ERASEBKGND && !c6502_native_resource_error()) return 0;
    if (message == MSG_PAINT && c6502_native_state.window == window &&
        !c6502_native_resource_error()) {
#if defined(C6502_TARGET_9288S) || defined(C6502_TARGET_9288T)
        T_GUI_HDC dc = fnGUI_BeginPaint(window);
        fnGUI_EndPaint(window, dc);
#endif
        c6502_native_invalidate_screen();
        return 0;
    }
    if (message == MSG_CLOSE) {
#ifdef C6502_TARGET_9288T
        /* A GUI callback is still on a native C bridge stack. Ask that
           bridge to unwind to App_Main before freeing host resources. */
        if (native_game_active) {
            c6502_native_host_stop_requested = 1u;
            return 0;
        }
#endif
        if (native_window_closed) return 0;
        native_window_closed = 1u;
        c6502_native_exit_checkpoint(NATIVE_EXIT_DESTROY_WINDOW, 0u, (c6502_u32)window);
        fnGUI_DestroyMainWindow(window);
        c6502_native_exit_checkpoint(NATIVE_EXIT_DESTROY_WINDOW, 1u, (c6502_u32)window);
        c6502_native_exit_checkpoint(NATIVE_EXIT_POST_QUIT, 0u, (c6502_u32)window);
#ifdef C6502_TARGET_9288T
        if (!c6502_native_t_quit_received)
#endif
            fnGUI_PostQuitMessage(window);
        c6502_native_exit_checkpoint(NATIVE_EXIT_POST_QUIT, 1u, (c6502_u32)window);
        return 0;
    }
    return fnGUI_DefaultMainWinProc(window, message, wparam, lparam);
}

T_WORD App_Main(void)
{
    c6502_u8 *desktop;
    c6502_u32 index;
    T_GUI_HWND launcher = fnGUI_GetActiveWindow();
    T_GUI_HWND focus = fnGUI_GetFocus();
    T_GUI_HWND window;
    T_GUI_MainWinCreate info;
    T_GUI_Msg message;
#ifdef C6502_TARGET_9288T
    int got_paint = 0;
#endif
    volatile c6502_u8 *lcd = (volatile c6502_u8 *)0x003c0000u;
    if (!c6502_native_prepare()) {
        const char *error = c6502_native_resource_error();
        if (error) fnGUI_MessageBox(HWND_DESKTOP, (const T_BYTE *)error,
                                   (const T_BYTE *)error, MB_OK);
        return 0;
    }
    desktop = (c6502_u8 *)malloc(C6502_HOST_FRAME_BYTES);
    if (!desktop) {
        c6502_native_release();
        return 0;
    }
    for (index = 0u; index < C6502_HOST_FRAME_BYTES; ++index)
        desktop[index] = lcd[index];
    for (index = 0; index < sizeof(info); ++index)
        ((c6502_u8 *)&info)[index] = 0;
    info.dwStyle = WS_VISIBLE;
#ifdef C6502_TARGET_9288S
    info.dwExStyle = WS_EX_TOPMOST;
#endif
#ifndef C6502_TARGET_9288S
    info.dwStyle |= WS_CAPTION;
#endif
    info.spCaption = (const T_BYTE *)NATIVE_TITLE;
    info.MainWindowProc = native_window_proc;
    info.rx = C6502_HOST_WIDTH; info.by = C6502_HOST_HEIGHT;
    info.iBkColor = COLOR_LIGHTWHITE;
    info.hHosting = HWND_DESKTOP;
    native_window_closed = 0u;
#ifdef C6502_TARGET_9288T
    native_game_active = 0u;
    c6502_native_t_input_reset();
#endif
    window = fnGUI_CreateMainWindow(&info);
    if (!window || window == HWND_INVALID) {
        c6502_native_release(); free(desktop); return -1;
    }
    (void)fnGUI_ShowWindow(window, SW_SHOWNORMAL);
    while (fnGUI_GetMessage(&message, window)) {
        fnGUI_TranslateMessage(&message);
        fnGUI_DispatchMessage(&message);
        if (message.message == MSG_PAINT) {
#ifdef C6502_TARGET_9288T
            got_paint = 1;
#endif
            break;
        }
    }
#ifdef C6502_TARGET_9288T
    if (!got_paint && !native_window_closed) c6502_native_t_quit_received = 1u;
    if (c6502_native_t_quit_received) goto release_game;
#endif
    if (native_window_closed) goto release_game;
    (void)fnGUI_SetActiveWindow(window);
    (void)fnGUI_SetFocus(window);
    c6502_native_state.window = window;
#ifdef C6502_TARGET_9288S
    /* Launch cleanup can run late and disable FPT6 or restore desktop
       focus. Settle before the final re-arm, as in the verified S port.
       Timer #2 ONLY bounds IAL collection, never drives guest execution. */
    tpDL_GUITable->EnableKeyBoard();
    (void)fnGUI_SetTimer(window, 2, 1);
    (void)tpDL_ROS33Table->ros33_dly_tsk(10);
    fnGUI_ReleaseCapture();
    *(volatile c6502_u8 *)0x00040287u = 0x10u;
    *(volatile c6502_u8 *)0x00040277u |= 0x10u;
    (void)fnGUI_SetActiveWindow(window);
    (void)fnGUI_SetFocus(window);
#endif
    /* CTM drives gameplay. T uses GUI keyboard input; original 9288 keeps
       GPIO polling, while S also collects calibrated touch messages. */
    /* Only used to rasterise glyphs into our explicit VirtualScr. The
       captioned client DC adds its screen origin to glyph coordinates. */
    c6502_native_state.hdc = fnGUI_GetDC(HWND_DESKTOP);
#ifdef C6502_TARGET_9288T
    if (!c6502_native_t_host_begin()) {
        static const T_BYTE error[] = "Unsupported 9288T power API";
        fnGUI_MessageBox(window, error, error, MB_OK);
        if (native_window_closed) goto release_game;
        (void)fnGUI_SetActiveWindow(window);
        (void)fnGUI_SetFocus(window);
        goto finish_input;
    }
    /* GUI timer #2 bounds IAL collection; it is not the A-series timer.
       Drain launch keys before accepting gameplay input. */
    if (!fnGUI_SetTimer(window, 2, 1)) {
        static const T_BYTE error[] = "9288T input timer failed";
        fnGUI_MessageBox(window, error, error, MB_OK);
        c6502_native_t_host_end();
        goto finish_input;
    }
    (void)fnGUI_SetTimer(window, 1, 1);
    c6502_native_finish_input();
    (void)fnGUI_KillTimer(window, 1);
    if (native_window_closed || c6502_native_t_quit_received) {
        (void)fnGUI_KillTimer(window, 2);
        c6502_native_t_host_end();
        goto release_game;
    }
    native_game_active = 1u;
#endif
    c6502_native_present();
    c6502_native_perf_begin();
    c6502_native_enter(c6502_entry_regs);
#ifdef C6502_TARGET_9288T
    native_game_active = 0u;
    (void)fnGUI_KillTimer(window, 2);
#endif
    c6502_native_exit_begin();
#ifdef C6502_TARGET_9288T
    c6502_native_exit_checkpoint(NATIVE_EXIT_T_HOST_RESTORE, 0u, 0u);
    c6502_native_t_host_end();
    c6502_native_exit_checkpoint(NATIVE_EXIT_T_HOST_RESTORE, 1u, 0u);
#endif
#ifdef C6502_TARGET_9288S
    (void)fnGUI_KillTimer(window, 2);
#endif
    c6502_native_exit_checkpoint(NATIVE_EXIT_PERF, 0u, 0u);
    c6502_native_perf_end();
    c6502_native_exit_checkpoint(NATIVE_EXIT_PERF, 1u, 0u);
#ifdef C6502_TARGET_9288T
finish_input:
#endif
    /* Rejoin the host message framework only after guest execution ends.
       Timer #1 drives the release/host-input handoff, not the game. */
    c6502_native_exit_checkpoint(NATIVE_EXIT_TIMER_START, 0u, (c6502_u32)window);
    (void)fnGUI_SetTimer(window, 1, 1);
    c6502_native_exit_checkpoint(NATIVE_EXIT_TIMER_START, 1u, (c6502_u32)window);
    /* The game may return while Confirm is still physically held. Keep
       our focus until release; otherwise the desktop can see that hold. */
    c6502_native_exit_checkpoint(NATIVE_EXIT_INPUT_RELEASE, 0u, (c6502_u32)window);
    c6502_native_finish_input();
    c6502_native_exit_checkpoint(NATIVE_EXIT_INPUT_RELEASE, 1u, native_window_closed);
    c6502_native_exit_checkpoint(NATIVE_EXIT_TIMER_STOP, 0u, (c6502_u32)window);
    (void)fnGUI_KillTimer(window, 1);
    c6502_native_exit_checkpoint(NATIVE_EXIT_TIMER_STOP, 1u, (c6502_u32)window);
    /* Return the keyboard to the firmware BEFORE entering a modal dialog.
       Also put the short error in its caption: some firmware revisions do
       not render MessageBox body text reliably after direct LCD drawing. */
    /* An already closed window cannot parent another modal dialog. */
    if (c6502_native_resource_error() && !native_window_closed) {
        c6502_native_exit_checkpoint(NATIVE_EXIT_ERROR_DIALOG, 0u, (c6502_u32)window);
        fnGUI_MessageBox(window, (const T_BYTE *)c6502_native_resource_error(),
                         (const T_BYTE *)c6502_native_resource_error(), MB_OK);
        /* Consume the dialog acknowledgement's release before returning
           focus to the launcher, just as for the game's own exit key. */
        (void)fnGUI_SetActiveWindow(window);
        (void)fnGUI_SetFocus(window);
        (void)fnGUI_SetTimer(window, 1, 1);
        c6502_native_finish_input();
        (void)fnGUI_KillTimer(window, 1);
        c6502_native_exit_checkpoint(NATIVE_EXIT_ERROR_DIALOG, 1u, native_window_closed);
    }
release_game:
    if (c6502_native_state.hdc) {
        c6502_native_exit_checkpoint(NATIVE_EXIT_RELEASE_DC, 0u,
                                     (c6502_u32)c6502_native_state.hdc);
        fnGUI_ReleaseDC(c6502_native_state.hdc);
        c6502_native_state.hdc = 0;
        c6502_native_exit_checkpoint(NATIVE_EXIT_RELEASE_DC, 1u, 0u);
    }
    c6502_native_state.window = 0;
    c6502_native_exit_checkpoint(NATIVE_EXIT_RELEASE_GAME, 0u, 0u);
    c6502_native_release();
    c6502_native_exit_checkpoint(NATIVE_EXIT_RELEASE_GAME, 1u, 0u);
    /* Discard only this app's queued gameplay keys, never loader messages.
       Follow the SDK's close -> filtered Quit -> cleanup lifecycle. */
    if (!native_window_closed) {
        c6502_native_exit_checkpoint(NATIVE_EXIT_CLOSE_WINDOW, 0u, (c6502_u32)window);
        fnGUI_ThrowAwayMessages(window);
#ifdef C6502_TARGET_9288T
        if (c6502_native_t_quit_received) {
            /* The collector already consumed Quit. Do not wait for a
               second one or post another global termination event. */
            native_window_proc(window, MSG_CLOSE, 0, 0);
        } else
#endif
            fnGUI_PostMessage(window, MSG_CLOSE, 0, 0);
        c6502_native_exit_checkpoint(NATIVE_EXIT_CLOSE_WINDOW, 1u, (c6502_u32)window);
        c6502_native_exit_checkpoint(NATIVE_EXIT_DRAIN_WINDOW, 0u, (c6502_u32)window);
#ifdef C6502_TARGET_9288T
        if (!c6502_native_t_quit_received)
#endif
        while (fnGUI_GetMessage(&message, window)) {
            native_dispatch_teardown(&message);
        }
        c6502_native_exit_checkpoint(NATIVE_EXIT_DRAIN_WINDOW, 1u, native_window_closed);
    }
    c6502_native_exit_checkpoint(NATIVE_EXIT_CLEANUP_WINDOW, 0u, (c6502_u32)window);
    fnGUI_ThrowAwayMessages(window);
    fnGUI_MainWindowCleanup(window);
    c6502_native_exit_checkpoint(NATIVE_EXIT_CLEANUP_WINDOW, 1u, (c6502_u32)window);
#ifndef C6502_TARGET_9288T
    /* The two-launcher-boundary workaround belongs to the verified 9288
       lifecycle. T's official program cleans its own window and returns;
       never dispatch loader/desktop messages on the outgoing T app stack. */
    c6502_native_exit_checkpoint(NATIVE_EXIT_RESTORE_LAUNCHER, 0u, (c6502_u32)launcher);
    {
        T_GUI_HWND active = fnGUI_GetActiveWindow();
        if (active && active != HWND_INVALID && active != window && fnGUI_IsWindow(active))
            launcher = active;
    }
    if (launcher && launcher != HWND_INVALID && fnGUI_IsWindow(launcher)) {
        c6502_u32 round;
        (void)fnGUI_SetActiveWindow(launcher);
        if (!focus || focus == HWND_INVALID || !fnGUI_IsWindow(focus)) focus = launcher;
        (void)fnGUI_SetFocus(focus);
        /* V1.5 can submit a late white DC page after window cleanup.
           Use the verified launcher-only two-boundary restore protocol
           from 9288_sdk.md; never consume the loader's global Quit. */
        for (round = 0u; round < 2u; ++round) {
            c6502_u32 pending = 32u, polls = 262144u;
#ifdef C6502_TARGET_9288S
            if (!fnGUI_HavePendingMessage(launcher)) break;
#endif
            if (!fnGUI_GetMessage(&message, launcher)) break;
            native_dispatch_teardown(&message);
            while (pending-- && fnGUI_HavePendingMessage(launcher)) {
                if (!fnGUI_GetMessage(&message, launcher)) break;
                native_dispatch_teardown(&message);
            }
            while (polls--) {
                c6502_u32 channel, busy = 0u;
                for (channel = 0; channel < 4u; ++channel)
                    busy |= *(volatile c6502_u8 *)(0x0004822cu + channel * 16u) & 1u;
                if (!busy) break;
            }
            for (index = 0u; index < C6502_HOST_FRAME_BYTES; ++index)
                lcd[index] = desktop[index];
        }
    }
    c6502_native_exit_checkpoint(NATIVE_EXIT_RESTORE_LAUNCHER, 1u, (c6502_u32)launcher);
#endif
    c6502_native_exit_checkpoint(NATIVE_EXIT_RESTORE_FRAME, 0u, C6502_HOST_FRAME_BYTES);
    for (index = 0u; index < C6502_HOST_FRAME_BYTES; ++index)
        lcd[index] = desktop[index];
    c6502_native_exit_checkpoint(NATIVE_EXIT_RESTORE_FRAME, 1u, C6502_HOST_FRAME_BYTES);
    c6502_native_exit_checkpoint(NATIVE_EXIT_FREE_DESKTOP, 0u, (c6502_u32)desktop);
    free(desktop);
    c6502_native_exit_checkpoint(NATIVE_EXIT_FREE_DESKTOP, 1u, 0u);
    c6502_native_exit_complete();
    return 0;
}
