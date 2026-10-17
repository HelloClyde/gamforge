#ifndef C6502_NATIVE_9288T_INPUT_H
#define C6502_NATIVE_9288T_INPUT_H

/* Official T games collect raw KEYDOWN/KEYUP through GetMessage and let
 * DefaultMainWinProc handle the power key. HavePendingMessage alone does
 * not collect hardware input. Host timer #2 bounds an idle GetMessage;
 * it NEVER advances the A-series timer or native game simulation. */
#define C6502_T_INPUT_PUMP_TICKS 8u
/* sdk9288t/include/c33L05.h: uc_KPORT_K6D, not the CTM time registers. */
#define C6502_T_SHIFT_DATA_ADDRESS 0x000402c4u
static c6502_u8 c6502_t_gui_held[16], c6502_t_gui_pumping;
static c6502_u8 c6502_t_gui_accept;
static c6502_u8 c6502_t_gui_shift;
static c6502_u32 c6502_t_gui_shift_edges;
static c6502_u32 c6502_t_gui_last_pump, c6502_t_gui_batches;
static c6502_u32 c6502_t_gui_messages, c6502_t_gui_power_messages;
static c6502_u32 c6502_t_gui_ignored_chars;
static c6502_u32 c6502_t_gui_trace[64][5], c6502_t_gui_trace_count;

static int native_t_gui_down(T_WORD message)
{
    return message == MSG_KEYDOWN || message == MSG_SYSKEYDOWN ||
        message == MSG_DT_KEYDOWN || message == MSG_DT_SYSKEYDOWN;
}

static int native_t_gui_up(T_WORD message)
{
    return message == MSG_KEYUP || message == MSG_SYSKEYUP ||
        message == MSG_DT_KEYUP || message == MSG_DT_SYSKEYUP;
}

static int native_t_direction(c6502_u8 code)
{
    return code == 0x35u || (code >= 0x37u && code <= 0x39u);
}

void c6502_native_t_input_reset(void)
{
    c6502_u32 i;
    for (i = 0u; i < sizeof(c6502_t_gui_held); ++i) c6502_t_gui_held[i] = 0u;
    c6502_t_gui_pumping = c6502_t_gui_accept = 0u;
    c6502_t_gui_shift = 0u;
    c6502_t_gui_shift_edges = 0u;
    c6502_t_gui_last_pump = c6502_t_gui_batches = 0u;
    c6502_t_gui_messages = c6502_t_gui_power_messages = c6502_t_gui_ignored_chars = 0u;
    c6502_t_gui_trace_count = 0u;
    c6502_native_host_stop_requested = c6502_native_t_quit_received = 0u;
    c6502_key_head = c6502_key_count = c6502_timer_key_deferred = 0u;
    c6502_key_repeat = 0xffu;
    c6502_key_repeating = c6502_key_initialized = 0u;
}

static void native_t_shift(int pressed)
{
    if (pressed && !c6502_t_gui_shift && c6502_input_active && c6502_t_gui_accept &&
        !c6502_native_host_stop_requested) {
        native_queue_key(0x28u, 0);
        ++c6502_t_gui_shift_edges;
    }
    c6502_t_gui_shift = (c6502_u8)(pressed != 0);
}

/* Return 1 for guest input, but the window procedure must still call the
 * firmware default procedure (as official T games do). Character-message
 * wParam is ASCII and must NOT be mapped a second time. */
int c6502_native_t_key_message(T_WORD message, T_GUI_WPARAM key, T_GUI_LPARAM flags)
{
    c6502_u8 code, bit, *held;
    c6502_u32 now;
    int down = native_t_gui_down(message), up = native_t_gui_up(message);
    /* Physical Help is MSG_HELP on the real T GUI. Official Fumo maps
       +0x7fd to scan 87. KEYUP still releases the shared held state. */
    if (message == MSG_HELP) { down = 1; key = SCANCODE_HELP; }
    /* Real T IAL sends MSG_HOTKEY (0x7fe) for Start/Translate/Longman/Exam,
       then ordinary KEYUP with the same scan. Reuse the held bit so a
       duplicate raw KEYDOWN cannot deliver a second guest action. Do not
       reinterpret unrelated host hotkeys (especially power) as game input. */
    if (message == MSG_HOTKEY &&
        (key == SCANCODE_START || (key >= 116u && key <= 118u))) down = 1;
    if (native_is_key_message(message) || message >= 0x7fdu) {
        c6502_u32 n = c6502_t_gui_trace_count++, *v;
        /* Preserve startup evidence as well as the most recent key messages. */
        v = c6502_t_gui_trace[n < 16u ? n : 16u + ((n - 16u) % 48u)];
        v[0] = native_clock(); v[1] = message; v[2] = key; v[3] = (c6502_u32)flags;
        v[4] = c6502_t_gui_accept;
    }
    if (message == MSG_DT_KEYOFF) {
        c6502_u32 i;
        for (i = 0u; i < sizeof(c6502_t_gui_held); ++i) c6502_t_gui_held[i] = 0u;
        c6502_key_repeat = 0xffu;
        return 0; /* Preserve the firmware's all-keys-released notification. */
    }
    if (!down && !up) {
        if (message == MSG_CHAR || message == MSG_SYSCHAR ||
            message == MSG_DT_CHAR || message == MSG_DT_SYSCHAR) {
            ++c6502_t_gui_ignored_chars;
            return 1;
        }
        return 0;
    }
    ++c6502_t_gui_messages;
    if ((c6502_u32)flags & KS_SHIFT) native_t_shift(1);
    if (key == SCANCODE_POWER_OFF_ON) {
        ++c6502_t_gui_power_messages;
        return 0;
    }
    /* Host modifier state follows the physical Shift keys only. Mapping
       another function key to guest Shift must not latch KS_SHIFT or the
       Shift+D debugger chord on the host. */
    if (key == SCANCODE_LEFTSHIFT || key == SCANCODE_RIGHTSHIFT || key == SCANCODE_SHIFT) {
        native_t_shift(down); return 1;
    }
    if (key >= 128u || (code = map_key((T_UHWORD)key)) == 0xffu) return 0;
    bit = (c6502_u8)(1u << (key & 7u));
    held = &c6502_t_gui_held[key >> 3];
    if (up) {
        *held &= (c6502_u8)~bit;
        /* Aliases share the guest key but not the physical key state. */
        if (c6502_key_repeat == code) {
            c6502_u32 scan;
            for (scan = 0u; scan < 128u; ++scan)
                if ((c6502_t_gui_held[scan >> 3] & (1u << (scan & 7u))) &&
                    map_key((T_UHWORD)scan) == code) return 1;
            c6502_key_repeat = 0xffu;
        }
        return 1;
    }
    if (*held & bit) return 1; /* OS repeats / duplicate message family. */
    *held |= bit;
    if (!c6502_input_active || !c6502_t_gui_accept || c6502_native_host_stop_requested)
        return 1; /* Launch/teardown records release, never queues input. */
    now = native_clock();
    c6502_key_scan_tick = now;
#ifdef C6502_CRASH_TRACE
    /* Unlike the matrix build, plain D remains a game letter. Shift+D is
       the optional trace toggle. No filesystem work in a GUI callback. */
    if (key == SCANCODE_D && nd_session_running && c6502_t_gui_shift) {
        nd_pending ^= 1u;
        return 1;
    }
#endif
    native_queue_key(code, 0);
    if (native_t_direction(code)) {
        c6502_key_repeat = code;
        c6502_key_repeat_tick = now;
        c6502_key_repeating = 0u;
    }
    return 1;
}

static void native_t_dispatch(T_GUI_Msg *message)
{
    /* Match the official game's host path. Collect raw keys only in our
       window procedure; CHAR is not another guest key. The firmware still
       receives DefaultMainWinProc for modifiers and system power. */
    fnGUI_TranslateMessage(message);
    fnGUI_DispatchMessage(message);
}

static void native_t_pump(c6502_u32 now)
{
    T_GUI_HWND window = c6502_native_state.window;
    c6502_u32 pending = 16u, gap;
    T_GUI_Msg message;
    if (!window || c6502_t_gui_pumping || c6502_native_t_quit_received ||
        c6502_native_host_stop_requested) return;
    if (c6502_key_initialized && now - c6502_t_gui_last_pump < C6502_T_INPUT_PUMP_TICKS &&
        !fnGUI_HavePendingMessage(window)) return;
    c6502_t_gui_pumping = 1u;
    /* The T IAL reports K6.4 only as a modifier on another key. A read of
       this independent input pin supplies the standalone Shift edge; no
       matrix selection, IRQ masking or competing keyboard scanner. */
    native_t_shift(!(*hardware_byte(C6502_T_SHIFT_DATA_ADDRESS) & 0x10u));
    /* Enter IAL once even for an empty queue; timer #2 guarantees a wake.
       Further iterations drain queued messages only, with a finite cap. */
    do {
        if (!fnGUI_GetMessage(&message, window)) {
            c6502_native_t_quit_received = 1u;
            c6502_native_host_stop_requested = 1u;
            break;
        }
        native_t_dispatch(&message);
    } while (--pending && !c6502_native_host_stop_requested && fnGUI_HavePendingMessage(window));
    now = native_clock();
    gap = now - c6502_t_gui_last_pump;
    if (c6502_key_initialized) {
        native_key_gap(now, gap, 0u);
        if (gap > c6502_perf.key_scan_max_gap_ticks) c6502_perf.key_scan_max_gap_ticks = gap;
    }
    c6502_t_gui_last_pump = c6502_key_scan_tick = now;
    c6502_key_previous_bridge = c6502_key_bridge_id;
    ++c6502_perf.key_scans;
    ++c6502_t_gui_batches;
    c6502_key_initialized = 1u;
    if (c6502_t_gui_accept && !c6502_native_host_stop_requested && c6502_key_repeat != 0xffu &&
        now - c6502_key_repeat_tick >= (c6502_key_repeating ? 20u : 80u)) {
        native_queue_key(c6502_key_repeat, 1);
        c6502_key_repeat_tick = now;
        c6502_key_repeating = 1u;
    }
    c6502_t_gui_pumping = 0u;
}

static void native_t_finish_input(void)
{
    T_GUI_HWND window = c6502_native_state.window;
    c6502_u32 quiet_at = native_clock(), timers = 0u;
    c6502_t_gui_accept = 0u;
    /* Timer #1 is installed by App_Main. Keep focus until GUI key release
       plus a quiet interval, without touching matrix ports or global queues. */
    while (window && !c6502_native_t_quit_received) {
        T_GUI_Msg message;
        c6502_u32 i, held = 0u, now;
        if (!fnGUI_GetMessage(&message, window)) {
            c6502_native_t_quit_received = 1u;
            break;
        }
        native_t_dispatch(&message);
        native_t_shift(!(*hardware_byte(C6502_T_SHIFT_DATA_ADDRESS) & 0x10u));
        now = native_clock();
        for (i = 0u; i < sizeof(c6502_t_gui_held); ++i) held |= c6502_t_gui_held[i];
        if (held || native_is_key_message(message.message)) { quiet_at = now; timers = 0u; }
        else if (message.hWnd == window && message.message == MSG_TIMER && message.wParam == 1u)
            ++timers;
        if (!held && !c6502_t_gui_shift && now - quiet_at >= 32u && timers >= 2u && !fnGUI_HavePendingMessage(window))
            break;
    }
    c6502_input_active = 0u;
    c6502_key_head = c6502_key_count = c6502_timer_key_deferred = 0u;
    c6502_key_repeat = 0xffu;
}

#endif
