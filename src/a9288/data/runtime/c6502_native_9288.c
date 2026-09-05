#include "Dsys.h"
#include "CRTL/malloc.h"
#include "c6502_native_runtime.h"

#ifndef NATIVE_TITLE
#define NATIVE_TITLE "GAM NATIVE"
#endif

static T_WORD native_window_proc(T_GUI_HWND window, T_WORD message,
    T_GUI_WPARAM wparam, T_GUI_LPARAM lparam)
{
    if (message == MSG_ERASEBKGND) return 0;
    if (message == MSG_PAINT && c6502_native_state.window == window) {
        c6502_native_invalidate_screen();
        return 0;
    }
    if (message == MSG_CLOSE) {
        fnGUI_DestroyMainWindow(window);
        fnGUI_PostQuitMessage(window);
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
    volatile c6502_u8 *lcd = (volatile c6502_u8 *)0x003c0000u;
    if (!c6502_native_prepare())
        return 0;
    desktop = (c6502_u8 *)malloc(19200u);
    if (!desktop) {
        c6502_native_release();
        return 0;
    }
    for (index = 0u; index < 19200u; ++index)
        desktop[index] = lcd[index];
    for (index = 0; index < sizeof(info); ++index)
        ((c6502_u8 *)&info)[index] = 0;
    info.dwStyle = WS_VISIBLE | WS_CAPTION;
    info.spCaption = (const T_BYTE *)NATIVE_TITLE;
    info.MainWindowProc = native_window_proc;
    info.rx = 320; info.by = 240;
    info.iBkColor = COLOR_LIGHTWHITE;
    info.hHosting = HWND_DESKTOP;
    window = fnGUI_CreateMainWindow(&info);
    if (!window) { c6502_native_release(); free(desktop); return -1; }
    (void)fnGUI_ShowWindow(window, SW_SHOWNORMAL);
    while (fnGUI_GetMessage(&message, window)) {
        fnGUI_TranslateMessage(&message);
        fnGUI_DispatchMessage(&message);
        if (message.message == MSG_PAINT) break;
    }
    (void)fnGUI_SetActiveWindow(window);
    (void)fnGUI_SetFocus(window);
    c6502_native_state.window = window;
    /* 9288 speed is a ~25 ms tick count, not milliseconds. */
    (void)fnGUI_SetTimer(window, 1, 1);
    /* Only used to rasterise glyphs into our explicit VirtualScr. The
       captioned client DC adds its screen origin to glyph coordinates. */
    c6502_native_state.hdc = fnGUI_GetDC(HWND_DESKTOP);
    c6502_native_present();
    c6502_native_perf_begin();
    c6502_native_enter(c6502_entry_regs);
    c6502_native_perf_end();
    (void)fnGUI_KillTimer(window, 1);
    if (c6502_native_state.hdc) {
        fnGUI_ReleaseDC(c6502_native_state.hdc);
        c6502_native_state.hdc = 0;
    }
    c6502_native_state.window = 0;
    c6502_native_release();
    /* Discard only this app's queued gameplay keys, never loader messages.
       Follow the SDK's close -> filtered Quit -> cleanup lifecycle. */
    fnGUI_ThrowAwayMessages(window);
    fnGUI_PostMessage(window, MSG_CLOSE, 0, 0);
    while (fnGUI_GetMessage(&message, window)) {
        fnGUI_TranslateMessage(&message);
        fnGUI_DispatchMessage(&message);
    }
    fnGUI_ThrowAwayMessages(window);
    fnGUI_MainWindowCleanup(window);
    {
        T_GUI_HWND active = fnGUI_GetActiveWindow();
        if (active && active != window && fnGUI_IsWindow(active))
            launcher = active;
    }
    if (launcher && fnGUI_IsWindow(launcher)) {
        c6502_u32 round;
        (void)fnGUI_SetActiveWindow(launcher);
        if (!focus || !fnGUI_IsWindow(focus)) focus = launcher;
        (void)fnGUI_SetFocus(focus);
        /* V1.5 can submit a late white DC page after window cleanup.
           Use the verified launcher-only two-boundary restore protocol
           from 9288_sdk.md; never consume the loader's global Quit. */
        for (round = 0u; round < 2u; ++round) {
            c6502_u32 pending = 32u, polls = 262144u;
            if (!fnGUI_GetMessage(&message, launcher)) break;
            fnGUI_TranslateMessage(&message);
            fnGUI_DispatchMessage(&message);
            while (pending-- && fnGUI_HavePendingMessage(launcher)) {
                if (!fnGUI_GetMessage(&message, launcher)) break;
                fnGUI_TranslateMessage(&message);
                fnGUI_DispatchMessage(&message);
            }
            while (polls--) {
                c6502_u32 channel, busy = 0u;
                for (channel = 0; channel < 4u; ++channel)
                    busy |= *(volatile c6502_u8 *)(0x0004822cu + channel * 16u) & 1u;
                if (!busy) break;
            }
            for (index = 0u; index < 19200u; ++index)
                lcd[index] = desktop[index];
        }
    }
    for (index = 0u; index < 19200u; ++index)
        lcd[index] = desktop[index];
    free(desktop);
    return 0;
}
