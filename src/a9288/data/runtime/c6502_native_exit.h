/* During teardown only: never replay gameplay keys to the launcher.
   Keep Timer/paint/lifecycle traffic and the HWND filter unchanged. */
#ifndef C6502_NATIVE_EXIT_H
#define C6502_NATIVE_EXIT_H
static int native_is_key_message(T_WORD message)
{
    /* These are the three keyboard families in app_env_9288 guiWindow.h.
       Desktop/system variants can otherwise escape the ordinary-key filter
       and be translated again when the launcher regains focus. KEYOFF is
       included, but lifecycle, mouse, timer and paint messages are not. */
    return (message >= MSG_FIRSTKEYMSG && message <= MSG_LASTKEYMSG) ||
        (message >= MSG_DT_KEYDOWN && message <= MSG_DT_SYSKEYUP) ||
        message == MSG_DT_KEYOFF;
}

static void native_dispatch_teardown(T_GUI_Msg *message)
{
#ifdef C6502_TARGET_9288T
    /* Keep host power working even in the key-release barrier. CHAR has
       ASCII payload, not a scan code: do not mistake letter X for F12. */
    if ((message->message == MSG_KEYDOWN || message->message == MSG_KEYUP ||
         message->message == MSG_SYSKEYDOWN || message->message == MSG_SYSKEYUP ||
         message->message == MSG_DT_KEYDOWN || message->message == MSG_DT_KEYUP ||
         message->message == MSG_DT_SYSKEYDOWN || message->message == MSG_DT_SYSKEYUP) &&
        message->wParam == SCANCODE_POWER_OFF_ON) {
        fnGUI_DispatchMessage(message);
        return;
    }
#endif
    if (native_is_key_message(message->message)) return;
    fnGUI_TranslateMessage(message);
    fnGUI_DispatchMessage(message);
}
#endif
