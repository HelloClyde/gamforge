#ifndef GAM4980_CORE_H
#define GAM4980_CORE_H

#include "gam4980_types.h"

#define GAM4980_LCD_WIDTH 159
#define GAM4980_LCD_HEIGHT 96
#define GAM4980_LCD_STRIDE (GAM4980_LCD_WIDTH + 1)
#define GAM4980_LCD_PACKED_STRIDE (GAM4980_LCD_STRIDE / 8)
#define GAM4980_LCD_PACKED_SIZE \
    (GAM4980_LCD_PACKED_STRIDE * GAM4980_LCD_HEIGHT)
#define GAM4980_ROM_SIZE 0x200000u
#define GAM4980_RAM_SIZE 0x8000u
#define GAM4980_FLASH_SIZE 0x200000u
#define GAM4980_SAVE_SIZE 0x14000u
#define GAM4980_GAME_MAX_SIZE 0x1e0000u
#define GAM4980_GAME_HEADER_SIZE 0x46u
#ifdef GAM4980_DYNAMIC_NATIVE_ALL
#define GAM4980_BARE_ROM_CACHE_LINES 64u
#else
#define GAM4980_BARE_ROM_CACHE_LINES 128u
#endif
#define GAM4980_BARE_ROM_CACHE_SIZE \
    (GAM4980_BARE_ROM_CACHE_LINES * 0x1000u)
#define GAM4980_NATIVE_CODE_ARENA_SIZE 0x40000u
#define GAM4980_ROM_MISS_TRACE_CAPACITY 19u

enum gam4980_rom_miss_kind {
    GAM4980_ROM_MISS_MAPPED_BANK = 1,
    GAM4980_ROM_MISS_DIRECT = 2,
};

enum gam4980_key {
    GAM4980_KEY_POWER = 0x00,
    GAM4980_KEY_MENU = 0x01,
    GAM4980_KEY_EC_SJ = 0x02,
    GAM4980_KEY_EC_SW = 0x03,
    GAM4980_KEY_CE = 0x04,
    GAM4980_KEY_DIALOG = 0x05,
    GAM4980_KEY_DOWNLOAD = 0x06,
    GAM4980_KEY_SPEAK = 0x07,
    GAM4980_KEY_1 = 0x08,
    GAM4980_KEY_2 = 0x09,
    GAM4980_KEY_3 = 0x0a,
    GAM4980_KEY_4 = 0x0b,
    GAM4980_KEY_5 = 0x0c,
    GAM4980_KEY_6 = 0x0d,
    GAM4980_KEY_7 = 0x0e,
    GAM4980_KEY_8 = 0x0f,
    GAM4980_KEY_Q = 0x10,
    GAM4980_KEY_W = 0x11,
    GAM4980_KEY_E = 0x12,
    GAM4980_KEY_R = 0x13,
    GAM4980_KEY_T = 0x14,
    GAM4980_KEY_Y = 0x15,
    GAM4980_KEY_U = 0x16,
    GAM4980_KEY_I = 0x17,
    GAM4980_KEY_A = 0x18,
    GAM4980_KEY_S = 0x19,
    GAM4980_KEY_D = 0x1a,
    GAM4980_KEY_F = 0x1b,
    GAM4980_KEY_G = 0x1c,
    GAM4980_KEY_H = 0x1d,
    GAM4980_KEY_J = 0x1e,
    GAM4980_KEY_K = 0x1f,
    GAM4980_KEY_INPUT = 0x20,
    GAM4980_KEY_Z = 0x21,
    GAM4980_KEY_X = 0x22,
    GAM4980_KEY_C = 0x23,
    GAM4980_KEY_V = 0x24,
    GAM4980_KEY_B = 0x25,
    GAM4980_KEY_N = 0x26,
    GAM4980_KEY_M = 0x27,
    GAM4980_KEY_SHIFT = 0x28,
    GAM4980_KEY_HELP = 0x29,
    GAM4980_KEY_SEARCH = 0x2a,
    GAM4980_KEY_INSERT = 0x2b,
    GAM4980_KEY_MODIFY = 0x2c,
    GAM4980_KEY_DELETE = 0x2d,
    GAM4980_KEY_EXIT = 0x2e,
    GAM4980_KEY_ENTER = 0x2f,
    GAM4980_KEY_9 = 0x30,
    GAM4980_KEY_0 = 0x31,
    GAM4980_KEY_O = 0x32,
    GAM4980_KEY_P = 0x33,
    GAM4980_KEY_L = 0x34,
    GAM4980_KEY_UP = 0x35,
    GAM4980_KEY_SPACE = 0x36,
    GAM4980_KEY_LEFT = 0x37,
    GAM4980_KEY_DOWN = 0x38,
    GAM4980_KEY_RIGHT = 0x39,
    GAM4980_KEY_PAGE_UP = 0x3a,
    GAM4980_KEY_PAGE_DOWN = 0x3b,
};

enum gam4980_lcd_theme {
    GAM4980_LCD_THEME_OFF = 0,
    GAM4980_LCD_THEME_GREEN,
    GAM4980_LCD_THEME_BLUE,
    GAM4980_LCD_THEME_YELLOW,
    GAM4980_LCD_THEME_COUNT,
};

enum gam4980_rom_region {
    GAM4980_ROM_REGION_8 = 0,
    GAM4980_ROM_REGION_E = 1,
};

typedef int (*gam4980_rom_read_fn)(
    void *context, u8 region, u32 offset, u8 *out, u32 size
);

typedef int (*gam4980_native_read_fn)(
    void *context, u32 offset, u8 *out, u32 size
);

enum gam4980_load_stage {
    GAM4980_LOAD_STAGE_GAME_HLE = 1,
    GAM4980_LOAD_STAGE_CFG,
    GAM4980_LOAD_STAGE_AOT_INDEX,
};

typedef void (*gam4980_load_progress_fn)(
    void *context, u32 stage, u32 current, u32 total
);

/* Optional host-service poll used by cooperative frontends that cannot rely
 * on interrupts while the guest CPU is running.  A non-zero max_guest_cycles
 * splits a long guest frame at safe CPU/timer boundaries so the callback can
 * sample hardware input without changing guest-visible time. */
typedef void (*gam4980_runtime_poll_fn)(void *context);

#ifdef GAM4980_ENABLE_PROFILING
typedef void (*gam4980_instruction_profile_fn)(
    void *context, u16 virtual_pc, u32 physical_pc, u8 opcode
);
#endif

typedef struct gam4980_buffers {
    u8 *ram;
    u8 *flash;
    u8 *rom_8;
    u8 *rom_e;
    u16 *framebuffer;
    gam4980_rom_read_fn rom_read;
    void *rom_context;
    u32 flash_size;
    u8 *rom_cache;
    u32 rom_cache_size;
    u8 *native_code;
    u32 native_code_size;
} gam4980_buffers_t;

int gam4980_init(const gam4980_buffers_t *buffers);
void gam4980_deinit(void);
void gam4980_set_load_progress_callback(
    gam4980_load_progress_fn callback, void *context
);
void gam4980_set_runtime_poll_callback(
    gam4980_runtime_poll_fn callback, void *context,
    u32 max_guest_cycles
);
u8 *gam4980_game_storage(void);
int gam4980_load_game_header(const u8 *header, u32 size);
void gam4980_key_down(u8 key);
void gam4980_step_frame(void);
int gam4980_render_frame(void);
void gam4980_run_frame(void);
int gam4980_cpu_halted(void);
const u8 *gam4980_packed_frame(void);
u32 gam4980_changed_row_mask(u32 word);
const u16 *gam4980_expand_frame(const u8 *packed_frame);
const u16 *gam4980_framebuffer(void);
void gam4980_set_lcd_theme(u32 theme);
u16 gam4980_lcd_background_color(void);
u16 gam4980_lcd_foreground_color(void);
u8 *gam4980_save_data(void);
int gam4980_save_dirty(void);
void gam4980_save_mark_clean(void);
int gam4980_shutdown_requested(void);
u16 gam4980_shutdown_pc(void);
int gam4980_warm_bare_rom_cache(void);
uint32_t gam4980_rom_cache_lines(void);
uint32_t gam4980_rom_cache_warm_pages(void);
uint32_t gam4980_rom_cache_runtime_misses(void);
uint32_t gam4980_rom_miss_trace_count(void);
uint32_t gam4980_rom_miss_trace_dropped(void);
uint32_t gam4980_rom_miss_trace_kind(uint32_t index);
uint32_t gam4980_rom_miss_trace_slot(uint32_t index);
uint32_t gam4980_rom_miss_trace_region(uint32_t index);
uint32_t gam4980_rom_miss_trace_page(uint32_t index);
int gam4980_native_modules_open(
    gam4980_native_read_fn reader, void *context, u32 file_size
);
void gam4980_native_modules_close(void);
u32 gam4980_native_module_status(void);
u32 gam4980_native_module_count(void);
u32 gam4980_native_module_match_count(void);
u32 gam4980_native_module_package_size(void);
u32 gam4980_native_module_preloaded(void);
u32 gam4980_native_module_loads(void);
u32 gam4980_native_module_evictions(void);
u32 gam4980_native_module_bytes_loaded(void);
u32 gam4980_native_module_fallbacks(void);
u32 gam4980_native_module_fault_attempts(void);
u32 gam4980_native_module_fault_deferred(void);
u32 gam4980_native_module_cooldown_deferred(void);
u32 gam4980_native_module_thrash_suppressions(void);
u32 gam4980_native_module_batches(void);
u32 gam4980_native_module_transition_count(void);
u32 gam4980_native_module_transition_from(u32 rank);
u32 gam4980_native_module_transition_to(u32 rank);
u32 gam4980_native_module_transition_hits(u32 rank);
u32 gam4980_native_module_transition_error(u32 rank);
u32 gam4980_native_module_arena_size(void);
u32 gam4980_native_module_slot_size(void);
u32 gam4980_native_module_resident_count(void);
u32 gam4980_native_module_alloc_units_used(void);
u32 gam4980_native_module_alloc_units_total(void);
u32 gam4980_native_module_format(void);
u32 gam4980_native_module_game_bound(void);
u32 gam4980_native_module_game_blocks(void);
u32 gam4980_native_module_game_bytes(void);
u32 gam4980_static_native_compiled(void);
u32 gam4980_static_native_bound(void);
u32 gam4980_static_native_modules(void);
u32 gam4980_static_native_blocks(void);
u32 gam4980_static_native_guest_bytes(void);
u32 gam4980_static_native_code_bytes(void);
u32 gam4980_static_native_invalidations(void);
#ifdef GAM4980_ENABLE_IRAM_EXEC_ENGINE
#define GAM4980_IRAM_BURST_BUCKET_COUNT 6u
#define GAM4980_IRAM_EXIT_HOTSPOT_CAPACITY 16u
#define GAM4980_IRAM_EXIT_HOTSPOT_REASON_COUNT 3u
#define GAM4980_IRAM_DISPATCH_TARGET_COUNT 5u
#define GAM4980_IRAM_SLOW_PATH_CLASS_COUNT 9u

enum gam4980_iram_exit_hotspot_reason {
    GAM4980_IRAM_HOTSPOT_ZERO = 0,
    GAM4980_IRAM_HOTSPOT_SLOW = 1,
    GAM4980_IRAM_HOTSPOT_DISPATCH = 2,
};

enum gam4980_iram_dispatch_target {
    GAM4980_IRAM_DISPATCH_UNKNOWN = 0,
    GAM4980_IRAM_DISPATCH_FIRMWARE_AOT = 1,
    GAM4980_IRAM_DISPATCH_FIRMWARE_HLE = 2,
    GAM4980_IRAM_DISPATCH_GAME_HLE = 3,
    GAM4980_IRAM_DISPATCH_GAME_AOT = 4,
};

enum gam4980_iram_slow_path_class {
    GAM4980_IRAM_SLOW_UNSUPPORTED_OPCODE = 0,
    GAM4980_IRAM_SLOW_FETCH_PAGE = 1,
    GAM4980_IRAM_SLOW_DECIMAL_MODE = 2,
    GAM4980_IRAM_SLOW_ZERO_PAGE_SPECIAL = 3,
    GAM4980_IRAM_SLOW_PAGE_READ = 4,
    GAM4980_IRAM_SLOW_PAGE_WRITE = 5,
    GAM4980_IRAM_SLOW_INDIRECT_READ = 6,
    GAM4980_IRAM_SLOW_INDIRECT_WRITE = 7,
    GAM4980_IRAM_SLOW_OTHER = 8,
};

enum gam4980_iram_super_kind {
    GAM4980_IRAM_SUPER_LOAD_OPER1_IMM16 = 0,
    GAM4980_IRAM_SUPER_LOAD_OPER2_IMM16 = 1,
    GAM4980_IRAM_SUPER_STACK_ADD16 = 2,
    GAM4980_IRAM_SUPER_STACK_SUB16 = 3,
    GAM4980_IRAM_SUPER_ADD16_OPER1_OPER2 = 4,
    GAM4980_IRAM_SUPER_COUNT = 5,
};

void gam4980_set_iram_exec_enabled(int enabled);
void gam4980_invalidate_iram_exec_residency(void);
u32 gam4980_iram_exec_calls(void);
u32 gam4980_iram_exec_instructions(void);
u32 gam4980_iram_exec_cycles(void);
u32 gam4980_iram_exec_zero_fallbacks(void);
u32 gam4980_iram_exec_control_exits(void);
u32 gam4980_iram_exec_deadline_exits(void);
u32 gam4980_iram_exec_dispatch_exits(void);
u32 gam4980_iram_exec_slow_exits(void);
u32 gam4980_iram_exec_max_instructions(void);
u32 gam4980_iram_fastchain_calls(void);
u32 gam4980_iram_fastchain_cycles(void);
u32 gam4980_iram_fastchain_reentries(void);
u32 gam4980_iram_fastchain_zero_returns(void);
u32 gam4980_iram_fastchain_reinstall_failures(void);
u32 gam4980_iram_fastchain_non_dispatch_skips(void);
u32 gam4980_native_shared_validation(void);
u32 gam4980_native_shared_calls(void);
u32 gam4980_native_shared_blocks(void);
u32 gam4980_native_shared_guest_cycles(void);
u32 gam4980_native_shared_7c30_entries(void);
u32 gam4980_native_shared_misses(void);
u32 gam4980_native_shared_chain_links(void);
u32 gam4980_native_shared_max_chain(void);
u32 gam4980_native_shared_direct_links(void);
u32 gam4980_iram_dispatch_firmware_aot_entries(void);
u32 gam4980_iram_dispatch_firmware_hle_entries(void);
u32 gam4980_iram_dispatch_game_hle_entries(void);
u32 gam4980_iram_dispatch_game_aot_entries(void);
u32 gam4980_iram_super_match_builds(u32 kind);
u32 gam4980_iram_super_hits(u32 kind);
u32 gam4980_iram_shadow_rebuilds(void);
u32 gam4980_iram_shadow_marker_visits(void);
u32 gam4980_iram_shadow_super_enabled(void);
u32 gam4980_iram_shadow_adaptive_checks(void);
u32 gam4980_iram_shadow_adaptive_disables(void);
u32 gam4980_iram_shadow_disable_reason(void);
u32 gam4980_iram_burst_bucket_hits(u32 bucket);
u32 gam4980_iram_exit_hotspot_hits(u32 reason, u32 index);
u32 gam4980_iram_exit_hotspot_error(u32 reason, u32 index);
u32 gam4980_iram_exit_hotspot_virtual_pc(u32 reason, u32 index);
u32 gam4980_iram_exit_hotspot_physical_pc(u32 reason, u32 index);
u32 gam4980_iram_exit_hotspot_opcode(u32 reason, u32 index);
u32 gam4980_iram_exit_hotspot_bank(u32 reason, u32 index);
u32 gam4980_iram_dispatch_target_hits(u32 target);
u32 gam4980_iram_slow_opcode_hits(u32 opcode);
u32 gam4980_iram_slow_path_class_hits(u32 path_class);
u32 gam4980_iram_exit_sample_rate(void);
u32 gam4980_iram_exit_samples(void);
#ifdef GAM4980_IRAM_EXEC_NATIVE_TEST
u32 gam4980_debug_exec_slice(u32 cycles);
u32 gam4980_debug_cpu_pc(void);
u32 gam4980_debug_cpu_regs(void);
u32 gam4980_debug_cpu_status(void);
u32 gam4980_debug_read8(u32 address);
u32 gam4980_debug_bank(u32 slot);
#endif
#endif
#ifdef GAM4980_ENABLE_FIRMWARE_HLE
void gam4980_set_firmware_hle_enabled(int enabled);
int gam4980_firmware_hle_enabled(void);
u32 gam4980_firmware_hle_hits(void);
u64 gam4980_firmware_hle_guest_cycles(void);
u32 gam4980_resource_span_cache_hits(void);
u32 gam4980_resource_span_cache_misses(void);
u32 gam4980_firmware_hle_path_count(void);
u16 gam4980_firmware_hle_path_pc(u32 path_id);
u32 gam4980_firmware_hle_path_attempts(u32 path_id);
u32 gam4980_firmware_hle_path_hits(u32 path_id);
u32 gam4980_firmware_hle_path_condition_rejects(u32 path_id);
u32 gam4980_firmware_hle_path_budget_rejects(u32 path_id);
u32 gam4980_firmware_hle_path_batch_groups(u32 path_id);
u32 gam4980_firmware_hle_path_batch_iterations(u32 path_id);
u32 gam4980_firmware_hle_path_batch_max(u32 path_id);
u32 gam4980_firmware_hle_path_direct_groups(u32 path_id);
u32 gam4980_firmware_hle_path_direct_iterations(u32 path_id);
u64 gam4980_firmware_hle_path_guest_cycles(u32 path_id);
#endif
#ifdef GAM4980_ENABLE_GAME_LOAD_AOT
#define GAM4980_GAME_AOT_SEMANTIC_KIND_COUNT 13u
void gam4980_set_game_load_aot_enabled(int enabled);
void gam4980_set_game_aot_metrics_enabled(int enabled);
void gam4980_set_game_aot_semantic_mask(u32 mask);
void gam4980_set_game_aot_entry_limit(u32 limit);
void gam4980_set_game_aot_direct_links(int enabled);
int gam4980_game_aot_direct_link_available(void);
u32 gam4980_game_aot_entry_count(void);
int gam4980_game_aot_enabled(void);
u32 gam4980_game_hle_match_count(void);
u32 gam4980_game_aot_entry_physical_pc(u32 entry_id);
u32 gam4980_game_aot_entry_pattern(u32 entry_id);
u32 gam4980_game_aot_semantic_count(void);
u32 gam4980_game_aot_linked_call_count(void);
u32 gam4980_game_aot_direct_link_hits(void);
u32 gam4980_game_aot_linear_link_count(void);
u32 gam4980_game_aot_linear_link_hits(void);
u32 gam4980_game_aot_trace_entry_count(void);
u32 gam4980_game_aot_trace_hits(void);
u32 gam4980_game_aot_trace_instruction_hits(void);
u32 gam4980_game_aot_direct_link_stage_hits(u32 stage);
u32 gam4980_game_aot_reachable_count(void);
u32 gam4980_game_aot_code_size(void);
u32 gam4980_game_aot_semantic_hits(u32 semantic_kind);
u32 gam4980_game_aot_semantic_hit_total(void);
#endif
#if (defined(GAM4980_ENABLE_AOT) && defined(GAM4980_AOT_DIAGNOSTICS)) || \
    defined(GAM4980_RUNTIME_PERFORMANCE_LOG) || \
    defined(GAM4980_ENABLE_FIRMWARE_HLE)
void gam4980_set_performance_debug(int enabled);
int gam4980_performance_debug_enabled(void);
#endif
#ifdef GAM4980_ENABLE_AOT
u32 gam4980_aot_token_link_hits(void);
void gam4980_set_native_trace_aot_enabled(int enabled);
int gam4980_native_trace_aot_enabled(void);
u32 gam4980_native_trace_7c30_calls(void);
u32 gam4980_native_trace_7c30_iterations(void);
u32 gam4980_native_trace_7c30_guest_cycles(void);
u32 gam4980_native_trace_7c30_slice_exits(void);
u32 gam4980_native_trace_7c30_terminal_exits(void);
u32 gam4980_native_trace_7c30_validation(void);
#endif
#if defined(GAM4980_ENABLE_AOT) && defined(GAM4980_AOT_DIAGNOSTICS)
u64 gam4980_aot_instruction_count(void);
u32 gam4980_aot_block_count(void);
u64 gam4980_aot_block_hit_count(u32 block_id);
u32 gam4980_aot_block_physical_pc(u32 block_id);
u16 gam4980_aot_block_virtual_pc(u32 block_id);
u32 gam4980_aot_block_instruction_count(u32 block_id);
u16 gam4980_aot_block_bank2(u32 block_id);
int gam4980_aot_block_bank2_varies(u32 block_id);
#ifdef GAM4980_ENABLE_GAME_LOAD_AOT
u64 gam4980_game_aot_instruction_count(void);
u64 gam4980_game_aot_entry_hit_count(u32 entry_id);
#endif
#endif
#ifdef GAM4980_RUNTIME_PERFORMANCE_LOG
u32 gam4980_performance_exec_calls(void);
u64 gam4980_performance_guest_cycles(void);
u64 gam4980_performance_scheduled_cycles(void);
u64 gam4980_performance_halted_cycles(void);
u64 gam4980_performance_timer_ticks(void);
u32 gam4980_performance_step_frames(void);
u32 gam4980_performance_lcd_write_calls(void);
u32 gam4980_performance_lcd_changed_writes(void);
u32 gam4980_performance_render_calls(void);
u32 gam4980_performance_dirty_render_calls(void);
u32 gam4980_performance_changed_render_calls(void);
u32 gam4980_performance_pc_sample_stride(void);
u32 gam4980_performance_sample_count(void);
u32 gam4980_performance_sample_capacity(void);
u16 gam4980_performance_sample_virtual_pc(u32 sample_id);
u32 gam4980_performance_sample_physical_pc(u32 sample_id);
u32 gam4980_performance_sample_hits(u32 sample_id);
u32 gam4980_performance_sample_dropped(void);
#endif
#ifdef GAM4980_STATE_DIAGNOSTICS
u64 gam4980_state_hash(void);
u64 gam4980_state_cpu_hash(void);
u64 gam4980_state_ram_hash(void);
u64 gam4980_state_timing_hash(void);
#endif
#ifdef GAM4980_ENABLE_PROFILING
void gam4980_set_instruction_profile(
    gam4980_instruction_profile_fn callback, void *context
);
#endif

#endif
