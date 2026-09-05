/* E.BIN high-level emulation blocks. Included inside s6502_exec(). */

#ifdef GAM4980_ENABLE_AGGRESSIVE_REGION_HLE
  _hle_ebin_picture_head:
    {
      int hle_status = s6502_firmware_hle_picture_head_call(
          ac, iy, sp, status, cycles - executed,
          &s6502_hle_direct_result);

      if (hle_status <= 0) {
        if (hle_status < 0)
          S6502_HLE_CONDITION_REJECT(S6502_HLE_ID_PICTURE_HEAD);
        else
          S6502_HLE_BUDGET_REJECT(S6502_HLE_ID_PICTURE_HEAD);
        goto _next;
      }
      CYCLES(s6502_hle_direct_result.cycles);
      S6502_HLE_RECORD(
          S6502_HLE_ID_PICTURE_HEAD,
          s6502_hle_direct_result.cycles);
      pc = s6502_hle_direct_result.pc;
      ac = s6502_hle_direct_result.ac;
      ix = s6502_hle_direct_result.ix;
      iy = s6502_hle_direct_result.iy;
      sp = s6502_hle_direct_result.dt;
      status = s6502_hle_direct_result.status;
      goto _exit;
    }

  _hle_ebin_picture_resume:
    {
      int hle_status = s6502_firmware_hle_picture_resume(
          ac, ix, iy, sp, status, cycles - executed,
          &s6502_hle_direct_result);

      if (hle_status <= 0) {
        if (hle_status < 0)
          S6502_HLE_CONDITION_REJECT(S6502_HLE_ID_PICTURE_RESUME);
        else
          S6502_HLE_BUDGET_REJECT(S6502_HLE_ID_PICTURE_RESUME);
        goto _next;
      }
      CYCLES(s6502_hle_direct_result.cycles);
      S6502_HLE_RECORD(
          S6502_HLE_ID_PICTURE_RESUME,
          s6502_hle_direct_result.cycles);
      pc = s6502_hle_direct_result.pc;
      ac = s6502_hle_direct_result.ac;
      ix = s6502_hle_direct_result.ix;
      iy = s6502_hle_direct_result.iy;
      sp = s6502_hle_direct_result.dt;
      status = s6502_hle_direct_result.status;
      goto _exit;
    }

  _hle_ebin_picture_tail_next:
    dt = 1u;
    goto _hle_ebin_picture_tail;

  _hle_ebin_picture_tail_zero:
    dt = 0u;

  _hle_ebin_picture_tail:
    {
      s6502_hle_region_result_t hle_result;
      int hle_status;

      /* Fuse the common SysPicture row suffix: final masked byte, source
       * advance, $6646 LCD row-address update and the mode-3 row counter. */
      ea = (uint16_t)(s6502_stack_ram[0x3au] |
          ((uint16_t)s6502_stack_ram[0x3bu] << 8));
      hle_status = s6502_firmware_hle_picture_tail_call(
          dt != 0u, sp, status, cycles - executed, &hle_result);
      if (hle_status <= 0) {
        if (hle_status < 0)
          S6502_HLE_CONDITION_REJECT(S6502_HLE_ID_PICTURE_TAIL);
        else
          S6502_HLE_BUDGET_REJECT(S6502_HLE_ID_PICTURE_TAIL);
        goto _next;
      }
      CYCLES(hle_result.cycles);
      S6502_HLE_RECORD(
          S6502_HLE_ID_PICTURE_TAIL, hle_result.cycles);
      pc = hle_result.pc;
      ac = hle_result.ac;
      ix = hle_result.ix;
      iy = hle_result.iy;
      sp = hle_result.sp;
      status = hle_result.status;
      if (dt == 0u)
        ea = 0x6c18u;
      dt = 0xffu;
      et = (uint16_t)(0x0100u + hle_result.ac);
      goto _exit;
    }

  _hle_ebin_shift_region:
    {
      s6502_hle_region_result_t hle_result;
      int hle_status;

      /* Merge the common mode-3 row beginning at $6988, including the
       * $6A75 inner loop, masked tail and shared $6646 row update. */
      hle_status = s6502_firmware_hle_shift_region_call(
          sp, status, cycles - executed, &hle_result);
      if (hle_status <= 0) {
        if (hle_status < 0)
          S6502_HLE_CONDITION_REJECT(S6502_HLE_ID_SHIFT_REGION);
        else
          S6502_HLE_BUDGET_REJECT(S6502_HLE_ID_SHIFT_REGION);
        goto _next;
      }
      CYCLES(hle_result.cycles);
      S6502_HLE_RECORD_BATCH(
          S6502_HLE_ID_SHIFT_REGION, hle_result.rows, hle_result.cycles);
      pc = hle_result.pc;
      ac = hle_result.ac;
      ix = hle_result.ix;
      iy = hle_result.iy;
      sp = hle_result.sp;
      status = hle_result.status;
      goto _exit;
    }

  _hle_ebin_bitmap_region:
    {
      s6502_hle_region_result_t hle_result;
      int hle_status;

      /* Execute complete rows while they fit the current CPU slice.  Keeping
       * the $5C5D row boundary preserves the firmware timer/IRQ schedule but
       * still removes every inner AOT/interpreter dispatch in those rows. */
      hle_status = s6502_firmware_hle_bitmap_region_call(
          sp, status, cycles - executed, &hle_result);
      if (hle_status <= 0) {
        if (hle_status < 0)
          S6502_HLE_CONDITION_REJECT(S6502_HLE_ID_BITMAP_REGION);
        else
          S6502_HLE_BUDGET_REJECT(S6502_HLE_ID_BITMAP_REGION);
        goto _next;
      }
      CYCLES(hle_result.cycles);
      S6502_HLE_RECORD_BATCH(
          S6502_HLE_ID_BITMAP_REGION, hle_result.rows, hle_result.cycles);
      pc = hle_result.pc;
      ac = hle_result.ac;
      ix = hle_result.ix;
      iy = hle_result.iy;
      sp = hle_result.sp;
      status = hle_result.status;
      goto _exit;
    }
#endif

#ifdef GAM4980_ENABLE_AGGRESSIVE_REGION_HLE
  _hle_ebin_graphics_address:
    {
      int hle_status = s6502_firmware_hle_graphics_address(
          ix, iy, sp, status, cycles - executed,
          &s6502_hle_direct_result);

      if (hle_status <= 0) {
        S6502_HLE_BUDGET_REJECT(S6502_HLE_ID_GRAPHICS_ADDRESS);
        goto _next;
      }
      CYCLES(s6502_hle_direct_result.cycles);
      S6502_HLE_RECORD(
          S6502_HLE_ID_GRAPHICS_ADDRESS,
          s6502_hle_direct_result.cycles);
      pc = s6502_hle_direct_result.pc;
      ac = s6502_hle_direct_result.ac;
      ix = s6502_hle_direct_result.ix;
      iy = s6502_hle_direct_result.iy;
      sp = s6502_hle_direct_result.dt;
      status = s6502_hle_direct_result.status;
      goto _exit;
    }

  _hle_ebin_hline_middle:
    {
      int hle_status = s6502_firmware_hle_hline_middle(
          ac, ix, iy, sp, status, cycles - executed,
          &s6502_hle_direct_result);

      if (hle_status <= 0) {
        if (hle_status < 0)
          S6502_HLE_CONDITION_REJECT(S6502_HLE_ID_HLINE_MIDDLE);
        else
          S6502_HLE_BUDGET_REJECT(S6502_HLE_ID_HLINE_MIDDLE);
        goto _next;
      }
      CYCLES(s6502_hle_direct_result.cycles);
      S6502_HLE_RECORD_BATCH(
          S6502_HLE_ID_HLINE_MIDDLE,
          s6502_hle_direct_result.hits,
          s6502_hle_direct_result.cycles);
      pc = s6502_hle_direct_result.pc;
      ea = s6502_hle_direct_result.ea;
      ac = s6502_hle_direct_result.ac;
      ix = s6502_hle_direct_result.ix;
      iy = s6502_hle_direct_result.iy;
      sp = s6502_hle_direct_result.dt;
      status = s6502_hle_direct_result.status;
      goto _exit;
    }

  _hle_ebin_part_picture_row_right:
    dt = 0u;
    goto _hle_ebin_part_picture_row;

  _hle_ebin_part_picture_row_left:
    dt = 1u;

  _hle_ebin_part_picture_row:
    {
      int hle_status = s6502_firmware_hle_part_picture_row(
          dt != 0u, ac, iy, sp, status, cycles - executed,
          &s6502_hle_direct_result);

      if (hle_status <= 0) {
        if (hle_status < 0)
          S6502_HLE_CONDITION_REJECT(S6502_HLE_ID_PART_PICTURE_ROW);
        else
          S6502_HLE_BUDGET_REJECT(S6502_HLE_ID_PART_PICTURE_ROW);
        goto _next;
      }
      CYCLES(s6502_hle_direct_result.cycles);
      S6502_HLE_RECORD_BATCH(
          S6502_HLE_ID_PART_PICTURE_ROW,
          s6502_hle_direct_result.hits,
          s6502_hle_direct_result.cycles);
      pc = s6502_hle_direct_result.pc;
      ea = s6502_hle_direct_result.ea;
      ac = s6502_hle_direct_result.ac;
      ix = s6502_hle_direct_result.ix;
      iy = s6502_hle_direct_result.iy;
      sp = s6502_hle_direct_result.dt;
      status = s6502_hle_direct_result.status;
      goto _exit;
    }

  _hle_ebin_pixel_tail:
    {
      int hle_status = s6502_firmware_hle_pixel_tail(
          sp, status, cycles - executed, &s6502_hle_direct_result);

      if (hle_status <= 0) {
        S6502_HLE_BUDGET_REJECT(S6502_HLE_ID_PIXEL_TAIL);
        goto _next;
      }
      CYCLES(s6502_hle_direct_result.cycles);
      S6502_HLE_RECORD(
          S6502_HLE_ID_PIXEL_TAIL,
          s6502_hle_direct_result.cycles);
      pc = s6502_hle_direct_result.pc;
      ea = s6502_hle_direct_result.ea;
      ac = s6502_hle_direct_result.ac;
      ix = s6502_hle_direct_result.ix;
      iy = s6502_hle_direct_result.iy;
      sp = s6502_hle_direct_result.dt;
      status = s6502_hle_direct_result.status;
      goto _exit;
    }
#endif

  _hle_ebin_bitmap_copy:
    {
      uint8_t *hle_ram = s6502_stack_ram;
      uint32_t hle_batch_cycles = 0u;
      uint32_t hle_batch_hits = 0u;
      uint8_t hle_shift;
      uint8_t hle_dest_high;
      uint8_t hle_dest_carry;

      /* Execute as many complete $5CB3-$5D04 iterations as fit this CPU
       * slice.  IRQ/timer checks occur between s6502_exec() calls, so this
       * removes only redundant AOT dispatches inside the same slice. */
#ifdef GAM4980_ENABLE_DIRECT_RAM_HLE
      {
        if (s6502_hle_try_direct_bitmap_copy(
                hle_ram, dt, cycles - executed, et, status)) {
          CYCLES(s6502_hle_direct_result.cycles);
          hle_batch_cycles = s6502_hle_direct_result.cycles;
          hle_batch_hits = s6502_hle_direct_result.hits;
          pc = s6502_hle_direct_result.pc;
          ea = s6502_hle_direct_result.ea;
          ac = s6502_hle_direct_result.ac;
          ix = s6502_hle_direct_result.ix;
          iy = s6502_hle_direct_result.iy;
          dt = s6502_hle_direct_result.dt;
          status = s6502_hle_direct_result.status;
          if (hle_batch_hits > 1u)
            S6502_HLE_ATTEMPT_EXTRA(
                S6502_HLE_ID_BITMAP_COPY, hle_batch_hits - 1u);
          S6502_HLE_RECORD_BATCH(
              S6502_HLE_ID_BITMAP_COPY, hle_batch_hits, hle_batch_cycles);
          S6502_HLE_RECORD_DIRECT_BATCH(
              S6502_HLE_ID_BITMAP_COPY, hle_batch_hits);
          goto _exit;
        }
      }
#endif

      for (;;) {
        CYCLES(et);
        hle_batch_cycles += et;
        ++hle_batch_hits;

        iy = 0u;
        ea = (uint16_t)(hle_ram[0x2fu] | (hle_ram[0x30u] << 8));
        ac = READ8(ea);
        WRITE8(0x20e5u, ac);
        ea = (uint16_t)(ea + 1u);
        hle_ram[0x2fu] = (uint8_t)ea;
        hle_ram[0x30u] = (uint8_t)(ea >> 8);
        ix = READ8(ea);
        WRITE8(0x20e6u, ix);

        hle_shift = READ8(0x20cfu);
        et = (uint16_t)(((uint16_t)ac << 8) | ix);
        et = (uint16_t)(et >> hle_shift);
        WRITE8(0x20e5u, (uint8_t)(et >> 8));
        WRITE8(0x20e6u, (uint8_t)et);
        ix = 0u;

        ea = (uint16_t)(hle_ram[0x31u] | (hle_ram[0x32u] << 8));
        ac = (uint8_t)et;
        WRITE8(ea, ac);
        hle_dest_high = (uint8_t)(ea >> 8);
        hle_dest_carry = (uint8_t)((uint8_t)ea == 0xffu);
        ea = (uint16_t)(ea + 1u);
        hle_ram[0x31u] = (uint8_t)ea;
        hle_ram[0x32u] = (uint8_t)(ea >> 8);
        SET_V(hle_dest_carry && hle_dest_high == 0x7fu);

        dt = (uint8_t)(READ8(0x20d8u) - 1u);
        WRITE8(0x20d8u, dt);
        ac = dt;
        SET_C(1);
        SET_NZ(ac);
        pc = ac ? 0x5cb3u : 0x5d05u;
        if (!ac || executed >= cycles || sys_halt_p())
          break;
        hle_shift = READ8(0x20cfu);
        if (!(GAM4980_FIRMWARE_HLE_MASK & S6502_HLE_BITMAP_COPY) ||
            !s6502_firmware_hle_enabled || DECIMAL_p ||
            s6502_firmware_hle_banks[5] != 0x0eb8u ||
            s6502_firmware_hle_bitmap_validation != 1u ||
            hle_shift > 7u)
          break;
        dt = (uint8_t)(READ8(0x20d8u) - 1u);
        et = (uint16_t)((hle_shift == 0u ? 55u :
            (uint16_t)(53u + 19u * hle_shift)) +
            (dt ? 48u : 46u));
        if ((uint32_t)et > cycles - executed)
          break;
      }
      if (hle_batch_hits > 1u)
        S6502_HLE_ATTEMPT_EXTRA(
            S6502_HLE_ID_BITMAP_COPY, hle_batch_hits - 1u);
      S6502_HLE_RECORD_BATCH(
          S6502_HLE_ID_BITMAP_COPY, hle_batch_hits, hle_batch_cycles);
      goto _exit;
    }

  _hle_ebin_bitmap_copy_suffix_5ce5:
    {
      uint8_t *hle_ram = s6502_stack_ram;
      uint8_t hle_dest_high;
      uint8_t hle_dest_carry;

      /* Resume after the variable-count $20E5:$20E6 shift loop. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_BITMAP_COPY, et);
      iy = 0u;
      ea = (uint16_t)(hle_ram[0x31u] | (hle_ram[0x32u] << 8));
      ac = READ8(0x20e6u);
      WRITE8(ea, ac);
      hle_dest_high = (uint8_t)(ea >> 8);
      hle_dest_carry = (uint8_t)((uint8_t)ea == 0xffu);
      ea = (uint16_t)(ea + 1u);
      hle_ram[0x31u] = (uint8_t)ea;
      hle_ram[0x32u] = (uint8_t)(ea >> 8);
      SET_V(hle_dest_carry && hle_dest_high == 0x7fu);
      WRITE8(0x20d8u, dt);
      ac = READ8(0x20d8u);
      SET_C(1);
      SET_NZ(ac);
      pc = ac ? 0x5cb3u : 0x5d05u;
      goto _exit;
    }

  _hle_ebin_glyph_row:
    {
      s6502_hle_glyph_result_t hle_result;
      uint32_t hle_batch_cycles = 0u;
      uint32_t hle_batch_hits = 0u;

      /* Batch complete ASCII rows while preserving the original $650B CPX /
       * BEQ boundary and never crossing the scheduler's cycle budget. */
      for (;;) {
        CYCLES(et);
        hle_batch_cycles += et;
        ++hle_batch_hits;
        s6502_firmware_hle_glyph_row(ix, sp, status, &hle_result);
        ac = hle_result.ac;
        ix = hle_result.ix;
        iy = hle_result.iy;
        status = hle_result.status;
        if (ix >= 0x10u || executed >= cycles || sys_halt_p())
          break;
        et = s6502_firmware_hle_glyph_row_cycles(ix, 0);
        if ((uint32_t)et + 4u > cycles - executed)
          break;
        /* CPX #$10; BEQ (not taken). */
        status = (uint8_t)((status & ~0x83u) |
            ((uint8_t)(ix - 0x10u) & 0x80u));
        CYCLES(4u);
        hle_batch_cycles += 4u;
      }
      if (hle_batch_hits > 1u)
        S6502_HLE_ATTEMPT_EXTRA(
            S6502_HLE_ID_GLYPH_ROW, hle_batch_hits - 1u);
      S6502_HLE_RECORD_BATCH(
          S6502_HLE_ID_GLYPH_ROW, hle_batch_hits, hle_batch_cycles);
      pc = 0x650bu;
      goto _exit;
    }

  _hle_ebin_wide_glyph_row:
    {
      s6502_hle_glyph_result_t hle_result;
      uint32_t hle_batch_cycles = 0u;
      uint32_t hle_batch_hits = 0u;

      /* The Chinese compositor consumes two source bytes per row, hence X
       * advances by two and the loop terminates at $20. */
      for (;;) {
        CYCLES(et);
        hle_batch_cycles += et;
        ++hle_batch_hits;
        s6502_firmware_hle_wide_glyph_row(ix, sp, status, &hle_result);
        ac = hle_result.ac;
        ix = hle_result.ix;
        iy = hle_result.iy;
        status = hle_result.status;
        if (ix >= 0x20u || executed >= cycles || sys_halt_p())
          break;
        et = s6502_firmware_hle_glyph_row_cycles(ix, 1);
        if ((uint32_t)et + 4u > cycles - executed)
          break;
        /* CPX #$20; BEQ (not taken). */
        status = (uint8_t)((status & ~0x83u) |
            ((uint8_t)(ix - 0x20u) & 0x80u));
        CYCLES(4u);
        hle_batch_cycles += 4u;
      }
      if (hle_batch_hits > 1u)
        S6502_HLE_ATTEMPT_EXTRA(
            S6502_HLE_ID_WIDE_GLYPH, hle_batch_hits - 1u);
      S6502_HLE_RECORD_BATCH(
          S6502_HLE_ID_WIDE_GLYPH, hle_batch_hits, hle_batch_cycles);
      pc = 0x6086u;
      goto _exit;
    }

  _hle_ebin_shift_blit:
    {
      uint8_t *hle_ram = s6502_stack_ram;
      uint32_t hle_batch_cycles = 0u;
      uint32_t hle_batch_hits = 0u;
      uint8_t hle_shift;

      /* Batch complete $6A75-$6B04 iterations inside the current CPU slice;
       * stop before the first iteration that would cross its cycle budget. */
#if defined(GAM4980_ENABLE_DIRECT_RAM_HLE) || \
    defined(GAM4980_ENABLE_AGGRESSIVE_REGION_HLE)
      {
        if (s6502_hle_try_direct_shift_blit(
                hle_ram, dt, cycles - executed, et, status)) {
          CYCLES(s6502_hle_direct_result.cycles);
          hle_batch_cycles = s6502_hle_direct_result.cycles;
          hle_batch_hits = s6502_hle_direct_result.hits;
          pc = s6502_hle_direct_result.pc;
          ea = s6502_hle_direct_result.ea;
          ac = s6502_hle_direct_result.ac;
          ix = s6502_hle_direct_result.ix;
          iy = s6502_hle_direct_result.iy;
          dt = s6502_hle_direct_result.dt;
          status = s6502_hle_direct_result.status;
          if (hle_batch_hits > 1u)
            S6502_HLE_ATTEMPT_EXTRA(
                S6502_HLE_ID_SHIFT_BLIT, hle_batch_hits - 1u);
          S6502_HLE_RECORD_BATCH(
              S6502_HLE_ID_SHIFT_BLIT, hle_batch_hits, hle_batch_cycles);
          S6502_HLE_RECORD_DIRECT_BATCH(
              S6502_HLE_ID_SHIFT_BLIT, hle_batch_hits);
          goto _exit;
        }
      }
#endif

      for (;;) {
        CYCLES(et);
        hle_batch_cycles += et;
        ++hle_batch_hits;
        iy = READ8(0x20cfu);
        et = (uint16_t)(hle_ram[0x2fu] | (hle_ram[0x30u] << 8));
        ac = READ8(et);
        WRITE8(0x20e5u, ac);
        et = (uint16_t)(et + 1u);
        hle_ram[0x2fu] = (uint8_t)et;
        hle_ram[0x30u] = (uint8_t)(et >> 8);
        ix = READ8(et);
        WRITE8(0x20e6u, ix);
        et = (uint16_t)(((uint16_t)ac << 8) | ix);
        et = (uint16_t)(et >> iy);
        WRITE8(0x20e5u, (uint8_t)(et >> 8));
        WRITE8(0x20e6u, (uint8_t)et);
        ix = 0u;
        iy = 0u;

        if (ea == 0x0400u) {
          ac = READ8(0x20e6u);
          WRITE8(0x1000u, ac);
          ea = 0x0400u;
        } else {
          ac = READ8(0x20e6u);
          WRITE8(ea, ac);
        }
        ea = (uint16_t)(ea + 1u);
        hle_ram[0x3au] = (uint8_t)ea;
        hle_ram[0x3bu] = (uint8_t)(ea >> 8);

        WRITE8(0x20d8u, dt);
        ac = READ8(0x20d8u);
        SET_C(1);
        SET_NZ(ac);
        pc = ac ? 0x6a75u : 0x6b05u;
        if (!ac || executed >= cycles || sys_halt_p())
          break;
        hle_shift = READ8(0x20cfu);
        if (!(GAM4980_FIRMWARE_HLE_MASK & S6502_HLE_SHIFT_BLIT) ||
            !s6502_firmware_hle_enabled || DECIMAL_p ||
            s6502_firmware_hle_banks[6] != 0x0eb5u ||
            s6502_firmware_hle_validation != 1u || hle_shift > 7u)
          break;
        ea = (uint16_t)(hle_ram[0x3au] | (hle_ram[0x3bu] << 8));
        dt = (uint8_t)(READ8(0x20d8u) - 1u);
        et = (uint16_t)((hle_shift == 0u ? 55u :
            (uint16_t)(53u + 19u * hle_shift)) +
            (ea == 0x0400u ? 75u :
                ((ea >> 8) != 0x04u ? 31u : 41u)) +
            (dt ? 39u : 37u));
        if ((uint32_t)et > cycles - executed)
          break;
      }
      if (hle_batch_hits > 1u)
        S6502_HLE_ATTEMPT_EXTRA(
            S6502_HLE_ID_SHIFT_BLIT, hle_batch_hits - 1u);
      S6502_HLE_RECORD_BATCH(
          S6502_HLE_ID_SHIFT_BLIT, hle_batch_hits, hle_batch_cycles);
      goto _exit;
    }

  _hle_ebin_shift_blit_suffix_6aa7:
    {
      uint8_t *hle_ram = s6502_stack_ram;

      /* Resume exactly after the variable-count shift loop.  This entry is
       * reached when the full $6A75 HLE did not fit the previous exec slice;
       * its short suffix now fits without borrowing cycles from the next
       * timer/interrupt boundary. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_SHIFT_BLIT, et);
      if (ea == 0x0400u) {
        ac = READ8(0x20e6u);
        WRITE8(0x1000u, ac);
        ea = 0x0400u;
      } else {
        ac = READ8(0x20e6u);
        WRITE8(ea, ac);
      }
      ea = (uint16_t)(ea + 1u);
      hle_ram[0x3au] = (uint8_t)ea;
      hle_ram[0x3bu] = (uint8_t)(ea >> 8);
      WRITE8(0x20d8u, dt);
      ac = READ8(0x20d8u);
      SET_C(1);
      SET_NZ(ac);
      pc = ac ? 0x6a75u : 0x6b05u;
      goto _exit;
    }

  _hle_ebin_shift_blit_suffix_6ae0:
    {
      uint8_t *hle_ram = s6502_stack_ram;

      /* Common non-aliased destination path, after the $03E5-$03E7 checks. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_SHIFT_BLIT, et);
      iy = 0u;
      ea = (uint16_t)(hle_ram[0x3au] | (hle_ram[0x3bu] << 8));
      ac = READ8(0x20e6u);
      WRITE8(ea, ac);
      ea = (uint16_t)(ea + 1u);
      hle_ram[0x3au] = (uint8_t)ea;
      hle_ram[0x3bu] = (uint8_t)(ea >> 8);
      WRITE8(0x20d8u, dt);
      ac = READ8(0x20d8u);
      SET_C(1);
      SET_NZ(ac);
      pc = ac ? 0x6a75u : 0x6b05u;
      goto _exit;
    }

  _hle_ebin_byte_fill:
    {
      uint8_t *hle_ram = s6502_stack_ram;
      uint16_t hle_address;
      uint16_t hle_count;
      uint8_t hle_value;
      uint8_t hle_y;

      /* Collapse E.BIN $7937-$793f and the final $7933-$7936 loop test.
       * This primitive is called repeatedly while the opening scroll is
       * composed.  Keep WRITE8 so mapped I/O and 16-bit wrapping stay exact. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_BYTE_FILL, et);
      hle_count = ix;
      hle_y = iy;
      hle_value = 0u;
      while (hle_count != 0u) {
        /* $03 is the fourth direct-memory data port, not ordinary zero-page
         * RAM.  READ8 preserves its auto-increment side effect.  Reload the
         * destination pointer too, for exact low-RAM aliasing behavior. */
        hle_value = READ8(0x0003u);
        hle_address = (uint16_t)(
            hle_ram[0x2fu] | ((uint16_t)hle_ram[0x30u] << 8)
        );
        hle_address = (uint16_t)(hle_address + hle_y);
        WRITE8(hle_address, hle_value);
        ++hle_y;
        --hle_count;
      }
      iy = hle_y;
      ix = 0u;
      ac = hle_value;
      SET_C(1);
      SET_NZ(ix);
      pc = 0x7940u;
      goto _exit;
    }

  _hle_ebin_byte_fill_partial:
    {
      uint8_t *hle_ram = s6502_stack_ram;
      uint16_t hle_address;
      uint16_t hle_count = ea;
      uint8_t hle_value = ac;
      uint8_t hle_y = iy;
      uint8_t hle_x = ix;

      /* Consume only complete 20-cycle non-final iterations that fit the
       * current exec slice.  X remains nonzero, so the architectural resume
       * point is the original loop body at $7937. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_BYTE_FILL, et);
      while (hle_count-- != 0u) {
        hle_value = READ8(0x0003u);
        hle_address = (uint16_t)(
            hle_ram[0x2fu] | ((uint16_t)hle_ram[0x30u] << 8)
        );
        hle_address = (uint16_t)(hle_address + hle_y);
        WRITE8(hle_address, hle_value);
        ++hle_y;
        --hle_x;
      }
      ac = hle_value;
      iy = hle_y;
      ix = hle_x;
      SET_C(1);
      SET_NZ(ix);
      pc = 0x7937u;
      goto _exit;
    }

  _hle_ebin_bank_switch:
    {
      /* E.BIN $F52A-$F5BC: fgf_switch_bank_number().  This is the
       * compiler/runtime bank trampoline shared by A-series GAM programs.
       * Keep its real stack frame and low-memory register traffic: both can
       * be observed by callers even though the arithmetic itself is simple. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_BANK_SWITCH, et);
      PUSH(status | FLAG_B | FLAG_U);
      SET_I(1);
      WRITE8(0x2000u, ac);
      ac = ix;
      SET_NZ(ac);
      PUSH(ac);
      ac = iy;
      SET_NZ(ac);
      PUSH(ac);
      ac = READ8(0x2000u);
      SET_NZ(ac);
      if (ac >= 0xe0u) {
        SET_C(1);
        dt = 0xe0u;
        et = (uint16_t)(ac - dt);
        SET_C(ac >= dt);
        SET_V((ac ^ dt) & (ac ^ et) & 0x80u);
        ac = (uint8_t)et;
        SET_NZ(ac);
        WRITE8(0x2000u, ac);
        ac = READ8(0x2029u);
        SET_NZ(ac);
        WRITE8(0x2001u, ac);
        ac = READ8(0x202au);
        SET_NZ(ac);
        WRITE8(0x2002u, ac);
      } else {
        ac = READ8(0x03d6u);
        SET_NZ(ac);
        WRITE8(0x2001u, ac);
        ac = READ8(0x03d5u);
        SET_NZ(ac);
        WRITE8(0x2002u, ac);
      }
      goto _hle_ebin_bank_switch_do;
    }

  _hle_ebin_bank_switch_f549:
    {
      /* Suffix entry after the prologue and A >= $E0 branch. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_BANK_SWITCH, et);
      SET_C(1);
      dt = 0xe0u;
      et = (uint16_t)(ac - dt);
      SET_C(ac >= dt);
      SET_V((ac ^ dt) & (ac ^ et) & 0x80u);
      ac = (uint8_t)et;
      SET_NZ(ac);
      WRITE8(0x2000u, ac);
      ac = READ8(0x2029u);
      SET_NZ(ac);
      WRITE8(0x2001u, ac);
      ac = READ8(0x202au);
      SET_NZ(ac);
      WRITE8(0x2002u, ac);
      goto _hle_ebin_bank_switch_do;
    }

  _hle_ebin_bank_switch_f55b:
    {
      /* Suffix entry with BankSwitchTemp/Temp1 already prepared. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_BANK_SWITCH, et);
      goto _hle_ebin_bank_switch_do;
    }

  _hle_ebin_bank_switch_do:
    {
      uint16_t hle_sum;
      uint8_t hle_bank;

      ac = 5u;
      SET_NZ(ac);
      WRITE8(0x000cu, ac);

      ac = READ8(0x2000u);
      SET_NZ(ac);
      SET_C(ac & 0x80u);
      ac = (uint8_t)(ac << 1);
      SET_NZ(ac);
      ix = ac;
      SET_NZ(ix);
      ac = 0u;
      SET_NZ(ac);
      ac = (uint8_t)((ac << 1) | CARRY);
      SET_C(0);
      SET_NZ(ac);
      iy = ac;
      SET_NZ(iy);
      ac = ix;
      SET_NZ(ac);
      SET_C(ac & 0x80u);
      ac = (uint8_t)(ac << 1);
      SET_NZ(ac);
      ix = ac;
      SET_NZ(ix);
      ac = iy;
      SET_NZ(ac);
      ac = (uint8_t)((ac << 1) | CARRY);
      SET_C(0);
      SET_NZ(ac);
      iy = ac;
      SET_NZ(iy);

      ac = ix;
      SET_NZ(ac);
      SET_C(0);
      dt = READ8(0x2001u);
      hle_sum = (uint16_t)(ac + dt);
      SET_C(hle_sum > 0xffu);
      SET_V((ac ^ hle_sum) & (dt ^ hle_sum) & 0x80u);
      ac = (uint8_t)hle_sum;
      SET_NZ(ac);
      WRITE8(0x000du, ac);
      ac = iy;
      SET_NZ(ac);
      dt = READ8(0x2002u);
      hle_sum = (uint16_t)(ac + dt + CARRY);
      SET_C(hle_sum > 0xffu);
      SET_V((ac ^ hle_sum) & (dt ^ hle_sum) & 0x80u);
      ac = (uint8_t)hle_sum;
      SET_NZ(ac);
      WRITE8(0x000eu, ac);
      WRITE8(0x2000u, ac);

      /* Advance physical bank and logical selector for windows 6, 7 and 8.
       * WRITE8 is deliberate: $0C-$0E update the emulator's mapping table. */
      for (hle_bank = 0u; hle_bank < 3u; ++hle_bank) {
        ac = READ8(0x000du);
        SET_NZ(ac);
        dt = READ8(0x000cu);
        ++dt;
        SET_NZ(dt);
        WRITE8(0x000cu, dt);
        SET_C(0);
        hle_sum = (uint16_t)(ac + 1u);
        SET_C(hle_sum > 0xffu);
        SET_V((ac ^ hle_sum) & (1u ^ hle_sum) & 0x80u);
        ac = (uint8_t)hle_sum;
        SET_NZ(ac);
        WRITE8(0x000du, ac);
        ac = 0u;
        SET_NZ(ac);
        dt = READ8(0x2000u);
        hle_sum = (uint16_t)(ac + dt + CARRY);
        SET_C(hle_sum > 0xffu);
        SET_V((ac ^ hle_sum) & (dt ^ hle_sum) & 0x80u);
        ac = (uint8_t)hle_sum;
        SET_NZ(ac);
        WRITE8(0x000eu, ac);
        WRITE8(0x2000u, ac);
      }

      ac = POP();
      SET_NZ(ac);
      iy = ac;
      SET_NZ(iy);
      ac = POP();
      SET_NZ(ac);
      ix = ac;
      SET_NZ(ix);
      status = (uint8_t)(POP() | FLAG_U | FLAG_B);
      pc = POP();
      pc = (uint16_t)(pc | ((uint16_t)POP() << 8));
      pc = (uint16_t)(pc + 1u);
      goto _exit;
    }

  _hle_ebin_and_long:
    {
      uint16_t hle_left;
      uint16_t hle_right;
      uint16_t hle_output;
      uint16_t hle_sum;
      uint8_t hle_index;

      /* E.BIN $D2CA-$D2F5: __and_long().  Operands are indirect four-byte
       * values and the result is stored at __temp_store+8. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_AND_LONG, et);
      hle_left = READ16W(0x0020u);
      hle_right = READ16W(0x0023u);
      hle_output = READ16W(0x002au);
      for (hle_index = 0u; hle_index < 4u; ++hle_index) {
        iy = hle_index;
        SET_NZ(iy);
        ac = READ8((uint16_t)(hle_left + hle_index));
        SET_NZ(ac);
        dt = READ8((uint16_t)(hle_right + hle_index));
        ac = (uint8_t)(ac & dt);
        SET_NZ(ac);
        iy = (uint8_t)(8u + hle_index);
        SET_NZ(iy);
        WRITE8((uint16_t)(hle_output + iy), ac);
      }

      /* Preserve the nested JSR $D596 stack writes before folding
       * __ld_oper1_temp_store_addr into this call. */
      PUSH(0xd2u);
      PUSH(0xf4u);
      PUSH(ac);
      SET_C(0);
      ac = READ8(0x002au);
      SET_NZ(ac);
      dt = 8u;
      hle_sum = (uint16_t)(ac + dt);
      SET_C(hle_sum > 0xffu);
      SET_V((ac ^ hle_sum) & (dt ^ hle_sum) & 0x80u);
      ac = (uint8_t)hle_sum;
      SET_NZ(ac);
      WRITE8(0x0020u, ac);
      ac = READ8(0x002bu);
      SET_NZ(ac);
      dt = 0u;
      hle_sum = (uint16_t)(ac + CARRY);
      SET_C(hle_sum > 0xffu);
      SET_V((ac ^ hle_sum) & (dt ^ hle_sum) & 0x80u);
      ac = (uint8_t)hle_sum;
      SET_NZ(ac);
      WRITE8(0x0021u, ac);
      ac = POP();
      SET_NZ(ac);
      pc = POP();
      pc = (uint16_t)(pc | ((uint16_t)POP() << 8));
      pc = (uint16_t)(pc + 1u);
      pc = POP();
      pc = (uint16_t)(pc | ((uint16_t)POP() << 8));
      pc = (uint16_t)(pc + 1u);
      goto _exit;
    }

  _hle_ebin_load_oper1_temp:
    {
      uint16_t hle_sum;

      /* E.BIN $D596-$D5A5: __ld_oper1_temp_store_addr(). */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_LOAD_OPER1_TEMP, et);
      PUSH(ac);
      SET_C(0);
      ac = READ8(0x002au);
      SET_NZ(ac);
      dt = 8u;
      hle_sum = (uint16_t)(ac + dt);
      SET_C(hle_sum > 0xffu);
      SET_V((ac ^ hle_sum) & (dt ^ hle_sum) & 0x80u);
      ac = (uint8_t)hle_sum;
      SET_NZ(ac);
      WRITE8(0x0020u, ac);
      ac = READ8(0x002bu);
      SET_NZ(ac);
      dt = 0u;
      hle_sum = (uint16_t)(ac + CARRY);
      SET_C(hle_sum > 0xffu);
      SET_V((ac ^ hle_sum) & (dt ^ hle_sum) & 0x80u);
      ac = (uint8_t)hle_sum;
      SET_NZ(ac);
      WRITE8(0x0021u, ac);
      ac = POP();
      SET_NZ(ac);
      pc = POP();
      pc = (uint16_t)(pc | ((uint16_t)POP() << 8));
      pc = (uint16_t)(pc + 1u);
      goto _exit;
    }

  _hle_ebin_indirect_call:
    {
      uint16_t hle_difference;

      /* E.BIN $D572-$D585: __indirect_call().  It synthesizes an indirect
       * JSR by pushing target-1 and executing RTS, while leaving the caller's
       * return address underneath it. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_INDIRECT_CALL, et);
      iy = ac;
      SET_NZ(iy);
      SET_C(1);
      ac = READ8(0x0026u);
      SET_NZ(ac);
      dt = (uint8_t)~1u;
      hle_difference = (uint16_t)(ac + dt + CARRY);
      SET_C(hle_difference > 0xffu);
      SET_V((ac ^ hle_difference) & (dt ^ hle_difference) & 0x80u);
      ac = (uint8_t)hle_difference;
      SET_NZ(ac);
      WRITE8(0x0026u, ac);
      ac = READ8(0x0027u);
      SET_NZ(ac);
      dt = 0xffu;
      hle_difference = (uint16_t)(ac + dt + CARRY);
      SET_C(hle_difference > 0xffu);
      SET_V((ac ^ hle_difference) & (dt ^ hle_difference) & 0x80u);
      ac = (uint8_t)hle_difference;
      SET_NZ(ac);
      WRITE8(0x0027u, ac);
      PUSH(ac);
      ac = READ8(0x0026u);
      SET_NZ(ac);
      PUSH(ac);
      ac = iy;
      SET_NZ(ac);
      pc = POP();
      pc = (uint16_t)(pc | ((uint16_t)POP() << 8));
      pc = (uint16_t)(pc + 1u);
      goto _exit;
    }

  _hle_ebin_multiply16:
    {
      uint8_t *hle_ram = s6502_stack_ram;
      uint8_t hle_operand_low = hle_ram[0x20u];
      uint8_t hle_operand_high = hle_ram[0x21u];
      uint8_t hle_multiplier_low = hle_ram[0x23u];
      uint8_t hle_multiplier_high = hle_ram[0x24u];
      uint8_t hle_result_low = 0u;
      uint8_t hle_result_high = 0u;
      uint8_t hle_multiplier_byte;
      uint8_t hle_phase;
      uint8_t hle_loop;
      uint8_t hle_carry;
      uint16_t hle_sum;

      /* Collapse E.BIN $D1A2-$D200, the firmware's unsigned 16x16 -> low16
       * multiply.  Reproduce its stack traffic, return, flags and cycle count;
       * callers therefore observe the same state as after the original RTS. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_MULTIPLY16, et);
      PUSH(hle_multiplier_high);
      PUSH(hle_multiplier_low);
      hle_ram[0x26u] = 0u;
      hle_ram[0x27u] = 0u;

      if ((hle_operand_low | hle_operand_high) != 0u &&
          (hle_multiplier_low | hle_multiplier_high) != 0u) {
        hle_phase = hle_multiplier_high != 0u ? 2u : 1u;
        hle_multiplier_byte = hle_phase == 2u ?
          hle_multiplier_high : hle_multiplier_low;
        do {
          hle_loop = 8u;
          do {
            hle_carry = (uint8_t)(hle_result_low >> 7);
            hle_result_low = (uint8_t)(hle_result_low << 1);
            SET_C(hle_result_high & 0x80u);
            hle_result_high = (uint8_t)(
              (hle_result_high << 1) | hle_carry
            );

            hle_carry = (uint8_t)(hle_multiplier_byte >> 7);
            hle_multiplier_byte = (uint8_t)(hle_multiplier_byte << 1);
            SET_C(hle_carry);
            if (hle_carry) {
              hle_sum = (uint16_t)(hle_operand_low + hle_result_low);
              SET_C(hle_sum > 0xffu);
              SET_V((hle_operand_low ^ hle_sum) &
                    (hle_result_low ^ hle_sum) & 0x80u);
              hle_result_low = (uint8_t)hle_sum;

              hle_sum = (uint16_t)(
                hle_operand_high + hle_result_high + CARRY
              );
              SET_C(hle_sum > 0xffu);
              SET_V((hle_operand_high ^ hle_sum) &
                    (hle_result_high ^ hle_sum) & 0x80u);
              hle_result_high = (uint8_t)hle_sum;
            }
          } while (--hle_loop != 0u);

          if (hle_phase == 2u) {
            hle_phase = 1u;
            hle_multiplier_byte = hle_multiplier_low;
          } else {
            hle_phase = 0u;
          }
        } while (hle_phase != 0u);
        ix = 0u;
      }

      hle_ram[0x26u] = hle_result_low;
      hle_ram[0x27u] = hle_result_high;
      hle_ram[0x20u] = hle_result_low;
      hle_ram[0x21u] = hle_result_high;
      ac = POP();
      SET_NZ(ac);
      hle_ram[0x23u] = ac;
      ac = POP();
      SET_NZ(ac);
      hle_ram[0x24u] = ac;
      pc = POP();
      pc = (uint16_t)(pc | (POP() << 8));
      pc = (uint16_t)(pc + 1u);
      goto _exit;
    }

  _hle_ebin_compare_long:
    {
      uint16_t hle_left = READ16W(0x0020u);
      uint16_t hle_right = READ16W(0x0023u);
      uint16_t hle_difference = 0u;
      uint8_t hle_index;
      uint8_t hle_nonzero = 0u;
      uint8_t hle_final_status;

      /* E.BIN $D362-$D39A: __cmp_long().  This is the four-byte analogue
       * of the existing __cmp_int HLE and is emitted by the same C compiler
       * in all three sampled games. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_COMPARE_LONG, et);
      ix = 0u;
      SET_NZ(ix);
      iy = 0u;
      SET_NZ(iy);
      SET_C(1);
      for (hle_index = 0u; hle_index < 4u; ++hle_index) {
        iy = hle_index;
        ac = READ8((uint16_t)(hle_left + iy));
        SET_NZ(ac);
        dt = READ8((uint16_t)(hle_right + iy));
        dt = (uint8_t)~dt;
        hle_difference = (uint16_t)(ac + dt + CARRY);
        SET_C(hle_difference > 0xffu);
        SET_V((ac ^ hle_difference) & (dt ^ hle_difference) & 0x80u);
        ac = (uint8_t)hle_difference;
        SET_NZ(ac);
        if (ac != 0u) {
          ++hle_nonzero;
          ix = hle_nonzero;
        }
      }
      iy = 3u;
      hle_final_status = (uint8_t)(status | FLAG_B | FLAG_U);
      if (hle_nonzero)
        hle_final_status &= (uint8_t)~FLAG_Z;
      else
        hle_final_status |= FLAG_Z;
      s6502_stack_ram[0x100u | sp] = hle_final_status;
      ac = hle_final_status;
      ix = hle_nonzero;
      status = hle_final_status;
      pc = POP();
      pc = (uint16_t)(pc | ((uint16_t)POP() << 8));
      pc = (uint16_t)(pc + 1u);
      goto _exit;
    }

  _hle_ebin_compare16:
    {
      s6502_hle_compare_result_t hle_result;

      /* Collapse E.BIN $D340-$D361.  This helper is the firmware's hot
       * 16-bit comparison primitive and returns its result through flags. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_COMPARE16, et);
      s6502_firmware_hle_compare16(sp, status, &hle_result);
      pc = hle_result.pc;
      ac = hle_result.ac;
      ix = hle_result.ix;
      sp = hle_result.sp;
      status = hle_result.status;
      goto _exit;
    }

  _hle_ebin_compare16_suffix:
    {
      s6502_hle_compare_result_t hle_result;

      /* All internal compare checkpoints still have the caller's return
       * address at the original stack position.  Recompute the already known
       * comparison result, but charge only the exact unexecuted suffix. */
      CYCLES(et);
      S6502_HLE_RECORD(S6502_HLE_ID_COMPARE16, et);
      s6502_firmware_hle_compare16(sp, status, &hle_result);
      pc = hle_result.pc;
      ac = hle_result.ac;
      ix = hle_result.ix;
      sp = hle_result.sp;
      status = hle_result.status;
      goto _exit;
    }
