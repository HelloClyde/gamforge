/* Compact 65C02 resident loop for the 9288 IRAM overlay.
 *
 * This file is included after the direct-memory helpers in gam4980_core.c.
 * It must stay self-contained: the target build audits the resulting IRAM
 * section and rejects calls to external code.  Unsupported or side-effecting
 * memory operations leave PC at the unexecuted instruction so the complete
 * external interpreter can execute exactly one slow instruction.
 */
static S6502_IRAM_EXEC_ATTRIBUTE uint32_t s6502_iram_exec_burst(
    s6502_iram_exec_state_t *state, uint32_t cycle_budget,
    uint8_t *const *pages, uint8_t *ram, int *dirty,
    const uint8_t *dispatch_bits
)
{
    uint16_t pc = state->pc;
    uint8_t ac = state->ac;
    uint8_t ix = state->ix;
    uint8_t iy = state->iy;
    uint8_t sp = state->sp;
    uint8_t status = state->status;
    uint32_t cycles = 0u;
    uint32_t instructions = 0u;
    uint32_t control_transitions = 0u;
    uint8_t exit_reason = S6502_IRAM_EXIT_SLOW;

    while (instructions < S6502_IRAM_MAX_INSTRUCTIONS) {
        uint16_t instruction_pc = pc;
        uint16_t address = 0u;
        uint16_t base = 0u;
        uint16_t next_pc;
        uint8_t opcode;
        uint8_t operand = 0u;
        uint8_t value = 0u;
        uint8_t operation;
        uint8_t mode;
        uint8_t control = 0u;
        uint32_t instruction_cycles = 0u;

        if (!s6502_iram_read(pages, ram, pc, &opcode))
            goto unsupported;
        pc = (uint16_t)(pc + 1u);

        /* The regular cc=01 matrix covers ORA/AND/EOR/ADC/STA/LDA/CMP/SBC
         * across all eight standard addressing modes. */
        if ((opcode & 0x03u) == 0x01u) {
            operation = opcode >> 5;
            mode = (opcode >> 2) & 0x07u;
            if (operation == 4u && mode == 2u)
                goto special_opcode; /* 0x89 is 65C02 BIT #imm. */
            if ((operation == 3u || operation == 7u) &&
                (status & S6502_IRAM_FLAG_D))
                goto unsupported;

            switch (mode) {
            case 0u: /* (zp,X) */
                if (!s6502_iram_read(pages, ram, pc, &operand) ||
                    !s6502_iram_read16_zp(
                        pages, ram, (uint8_t)(operand + ix), &address))
                    goto unsupported;
                ++pc;
                instruction_cycles = 6u;
                break;
            case 1u: /* zp */
                if (!s6502_iram_read(pages, ram, pc, &operand))
                    goto unsupported;
                ++pc;
                address = operand;
                instruction_cycles = 3u;
                break;
            case 2u: /* #imm */
                if (!s6502_iram_read(pages, ram, pc, &value))
                    goto unsupported;
                ++pc;
                instruction_cycles = 2u;
                break;
            case 3u: /* abs */
                if (!s6502_iram_read16(pages, ram, pc, &address))
                    goto unsupported;
                pc = (uint16_t)(pc + 2u);
                instruction_cycles = 4u;
                break;
            case 4u: /* (zp),Y */
                if (!s6502_iram_read(pages, ram, pc, &operand) ||
                    !s6502_iram_read16_zp(pages, ram, operand, &base))
                    goto unsupported;
                ++pc;
                address = (uint16_t)(base + iy);
                instruction_cycles = operation == 4u
                    ? 6u : 5u + (((base ^ address) & 0xff00u) ? 1u : 0u);
                break;
            case 5u: /* zp,X */
                if (!s6502_iram_read(pages, ram, pc, &operand))
                    goto unsupported;
                ++pc;
                address = (uint8_t)(operand + ix);
                instruction_cycles = 4u;
                break;
            case 6u: /* abs,Y */
                if (!s6502_iram_read16(pages, ram, pc, &base))
                    goto unsupported;
                pc = (uint16_t)(pc + 2u);
                address = (uint16_t)(base + iy);
                instruction_cycles = operation == 4u
                    ? 5u : 4u + (((base ^ address) & 0xff00u) ? 1u : 0u);
                break;
            default: /* abs,X */
                if (!s6502_iram_read16(pages, ram, pc, &base))
                    goto unsupported;
                pc = (uint16_t)(pc + 2u);
                address = (uint16_t)(base + ix);
                instruction_cycles = operation == 4u
                    ? 5u : 4u + (((base ^ address) & 0xff00u) ? 1u : 0u);
                break;
            }
            if (operation != 4u && mode != 2u &&
                !s6502_iram_read(pages, ram, address, &value))
                goto unsupported;
            switch (operation) {
            case 0u:
                ac |= value;
                status = s6502_iram_nz(status, ac);
                break;
            case 1u:
                ac &= value;
                status = s6502_iram_nz(status, ac);
                break;
            case 2u:
                ac ^= value;
                status = s6502_iram_nz(status, ac);
                break;
            case 3u:
                s6502_iram_add(value, &ac, &status);
                break;
            case 4u:
                if (!s6502_iram_write(pages, ram, dirty, address, ac))
                    goto unsupported;
                break;
            case 5u:
                ac = value;
                status = s6502_iram_nz(status, ac);
                break;
            case 6u:
                s6502_iram_compare(ac, value, &status);
                break;
            default:
                s6502_iram_add((uint8_t)~value, &ac, &status);
                break;
            }
            cycles += instruction_cycles;
            goto instruction_complete;
        }

        /* The cc=10 matrix shares all shifts, rotates, X loads/stores and
         * increment/decrement memory operations. */
        if ((opcode & 0x03u) == 0x02u) {
            operation = opcode >> 5;
            mode = (opcode >> 2) & 0x07u;
            if (operation <= 3u) {
                if (mode != 1u && mode != 2u && mode != 3u &&
                    mode != 5u && mode != 7u)
                    goto special_opcode;
            } else if (operation == 4u) {
                if (mode != 1u && mode != 3u && mode != 5u)
                    goto special_opcode;
            } else if (operation == 5u) {
                if (mode != 0u && mode != 1u && mode != 3u &&
                    mode != 5u && mode != 7u)
                    goto special_opcode;
            } else if (mode != 1u && mode != 3u &&
                       mode != 5u && mode != 7u) {
                goto special_opcode;
            }

            if (mode == 2u) {
                value = ac;
                instruction_cycles = 2u;
            } else if (mode == 0u) {
                if (!s6502_iram_read(pages, ram, pc, &value))
                    goto unsupported;
                ++pc;
                instruction_cycles = 2u;
            } else if (mode == 1u || mode == 5u) {
                if (!s6502_iram_read(pages, ram, pc, &operand))
                    goto unsupported;
                ++pc;
                address = operand;
                if (mode == 5u)
                    address = (uint8_t)(operand +
                        ((operation == 4u || operation == 5u) ? iy : ix));
                instruction_cycles = mode == 1u
                    ? ((operation == 4u || operation == 5u) ? 3u : 5u)
                    : ((operation == 4u || operation == 5u) ? 4u : 6u);
            } else {
                if (!s6502_iram_read16(pages, ram, pc, &base))
                    goto unsupported;
                pc = (uint16_t)(pc + 2u);
                address = base;
                if (mode == 7u)
                    address = (uint16_t)(base +
                        (operation == 5u ? iy : ix));
                if (mode == 3u)
                    instruction_cycles =
                        (operation == 4u || operation == 5u) ? 4u : 6u;
                else if (operation == 5u)
                    instruction_cycles = 4u +
                        (((base ^ address) & 0xff00u) ? 1u : 0u);
                else if (operation >= 6u)
                    instruction_cycles = 7u;
                else
                    instruction_cycles = 6u +
                        (((base ^ address) & 0xff00u) ? 1u : 0u);
            }
            if (mode != 0u && mode != 2u && operation != 4u &&
                !s6502_iram_read(pages, ram, address, &value))
                goto unsupported;
            if (operation <= 3u) {
                uint8_t carry = (status & S6502_IRAM_FLAG_C) ? 1u : 0u;
                uint8_t next_carry;

                if (operation == 0u) {
                    next_carry = value >> 7;
                    value = (uint8_t)(value << 1);
                } else if (operation == 1u) {
                    next_carry = value >> 7;
                    value = (uint8_t)((value << 1) | carry);
                } else if (operation == 2u) {
                    next_carry = value & 1u;
                    value >>= 1;
                } else {
                    next_carry = value & 1u;
                    value = (uint8_t)((value >> 1) | (carry << 7));
                }
                status = (uint8_t)((status & ~S6502_IRAM_FLAG_C) |
                    (next_carry ? S6502_IRAM_FLAG_C : 0u));
                status = s6502_iram_nz(status, value);
                if (mode == 2u)
                    ac = value;
                else if (!s6502_iram_write(
                             pages, ram, dirty, address, value))
                    goto unsupported;
            } else if (operation == 4u) {
                if (!s6502_iram_write(pages, ram, dirty, address, ix))
                    goto unsupported;
            } else if (operation == 5u) {
                ix = value;
                status = s6502_iram_nz(status, ix);
            } else {
                value = operation == 6u
                    ? (uint8_t)(value - 1u) : (uint8_t)(value + 1u);
                status = s6502_iram_nz(status, value);
                if (!s6502_iram_write(pages, ram, dirty, address, value))
                    goto unsupported;
            }
            cycles += instruction_cycles;
            goto instruction_complete;
        }

special_opcode:
        switch (opcode) {
        case 0x08: /* PHP */
            ram[0x100u | sp] = (uint8_t)(status |
                S6502_IRAM_FLAG_B | S6502_IRAM_FLAG_U);
            --sp;
            cycles += 3u;
            break;
        case 0x18: /* CLC */
            status &= (uint8_t)~S6502_IRAM_FLAG_C;
            cycles += 2u;
            break;
        case 0x20: /* JSR abs */
            if (!s6502_iram_read16(pages, ram, pc, &address))
                goto unsupported;
            next_pc = (uint16_t)(pc + 1u);
            ram[0x100u | sp] = (uint8_t)(next_pc >> 8);
            --sp;
            ram[0x100u | sp] = (uint8_t)next_pc;
            --sp;
            pc = address;
            cycles += 6u;
            control = 1u;
            break;
        case 0x24: /* BIT zp */
        case 0x2c: /* BIT abs */
        case 0x34: /* BIT zp,X */
        case 0x3c: /* BIT abs,X */
            if (opcode == 0x24u || opcode == 0x34u) {
                if (!s6502_iram_read(pages, ram, pc, &operand))
                    goto unsupported;
                ++pc;
                address = opcode == 0x34u
                    ? (uint8_t)(operand + ix) : operand;
                instruction_cycles = opcode == 0x34u ? 4u : 3u;
            } else {
                if (!s6502_iram_read16(pages, ram, pc, &base))
                    goto unsupported;
                pc = (uint16_t)(pc + 2u);
                address = opcode == 0x3cu
                    ? (uint16_t)(base + ix) : base;
                instruction_cycles = 4u;
            }
            if (!s6502_iram_read(pages, ram, address, &value))
                goto unsupported;
            status = (uint8_t)((status & ~(S6502_IRAM_FLAG_N |
                S6502_IRAM_FLAG_V | S6502_IRAM_FLAG_Z)) |
                (value & (S6502_IRAM_FLAG_N | S6502_IRAM_FLAG_V)) |
                ((ac & value) ? 0u : S6502_IRAM_FLAG_Z));
            cycles += instruction_cycles;
            break;
        case 0x28: /* PLP */
            status = (uint8_t)(ram[0x100u | ++sp] |
                S6502_IRAM_FLAG_U | S6502_IRAM_FLAG_B);
            cycles += 4u;
            break;
        case 0x38: /* SEC */
            status |= S6502_IRAM_FLAG_C;
            cycles += 2u;
            break;
        case 0x40: /* RTI */
            status = (uint8_t)(ram[0x100u | ++sp] |
                S6502_IRAM_FLAG_U | S6502_IRAM_FLAG_B);
            pc = ram[0x100u | ++sp];
            pc |= (uint16_t)ram[0x100u | ++sp] << 8;
            cycles += 6u;
            control = 1u;
            break;
        case 0x48: /* PHA */
            ram[0x100u | sp] = ac;
            --sp;
            cycles += 3u;
            break;
        case 0x4c: /* JMP abs */
            if (!s6502_iram_read16(pages, ram, pc, &address))
                goto unsupported;
            pc = address;
            cycles += 3u;
            control = 1u;
            break;
        case 0x58: /* CLI */
            status &= (uint8_t)~S6502_IRAM_FLAG_I;
            cycles += 2u;
            break;
        case 0x5a: /* PHY */
            ram[0x100u | sp] = iy;
            --sp;
            cycles += 3u;
            break;
        case 0x60: /* RTS */
            address = ram[0x100u | ++sp];
            address |= (uint16_t)ram[0x100u | ++sp] << 8;
            pc = (uint16_t)(address + 1u);
            cycles += 6u;
            control = 1u;
            break;
        case 0x64: /* STZ zp */
        case 0x74: /* STZ zp,X */
        case 0x9c: /* STZ abs */
        case 0x9e: /* STZ abs,X */
            if (opcode == 0x64u || opcode == 0x74u) {
                if (!s6502_iram_read(pages, ram, pc, &operand))
                    goto unsupported;
                ++pc;
                address = opcode == 0x74u
                    ? (uint8_t)(operand + ix) : operand;
                instruction_cycles = opcode == 0x74u ? 4u : 3u;
            } else {
                if (!s6502_iram_read16(pages, ram, pc, &base))
                    goto unsupported;
                pc = (uint16_t)(pc + 2u);
                address = opcode == 0x9eu
                    ? (uint16_t)(base + ix) : base;
                instruction_cycles = opcode == 0x9eu ? 5u : 4u;
            }
            if (!s6502_iram_write(pages, ram, dirty, address, 0u))
                goto unsupported;
            cycles += instruction_cycles;
            break;
        case 0x68: /* PLA */
            ac = ram[0x100u | ++sp];
            status = s6502_iram_nz(status, ac);
            cycles += 4u;
            break;
        case 0x6c: /* JMP (abs) */
        case 0x7c: /* JMP (abs,X) */
            if (!s6502_iram_read16(pages, ram, pc, &base))
                goto unsupported;
            if (opcode == 0x7cu)
                base = (uint16_t)(base + ix);
            if (!s6502_iram_read16(pages, ram, base, &address))
                goto unsupported;
            pc = address;
            cycles += 6u;
            control = 1u;
            break;
        case 0x78: /* SEI */
            status |= S6502_IRAM_FLAG_I;
            cycles += 2u;
            break;
        case 0x7a: /* PLY */
            iy = ram[0x100u | ++sp];
            status = s6502_iram_nz(status, iy);
            cycles += 4u;
            break;
        case 0x80: /* BRA */
        case 0x10: /* BPL */
        case 0x30: /* BMI */
        case 0x50: /* BVC */
        case 0x70: /* BVS */
        case 0x90: /* BCC */
        case 0xb0: /* BCS */
        case 0xd0: /* BNE */
        case 0xf0: /* BEQ */
        {
            uint16_t target;
            int take;

            if (!s6502_iram_read(pages, ram, pc, &operand))
                goto unsupported;
            next_pc = (uint16_t)(pc + 1u);
            target = (uint16_t)(next_pc + (int8_t)operand);
            switch (opcode) {
            case 0x10: take = !(status & S6502_IRAM_FLAG_N); break;
            case 0x30: take = !!(status & S6502_IRAM_FLAG_N); break;
            case 0x50: take = !(status & S6502_IRAM_FLAG_V); break;
            case 0x70: take = !!(status & S6502_IRAM_FLAG_V); break;
            case 0x80: take = 1; break;
            case 0x90: take = !(status & S6502_IRAM_FLAG_C); break;
            case 0xb0: take = !!(status & S6502_IRAM_FLAG_C); break;
            case 0xd0: take = !(status & S6502_IRAM_FLAG_Z); break;
            default: take = !!(status & S6502_IRAM_FLAG_Z); break;
            }
            pc = take ? target : next_pc;
            cycles += 2u;
            if (take) {
                ++cycles;
                if ((next_pc ^ target) & 0xff00u)
                    ++cycles;
            }
            control = 1u;
            break;
        }
        case 0x84: /* STY zp */
        case 0x8c: /* STY abs */
        case 0x94: /* STY zp,X */
        case 0xa0: /* LDY #imm */
        case 0xa4: /* LDY zp */
        case 0xac: /* LDY abs */
        case 0xb4: /* LDY zp,X */
        case 0xbc: /* LDY abs,X */
        case 0xc0: /* CPY #imm */
        case 0xc4: /* CPY zp */
        case 0xcc: /* CPY abs */
        case 0xe0: /* CPX #imm */
        case 0xe4: /* CPX zp */
        case 0xec: /* CPX abs */
        {
            uint8_t kind = opcode >> 5;
            uint8_t low = opcode & 0x1fu;

            if (low == 0x00u) {
                if (!s6502_iram_read(pages, ram, pc, &value))
                    goto unsupported;
                ++pc;
                instruction_cycles = 2u;
            } else if (low == 0x04u || low == 0x14u) {
                if (!s6502_iram_read(pages, ram, pc, &operand))
                    goto unsupported;
                ++pc;
                address = low == 0x14u
                    ? (uint8_t)(operand + ix) : operand;
                instruction_cycles = low == 0x14u ? 4u : 3u;
                if (kind != 4u &&
                    !s6502_iram_read(pages, ram, address, &value))
                    goto unsupported;
            } else {
                if (!s6502_iram_read16(pages, ram, pc, &base))
                    goto unsupported;
                pc = (uint16_t)(pc + 2u);
                address = low == 0x1cu
                    ? (uint16_t)(base + ix) : base;
                instruction_cycles = 4u;
                if (kind != 4u &&
                    !s6502_iram_read(pages, ram, address, &value))
                    goto unsupported;
            }
            if (kind == 4u) {
                if (!s6502_iram_write(pages, ram, dirty, address, iy))
                    goto unsupported;
            } else if (kind == 5u) {
                iy = value;
                status = s6502_iram_nz(status, iy);
            } else {
                s6502_iram_compare(kind == 6u ? iy : ix, value, &status);
            }
            cycles += instruction_cycles;
            break;
        }
        case 0x88: /* DEY */
            --iy;
            status = s6502_iram_nz(status, iy);
            cycles += 2u;
            break;
        case 0x89: /* BIT #imm */
            if (!s6502_iram_read(pages, ram, pc, &value))
                goto unsupported;
            ++pc;
            status = (uint8_t)((status & ~S6502_IRAM_FLAG_Z) |
                ((ac & value) ? 0u : S6502_IRAM_FLAG_Z));
            cycles += 2u;
            break;
        case 0x8a: /* TXA */
            ac = ix;
            status = s6502_iram_nz(status, ac);
            cycles += 2u;
            break;
        case 0x98: /* TYA */
            ac = iy;
            status = s6502_iram_nz(status, ac);
            cycles += 2u;
            break;
        case 0x9a: /* TXS */
            sp = ix;
            cycles += 2u;
            break;
        case 0xa8: /* TAY */
            iy = ac;
            status = s6502_iram_nz(status, iy);
            cycles += 2u;
            break;
        case 0xaa: /* TAX */
            ix = ac;
            status = s6502_iram_nz(status, ix);
            cycles += 2u;
            break;
        case 0xb8: /* CLV */
            status &= (uint8_t)~S6502_IRAM_FLAG_V;
            cycles += 2u;
            break;
        case 0xba: /* TSX */
            ix = sp;
            status = s6502_iram_nz(status, ix);
            cycles += 2u;
            break;
        case 0xc8: /* INY */
            ++iy;
            status = s6502_iram_nz(status, iy);
            cycles += 2u;
            break;
        case 0xca: /* DEX */
            --ix;
            status = s6502_iram_nz(status, ix);
            cycles += 2u;
            break;
        case 0xd8: /* CLD */
            status &= (uint8_t)~S6502_IRAM_FLAG_D;
            cycles += 2u;
            break;
        case 0xda: /* PHX */
            ram[0x100u | sp] = ix;
            --sp;
            cycles += 3u;
            break;
        case 0xe8: /* INX */
            ++ix;
            status = s6502_iram_nz(status, ix);
            cycles += 2u;
            break;
        case 0xea: /* NOP */
            cycles += 2u;
            break;
        case 0xf8: /* SED */
            status |= S6502_IRAM_FLAG_D;
            cycles += 2u;
            break;
        case 0xfa: /* PLX */
            ix = ram[0x100u | ++sp];
            status = s6502_iram_nz(status, ix);
            cycles += 4u;
            break;
        default:
            /* 65C02 direct zero-page indirect forms. */
            if ((opcode & 0x1fu) == 0x12u) {
                operation = opcode >> 5;
                if ((operation == 3u || operation == 7u) &&
                    (status & S6502_IRAM_FLAG_D))
                    goto unsupported;
                if (!s6502_iram_read(pages, ram, pc, &operand) ||
                    !s6502_iram_read16_zp(pages, ram, operand, &address))
                    goto unsupported;
                ++pc;
                if (operation != 4u &&
                    !s6502_iram_read(pages, ram, address, &value))
                    goto unsupported;
                switch (operation) {
                case 0u: ac |= value; status = s6502_iram_nz(status, ac); break;
                case 1u: ac &= value; status = s6502_iram_nz(status, ac); break;
                case 2u: ac ^= value; status = s6502_iram_nz(status, ac); break;
                case 3u: s6502_iram_add(value, &ac, &status); break;
                case 4u:
                    if (!s6502_iram_write(pages, ram, dirty, address, ac))
                        goto unsupported;
                    break;
                case 5u: ac = value; status = s6502_iram_nz(status, ac); break;
                case 6u: s6502_iram_compare(ac, value, &status); break;
                default:
                    s6502_iram_add((uint8_t)~value, &ac, &status);
                    break;
                }
                cycles += 5u;
                break;
            }
            goto unsupported;
        }

instruction_complete:
        ++instructions;
        if (!control)
            continue;
        ++control_transitions;
        if (cycles >= cycle_budget || (ram[_SYSCON] & 0x08u)) {
            exit_reason = S6502_IRAM_EXIT_DEADLINE;
            break;
        }
        if (dispatch_bits &&
            (dispatch_bits[pc >> 3] & (uint8_t)(1u << (pc & 7u)))) {
            exit_reason = S6502_IRAM_EXIT_DISPATCH;
            break;
        }
        continue;

unsupported:
        pc = instruction_pc;
        exit_reason = S6502_IRAM_EXIT_SLOW;
        break;
    }
    if (instructions >= S6502_IRAM_MAX_INSTRUCTIONS)
        exit_reason = S6502_IRAM_EXIT_DEADLINE;
    state->pc = pc;
    state->ac = ac;
    state->ix = ix;
    state->iy = iy;
    state->sp = sp;
    state->status = status;
    state->instructions = instructions;
    state->control_transitions = control_transitions;
    state->exit_reason = exit_reason;
    return cycles |
        ((exit_reason == S6502_IRAM_EXIT_DEADLINE ||
          exit_reason == S6502_IRAM_EXIT_DISPATCH)
            ? 0x80000000u : 0u);
}
