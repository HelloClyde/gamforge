/* Load-time game AOT templates.  Included inside s6502_exec(). */

#define S6502_GAME_AOT_JMP(target) do {                                     \
    pc = (uint16_t)(target); CYCLES(3);                                     \
    if ((executed >= cycles) || sys_halt_p()) goto _aot_return;             \
    S6502_GAME_AOT_DISPATCH();                                              \
    goto _next;                                                             \
} while (0)

#define S6502_GAME_AOT_NEXT(byte_count) do {                                \
    pc = (uint16_t)(pc + (byte_count));                                     \
    /* The base interpreter intentionally runs a straight-line region past  \
     * the requested budget and returns only at a control-flow boundary.    \
     * Returning here would move IRQ delivery into the middle of a C6502    \
     * expression and is observably different on the real games. */        \
    if (s6502_game_aot_enabled && s6502_game_aot_requested &&               \
        game_aot_entry->linear_next_entry &&                                \
        game_aot_entry->linear_next_entry <= s6502_game_aot_entry_limit) {  \
        uint16_t aot_linear_id = game_aot_entry->linear_next_entry;         \
        const s6502_game_aot_entry_t *aot_linear_entry =                    \
            &s6502_game_aot_entries[aot_linear_id - 1u];                    \
        if (!aot_linear_entry->semantic ||                                  \
            (s6502_game_aot_semantic_mask &                                 \
                (1u << (aot_linear_entry->semantic - 1u)))) {               \
            game_aot_entry_id = aot_linear_id;                              \
            game_aot_entry = aot_linear_entry;                              \
            game_aot_physical_pc = aot_linear_entry->physical_pc;           \
            game_aot_code = s6502_game_aot_code_base +                     \
                (aot_linear_entry->physical_pc - 0x20d000u);                \
            ++s6502_game_aot_linear_link_hits;                              \
            goto _game_aot_dispatch;                                        \
        }                                                                   \
    }                                                                       \
    S6502_GAME_AOT_DISPATCH();                                              \
    goto _next;                                                             \
} while (0)

  _game_aot_dispatch:
    switch (game_aot_entry->pattern) {
    case 0u: goto _game_aot_0;
    case 1u: goto _game_aot_1;
    case 2u: goto _game_aot_2;
    case 3u: goto _game_aot_3;
    case 4u: goto _game_aot_4;
    case 5u: goto _game_aot_5;
    case 6u: goto _game_aot_6;
    case 7u: goto _game_aot_far_call;
    case 8u: goto _game_aot_load_oper1_imm16;
    case 9u: goto _game_aot_load_oper2_imm16;
    case 10u: goto _game_aot_stack_add16;
    case 11u: goto _game_aot_stack_sub16;
    case 12u: goto _game_aot_store_char_arg_imm;
    case 13u: goto _game_aot_store_int_arg_oper1;
    case 14u: goto _game_aot_load_oper1_zp16;
    case 15u: goto _game_aot_load_oper2_zp16;
    case 16u: goto _game_aot_add16_oper1_oper2;
    case 17u: goto _game_aot_sub16_oper1_oper2;
    case 18u: goto _game_aot_load_oper1_indy16;
    case 19u: goto _game_aot_store_oper1_indy16;
    case S6502_GAME_AOT_TRACE_PATTERN: goto _game_aot_linear_trace;
    default: goto _next;
    }

  _game_aot_0:
    S6502_GAME_AOT_HIT(10u);
    S6502_AOT_LDA(game_aot_code[1], 2, 0x00u);
    S6502_AOT_STA_ZP(game_aot_code[3], 3);
    S6502_AOT_LDA(game_aot_code[5], 2, 0x00u);
    S6502_AOT_STA_ZP(game_aot_code[7], 3);
    S6502_AOT_LDY(game_aot_code[9], 2, 0x00u);
    S6502_AOT_LDA_INDY(S6502_AOT_ZP16(game_aot_code[11]), 0x00u);
    S6502_AOT_STA_ZP(game_aot_code[13], 3);
    S6502_AOT_LDA(game_aot_code[15], 2, 0x82u);
    S6502_AOT_STA_ZP(game_aot_code[17], 3);
    S6502_AOT_JSR(
        (uint16_t)(pc + 20u),
        (uint16_t)(game_aot_code[19] | (game_aot_code[20] << 8))
    );

  _game_aot_1:
    S6502_GAME_AOT_HIT(7u);
    S6502_AOT_LDY(game_aot_code[1], 2, 0x00u);
    S6502_AOT_LDA_INDY(S6502_AOT_ZP16(game_aot_code[3]), 0x00u);
    S6502_AOT_CLC(0x01u);
    S6502_AOT_ADC(game_aot_code[6], 2, 0x41u);
    S6502_AOT_LDY(game_aot_code[8], 2, 0x82u);
    S6502_AOT_STA_INDY(S6502_AOT_ZP16(game_aot_code[10]));
    S6502_GAME_AOT_JMP(
        (uint16_t)(game_aot_code[12] | (game_aot_code[13] << 8))
    );

  _game_aot_2:
    S6502_GAME_AOT_HIT(5u);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(game_aot_code[1]), 3, 0x00u);
    S6502_AOT_ASL_A(0x00u);
    S6502_AOT_ASL_A(0x83u);
    S6502_AOT_STA_ZP(game_aot_code[5], 3);
    S6502_GAME_AOT_JMP(
        (uint16_t)(game_aot_code[7] | (game_aot_code[8] << 8))
    );

  _game_aot_3:
    S6502_GAME_AOT_HIT(3u);
    S6502_AOT_INX(0x00u);
    S6502_AOT_COMPARE(ix, game_aot_code[2], 2, 0x83u);
    ea = (uint16_t)(pc + 5u);
    et = (uint16_t)(ea + (int8_t)game_aot_code[4]);
    S6502_AOT_BRANCH(!ZERO_p, ea, et);

  _game_aot_4:
    S6502_GAME_AOT_HIT(3u);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(game_aot_code[1]), 3, 0x00u);
    S6502_AOT_AND(game_aot_code[3], 2, 0x82u);
    ea = (uint16_t)(pc + 6u);
    et = (uint16_t)(ea + (int8_t)game_aot_code[5]);
    S6502_AOT_BRANCH(ZERO_p, ea, et);

  _game_aot_5:
    S6502_GAME_AOT_HIT(2u);
    S6502_AOT_COMPARE(ac, game_aot_code[1], 2, 0x83u);
    ea = (uint16_t)(pc + 4u);
    et = (uint16_t)(ea + (int8_t)game_aot_code[3]);
    S6502_AOT_BRANCH(!ZERO_p, ea, et);

  _game_aot_6:
    S6502_GAME_AOT_HIT(20u);
    S6502_AOT_LDY(game_aot_code[1], 2, 0x00u);
    S6502_AOT_LDA_INDY(S6502_AOT_ZP16(game_aot_code[3]), 0x00u);
    S6502_AOT_STA_ZP(game_aot_code[5], 3);
    S6502_AOT_INY(0x00u);
    S6502_AOT_LDA_INDY(S6502_AOT_ZP16(game_aot_code[8]), 0x00u);
    S6502_AOT_STA_ZP(game_aot_code[10], 3);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(game_aot_code[12]), 3, 0x00u);
    S6502_AOT_CLC(0x01u);
    S6502_AOT_ADC(game_aot_code[15], 2, 0x01u);
    S6502_AOT_STA_ZP(game_aot_code[17], 3);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(game_aot_code[19]), 3, 0x00u);
    S6502_AOT_ADC(game_aot_code[21], 2, 0x41u);
    S6502_AOT_STA_ZP(game_aot_code[23], 3);
    S6502_AOT_LDY(game_aot_code[25], 2, 0x00u);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(game_aot_code[27]), 3, 0x00u);
    S6502_AOT_STA_INDY(S6502_AOT_ZP16(game_aot_code[29]));
    S6502_AOT_INY(0x00u);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(game_aot_code[32]), 3, 0x82u);
    S6502_AOT_STA_INDY(S6502_AOT_ZP16(game_aot_code[34]));
    S6502_GAME_AOT_JMP(
        (uint16_t)(game_aot_code[36] | (game_aot_code[37] << 8))
    );

  _game_aot_far_call:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_FAR_CALL);
    /* C6502 .bf_call prefix.  For the verified compiler/runtime ABI, fold
     * __banked_function_call, get-current-bank, switch-bank and the indirect
     * D572 call into one exact state transition.  The target's RTS still
     * returns to the real D313 suffix, which restores the old bank. */
    if (s6502_game_aot_direct_links_enabled &&
        game_aot_entry->linked_physical_pc && !DECIMAL_p) {
      S6502_GAME_AOT_DIRECT_LINK_STAGE(0);
    if (s6502_game_aot_direct_link_match()) {
      S6502_GAME_AOT_DIRECT_LINK_STAGE(1);
      uint16_t aot_table = game_aot_entry->linked_table_address;
      uint16_t aot_target = (uint16_t)(
          READ8(aot_table) |
          ((uint16_t)READ8((uint16_t)(aot_table + 1u)) << 8)
      );
      uint8_t aot_target_bank = READ8((uint16_t)(aot_table + 2u));
      uint16_t aot_current_base = s6502_game_aot_banks[5];
      uint16_t aot_firmware_base = (uint16_t)(
          READ8(0x03d6u) | ((uint16_t)READ8(0x03d5u) << 8)
      );
      uint16_t aot_game_base = (uint16_t)(
          S6502_FAST_STACK_RAM[0x2029u] |
          ((uint16_t)S6502_FAST_STACK_RAM[0x202au] << 8)
      );
      uint16_t aot_source_base;
      uint16_t aot_target_base;
      uint16_t aot_target_minus_one;
      uint16_t aot_direct_cycles;
      uint8_t aot_current_bank;
      uint8_t aot_source_marker;
      uint8_t aot_original_a = ac;
      uint8_t aot_original_sp = sp;
      uint8_t aot_high_result;
      uint8_t aot_bank_slot;

      if (aot_target == game_aot_entry->linked_virtual_pc &&
          aot_target_bank == game_aot_entry->linked_bank_number &&
          aot_target >= 0x5000u && aot_target < 0x9000u) {
        S6502_GAME_AOT_DIRECT_LINK_STAGE(2);
        /* F4A5 chooses its base from the current page-high comparison. */
        if ((uint8_t)(aot_current_base >> 8) >=
            READ8(0x03d5u)) {
          aot_source_base = aot_firmware_base;
          aot_source_marker = 0u;
          aot_direct_cycles = 108u;
        } else {
          aot_source_base = aot_game_base;
          aot_source_marker = 0xe0u;
          aot_direct_cycles = 110u;
        }
        if (aot_current_base >= aot_source_base &&
            ((aot_current_base - aot_source_base) & 3u) == 0u) {
          S6502_GAME_AOT_DIRECT_LINK_STAGE(3);
          aot_current_bank = (uint8_t)(
              aot_source_marker +
              ((aot_current_base - aot_source_base) >> 2)
          );
          if (aot_target_bank >= 0xe0u) {
            aot_source_base = aot_game_base;
            aot_target_base = (uint16_t)(
                aot_game_base +
                ((uint16_t)(aot_target_bank - 0xe0u) << 2)
            );
            aot_direct_cycles = (uint16_t)(aot_direct_cycles + 213u);
          } else {
            aot_source_base = aot_firmware_base;
            aot_target_base = (uint16_t)(
                aot_firmware_base + ((uint16_t)aot_target_bank << 2)
            );
            aot_direct_cycles = (uint16_t)(aot_direct_cycles + 207u);
          }
          /* Prefix + D2F6/D572 fixed instructions and the two possible
           * (zp),Y page crossings for table bytes 2 and 1. */
          aot_direct_cycles = (uint16_t)(
              aot_direct_cycles + 120u +
              (((aot_table & 0xffu) + 2u) > 0xffu) +
              (((aot_table & 0xffu) + 1u) > 0xffu)
          );
          if ((uint32_t)aot_direct_cycles <= cycles - executed) {
            S6502_GAME_AOT_DIRECT_LINK_STAGE(4);
            aot_target_minus_one = (uint16_t)(aot_target - 1u);

            /* Final observable stack image at target entry. */
            S6502_FAST_STACK_RAM[0x100u | aot_original_sp] =
                (uint8_t)((pc + 10u) >> 8);
            S6502_FAST_STACK_RAM[0x100u |
                (uint8_t)(aot_original_sp - 1u)] = (uint8_t)(pc + 10u);
            S6502_FAST_STACK_RAM[0x100u |
                (uint8_t)(aot_original_sp - 2u)] = aot_current_bank;
            S6502_FAST_STACK_RAM[0x100u |
                (uint8_t)(aot_original_sp - 3u)] = 0xd3u;
            S6502_FAST_STACK_RAM[0x100u |
                (uint8_t)(aot_original_sp - 4u)] = 0x12u;
            S6502_FAST_STACK_RAM[0x100u |
                (uint8_t)(aot_original_sp - 5u)] =
                (uint8_t)(aot_target_minus_one >> 8);
            S6502_FAST_STACK_RAM[0x100u |
                (uint8_t)(aot_original_sp - 6u)] =
                (uint8_t)aot_target_minus_one;
            S6502_FAST_STACK_RAM[0x100u |
                (uint8_t)(aot_original_sp - 7u)] = 2u;

            /* Preserve the final RAM and page-0 bank-register results from
             * F52A while rebuilding each final window only once. */
            S6502_FAST_STACK_RAM[0x2001u] = (uint8_t)aot_source_base;
            S6502_FAST_STACK_RAM[0x2002u] =
                (uint8_t)(aot_source_base >> 8);
            for (aot_bank_slot = 5u; aot_bank_slot <= 8u;
                 ++aot_bank_slot) {
              uint16_t aot_page = (uint16_t)(
                  aot_target_base + (aot_bank_slot - 5u)
              );
              s6502_game_aot_banks[aot_bank_slot] = aot_page;
              mem_bs(aot_bank_slot);
            }
            WRITE8(0x000cu, 8u);
            S6502_FAST_STACK_RAM[0x2000u] =
                (uint8_t)((aot_target_base + 3u) >> 8);

            /* D572 leaves target-1 in the compiler address register and
             * A/X/Y equal to the caller's A.  Its final high-byte SBC owns
             * C/V; TYA then owns N/Z. */
            S6502_FAST_STACK_RAM[0x26u] =
                (uint8_t)aot_target_minus_one;
            S6502_FAST_STACK_RAM[0x27u] =
                (uint8_t)(aot_target_minus_one >> 8);
            aot_high_result = (uint8_t)(aot_target_minus_one >> 8);
            status = (uint8_t)(
                (status & ~(FLAG_N | FLAG_V | FLAG_Z | FLAG_C)) |
                FLAG_U | FLAG_B |
                (aot_original_a & FLAG_N) |
                (!aot_original_a ? FLAG_Z : 0u) |
                FLAG_C |
                (((((aot_target >> 8) ^ aot_high_result) &
                    (aot_target >> 8) & 0x80u) != 0u) ? FLAG_V : 0u)
            );
            ac = aot_original_a;
            ix = aot_original_a;
            iy = aot_original_a;
            sp = (uint8_t)(aot_original_sp - 5u);
            pc = aot_target;
            CYCLES(aot_direct_cycles);
            ++s6502_game_aot_direct_link_hits;
            S6502_GAME_AOT_HIT(39u);
            goto _exit;
          }
        }
      }
    }
    }
    S6502_GAME_AOT_HIT(5u);
    S6502_AOT_LDX(game_aot_code[1], 2, 0x00u);
    S6502_AOT_STX_ZP(game_aot_code[3], 3);
    S6502_AOT_LDX(game_aot_code[5], 2, 0x82u);
    S6502_AOT_STX_ZP(game_aot_code[7], 3);
    S6502_AOT_JSR(
        (uint16_t)(pc + 10u),
        (uint16_t)(game_aot_code[9] | (game_aot_code[10] << 8))
    );

  _game_aot_load_oper1_imm16:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_LOAD_OPER1_IMM16);
    S6502_GAME_AOT_HIT(4u);
    S6502_AOT_LDA(game_aot_code[1], 2, 0x00u);
    S6502_AOT_STA_ZP(game_aot_code[3], 3);
    S6502_AOT_LDA(game_aot_code[5], 2, 0x82u);
    S6502_AOT_STA_ZP(game_aot_code[7], 3);
    S6502_GAME_AOT_NEXT(8u);

  _game_aot_load_oper2_imm16:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_LOAD_OPER2_IMM16);
    S6502_GAME_AOT_HIT(4u);
    S6502_AOT_LDA(game_aot_code[1], 2, 0x00u);
    S6502_AOT_STA_ZP(game_aot_code[3], 3);
    S6502_AOT_LDA(game_aot_code[5], 2, 0x82u);
    S6502_AOT_STA_ZP(game_aot_code[7], 3);
    S6502_GAME_AOT_NEXT(8u);

  _game_aot_stack_add16:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_STACK_ADD16);
    {
      uint16_t aot_stack_value;
      uint16_t aot_stack_delta;

      S6502_GAME_AOT_HIT(10u);
      PUSH(status | FLAG_B | FLAG_U);
      aot_stack_value = (uint16_t)(
          S6502_AOT_ZP_READ(0x28u) |
          ((uint16_t)S6502_AOT_ZP_READ(0x29u) << 8)
      );
      aot_stack_delta = (uint16_t)(
          game_aot_code[6] | ((uint16_t)game_aot_code[12] << 8)
      );
      aot_stack_value = (uint16_t)(aot_stack_value + aot_stack_delta);
      S6502_FAST_STACK_RAM[0x28u] = (uint8_t)aot_stack_value;
      S6502_FAST_STACK_RAM[0x29u] = (uint8_t)(aot_stack_value >> 8);
      ac = (uint8_t)(aot_stack_value >> 8);
      status = (uint8_t)(POP() | FLAG_U | FLAG_B);
      CYCLES(27u);
      S6502_GAME_AOT_NEXT(16u);
    }

  _game_aot_stack_sub16:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_STACK_SUB16);
    {
      uint16_t aot_stack_value;
      uint16_t aot_stack_delta;

      S6502_GAME_AOT_HIT(10u);
      PUSH(status | FLAG_B | FLAG_U);
      aot_stack_value = (uint16_t)(
          S6502_AOT_ZP_READ(0x28u) |
          ((uint16_t)S6502_AOT_ZP_READ(0x29u) << 8)
      );
      aot_stack_delta = (uint16_t)(
          game_aot_code[6] | ((uint16_t)game_aot_code[12] << 8)
      );
      aot_stack_value = (uint16_t)(aot_stack_value - aot_stack_delta);
      S6502_FAST_STACK_RAM[0x28u] = (uint8_t)aot_stack_value;
      S6502_FAST_STACK_RAM[0x29u] = (uint8_t)(aot_stack_value >> 8);
      ac = (uint8_t)(aot_stack_value >> 8);
      status = (uint8_t)(POP() | FLAG_U | FLAG_B);
      CYCLES(27u);
      S6502_GAME_AOT_NEXT(16u);
    }

  _game_aot_store_char_arg_imm:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_STORE_CHAR_ARG_IMM);
    S6502_GAME_AOT_HIT(2u);
    S6502_AOT_LDA(game_aot_code[1], 2, 0x82u);
    S6502_AOT_JSR(
        (uint16_t)(pc + 4u),
        (uint16_t)(game_aot_code[3] | (game_aot_code[4] << 8))
    );

  _game_aot_store_int_arg_oper1:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_STORE_INT_ARG_OPER1);
    S6502_GAME_AOT_HIT(1u);
    S6502_AOT_JSR(
        (uint16_t)(pc + 2u),
        (uint16_t)(game_aot_code[1] | (game_aot_code[2] << 8))
    );

  _game_aot_load_oper1_zp16:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_LOAD_OPER1_ZP16);
    S6502_GAME_AOT_HIT(4u);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(game_aot_code[1]), 3, 0x00u);
    S6502_AOT_STA_ZP(game_aot_code[3], 3);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(game_aot_code[5]), 3, 0x82u);
    S6502_AOT_STA_ZP(game_aot_code[7], 3);
    S6502_GAME_AOT_NEXT(8u);

  _game_aot_load_oper2_zp16:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_LOAD_OPER2_ZP16);
    S6502_GAME_AOT_HIT(4u);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(game_aot_code[1]), 3, 0x00u);
    S6502_AOT_STA_ZP(game_aot_code[3], 3);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(game_aot_code[5]), 3, 0x82u);
    S6502_AOT_STA_ZP(game_aot_code[7], 3);
    S6502_GAME_AOT_NEXT(8u);

  _game_aot_add16_oper1_oper2:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_ADD16_OPER1_OPER2);
    S6502_GAME_AOT_HIT(7u);
    S6502_AOT_CLC(0x01u);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(0x20u), 3, 0x00u);
    S6502_AOT_ADC(S6502_AOT_ZP_READ(0x23u), 3, 0x01u);
    S6502_AOT_STA_ZP(0x20u, 3);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(0x21u), 3, 0x00u);
    S6502_AOT_ADC(S6502_AOT_ZP_READ(0x24u), 3, 0xc3u);
    S6502_AOT_STA_ZP(0x21u, 3);
    S6502_GAME_AOT_NEXT(13u);

  _game_aot_sub16_oper1_oper2:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_SUB16_OPER1_OPER2);
    S6502_GAME_AOT_HIT(7u);
    S6502_AOT_SEC(0x01u);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(0x20u), 3, 0x00u);
    S6502_AOT_SBC(S6502_AOT_ZP_READ(0x23u), 3, 0x01u);
    S6502_AOT_STA_ZP(0x20u, 3);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(0x21u), 3, 0x00u);
    S6502_AOT_SBC(S6502_AOT_ZP_READ(0x24u), 3, 0xc3u);
    S6502_AOT_STA_ZP(0x21u, 3);
    S6502_GAME_AOT_NEXT(13u);

  _game_aot_load_oper1_indy16:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_LOAD_OPER1_INDY16);
    S6502_GAME_AOT_HIT(6u);
    S6502_AOT_LDY(game_aot_code[1], 2, 0x00u);
    S6502_AOT_LDA_INDY(S6502_AOT_ZP16(game_aot_code[3]), 0x00u);
    S6502_AOT_STA_ZP(game_aot_code[5], 3);
    S6502_AOT_INY(0x00u);
    S6502_AOT_LDA_INDY(S6502_AOT_ZP16(game_aot_code[8]), 0x82u);
    S6502_AOT_STA_ZP(game_aot_code[10], 3);
    S6502_GAME_AOT_NEXT(11u);

  _game_aot_store_oper1_indy16:
    S6502_GAME_AOT_SEMANTIC_HIT(C6502_TEMPLATE_STORE_OPER1_INDY16);
    S6502_GAME_AOT_HIT(6u);
    S6502_AOT_LDY(game_aot_code[1], 2, 0x00u);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(game_aot_code[3]), 3, 0x00u);
    S6502_AOT_STA_INDY(S6502_AOT_ZP16(game_aot_code[5]));
    S6502_AOT_INY(0x00u);
    S6502_AOT_LDA(S6502_AOT_ZP_READ(game_aot_code[8]), 3, 0x82u);
    S6502_AOT_STA_INDY(S6502_AOT_ZP16(game_aot_code[10]));
    S6502_GAME_AOT_NEXT(11u);

  _game_aot_linear_trace:
    {
      uint8_t trace_offset = 0u;
      uint8_t trace_instruction = 0u;

      S6502_GAME_AOT_HIT(game_aot_entry->memory_class);
      if (s6502_game_aot_metrics_enabled) {
        ++s6502_game_aot_trace_hits;
        s6502_game_aot_trace_instruction_hits +=
            game_aot_entry->memory_class;
      }
      while (trace_instruction < game_aot_entry->memory_class) {
        uint8_t trace_opcode = game_aot_code[trace_offset];
        uint8_t trace_operand = trace_offset + 1u < game_aot_entry->size
            ? game_aot_code[trace_offset + 1u] : 0u;
        uint16_t trace_base;
        uint16_t trace_address;

        switch (trace_opcode) {
        case 0x08u: S6502_AOT_PHP(); trace_offset += 1u; break;
        case 0x0au: S6502_AOT_ASL_A(0x83u); trace_offset += 1u; break;
        case 0x18u: S6502_AOT_CLC(0x01u); trace_offset += 1u; break;
        case 0x28u: S6502_AOT_PLP(); trace_offset += 1u; break;
        case 0x2au: S6502_AOT_ROL_A(0x83u); trace_offset += 1u; break;
        case 0x38u: S6502_AOT_SEC(0x01u); trace_offset += 1u; break;
        case 0x48u: S6502_AOT_PHA(); trace_offset += 1u; break;
        case 0x4au: S6502_AOT_LSR_A(0x83u); trace_offset += 1u; break;
        case 0x58u:
          status = (uint8_t)(status & ~FLAG_I); CYCLES(2);
          trace_offset += 1u; break;
        case 0x68u: S6502_AOT_PLA(0x82u); trace_offset += 1u; break;
        case 0x6au: S6502_AOT_ROR_A(0x83u); trace_offset += 1u; break;
        case 0x78u:
          status = (uint8_t)(status | FLAG_I); CYCLES(2);
          trace_offset += 1u; break;
        case 0x88u: S6502_AOT_DEY(0x82u); trace_offset += 1u; break;
        case 0x8au: S6502_AOT_TXA(0x82u); trace_offset += 1u; break;
        case 0x98u: S6502_AOT_TYA(0x82u); trace_offset += 1u; break;
        case 0x9au: S6502_AOT_TXS(); trace_offset += 1u; break;
        case 0xa8u: S6502_AOT_TAY(0x82u); trace_offset += 1u; break;
        case 0xaau: S6502_AOT_TAX(0x82u); trace_offset += 1u; break;
        case 0xb8u:
          status = (uint8_t)(status & ~FLAG_V); CYCLES(2);
          trace_offset += 1u; break;
        case 0xbau: S6502_AOT_TSX(0x82u); trace_offset += 1u; break;
        case 0xc8u: S6502_AOT_INY(0x82u); trace_offset += 1u; break;
        case 0xcau: S6502_AOT_DEX(0x82u); trace_offset += 1u; break;
        case 0xd8u:
          status = (uint8_t)(status & ~FLAG_D); CYCLES(2);
          trace_offset += 1u; break;
        case 0xe8u: S6502_AOT_INX(0x82u); trace_offset += 1u; break;
        case 0xeau: S6502_AOT_NOP(); trace_offset += 1u; break;
        case 0xf8u:
          status = (uint8_t)(status | FLAG_D); CYCLES(2);
          trace_offset += 1u; break;

        case 0x09u: S6502_AOT_ORA(trace_operand, 2, 0x82u); trace_offset += 2u; break;
        case 0x29u: S6502_AOT_AND(trace_operand, 2, 0x82u); trace_offset += 2u; break;
        case 0x49u: S6502_AOT_EOR(trace_operand, 2, 0x82u); trace_offset += 2u; break;
        case 0x69u: S6502_AOT_ADC(trace_operand, 2, 0xc3u); trace_offset += 2u; break;
        case 0xa0u: S6502_AOT_LDY(trace_operand, 2, 0x82u); trace_offset += 2u; break;
        case 0xa2u: S6502_AOT_LDX(trace_operand, 2, 0x82u); trace_offset += 2u; break;
        case 0xa9u: S6502_AOT_LDA(trace_operand, 2, 0x82u); trace_offset += 2u; break;
        case 0xc0u: S6502_AOT_COMPARE(iy, trace_operand, 2, 0x83u); trace_offset += 2u; break;
        case 0xc9u: S6502_AOT_COMPARE(ac, trace_operand, 2, 0x83u); trace_offset += 2u; break;
        case 0xe0u: S6502_AOT_COMPARE(ix, trace_operand, 2, 0x83u); trace_offset += 2u; break;
        case 0xe9u: S6502_AOT_SBC(trace_operand, 2, 0xc3u); trace_offset += 2u; break;

        case 0x05u: S6502_AOT_ORA(READ8(trace_operand), 3, 0x82u); trace_offset += 2u; break;
        case 0x25u: S6502_AOT_AND(READ8(trace_operand), 3, 0x82u); trace_offset += 2u; break;
        case 0x45u: S6502_AOT_EOR(READ8(trace_operand), 3, 0x82u); trace_offset += 2u; break;
        case 0x65u: S6502_AOT_ADC(READ8(trace_operand), 3, 0xc3u); trace_offset += 2u; break;
        case 0x84u: S6502_AOT_STY(trace_operand, 3); trace_offset += 2u; break;
        case 0x85u: S6502_AOT_STA(trace_operand, 3); trace_offset += 2u; break;
        case 0x86u: S6502_AOT_STX(trace_operand, 3); trace_offset += 2u; break;
        case 0xa4u: S6502_AOT_LDY(READ8(trace_operand), 3, 0x82u); trace_offset += 2u; break;
        case 0xa5u: S6502_AOT_LDA(READ8(trace_operand), 3, 0x82u); trace_offset += 2u; break;
        case 0xa6u: S6502_AOT_LDX(READ8(trace_operand), 3, 0x82u); trace_offset += 2u; break;
        case 0xc4u: S6502_AOT_COMPARE(iy, READ8(trace_operand), 3, 0x83u); trace_offset += 2u; break;
        case 0xc5u: S6502_AOT_COMPARE(ac, READ8(trace_operand), 3, 0x83u); trace_offset += 2u; break;
        case 0xe4u: S6502_AOT_COMPARE(ix, READ8(trace_operand), 3, 0x83u); trace_offset += 2u; break;
        case 0xe5u: S6502_AOT_SBC(READ8(trace_operand), 3, 0xc3u); trace_offset += 2u; break;

        case 0x06u: S6502_AOT_ASL_ZP(trace_operand, 0x83u); trace_offset += 2u; break;
        case 0x26u: S6502_AOT_ROL_ZP(trace_operand, 0x83u); trace_offset += 2u; break;
        case 0x46u: S6502_AOT_LSR_ZP(trace_operand, 0x83u); trace_offset += 2u; break;
        case 0x66u: S6502_AOT_ROR_ZP(trace_operand, 0x83u); trace_offset += 2u; break;
        case 0xc6u: S6502_AOT_DEC(trace_operand, 5, 0x82u); trace_offset += 2u; break;
        case 0xe6u: S6502_AOT_INC(trace_operand, 5, 0x82u); trace_offset += 2u; break;

        case 0x15u: case 0x35u: case 0x55u: case 0x75u:
        case 0xb4u: case 0xb5u: case 0xd5u: case 0xf5u:
          trace_address = (uint8_t)(trace_operand + ix);
          dt = READ8(trace_address);
          if (trace_opcode == 0x15u) S6502_AOT_ORA(dt, 4, 0x82u);
          else if (trace_opcode == 0x35u) S6502_AOT_AND(dt, 4, 0x82u);
          else if (trace_opcode == 0x55u) S6502_AOT_EOR(dt, 4, 0x82u);
          else if (trace_opcode == 0x75u) S6502_AOT_ADC(dt, 4, 0xc3u);
          else if (trace_opcode == 0xb4u) S6502_AOT_LDY(dt, 4, 0x82u);
          else if (trace_opcode == 0xb5u) S6502_AOT_LDA(dt, 4, 0x82u);
          else if (trace_opcode == 0xd5u) S6502_AOT_COMPARE(ac, dt, 4, 0x83u);
          else S6502_AOT_SBC(dt, 4, 0xc3u);
          trace_offset += 2u;
          break;
        case 0xb6u:
          trace_address = (uint8_t)(trace_operand + iy);
          S6502_AOT_LDX(READ8(trace_address), 4, 0x82u);
          trace_offset += 2u;
          break;

        case 0x0du: case 0x2du: case 0x4du: case 0x6du:
        case 0x8cu: case 0x8du: case 0x8eu: case 0xacu:
        case 0xadu: case 0xaeu: case 0xccu: case 0xcdu:
        case 0xecu: case 0xedu:
          trace_address = (uint16_t)(trace_operand |
              ((uint16_t)game_aot_code[trace_offset + 2u] << 8));
          if (trace_opcode == 0x0du) S6502_AOT_ORA(READ8(trace_address), 4, 0x82u);
          else if (trace_opcode == 0x2du) S6502_AOT_AND(READ8(trace_address), 4, 0x82u);
          else if (trace_opcode == 0x4du) S6502_AOT_EOR(READ8(trace_address), 4, 0x82u);
          else if (trace_opcode == 0x6du) S6502_AOT_ADC(READ8(trace_address), 4, 0xc3u);
          else if (trace_opcode == 0x8cu) S6502_AOT_STY(trace_address, 4);
          else if (trace_opcode == 0x8du) S6502_AOT_STA(trace_address, 4);
          else if (trace_opcode == 0x8eu) S6502_AOT_STX(trace_address, 4);
          else if (trace_opcode == 0xacu) S6502_AOT_LDY(READ8(trace_address), 4, 0x82u);
          else if (trace_opcode == 0xadu) S6502_AOT_LDA(READ8(trace_address), 4, 0x82u);
          else if (trace_opcode == 0xaeu) S6502_AOT_LDX(READ8(trace_address), 4, 0x82u);
          else if (trace_opcode == 0xccu) S6502_AOT_COMPARE(iy, READ8(trace_address), 4, 0x83u);
          else if (trace_opcode == 0xcdu) S6502_AOT_COMPARE(ac, READ8(trace_address), 4, 0x83u);
          else if (trace_opcode == 0xecu) S6502_AOT_COMPARE(ix, READ8(trace_address), 4, 0x83u);
          else S6502_AOT_SBC(READ8(trace_address), 4, 0xc3u);
          trace_offset += 3u;
          break;

        case 0x19u: case 0x1du: case 0x39u: case 0x3du:
        case 0x59u: case 0x5du: case 0x79u: case 0x7du:
        case 0xb9u: case 0xbcu: case 0xbdu: case 0xbeu:
        case 0xd9u: case 0xddu: case 0xf9u: case 0xfdu:
          trace_base = (uint16_t)(trace_operand |
              ((uint16_t)game_aot_code[trace_offset + 2u] << 8));
          trace_address = (uint16_t)(trace_base +
              ((trace_opcode == 0x19u || trace_opcode == 0x39u ||
                trace_opcode == 0x59u || trace_opcode == 0x79u ||
                trace_opcode == 0xb9u || trace_opcode == 0xbeu ||
                trace_opcode == 0xd9u || trace_opcode == 0xf9u)
                  ? iy : ix));
          CYCLES((!!(0xff00u & (trace_base ^ trace_address))));
          dt = READ8(trace_address);
          if (trace_opcode == 0x19u || trace_opcode == 0x1du) S6502_AOT_ORA(dt, 4, 0x82u);
          else if (trace_opcode == 0x39u || trace_opcode == 0x3du) S6502_AOT_AND(dt, 4, 0x82u);
          else if (trace_opcode == 0x59u || trace_opcode == 0x5du) S6502_AOT_EOR(dt, 4, 0x82u);
          else if (trace_opcode == 0x79u || trace_opcode == 0x7du) S6502_AOT_ADC(dt, 4, 0xc3u);
          else if (trace_opcode == 0xb9u || trace_opcode == 0xbdu) S6502_AOT_LDA(dt, 4, 0x82u);
          else if (trace_opcode == 0xbcu) S6502_AOT_LDY(dt, 4, 0x82u);
          else if (trace_opcode == 0xbeu) S6502_AOT_LDX(dt, 4, 0x82u);
          else if (trace_opcode == 0xd9u || trace_opcode == 0xddu) S6502_AOT_COMPARE(ac, dt, 4, 0x83u);
          else S6502_AOT_SBC(dt, 4, 0xc3u);
          trace_offset += 3u;
          break;

        case 0x11u: case 0x31u: case 0x51u: case 0x71u:
        case 0xb1u: case 0xd1u: case 0xf1u:
          trace_base = (uint16_t)(READ8(trace_operand) |
              ((uint16_t)READ8((uint8_t)(trace_operand + 1u)) << 8));
          trace_address = (uint16_t)(trace_base + iy);
          CYCLES((!!(0xff00u & (trace_base ^ trace_address))));
          dt = READ8(trace_address);
          if (trace_opcode == 0x11u) S6502_AOT_ORA(dt, 5, 0x82u);
          else if (trace_opcode == 0x31u) S6502_AOT_AND(dt, 5, 0x82u);
          else if (trace_opcode == 0x51u) S6502_AOT_EOR(dt, 5, 0x82u);
          else if (trace_opcode == 0x71u) S6502_AOT_ADC(dt, 5, 0xc3u);
          else if (trace_opcode == 0xb1u) S6502_AOT_LDA(dt, 5, 0x82u);
          else if (trace_opcode == 0xd1u) S6502_AOT_COMPARE(ac, dt, 5, 0x83u);
          else S6502_AOT_SBC(dt, 5, 0xc3u);
          trace_offset += 2u;
          break;
        default:
          /* The load-time decoder and this executor intentionally share the
           * same closed opcode set.  If a corrupted descriptor ever reaches
           * here, commit the already completed prefix and resume exactly at
           * the first unknown instruction rather than replaying side effects. */
          pc = (uint16_t)(pc + trace_offset);
          goto _next;
        }
        ++trace_instruction;
      }
      S6502_GAME_AOT_NEXT(game_aot_entry->size);
    }

#undef S6502_GAME_AOT_JMP
#undef S6502_GAME_AOT_NEXT
