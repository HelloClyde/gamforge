/* Private matrix acquisition only: no queue consumption or GUI messages.
 * The caller owns the short IRQ-masked transaction and restores all ports.
 * Right (row 7), Enter (row 1), and Exit (rows 0/5) share column 6.
 * Break-before-make and discard reads prevent a previous row's low column
 * level from being immediately interpreted as a different physical key.
 * These are bounded MMIO settling reads, not a millisecond input delay. */
#define C6502_MATRIX_SETTLE_READS 4u
static c6502_u32 c6502_matrix_unstable_rows;
static c6502_u32 c6502_matrix_action_checks, c6502_matrix_action_rejected;
/* Last eight independent action rechecks: seq,tick,row,first,verify,right. */
static c6502_u32 c6502_matrix_actions[8][6];

static c6502_u8 native_matrix_columns(void)
{
    c6502_u8 k5 = *hardware_byte(C6502_K5_DATA_ADDRESS);
    c6502_u8 p0 = *hardware_byte(C6502_PORT0_DATA_ADDRESS);
    return (c6502_u8)(((c6502_u8)~k5 & 15u) | ((c6502_u8)~p0 & 0x70u));
}

static void native_matrix_settle(void)
{
    c6502_u32 i;
    for (i = 0u; i < C6502_MATRIX_SETTLE_READS; ++i) {
        (void)*hardware_byte(C6502_K5_DATA_ADDRESS);
        (void)*hardware_byte(C6502_PORT0_DATA_ADDRESS);
    }
}

static c6502_u8 native_matrix_row(c6502_u32 row, c6502_u8 previous)
{
    c6502_u8 first, second, changing;
    *hardware_byte(C6502_KEY_ROW_SELECT_ADDRESS) = 0xffu;
    native_matrix_settle();
    *hardware_byte(C6502_KEY_ROW_SELECT_ADDRESS) = (c6502_u8)~(1u << row);
    native_matrix_settle();
    first = native_matrix_columns();
    second = native_matrix_columns();
    changing = first ^ second;
    if (changing) ++c6502_matrix_unstable_rows;
    /* Defer only changing bits to the next scan, not the entire row.
     * In particular, a one-sample release must not re-arm a held key. */
    return (c6502_u8)((first & second) | (changing & previous));
}

static void native_matrix_snapshot(c6502_u8 current[8], c6502_u32 now)
{
    c6502_u32 row;
    for (row = 0u; row < 8u; ++row)
        current[row] = native_matrix_row(row,
            c6502_key_initialized ? c6502_key_previous[row] : 0u);
    /* New action presses get another, independently selected row sample.
     * Do not globally mask Exit while Right is held: real chords must work. */
    for (row = 0u; row < 6u; ++row) {
        c6502_u8 verify;
        c6502_u32 *trace;
        if (row != 0u && row != 1u && row != 5u) continue;
        if (!(current[row] & 64u) ||
            (c6502_key_initialized && (c6502_key_previous[row] & 64u))) continue;
        verify = native_matrix_row(row, 0u);
        trace = c6502_matrix_actions[c6502_matrix_action_checks & 7u];
        trace[0] = ++c6502_matrix_action_checks;
        trace[1] = now; trace[2] = row;
        trace[3] = current[row]; trace[4] = verify; trace[5] = current[7];
        if (!(verify & 64u)) {
            current[row] &= (c6502_u8)~64u;
            ++c6502_matrix_action_rejected;
        }
    }
    *hardware_byte(C6502_KEY_ROW_SELECT_ADDRESS) = 0xffu;
    native_matrix_settle();
}
