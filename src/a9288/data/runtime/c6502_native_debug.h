/* Optional, on-demand crash breadcrumbs. Never call the filesystem while
 * the keyboard matrix transaction has interrupts masked. A key/touch only
 * requests a toggle; the next full C bridge performs it with the host ABI.
 * Keep two independent, bounded text snapshots. An interrupted overwrite
 * can destroy one slot, not both. No file is touched at ordinary startup.
 * update+close requests persistence; hardware/firmware reset guarantees
 * are deliberately not assumed. No fault handler or watchdog is installed.
 */
#ifndef C6502_TRACE_ON_START
#define C6502_TRACE_ON_START 0u
#endif
#ifndef C6502_TRACE_GAME_SHA256
#define C6502_TRACE_GAME_SHA256 "unknown"
#endif
#ifndef C6502_TRACE_TARGET
#define C6502_TRACE_TARGET "unknown"
#endif
#ifndef C6502_TRACE_BUILD_ID
#define C6502_TRACE_BUILD_ID "unknown"
#endif
#define ND_EVENTS 16u
#define ND_FIELDS 32u
#define ND_TEXT_SIZE 8192u
enum { ND_ENTER, ND_LEAVE, ND_ENABLE, ND_PAUSE, ND_FINISH, ND_EXIT_ENTER, ND_EXIT_LEAVE };
static c6502_u32 nd_events[ND_EVENTS][ND_FIELDS];
static c6502_u32 nd_event_count, nd_snapshot_sequence, nd_session_tick;
static c6502_u32 nd_min_host_sp, nd_writes, nd_errors, nd_io_ticks;
static c6502_u32 nd_last_idle_write, nd_text_length;
static c6502_u8 nd_active, nd_pending, nd_busy, nd_session_running;
static c6502_u8 nd_overflow;
static char nd_text[ND_TEXT_SIZE];
static const c6502_u32 *nd_current_regs;
static c6502_u32 nd_current_id, nd_current_caller, nd_current_host_sp;
static c6502_u8 nd_teardown_active;
static c6502_u32 nd_exit_stage, nd_exit_detail;
static const char *const nd_exit_names[] = {
    "none", "performance_log", "start_release_timer", "release_input",
    "stop_release_timer", "error_dialog", "release_dc", "release_game_resources",
    "post_window_close", "drain_app_window", "cleanup_app_window",
    "restore_launcher_9288", "restore_desktop_frame", "free_desktop_backup", "return_to_host",
    "destroy_app_window", "post_app_quit", "restore_9288t_host"
};

static void nd_indicator(void)
{
    c6502_u32 x, y;
    /* 8x7 D, outside every supported guest viewport. E means write error.
       The touch targets keep a grey D button even when tracing is off. */
    static const c6502_u8 d[7] = {0x3cu,0x22u,0x22u,0x22u,0x22u,0x22u,0x3cu};
    static const c6502_u8 e[7] = {0x3eu,0x20u,0x20u,0x3cu,0x20u,0x20u,0x3eu};
    for (y = 0u; y < 7u; ++y) for (x = 0u; x < 8u; ++x) {
        c6502_u32 px = C6502_HOST_WIDTH - 10u + x;
        c6502_u32 at = (y + 1u) * C6502_HOST_STRIDE + px / 4u;
        c6502_u32 shift = (3u - (px & 3u)) * 2u;
        c6502_u8 bits = nd_errors ? e[y] : d[y];
        c6502_u8 ink = 3u; /* Packed 2-bpp: 3 is white, 0 is black. */
        c6502_u8 v;
        if (nd_active && (bits & (0x80u >> x))) ink = 0u;
#ifdef C6502_TARGET_9288S
        if (!nd_active && !nd_errors && (bits & (0x80u >> x))) ink = 2u;
#endif
        if (nd_errors && (bits & (0x80u >> x))) ink = 0u;
        v = (c6502_u8)((C6502_FRAMEBUFFER[at] & ~(3u << shift)) | (ink << shift));
        C6502_FRAMEBUFFER[at] = v;
#ifdef C6502_HOST_PACKED_1X
        c6502_t_frame_shadow[at] = v;
#endif
    }
}

static void nd_key_snapshot(const c6502_u8 current[8])
{
    /* D is reserved only in builds containing this feature. Ignore a key
       already held at launch; one down edge toggles, no repeat toggles. */
    if (nd_session_running && c6502_key_initialized &&
        (current[2] & 4u) && !(c6502_key_previous[2] & 4u)) nd_pending ^= 1u;
}

static void nd_put(const char *text)
{
    while (*text) {
        if (nd_text_length >= ND_TEXT_SIZE) { nd_overflow = 1u; return; }
        nd_text[nd_text_length++] = *text++;
    }
}

static void nd_hex(c6502_u32 value)
{
    c6502_u32 i;
    static const char digits[] = "0123456789ABCDEF";
    for (i = 0u; i < 8u; ++i) {
        char s[2]; s[0] = digits[(value >> (28u - 4u * i)) & 15u]; s[1] = 0;
        nd_put(s);
    }
}

static void nd_value(const char *name, c6502_u32 value)
{
    nd_put(name); nd_put("="); nd_hex(value); nd_put("\n");
}

static void nd_record(c6502_u32 kind, const c6502_u32 *r, c6502_u32 id,
                      c6502_u32 caller, c6502_u32 host_sp)
{
    c6502_u32 *v = nd_events[nd_event_count & (ND_EVENTS - 1u)];
    c6502_u32 i, sp = r[10];
    c6502_u8 *ram = c6502_native_state.ram;
    v[0] = ++nd_event_count; v[1] = kind; v[2] = native_clock();
    v[3] = id; v[4] = caller; v[5] = host_sp;
    if (host_sp && (!nd_min_host_sp || host_sp < nd_min_host_sp)) nd_min_host_sp = host_sp;
    for (i = 0u; i < 15u; ++i) v[6u + i] = r[i];
    v[21] = c6502_native_state.banks[5]; v[22] = c6502_native_state.banks[9];
    v[23] = ram && sp <= C6502_RAM_SIZE - 16u;
    /* Only resident RAM, never guest_read() or banked ROM: tracing must
       not load a resource page, change DATA channels, or recurse into FS. */
    for (i = 0u; i < 4u; ++i) {
        c6502_u32 at = sp + i * 4u;
        v[24u + i] = v[23] ? (c6502_u32)ram[at] | ((c6502_u32)ram[at+1u] << 8) |
            ((c6502_u32)ram[at+2u] << 16) | ((c6502_u32)ram[at+3u] << 24) : 0u;
    }
    v[28] = ram ? get16(0x20u) : 0u; v[29] = ram ? get16(0x23u) : 0u;
    v[30] = ram ? get16(0x28u) : 0u; v[31] = ram ? get16(0x2au) : 0u;
}

static int nd_snapshot(const char *status)
{
    FS_FILE *file;
    c6502_u32 start, first, i, j, checksum = 2166136261u;
    int ok;
    if (nd_busy) return 0;
    nd_busy = 1u;
    start = native_clock();
    nd_text_length = 0u; nd_overflow = 0u;
    nd_put("[GAMFORGE CRASH TRACE 1]\nbuild=CRASH-TRACE-1\n");
    nd_put("target=" C6502_TRACE_TARGET "\ngame_sha256=" C6502_TRACE_GAME_SHA256 "\n");
    nd_put("build_id=" C6502_TRACE_BUILD_ID "\n");
#ifdef NATIVE_TITLE
    nd_put("game=" NATIVE_TITLE "\n");
#endif
    nd_put("status="); nd_put(status); nd_put("\n");
    nd_put("numbers=hexadecimal_except_clock_hz_and_format_version\nclock_hz=256\n");
    nd_put("caller_kind=native_return_pc_not_guest_pc\n");
    nd_put("host_sp_kind=bridge_entry_not_deepest_C_or_firmware_SP\n");
    nd_put("coverage=full_C_bridges_and_host_exit_not_inline_native_game_or_fast_assembly_helpers\n");
    nd_put("event_kinds=0:enter,1:leave,2:enable,3:pause,4:game_return,5:exit_enter,6:exit_leave\n");
    nd_put("event_columns=seq,kind,tick,id,caller,host_sp,r0,r1,r2,r3,A,X,Y,guest_sp,NZ,P,soft_sp,r11,r12,r13,ram_base,bank5,bank9,stack_valid,stack0,stack1,stack2,stack3,oper1,oper2,zp28,zp2a\n");
    nd_value("game_size", C6502_GAME_SIZE);
    nd_value("session_tick", nd_session_tick);
    nd_value("snapshot_sequence", ++nd_snapshot_sequence);
    nd_value("events_total", nd_event_count);
    nd_value("min_bridge_entry_sp", nd_min_host_sp);
    nd_value("prior_successful_writes", nd_writes);
    nd_value("prior_io_ticks", nd_io_ticks);
    nd_value("write_errors", nd_errors);
    first = nd_event_count > ND_EVENTS ? nd_event_count - ND_EVENTS : 0u;
    for (i = first; i < nd_event_count; ++i) {
        c6502_u32 *v = nd_events[i & (ND_EVENTS - 1u)];
        nd_put("event");
        for (j = 0u; j < ND_FIELDS; ++j) { nd_put(","); nd_hex(v[j]); }
        nd_put("\n");
    }
    /* Include the final pending helper name without requiring a separate
       device-side symbols file. The accompanying PC JSON maps callers. */
    if (nd_event_count) {
        c6502_u32 *last = nd_events[(nd_event_count - 1u) & (ND_EVENTS - 1u)];
        c6502_u32 id = last[3];
        if (last[1] == ND_EXIT_ENTER || last[1] == ND_EXIT_LEAVE) {
            nd_value("exit_stage_id", id);
            nd_put("exit_stage=");
            nd_put(id < sizeof(nd_exit_names)/sizeof(nd_exit_names[0]) ?
                   nd_exit_names[id] : "unknown");
            nd_put("\n");
            nd_value("exit_step_returned", last[1] == ND_EXIT_LEAVE);
            nd_value("exit_detail", nd_exit_detail);
        } else if (id < C6502_BRIDGE_COUNT) {
            nd_put("last_bridge="); nd_put(c6502_profile_names[id]); nd_put("\n");
        }
    }
    for (i = 0u; i < nd_text_length; ++i) {
        checksum ^= (c6502_u8)nd_text[i]; checksum *= 16777619u;
    }
    nd_value("checksum_fnv1a32", checksum);
    nd_put("[END]\n");
    if (nd_overflow) { nd_busy = 0u; ++nd_errors; nd_active = 0u; return 0; }
    file = fs_fopen((nd_snapshot_sequence & 1u) ? "a:\\GAMDBG1.LOG" : "a:\\GAMDBG0.LOG", "wb");
    ok = file != 0;
    if (file) {
        ok = fs_fwrite(nd_text, 1, nd_text_length, file) == nd_text_length;
        if (fs_ferror(file)) ok = 0;
        if (fs_update(file)) ok = 0;
        if (fs_fclose(file)) ok = 0;
    }
    nd_io_ticks += native_clock() - start;
    if (ok) ++nd_writes;
    else { ++nd_errors; nd_active = 0u; }
    nd_busy = 0u;
    /* Exit snapshots must not redraw D onto the restored desktop. */
    if (nd_session_running) nd_indicator();
    return ok;
}

static void nd_reset(void)
{
    nd_active = nd_busy = nd_errors = nd_event_count = nd_snapshot_sequence = 0u;
    nd_writes = nd_io_ticks = nd_min_host_sp = 0u;
    nd_current_regs = 0;
    nd_teardown_active = 0u;
    nd_exit_stage = nd_exit_detail = 0u;
    nd_session_tick = nd_last_idle_write = native_clock();
    nd_session_running = 1u;
    nd_pending = C6502_TRACE_ON_START;
    /* Do not remove/rewrite a previous crash log on the next launch. */
}

static void nd_service(const c6502_u32 *r, c6502_u32 id,
                       c6502_u32 caller, c6502_u32 host_sp)
{
    if (!nd_pending || nd_busy || !nd_session_running) return;
    nd_pending = 0u;
    if (nd_active) {
        nd_record(ND_PAUSE, r, id, caller, host_sp);
        (void)nd_snapshot("paused");
        nd_active = 0u;
    } else {
        nd_errors = 0u;
        nd_active = 1u;
        nd_record(ND_ENABLE, r, id, caller, host_sp);
        /* Seed both slots for this session. Later launches while tracing
           is off leave these alone, even if the game starts successfully. */
        if (nd_snapshot("enabled")) (void)nd_snapshot("enabled");
    }
    nd_last_idle_write = native_clock();
    nd_indicator();
}

static void nd_finish(void)
{
    /* Keep exit coverage iff the user had tracing on at game return. No
       filesystem writes for an ordinary/off/paused session. */
    nd_teardown_active = nd_active;
    if (nd_active) {
        nd_record(ND_FINISH, (const c6502_u32 *)c6502_bridge_regs, 0u, 0u, 0u);
        if (!nd_snapshot("returned_from_game")) nd_teardown_active = 0u;
    }
    nd_session_running = nd_active = nd_pending = 0u;
}

void c6502_native_exit_begin(void) { nd_finish(); }

void c6502_native_exit_checkpoint(c6502_u32 stage, c6502_u32 after, c6502_u32 detail)
{
    if (!nd_teardown_active || nd_busy) return;
    nd_exit_stage = stage; nd_exit_detail = detail;
    /* Historical guest state is resident RAM; there is no bridge-entry SP
       or game caller PC for a host teardown marker. Never invent either. */
    nd_record(after ? ND_EXIT_LEAVE : ND_EXIT_ENTER,
              (const c6502_u32 *)c6502_bridge_regs, stage, 0u, 0u);
    if (!nd_snapshot(after ? "after_exit_step" : "before_exit_step"))
        nd_teardown_active = 0u;
}

void c6502_native_exit_complete(void)
{
    c6502_native_exit_checkpoint(NATIVE_EXIT_RETURN, 1u, 0u);
    nd_teardown_active = 0u;
}

static void nd_capture_service(void)
{
    /* A blocking SysKeyRead/GuiGetMsg might not return on reserved D.
       Service the request AFTER restoring the matrix registers and PSR,
       using its already saved bridge context. No extra game key is needed. */
    if (nd_current_regs)
        nd_service(nd_current_regs, nd_current_id, nd_current_caller, nd_current_host_sp);
}
