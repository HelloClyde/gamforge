#ifndef S6502_IRAM_EXEC_ABI_H
#define S6502_IRAM_EXEC_ABI_H

/* Shared C/S1C33 contract for the resident 65C02 execution loop.
 *
 * Keep every context member 32-bit.  Besides making the assembly offsets
 * unambiguous, this lets the resident loop keep the six guest registers in
 * host registers without loading or storing packed byte fields on every
 * entry.  Pointer fields are 32-bit target addresses, not native C pointers;
 * GAM4980_IRAM_EXEC_ASM is therefore only valid on the 32-bit 9288 target.
 */

#define S6502_IRAM_ASM_CONTEXT_SIZE                100u
#define S6502_IRAM_ASM_CONTEXT_PC_OFFSET             0u
#define S6502_IRAM_ASM_CONTEXT_AC_OFFSET             4u
#define S6502_IRAM_ASM_CONTEXT_IX_OFFSET             8u
#define S6502_IRAM_ASM_CONTEXT_IY_OFFSET            12u
#define S6502_IRAM_ASM_CONTEXT_SP_OFFSET            16u
#define S6502_IRAM_ASM_CONTEXT_STATUS_OFFSET        20u
#define S6502_IRAM_ASM_CONTEXT_CYCLE_BUDGET_OFFSET  24u
#define S6502_IRAM_ASM_CONTEXT_PAGES_OFFSET         28u
#define S6502_IRAM_ASM_CONTEXT_PAGE_KIND_OFFSET     32u
#define S6502_IRAM_ASM_CONTEXT_RAM_OFFSET           36u
#define S6502_IRAM_ASM_CONTEXT_DIRTY_OFFSET         40u
#define S6502_IRAM_ASM_CONTEXT_DISPATCH_BITS_OFFSET 44u
#define S6502_IRAM_ASM_CONTEXT_CYCLES_OFFSET        48u
#define S6502_IRAM_ASM_CONTEXT_INSTRUCTIONS_OFFSET  52u
#define S6502_IRAM_ASM_CONTEXT_TRANSITIONS_OFFSET   56u
#define S6502_IRAM_ASM_CONTEXT_EXIT_REASON_OFFSET   60u
#define S6502_IRAM_ASM_CONTEXT_CODE_PAGES_OFFSET    64u
#define S6502_IRAM_ASM_CONTEXT_SUPER_HITS_OFFSET    68u
#define S6502_IRAM_ASM_CONTEXT_NATIVE_ENTRY_OFFSET  72u
#define S6502_IRAM_ASM_CONTEXT_NATIVE_METRICS_OFFSET 76u
#define S6502_IRAM_ASM_CONTEXT_READ8_OFFSET          80u
#define S6502_IRAM_ASM_CONTEXT_WRITE8_OFFSET         84u
#define S6502_IRAM_ASM_CONTEXT_NATIVE_EPOCH_OFFSET   88u
#define S6502_IRAM_ASM_CONTEXT_LCD_WRITES_OFFSET     92u
#define S6502_IRAM_ASM_CONTEXT_LCD_CHANGES_OFFSET    96u

#define S6502_IRAM_PAGE_READ_DIRECT  0x01u
#define S6502_IRAM_PAGE_WRITE_DIRECT 0x02u
#define S6502_IRAM_PAGE_FETCH_DIRECT 0x04u
#define S6502_IRAM_PAGE_FORCE_PB_ZERO 0x08u
#define S6502_IRAM_PAGE_FORCE_APO_FF  0x10u

#define S6502_IRAM_EXIT_SLOW     1u
#define S6502_IRAM_EXIT_DEADLINE 2u
#define S6502_IRAM_EXIT_DISPATCH 3u

#define S6502_IRAM_RESULT_FORCE_EXIT 0x80000000u
#define S6502_IRAM_RESULT_CYCLES_MASK 0x7fffffffu

#ifndef __ASSEMBLER__

#include <stddef.h>
#include "gam4980_types.h"

typedef struct s6502_iram_asm_context {
    uint32_t pc;
    uint32_t ac;
    uint32_t ix;
    uint32_t iy;
    uint32_t sp;
    uint32_t status;
    uint32_t cycle_budget;
    uint32_t pages;
    uint32_t page_kind;
    uint32_t ram;
    uint32_t dirty;
    uint32_t dispatch_bits;
    uint32_t cycles;
    uint32_t instructions;
    uint32_t control_transitions;
    uint32_t exit_reason;
    uint32_t code_pages;
    uint32_t super_hits;
    uint32_t native_shared_entry;
    uint32_t native_shared_metrics;
    uint32_t read8;
    uint32_t write8;
    uint32_t native_epoch;
    uint32_t lcd_write_calls;
    uint32_t lcd_changed_writes;
} s6502_iram_asm_context_t;

#define S6502_IRAM_ABI_ASSERT(member, offset_value) \
    _Static_assert(offsetof(s6502_iram_asm_context_t, member) == \
        (offset_value), "s6502 IRAM ABI offset mismatch: " #member)

_Static_assert(sizeof(uint32_t) == 4u,
    "s6502 IRAM ABI requires 32-bit uint32_t");
_Static_assert(sizeof(s6502_iram_asm_context_t) ==
    S6502_IRAM_ASM_CONTEXT_SIZE, "s6502 IRAM ABI size mismatch");
S6502_IRAM_ABI_ASSERT(pc, S6502_IRAM_ASM_CONTEXT_PC_OFFSET);
S6502_IRAM_ABI_ASSERT(ac, S6502_IRAM_ASM_CONTEXT_AC_OFFSET);
S6502_IRAM_ABI_ASSERT(ix, S6502_IRAM_ASM_CONTEXT_IX_OFFSET);
S6502_IRAM_ABI_ASSERT(iy, S6502_IRAM_ASM_CONTEXT_IY_OFFSET);
S6502_IRAM_ABI_ASSERT(sp, S6502_IRAM_ASM_CONTEXT_SP_OFFSET);
S6502_IRAM_ABI_ASSERT(status, S6502_IRAM_ASM_CONTEXT_STATUS_OFFSET);
S6502_IRAM_ABI_ASSERT(
    cycle_budget, S6502_IRAM_ASM_CONTEXT_CYCLE_BUDGET_OFFSET);
S6502_IRAM_ABI_ASSERT(pages, S6502_IRAM_ASM_CONTEXT_PAGES_OFFSET);
S6502_IRAM_ABI_ASSERT(page_kind, S6502_IRAM_ASM_CONTEXT_PAGE_KIND_OFFSET);
S6502_IRAM_ABI_ASSERT(ram, S6502_IRAM_ASM_CONTEXT_RAM_OFFSET);
S6502_IRAM_ABI_ASSERT(dirty, S6502_IRAM_ASM_CONTEXT_DIRTY_OFFSET);
S6502_IRAM_ABI_ASSERT(
    dispatch_bits, S6502_IRAM_ASM_CONTEXT_DISPATCH_BITS_OFFSET);
S6502_IRAM_ABI_ASSERT(cycles, S6502_IRAM_ASM_CONTEXT_CYCLES_OFFSET);
S6502_IRAM_ABI_ASSERT(
    instructions, S6502_IRAM_ASM_CONTEXT_INSTRUCTIONS_OFFSET);
S6502_IRAM_ABI_ASSERT(
    control_transitions, S6502_IRAM_ASM_CONTEXT_TRANSITIONS_OFFSET);
S6502_IRAM_ABI_ASSERT(
    exit_reason, S6502_IRAM_ASM_CONTEXT_EXIT_REASON_OFFSET);
S6502_IRAM_ABI_ASSERT(
    code_pages, S6502_IRAM_ASM_CONTEXT_CODE_PAGES_OFFSET);
S6502_IRAM_ABI_ASSERT(
    super_hits, S6502_IRAM_ASM_CONTEXT_SUPER_HITS_OFFSET);
S6502_IRAM_ABI_ASSERT(
    native_shared_entry, S6502_IRAM_ASM_CONTEXT_NATIVE_ENTRY_OFFSET);
S6502_IRAM_ABI_ASSERT(
    native_shared_metrics, S6502_IRAM_ASM_CONTEXT_NATIVE_METRICS_OFFSET);
S6502_IRAM_ABI_ASSERT(read8, S6502_IRAM_ASM_CONTEXT_READ8_OFFSET);
S6502_IRAM_ABI_ASSERT(write8, S6502_IRAM_ASM_CONTEXT_WRITE8_OFFSET);
S6502_IRAM_ABI_ASSERT(
    native_epoch, S6502_IRAM_ASM_CONTEXT_NATIVE_EPOCH_OFFSET);
S6502_IRAM_ABI_ASSERT(
    lcd_write_calls, S6502_IRAM_ASM_CONTEXT_LCD_WRITES_OFFSET);
S6502_IRAM_ABI_ASSERT(
    lcd_changed_writes, S6502_IRAM_ASM_CONTEXT_LCD_CHANGES_OFFSET);

#undef S6502_IRAM_ABI_ASSERT

/* Atomic fallback contract:
 *
 * - SLOW leaves pc at the first unexecuted instruction.
 * - A zero-cycle SLOW return must not change guest registers, RAM, bank state
 *   or *dirty.  The C interpreter can then execute exactly one instruction.
 * - Once an instruction has committed RAM, it must also be reflected in
 *   cycles and in the output register state; it may not return zero.
 * - DEADLINE and DISPATCH return cycles | FORCE_EXIT.  SLOW does not set the
 *   high bit, allowing the C interpreter to make the one-instruction fallback.
 */
uint32_t s6502_iram_exec_burst_asm(s6502_iram_asm_context_t *context);

#endif /* !__ASSEMBLER__ */

#endif /* S6502_IRAM_EXEC_ABI_H */
