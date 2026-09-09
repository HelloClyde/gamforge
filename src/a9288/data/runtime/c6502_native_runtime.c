#include "Dsys.h"
#include "CRTL/malloc.h"
#include "c6502_native_runtime.h"
#include "c6502_native_bridge_ids.h"

#define C6502_RAM_SIZE 0x8000u
#ifndef C6502_GAME_SIZE
#error C6502_GAME_SIZE must be provided by the per-game compiler
#endif
#define C6502_BOOT_RAW_SIZE 32832u
#define C6502_GAME_PHYSICAL_BASE 0x20d000u
#define C6502_VIEW_Y 24u
#define C6502_GUEST_STRIDE 20u
#define C6502_GUEST_HEIGHT 96u
#define C6502_RESOURCE_SCRATCH_SIZE \
    (C6502_GUEST_STRIDE * C6502_GUEST_HEIGHT)
#define C6502_FRAMEBUFFER ((volatile c6502_u8 *)0x003c0000u)
#define C6502_FRAME_STRIDE 80u
#define C6502_FRAME_HEIGHT 240u
#define C6502_FLAG_C 0x01u
#define C6502_FLAG_Z 0x02u
#define C6502_FLAG_V 0x40u
#define C6502_FLAG_N 0x80u
#define C6502_IO_BASE 0x00040000u
#define C6502_CTM_DIVIDER_ADDRESS (C6502_IO_BASE + 0x0153u)
#define C6502_K5_FUNCTION_ADDRESS (C6502_IO_BASE + 0x02c0u)
#define C6502_K5_DATA_ADDRESS (C6502_IO_BASE + 0x02c1u)
#define C6502_PORT0_DATA_ADDRESS (C6502_IO_BASE + 0x02d1u)
#define C6502_PORT0_IOCTRL_ADDRESS (C6502_IO_BASE + 0x02d2u)
#define C6502_KEY_IRQ_FACTOR_ADDRESS (C6502_IO_BASE + 0x0280u)
#define C6502_KEY_ROW_SELECT_ADDRESS 0x00300f46u
#define C6502_PSR_IE 0x10u
/* Only audit unsolicited firmware repaint at input/wait checkpoints.
   Drawing itself maps LCD writes immediately; this is NOT a frame timer. */
#define C6502_FRAME_TICKS 64u
/* Original A4980 timer input: one source tick per 400 cycles at 4 MHz.
   ST1LD determines the IRQ period; SysTimer1Open selects IRQs per message. */
#define C6502_TIMER_SOURCE_HZ 10000u

extern const c6502_u8 c6502_game_image_lzss_start[];
extern const c6502_u8 c6502_game_image_lzss_end[];
extern const c6502_u8 c6502_boot_snapshot_lzss_start[];
extern const c6502_u8 c6502_boot_snapshot_lzss_end[];
extern const c6502_u16 c6502_dispatch_bank_starts[];
extern const c6502_u16 c6502_dispatch_bank_starts_end[];
extern const c6502_u16 c6502_dispatch_offsets[];
extern void *const c6502_dispatch_targets[];
extern void *const c6502_dispatch_targets_end[];

volatile c6502_u32 c6502_bridge_regs[15];
volatile c6502_u32 c6502_bridge_target;
/* Kept in the ELF for emulator/GDB completeness checks.  A missing bridge is
   never allowed to disappear as a silent successful call: record the exact
   runtime order so the PC recompiler can reject or implement it. */
volatile c6502_u32 c6502_missing_bridge_count;
volatile c6502_u32 c6502_missing_bridge_ids[64];
c6502_u32 c6502_entry_regs[15];
C6502_NativeState c6502_native_state;
c6502_u32 c6502_host_dp;
volatile c6502_u32 c6502_validation_trace_count;
volatile c6502_u32 c6502_validation_trace[128][10];
volatile c6502_u32 c6502_validation_key_count;
volatile c6502_u32 c6502_validation_keys[32][4];
static c6502_u16 c6502_heap_begin;
static c6502_u16 c6502_heap_end;
static c6502_u16 c6502_allocations[128][2];
/* Both buffers are fully overwritten by c6502_native_prepare(). Keeping
   them out of .bss avoids a redundant 64 KiB clear at the KF2 entry point. */
static c6502_u8 c6502_boot_raw[C6502_BOOT_RAW_SIZE]
    __attribute__((section(".noinit"), aligned(4)));
/* The snapshot's trailing 32 KiB already IS the game RAM image.  Use it
   in place instead of retaining a second permanent copy after startup. */
#define c6502_ram (c6502_boot_raw + 64u)
static c6502_u8 c6502_resource_scratch[C6502_RESOURCE_SCRATCH_SIZE]
    __attribute__((section(".noinit"), aligned(4)));
static c6502_u8 c6502_text_surface[80u * 240u]
    __attribute__((section(".noinit"), aligned(4)));
/* 9288 V1.5 has five private entries before the SDK's late game API block.
   Its drawing surface is 320x240/2-bpp, not the A-series 160x96/1-bpp RAM. */
#define NATIVE_GAME_GUI(member) \
    (*(__typeof__(tpDL_GUITable->member) *)(void *)( \
        (c6502_u8 *)tpDL_GUITable + \
        __builtin_offsetof(T_GUI_RelocationTable, member) + 0x14u))
static c6502_u32 c6502_last_frame_tick;
static c6502_u32 c6502_timer_clock;
static c6502_u32 c6502_timer_fraction;
static c6502_u32 c6502_timer_remaining;
static c6502_u8 c6502_timer_pending;
static c6502_u8 c6502_frame_valid;
static c6502_u8 c6502_output_ready;
static c6502_u8 c6502_previous_frame[1920];
static c6502_u32 c6502_expand_2x[256];
typedef struct C6502_Glyph {
    c6502_u16 code;
    c6502_u8 rows[32];
} C6502_Glyph;
static C6502_Glyph c6502_glyphs[64];

typedef struct C6502_Perf {
    c6502_u32 start, elapsed;
    c6502_u32 polls, poll_ticks, waits, wait_ticks;
    c6502_u32 graphics, graphics_ticks, presents, present_ticks;
    c6502_u32 submissions, dirty_rows, glyph_hits, glyph_misses;
    c6502_u32 timer_steps;
    c6502_u32 timer_irqs, timer_opens, timer_closes;
    c6502_u32 picture_frame_commits;
    c6502_u32 msgbox_calls, msgbox_ticks, msgbox_wait_ticks;
    c6502_u32 msgbox_last_timeout, msgbox_last_y, msgbox_last_height;
    c6502_u32 mapped_lcd_bytes, framebuffer_bytes, repair_checks;
    c6502_u32 lcd_span_rows, lcd_span_bytes;
    c6502_u32 picture_direct_bytes, picture_staged_bytes, picture_ordered_calls;
    c6502_u32 key_scans, key_scan_max_gap_ticks, key_edges, key_repeats;
    c6502_u32 keys_consumed, key_queue_peak, key_queue_overflows;
    c6502_u32 timer_messages_delivered, key_messages_delivered;
    c6502_u32 timer_coalesced, timer_update_max_gap_ticks, timer_burst_max;
    c6502_u32 timer_key_deferrals, timer_key_yields;
    c6502_u32 timer_backward_rejected, timer_advance_chunks, timer_advance_chunks_max;
} C6502_Perf;
static C6502_Perf c6502_perf;
static c6502_u32 native_clock(void);

static void bytes_set(c6502_u8 *out, c6502_u8 value, c6502_u32 size)
{
    while (size--)
        *out++ = value;
}

static void bytes_copy(c6502_u8 *out, const c6502_u8 *in, c6502_u32 size)
{
    while (size--)
        *out++ = *in++;
}

#ifdef C6502_EXTERNAL_RESOURCES
#include "c6502_native_resources.h"
#endif
#include "c6502_native_timing.h"
#ifdef C6502_PROFILE_OTHER
#include "c6502_native_profile.h"
#endif

static void native_timing_frame(c6502_u32 kind, c6502_u32 now, c6502_u32 draw)
{
    nt_frame(kind, now, draw, c6502_native_state.ram[0x227u],
        (c6502_native_state.ram[0x226u] & 1u) ? c6502_native_state.ram[0x2019u] : 0u,
        c6502_perf.timer_steps,
        c6502_perf.timer_messages_delivered, c6502_perf.timer_coalesced);
}

/* Input checkpoint after LCD activity, NOT a guessed game frame. */
static c6502_u32 native_timing_input_begin(void)
{
    c6502_u32 now = nt_enter(native_clock());
    if (c6502_perf.mapped_lcd_bytes != c6502_timing.lcd_checkpoint) {
        c6502_timing.lcd_checkpoint = c6502_perf.mapped_lcd_bytes;
        native_timing_frame(2u, now, 0u);
    }
    return now;
}

static c6502_u32 native_graphics_phase(c6502_u32 id)
{
    if (id == C6502_BRIDGE_c6502_adapter_syspicture ||
        id == C6502_BRIDGE_c6502_adapter_syspicturedummy) return NT_PICTURE;
    if (id == C6502_BRIDGE_c6502_adapter_sysascii ||
        id == C6502_BRIDGE_c6502_adapter_sysprintstring) return NT_TEXT;
    if (id == C6502_BRIDGE_c6502_adapter_syssavescreen ||
        id == C6502_BRIDGE_c6502_adapter_sysrestorescreen) return NT_SURFACE;
    return NT_SHAPE;
}

static void native_heap_init(c6502_u16 begin, c6502_u16 size)
{
    c6502_heap_begin = begin;
    c6502_heap_end = (c6502_u16)(begin + size);
    bytes_set((c6502_u8 *)c6502_allocations, 0u, sizeof(c6502_allocations));
    c6502_native_state.heap_next = begin;
}

static c6502_u16 native_heap_allocate(c6502_u16 requested)
{
    c6502_u32 candidate = c6502_heap_begin;
    c6502_u32 size = ((c6502_u32)requested + 1u) & ~1u;
    c6502_u32 slot, index;
    if (!size) size = 2u;
    for (slot = 0u; slot < 128u && c6502_allocations[slot][1]; ++slot) {}
    if (slot == 128u) return 0u;
    for (;;) {
        if (candidate + size > c6502_heap_end) return 0u;
        for (index = 0u; index < 128u; ++index) {
            c6502_u32 start = c6502_allocations[index][0];
            c6502_u32 length = c6502_allocations[index][1];
            if (length && candidate < start + length && candidate + size > start) {
                candidate = start + length;
                break;
            }
        }
        if (index == 128u) break;
    }
    c6502_allocations[slot][0] = (c6502_u16)candidate;
    c6502_allocations[slot][1] = (c6502_u16)size;
    if (candidate + size > c6502_native_state.heap_next)
        c6502_native_state.heap_next = candidate + size;
    return (c6502_u16)candidate;
}

static c6502_u8 native_heap_free(c6502_u16 pointer)
{
    c6502_u32 index;
    for (index = 0u; index < 128u; ++index)
        if (c6502_allocations[index][1] && c6502_allocations[index][0] == pointer) {
            c6502_allocations[index][1] = 0u;
            return 1u;
        }
    return 0u;
}

static int lzss_expand(
    const c6502_u8 *input, const c6502_u8 *end,
    c6502_u8 *output, c6502_u32 output_size
)
{
    c6502_u32 produced = 0u;
    while (produced < output_size && input < end) {
        c6502_u8 flags = *input++;
        c6502_u32 bit;
        for (bit = 0u; bit < 8u && produced < output_size; ++bit) {
            if (flags & (1u << bit)) {
                if (input >= end)
                    return 0;
                output[produced++] = *input++;
            } else {
                c6502_u16 token;
                c6502_u32 distance;
                c6502_u32 length;
                c6502_u32 index;
                if (input + 1 >= end)
                    return 0;
                token = (c6502_u16)(input[0] | ((c6502_u16)input[1] << 8));
                input += 2;
                distance = (token & 0x0fffu) + 1u;
                length = (token >> 12) + 3u;
                if (distance > produced || produced + length > output_size)
                    return 0;
                index = produced - distance;
                while (length--)
                    output[produced++] = output[index++];
            }
        }
    }
    return produced == output_size;
}

static c6502_u16 get16(c6502_u32 address)
{
    c6502_u8 *ram = c6502_native_state.ram;
    return (c6502_u16)(ram[address & 0x7fffu] |
        ((c6502_u16)ram[(address + 1u) & 0x7fffu] << 8));
}

static void put16(c6502_u32 address, c6502_u16 value);
static c6502_u8 guest_read(c6502_u16 address);
static void guest_write(c6502_u16 address, c6502_u8 value);
static void native_lcd_write(c6502_u16 address);
static void native_capture_keys(void);
static void set_nz(c6502_u32 *r, c6502_u8 value);

/* $28/$29 are the C6502 compiler's software-stack pointer.  Direct native
   code keeps that value live in R10 for the complete call chain, so the RAM
   shadow is deliberately stale.  Semantic helpers must participate in the
   same register ABI; otherwise an otherwise-correct recovered expression
   such as ``__stack_ptr + local_offset`` silently produces a pointer based
   on the old RAM shadow. */
static c6502_u16 semantic_get16(c6502_u32 *r, c6502_u32 address)
{
    if ((c6502_u8)address == 0x28u)
        return (c6502_u16)r[10];
    return get16((c6502_u8)address);
}

static void semantic_put16(c6502_u32 *r, c6502_u32 address, c6502_u16 value)
{
    if ((c6502_u8)address == 0x28u) {
        r[10] = value;
        return;
    }
    put16((c6502_u8)address, value);
}

static c6502_u32 get32(c6502_u32 address)
{
    return (c6502_u32)get16(address) |
        ((c6502_u32)get16(address + 2u) << 16);
}

static void put16(c6502_u32 address, c6502_u16 value)
{
    c6502_native_state.ram[address & 0x7fffu] = (c6502_u8)value;
    c6502_native_state.ram[(address + 1u) & 0x7fffu] = (c6502_u8)(value >> 8);
}

static void put32(c6502_u32 address, c6502_u32 value)
{
    put16(address, (c6502_u16)value);
    put16(address + 2u, (c6502_u16)(value >> 16));
}

static c6502_u32 guest_get32(c6502_u16 address)
{
    c6502_u32 value = 0u;
    c6502_u32 index;
    for (index = 0u; index < 4u; ++index)
        value |= (c6502_u32)guest_read((c6502_u16)(address + index)) <<
            (index * 8u);
    return value;
}

static void guest_put32(c6502_u16 address, c6502_u32 value)
{
    c6502_u32 index;
    for (index = 0u; index < 4u; ++index)
        guest_write((c6502_u16)(address + index),
            (c6502_u8)(value >> (index * 8u)));
}

/* Long and float values in the C6502 ABI are indirect.  $20/$23 hold
   pointers to four-byte objects; the result object lives at temp_store+8
   and $20 is changed to point at it. */
static c6502_u32 long_operand(c6502_u32 zero_page)
{
    return guest_get32(get16(zero_page));
}

static void return_long(c6502_u32 *r, c6502_u32 value)
{
    c6502_u16 output = (c6502_u16)(get16(0x2au) + 8u);
    guest_put32(output, value);
    put16(0x20u, output);
    r[6] = 3u;
    r[4] = (c6502_u8)(value >> 24);
    set_nz(r, (c6502_u8)r[4]);
}

static void convert_operand_to_long(
    c6502_u32 *r, c6502_u32 zero_page, c6502_u32 size, int sign_extend
)
{
    c6502_u16 base = get16(0x2au);
    c6502_u16 output = (c6502_u16)(base +
        (zero_page == 0x20u ? 16u : 32u));
    c6502_u32 value = zero_page == 0x20u ?
        (size == 1u ? (c6502_u8)r[4] : get16(0x20u)) :
        (size == 1u ? c6502_native_state.ram[0x23u] : get16(0x23u));
    if (sign_extend) {
        if (size == 1u && (value & 0x80u))
            value |= 0xffffff00u;
        else if (size == 2u && (value & 0x8000u))
            value |= 0xffff0000u;
    }
    guest_put32(output, value);
    put16(zero_page, output);
    r[4] = 0u;
    set_nz(r, 0u);
}

static c6502_u8 physical_read(c6502_u32 address)
{
    if (address < C6502_RAM_SIZE)
        return c6502_native_state.ram[address];
    if (address >= C6502_GAME_PHYSICAL_BASE &&
        address - C6502_GAME_PHYSICAL_BASE < c6502_native_state.game_size)
#ifdef C6502_EXTERNAL_RESOURCES
        return nr_read(address - C6502_GAME_PHYSICAL_BASE);
#else
        return c6502_native_state.game[address - C6502_GAME_PHYSICAL_BASE];
#endif
    return 0u;
}

static void physical_write(c6502_u32 address, c6502_u8 value)
{
    if (address < C6502_RAM_SIZE) {
        c6502_native_state.ram[address] = value;
        if (address > 0x400u && address <= 0x1000u)
            native_lcd_write((c6502_u16)address);
    } else if (address >= C6502_GAME_PHYSICAL_BASE &&
               address - C6502_GAME_PHYSICAL_BASE <
                   c6502_native_state.game_size) {
#ifdef C6502_EXTERNAL_RESOURCES
        nr_write(address - C6502_GAME_PHYSICAL_BASE, value);
#else
        c6502_native_state.game[address - C6502_GAME_PHYSICAL_BASE] = value;
#endif
    }
}

static c6502_u32 data_address(c6502_u32 channel, int increment)
{
    c6502_u32 slot = 0x208u + channel * 3u;
    c6502_u8 *ram = c6502_native_state.ram;
    c6502_u32 address = ram[slot] | ((c6502_u32)ram[slot + 1u] << 8) |
        ((c6502_u32)ram[slot + 2u] << 16);
    if (increment && (ram[0x207u] & (1u << channel))) {
        c6502_u32 next = address + 1u;
        ram[slot] = (c6502_u8)next;
        ram[slot + 1u] = (c6502_u8)(next >> 8);
        ram[slot + 2u] = (c6502_u8)(next >> 16);
    }
    return address;
}

static c6502_u8 guest_read(c6502_u16 address)
{
    if (address < 4u)
        return physical_read(data_address(address, 1));
    if (address == 0x0cu)
        return c6502_native_state.bank_select;
    if (address == 0x0du)
        return (c6502_u8)c6502_native_state.banks[
            c6502_native_state.bank_select];
    if (address == 0x0eu)
        return (c6502_u8)(c6502_native_state.banks[
            c6502_native_state.bank_select] >> 8);
    if (address < 0x4000u)
        return c6502_native_state.ram[address];
    return physical_read(
        ((c6502_u32)c6502_native_state.banks[address >> 12] << 12) |
        (address & 0x0fffu)
    );
}

static c6502_u16 guest_get16(c6502_u16 address)
{
    return (c6502_u16)(guest_read(address) |
        ((c6502_u16)guest_read((c6502_u16)(address + 1u)) << 8));
}

static void guest_write(c6502_u16 address, c6502_u8 value)
{
    if (address < 4u) {
        physical_write(data_address(address, 1), value);
        return;
    }
    if (address == 0x0cu) {
        c6502_native_state.bank_select = value & 0x0fu;
        return;
    }
    if (address == 0x0du) {
        c6502_u16 *bank = &c6502_native_state.banks[
            c6502_native_state.bank_select];
        *bank = (c6502_u16)((*bank & 0xff00u) | value);
        return;
    }
    if (address == 0x0eu) {
        c6502_u16 *bank = &c6502_native_state.banks[
            c6502_native_state.bank_select];
        *bank = (c6502_u16)((*bank & 0x00ffu) | ((value & 0x0fu) << 8));
        return;
    }
    if (address >= 0x300u && address < 0x400u)
        return;
    if (address < 0x4000u) {
        c6502_native_state.ram[address] = value;
        if (address > 0x400u && address <= 0x1000u)
            native_lcd_write(address);
        if (address == 0x21bu)
            c6502_native_state.ram[address] = 0u;
        if (address == 0x2028u)
            c6502_native_state.ram[address] = 0xffu;
        return;
    }
    physical_write(
        ((c6502_u32)c6502_native_state.banks[address >> 12] << 12) |
        (address & 0x0fffu), value
    );
}

static void set_nz(c6502_u32 *r, c6502_u8 value)
{
    r[8] = value;
    r[9] = (r[9] & ~(C6502_FLAG_N | C6502_FLAG_Z)) |
        (value == 0u ? C6502_FLAG_Z : 0u) |
        (value & C6502_FLAG_N);
}

static c6502_u8 stack8(c6502_u32 *r, c6502_u32 offset)
{
    return c6502_native_state.ram[(r[10] + offset) & 0x7fffu];
}

static c6502_u16 stack16(c6502_u32 *r, c6502_u32 offset)
{
    return (c6502_u16)(stack8(r, offset) |
        ((c6502_u16)stack8(r, offset + 1u) << 8));
}

static void return8(c6502_u32 *r, c6502_u8 value)
{
    r[4] = value;
    set_nz(r, value);
}

static void return16(c6502_u32 *r, c6502_u16 value)
{
    put16(0x20u, value);
    r[4] = value >> 8;
    set_nz(r, (c6502_u8)r[4]);
}

/* RT.LST/E.BIN: byte arithmetic takes operand 1 in A, not $20.
   Shifts finish with DEX (Z=1), not an LDA of their result. Preserve the
   actual ABI, including zero-count and oversize-count paths. */
static void runtime_shift(c6502_u32 *r, c6502_u8 bits, c6502_u8 right)
{
    c6502_u8 *ram = c6502_native_state.ram;
    c6502_u32 count = ram[0x23u];
    c6502_u32 value = bits == 8u ? (c6502_u8)r[4] : get16(0x20u);
    if (bits == 16u && ram[0x24u]) {
        r[5] = ram[0x24u]; r[4] = 0u;
        put16(0x20u, 0u); set_nz(r, 0u); return;
    }
    r[5] = count;
    if (!count) { set_nz(r, 0u); return; }
    if (count >= bits) {
        r[9] |= C6502_FLAG_C;
        r[4] = 0u;
        if (bits == 16u) put16(0x20u, 0u);
    } else {
        c6502_u32 carry = right ? ((value >> (count - 1u)) & 1u) :
            ((value >> (bits - count)) & 1u);
        value = right ? value >> count : value << count;
        r[9] = (r[9] & ~C6502_FLAG_C) | carry;
        if (bits == 8u) r[4] = (c6502_u8)value;
        else put16(0x20u, (c6502_u16)value);
        r[5] = 0u;
    }
    set_nz(r, 0u);
}

static void runtime_divide8(c6502_u32 *r, c6502_u8 remainder)
{
    c6502_u8 *ram = c6502_native_state.ram;
    c6502_u8 dividend = (c6502_u8)r[4], divisor = ram[0x23u];
    ram[0x20u] = dividend;
    if (!dividend) { ram[0x21u] = 0u; return8(r, 0u); return; }
    if (!divisor) { ram[0x21u] = 0xffu; return8(r, 0xffu); return; }
    ram[0x20u] = 0u;
    ram[0x21u] = dividend % divisor;
    ram[0x26u] = dividend / divisor;
    if (ram[0x26u]) {
        c6502_u32 prefix = dividend, quotient = ram[0x26u];
        c6502_u8 difference, before;
        /* V comes from the final successful SBC of the ROM division,
           which occurs at the least-significant set quotient bit. */
        while (!(quotient & 1u)) { quotient >>= 1; prefix >>= 1; }
        difference = prefix % divisor;
        before = (c6502_u8)(difference + divisor);
        r[9] = (r[9] & ~C6502_FLAG_V) |
            ((((before ^ divisor) & (before ^ difference)) & 0x80u) >> 1);
    }
    r[5] = 0u;
    r[9] &= ~C6502_FLAG_C;
    return8(r, ram[remainder ? 0x21u : 0x26u]);
}

static void runtime_compare16(c6502_u32 *r, c6502_u16 left, c6502_u16 right)
{
    c6502_u16 difference = (c6502_u16)(left - right);
    c6502_u8 low = (c6502_u8)difference;
    c6502_u8 high = (c6502_u8)(difference >> 8);
    /* C6502 RT $D340 is a two-byte SBC followed by PHP/PLA/PLP.
       It returns the comparison in C/Z/N/V, NOT a C strcmp -1/0/+1.
       X counts nonzero subtraction bytes and A contains the final P image. */
    r[9] = (r[9] & ~(C6502_FLAG_C | C6502_FLAG_Z |
        C6502_FLAG_N | C6502_FLAG_V)) | 0x30u |
        (left >= right ? C6502_FLAG_C : 0u) |
        (!difference ? C6502_FLAG_Z : 0u) | (high & C6502_FLAG_N) |
        (((left ^ right) & (left ^ difference) & 0x8000u) ? C6502_FLAG_V : 0u);
    r[4] = r[9];
    r[5] = (low != 0u) + (high != 0u);
    r[8] = !difference ? 0u : ((high & 0x80u) ? 0x80u : 1u);
}

static void *native_target(c6502_u16 virtual_address)
{
    c6502_u32 physical =
        ((c6502_u32)c6502_native_state.banks[virtual_address >> 12] << 12) |
        (virtual_address & 0x0fffu);
    c6502_u32 offset;
    c6502_u32 bank;
    c6502_u32 low;
    c6502_u32 high;
    c6502_u32 count = (c6502_u32)(
        c6502_dispatch_targets_end - c6502_dispatch_targets);
    if (physical < C6502_GAME_PHYSICAL_BASE)
        return 0;
    offset = physical - C6502_GAME_PHYSICAL_BASE;
    bank = offset >> 14;
    if (bank + 1u >= (c6502_u32)(c6502_dispatch_bank_starts_end -
            c6502_dispatch_bank_starts))
        return 0;
    low = c6502_dispatch_bank_starts[bank];
    high = c6502_dispatch_bank_starts[bank + 1u];
    while (low < high) {
        c6502_u32 middle = low + ((high - low) >> 1);
        c6502_u16 candidate = c6502_dispatch_offsets[middle];
        c6502_u16 wanted = (c6502_u16)(offset & 0x3fffu);
        if (candidate < wanted)
            low = middle + 1u;
        else
            high = middle;
    }
    if (low >= count ||
        c6502_dispatch_offsets[low] != (c6502_u16)(offset & 0x3fffu))
        return 0;
    return c6502_dispatch_targets[low];
}

/* Original A LCD storage folds scan lines around row 65, and keeps the
   first column one row apart.  Game code also accesses this storage itself;
   normalising it to a flat 20-byte stride silently corrupts such effects. */
static c6502_u16 lcd_address(c6502_u32 byte_x, c6502_u32 y)
{
    c6502_u32 address;
    if (!byte_x) {
        if (y == 65u) return 0x0ff3u;
        address = 0x413u + (y < 65u ? 64u - y : y - 1u) * 32u;
    } else {
        address = 0x400u + (y <= 65u ? 65u - y : y) * 32u + byte_x - 1u;
    }
    if (address == 0x400u) address = 0x1000u;
    return (c6502_u16)address;
}

static void pixel(c6502_u8 x, c6502_u8 y, int black)
{
    c6502_u8 *screen;
    c6502_u8 mask;
    if (x >= 160u || y >= 96u)
        return;
    screen = c6502_native_state.ram + lcd_address(x >> 3, y);
    mask = (c6502_u8)(0x80u >> (x & 7u));
    guest_write(lcd_address(x >> 3, y), black ? *screen | mask :
        *screen & (c6502_u8)~mask);
}

static void horizontal_span(c6502_u8 x0, c6502_u8 x1, c6502_u8 y, int operation)
{
    c6502_u32 column, first, last;
    if (y >= 96u || x0 >= 160u || x1 < x0) return;
    if (x1 >= 160u) x1 = 159u;
    first = x0 >> 3; last = x1 >> 3;
    for (column = first; column <= last; ++column) {
        c6502_u8 mask = 0xffu;
        c6502_u8 *byte = c6502_native_state.ram + lcd_address(column, y);
        if (column == first) mask &= (c6502_u8)(0xffu >> (x0 & 7u));
        if (column == last) mask &= (c6502_u8)(0xffu << (7u - (x1 & 7u)));
        c6502_u8 value = operation == 0 ? *byte & (c6502_u8)~mask :
            operation == 1 ? *byte | mask : *byte ^ mask;
        guest_write(lcd_address(column, y), value);
    }
}

static void line(c6502_u8 x0, c6502_u8 y0, c6502_u8 x1, c6502_u8 y1)
{
    if (y0 == y1) {
        horizontal_span(x0 < x1 ? x0 : x1, x0 < x1 ? x1 : x0, y0, 1);
        return;
    }
    int dx = x1 > x0 ? x1 - x0 : x0 - x1;
    int sx = x0 < x1 ? 1 : -1;
    int dy = y1 > y0 ? y0 - y1 : y1 - y0;
    int sy = y0 < y1 ? 1 : -1;
    int error = dx + dy;
    for (;;) {
        int doubled_error;
        pixel(x0, y0, 1);
        if (x0 == x1 && y0 == y1)
            break;
        doubled_error = error * 2;
        if (doubled_error >= dy) { error += dy; x0 = (c6502_u8)(x0 + sx); }
        if (doubled_error <= dx) { error += dx; y0 = (c6502_u8)(y0 + sy); }
    }
}

static void rectangle(
    c6502_u8 x0, c6502_u8 y0, c6502_u8 x1, c6502_u8 y1, int fill
)
{
    c6502_u8 y;
    if (fill) {
        for (y = y0; y <= y1; ++y) {
            line(x0, y, x1, y);
            if (y == 0xffu)
                break;
        }
    } else {
        line(x0, y0, x1, y0); line(x0, y1, x1, y1);
        line(x0, y0, x0, y1); line(x1, y0, x1, y1);
    }
}

static void rectangle_clear(
    c6502_u8 x0, c6502_u8 y0, c6502_u8 x1, c6502_u8 y1
)
{
    c6502_u8 x;
    c6502_u8 y;
    for (x = x0; x <= x1; ++x) {
        pixel(x, y0, 0); pixel(x, y1, 0);
        if (x == 0xffu) break;
    }
    for (y = y0; y <= y1; ++y) {
        pixel(x0, y, 0); pixel(x1, y, 0);
        if (y == 0xffu) break;
    }
}

void c6502_native_present(void)
{
    c6502_u8 *source = c6502_native_state.ram;
    volatile c6502_u8 *frame = C6502_FRAMEBUFFER;
    c6502_u32 y;
    c6502_u32 x;
    c6502_u32 started = native_clock(), changed = 0u;
    ++c6502_perf.presents;

    /* Expand each 1-bpp guest pixel to a 2x2 block, centred in the
       24..215 scan lines.  This path needs neither a GUI paint transaction
       nor the legacy SysBltFrame conversion. */
    if (!c6502_frame_valid) {
        for (x = 0u; x < 256u; ++x) {
            c6502_u32 raw = 0u, bit, shifted;
            for (bit = 0u; bit < 8u; ++bit)
                raw = (raw << 4) | ((x & (128u >> bit)) ? 0u : 15u);
            shifted = raw >> 2;
            /* Table is already in little-endian host byte order, shifted
               by one host pixel. The previous byte contributes two bits. */
            c6502_expand_2x[x] = (shifted >> 24) |
                ((shifted >> 8) & 0xff00u) |
                ((shifted << 8) & 0xff0000u) | (shifted << 24);
        }
    }
    /* Full-screen reconciliation is reserved for startup, explicit paint
       invalidation and low-rate firmware repaint audits. Unchanged words
       are NOT resubmitted. This also detects writes without MSG_PAINT. */
    for (y = 0u; y < C6502_VIEW_Y; ++y)
        for (x = 0u; x < C6502_FRAME_STRIDE; x += 4u) {
            volatile c6502_u32 *out = (volatile c6502_u32 *)(frame + y * C6502_FRAME_STRIDE + x);
            if (*out != 0xffffffffu) { *out = 0xffffffffu; c6502_perf.framebuffer_bytes += 4u; }
        }
    for (y = C6502_VIEW_Y + C6502_GUEST_HEIGHT * 2u; y < C6502_FRAME_HEIGHT; ++y)
        for (x = 0u; x < C6502_FRAME_STRIDE; x += 4u) {
            volatile c6502_u32 *out = (volatile c6502_u32 *)(frame + y * C6502_FRAME_STRIDE + x);
            if (*out != 0xffffffffu) { *out = 0xffffffffu; c6502_perf.framebuffer_bytes += 4u; }
        }
    for (y = 0u; y < C6502_GUEST_HEIGHT; ++y) {
        c6502_u8 carry = 0xc0u;
        c6502_u8 row[20];
        c6502_u32 dirty = !c6502_frame_valid;
        volatile c6502_u8 *upper = frame +
            (C6502_VIEW_Y + y * 2u) * C6502_FRAME_STRIDE;
        volatile c6502_u8 *lower = upper + C6502_FRAME_STRIDE;
        for (x = 0u; x < C6502_GUEST_STRIDE; ++x) {
            row[x] = source[lcd_address(x, y)];
            if (x == C6502_GUEST_STRIDE - 1u) row[x] &= 0xfeu;
            dirty |= row[x] != c6502_previous_frame[y * 20u + x];
        }
        if (dirty) ++changed;
        /* Compare actual host memory, not just the guest shadow: the GUI
           can overwrite this surface independently of guest LCD writes. */
        for (x = 0u; x < C6502_GUEST_STRIDE; ++x) {
            c6502_u8 bits = row[x];
            c6502_u32 word = c6502_expand_2x[bits] | carry;
            volatile c6502_u32 *a = (volatile c6502_u32 *)(upper + x * 4u);
            volatile c6502_u32 *b = (volatile c6502_u32 *)(lower + x * 4u);
            if (*a != word) { *a = word; c6502_perf.framebuffer_bytes += 4u; }
            if (*b != word) { *b = word; c6502_perf.framebuffer_bytes += 4u; }
            c6502_previous_frame[y * 20u + x] = bits;
            carry = (bits & 1u) ? 0u : 0xc0u;
        }
    }
    c6502_frame_valid = 1u;
    c6502_output_ready = 1u;
    c6502_perf.dirty_rows += changed;
    ++c6502_perf.submissions;
    c6502_perf.present_ticks += native_clock() - started;
}

void c6502_native_invalidate_screen(void) { c6502_frame_valid = 0u; }

/* Mirror a real A-series LCD byte immediately, including physical/banked
   aliases. Padding in its folded 32-byte rows is NOT visible memory.
   The 159-pixel view is centred at host x=1: a byte spans one aligned word
   plus two bits of its neighbour. Preserve both neighbour pixels and the
   API's hidden 160th guest pixel. No clock read, frame copy or SDK call. */
static void native_lcd_write(c6502_u16 address)
{
    c6502_u32 row, column, x, y, word;
    c6502_u8 bits, carry;
    volatile c6502_u8 *upper, *lower;
    if (!c6502_output_ready || address <= 0x400u || address > 0x1000u) return;
    if (address == 0x1000u) { x = 1u; y = 65u; }
    else if (address == 0x0ff3u) { x = 0u; y = 65u; }
    else {
        row = (address - 0x400u) >> 5;
        column = (address - 0x400u) & 31u;
        if (column < 19u) {
            x = column + 1u; y = row <= 65u ? 65u - row : row;
        } else if (column == 19u) {
            x = 0u; y = row < 65u ? 64u - row : row + 1u;
        } else return;
        if (y >= 96u) return;
    }
    bits = c6502_native_state.ram[address];
    if (x == 19u) bits &= 0xfeu;
    carry = x && (c6502_native_state.ram[lcd_address(x - 1u, y)] & 1u) ? 0u : 0xc0u;
    word = c6502_expand_2x[bits] | carry;
    upper = C6502_FRAMEBUFFER + (C6502_VIEW_Y + y * 2u) * C6502_FRAME_STRIDE + x * 4u;
    lower = upper + C6502_FRAME_STRIDE;
    *(volatile c6502_u32 *)upper = word;
    *(volatile c6502_u32 *)lower = word;
    if (x < 19u) {
        carry = (bits & 1u) ? 0u : 0xc0u;
        upper[4] = (upper[4] & 0x3fu) | carry;
        lower[4] = (lower[4] & 0x3fu) | carry;
        c6502_perf.framebuffer_bytes += 2u;
    }
    c6502_previous_frame[y * 20u + x] = bits;
    ++c6502_perf.mapped_lcd_bytes;
    c6502_perf.framebuffer_bytes += 8u;
    /* Also sample within a full-screen blit, not just between drawing APIs.
       The clock gate in capture limits actual matrix scans to 256 Hz. */
    if (!(c6502_perf.mapped_lcd_bytes & 31u)) native_capture_keys();
}

static c6502_u8 map_key(T_UHWORD key)
{
    switch (key) {
    case SCANCODE_1: return 0x08u; case SCANCODE_2: return 0x09u;
    case SCANCODE_3: return 0x0au; case SCANCODE_4: return 0x0bu;
    case SCANCODE_5: return 0x0cu; case SCANCODE_6: return 0x0du;
    case SCANCODE_7: return 0x0eu; case SCANCODE_8: return 0x0fu;
    case SCANCODE_9: return 0x30u; case SCANCODE_0: return 0x31u;
    case SCANCODE_Q: return 0x10u; case SCANCODE_W: return 0x11u;
    case SCANCODE_E: return 0x12u; case SCANCODE_R: return 0x13u;
    case SCANCODE_T: return 0x14u; case SCANCODE_Y: return 0x15u;
    case SCANCODE_U: return 0x16u; case SCANCODE_I: return 0x17u;
    case SCANCODE_O: return 0x32u; case SCANCODE_P: return 0x33u;
    case SCANCODE_A: return 0x18u; case SCANCODE_S: return 0x19u;
    case SCANCODE_D: return 0x1au; case SCANCODE_F: return 0x1bu;
    case SCANCODE_G: return 0x1cu; case SCANCODE_H: return 0x1du;
    case SCANCODE_J: return 0x1eu; case SCANCODE_K: return 0x1fu;
    case SCANCODE_L: return 0x34u; case SCANCODE_Z: return 0x21u;
    case SCANCODE_X: return 0x22u; case SCANCODE_C: return 0x23u;
    case SCANCODE_V: return 0x24u; case SCANCODE_B: return 0x25u;
    case SCANCODE_N: return 0x26u; case SCANCODE_M: return 0x27u;
    case SCANCODE_ENTER: case SCANCODE_KEYPADENTER: return 0x2fu;
    case SCANCODE_ESCAPE: case SCANCODE_F12: return 0x2eu;
    case SCANCODE_SPACE: return 0x36u;
    case SCANCODE_CURSORUP: case SCANCODE_CURSORBLOCKUP: return 0x35u;
    case SCANCODE_CURSORLEFT: case SCANCODE_CURSORBLOCKLEFT: return 0x37u;
    case SCANCODE_CURSORDOWN: case SCANCODE_CURSORBLOCKDOWN: return 0x38u;
    case SCANCODE_CURSORRIGHT: case SCANCODE_CURSORBLOCKRIGHT: return 0x39u;
    case SCANCODE_PAGEUP: return 0x3au; case SCANCODE_PAGEDOWN: return 0x3bu;
    default: return 0xffu;
    }
}

static volatile c6502_u8 *hardware_byte(c6502_u32 address)
{
    return (volatile c6502_u8 *)(unsigned long)address;
}

static c6502_u32 read_psr(void)
{
    c6502_u32 value;
    __asm__ volatile("ld.w %0,%%psr" : "=r"(value));
    return value;
}

static void write_psr(c6502_u32 value)
{
    __asm__ volatile("ld.w %%psr,%0" : : "r"(value) : "memory");
}

#include "c6502_native_input.h"
#include "c6502_native_matrix.h"
#include "c6502_native_exit.h"
#include "c6502_native_clock.h"

static void native_capture_keys(void)
{
    c6502_u8 current[8];
    c6502_u8 saved_row;
    c6502_u8 saved_k5;
    c6502_u8 saved_port0;
    c6502_u8 saved_factors;
    c6502_u32 now;
    c6502_u32 saved_psr;
    if (!c6502_input_active) return;
    /* Cheap fast gate for tight drawing/poll loops. A full-second gap can
       defer a scan by at most one divider tick, never a whole second. */
    if (c6502_key_initialized &&
        *hardware_byte(C6502_CTM_DIVIDER_ADDRESS) == (c6502_u8)c6502_key_scan_tick) return;
    now = native_clock();
    saved_psr = read_psr();

    /* The matrix registers are shared with the firmware ISR.  Mask IRQs
       only for the few dozen MMIO accesses, then restore every register
       exactly before resuming the native game. */
    write_psr(saved_psr & ~C6502_PSR_IE);
    saved_factors = *hardware_byte(C6502_KEY_IRQ_FACTOR_ADDRESS);
    saved_row = *hardware_byte(C6502_KEY_ROW_SELECT_ADDRESS);
    saved_k5 = *hardware_byte(C6502_K5_FUNCTION_ADDRESS);
    saved_port0 = *hardware_byte(C6502_PORT0_IOCTRL_ADDRESS);
    *hardware_byte(C6502_K5_FUNCTION_ADDRESS) =
        (c6502_u8)(saved_k5 & ~0x0fu);
    *hardware_byte(C6502_PORT0_IOCTRL_ADDRESS) =
        (c6502_u8)(saved_port0 & ~0x70u);
    native_matrix_snapshot(current, now);
    *hardware_byte(C6502_KEY_ROW_SELECT_ADDRESS) = saved_row;
    *hardware_byte(C6502_K5_FUNCTION_ADDRESS) = saved_k5;
    *hardware_byte(C6502_PORT0_IOCTRL_ADDRESS) = saved_port0;
    /* Changing rows can itself latch KEY0/KEY1 factors.  V1.5 leaves those
       vectors pointing at its default infinite-loop handler.  Acknowledge
       only factors generated by this private scan before re-enabling IRQs;
       preserve factors that were pending on entry and unrelated port IRQs.
       FIR0 is write-one-to-clear, not an ordinary saved-state register. */
    *hardware_byte(C6502_KEY_IRQ_FACTOR_ADDRESS) = (c6502_u8)(
        *hardware_byte(C6502_KEY_IRQ_FACTOR_ADDRESS) & ~saved_factors & 0x30u);
    write_psr(saved_psr);

#ifdef C6502_PROFILE_OTHER
    np_key(now); /* Observe the existing scan; do not trigger another one. */
#endif
    native_key_snapshot(current, now);
}

static c6502_u32 native_clock(void)
{
    c6502_u32 attempt;
    for (attempt = 0u; attempt < 4u; ++attempt) {
        volatile c6502_u8 *ctm = hardware_byte(C6502_CTM_DIVIDER_ADDRESS);
        c6502_u8 before = ctm[0];
        c6502_u8 hi = ctm[5], lo = ctm[4], hour = ctm[3];
        c6502_u8 minute = ctm[2], second = ctm[1], divider = ctm[0];
        c6502_u32 candidate;
        if (divider < before ||
            second != ctm[1] || minute != ctm[2] || hour != ctm[3] ||
            lo != ctm[4] || hi != ctm[5] ||
            second >= 60u || minute >= 60u || hour >= 24u) {
            ++c6502_clock_diagnostics.snapshot_retries;
            continue;
        }
        candidate = (((((c6502_u32)hi << 8) | lo) * 86400u +
            hour * 3600u + minute * 60u + second) << 8) | divider;
        if (native_clock_accept(candidate)) return candidate;
    }
    /* Never manufacture elapsed time out of a torn/backwards snapshot.
       Retry on the next call; do not busy-wait for the clock to recover. */
    ++c6502_clock_diagnostics.exhausted;
    return c6502_clock_previous;
}

void c6502_native_finish_input(void)
{
    T_GUI_HWND window = c6502_native_state.window;
    c6502_u32 released_at = 0u;
    c6502_u32 quiet_timers = 0u;
    c6502_u8 releasing = 0u;
    /* May also run after acknowledging a host resource-error dialog. */
    c6502_input_active = 1u;
    /* Physical release alone is not a firmware-input barrier. Keep focus
       while the host drains its keyboard state, for at least 125 ms and
       two of our own GUI timer messages. Any key traffic restarts it.
       No global queue flush, key synthesis, or firmware RAM reset. */
    while (window) {
        c6502_u32 row, down = 0u, pending = 32u, now;
        T_GUI_Msg message;
        native_capture_keys();
        now = c6502_key_scan_tick;
        for (row = 0u; row < 8u; ++row) down |= c6502_key_previous[row];
        if (down) { releasing = 0u; quiet_timers = 0u; }
        else if (!releasing) {
            releasing = 1u; released_at = now; quiet_timers = 0u;
        }
        /* Unlike gameplay polling, teardown must enter the real message
           pump even when its queue is empty. HavePendingMessage only
           inspects queued flags; it does not advance host input/timers.
           App_Main keeps timer #1 alive until this function returns. */
        do {
            if (!fnGUI_GetMessage(&message, window)) goto finished;
            if (native_is_key_message(message.message)) {
                released_at = now; quiet_timers = 0u;
            } else if (releasing && message.hWnd == window &&
                message.message == MSG_TIMER && message.wParam == 1u) {
                if (quiet_timers < 2u) ++quiet_timers;
            }
            native_dispatch_teardown(&message);
        } while (--pending && fnGUI_HavePendingMessage(window));
        /* Check after draining, not before: a late KEYUP/CHAR in this batch
           must not escape because the physical quiet interval just ended. */
        if (releasing && now - released_at >= 32u && quiet_timers >= 2u &&
            !fnGUI_HavePendingMessage(window)) break;
    }
finished:
    c6502_input_active = 0u;
    c6502_key_head = c6502_key_count = c6502_timer_key_deferred = 0u;
}

static c6502_u8 native_window_key(int wait)
{
    c6502_u32 started = native_clock();
    c6502_u8 result;
    /* Gameplay owns its input: matrix snapshot -> local FIFO, exactly one
       consumption per query. Never inspect, translate, dispatch or wait on
       9288 GUI messages here, even if a host key/close message is pending.
       The guest GuiGetMsg wait loop uses this same nonblocking primitive;
       its Timer events come from native_update_timer's hardware clock. */
    native_capture_keys();
    result = native_take_key();
    if (result != 0xffu)
        native_key_trace(wait ? 3u : 2u, result, native_clock());
    if (result != 0xffu && c6502_validation_key_count < 32u) {
        volatile c6502_u32 *t = c6502_validation_keys[c6502_validation_key_count++];
        t[0] = 1u; t[1] = result;
    }
    if (wait) { ++c6502_perf.waits; c6502_perf.wait_ticks += native_clock() - started; }
    else { ++c6502_perf.polls; c6502_perf.poll_ticks += native_clock() - started; }
    return result;
}

static c6502_u8 native_poll_key(void) { return native_window_key(0); }

static void native_update_timer(void)
{
    c6502_u32 now = native_clock();
    c6502_u32 elapsed = now - c6502_timer_clock;
    c6502_u32 chunks = 0u;
    c6502_u8 *ram = c6502_native_state.ram;
    /* Independent of the reader guard: do not rebase on a negative delta.
       -1 tick used to execute 65536 catch-up chunks and block input for
       seconds. A genuine u32 wrap still has a small positive delta. */
    if (elapsed & 0x80000000u) {
        ++c6502_perf.timer_backward_rejected;
        return;
    }
    c6502_timer_clock = now;
    if (!(ram[0x226u] & 1u)) return;
    if (elapsed > c6502_perf.timer_update_max_gap_ticks)
        c6502_perf.timer_update_max_gap_ticks = elapsed;
    while (elapsed) {
        /* Split whole seconds from the fraction before multiplying. At
           10000 Hz each chunk produces <= 2621440000 source ticks, so all
           math fits u32 without target 64-bit helpers. Even the largest
           valid elapsed time now takes <= 32 chunks, not 32768. */
        c6502_u32 chunk = elapsed > 0x04000000u ? 0x04000000u : elapsed;
        c6502_u32 partial = (chunk & 255u) * C6502_TIMER_SOURCE_HZ + c6502_timer_fraction;
        c6502_u32 source = (chunk >> 8) * C6502_TIMER_SOURCE_HZ + (partial >> 8);
        c6502_u32 period = 256u - ram[0x227u], irqs, first, count, number;
        ++chunks;
        elapsed -= chunk;
        c6502_timer_fraction = partial & 255u;
        if (source < c6502_timer_remaining) {
            c6502_timer_remaining -= source;
            continue;
        }
        source -= c6502_timer_remaining;
        irqs = 1u + source / period;
        c6502_timer_remaining = period - source % period;
        c6502_perf.timer_irqs += irqs;
        count = ram[0x2018u]; number = ram[0x2019u];
        /* Exact INC/CMP behaviour, including zero and byte wrap. */
        first = count < number ? number - count :
            (count == 255u && number ? number + 1u : 1u);
        if (irqs < first) { ram[0x2018u] = (c6502_u8)(count + irqs); continue; }
        irqs -= first;
        if (!number) number = 1u;
        {
            c6502_u32 produced = 1u + irqs / number;
            c6502_u32 already_pending = c6502_timer_pending || (ram[0x201eu] & 1u);
            c6502_perf.timer_steps += produced;
            c6502_perf.timer_coalesced += produced - (already_pending ? 0u : 1u);
            if (produced > c6502_perf.timer_burst_max)
                c6502_perf.timer_burst_max = produced;
        }
        ram[0x2018u] = (c6502_u8)(irqs % number);
        ram[0x201eu] |= 1u;
        c6502_timer_pending = 1u; /* ROM has one pending bit, not a queue. */
    }
    c6502_perf.timer_advance_chunks += chunks;
    if (chunks > c6502_perf.timer_advance_chunks_max)
        c6502_perf.timer_advance_chunks_max = chunks;
}

static void native_timer_open(c6502_u8 number)
{
    c6502_u8 *ram = c6502_native_state.ram;
    native_update_timer();
    ++c6502_perf.timer_opens;
    /* E.BIN bank 7 $7B4C: zero and an already-open timer are no-ops. */
    if (!number || ram[0x201au]) return;
    ram[0x201au] = 1u; ram[0x2019u] = number; ram[0x2018u] = 0u;
    ram[0x226u] |= 1u;
}

static void native_timer_close(void)
{
    native_update_timer();
    ++c6502_perf.timer_closes;
    c6502_native_state.ram[0x201au] = 0u;
    c6502_native_state.ram[0x226u] &= 0xfeu;
}

static c6502_u8 native_timer_number(void)
{
    c6502_u8 *ram = c6502_native_state.ram;
    return ram[0x201au] ? ram[0x2019u] : 0u;
}

static void native_refresh_if_due(void)
{
    c6502_u32 now = native_clock();
    c6502_u32 elapsed = now - c6502_last_frame_tick;
    if (c6502_frame_valid && elapsed < C6502_FRAME_TICKS) return;
    c6502_last_frame_tick = now;
    ++c6502_perf.repair_checks;
    c6502_native_present();
}

static c6502_u8 translate_key(c6502_u8 key, c6502_u8 *type)
{
    static const c6502_u8 letters[36] = {
        'q','w','e','r','t','y','u','i',
        'a','s','d','f','g','h','j','k',
        0u,'z','x','c','v','b','n','m',
        0u,0u,0u,0u,0u,0u,0u,0u,0u,0u,0u,0u
    };
    *type = 5u; /* WM_CHAR_FUN */
    switch (key) {
    case 0x00u: return 0x04u; case 0x01u: return 0x07u;
    case 0x02u: return 0x01u; case 0x03u: return 0x02u;
    case 0x06u: return 0x05u; case 0x07u: return 0x03u;
    case 0x20u: return 0x2au; case 0x28u: return 0x29u;
    case 0x29u: return 0x30u; case 0x2au: return 0x32u;
    case 0x2bu: return 0x33u; case 0x2cu: return 0x31u;
    case 0x2du: return 0x26u; case 0x2eu: return 0x28u;
    case 0x2fu: return 0x27u; case 0x35u: return 0x22u;
    case 0x36u: *type = 2u; return ' ';
    case 0x37u: return 0x24u; case 0x38u: return 0x23u;
    case 0x39u: return 0x25u; case 0x3au: return 0x20u;
    case 0x3bu: return 0x21u;
    default: break;
    }
    *type = 2u; /* WM_CHAR_ASC */
    if (key >= 0x08u && key <= 0x0fu)
        return (c6502_u8)('1' + key - 0x08u);
    if (key == 0x30u) return '9';
    if (key == 0x31u) return '0';
    if (key >= 0x10u && key <= 0x33u && letters[key - 0x10u])
        return letters[key - 0x10u];
    if (key == 0x34u) return 'l';
    *type = 0u;
    return 0u;
}

static void api_translate_message(c6502_u32 *r)
{
    c6502_u16 pointer = stack16(r, 0u);
    c6502_u8 type;
    c6502_u8 key;
    c6502_u8 translated;
    if (guest_read(pointer) != 1u) {
        return8(r, guest_read(pointer) != 0u);
        return;
    }
    key = guest_read((c6502_u16)(pointer + 1u));
    if (key == 0xffu) {
        return8(r, 0u);
        return;
    }
    translated = translate_key(key, &type);
    if (c6502_validation_key_count < 32u) {
        volatile c6502_u32 *t = c6502_validation_keys[c6502_validation_key_count++];
        t[0] = 2u; t[1] = key; t[2] = type; t[3] = translated;
    }
    if (!type) {
        return8(r, 0u);
        return;
    }
    guest_write(pointer, type);
    guest_write((c6502_u16)(pointer + 1u), translated);
    guest_write((c6502_u16)(pointer + 2u), 0u);
    return8(r, 1u);
}

static void api_get_message(c6502_u32 *r)
{
    c6502_u16 pointer = stack16(r, 0u);
    c6502_u8 *guest = c6502_native_state.ram + pointer;
    c6502_u8 key;
    for (;;) {
        native_update_timer();
        native_capture_keys();
        native_refresh_if_due();
        /* ROM gives Timer first priority. Keep that first decision, but
           prevent native-host overload from starving an already captured
           key forever: after THIS FIFO head has yielded to one timer,
           deliver it on the next query, leaving the timer pending. Taking
           a key through SysGetKey also resets the deferred-head token. */
        if (c6502_timer_pending || (c6502_native_state.ram[0x201eu] & 1u)) {
            if (c6502_key_count && c6502_timer_key_deferred) {
                ++c6502_perf.timer_key_yields;
            } else {
                c6502_timer_key_deferred = c6502_key_count != 0u;
                if (c6502_timer_key_deferred) ++c6502_perf.timer_key_deferrals;
                ++c6502_perf.timer_messages_delivered;
                c6502_timer_pending = 0u;
                c6502_native_state.ram[0x201eu] &= 0xfeu;
                guest[0] = 6u; guest[1] = 0u; guest[2] = 0u;
                return8(r, 1u);
                return;
            }
        }
        key = native_window_key(1);
        if (key != 0xffu) {
            ++c6502_perf.key_messages_delivered;
            guest[0] = 1u; guest[1] = key; guest[2] = 0u;
            return8(r, 1u);
            return;
        }
    }
}

static void api_get_key(c6502_u32 *r)
{
    c6502_u8 key = native_poll_key();
    /* Real SysGetKey is non-blocking and returns 0xff for an empty buffer. */
    native_update_timer();
    native_refresh_if_due();
    return8(r, key);
}

static c6502_u8 screen_bit(c6502_u16 screen, c6502_u8 x, c6502_u8 y)
{
    c6502_u16 byte_address = screen == 0x400u ? lcd_address(x >> 3, y) :
        (c6502_u16)(screen + (c6502_u16)y * C6502_GUEST_STRIDE + (x >> 3));
    return (guest_read(byte_address) & (0x80u >> (x & 7u))) != 0u;
}

static void set_screen_bit(
    c6502_u16 screen, c6502_u8 x, c6502_u8 y, c6502_u8 value
)
{
    c6502_u16 byte_address = screen == 0x400u ? lcd_address(x >> 3, y) :
        (c6502_u16)(screen + (c6502_u16)y * C6502_GUEST_STRIDE + (x >> 3));
    c6502_u8 mask = (c6502_u8)(0x80u >> (x & 7u));
    c6502_u8 byte = guest_read(byte_address);
    guest_write(byte_address,
        value ? (c6502_u8)(byte | mask) : (c6502_u8)(byte & ~mask));
}

/* A validated packed row already identifies its LCD coordinates. Do not
   send every byte through guest_write -> inverse LCD mapping -> neighbour
   repair. Fold the guest addresses once, carry the shifted host edge from
   the preceding byte, and repair only the rightmost neighbour. This is an
   immediate row writer, NOT a deferred present or an atomic game frame.
   Source must not alias the destination: callers snapshot or prove that. */
static void native_lcd_span(c6502_u32 first, c6502_u32 last, c6502_u32 y,
    const c6502_u8 *source, c6502_u8 left_mask, c6502_u8 right_mask)
{
    c6502_u8 *ram = c6502_native_state.ram;
    c6502_u32 count = last - first + 1u, remaining = count, column = first;
    c6502_u32 zero = lcd_address(0u, y), base = lcd_address(2u, y) - 2u;
    c6502_u8 row[20], *in = row, *end = row + count;
    c6502_u8 *previous;
    c6502_u32 carry = 0xc0u;
    volatile c6502_u32 *out;
    ++c6502_perf.lcd_span_rows;
    c6502_perf.lcd_span_bytes += count;
    /* Only the two edges need masks. A tiny snapshot also keeps the host
       expansion loop free of guest addressing, masks and row-65 branches. */
    while (in != end) *in++ = *source++;
    if (left_mask != 0xffu)
        row[0] = (ram[lcd_address(first, y)] & ~left_mask) | (row[0] & left_mask);
    if (right_mask != 0xffu)
        row[count - 1u] = (ram[lcd_address(last, y)] & ~right_mask) |
            (row[count - 1u] & right_mask);
    in = row;
    if (!column) { ram[zero] = *in++; ++column; --remaining; }
    if (remaining && y == 65u && column == 1u) {
        ram[0x1000u] = *in++; ++column; --remaining;
    }
    if (remaining) {
        c6502_u8 *destination = ram + base + column;
        while (in != end) *destination++ = *in++;
    }
    /* Hidden x=159 is masked only AFTER storing the exact guest RAM. */
    if (c6502_output_ready) {
        if (last == 19u) row[count - 1u] &= 0xfeu;
        if (first) carry = ((c6502_u32)(ram[lcd_address(first - 1u, y)] & 1u) - 1u) & 0xc0u;
        previous = c6502_previous_frame + y * 20u + first;
        out = (volatile c6502_u32 *)(C6502_FRAMEBUFFER +
            (C6502_VIEW_Y + y * 2u) * C6502_FRAME_STRIDE + first * 4u);
        in = row;
        do {
            c6502_u32 bits = *in++, word = c6502_expand_2x[bits] | carry;
            out[0] = word; out[C6502_FRAME_STRIDE / 4u] = word;
            ++out; *previous++ = (c6502_u8)bits;
            carry = ((bits & 1u) - 1u) & 0xc0u;
        } while (in != end);
        if (last < 19u) {
            volatile c6502_u8 *edge = (volatile c6502_u8 *)out;
            edge[0] = (edge[0] & 0x3fu) | carry;
            edge[C6502_FRAME_STRIDE] = (edge[C6502_FRAME_STRIDE] & 0x3fu) | carry;
            c6502_perf.framebuffer_bytes += 2u;
        }
        c6502_perf.mapped_lcd_bytes += count;
        c6502_perf.framebuffer_bytes += count * 8u;
        /* At most 20 guest bytes between checkpoints, without a GUI pump. */
        native_capture_keys();
    }
}

/* Merge one packed row by destination bytes, including unaligned edges.
   Unlike the ROM's special single-byte picture path, glyphs always mask
   their padding. Callers retain that picture quirk before reaching here. */
static void blit_packed_row(c6502_u16 screen, c6502_u8 x0, c6502_u8 y,
    c6502_u8 width, const c6502_u8 *row)
{
    c6502_u32 first = x0 >> 3, last = (x0 + width - 1u) >> 3;
    c6502_u32 shift = x0 & 7u, stride = (width + 7u) >> 3, column;
    /* Promote byte-aligned rows first. Keep the established unaligned
       loop below: it preserves the ROM masks without another shifted-row
       temporary / variable-shift loop on the S1C33 backend. */
    if (screen == 0x400u && !shift) {
        native_lcd_span(first, last, y, row, 0xffu,
            (c6502_u8)(0xffu << (7u - ((x0 + width - 1u) & 7u))));
        return;
    }
    for (column = first; column <= last; ++column) {
        c6502_u32 i = column - first;
        c6502_u8 bits = i < stride ? row[i] >> shift : 0u;
        c6502_u8 mask = 0xffu;
        c6502_u16 address = screen == 0x400u ? lcd_address(column, y) :
            (c6502_u16)(screen + y * 20u + column);
        if (i && shift) bits |= (c6502_u8)(row[i - 1u] << (8u - shift));
        if (column == first) mask &= (c6502_u8)(0xffu >> shift);
        if (column == last) mask &= (c6502_u8)(0xffu << (7u - ((x0 + width - 1u) & 7u)));
        guest_write(address, mask == 0xffu ? bits :
            (c6502_u8)((guest_read(address) & ~mask) | (bits & mask)));
    }
}

static void save_restore_screen(c6502_u32 *r, int restore)
{
    c6502_u8 x0 = (c6502_u8)r[4];
    c6502_u8 y0 = stack8(r, 0u);
    c6502_u8 x1 = stack8(r, 1u);
    c6502_u8 y1 = stack8(r, 2u);
    c6502_u16 buffer = stack16(r, 3u);
    c6502_u32 y, column;
    c6502_u8 swap;
    if (x1 >= 160u || y1 >= 96u) return;
    if (x1 < x0) { swap = x0; x0 = x1; x1 = swap; }
    if (y1 < y0) { swap = y0; y0 = y1; y1 = swap; }
    /* E.BIN's Save/RestoreScreen copies complete destination-aligned
       bytes, including pixels outside the nominal rectangle. It is NOT
       the tightly packed/masked SysPicture(flag=0) format. */
    for (y = y0; y <= y1; ++y) {
        for (column = x0 >> 3; column <= (c6502_u32)(x1 >> 3); ++column) {
            c6502_u16 address = lcd_address(column, y);
            if (restore) guest_write(address, guest_read(buffer));
            else guest_write(buffer, guest_read(address));
            ++buffer;
        }
    }
}

static void picture_dummy(c6502_u32 *r)
{
    c6502_u8 x0 = (c6502_u8)r[4];
    c6502_u8 y0 = stack8(r, 0u);
    c6502_u8 x1 = stack8(r, 1u);
    c6502_u8 y1 = stack8(r, 2u);
    c6502_u16 picture = stack16(r, 3u);
    c6502_u16 screen = stack16(r, 5u);
    c6502_u32 length;
    c6502_u32 index;
    c6502_u8 swap;
    if (x1 >= 160u || y1 >= 96u || screen >= C6502_RAM_SIZE)
        return;
    if (x1 < x0) { swap = x0; x0 = x1; x1 = swap; }
    if (y1 < y0) { swap = y0; y0 = y1; y1 = swap; }
    length = (((c6502_u32)x1 - x0 + 8u) >> 3) *
        ((c6502_u32)y1 - y0 + 1u);
    if (length > C6502_RESOURCE_SCRATCH_SIZE)
        length = C6502_RESOURCE_SCRATCH_SIZE;
    for (index = 0u; index < length; ++index)
        c6502_resource_scratch[index] = guest_read(
            (c6502_u16)(picture + index));
    for (index = 0u; index < (c6502_u32)(y1 - y0 + 1u); ++index) {
        c6502_u32 stride = ((c6502_u32)x1 - x0 + 8u) >> 3;
        if ((x0 >> 3) == (x1 >> 3)) {
            c6502_u16 address = (c6502_u16)(screen +
                (y0 + index) * 20u + (x0 >> 3));
            c6502_u8 mask = (c6502_u8)((0xffu << (8u - (x0 & 7u))) |
                (0x7fu >> (x1 & 7u)));
            /* ROM's single-byte path preserves edge pixels but ORs the
               shifted source without masking its padding. */
            guest_write(address, (guest_read(address) & mask) |
                (c6502_resource_scratch[index] >> (x0 & 7u)));
            continue;
        }
        blit_packed_row(screen, x0, (c6502_u8)(y0 + index),
            (c6502_u8)(x1 - x0 + 1u), c6502_resource_scratch + index * stride);
    }
}

/* The 9288 font renderer consumes a 320x240 two-bit surface, never the
   game's 1920-byte monochrome buffer. Only glyphs use the staging surface. */
static const c6502_u8 *native_glyph(const c6502_u8 *glyph, c6502_u8 width)
{
    c6502_u16 code = (c6502_u16)(glyph[0] | ((c6502_u16)glyph[1] << 8));
    C6502_Glyph *entry = c6502_glyphs + ((glyph[0] ^ glyph[1]) & 63u);
    c6502_u32 y, byte;
    if (entry->code == code) { ++c6502_perf.glyph_hits; return entry->rows; }
    ++c6502_perf.glyph_misses;
    bytes_set(c6502_text_surface, 0xffu, 80u * 32u);
    NATIVE_GAME_GUI(SysPrintString)(c6502_native_state.hdc, 0, 0,
        glyph, c6502_text_surface);
    for (y = 0u; y < 16u; ++y) {
        for (byte = 0u; byte < (c6502_u32)(width >> 3); ++byte) {
            c6502_u8 a = (c6502_u8)~c6502_text_surface[y * 80u + byte * 2u];
            c6502_u8 b = (c6502_u8)~c6502_text_surface[y * 80u + byte * 2u + 1u];
            entry->rows[y * (width >> 3) + byte] = (a & 0x80u) |
                ((a & 0x20u) << 1) | ((a & 8u) << 2) | ((a & 2u) << 3) |
                ((b & 0x80u) >> 4) | ((b & 0x20u) >> 3) |
                ((b & 8u) >> 2) | ((b & 2u) >> 1);
        }
    }
    entry->code = code;
    return entry->rows;
}

static void native_text(c6502_u8 x, c6502_u8 y,
                        const c6502_u8 *text)
{
    /* SysPrintString on 9288 wraps at 320 pixels; the original A-series
       routine wraps at 160 and paints opaque 8x16/16x16 cells.  Rendering
       the complete paragraph onto the desktop DC and cropping it loses
       alternate half-lines and leaves old glyph fragments during scrolling.
       Ask the SDK only for glyphs, then apply the A-series layout ourselves. */
    while (*text && y <= 80u) {
        c6502_u8 glyph[3], width, gy;
        const c6502_u8 *rows;
        glyph[0] = *text++;
        glyph[1] = 0u; glyph[2] = 0u;
        if (glyph[0] == '\n' || glyph[0] == '\r') {
            x = 0u; y = (c6502_u8)(y + 16u); continue;
        }
        width = 8u;
        if (glyph[0] >= 0x81u && *text) {
            glyph[1] = *text++;
            width = glyph[0] >= 0xfdu && glyph[1] >= 0xa1u ? 8u : 16u;
        }
        if ((c6502_u32)x + width > 160u) {
            x = 0u; y = (c6502_u8)(y + 16u);
            if (y > 80u) break;
        }
        rows = native_glyph(glyph, width);
        for (gy = 0u; gy < 16u; ++gy)
            blit_packed_row(0x400u, x, (c6502_u8)(y + gy), width,
                rows + gy * (width >> 3));
        x = (c6502_u8)(x + width);
    }
}

static int picture_source_disjoint(c6502_u16 source, c6502_u32 size)
{
    c6502_u32 end = (c6502_u32)source + size, cursor;
    if (!size) return 0;
    if (source >= 0x1001u && end <= 0x4000u) return 1;
    if (source < 0x4000u || end > 0x10000u) return 0;
    for (cursor = source; cursor < end;) {
        c6502_u32 next = (cursor | 0xfffu) + 1u;
        c6502_u32 physical = ((c6502_u32)c6502_native_state.banks[cursor >> 12] << 12) |
            (cursor & 0xfffu);
        if (next > end) next = end;
        /* Low-numbered banks include ordinary off-screen RAM, not just
           LCD aliases. Check the actual physical span against the LCD
           envelope; $4800 -> bank 4:$0800 is safe, bank 0:$0800 is not.
           Banked physical_read does not execute virtual DATA/I/O reads. */
        if (physical < 0x1001u && physical + next - cursor > 0x400u) return 0;
        cursor = next;
    }
    return 1;
}

/* Resolve the whole read-only-for-this-call resource span, not each pixel
   or byte. Never assume bank windows are contiguous, ROM is immutable, or
   $0000..$0003 reads are ordinary RAM. NULL retains the generic read path. */
static const c6502_u8 *picture_direct_source(c6502_u16 source, c6502_u32 size)
{
    c6502_u32 end = (c6502_u32)source + size, page, physical, offset;
    if (!size) return 0;
    if (source >= 0x1001u && end <= 0x4000u)
        return c6502_native_state.ram + source;
    if (source < 0x4000u || end > 0x10000u) return 0;
    physical = ((c6502_u32)c6502_native_state.banks[source >> 12] << 12) |
        (source & 0xfffu);
    for (page = (source >> 12) + 1u; page <= (end - 1u) >> 12; ++page)
        if (((c6502_u32)c6502_native_state.banks[page] << 12) !=
            physical + (page << 12) - source) return 0;
    /* A contiguous, LCD-disjoint RAM bank span needs no per-byte guest
       lookup either. Never hand a caller a direct LCD-alias pointer. */
    if (physical < C6502_RAM_SIZE) {
        if (size > C6502_RAM_SIZE - physical ||
            (physical < 0x1001u && physical + size > 0x400u)) return 0;
        return c6502_native_state.ram + physical;
    }
    if (physical < C6502_GAME_PHYSICAL_BASE) return 0;
    offset = physical - C6502_GAME_PHYSICAL_BASE;
    if (offset > c6502_native_state.game_size ||
        size > c6502_native_state.game_size - offset) return 0;
#ifdef C6502_EXTERNAL_RESOURCES
    return nr_span(offset, size);
#else
    return c6502_native_state.game + offset;
#endif
}

static void native_picture(c6502_u8 x0, c6502_u8 y0,
    c6502_u8 x1, c6502_u8 y1, c6502_u16 picture, c6502_u8 flag)
{
    c6502_u32 x, y, stride;
    c6502_u8 t;
    if (x1 >= 160u || y1 >= 96u)
        return;
    if (x1 < x0) { t = x0; x0 = x1; x1 = t; }
    if (y1 < y0) { t = y0; y0 = y1; y1 = t; }
    /* E.BIN $682d: flag=1 restores whole aligned screen bytes; flag=0
       copies tightly packed rows while preserving the edge pixels. */
    if (flag == 1u) {
        stride = (x1 >> 3) - (x0 >> 3) + 1u;
        if (picture_source_disjoint(picture, stride * (y1 - y0 + 1u))) {
            c6502_u8 row[20];
            const c6502_u8 *direct = picture_direct_source(picture, stride * (y1 - y0 + 1u));
            for (y = y0; y <= y1; ++y) {
                const c6502_u8 *source = direct;
                if (direct) { direct += stride; c6502_perf.picture_direct_bytes += stride; }
                else {
                    for (x = 0u; x < stride; ++x) row[x] = guest_read(picture++);
                    c6502_perf.picture_staged_bytes += stride; source = row;
                }
                native_lcd_span(x0 >> 3, x1 >> 3, y, source, 0xffu, 0xffu);
            }
            return;
        }
        ++c6502_perf.picture_ordered_calls;
        for (y = y0; y <= y1; ++y)
            for (x = 0u; x < stride; ++x)
                guest_write(lcd_address((x0 >> 3) + x, y),
                    guest_read(picture++));
    } else if ((x0 >> 3) == (x1 >> 3)) {
        c6502_u8 mask = (c6502_u8)((0xffu << (8u - (x0 & 7u))) |
            (0x7fu >> (x1 & 7u)));
        ++c6502_perf.picture_ordered_calls;
        for (y = y0; y <= y1; ++y) {
            c6502_u16 address = lcd_address(x0 >> 3, y);
            guest_write(address, (guest_read(address) & mask) |
                (guest_read(picture++) >> (x0 & 7u)));
        }
    } else if (picture_source_disjoint(picture,
        ((x1 - x0 + 8u) >> 3) * (y1 - y0 + 1u))) {
        /* Prove the complete source span cannot alias LCD RAM, then read
           each byte once. Keep the original read order for other spans. */
        c6502_u8 row[20];
        const c6502_u8 *direct;
        stride = ((c6502_u32)x1 - x0 + 8u) >> 3;
        direct = picture_direct_source(picture, stride * (y1 - y0 + 1u));
        for (y = y0; y <= y1; ++y) {
            const c6502_u8 *source = direct;
            if (direct) { direct += stride; c6502_perf.picture_direct_bytes += stride; }
            else {
                for (x = 0u; x < stride; ++x) row[x] = guest_read(picture++);
                c6502_perf.picture_staged_bytes += stride; source = row;
            }
            blit_packed_row(0x400u, x0, (c6502_u8)y,
                (c6502_u8)(x1 - x0 + 1u), source);
        }
    } else {
        ++c6502_perf.picture_ordered_calls;
        stride = ((c6502_u32)x1 - x0 + 8u) >> 3;
        for (y = y0; y <= y1; ++y)
            for (x = x0; x <= x1; ++x)
                pixel((c6502_u8)x, (c6502_u8)y,
                    (guest_read((c6502_u16)(picture +
                     (y - y0) * stride + ((x - x0) >> 3))) &
                     (0x80u >> ((x - x0) & 7u))) != 0u);
    }
}

static void integer_to_ascii(
    c6502_u32 *r, c6502_u16 value, c6502_u16 output, c6502_u16 radix
)
{
    c6502_u8 digits[18];
    c6502_u16 start = output;
    c6502_u32 count = 0u;
    c6502_u32 magnitude = value;
    int negative = 0;
    if (radix < 2u || radix > 16u)
        radix = 10u;
    if (radix == 10u && (value & 0x8000u)) {
        negative = 1;
        magnitude = (c6502_u16)(0u - value);
    }
    do {
        c6502_u32 digit = magnitude % radix;
        digits[count++] = (c6502_u8)(digit < 10u ? '0' + digit :
            'a' + digit - 10u);
        magnitude /= radix;
    } while (magnitude && count < sizeof(digits));
    if (negative)
        guest_write(output++, '-');
    while (count)
        guest_write(output++, digits[--count]);
    guest_write(output, 0u);
    return16(r, start);
}

#ifdef C6502_NEEDS_c6502_adapter_ltoa
static void long_integer_to_ascii(
    c6502_u32 *r, c6502_u32 value, c6502_u16 output, c6502_u16 radix
)
{
    c6502_u8 digits[34];
    c6502_u16 start = output;
    c6502_u32 count = 0u;
    c6502_u32 magnitude = value;
    int negative = 0;
    if (radix < 2u || radix > 16u)
        radix = 10u;
    if (radix == 10u && (value & 0x80000000u)) {
        negative = 1;
        magnitude = 0u - value;
    }
    do {
        c6502_u32 digit = magnitude % radix;
        digits[count++] = (c6502_u8)(digit < 10u ? '0' + digit :
            'a' + digit - 10u);
        magnitude /= radix;
    } while (magnitude && count < sizeof(digits));
    if (negative)
        guest_write(output++, '-');
    while (count)
        guest_write(output++, digits[--count]);
    guest_write(output, 0u);
    return16(r, start);
}
#endif

#include "c6502_native_query_assets.h"

static void query_box_bitmap(c6502_u8 x, c6502_u8 y, c6502_u8 width,
    c6502_u8 height, const c6502_u8 *image)
{
    c6502_u32 row, stride = (width + 7u) >> 3;
    for (row = 0u; row < height; ++row)
        blit_packed_row(0x400u, x, (c6502_u8)(y + row), width,
            image + row * stride);
}

static void query_box_buttons(c6502_u8 selection)
{
    query_box_bitmap(29u, 49u, 40u, 20u,
        selection == 0u ? query_button_0_1 : query_button_0_0);
    query_box_bitmap(86u, 49u, 40u, 20u,
        selection == 1u ? query_button_1_1 : query_button_1_0);
}

/* E.BIN bank 9 $7540, shared by all C6502 games. sel=0 is Yes, sel=1
   is No; Enter returns sel, Escape returns 0xff. Do not invert raw keys
   or turn cancellation into a positive answer. infoType!=0 is a picture
   descriptor {relative_x,relative_y,height,width,pointer_le16}, not text. */
static void query_box_run(c6502_u32 *r, c6502_u8 selection,
    c6502_u8 info_type, c6502_u16 info)
{
    c6502_u16 old_keyboard = c6502_native_state.keyboard_state;
    c6502_u8 old_type = c6502_native_state.keyboard_type;
    c6502_u8 old_filter = c6502_native_state.input_filter;
    c6502_u8 result = 0xfeu;
    c6502_u32 x, y, length;
    c6502_u8 *saved;
    /* The ROM indexes a two-entry artwork table without bounds checking.
       Reject invalid callers instead of reproducing its out-of-range read. */
    if (selection > 1u) { return8(r, 0xffu); return; }
    saved = (c6502_u8 *)malloc(18u * 59u);
    if (!saved) { return8(r, result); return; }
    c6502_native_state.keyboard_type = 2u;
    c6502_native_state.input_filter = 2u;
    /* SysSaveScreen/RestoreScreen operate on complete aligned bytes. */
    for (y = 0u; y < 59u; ++y)
        for (x = 0u; x < 18u; ++x)
            saved[y * 18u + x] = guest_read(lcd_address(x + 1u, y + 18u));
    for (y = 18u; y <= 76u; ++y) horizontal_span(15u, 146u, (c6502_u8)y, 0);
    rectangle(15u, 18u, 144u, 74u, 0);
    query_box_bitmap(19u, 22u, 24u, 24u, query_icon);
    if (!info_type) {
        for (length = 0u; length + 1u < C6502_RESOURCE_SCRATCH_SIZE; ++length) {
            c6502_resource_scratch[length] = guest_read((c6502_u16)(info + length));
            if (!c6502_resource_scratch[length]) break;
        }
        c6502_resource_scratch[length] = 0u;
        native_text(46u, 26u, c6502_resource_scratch);
    } else {
        c6502_u8 x0 = (c6502_u8)(15u + guest_read(info));
        c6502_u8 y0 = (c6502_u8)(18u + guest_read((c6502_u16)(info + 1u)));
        c6502_u8 height = guest_read((c6502_u16)(info + 2u));
        c6502_u8 width = guest_read((c6502_u16)(info + 3u));
        c6502_u16 pointer = guest_read((c6502_u16)(info + 4u)) |
            ((c6502_u16)guest_read((c6502_u16)(info + 5u)) << 8);
        native_picture(x0, y0, (c6502_u8)(x0 + width - 1u),
            (c6502_u8)(y0 + height - 1u), pointer, 0u);
    }
    rectangle(19u, 74u, 144u, 76u, 1);
    rectangle(144u, 22u, 146u, 76u, 1);
    query_box_buttons(selection);
    c6502_native_present();
    for (;;) {
        c6502_u8 type, key = native_window_key(1);
        native_update_timer();
        c6502_timer_pending = 0u;
        c6502_native_state.ram[0x201eu] &= 0xfeu;
        key = translate_key(key, &type);
        if (type == 5u) {
            if (key == 0x27u) { result = selection; break; }
            if (key == 0x28u) { result = 0xffu; break; }
            if (key >= 0x22u && key <= 0x25u) {
                selection = (c6502_u8)(selection + 1u) & 1u;
                query_box_buttons(selection);
                c6502_native_present();
            }
        } else if (type == 2u) {
            if (key == 'y' || key == 'Y') { result = 0u; break; }
            if (key == 'n' || key == 'N') { result = 1u; break; }
        }
        native_refresh_if_due();
    }
    for (y = 0u; y < 59u; ++y)
        for (x = 0u; x < 18u; ++x)
            guest_write(lcd_address(x + 1u, y + 18u), saved[y * 18u + x]);
    free(saved);
    c6502_native_state.keyboard_state = old_keyboard;
    c6502_native_state.keyboard_type = old_type;
    c6502_native_state.input_filter = old_filter;
    c6502_native_present();
    return8(r, result);
}

/* E.BIN bank 9 $8195: wrap at sixteen bytes without splitting a GBK pair.
   The ROM retains a trailing blank row at an exact line boundary. */
static c6502_u8 message_box_layout(const c6502_u8 *text, c6502_u16 starts[6])
{
    c6502_u32 length = 0u, cursor = 0u, lines = 0u, column = 0u, high = 0u;
    while (text[length]) ++length;
    if (!(c6502_u8)length) return 0u;
    starts[0] = 0u;
    while (lines < 5u && text[cursor]) {
        high = text[cursor] > 0x80u ? high + 1u : 0u;
        if (++column == 16u) {
            ++lines;
            if (!(high & 1u)) {
                starts[lines] = (c6502_u16)(cursor + 1u); column = high = 0u;
            } else {
                starts[lines] = (c6502_u16)cursor; column = high = 1u;
            }
        }
        ++cursor;
    }
    if (lines < 5u) starts[lines + 1u] = (c6502_u16)cursor;
    else --lines;
    return (c6502_u8)(lines + 1u);
}

static void message_box_draw(const c6502_u8 *text, const c6502_u16 starts[6],
    c6502_u8 lines, c6502_u8 top)
{
    c6502_u8 bottom = (c6502_u8)(top + 4u + lines * 16u), y, row;
    for (y = top; y <= bottom + 2u; ++y) horizontal_span(11u, 148u, y, 0);
    for (row = 0u; row < lines; ++row) {
        c6502_u8 part[17];
        c6502_u32 i, count = starts[row + 1u] - starts[row];
        for (i = 0u; i < count; ++i) part[i] = text[starts[row] + i];
        part[count] = 0u;
        native_text(15u, (c6502_u8)(top + 2u + row * 16u), part);
    }
    rectangle(11u, top, 146u, bottom, 0);
    rectangle(14u, bottom, 146u, (c6502_u8)(bottom + 2u), 1);
    rectangle(146u, (c6502_u8)(top + 3u), 148u, (c6502_u8)(bottom + 2u), 1);
}

static void message_box(c6502_u32 *r, c6502_u16 text, c6502_u16 timeout)
{
    c6502_u16 starts[6];
    c6502_u8 *saved, lines, top, height, previous_timer = 0u;
    c6502_u32 i, x, y, started = native_clock(), wait_started, deadline = 0u;
    ++c6502_perf.msgbox_calls;
    c6502_perf.msgbox_last_timeout = timeout;
    for (i = 0u; i + 1u < C6502_RESOURCE_SCRATCH_SIZE; ++i) {
        c6502_resource_scratch[i] = guest_read((c6502_u16)(text + i));
        if (!c6502_resource_scratch[i]) break;
    }
    c6502_resource_scratch[i] = 0u;
    lines = message_box_layout(c6502_resource_scratch, starts);
    if (!lines) { return8(r, 0xffu); return; }
    top = (c6502_u8)((90u - lines * 16u) / 2u);
    height = (c6502_u8)(lines * 16u + 7u);
    saved = (c6502_u8 *)malloc(18u * height);
    if (!saved) { return8(r, 0xfeu); return; }
    c6502_perf.msgbox_last_y = top; c6502_perf.msgbox_last_height = height;
    /* Save complete aligned bytes, as SysSaveScreen does, not masked pixels. */
    for (y = 0u; y < height; ++y)
        for (x = 0u; x < 18u; ++x)
            saved[y * 18u + x] = guest_read(lcd_address(x + 1u, y + top));
    message_box_draw(c6502_resource_scratch, starts, lines, top);
    c6502_native_present();
    if (timeout) {
        c6502_u32 source;
        previous_timer = native_timer_number();
        if (previous_timer) native_timer_close();
        native_timer_open(1u);
        source = c6502_timer_remaining + (timeout - 1u) *
            (256u - c6502_native_state.ram[0x227u]);
        /* A modal deadline is independent of 9288's ~25 ms GUI wake-up.
           Round upwards in 256 Hz ticks; never speed up by counting polls. */
        deadline = (source / C6502_TIMER_SOURCE_HZ) * 256u +
            ((source % C6502_TIMER_SOURCE_HZ) * 256u +
             C6502_TIMER_SOURCE_HZ - 1u) / C6502_TIMER_SOURCE_HZ;
    }
    wait_started = native_clock();
    for (;;) {
        c6502_u8 key = native_window_key(1);
        native_update_timer();
        c6502_timer_pending = 0u;
        c6502_native_state.ram[0x201eu] &= 0xfeu;
        native_refresh_if_due();
        if (key != 0xffu || (timeout && native_clock() - wait_started >= deadline)) break;
    }
    c6502_perf.msgbox_wait_ticks += native_clock() - wait_started;
    if (timeout) {
        native_timer_close();
        if (previous_timer) native_timer_open(previous_timer);
    }
    for (y = 0u; y < height; ++y)
        for (x = 0u; x < 18u; ++x)
            guest_write(lcd_address(x + 1u, y + top), saved[y * 18u + x]);
    free(saved);
    c6502_native_present();
    c6502_perf.msgbox_ticks += native_clock() - started;
    return8(r, 1u);
}

static void query_box(c6502_u32 *r)
{
    query_box_run(r, (c6502_u8)r[4], stack8(r, 0u), stack16(r, 1u));
}

static void api_graphics(c6502_u32 *r, c6502_u32 id)
{
    /* C6502's FAR ABI leaves a leading U8 argument in A.  The remaining
       arguments are evaluated right-to-left and pushed, so they appear in
       source order at stack[0..].  (A leading pointer/U16 is pushed too.)
       All of the A-series drawing calls start with an x coordinate, hence
       x0 comes from the translated A register, not the software stack. */
    c6502_u8 x0 = (c6502_u8)r[4];
    c6502_u8 y0 = stack8(r, 0u);
    c6502_u8 x1 = stack8(r, 1u);
    c6502_u8 y1 = stack8(r, 2u);
    c6502_u16 pointer;
    native_capture_keys();
    if (id == C6502_BRIDGE_c6502_adapter_sysascii) {
        c6502_u8 text[2];
        text[0] = stack8(r, 1u); text[1] = 0u;
        native_text(x0, y0, text);
    } else if (id == C6502_BRIDGE_c6502_adapter_sysprintstring) {
        c6502_u32 length = 0u;
        pointer = stack16(r, 1u);
        while (length + 1u < C6502_RESOURCE_SCRATCH_SIZE) {
            c6502_resource_scratch[length] = guest_read(
                (c6502_u16)(pointer + length));
            if (!c6502_resource_scratch[length++])
                break;
        }
        c6502_resource_scratch[length] = 0u;
        native_text(x0, y0, c6502_resource_scratch);
    } else if (id == C6502_BRIDGE_c6502_adapter_syspicture) {
        pointer = stack16(r, 3u);
        native_picture(x0, y0, x1, y1, pointer, stack8(r, 5u));
        /* LCD stores have already reached the host framebuffer. Keep the
           full-picture counter for diagnostics, not as a flush trigger. */
        if (!x0 && !y0 && x1 >= 158u && y1 >= 95u)
            ++c6502_perf.picture_frame_commits;
    } else if (id == C6502_BRIDGE_c6502_adapter_sysline) {
        line(x0, y0, x1, y1);
    } else if (id == C6502_BRIDGE_c6502_adapter_sysrect) {
        rectangle(x0, y0, x1, y1, 0);
    } else if (id == C6502_BRIDGE_c6502_adapter_sysrectclear) {
        rectangle_clear(x0, y0, x1, y1);
    } else if (id == C6502_BRIDGE_c6502_adapter_sysfillrect) {
        rectangle(x0, y0, x1, y1, 1);
    } else if (id == C6502_BRIDGE_c6502_adapter_syslcdpartclear) {
        c6502_u8 y;
        for (y = y0; y <= y1; ++y) {
            horizontal_span(x0, x1, y, 0);
            if (y == 0xffu) break;
        }
    } else if (id == C6502_BRIDGE_c6502_adapter_syslcdreverse) {
        c6502_u8 y;
        for (y = y0; y <= y1; ++y) {
            horizontal_span(x0, x1, y, 2);
            if (y == 0xffu) break;
        }
    } else if (id == C6502_BRIDGE_c6502_adapter_syspicturedummy) {
        picture_dummy(r);
    } else if (id == C6502_BRIDGE_c6502_adapter_syssavescreen) {
        save_restore_screen(r, 0);
    } else if (id == C6502_BRIDGE_c6502_adapter_sysrestorescreen) {
        save_restore_screen(r, 1);
    }
    native_capture_keys();
}

static void native_strcmp(c6502_u32 *r, c6502_u16 left, c6502_u16 right)
{
    c6502_u8 a, b, difference;
    do {
        a = guest_read(left); b = guest_read(right);
        if (a != b || !a) break;
        ++left; ++right;
    } while (1);
    /* STDLIB.H returns int in $20/$21, not a byte in A. E.BIN $604F
       subtracts bytes then sign-extends the wrapped difference. */
    difference = (c6502_u8)(a - b);
    r[9] = (r[9] & ~(C6502_FLAG_C | C6502_FLAG_V)) |
        (a >= b ? C6502_FLAG_C : 0u) |
        (((a ^ b) & (a ^ difference) & 0x80u) ? C6502_FLAG_V : 0u);
    guest_write(0x23u, b);
    put16(0x26u, right);
    return16(r, (c6502_u16)((difference & 0x80u) ?
        0xff00u | difference : difference));
    r[6] = r[4];
}

#define C6502_FILE_RECORDS 8u
#define C6502_OPEN_FILES 4u
#define C6502_FILE_INDEX_PATH "a:\\G49NIDX.BIN"

typedef struct __attribute__((packed)) C6502_FileRecord {
    c6502_u8 valid;
    c6502_u8 type;
    c6502_u16 name;
    c6502_u8 information[10];
    c6502_u32 length;
} C6502_FileRecord;

typedef struct C6502_OpenFile {
    FS_FILE *stream;
    c6502_u8 record;
} C6502_OpenFile;

static C6502_FileRecord c6502_file_records[C6502_FILE_RECORDS];
static C6502_OpenFile c6502_open_files[C6502_OPEN_FILES];

static char hex_digit(c6502_u32 value)
{
    value &= 15u;
    return (char)(value < 10u ? '0' + value : 'A' + value - 10u);
}

static void file_path(char *path, c6502_u8 type, c6502_u16 name)
{
    const char prefix[] = "a:\\G49";
    c6502_u32 index;
    for (index = 0u; index < sizeof(prefix) - 1u; ++index)
        path[index] = prefix[index];
    path[index++] = hex_digit(type >> 4);
    path[index++] = hex_digit(type);
    path[index++] = hex_digit(name >> 12);
    path[index++] = hex_digit(name >> 8);
    path[index++] = hex_digit(name >> 4);
    path[index++] = hex_digit(name);
    path[index++] = '.'; path[index++] = 'D'; path[index++] = 'A';
    path[index++] = 'T'; path[index] = 0;
}

static void save_file_index(void)
{
    static const c6502_u8 magic[4] = {'G', '4', '9', 'I'};
    FS_FILE *file = fs_fopen(C6502_FILE_INDEX_PATH, "wb");
    if (!file)
        return;
    (void)fs_fwrite(magic, 1, sizeof(magic), file);
    (void)fs_fwrite(c6502_file_records, 1,
        sizeof(c6502_file_records), file);
    (void)fs_update(file);
    (void)fs_fclose(file);
}

static void load_file_index(void)
{
    c6502_u8 magic[4];
    FS_FILE *file;
    bytes_set((c6502_u8 *)c6502_file_records, 0u,
        sizeof(c6502_file_records));
    bytes_set((c6502_u8 *)c6502_open_files, 0u,
        sizeof(c6502_open_files));
    file = fs_fopen(C6502_FILE_INDEX_PATH, "rb");
    if (!file)
        return;
    if (fs_fread(magic, 1, sizeof(magic), file) != sizeof(magic) ||
        magic[0] != 'G' || magic[1] != '4' || magic[2] != '9' ||
        magic[3] != 'I' ||
        fs_fread(c6502_file_records, 1, sizeof(c6502_file_records), file) !=
            sizeof(c6502_file_records))
        bytes_set((c6502_u8 *)c6502_file_records, 0u,
            sizeof(c6502_file_records));
    (void)fs_fclose(file);
}

static int file_record(c6502_u8 type, c6502_u16 name)
{
    c6502_u32 index;
    for (index = 0u; index < C6502_FILE_RECORDS; ++index) {
        if (c6502_file_records[index].valid &&
            c6502_file_records[index].type == type &&
            c6502_file_records[index].name == name)
            return (int)index;
    }
    return -1;
}

static int allocate_open_file(c6502_u32 record, const char *mode)
{
    c6502_u32 index;
    char path[20];
    for (index = 0u; index < C6502_OPEN_FILES; ++index) {
        if (!c6502_open_files[index].stream) {
            file_path(path, c6502_file_records[record].type,
                c6502_file_records[record].name);
            c6502_open_files[index].stream = fs_fopen(path, mode);
            if (!c6502_open_files[index].stream)
                return -1;
            c6502_open_files[index].record = (c6502_u8)record;
            return (int)index;
        }
    }
    return -1;
}

static void api_file(c6502_u32 *r, c6502_u32 id)
{
    c6502_u32 index;
    c6502_u32 count;
    c6502_u32 length;
    c6502_u32 address;
    c6502_u8 handle;
    int record;
    if (id == C6502_BRIDGE_c6502_adapter_filenum) {
        count = 0u;
        for (index = 0u; index < C6502_FILE_RECORDS; ++index)
            if (c6502_file_records[index].valid &&
                c6502_file_records[index].type == (c6502_u8)r[4])
                ++count;
        put16(stack16(r, 0u), (c6502_u16)count);
        return8(r, 1u);
        return;
    }
    if (id == C6502_BRIDGE_c6502_adapter_filesearch) {
        count = stack16(r, 0u);
        for (index = 0u; index < C6502_FILE_RECORDS; ++index) {
            if (!c6502_file_records[index].valid ||
                c6502_file_records[index].type != (c6502_u8)r[4])
                continue;
            if (--count == 0u) {
                put16(stack16(r, 2u), c6502_file_records[index].name);
                address = stack16(r, 4u);
                for (length = 0u; length < 10u; ++length)
                    guest_write((c6502_u16)(address + length),
                        c6502_file_records[index].information[length]);
                return8(r, 1u);
                return;
            }
        }
        return8(r, 0u);
        return;
    }
    if (id == C6502_BRIDGE_c6502_adapter_filecreat) {
        c6502_u16 assigned = 1u;
        int free_record = -1;
        for (index = 0u; index < C6502_FILE_RECORDS; ++index) {
            if (!c6502_file_records[index].valid && free_record < 0)
                free_record = (int)index;
            if (c6502_file_records[index].valid &&
                c6502_file_records[index].type == (c6502_u8)r[4] &&
                c6502_file_records[index].name >= assigned)
                assigned = (c6502_u16)(c6502_file_records[index].name + 1u);
        }
        if (free_record < 0) { return8(r, 0u); return; }
        index = (c6502_u32)free_record;
        c6502_file_records[index].valid = 1u;
        c6502_file_records[index].type = (c6502_u8)r[4];
        c6502_file_records[index].name = assigned;
        c6502_file_records[index].length = guest_get32((c6502_u16)r[10]);
        address = stack16(r, 4u);
        for (length = 0u; length < 10u; ++length)
            c6502_file_records[index].information[length] = guest_read(
                (c6502_u16)(address + length));
        record = allocate_open_file(index, "w+b");
        if (record < 0) {
            c6502_file_records[index].valid = 0u;
            return8(r, 0u); return;
        }
        /* A FileCreat reserves the declared length. Embedded SDK fseek
           need not permit seeking beyond an empty file, unlike desktop C.
           Materialise erased-flash bytes before any game seeks/writes. */
        {
            c6502_u32 remaining = c6502_file_records[index].length;
            int valid = remaining <= 0x200000u;
            bytes_set(c6502_resource_scratch, 0xffu,
                C6502_RESOURCE_SCRATCH_SIZE);
            while (valid && remaining) {
                c6502_u32 amount = remaining > C6502_RESOURCE_SCRATCH_SIZE ?
                    C6502_RESOURCE_SCRATCH_SIZE : remaining;
                if (fs_fwrite(c6502_resource_scratch, 1, amount,
                        c6502_open_files[record].stream) != amount) {
                    valid = 0; break;
                }
                remaining -= amount;
            }
            if (valid) valid = fs_fseek(c6502_open_files[record].stream,
                0, SEEK_SET) >= 0;
            if (!valid) {
                char path[20];
                (void)fs_fclose(c6502_open_files[record].stream);
                c6502_open_files[record].stream = 0;
                file_path(path, c6502_file_records[index].type, assigned);
                (void)fs_remove(path);
                c6502_file_records[index].valid = 0u;
                return8(r, 0u); return;
            }
        }
        put16(stack16(r, 6u), assigned);
        guest_write(stack16(r, 8u), (c6502_u8)record);
        save_file_index();
        return8(r, 1u);
        return;
    }
    if (id == C6502_BRIDGE_c6502_adapter_fileopen) {
        c6502_u16 name = stack16(r, 0u);
        c6502_u8 type = stack8(r, 2u);
        record = file_record(type, name);
        if (record < 0) { return8(r, 0u); return; }
        record = allocate_open_file((c6502_u32)record,
            stack8(r, 3u) == 1u ? "rb" : "r+b");
        if (record < 0) { return8(r, 0u); return; }
        guest_write(stack16(r, 4u), (c6502_u8)record);
        guest_put32(stack16(r, 6u),
            c6502_file_records[c6502_open_files[record].record].length);
        return8(r, 1u);
        return;
    }
    handle = (c6502_u8)r[4];
    if (handle >= C6502_OPEN_FILES || !c6502_open_files[handle].stream) {
        return8(r, 0u);
        return;
    }
    record = c6502_open_files[handle].record;
#ifdef C6502_NEEDS_c6502_adapter_filechangeinf
    if (id == C6502_BRIDGE_c6502_adapter_filechangeinf) {
        address = stack16(r, 0u);
        for (length = 0u; length < 10u; ++length)
            c6502_file_records[record].information[length] = guest_read(
                (c6502_u16)(address + length));
        save_file_index();
        return8(r, 1u);
        return;
    }
#endif
    if (id == C6502_BRIDGE_c6502_adapter_fileclose) {
        (void)fs_update(c6502_open_files[handle].stream);
        (void)fs_fclose(c6502_open_files[handle].stream);
        c6502_open_files[handle].stream = 0;
        save_file_index();
        return8(r, 1u);
        return;
    }
    if (id == C6502_BRIDGE_c6502_adapter_filedel) {
        char path[20];
        (void)fs_fclose(c6502_open_files[handle].stream);
        c6502_open_files[handle].stream = 0;
        file_path(path, c6502_file_records[record].type,
            c6502_file_records[record].name);
        (void)fs_remove(path);
        c6502_file_records[record].valid = 0u;
        save_file_index();
        return8(r, 1u);
        return;
    }
    if (id == C6502_BRIDGE_c6502_adapter_fileseek) {
        c6502_u8 origin = stack8(r, 4u);
        long offset = (long)guest_get32((c6502_u16)r[10]);
        int whence = origin == 1u ? SEEK_SET :
            (origin == 2u ? SEEK_CUR : SEEK_END);
        return8(r, fs_fseek(c6502_open_files[handle].stream,
            offset, whence) >= 0 ? 1u : 0u);
        return;
    }
    length = stack8(r, 0u);
    if (!length)
        length = 256u;
    address = stack16(r, 1u);
    if (id == C6502_BRIDGE_c6502_adapter_fileread) {
        count = fs_fread(c6502_resource_scratch, 1, length,
            c6502_open_files[handle].stream);
        for (index = 0u; index < count; ++index)
            guest_write((c6502_u16)(address + index),
                c6502_resource_scratch[index]);
        return8(r, count == length ? 1u : 0u);
        return;
    }
    if (id == C6502_BRIDGE_c6502_adapter_filewrite) {
        long position;
        for (index = 0u; index < length; ++index)
            c6502_resource_scratch[index] = guest_read(
                (c6502_u16)(address + index));
        count = fs_fwrite(c6502_resource_scratch, 1, length,
            c6502_open_files[handle].stream);
        position = fs_ftell(c6502_open_files[handle].stream);
        if (position > 0 && (c6502_u32)position >
                c6502_file_records[record].length)
            c6502_file_records[record].length = (c6502_u32)position;
        return8(r, count == length ? 1u : 0u);
        return;
    }
    return8(r, 0u);
}

static c6502_u32 signed_div(c6502_u32 left, c6502_u32 right)
{
    int negative = 0;
    if ((long)left < 0) { left = 0u - left; negative ^= 1; }
    if ((long)right < 0) { right = 0u - right; negative ^= 1; }
    if (!right) return 0u;
    left /= right;
    return negative ? 0u - left : left;
}

static c6502_u32 float_multiply_bits(c6502_u32 left, c6502_u32 right)
{
    c6502_u32 sign = (left ^ right) & 0x80000000u;
    c6502_u32 exponent_left = (left >> 23) & 0xffu;
    c6502_u32 exponent_right = (right >> 23) & 0xffu;
    c6502_u32 mantissa_left;
    c6502_u32 mantissa_right;
    c6502_u32 low_product;
    c6502_u32 cross_product;
    c6502_u32 high_product;
    c6502_u32 previous;
    c6502_u32 mantissa;
    long exponent;
    if (!exponent_left || !exponent_right)
        return sign;
    if (exponent_left == 255u || exponent_right == 255u)
        return sign | 0x7f800000u;
    mantissa_left = (left & 0x7fffffu) | 0x800000u;
    mantissa_right = (right & 0x7fffffu) | 0x800000u;
    low_product = (mantissa_left & 0xffffu) *
        (mantissa_right & 0xffffu);
    cross_product = (mantissa_left & 0xffffu) *
        (mantissa_right >> 16) + (mantissa_left >> 16) *
        (mantissa_right & 0xffffu);
    high_product = (mantissa_left >> 16) * (mantissa_right >> 16) +
        (cross_product >> 16);
    previous = low_product;
    low_product += cross_product << 16;
    if (low_product < previous)
        ++high_product;
    exponent = (long)exponent_left + (long)exponent_right - 127;
    if (high_product & 0x8000u) {
        mantissa = (high_product << 8) | (low_product >> 24);
        ++exponent;
    } else {
        mantissa = (high_product << 9) | (low_product >> 23);
    }
    if (exponent <= 0)
        return sign;
    if (exponent >= 255)
        return sign | 0x7f800000u;
    return sign | ((c6502_u32)exponent << 23) | (mantissa & 0x7fffffu);
}

static c6502_u32 float_divide_bits(c6502_u32 left, c6502_u32 right)
{
    c6502_u32 sign = (left ^ right) & 0x80000000u;
    c6502_u32 exponent_left = (left >> 23) & 0xffu;
    c6502_u32 exponent_right = (right >> 23) & 0xffu;
    c6502_u32 numerator;
    c6502_u32 denominator;
    c6502_u32 quotient = 0u;
    c6502_u32 index;
    long exponent;
    if (!exponent_left)
        return sign;
    if (!exponent_right)
        return sign | 0x7f800000u;
    numerator = (left & 0x7fffffu) | 0x800000u;
    denominator = (right & 0x7fffffu) | 0x800000u;
    for (index = 0u; index < 24u; ++index) {
        quotient <<= 1;
        if (numerator >= denominator) {
            numerator -= denominator;
            quotient |= 1u;
        }
        numerator <<= 1;
    }
    exponent = (long)exponent_left - (long)exponent_right + 127;
    if (!(quotient & 0x800000u)) {
        quotient <<= 1;
        --exponent;
    }
    if (exponent <= 0)
        return sign;
    if (exponent >= 255)
        return sign | 0x7f800000u;
    return sign | ((c6502_u32)exponent << 23) | (quotient & 0x7fffffu);
}

static c6502_u32 unsigned_to_float_bits(c6502_u32 value)
{
    c6502_u32 bit = 0u;
    c6502_u32 probe = value;
    if (!value)
        return 0u;
    while (probe >>= 1)
        ++bit;
    return ((127u + bit) << 23) |
        ((value << (23u - bit)) & 0x7fffffu);
}

#ifdef C6502_NEEDS_c6502_runtime_exts_oper2_char_to_float
static c6502_u32 signed_to_float_bits(c6502_u32 value)
{
    c6502_u32 sign = value & 0x80000000u;
    c6502_u32 magnitude = sign ? 0u - value : value;
    c6502_u32 result = unsigned_to_float_bits(magnitude);
    return magnitude ? result | sign : 0u;
}
#endif

#if defined(C6502_NEEDS_c6502_runtime_oper1_float_to_char) || \
    defined(C6502_NEEDS_c6502_runtime_oper1_float_to_int)
static c6502_u32 float_to_signed(c6502_u32 bits)
{
    c6502_u32 exponent = (bits >> 23) & 0xffu;
    c6502_u32 magnitude;
    c6502_u32 mantissa;
    if (exponent < 127u)
        return 0u;
    if (exponent > 158u)
        return (bits & 0x80000000u) ? 0x80000000u : 0x7fffffffu;
    mantissa = (bits & 0x7fffffu) | 0x800000u;
    if (exponent >= 150u)
        magnitude = mantissa << (exponent - 150u);
    else
        magnitude = mantissa >> (150u - exponent);
    return (bits & 0x80000000u) ? 0u - magnitude : magnitude;
}
#endif

#ifdef C6502_NEEDS_c6502_runtime_add_float
static c6502_u32 float_add_bits(c6502_u32 left, c6502_u32 right)
{
    c6502_u32 left_abs = left & 0x7fffffffu;
    c6502_u32 right_abs = right & 0x7fffffffu;
    c6502_u32 left_exp;
    c6502_u32 right_exp;
    c6502_u32 left_mantissa;
    c6502_u32 right_mantissa;
    c6502_u32 sign;
    c6502_u32 mantissa;
    c6502_u32 shift;
    if (!left_abs)
        return right;
    if (!right_abs)
        return left;
    if (left_abs < right_abs) {
        c6502_u32 swap = left;
        left = right;
        right = swap;
    }
    left_exp = (left >> 23) & 0xffu;
    right_exp = (right >> 23) & 0xffu;
    if (left_exp == 255u)
        return left;
    left_mantissa = ((left & 0x7fffffu) | 0x800000u) << 3;
    right_mantissa = ((right & 0x7fffffu) | 0x800000u) << 3;
    shift = left_exp - right_exp;
    right_mantissa = shift >= 28u ? 0u : right_mantissa >> shift;
    sign = left & 0x80000000u;
    if ((left ^ right) & 0x80000000u) {
        mantissa = left_mantissa - right_mantissa;
        if (!mantissa)
            return 0u;
        while (!(mantissa & 0x04000000u) && left_exp) {
            mantissa <<= 1;
            --left_exp;
        }
    } else {
        mantissa = left_mantissa + right_mantissa;
        if (mantissa & 0x08000000u) {
            mantissa >>= 1;
            ++left_exp;
        }
    }
    if (!left_exp)
        return sign;
    if (left_exp >= 255u)
        return sign | 0x7f800000u;
    return sign | (left_exp << 23) | ((mantissa >> 3) & 0x7fffffu);
}
#endif

static void convert_operand_to_float(
    c6502_u32 *r, c6502_u32 zero_page, c6502_u32 size
)
{
    c6502_u16 output = (c6502_u16)(get16(0x2au) +
        (zero_page == 0x20u ? 16u : 32u));
    c6502_u32 value = zero_page == 0x20u ?
        (size == 1u ? (c6502_u8)r[4] : get16(0x20u)) :
        (size == 1u ? c6502_native_state.ram[0x23u] : get16(0x23u));
    guest_put32(output, unsigned_to_float_bits(value));
    put16(zero_page, output);
    r[4] = 0u;
    set_nz(r, 0u);
}

#include "c6502_native_long_shift.h"
#include "c6502_native_key_checkpoint.h"

void c6502_native_bridge(c6502_u32 *r, c6502_u32 id)
{
    c6502_u8 *ram = c6502_native_state.ram;
    c6502_u16 left16;
    c6502_u16 right16;
    c6502_u32 left32;
    c6502_u32 right32;
    c6502_u32 result;
    c6502_u32 address;
    c6502_u32 i;

    native_key_checkpoint(id);
    if (id < C6502_BRIDGE_c6502_direct_read8 &&
            id != C6502_BRIDGE_c6502_adapter_sysgetkey &&
            id != C6502_BRIDGE_c6502_adapter_guitranslatemsg &&
            c6502_validation_trace_count < 128u) {
        volatile c6502_u32 *t =
            c6502_validation_trace[c6502_validation_trace_count++];
        t[0] = id; t[1] = r[4]; t[2] = r[10];
        for (i = 0u; i < 4u; ++i)
            t[3u + i] = guest_get32((c6502_u16)(r[10] + i * 4u));
        t[7] = c6502_native_state.banks[5];
        t[8] = c6502_native_state.banks[9];
        t[9] = get16(0x20u);
    }
    switch (id) {
    case C6502_BRIDGE_c6502_native_set_codebank:
        result = c6502_native_state.banks[5];
        for (i = 0u; i < 4u; ++i)
            c6502_native_state.banks[5u + i] = (c6502_u16)(r[11] + i);
        r[11] = result;
        return;
    case C6502_BRIDGE_c6502_direct_read8:
        r[12] = guest_read((c6502_u16)r[12]); return;
    case C6502_BRIDGE_c6502_direct_write8:
        guest_write((c6502_u16)r[12], (c6502_u8)r[13]); return;
    case C6502_BRIDGE_c6502_sem_materialize_nz:
        set_nz(r, (c6502_u8)r[8]); return;
    case C6502_BRIDGE_c6502_sem_status_to_nz:
        r[8] = (r[9] & C6502_FLAG_Z) ? 0u :
            ((r[9] & C6502_FLAG_N) ? 0x80u : 1u); return;
    case C6502_BRIDGE_c6502_sem_adc8:
        result = (c6502_u8)r[4] + (c6502_u8)r[12] + (r[9] & 1u);
        r[9] = (r[9] & ~(C6502_FLAG_C | C6502_FLAG_V)) |
            (result > 0xffu) |
            ((~(r[4] ^ r[12]) & (r[4] ^ result) & 0x80u) ? C6502_FLAG_V : 0u);
        r[4] = (c6502_u8)result; set_nz(r, (c6502_u8)r[4]); return;
    case C6502_BRIDGE_c6502_sem_sbc8:
        result = (c6502_u8)r[4] - (c6502_u8)r[12] - ((r[9] & 1u) ? 0u : 1u);
        r[9] = (r[9] & ~(C6502_FLAG_C | C6502_FLAG_V)) |
            (((c6502_u8)r[4] >= (c6502_u8)r[12] + ((r[9] & 1u) ? 0u : 1u)) ? 1u : 0u) |
            (((r[4] ^ r[12]) & (r[4] ^ result) & 0x80u) ? C6502_FLAG_V : 0u);
        r[4] = (c6502_u8)result; set_nz(r, (c6502_u8)r[4]); return;
    case C6502_BRIDGE_c6502_sem_cmp8:
        result = (c6502_u8)r[13] - (c6502_u8)r[12];
        r[9] = (r[9] & ~C6502_FLAG_C) |
            ((c6502_u8)r[13] >= (c6502_u8)r[12]);
        set_nz(r, (c6502_u8)result); return;
    case C6502_BRIDGE_c6502_sem_asl_a:
        r[9] = (r[9] & ~1u) | ((r[4] >> 7) & 1u);
        r[4] = (c6502_u8)(r[4] << 1); set_nz(r, (c6502_u8)r[4]); return;
    case C6502_BRIDGE_c6502_sem_lsr_a:
        r[9] = (r[9] & ~1u) | (r[4] & 1u);
        r[4] = (c6502_u8)(r[4] >> 1); set_nz(r, (c6502_u8)r[4]); return;
    case C6502_BRIDGE_c6502_sem_asl_m:
    case C6502_BRIDGE_c6502_sem_lsr_m:
    case C6502_BRIDGE_c6502_sem_rol_m:
#ifdef C6502_NEEDS_c6502_sem_ror_m
    case C6502_BRIDGE_c6502_sem_ror_m:
#endif
    case C6502_BRIDGE_c6502_sem_inc_m:
    case C6502_BRIDGE_c6502_sem_dec_m:
        address = (c6502_u16)r[12]; result = guest_read((c6502_u16)address);
        if (id == C6502_BRIDGE_c6502_sem_asl_m) {
            r[9] = (r[9] & ~1u) | ((result >> 7) & 1u); result <<= 1;
        } else if (id == C6502_BRIDGE_c6502_sem_lsr_m) {
            r[9] = (r[9] & ~1u) | (result & 1u); result >>= 1;
        } else if (id == C6502_BRIDGE_c6502_sem_rol_m) {
            i = r[9] & 1u; r[9] = (r[9] & ~1u) | ((result >> 7) & 1u);
            result = (result << 1) | i;
#ifdef C6502_NEEDS_c6502_sem_ror_m
        } else if (id == C6502_BRIDGE_c6502_sem_ror_m) {
            i = r[9] & 1u; r[9] = (r[9] & ~1u) | (result & 1u);
            result = (result >> 1) | (i << 7);
#endif
        } else if (id == C6502_BRIDGE_c6502_sem_inc_m) {
            result++;
        } else {
            result--;
        }
        result = (c6502_u8)result; guest_write((c6502_u16)address, (c6502_u8)result);
        r[13] = result; set_nz(r, (c6502_u8)result); return;
    case C6502_BRIDGE_c6502_sem_store16_imm:
        semantic_put16(r, r[11], (c6502_u16)r[12]);
        r[4] = (r[12] >> 8) & 0xffu; set_nz(r, (c6502_u8)r[4]); return;
    case C6502_BRIDGE_c6502_sem_copy16:
        result = semantic_get16(r, r[11]);
        semantic_put16(r, r[12], (c6502_u16)result);
        r[4] = result >> 8; set_nz(r, (c6502_u8)r[4]); return;
    case C6502_BRIDGE_c6502_sem_add16:
    case C6502_BRIDGE_c6502_sem_add16_regs:
    case C6502_BRIDGE_c6502_sem_sub16_regs:
        left16 = semantic_get16(r, r[11]);
        right16 = id == C6502_BRIDGE_c6502_sem_add16 ?
            (c6502_u16)r[13] : semantic_get16(r, r[12]);
        result = id == C6502_BRIDGE_c6502_sem_sub16_regs ?
            (c6502_u16)(left16 - right16) : (c6502_u16)(left16 + right16);
        semantic_put16(r,
            id == C6502_BRIDGE_c6502_sem_add16 ? r[12] : r[13],
            (c6502_u16)result);
        r[4] = result >> 8; set_nz(r, (c6502_u8)r[4]); return;
    case C6502_BRIDGE_c6502_sem_load16_indirect:
        address = semantic_get16(r, r[11]) + (c6502_u8)r[13];
        result = guest_read((c6502_u16)address) |
            ((c6502_u16)guest_read((c6502_u16)(address + 1u)) << 8);
        semantic_put16(r, r[12], (c6502_u16)result);
        r[6] = ((c6502_u8)r[13] + 1u) & 0xffu;
        r[4] = result >> 8; set_nz(r, (c6502_u8)r[4]); return;
    case C6502_BRIDGE_c6502_sem_store16_indirect:
        address = semantic_get16(r, r[11]) + (c6502_u8)r[13];
        result = semantic_get16(r, r[12]);
        guest_write((c6502_u16)address, (c6502_u8)result);
        guest_write((c6502_u16)(address + 1u), (c6502_u8)(result >> 8));
        r[6] = ((c6502_u8)r[13] + 1u) & 0xffu;
        r[4] = result >> 8; set_nz(r, (c6502_u8)r[4]); return;

    case C6502_BRIDGE_c6502_runtime_mult_int:
    case C6502_BRIDGE_c6502_runtime_uns_mult_int:
        result = (c6502_u16)(get16(0x20u) * get16(0x23u));
        return16(r, (c6502_u16)result); return;
    case C6502_BRIDGE_c6502_runtime_uns_div_char:
        runtime_divide8(r, 0u); return;
    case C6502_BRIDGE_c6502_runtime_uns_mod_char:
        runtime_divide8(r, 1u); return;
    case C6502_BRIDGE_c6502_runtime_uns_div_int:
        left16 = get16(0x20u); right16 = get16(0x23u);
        return16(r, right16 ? (c6502_u16)(left16 / right16) : 0u); return;
    case C6502_BRIDGE_c6502_runtime_uns_mod_int:
        left16 = get16(0x20u); right16 = get16(0x23u);
        return16(r, right16 ? (c6502_u16)(left16 % right16) : 0u); return;
#ifdef C6502_NEEDS_c6502_runtime_div_int
    case C6502_BRIDGE_c6502_runtime_div_int:
        left16 = get16(0x20u); right16 = get16(0x23u);
        left32 = (left16 & 0x8000u) ? 0xffff0000u | left16 : left16;
        right32 = (right16 & 0x8000u) ? 0xffff0000u | right16 : right16;
        return16(r, right16 ? (c6502_u16)signed_div(left32, right32) : 0u);
        return;
#endif
    case C6502_BRIDGE_c6502_runtime_sl_char:
        runtime_shift(r, 8u, 0u); return;
    case C6502_BRIDGE_c6502_runtime_u_sr_char:
        runtime_shift(r, 8u, 1u); return;
    case C6502_BRIDGE_c6502_runtime_sl_int:
        runtime_shift(r, 16u, 0u); return;
    case C6502_BRIDGE_c6502_runtime_u_sr_int:
        runtime_shift(r, 16u, 1u); return;
#ifdef C6502_NEEDS_c6502_runtime_s_sr_int
    case C6502_BRIDGE_c6502_runtime_s_sr_int:
        return16(r, (c6502_u16)((short)get16(0x20u) >>
            (ram[0x23u] & 15u))); return;
#endif
    case C6502_BRIDGE_c6502_runtime_cmp_int:
        left16 = get16(0x20u); right16 = get16(0x23u);
        runtime_compare16(r, left16, right16); return;
    case C6502_BRIDGE_c6502_runtime_add_long:
    case C6502_BRIDGE_c6502_runtime_sub_long:
    case C6502_BRIDGE_c6502_runtime_uns_mult_long:
    case C6502_BRIDGE_c6502_runtime_uns_div_long:
#ifdef C6502_NEEDS_c6502_runtime_uns_mod_long
    case C6502_BRIDGE_c6502_runtime_uns_mod_long:
#endif
#ifdef C6502_NEEDS_c6502_runtime_and_long
    case C6502_BRIDGE_c6502_runtime_and_long:
#endif
        left32 = long_operand(0x20u); right32 = long_operand(0x23u);
        if (id == C6502_BRIDGE_c6502_runtime_add_long) result = left32 + right32;
        else if (id == C6502_BRIDGE_c6502_runtime_sub_long) result = left32 - right32;
        else if (id == C6502_BRIDGE_c6502_runtime_uns_mult_long) result = left32 * right32;
        else if (id == C6502_BRIDGE_c6502_runtime_uns_div_long)
            result = right32 ? left32 / right32 : 0u;
#ifdef C6502_NEEDS_c6502_runtime_uns_mod_long
        else if (id == C6502_BRIDGE_c6502_runtime_uns_mod_long)
            result = right32 ? left32 % right32 : 0u;
#endif
#ifdef C6502_NEEDS_c6502_runtime_and_long
        else result = left32 & right32;
#else
        else result = 0u;
#endif
        return_long(r, result); return;
#ifdef C6502_NEEDS_c6502_runtime_sl_long
    case C6502_BRIDGE_c6502_runtime_sl_long:
        runtime_shift_long(r, 0); return;
#endif
#ifdef C6502_NEEDS_c6502_runtime_u_sr_long
    case C6502_BRIDGE_c6502_runtime_u_sr_long:
        runtime_shift_long(r, 1); return;
#endif
    case C6502_BRIDGE_c6502_runtime_cmp_long:
        left32 = long_operand(0x20u); right32 = long_operand(0x23u);
        result = left32 - right32;
        r[4] = (c6502_u8)(result >> 24);
        r[6] = 3u;
        r[8] = result == 0u ? 0u : ((result & 0x80000000u) ? 0x80u : 1u);
        r[9] = (r[9] & ~(C6502_FLAG_C | C6502_FLAG_Z |
                C6502_FLAG_V | C6502_FLAG_N)) |
            (left32 >= right32 ? C6502_FLAG_C : 0u) |
            (result == 0u ? C6502_FLAG_Z : 0u) |
            ((result >> 24) & C6502_FLAG_N) |
            (((left32 ^ right32) & (left32 ^ result) & 0x80000000u) ?
                C6502_FLAG_V : 0u);
        return;
    case C6502_BRIDGE_c6502_runtime_neg_long:
        return_long(r, 0u - long_operand(0x20u)); return;
#ifdef C6502_NEEDS_c6502_runtime_neg_int
    case C6502_BRIDGE_c6502_runtime_neg_int:
        return16(r, (c6502_u16)(0u - get16(0x20u))); return;
#endif
    case C6502_BRIDGE_c6502_runtime_store_long:
    case C6502_BRIDGE_c6502_runtime_store_float:
        address = get16(0x20u);
        left32 = long_operand(0x23u);
        guest_put32((c6502_u16)address, left32);
        r[6] = 3u; r[4] = (c6502_u8)(left32 >> 24);
        set_nz(r, (c6502_u8)r[4]); return;
    case C6502_BRIDGE_c6502_runtime_store_long_funct_arg:
        left32 = long_operand(0x20u);
        r[10] = (c6502_u16)(r[10] - 4u);
        guest_put32((c6502_u16)r[10], left32);
        r[6] = 3u; r[4] = (c6502_u8)(left32 >> 24);
        set_nz(r, (c6502_u8)r[4]); return;
#ifdef C6502_NEEDS_c6502_runtime_store_long_oper2_indirect
    case C6502_BRIDGE_c6502_runtime_store_long_oper2_indirect:
        left32 = long_operand(0x20u);
        guest_put32(get16(0x23u), left32);
        r[6] = 3u; r[4] = (c6502_u8)(left32 >> 24);
        set_nz(r, (c6502_u8)r[4]); return;
#endif
    case C6502_BRIDGE_c6502_runtime_exts_oper1_char_to_int:
        put16(0x20u, (r[4] & 0x80u) ?
            (c6502_u16)(0xff00u | (c6502_u8)r[4]) : (c6502_u8)r[4]);
        r[4] = (r[4] & 0x80u) ? 0xffu : 0u;
        set_nz(r, (c6502_u8)r[4]); return;
    case C6502_BRIDGE_c6502_runtime_exts_oper2_char_to_int:
        ram[0x24u] = (ram[0x23u] & 0x80u) ? 0xffu : 0u;
        set_nz(r, ram[0x24u]); return;
#ifdef C6502_NEEDS_c6502_runtime_exts_oper2_char_to_float
    case C6502_BRIDGE_c6502_runtime_exts_oper2_char_to_float:
        left32 = ram[0x23u];
        if (left32 & 0x80u) left32 |= 0xffffff00u;
        address = get16(0x2au) + 32u;
        guest_put32((c6502_u16)address, signed_to_float_bits(left32));
        put16(0x23u, (c6502_u16)address); return;
#endif
    case C6502_BRIDGE_c6502_runtime_oper1_long_to_char:
        return8(r, guest_read(get16(0x20u))); return;
    case C6502_BRIDGE_c6502_runtime_oper1_long_to_int:
        return16(r, (c6502_u16)long_operand(0x20u)); return;
#ifdef C6502_NEEDS_c6502_runtime_oper2_long_to_int
    case C6502_BRIDGE_c6502_runtime_oper2_long_to_int:
        put16(0x23u, (c6502_u16)long_operand(0x23u));
        r[4] = ram[0x24u]; set_nz(r, (c6502_u8)r[4]); return;
#endif
#ifdef C6502_NEEDS_c6502_runtime_oper1_float_to_char
    case C6502_BRIDGE_c6502_runtime_oper1_float_to_char:
        return8(r, (c6502_u8)float_to_signed(long_operand(0x20u))); return;
#endif
#ifdef C6502_NEEDS_c6502_runtime_oper1_float_to_int
    case C6502_BRIDGE_c6502_runtime_oper1_float_to_int:
        return16(r, (c6502_u16)float_to_signed(long_operand(0x20u))); return;
#endif
    case C6502_BRIDGE_c6502_runtime_uns_mult_char:
        return8(r, (c6502_u8)((c6502_u8)r[4] * ram[0x23u])); return;
    case C6502_BRIDGE_c6502_runtime_uns_oper1_char_to_long:
        convert_operand_to_long(r, 0x20u, 1u, 0); return;
    case C6502_BRIDGE_c6502_runtime_uns_oper1_int_to_long:
        convert_operand_to_long(r, 0x20u, 2u, 0); return;
    case C6502_BRIDGE_c6502_runtime_uns_oper2_char_to_long:
        convert_operand_to_long(r, 0x23u, 1u, 0); return;
    case C6502_BRIDGE_c6502_runtime_uns_oper2_int_to_long:
        convert_operand_to_long(r, 0x23u, 2u, 0); return;
    case C6502_BRIDGE_c6502_runtime_uns_oper1_int_to_float:
        convert_operand_to_float(r, 0x20u, 2u); return;
#ifdef C6502_NEEDS_c6502_runtime_uns_oper1_char_to_float
    case C6502_BRIDGE_c6502_runtime_uns_oper1_char_to_float:
        convert_operand_to_float(r, 0x20u, 1u); return;
#endif
    case C6502_BRIDGE_c6502_runtime_uns_oper2_char_to_float:
        convert_operand_to_float(r, 0x23u, 1u); return;
#ifdef C6502_NEEDS_c6502_runtime_uns_oper2_int_to_float
    case C6502_BRIDGE_c6502_runtime_uns_oper2_int_to_float:
        convert_operand_to_float(r, 0x23u, 2u); return;
#endif
#ifdef C6502_NEEDS_c6502_runtime_add_float
    case C6502_BRIDGE_c6502_runtime_add_float:
        return_long(r, float_add_bits(
            long_operand(0x20u), long_operand(0x23u))); return;
#endif
    case C6502_BRIDGE_c6502_runtime_mult_float:
        return_long(r, float_multiply_bits(
            long_operand(0x20u), long_operand(0x23u))); return;
    case C6502_BRIDGE_c6502_runtime_div_float:
        return_long(r, float_divide_bits(
            long_operand(0x20u), long_operand(0x23u))); return;
    case C6502_BRIDGE_c6502_runtime_zero_or_one_char:
        return8(r, (c6502_u8)r[4] == 0u ? 1u : 0u); return;
    case C6502_BRIDGE_c6502_runtime_switch_comparison:
        address = get16(0x26u); left16 = get16(0x23u);
        right16 = (c6502_u16)((r[5] & 0xffu) | ((r[6] & 0xffu) << 8));
        result = get16(0x20u);
        for (i = 0u; i < right16; ++i) {
            if (guest_get16((c6502_u16)(address + i * 2u)) == left16) {
                result = guest_get16((c6502_u16)(address + right16 * 2u + i * 2u));
                break;
            }
        }
        c6502_bridge_target = (c6502_u32)native_target((c6502_u16)result);
        return;
    case C6502_BRIDGE_c6502_runtime_banked_function_call:
        c6502_bridge_target = (c6502_u32)native_target(get16(0x26u)); return;
#ifdef C6502_NEEDS_c6502_runtime_indirect_call
    case C6502_BRIDGE_c6502_runtime_indirect_call:
        c6502_bridge_target = (c6502_u32)native_target(get16(0x26u)); return;
#endif

    case C6502_BRIDGE_c6502_adapter_guigetmsg:
        result = native_timing_input_begin();
        api_get_message(r);
        nt_leave(NT_GETMSG, result, native_clock()); return;
    case C6502_BRIDGE_c6502_adapter_guitranslatemsg:
        api_translate_message(r); return;
    case C6502_BRIDGE_c6502_adapter_guiinit:
    case C6502_BRIDGE_c6502_adapter_flashinit:
    case C6502_BRIDGE_c6502_adapter_sysiconallclear:
    case C6502_BRIDGE_c6502_adapter_sysplaymelody:
    case C6502_BRIDGE_c6502_adapter_sysstopmelody:
        return;
    case C6502_BRIDGE_c6502_adapter_guigetkbdstate:
        return16(r, c6502_native_state.keyboard_state); return;
    case C6502_BRIDGE_c6502_adapter_guisetkbdstate_direct:
        c6502_native_state.keyboard_state = (c6502_u16)r[0]; return;
    case C6502_BRIDGE_c6502_adapter_guisetinputfilter:
        c6502_native_state.input_filter = (c6502_u8)r[4]; return;
    case C6502_BRIDGE_c6502_adapter_guisetkbdtype:
        c6502_native_state.keyboard_type = (c6502_u8)r[4]; return;
    case C6502_BRIDGE_c6502_adapter_guimsgbox:
        result = native_timing_input_begin();
        message_box(r, stack16(r, 0u), stack16(r, 2u));
        nt_leave(NT_DIALOG, result, native_clock()); return;
    case C6502_BRIDGE_c6502_adapter_guimsgbox_direct:
        result = native_timing_input_begin();
        message_box(r, (c6502_u16)r[0], (c6502_u16)r[1]);
        nt_leave(NT_DIALOG, result, native_clock()); return;
    case C6502_BRIDGE_c6502_adapter_guiquerybox:
        result = native_timing_input_begin();
        query_box(r);
        nt_leave(NT_DIALOG, result, native_clock()); return;
    case C6502_BRIDGE_c6502_adapter_guidownapphelp:
    case C6502_BRIDGE_c6502_adapter_guidownapphelp_direct:
        /* The downloadable-app help hook is optional.  Returning false is
           the firmware contract for "help not entered"; game input remains
           owned by its normal GuiGetMsg loop. */
        return8(r, 0u); return;
#ifdef C6502_NEEDS_c6502_adapter_invalid_far_call
    case C6502_BRIDGE_c6502_adapter_invalid_far_call:
        return8(r, 0u); return;
#endif
    case C6502_BRIDGE_c6502_adapter_itoa:
        integer_to_ascii(r, stack16(r, 0u), stack16(r, 2u),
            stack16(r, 4u)); return;
    case C6502_BRIDGE_c6502_adapter_itoa_direct:
        integer_to_ascii(r, (c6502_u16)r[0], (c6502_u16)r[1],
            (c6502_u16)r[2]); return;
#ifdef C6502_NEEDS_c6502_adapter_ltoa
    case C6502_BRIDGE_c6502_adapter_ltoa:
        long_integer_to_ascii(r, guest_get32((c6502_u16)r[10]),
            stack16(r, 4u), stack16(r, 6u)); return;
#endif
    case C6502_BRIDGE_c6502_adapter_systimer1close:
        native_timer_close(); return;
    case C6502_BRIDGE_c6502_adapter_systimer1open:
        native_timer_open((c6502_u8)r[4]); return;
#ifdef C6502_NEEDS_c6502_adapter_sysgettimer1number
    case C6502_BRIDGE_c6502_adapter_sysgettimer1number:
        native_update_timer();
        return8(r, native_timer_number()); return;
#endif
#ifdef C6502_NEEDS_c6502_adapter_sysputpixel
    case C6502_BRIDGE_c6502_adapter_sysputpixel:
        result = nt_enter(native_clock());
        pixel((c6502_u8)r[4], stack8(r, 0u), stack8(r, 1u));
        nt_leave(NT_SHAPE, result, native_clock()); return;
#endif
    case C6502_BRIDGE_c6502_adapter_sysascii:
    case C6502_BRIDGE_c6502_adapter_sysprintstring:
    case C6502_BRIDGE_c6502_adapter_syspicture:
    case C6502_BRIDGE_c6502_adapter_sysline:
    case C6502_BRIDGE_c6502_adapter_sysrect:
    case C6502_BRIDGE_c6502_adapter_sysrectclear:
    case C6502_BRIDGE_c6502_adapter_sysfillrect:
    case C6502_BRIDGE_c6502_adapter_syslcdpartclear:
    case C6502_BRIDGE_c6502_adapter_syslcdreverse:
    case C6502_BRIDGE_c6502_adapter_syspicturedummy:
    case C6502_BRIDGE_c6502_adapter_syssavescreen:
    case C6502_BRIDGE_c6502_adapter_sysrestorescreen:
        result = nt_enter(native_clock());
        left32 = c6502_perf.present_ticks;
        right32 = c6502_perf.picture_frame_commits;
        ++c6502_perf.graphics;
        api_graphics(r, id);
        /* Output is accounted separately, even when a drawing API commits
           a frame itself. Do not charge the same time to both categories. */
        i = native_clock();
        c6502_perf.graphics_ticks += i - result -
            (c6502_perf.present_ticks - left32);
        nt_leave(native_graphics_phase(id), result, i);
        if (right32 != c6502_perf.picture_frame_commits)
            native_timing_frame(1u, i, i - result);
        return;
    case C6502_BRIDGE_c6502_adapter_strlen:
        address = stack16(r, 0u); result = 0u;
        while (guest_read((c6502_u16)(address + result))) ++result;
        return16(r, (c6502_u16)result); return;
    case C6502_BRIDGE_c6502_adapter_strlen_direct:
        address = r[0]; result = 0u;
        while (guest_read((c6502_u16)(address + result))) ++result;
        return16(r, (c6502_u16)result); return;
    case C6502_BRIDGE_c6502_adapter_strcpy_direct:
        address = r[0]; i = r[1];
        do { result = guest_read((c6502_u16)i++); guest_write((c6502_u16)address++, (c6502_u8)result); } while (result);
        return16(r, (c6502_u16)r[0]); return;
    case C6502_BRIDGE_c6502_adapter_strcat_direct:
        address = r[0]; while (guest_read((c6502_u16)address)) ++address;
        i = r[1]; do { result = guest_read((c6502_u16)i++); guest_write((c6502_u16)address++, (c6502_u8)result); } while (result);
        return16(r, (c6502_u16)r[0]); return;
    case C6502_BRIDGE_c6502_adapter_strcmp_direct:
        native_strcmp(r, (c6502_u16)r[0], (c6502_u16)r[1]); return;
    case C6502_BRIDGE_c6502_adapter_sysmemcmp:
        address = stack16(r, 0u); i = stack16(r, 2u); right16 = stack16(r, 4u);
        result = 0u; while (right16--) { left16 = guest_read((c6502_u16)address++); result = guest_read((c6502_u16)i++); if (left16 != result) break; }
        return8(r, left16 == result ? 0u : (left16 < result ? 0xffu : 1u)); return;
    case C6502_BRIDGE_c6502_adapter_sysmemcpy_direct:
    case C6502_BRIDGE_c6502_adapter_fillmem_direct:
        left32 = nt_enter(native_clock());
        address = r[0];
        if (id == C6502_BRIDGE_c6502_adapter_sysmemcpy_direct) {
            i = r[1]; result = r[2];
            while (result--) {
                guest_write((c6502_u16)address++, guest_read((c6502_u16)i++));
                if (!(address & 127u)) native_capture_keys();
            }
        } else {
            /* A-series stdlib declares fillmem(char *dst, int count,
               char value).  The direct transaction keeps those source
               arguments in R0/R1/R2 in that order.  Treating R2 as the
               count turned the common fillmem(0, 255, 0xff) startup clear
               into 65,535 mapped writes and corrupted banked game data. */
            i = r[1]; result = r[2];
            while (i--) {
                guest_write((c6502_u16)address++, (c6502_u8)result);
                if (!(address & 127u)) native_capture_keys();
            }
        }
        nt_leave(NT_MEMORY, left32, native_clock()); return;
    case C6502_BRIDGE_c6502_adapter_fillmem:
        left32 = nt_enter(native_clock());
        address = stack16(r, 0u); i = stack16(r, 2u);
        result = stack8(r, 4u);
        while (i--) {
            guest_write((c6502_u16)address++, (c6502_u8)result);
            if (!(address & 127u)) native_capture_keys();
        }
        nt_leave(NT_MEMORY, left32, native_clock()); return;
    case C6502_BRIDGE_c6502_adapter_sysmeminit_direct:
        native_heap_init((c6502_u16)r[0], (c6502_u16)r[1]); return;
    case C6502_BRIDGE_c6502_adapter_sysmemallocate:
        return16(r, native_heap_allocate(stack16(r, 0u))); return;
    case C6502_BRIDGE_c6502_adapter_sysmemallocate_direct:
        return16(r, native_heap_allocate((c6502_u16)r[0])); return;
    case C6502_BRIDGE_c6502_adapter_sysmemfree:
        return8(r, native_heap_free(stack16(r, 0u))); return;
#ifdef C6502_NEEDS_c6502_adapter_sysmemfree_direct
    case C6502_BRIDGE_c6502_adapter_sysmemfree_direct:
        return8(r, native_heap_free((c6502_u16)r[0])); return;
#endif
    case C6502_BRIDGE_c6502_adapter_sysrand:
    case C6502_BRIDGE_c6502_adapter_sysrand_direct:
        c6502_native_state.random_state = c6502_native_state.random_state * 1103515245u + 12345u;
        return16(r, (c6502_u16)(c6502_native_state.random_state >> 16)); return;
    case C6502_BRIDGE_c6502_adapter_syssrand_direct:
        c6502_native_state.random_state = r[0]; return;
    case C6502_BRIDGE_c6502_adapter_sysgetkey:
        result = native_timing_input_begin();
        api_get_key(r);
        nt_leave(NT_GETKEY, result, native_clock()); return;
    case C6502_BRIDGE_c6502_adapter_sysgetkeysound:
        return8(r, c6502_native_state.key_sound); return;
    case C6502_BRIDGE_c6502_adapter_syssetkeysound:
        c6502_native_state.key_sound = (c6502_u8)r[4]; return;
    case C6502_BRIDGE_c6502_adapter_sysgetsecond:
        return8(r, 0u); return;
    case C6502_BRIDGE_c6502_adapter_getdatabanknumber:
        address = r[4] & 0x0fu;
        put16(stack16(r, 0u), c6502_native_state.banks[address]); return;
    case C6502_BRIDGE_c6502_adapter_databankswitch:
        address = r[4] & 0x0fu; result = stack8(r, 0u);
        left16 = stack16(r, 1u);
        while (result-- && address < 16u) c6502_native_state.banks[address++] = left16++;
        return;
    case C6502_BRIDGE_c6502_adapter_fileclose:
    case C6502_BRIDGE_c6502_adapter_filecreat:
    case C6502_BRIDGE_c6502_adapter_filedel:
    case C6502_BRIDGE_c6502_adapter_filenum:
    case C6502_BRIDGE_c6502_adapter_fileopen:
    case C6502_BRIDGE_c6502_adapter_fileread:
    case C6502_BRIDGE_c6502_adapter_filesearch:
    case C6502_BRIDGE_c6502_adapter_fileseek:
    case C6502_BRIDGE_c6502_adapter_filewrite:
#ifdef C6502_NEEDS_c6502_adapter_filechangeinf
    case C6502_BRIDGE_c6502_adapter_filechangeinf:
#endif
        api_file(r, id); return;
    default:
        if (c6502_missing_bridge_count < 64u)
            c6502_missing_bridge_ids[c6502_missing_bridge_count] = id;
        ++c6502_missing_bridge_count;
        return8(r, 0u);
        return;
    }
}

#ifdef C6502_PROFILE_OTHER
/* Called only by diagnostic bridges. The native caller PC is supplied by
   assembly after saving R8, not extracted from a guessed host C frame.
   Fast RAM assembly and the compiled game functions remain unchanged. */
void c6502_native_bridge_profiled(c6502_u32 *r, c6502_u32 id, c6502_u32 caller)
{
    c6502_u32 started, before_other, stopped;
    NativeProfile *p = &c6502_profile;
    if (!p->active || !id || id >= C6502_BRIDGE_COUNT) {
        c6502_native_bridge(r, id); return;
    }
    p->current_id = id; p->current_pc = caller;
    if (!np_select(id, id < C6502_BRIDGE_c6502_direct_read8)) {
        c6502_native_bridge(r, id); return;
    }
    started = native_clock(); ++p->clock_reads;
    nt_charge(NT_OTHER, started);
    before_other = c6502_timing.phase[NT_OTHER].ticks;
    np_gap(started, before_other, id, caller);
    c6502_native_bridge(r, id);
    stopped = native_clock(); ++p->clock_reads;
    /* Existing APIs have already charged their own phase. This adds only
       their remaining OTHER time, or the entire unclassified helper call. */
    nt_charge(NT_OTHER, stopped);
    np_leave(id, caller, started, before_other, stopped,
        c6502_timing.phase[NT_OTHER].ticks);
}
#endif

int c6502_native_prepare(void)
{
    const c6502_u8 *snapshot;
    c6502_u32 index;
    c6502_u32 packed_regs;
    c6502_u32 status;
    bytes_set((c6502_u8 *)&c6502_native_state, 0u, sizeof(c6502_native_state));
    c6502_native_state.ram = c6502_ram;
    c6502_native_state.game_size = C6502_GAME_SIZE;
#ifdef C6502_EXTERNAL_RESOURCES
    if (!nr_open()) { nr_close(); return 0; }
#else
    c6502_native_state.game = (c6502_u8 *)malloc(C6502_GAME_SIZE);
    if (!c6502_native_state.game)
        return 0;
    if (!lzss_expand(c6502_game_image_lzss_start, c6502_game_image_lzss_end,
            c6502_native_state.game, C6502_GAME_SIZE)) {
        c6502_native_release(); return 0;
    }
#endif
    if (!lzss_expand(c6502_boot_snapshot_lzss_start,
            c6502_boot_snapshot_lzss_end, c6502_boot_raw,
            C6502_BOOT_RAW_SIZE)) {
        c6502_native_release();
        return 0;
    }
    snapshot = c6502_boot_raw;
    if (snapshot[0] != 'C' || snapshot[1] != '6' || snapshot[2] != '5') {
        c6502_native_release();
        return 0;
    }
    for (index = 0u; index < 16u; ++index)
        c6502_native_state.banks[index] = (c6502_u16)(
            snapshot[32u + index * 2u] |
            ((c6502_u16)snapshot[33u + index * 2u] << 8));
    packed_regs = (c6502_u32)snapshot[20] |
        ((c6502_u32)snapshot[21] << 8) |
        ((c6502_u32)snapshot[22] << 16) |
        ((c6502_u32)snapshot[23] << 24);
    status = snapshot[24];
    bytes_set((c6502_u8 *)c6502_entry_regs, 0u, sizeof(c6502_entry_regs));
    c6502_entry_regs[4] = packed_regs & 0xffu;
    c6502_entry_regs[5] = (packed_regs >> 8) & 0xffu;
    c6502_entry_regs[6] = (packed_regs >> 16) & 0xffu;
    c6502_entry_regs[7] = (packed_regs >> 24) & 0xffu;
    c6502_entry_regs[8] = (status & C6502_FLAG_Z) ? 0u :
        ((status & C6502_FLAG_N) ? 0x80u : 1u);
    c6502_entry_regs[9] = status;
    c6502_entry_regs[10] = get16(0x28u);
    c6502_entry_regs[14] = (c6502_u32)c6502_ram;
    c6502_native_state.heap_next = 0x3000u;
    c6502_native_state.random_state = 1u;
    load_file_index();
    c6502_key_initialized = 0u;
    c6502_input_active = 0u;
    c6502_key_head = c6502_key_count = 0u;
    c6502_key_repeat = 0xffu;
    c6502_clock_initialized = 0u;
    c6502_clock_previous = 0u;
    bytes_set((c6502_u8 *)&c6502_clock_diagnostics, 0u, sizeof(c6502_clock_diagnostics));
    c6502_last_frame_tick = native_clock();
    c6502_timer_clock = c6502_last_frame_tick;
    c6502_timer_fraction = 0u;
    c6502_timer_remaining = 256u;
    c6502_timer_pending = 0u;
    c6502_frame_valid = 0u;
    c6502_output_ready = 0u;
    bytes_set((c6502_u8 *)c6502_glyphs, 0u, sizeof(c6502_glyphs));
    c6502_native_state.running = 1u;
    c6502_missing_bridge_count = 0u;
    return 1;
}

void c6502_native_perf_begin(void)
{
    bytes_set((c6502_u8 *)&c6502_perf, 0u, sizeof(c6502_perf));
    /* Reset statistics, not the accepted clock baseline. */
    bytes_set((c6502_u8 *)&c6502_clock_diagnostics, 0u, sizeof(c6502_clock_diagnostics));
    c6502_perf.start = native_clock();
    nt_begin(c6502_perf.start);
#ifdef C6502_PROFILE_OTHER
    np_begin(c6502_perf.start);
#endif
    c6502_last_frame_tick = c6502_perf.start;
    c6502_timer_clock = c6502_perf.start;
    c6502_input_active = 1u;
    c6502_timer_key_deferred = 0u;
    c6502_matrix_unstable_rows = 0u;
    c6502_matrix_action_checks = c6502_matrix_action_rejected = 0u;
    native_key_diagnostics_reset();
    c6502_key_bridge_calls = 0u;
    c6502_key_checkpoint_checks = c6502_key_checkpoint_scans = 0u;
    native_capture_keys(); /* Establish launch-key baseline BEFORE game code. */
}

static void native_log_value(FS_FILE *file, const char *name, c6502_u32 value)
{
    char digits[12], line[64];
    c6502_u32 n = 0u, length = 0u;
    while (name[length] && length < 48u) { line[length] = name[length]; ++length; }
    line[length++] = '=';
    do { digits[n++] = (char)('0' + value % 10u); value /= 10u; } while (value);
    while (n) line[length++] = digits[--n];
    line[length++] = '\n';
    (void)fs_fwrite(line, 1, length, file);
}

static void native_log_csv(FS_FILE *file, const char *tag,
    const c6502_u32 *values, c6502_u32 count)
{
    char line[320], digits[10];
    c6502_u32 length = 0u, i, n, v;
    /* All callers have <= 24 fields; worst-case output is < 280 bytes. */
    if (count > 24u) return;
    while (tag[length] && length < 24u) { line[length] = tag[length]; ++length; }
    for (i = 0u; i < count; ++i) {
        line[length++] = ','; v = values[i]; n = 0u;
        do { digits[n++] = (char)('0' + v % 10u); v /= 10u; } while (v);
        while (n) line[length++] = digits[--n];
    }
    line[length++] = '\n';
    (void)fs_fwrite(line, 1, length, file);
}

static void native_log_timing(FS_FILE *file)
{
    static const char format[] =
        "timing_unit=ctm_tick_1_over_256_second\n"
        "phase_order=other,picture,text,shape,surface,memory,getmsg,getkey,dialog\n"
        "phase_ticks_are_exclusive=1\n"
        "other_includes_native_game_unprofiled_helpers_os_and_probe_overhead=1\n"
        "getmsg_includes_wait_input_and_screen_repair=1\n"
        "legacy_counters_overlap_phase_totals=1\n"
        "frame_kind_1=full_SysPicture_completion_not_vsync\n"
        "frame_kind_2=LCD_activity_at_input_checkpoint_not_game_frame\n"
        "gap_bins_ticks=0,1-2,3-4,5-8,9-16,17-32,33-64,65-128,129-256,257+\n"
        "phase_columns=id,calls,ticks,max_call_ticks,b0,b1,b2,b3,b4,b5,b6,b7,b8,b9\n"
        "interval_columns=kind,events,intervals,min,max,sum,b0,b1,b2,b3,b4,b5,b6,b7,b8,b9\n"
        "sample_columns=seq,kind,at,gap_valid,gap,draw_ticks,reload,number,"
        "other,picture,text,shape,surface,memory,getmsg,getkey,dialog,"
        "timer_generated,timer_delivered,timer_coalesced\n"
        "window_columns=start,elapsed,other,picture,text,shape,surface,memory,"
        "getmsg,getkey,dialog,full_pictures,display_batches\n";
    c6502_u32 i, j, values[24], first, count, sum = 0u;
    NativeTiming *t = &c6502_timing;
    (void)fs_fwrite(format, 1, sizeof(format) - 1u, file);
    native_log_value(file, "timing_storage_bytes", sizeof(*t));
    native_log_value(file, "timing_invalid_deltas", t->invalid_deltas);
    native_log_value(file, "timing_window_fast_forwards", t->window_fast_forwards);
    native_log_value(file, "timing_samples_total", t->sample_count);
    native_log_value(file, "timing_samples_first_capacity", NT_FIRST);
    native_log_value(file, "timing_samples_recent_capacity", NT_RECENT);
    count = t->sample_count < NT_FIRST ? t->sample_count : NT_FIRST;
    native_log_value(file, "timing_samples_omitted", t->sample_count - count - t->recent_count);
    for (i = 0u; i < NT_PHASES; ++i) {
        NativeTimingMetric *m = &t->phase[i];
        values[0] = i; values[1] = m->calls; values[2] = m->ticks; values[3] = m->max_ticks;
        for (j = 0u; j < NT_BINS; ++j) values[4u + j] = m->bins[j];
        native_log_csv(file, "phase", values, 4u + NT_BINS);
        sum += m->ticks;
    }
    native_log_value(file, "phase_ticks_sum", sum);
    native_log_value(file, "phase_elapsed_match", sum == c6502_perf.elapsed);
    for (i = 0u; i < 2u; ++i) {
        NativeTimingFrame *f = &t->frame[i];
        values[0] = i + 1u; values[1] = f->events; values[2] = f->intervals;
        values[3] = f->min_gap; values[4] = f->max_gap; values[5] = f->sum_gap;
        for (j = 0u; j < NT_BINS; ++j) values[6u + j] = f->bins[j];
        native_log_csv(file, "interval", values, 6u + NT_BINS);
    }
    for (i = 0u; i < count; ++i)
        native_log_csv(file, "sample", (c6502_u32 *)&t->first[i],
            sizeof(NativeTimingSample) / sizeof(c6502_u32));
    first = (t->recent_head + NT_RECENT - t->recent_count) % NT_RECENT;
    for (i = 0u; i < t->recent_count; ++i)
        native_log_csv(file, "sample", (c6502_u32 *)&t->recent[(first + i) % NT_RECENT],
            sizeof(NativeTimingSample) / sizeof(c6502_u32));
    first = (t->window_head + NT_WINDOWS - t->window_count) % NT_WINDOWS;
    for (i = 0u; i < t->window_count; ++i)
        native_log_csv(file, "window", (c6502_u32 *)&t->windows[(first + i) % NT_WINDOWS],
            sizeof(NativeTimingWindow) / sizeof(c6502_u32));
    if (t->current.elapsed)
        native_log_csv(file, "window", (c6502_u32 *)&t->current,
            sizeof(NativeTimingWindow) / sizeof(c6502_u32));
}

#include "c6502_native_log.h"

#ifdef C6502_PROFILE_OTHER
static void native_log_profile(FS_FILE *file)
{
    static const char format[] =
        "profile_other_version=1\n"
        "profile_pc_kind=native_return_address_not_guest_pc_or_full_stack\n"
        "profile_gaps_include_native_game_unsampled_helpers_os_probe_overhead=1\n"
        "profile_bridge_ticks_include_probe_overhead_and_interrupts=1\n"
        "profile_helper_sampling=first_then_pseudorandom_1_to_127_calls\n"
        "profile_helper_target_stride=64\n"
        "profile_helper_ticks_are_measured_samples_not_extrapolated=1\n"
        "profile_other_is_subset_of_phase_other_do_not_add_again=1\n"
        "profile_bridge_columns=id,calls,samples,wall_ticks,other_ticks,max_sample_ticks\n"
        "profile_edge_columns=from_id,from_pc,to_id,to_pc,nonzero_intervals,other_ticks,max_other_ticks\n"
        "profile_spike_columns=from_id,from_pc,to_id,to_pc,at,wall_ticks,other_ticks\n"
        "profile_keygap_columns=from_id,from_pc,to_id,to_pc,at,wall_ticks,unused\n";
    NativeProfile *p = &c6502_profile;
    c6502_u32 i, n, v[6], sum = p->gap_other + p->bridge_other;
    (void)fs_fwrite(format, 1, sizeof(format) - 1u, file);
    native_log_value(file, "profile_storage_bytes", sizeof(*p));
    native_log_value(file, "profile_clock_reads", p->clock_reads);
    native_log_value(file, "profile_invalid_deltas", p->invalid);
    native_log_value(file, "profile_gap_intervals", p->gaps);
    native_log_value(file, "profile_gap_other_ticks", p->gap_other);
    native_log_value(file, "profile_measured_bridge_other_ticks", p->bridge_other);
    native_log_value(file, "profile_other_sum", sum);
    native_log_value(file, "profile_other_match", sum == c6502_timing.phase[NT_OTHER].ticks);
    native_log_value(file, "profile_edge_capacity", NP_EDGES);
    native_log_value(file, "profile_edge_overflow_intervals", p->edge_overflow_calls);
    native_log_value(file, "profile_edge_overflow_ticks", p->edge_overflow_ticks);
    native_log_value(file, "profile_spike_events", p->spike_events);
    native_log_value(file, "profile_keygap_events", p->key_events);
    native_log_value(file, "profile_spike_capacity_each", NP_SPIKES);
    for (i = 1u; i < C6502_BRIDGE_COUNT; ++i) {
        NPBridge *b = &p->bridge[i];
        if (!b->calls) continue;
        v[0] = i; v[1] = b->calls; v[2] = b->samples;
        v[3] = b->ticks; v[4] = b->other; v[5] = b->max_ticks;
        native_log_csv(file, "profile_bridge", v, 6u);
        native_log_csv(file, "profile_name_id", v, 1u);
        n = 0u; while (c6502_profile_names[i][n]) ++n;
        (void)fs_fwrite("profile_name=", 1, 13, file);
        (void)fs_fwrite(c6502_profile_names[i], 1, n, file);
        (void)fs_fwrite("\n", 1, 1, file);
    }
    for (i = 0u; i < NP_EDGES; ++i)
        if (p->edges[i].calls)
            native_log_csv(file, "profile_edge", (const c6502_u32 *)&p->edges[i], 7u);
    for (i = 0u; i < NP_SPIKES; ++i) {
        if (p->spikes[i].wall)
            native_log_csv(file, "profile_spike", (const c6502_u32 *)&p->spikes[i], 7u);
        if (p->keys[i].wall)
            native_log_csv(file, "profile_keygap", (const c6502_u32 *)&p->keys[i], 7u);
    }
}
#endif

void c6502_native_perf_end(void)
{
    FS_FILE *file;
    int log_ok;
#ifdef C6502_PROFILE_OTHER
    static const char header[] = "[A9288 NATIVE PERF 6]\nbuild=OTHER-PROFILE-1\nclock_hz=256\n";
#else
    static const char header[] = "[A9288 NATIVE PERF 5]\nbuild=CLOCK-GUARD-1\nclock_hz=256\n";
#endif
    c6502_u32 stopped = native_clock();
    nt_charge(NT_OTHER, stopped);
#ifdef C6502_PROFILE_OTHER
    np_gap(stopped, c6502_timing.phase[NT_OTHER].ticks, 0u, 0u);
    c6502_profile.active = 0u;
#endif
    c6502_timing.active = 0u;
    c6502_perf.elapsed = stopped - c6502_perf.start;
    file = fs_fopen("a:\\NATIVE.TMP", "wb");
    if (!file) return;
    (void)fs_fwrite(header, 1, sizeof(header) - 1u, file);
    native_log_value(file, "game_size", C6502_GAME_SIZE);
#ifdef C6502_EXTERNAL_RESOURCES
    native_log_value(file, "external_resources", 1u);
    native_log_value(file, "resource_cache_bytes", NR_SLOTS*NR_PAGE);
    native_log_value(file, "resource_cache_hits", nr_hits);
    native_log_value(file, "resource_cache_misses", nr_misses);
    native_log_value(file, "resource_dirty_pages", nr_dirty_count);
    native_log_value(file, "resource_writes", nr_writes);
    native_log_value(file, "resource_error", nr_error);
#endif
#ifdef NATIVE_TITLE
    (void)fs_fwrite("game=", 1, 5, file);
    (void)fs_fwrite(NATIVE_TITLE, 1, sizeof(NATIVE_TITLE) - 1u, file);
    (void)fs_fwrite("\n", 1, 1, file);
#endif
#define NATIVE_LOG(field) native_log_value(file, #field, c6502_perf.field)
    NATIVE_LOG(elapsed);
    NATIVE_LOG(polls); NATIVE_LOG(poll_ticks);
    NATIVE_LOG(waits); NATIVE_LOG(wait_ticks);
    NATIVE_LOG(graphics); NATIVE_LOG(graphics_ticks);
    NATIVE_LOG(presents); NATIVE_LOG(present_ticks);
    NATIVE_LOG(submissions); NATIVE_LOG(dirty_rows);
    NATIVE_LOG(mapped_lcd_bytes); NATIVE_LOG(framebuffer_bytes); NATIVE_LOG(repair_checks);
    NATIVE_LOG(lcd_span_rows); NATIVE_LOG(lcd_span_bytes);
    NATIVE_LOG(picture_direct_bytes); NATIVE_LOG(picture_staged_bytes); NATIVE_LOG(picture_ordered_calls);
    NATIVE_LOG(key_scans); NATIVE_LOG(key_scan_max_gap_ticks);
    NATIVE_LOG(key_edges); NATIVE_LOG(key_repeats); NATIVE_LOG(keys_consumed);
    NATIVE_LOG(key_queue_peak); NATIVE_LOG(key_queue_overflows);
    native_log_value(file, "key_action_bounces", c6502_action_bounces);
    native_log_value(file, "key_checkpoint_interval_calls", C6502_KEY_CHECKPOINT_INTERVAL);
    native_log_value(file, "key_bridge_calls", c6502_key_bridge_calls);
    native_log_value(file, "key_checkpoint_checks", c6502_key_checkpoint_checks);
    native_log_value(file, "key_checkpoint_scans", c6502_key_checkpoint_scans);
    {
        c6502_u32 i, row[4], first;
        static const char format[] =
            "key_code_columns=code,edges,repeats,consumed\n"
            "key_gap_bins_ticks=0-4,5-8,9-16,17-32,33-64,65+\n"
            "key_gap_columns=seq,end_tick,gap,previous_scan_last_bridge,current_last_bridge,row7\n"
            "key_gap_bridge_ids_are_endpoint_context_not_time_attribution=1\n"
            "key_event_columns=seq,tick,code,kind,queue_depth_after\n"
            "key_event_kinds=0:edge,1:repeat,2:poll_consume,3:wait_consume\n";
        (void)fs_fwrite(format, 1, sizeof(format) - 1u, file);
        for (i = 0u; i < 64u; ++i) {
            if (!c6502_key_code_counts[i][0] && !c6502_key_code_counts[i][1] &&
                !c6502_key_code_counts[i][2]) continue;
            row[0] = i; row[1] = c6502_key_code_counts[i][0];
            row[2] = c6502_key_code_counts[i][1]; row[3] = c6502_key_code_counts[i][2];
            native_log_csv(file, "key_code", row, 4u);
        }
        native_log_csv(file, "key_gap_bins", c6502_key_gap_bins, 6u);
        first = c6502_key_gap_count > 8u ? c6502_key_gap_count - 8u : 0u;
        native_log_value(file, "key_gap_trace_overwritten", first);
        for (i = first; i < c6502_key_gap_count; ++i)
            native_log_csv(file, "key_gap", c6502_key_gaps[i & 7u], 6u);
        first = c6502_key_event_count > 32u ? c6502_key_event_count - 32u : 0u;
        native_log_value(file, "key_event_trace_overwritten", first);
        for (i = first; i < c6502_key_event_count; ++i)
            native_log_csv(file, "key_event", c6502_key_events[i & 31u], 5u);
    }
    native_log_value(file, "key_matrix_unstable_rows", c6502_matrix_unstable_rows);
    native_log_value(file, "key_matrix_action_checks", c6502_matrix_action_checks);
    native_log_value(file, "key_matrix_action_rejected", c6502_matrix_action_rejected);
    {
        c6502_u32 n = c6502_matrix_action_checks > 8u ? 8u : c6502_matrix_action_checks;
        c6502_u32 first = c6502_matrix_action_checks - n, i;
        native_log_value(file, "key_matrix_trace_overwritten", first);
        for (i = first; i < c6502_matrix_action_checks; ++i)
            native_log_csv(file, "key_matrix_action", c6502_matrix_actions[i & 7u], 6u);
    }
    NATIVE_LOG(glyph_hits); NATIVE_LOG(glyph_misses); NATIVE_LOG(timer_steps);
    NATIVE_LOG(timer_irqs); NATIVE_LOG(timer_opens); NATIVE_LOG(timer_closes);
    NATIVE_LOG(timer_messages_delivered); NATIVE_LOG(key_messages_delivered);
    NATIVE_LOG(timer_coalesced); NATIVE_LOG(timer_update_max_gap_ticks); NATIVE_LOG(timer_burst_max);
    NATIVE_LOG(timer_key_deferrals); NATIVE_LOG(timer_key_yields);
    NATIVE_LOG(timer_backward_rejected);
    NATIVE_LOG(timer_advance_chunks); NATIVE_LOG(timer_advance_chunks_max);
    {
        NativeClockDiagnostics *d = &c6502_clock_diagnostics;
        c6502_u32 i, first = d->backwards > 8u ? d->backwards - 8u : 0u;
        static const char format[] = "clock_backstep_columns=seq,raw,previous,backward_ticks\n";
        native_log_value(file, "clock_backward_samples", d->backwards);
        native_log_value(file, "clock_max_backstep_ticks", d->max_backstep);
        native_log_value(file, "clock_snapshot_retries", d->snapshot_retries);
        native_log_value(file, "clock_retry_exhausted", d->exhausted);
        native_log_value(file, "clock_forward_wraps", d->wraps);
        native_log_value(file, "clock_backstep_trace_overwritten", first);
        (void)fs_fwrite(format, 1, sizeof(format) - 1u, file);
        for (i = first; i < d->backwards; ++i)
            native_log_csv(file, "clock_backstep", d->trace[i & 7u], 4u);
    }
    NATIVE_LOG(picture_frame_commits);
    NATIVE_LOG(msgbox_calls); NATIVE_LOG(msgbox_ticks); NATIVE_LOG(msgbox_wait_ticks);
    NATIVE_LOG(msgbox_last_timeout); NATIVE_LOG(msgbox_last_y); NATIVE_LOG(msgbox_last_height);
    native_log_value(file, "timer_reload", c6502_native_state.ram[0x227u]);
    native_log_value(file, "timer_period_number", native_timer_number());
    native_log_value(file, "session_start_clock_tick", c6502_perf.start);
    native_log_value(file, "session_end_clock_tick", stopped);
#undef NATIVE_LOG
    native_log_timing(file);
#ifdef C6502_PROFILE_OTHER
    native_log_profile(file);
#endif
    (void)fs_fwrite("[END]\n", 1, 6, file);
    log_ok = !fs_ferror(file);
    if (fs_update(file)) log_ok = 0;
    if (fs_fclose(file)) log_ok = 0;
    if (log_ok) (void)native_log_commit();
}

void c6502_native_release(void)
{
    c6502_u32 index;
#ifdef C6502_EXTERNAL_RESOURCES
    nr_close();
#endif
    for (index = 0u; index < C6502_OPEN_FILES; ++index) {
        if (c6502_open_files[index].stream) {
            (void)fs_update(c6502_open_files[index].stream);
            (void)fs_fclose(c6502_open_files[index].stream);
            c6502_open_files[index].stream = 0;
        }
    }
    save_file_index();
    if (c6502_native_state.game)
        free(c6502_native_state.game);
    c6502_native_state.game = 0;
}

const char *c6502_native_resource_error(void)
{
#ifdef C6502_EXTERNAL_RESOURCES
    switch (nr_error) {
    /* Short GBK messages fit the firmware's fixed-width MessageBox. */
    case 1: return "\xc8\xb1\xc9\xd9\xd7\xca\xd4\xb4\xce\xc4\xbc\xfe";
    case 2: return "\xd7\xca\xd4\xb4\xce\xc4\xbc\xfe\xb2\xbb\xc6\xa5\xc5\xe4";
    case 3: return "\xd7\xca\xd4\xb4\xc4\xda\xb4\xe6\xb2\xbb\xd7\xe3";
    case 4: return "\xd7\xca\xd4\xb4\xb6\xc1\xc8\xa1\xca\xa7\xb0\xdc";
    case 5: return "\xd7\xca\xd4\xb4\xd0\xa3\xd1\xe9\xca\xa7\xb0\xdc";
    case 6: return "\xd7\xca\xd4\xb4\xd0\xb4\xc8\xeb\xc4\xda\xb4\xe6\xb3\xac\xcf\xde";
    }
#endif
    return 0;
}
