/* Function-level GAM high-level emulation blocks. Included in s6502_exec(). */

  _hle_game_counter:
    {
      s6502_hle_compare_result_t hle_result;
      uint16_t hle_base;
      uint16_t hle_address;
      uint16_t hle_return_pc;

      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_GAME_COUNTER, et);

      ac = game_hle_counter->limit_low;
      SET_NZ(ac);
      WRITE8(0x0023u, ac);
      ac = game_hle_counter->limit_high;
      SET_NZ(ac);
      WRITE8(0x0024u, ac);
      iy = game_hle_counter->index;
      SET_NZ(iy);
      hle_base = READ16W(game_hle_counter->pointer_zp);
      hle_address = (uint16_t)(hle_base + iy);
      ac = READ8(hle_address);
      SET_NZ(ac);
      WRITE8(0x0020u, ac);
      ac = game_hle_counter->value_high;
      SET_NZ(ac);
      WRITE8(0x0021u, ac);

      /* Reproduce the JSR stack image before collapsing the firmware
       * Compare16 call.  Its RTS restores this handler's original SP. */
      hle_return_pc = (uint16_t)(game_hle_counter->virtual_pc + 0x14u);
      PUSH((uint8_t)(hle_return_pc >> 8));
      PUSH((uint8_t)hle_return_pc);
      s6502_firmware_hle_compare16(sp, status, &hle_result);
      pc = hle_result.pc;
      ac = hle_result.ac;
      ix = hle_result.ix;
      sp = hle_result.sp;
      status = hle_result.status;

      if (CARRY_p) {
        pc = game_hle_counter->exit_pc;
      } else {
        /* Follow the two local JMPs into the increment block and return to
         * the matched function head for the next logical iteration. */
        iy = game_hle_counter->index;
        SET_NZ(iy);
        hle_base = READ16W(game_hle_counter->pointer_zp);
        hle_address = (uint16_t)(hle_base + iy);
        ac = READ8(hle_address);
        SET_NZ(ac);
        SET_C(0);
        dt = game_hle_counter->increment;
        et = (uint16_t)(ac + dt);
        SET_C(et > 0xffu);
        SET_V((ac ^ et) & (dt ^ et) & 0x80u);
        ac = (uint8_t)et;
        SET_NZ(ac);
        iy = game_hle_counter->index;
        SET_NZ(iy);
        WRITE8(hle_address, ac);
        pc = game_hle_counter->virtual_pc;
      }
      goto _exit;
    }

  _hle_game_counter_suffix_15:
    {
      uint16_t hle_base;
      uint16_t hle_address;

      /* Resume at the BCC immediately following firmware Compare16. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_GAME_COUNTER, et);
      if (CARRY_p) {
        pc = game_hle_counter->exit_pc;
      } else {
        iy = game_hle_counter->index;
        SET_NZ(iy);
        hle_base = READ16W(game_hle_counter->pointer_zp);
        hle_address = (uint16_t)(hle_base + iy);
        ac = READ8(hle_address);
        SET_NZ(ac);
        SET_C(0);
        dt = game_hle_counter->increment;
        et = (uint16_t)(ac + dt);
        SET_C(et > 0xffu);
        SET_V((ac ^ et) & (dt ^ et) & 0x80u);
        ac = (uint8_t)et;
        SET_NZ(ac);
        iy = game_hle_counter->index;
        SET_NZ(iy);
        WRITE8(hle_address, ac);
        pc = game_hle_counter->virtual_pc;
      }
      goto _exit;
    }

  _hle_game_scan:
    {
      CYCLES(s6502_game_hle_scan_result.cycles);
      S6502_HLE_RECORD_BATCH(
        S6502_HLE_ID_GAME_SCAN,
        s6502_game_hle_scan_result.iterations,
        s6502_game_hle_scan_result.cycles
      );
      pc = s6502_game_hle_scan_result.pc;
      ac = s6502_game_hle_scan_result.ac;
      iy = s6502_game_hle_scan_result.iy;
      status = s6502_game_hle_scan_result.status;
      goto _exit;
    }

  _hle_game_callback_scan:
    {
      CYCLES(s6502_game_hle_table_result.cycles);
      S6502_HLE_RECORD(
        S6502_HLE_ID_GAME_CALLBACK_SCAN,
        s6502_game_hle_table_result.cycles
      );
      pc = s6502_game_hle_table_result.pc;
      ac = s6502_game_hle_table_result.ac;
      ix = s6502_game_hle_table_result.ix;
      iy = s6502_game_hle_table_result.iy;
      sp = s6502_game_hle_table_result.sp;
      status = s6502_game_hle_table_result.status;
      goto _exit;
    }

  _hle_game_record_scan:
    {
      CYCLES(s6502_game_hle_scan_result.cycles);
      S6502_HLE_RECORD_BATCH(
        S6502_HLE_ID_GAME_RECORD_SCAN,
        s6502_game_hle_scan_result.iterations,
        s6502_game_hle_scan_result.cycles
      );
      pc = s6502_game_hle_scan_result.pc;
      ac = s6502_game_hle_scan_result.ac;
      iy = s6502_game_hle_scan_result.iy;
      status = s6502_game_hle_scan_result.status;
      goto _exit;
    }

  _hle_game_record_reverse:
    {
      CYCLES(s6502_game_hle_scan_result.cycles);
      S6502_HLE_RECORD_BATCH(
        S6502_HLE_ID_GAME_RECORD_REVERSE,
        s6502_game_hle_scan_result.iterations,
        s6502_game_hle_scan_result.cycles
      );
      pc = s6502_game_hle_scan_result.pc;
      ac = s6502_game_hle_scan_result.ac;
      iy = s6502_game_hle_scan_result.iy;
      status = s6502_game_hle_scan_result.status;
      goto _exit;
    }

  _hle_game_table_chain:
    {
      CYCLES(s6502_game_hle_table_result.cycles);
      S6502_HLE_RECORD(
        S6502_HLE_ID_GAME_TABLE_CHAIN,
        s6502_game_hle_table_result.cycles
      );
      pc = s6502_game_hle_table_result.pc;
      ac = s6502_game_hle_table_result.ac;
      ix = s6502_game_hle_table_result.ix;
      iy = s6502_game_hle_table_result.iy;
      sp = s6502_game_hle_table_result.sp;
      status = s6502_game_hle_table_result.status;
      goto _exit;
    }

  _hle_game_object_flow:
    {
      CYCLES(s6502_game_hle_table_result.cycles);
      S6502_HLE_RECORD(
        S6502_HLE_ID_GAME_OBJECT_FLOW,
        s6502_game_hle_table_result.cycles
      );
      pc = s6502_game_hle_table_result.pc;
      ac = s6502_game_hle_table_result.ac;
      ix = s6502_game_hle_table_result.ix;
      iy = s6502_game_hle_table_result.iy;
      sp = s6502_game_hle_table_result.sp;
      status = s6502_game_hle_table_result.status;
      goto _exit;
    }

  _hle_game_bitmap_outer_prefix:
    {
      uint16_t hle_base;
      uint16_t hle_address;

      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_GAME_BITMAP, et);
      iy = READ8(game_hle_bitmap->source_index_zp);
      SET_NZ(iy);
      hle_base = READ16W(game_hle_bitmap->source_pointer_zp);
      hle_address = (uint16_t)(hle_base + iy);
      ac = READ8(hle_address);
      SET_NZ(ac);
      WRITE8(game_hle_bitmap->source_index_zp, iy);
      WRITE8(game_hle_bitmap->source_zp, ac);
      pc = game_hle_bitmap->virtual_pc;

      et = s6502_game_hle_bitmap_cycles(game_hle_bitmap, ix);
      if (et && (uint32_t)et <= cycles - executed)
        goto _hle_game_bitmap;
      et = s6502_game_hle_bitmap_iteration_cycles(game_hle_bitmap, ix);
      if (et && (uint32_t)et <= cycles - executed) {
        game_hle_bitmap_partial = 1u;
        goto _hle_game_bitmap;
      }
      goto _exit;
    }

  _hle_game_bitmap_subpixel_tail:
    {
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_GAME_BITMAP, et);

      dt = (uint8_t)(READ8(game_hle_bitmap->subpixel_zp) + 1u);
      SET_NZ(dt);
      WRITE8(game_hle_bitmap->subpixel_zp, dt);
      ac = 4u;
      SET_NZ(ac);
      dt = (uint8_t)~READ8(game_hle_bitmap->subpixel_zp);
      et = (uint16_t)(ac + dt + 1u);
      SET_C(et > 0xffu);
      SET_NZ((uint8_t)et);
      if ((uint8_t)et == 0u) {
        pc = (uint16_t)(game_hle_bitmap->virtual_pc + 0x40u);
        et = s6502_game_hle_bitmap_group_tail_cycles(game_hle_bitmap);
        if ((uint32_t)et <= cycles - executed)
          goto _hle_game_bitmap_group_tail;
        goto _exit;
      }

      ac = READ8(game_hle_bitmap->source_zp);
      SET_NZ(ac);
      SET_C(ac & 0x80u);
      ac = (uint8_t)(ac << 1);
      SET_NZ(ac);
      SET_C(ac & 0x80u);
      ac = (uint8_t)(ac << 1);
      SET_NZ(ac);
      WRITE8(game_hle_bitmap->source_zp, ac);
      pc = game_hle_bitmap->virtual_pc;
      et = s6502_game_hle_bitmap_cycles(game_hle_bitmap, ix);
      if (et && (uint32_t)et <= cycles - executed)
        goto _hle_game_bitmap;
      et = s6502_game_hle_bitmap_iteration_cycles(game_hle_bitmap, ix);
      if (et && (uint32_t)et <= cycles - executed) {
        game_hle_bitmap_partial = 1u;
        goto _hle_game_bitmap;
      }
      goto _exit;
    }

  _hle_game_bitmap_group_tail:
    {
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_GAME_BITMAP, et);

      ac = 0u;
      SET_NZ(ac);
      WRITE8(game_hle_bitmap->subpixel_zp, ac);
      dt = (uint8_t)(READ8(game_hle_bitmap->source_index_zp) + 1u);
      SET_NZ(dt);
      WRITE8(game_hle_bitmap->source_index_zp, dt);
      ac = READ8(game_hle_bitmap->source_index_zp);
      SET_NZ(ac);
      SET_C(ac & 0x80u);
      ac = (uint8_t)(ac << 1);
      SET_NZ(ac);
      SET_C(ac & 0x80u);
      ac = (uint8_t)(ac << 1);
      SET_NZ(ac);
      dt = (uint8_t)~READ8(game_hle_bitmap->width_zp);
      et = (uint16_t)(ac + dt + 1u);
      SET_C(et > 0xffu);
      SET_NZ((uint8_t)et);
      if (CARRY_p) {
        pc = game_hle_bitmap->outer_exit_pc;
        et = s6502_game_hle_bitmap_row_cycles(game_hle_bitmap, ix);
        if (et && (uint32_t)et <= cycles - executed)
          goto _hle_game_bitmap_row;
        goto _exit;
      }

      pc = game_hle_bitmap->outer_virtual_pc;
      et = s6502_game_hle_bitmap_row_body_cycles(game_hle_bitmap, ix);
      if (et && (uint32_t)et <= cycles - executed) {
        game_hle_bitmap_outer = 1u;
        goto _hle_game_bitmap_row_body_fast;
      }
      et = s6502_game_hle_bitmap_outer_cycles(game_hle_bitmap, ix);
      if (et && (uint32_t)et <= cycles - executed) {
        game_hle_bitmap_outer = 1u;
        goto _hle_game_bitmap;
      }
      et = s6502_game_hle_bitmap_outer_prefix_cycles(game_hle_bitmap);
      if (et && (uint32_t)et <= cycles - executed)
        goto _hle_game_bitmap_outer_prefix;
      goto _exit;
    }

  _hle_game_bitmap_row:
    {
      uint16_t hle_base;

      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_GAME_BITMAP, et);

      /* CPX #$00 / BEQ: flush the final partial destination byte. */
      dt = 0xffu;
      et = (uint16_t)(ix + dt + 1u);
      SET_C(et > 0xffu);
      SET_NZ((uint8_t)et);
      if (ix != 0u) {
        ac = READ8(game_hle_bitmap->accumulator_zp);
        SET_NZ(ac);
        iy = READ8(game_hle_bitmap->destination_index_zp);
        SET_NZ(iy);
        hle_base = READ16W(game_hle_bitmap->destination_pointer_zp);
        WRITE8((uint16_t)(hle_base + iy), ac);
      }

      /* Advance and compare the completed source row. */
      dt = (uint8_t)(READ8(game_hle_bitmap->row_count_zp) + 1u);
      SET_NZ(dt);
      WRITE8(game_hle_bitmap->row_count_zp, dt);
      ac = READ8(game_hle_bitmap->height_zp);
      SET_NZ(ac);
      dt = (uint8_t)~READ8(game_hle_bitmap->row_count_zp);
      et = (uint16_t)(ac + dt + 1u);
      SET_C(et > 0xffu);
      SET_NZ((uint8_t)et);
      if ((uint8_t)et == 0u) {
        pc = game_hle_bitmap->function_exit_pc;
        goto _exit;
      }

      dt = (uint8_t)(READ8(game_hle_bitmap->vertical_zp) + 1u);
      SET_NZ(dt);
      WRITE8(game_hle_bitmap->vertical_zp, dt);
      ac = 0x5fu;
      SET_NZ(ac);
      dt = (uint8_t)~READ8(game_hle_bitmap->vertical_zp);
      et = (uint16_t)(ac + dt + 1u);
      SET_C(et > 0xffu);
      SET_NZ((uint8_t)et);

      /* The cycle estimator rejects the clipping RTS path, so C is set. */
      SET_C(0);
      ac = game_hle_bitmap->row_stride;
      SET_NZ(ac);
      dt = READ8(game_hle_bitmap->destination_pointer_zp);
      et = (uint16_t)(ac + dt);
      SET_C(et > 0xffu);
      SET_V((ac ^ et) & (dt ^ et) & 0x80u);
      ac = (uint8_t)et;
      SET_NZ(ac);
      WRITE8(game_hle_bitmap->destination_pointer_zp, ac);
      ac = READ8((uint8_t)(game_hle_bitmap->destination_pointer_zp + 1u));
      SET_NZ(ac);
      dt = 0u;
      et = (uint16_t)(ac + (CARRY_p ? 1u : 0u));
      SET_C(et > 0xffu);
      SET_V((ac ^ et) & (dt ^ et) & 0x80u);
      ac = (uint8_t)et;
      SET_NZ(ac);
      WRITE8(
        (uint8_t)(game_hle_bitmap->destination_pointer_zp + 1u), ac
      );

      iy = 0u;
      SET_NZ(iy);
      hle_base = READ16W(game_hle_bitmap->destination_pointer_zp);
      ac = READ8(hle_base);
      SET_NZ(ac);
      WRITE8(game_hle_bitmap->accumulator_zp, ac);

      ac = 7u;
      SET_NZ(ac);
      ac = (uint8_t)(ac & READ8(game_hle_bitmap->width_zp));
      SET_NZ(ac);
      WRITE8(game_hle_bitmap->source_index_zp, ac);
      ac = READ8(game_hle_bitmap->width_zp);
      SET_NZ(ac);
      SET_C(ac & 0x01u);
      ac = (uint8_t)(ac >> 1);
      SET_NZ(ac);
      SET_C(ac & 0x01u);
      ac = (uint8_t)(ac >> 1);
      SET_NZ(ac);
      SET_C(ac & 0x01u);
      ac = (uint8_t)(ac >> 1);
      SET_NZ(ac);
      iy = READ8(game_hle_bitmap->source_index_zp);
      SET_NZ(iy);
      if (iy != 0u) {
        SET_C(0);
        dt = 1u;
        et = (uint16_t)(ac + dt);
        SET_C(et > 0xffu);
        SET_V((ac ^ et) & (dt ^ et) & 0x80u);
        ac = (uint8_t)et;
        SET_NZ(ac);
      }
      SET_C(ac & 0x80u);
      ac = (uint8_t)(ac << 1);
      SET_NZ(ac);
      SET_C(0);
      dt = READ8(game_hle_bitmap->source_pointer_zp);
      et = (uint16_t)(ac + dt);
      SET_C(et > 0xffu);
      SET_V((ac ^ et) & (dt ^ et) & 0x80u);
      ac = (uint8_t)et;
      SET_NZ(ac);
      WRITE8(game_hle_bitmap->source_pointer_zp, ac);
      ac = READ8((uint8_t)(game_hle_bitmap->source_pointer_zp + 1u));
      SET_NZ(ac);
      dt = 0u;
      et = (uint16_t)(ac + (CARRY_p ? 1u : 0u));
      SET_C(et > 0xffu);
      SET_V((ac ^ et) & (dt ^ et) & 0x80u);
      ac = (uint8_t)et;
      SET_NZ(ac);
      WRITE8((uint8_t)(game_hle_bitmap->source_pointer_zp + 1u), ac);

      ac = 0u;
      SET_NZ(ac);
      WRITE8(game_hle_bitmap->source_index_zp, ac);
      WRITE8(game_hle_bitmap->destination_index_zp, ac);
      ix = READ8(game_hle_bitmap->initial_x_zp);
      SET_NZ(ix);
      pc = game_hle_bitmap->outer_virtual_pc;

      et = s6502_game_hle_bitmap_row_body_cycles(game_hle_bitmap, ix);
      if (et && (uint32_t)et <= cycles - executed) {
        game_hle_bitmap_outer = 1u;
        goto _hle_game_bitmap_row_body_fast;
      }
      et = s6502_game_hle_bitmap_outer_cycles(game_hle_bitmap, ix);
      if (et && (uint32_t)et <= cycles - executed) {
        game_hle_bitmap_outer = 1u;
        goto _hle_game_bitmap;
      }
      goto _exit;
    }

  _hle_game_bitmap_row_body_fast:
    {
      uint8_t hle_source_index;
      uint8_t hle_destination_index;
      uint8_t hle_width;
      uint8_t hle_x;
      uint8_t hle_source = 0u;
      uint8_t hle_accumulator;
      uint8_t hle_subpixel;
      uint16_t hle_source_base;
      uint16_t hle_destination_base;

      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_GAME_BITMAP, et);

      hle_source_index = READ8(game_hle_bitmap->source_index_zp);
      hle_destination_index = READ8(
        game_hle_bitmap->destination_index_zp
      );
      hle_width = READ8(game_hle_bitmap->width_zp);
      hle_x = (uint8_t)ix;
      hle_accumulator = READ8(game_hle_bitmap->accumulator_zp);
      hle_source_base = READ16W(game_hle_bitmap->source_pointer_zp);
      hle_destination_base = READ16W(
        game_hle_bitmap->destination_pointer_zp
      );

      do {
        uint8_t hle_pixel;
        uint8_t hle_compared;

        /* LDY source_index / LDA (source),Y.  Y is overwritten only if this
         * packed byte crosses a destination-byte boundary. */
        iy = hle_source_index;
        hle_source = READ8((uint16_t)(
          hle_source_base + hle_source_index
        ));
        hle_subpixel = 0u;
        for (hle_pixel = 0u; hle_pixel < 4u; ++hle_pixel) {
          uint8_t hle_bits = (uint8_t)(hle_source & 0xc0u);

          if (!hle_bits) {
            hle_accumulator = (uint8_t)(
              hle_accumulator & READ8((uint16_t)(
                game_hle_bitmap->and_table + hle_x
              ))
            );
          } else if (hle_bits == 0x40u) {
            hle_accumulator = (uint8_t)(
              hle_accumulator | READ8((uint16_t)(
                game_hle_bitmap->or_table + hle_x
              ))
            );
          }

          hle_x = (uint8_t)(hle_x + 1u);
          if (hle_x == 8u) {
            WRITE8(
              (uint16_t)(hle_destination_base + hle_destination_index),
              hle_accumulator
            );
            hle_destination_index = (uint8_t)(
              hle_destination_index + 1u
            );
            iy = hle_destination_index;
            hle_accumulator = READ8((uint16_t)(
              hle_destination_base + hle_destination_index
            ));
            hle_x = 0u;
          }

          ++hle_subpixel;
          if (hle_subpixel != 4u)
            hle_source = (uint8_t)(hle_source << 2);
        }

        hle_source_index = (uint8_t)(hle_source_index + 1u);
        hle_compared = (uint8_t)(hle_source_index << 2);
        if (hle_compared >= hle_width)
          break;
      } while (1);

      /* Commit the exact zero-page and visible CPU state at $513E, the row
       * suffix entry.  Intermediate flag values cannot be observed because
       * the fused path is admitted only when the complete row fits before
       * the current guest deadline. */
      WRITE8(game_hle_bitmap->source_zp, hle_source);
      WRITE8(game_hle_bitmap->accumulator_zp, hle_accumulator);
      WRITE8(game_hle_bitmap->destination_index_zp, hle_destination_index);
      WRITE8(game_hle_bitmap->subpixel_zp, 0u);
      WRITE8(game_hle_bitmap->source_index_zp, hle_source_index);
      ix = hle_x;
      ac = (uint8_t)(hle_source_index << 2);
      SET_NZ(ac);
      dt = (uint8_t)~hle_width;
      et = (uint16_t)(ac + dt + 1u);
      SET_C(et > 0xffu);
      SET_NZ((uint8_t)et);
      pc = game_hle_bitmap->outer_exit_pc;

      et = s6502_game_hle_bitmap_row_cycles(game_hle_bitmap, ix);
      if (et && (uint32_t)et <= cycles - executed)
        goto _hle_game_bitmap_row;
      goto _exit;
    }

  _hle_game_bitmap:
    {
      uint8_t hle_subpixel;
      uint16_t hle_base;
      uint16_t hle_address;

      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_GAME_BITMAP, et);

      if (game_hle_bitmap_outer) {
        iy = READ8(game_hle_bitmap->source_index_zp);
        SET_NZ(iy);
        hle_base = READ16W(game_hle_bitmap->source_pointer_zp);
        hle_address = (uint16_t)(hle_base + iy);
        ac = READ8(hle_address);
        SET_NZ(ac);
        WRITE8(game_hle_bitmap->source_index_zp, iy);
        WRITE8(game_hle_bitmap->source_zp, ac);
      }
      hle_subpixel = READ8(game_hle_bitmap->subpixel_zp);

      do {
        ac = READ8(game_hle_bitmap->source_zp);
        SET_NZ(ac);
        ac = (uint8_t)(ac & 0xc0u);
        SET_NZ(ac);
        if (ac == 0u) {
          ac = READ8((uint16_t)(game_hle_bitmap->and_table + ix));
          SET_NZ(ac);
          ac = (uint8_t)(
            ac & READ8(game_hle_bitmap->accumulator_zp)
          );
          SET_NZ(ac);
          WRITE8(game_hle_bitmap->accumulator_zp, ac);
        } else if (ac == 0x40u) {
          ac = READ8((uint16_t)(game_hle_bitmap->or_table + ix));
          SET_NZ(ac);
          ac = (uint8_t)(
            ac | READ8(game_hle_bitmap->accumulator_zp)
          );
          SET_NZ(ac);
          WRITE8(game_hle_bitmap->accumulator_zp, ac);
        }

        ix = (uint8_t)(ix + 1u);
        SET_NZ(ix);
        dt = (uint8_t)~8u;
        et = (uint16_t)(ix + dt + 1u);
        SET_C(et > 0xffu);
        SET_NZ((uint8_t)et);
        if (ix == 8u) {
          ac = READ8(game_hle_bitmap->accumulator_zp);
          SET_NZ(ac);
          iy = READ8(game_hle_bitmap->destination_index_zp);
          SET_NZ(iy);
          hle_base = READ16W(game_hle_bitmap->destination_pointer_zp);
          hle_address = (uint16_t)(hle_base + iy);
          WRITE8(hle_address, ac);
          iy = (uint8_t)(iy + 1u);
          SET_NZ(iy);
          hle_address = (uint16_t)(hle_base + iy);
          ac = READ8(hle_address);
          SET_NZ(ac);
          WRITE8(game_hle_bitmap->accumulator_zp, ac);
          WRITE8(game_hle_bitmap->destination_index_zp, iy);
          ix = 0u;
          SET_NZ(ix);
        }

        hle_subpixel = (uint8_t)(hle_subpixel + 1u);
        SET_NZ(hle_subpixel);
        WRITE8(game_hle_bitmap->subpixel_zp, hle_subpixel);
        ac = 4u;
        SET_NZ(ac);
        dt = (uint8_t)~hle_subpixel;
        et = (uint16_t)(ac + dt + 1u);
        SET_C(et > 0xffu);
        SET_NZ((uint8_t)et);
        if (hle_subpixel != 4u) {
          ac = READ8(game_hle_bitmap->source_zp);
          SET_NZ(ac);
          SET_C(ac & 0x80u);
          ac = (uint8_t)(ac << 1);
          SET_NZ(ac);
          SET_C(ac & 0x80u);
          ac = (uint8_t)(ac << 1);
          SET_NZ(ac);
          WRITE8(game_hle_bitmap->source_zp, ac);
        }
      } while (!game_hle_bitmap_partial && hle_subpixel != 4u);

      if (game_hle_bitmap_outer) {
        ac = 0u;
        SET_NZ(ac);
        WRITE8(game_hle_bitmap->subpixel_zp, ac);

        dt = (uint8_t)(READ8(game_hle_bitmap->source_index_zp) + 1u);
        SET_NZ(dt);
        WRITE8(game_hle_bitmap->source_index_zp, dt);
        ac = READ8(game_hle_bitmap->source_index_zp);
        SET_NZ(ac);
        SET_C(ac & 0x80u);
        ac = (uint8_t)(ac << 1);
        SET_NZ(ac);
        SET_C(ac & 0x80u);
        ac = (uint8_t)(ac << 1);
        SET_NZ(ac);
        dt = (uint8_t)~READ8(game_hle_bitmap->width_zp);
        et = (uint16_t)(ac + dt + 1u);
        SET_C(et > 0xffu);
        SET_NZ((uint8_t)et);
        if (CARRY_p) {
          pc = game_hle_bitmap->outer_exit_pc;
          et = s6502_game_hle_bitmap_row_cycles(game_hle_bitmap, ix);
          if (et && (uint32_t)et <= cycles - executed)
            goto _hle_game_bitmap_row;
        } else {
          pc = game_hle_bitmap->outer_virtual_pc;
          et = s6502_game_hle_bitmap_row_body_cycles(
            game_hle_bitmap, ix
          );
          if (et && (uint32_t)et <= cycles - executed)
          {
            goto _hle_game_bitmap_row_body_fast;
          }
          et = s6502_game_hle_bitmap_outer_cycles(game_hle_bitmap, ix);
          if (et && (uint32_t)et <= cycles - executed)
            goto _hle_game_bitmap;
        }
      } else {
        if (hle_subpixel == 4u) {
          pc = (uint16_t)(game_hle_bitmap->virtual_pc + 0x40u);
          et = s6502_game_hle_bitmap_group_tail_cycles(game_hle_bitmap);
          if ((uint32_t)et <= cycles - executed)
            goto _hle_game_bitmap_group_tail;
        } else {
          pc = game_hle_bitmap->virtual_pc;
          game_hle_bitmap_partial = 0u;
          et = s6502_game_hle_bitmap_cycles(game_hle_bitmap, ix);
          if (et && (uint32_t)et <= cycles - executed)
            goto _hle_game_bitmap;
          et = s6502_game_hle_bitmap_iteration_cycles(
            game_hle_bitmap, ix
          );
          if (et && (uint32_t)et <= cycles - executed) {
            game_hle_bitmap_partial = 1u;
            goto _hle_game_bitmap;
          }
        }
      }
      goto _exit;
    }
