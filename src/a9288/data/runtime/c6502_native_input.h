/* One input source, two operations: capture now; consume later.  Drawing
   checkpoints must never consume a key intended for SysGetKey/GuiGetMsg. */
#define C6502_KEY_QUEUE_SIZE 16u
static c6502_u8 c6502_key_queue[C6502_KEY_QUEUE_SIZE];
static c6502_u8 c6502_key_head, c6502_key_count;
/* A captured FIFO head may yield to a timer once, never indefinitely. */
static c6502_u8 c6502_timer_key_deferred;
static c6502_u8 c6502_key_previous[8];
static c6502_u8 c6502_key_initialized, c6502_input_active;
static c6502_u32 c6502_key_scan_tick, c6502_key_repeat_tick;
static c6502_u8 c6502_key_repeat = 0xffu;
static c6502_u8 c6502_key_repeating;
/* Action keys have no auto-repeat. Re-arm only after a stable release,
   while accepting the initial down edge immediately (no short-tap delay). */
#define C6502_ACTION_RELEASE_TICKS 4u
static c6502_u8 c6502_action_blocked, c6502_action_releasing;
static c6502_u32 c6502_action_release_at[2];
static c6502_u32 c6502_action_bounces;
/* Small, passive diagnostics. Bridge IDs below are scan-endpoint context,
   NOT a claim that one helper occupied the whole unsampled interval. */
static c6502_u32 c6502_key_bridge_id, c6502_key_previous_bridge;
static c6502_u32 c6502_key_code_counts[64][3]; /* edge, repeat, consumed */
static c6502_u32 c6502_key_gap_bins[6]; /* <=4,8,16,32,64,>64 ticks */
static c6502_u32 c6502_key_gap_count, c6502_key_gaps[8][6];
static c6502_u32 c6502_key_event_count, c6502_key_events[32][5];

static void native_key_trace(c6502_u32 kind, c6502_u8 code, c6502_u32 now)
{
    c6502_u32 *t = c6502_key_events[c6502_key_event_count & 31u];
    t[0] = ++c6502_key_event_count; t[1] = now;
    t[2] = code; t[3] = kind; t[4] = c6502_key_count;
}

static void native_key_diagnostics_reset(void)
{
    c6502_u32 i, j;
    for (i = 0u; i < 64u; ++i)
        for (j = 0u; j < 3u; ++j) c6502_key_code_counts[i][j] = 0u;
    for (i = 0u; i < 6u; ++i) c6502_key_gap_bins[i] = 0u;
    c6502_key_gap_count = c6502_key_event_count = 0u;
    c6502_key_bridge_id = c6502_key_previous_bridge = 0xffffffffu;
}

static void native_key_gap(c6502_u32 now, c6502_u32 gap, c6502_u8 row7)
{
    c6502_u32 bin = 0u, limit = 4u;
    while (bin < 5u && gap > limit) { ++bin; limit <<= 1; }
    ++c6502_key_gap_bins[bin];
    if (gap > 16u) {
        c6502_u32 *t = c6502_key_gaps[c6502_key_gap_count & 7u];
        t[0] = ++c6502_key_gap_count; t[1] = now; t[2] = gap;
        t[3] = c6502_key_previous_bridge; t[4] = c6502_key_bridge_id;
        t[5] = row7;
    }
}

static void native_queue_key(c6502_u8 code, int repeat);

static void native_action_snapshot(c6502_u8 held, c6502_u32 now)
{
    c6502_u32 i;
    if (!c6502_key_initialized) {
        c6502_action_blocked = held;
        c6502_action_releasing = 0u;
        c6502_action_bounces = 0u;
        return;
    }
    for (i = 0u; i < 2u; ++i) {
        c6502_u8 bit = (c6502_u8)(1u << i);
        if ((c6502_action_releasing & bit) &&
            now - c6502_action_release_at[i] >= C6502_ACTION_RELEASE_TICKS) {
            c6502_action_blocked &= (c6502_u8)~bit;
            c6502_action_releasing &= (c6502_u8)~bit;
        }
        if (held & bit) {
            if (!(c6502_action_blocked & bit)) {
                native_queue_key(i ? 0x2fu : 0x2eu, 0);
                c6502_action_blocked |= bit;
            } else if (c6502_action_releasing & bit) {
                ++c6502_action_bounces;
            }
            c6502_action_releasing &= (c6502_u8)~bit;
        } else if ((c6502_action_blocked & bit) && !(c6502_action_releasing & bit)) {
            c6502_action_releasing |= bit;
            c6502_action_release_at[i] = now;
        }
    }
}

static void native_queue_key(c6502_u8 code, int repeat)
{
    /* A slow game must not accumulate stale auto-repeat movements. Actual
       press edges are kept independently, including press/release/press. */
    if (repeat && c6502_key_count) return;
    if (c6502_key_count == C6502_KEY_QUEUE_SIZE) {
        ++c6502_perf.key_queue_overflows;
        return;
    }
    c6502_key_queue[(c6502_key_head + c6502_key_count) & 15u] = code;
    ++c6502_key_count;
    if (c6502_key_count > c6502_perf.key_queue_peak)
        c6502_perf.key_queue_peak = c6502_key_count;
    if (repeat) ++c6502_perf.key_repeats;
    else ++c6502_perf.key_edges;
    if (code < 64u) ++c6502_key_code_counts[code][repeat ? 1u : 0u];
    native_key_trace(repeat ? 1u : 0u, code, c6502_key_scan_tick);
}

static c6502_u8 native_take_key(void)
{
    c6502_u8 code;
    if (!c6502_key_count) return 0xffu;
    code = c6502_key_queue[c6502_key_head];
    c6502_key_head = (c6502_key_head + 1u) & 15u;
    --c6502_key_count;
    c6502_timer_key_deferred = 0u;
    ++c6502_perf.keys_consumed;
    if (code < 64u) ++c6502_key_code_counts[code][2];
    return code;
}

static void native_key_snapshot(const c6502_u8 current[8], c6502_u32 now)
{
    static const c6502_u8 key_map[8][7] = {
        {0x31u, 0x10u, 0x18u, 0x21u, 0x32u, 0x00u, 0x2eu},
        {0x08u, 0x11u, 0x19u, 0x22u, 0x33u, 0x07u, 0x2fu},
        {0x09u, 0x12u, 0x1au, 0x23u, 0x34u, 0x01u, 0x3au},
        {0x0au, 0x13u, 0x1bu, 0x24u, 0x0fu, 0x20u, 0x3bu},
        {0x0bu, 0x14u, 0x1cu, 0x25u, 0x30u, 0x29u, 0x28u},
        {0x0cu, 0x15u, 0x1du, 0x26u, 0xffu, 0x2du, 0x2eu},
        {0x0du, 0x16u, 0x1eu, 0x27u, 0xffu, 0x36u, 0xffu},
        {0x0eu, 0x17u, 0x1fu, 0x35u, 0x38u, 0x37u, 0x39u}
    };
    c6502_u8 held = 0xffu;
    c6502_u32 row, gap = now - c6502_key_scan_tick;
    if (c6502_key_initialized && gap > c6502_perf.key_scan_max_gap_ticks)
        c6502_perf.key_scan_max_gap_ticks = gap;
    if (c6502_key_initialized) native_key_gap(now, gap, current[7]);
    c6502_key_previous_bridge = c6502_key_bridge_id;
    c6502_key_scan_tick = now;
    ++c6502_perf.key_scans;
    /* Both physical Exit aliases belong to one logical action key. */
    native_action_snapshot((c6502_u8)(
        (((current[0] | current[5]) & 64u) ? 1u : 0u) |
        ((current[1] & 64u) ? 2u : 0u)), now);
    for (row = 0u; row < 8u; ++row) {
        c6502_u32 column;
        c6502_u8 pressed = current[row] & ~c6502_key_previous[row];
        for (column = 0u; column < 7u; ++column) {
            c6502_u8 code = key_map[row][column];
            if (code == 0xffu) continue;
            if ((current[row] & (1u << column)) &&
                (code == 0x35u || (code >= 0x37u && code <= 0x39u))) held = code;
            if (code != 0x2eu && code != 0x2fu &&
                c6502_key_initialized && (pressed & (1u << column)))
                native_queue_key(code, 0);
        }
        c6502_key_previous[row] = current[row];
    }
    /* This baseline is taken at game entry, not at the first key query.
       It suppresses only the key still held from launching the app. */
    if (!c6502_key_initialized || held != c6502_key_repeat || gap > 64u) {
        /* A long unsampled interval (or debugger/clock jump) is not proof
           the key was continuously held. Do not synthesize a repeat. */
        c6502_key_repeat = held;
        c6502_key_repeat_tick = now;
        c6502_key_repeating = 0u;
    } else if (held != 0xffu &&
        now - c6502_key_repeat_tick >= (c6502_key_repeating ? 20u : 80u)) {
        native_queue_key(held, 1);
        c6502_key_repeat_tick = now;
        c6502_key_repeating = 1u;
    }
    c6502_key_initialized = 1u;
}
