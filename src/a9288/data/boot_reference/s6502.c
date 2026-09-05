
#include "gam4980_types.h"
#ifndef S6502_CPU_TYPE_DEFINED
#define S6502_CPU_TYPE_DEFINED
typedef struct {
  uint16_t pc;
  uint8_t ac;
  uint8_t ix;
  uint8_t iy;
  uint8_t sp;
  uint8_t status;
} s6502_t;
#endif
#ifndef S6502_EXEC_FUNCTION
#define S6502_EXEC_FUNCTION s6502_exec
#define S6502_EXEC_FUNCTION_LOCAL
#endif
uint32_t S6502_EXEC_FUNCTION(s6502_t *u, uint32_t cycles) {
#if !defined(S6502_NO_COMPUTED_GOTO) && \
    !defined(S6502_NATIVE_CHAIN_ONLY)
  static void *_table[0x100] = {
      &&_00, &&_01, &&_02, &&_03, &&_04, &&_05, &&_06, &&_07, &&_08, &&_09,
      &&_0a, &&_0b, &&_0c, &&_0d, &&_0e, &&_0f, &&_10, &&_11, &&_12, &&_13,
      &&_14, &&_15, &&_16, &&_17, &&_18, &&_19, &&_1a, &&_1b, &&_1c, &&_1d,
      &&_1e, &&_1f, &&_20, &&_21, &&_22, &&_23, &&_24, &&_25, &&_26, &&_27,
      &&_28, &&_29, &&_2a, &&_2b, &&_2c, &&_2d, &&_2e, &&_2f, &&_30, &&_31,
      &&_32, &&_33, &&_34, &&_35, &&_36, &&_37, &&_38, &&_39, &&_3a, &&_3b,
      &&_3c, &&_3d, &&_3e, &&_3f, &&_40, &&_41, &&_42, &&_43, &&_44, &&_45,
      &&_46, &&_47, &&_48, &&_49, &&_4a, &&_4b, &&_4c, &&_4d, &&_4e, &&_4f,
      &&_50, &&_51, &&_52, &&_53, &&_54, &&_55, &&_56, &&_57, &&_58, &&_59,
      &&_5a, &&_5b, &&_5c, &&_5d, &&_5e, &&_5f, &&_60, &&_61, &&_62, &&_63,
      &&_64, &&_65, &&_66, &&_67, &&_68, &&_69, &&_6a, &&_6b, &&_6c, &&_6d,
      &&_6e, &&_6f, &&_70, &&_71, &&_72, &&_73, &&_74, &&_75, &&_76, &&_77,
      &&_78, &&_79, &&_7a, &&_7b, &&_7c, &&_7d, &&_7e, &&_7f, &&_80, &&_81,
      &&_82, &&_83, &&_84, &&_85, &&_86, &&_87, &&_88, &&_89, &&_8a, &&_8b,
      &&_8c, &&_8d, &&_8e, &&_8f, &&_90, &&_91, &&_92, &&_93, &&_94, &&_95,
      &&_96, &&_97, &&_98, &&_99, &&_9a, &&_9b, &&_9c, &&_9d, &&_9e, &&_9f,
      &&_a0, &&_a1, &&_a2, &&_a3, &&_a4, &&_a5, &&_a6, &&_a7, &&_a8, &&_a9,
      &&_aa, &&_ab, &&_ac, &&_ad, &&_ae, &&_af, &&_b0, &&_b1, &&_b2, &&_b3,
      &&_b4, &&_b5, &&_b6, &&_b7, &&_b8, &&_b9, &&_ba, &&_bb, &&_bc, &&_bd,
      &&_be, &&_bf, &&_c0, &&_c1, &&_c2, &&_c3, &&_c4, &&_c5, &&_c6, &&_c7,
      &&_c8, &&_c9, &&_ca, &&_cb, &&_cc, &&_cd, &&_ce, &&_cf, &&_d0, &&_d1,
      &&_d2, &&_d3, &&_d4, &&_d5, &&_d6, &&_d7, &&_d8, &&_d9, &&_da, &&_db,
      &&_dc, &&_dd, &&_de, &&_df, &&_e0, &&_e1, &&_e2, &&_e3, &&_e4, &&_e5,
      &&_e6, &&_e7, &&_e8, &&_e9, &&_ea, &&_eb, &&_ec, &&_ed, &&_ee, &&_ef,
      &&_f0, &&_f1, &&_f2, &&_f3, &&_f4, &&_f5, &&_f6, &&_f7, &&_f8, &&_f9,
      &&_fa, &&_fb, &&_fc, &&_fd, &&_fe, &&_ff};
#endif
#if defined(S6502_AOT_DISPATCH) && !defined(S6502_NATIVE_HLE_ONLY) && \
    !defined(S6502_FIRMWARE_AOT_EXTERNAL)
#define S6502_AOT_DEFINE_TOKEN_TABLE
#include "s6502_aot_ebin_generated.h"
#undef S6502_AOT_DEFINE_TOKEN_TABLE
#endif
#define CYCLES(n) executed += n
#define EXIT goto _exit
#define NEXT goto _next
#define FLAG_N 0x80
#define FLAG_V 0x40
#define FLAG_U 0x20
#define FLAG_B 0x10
#define FLAG_D 0x08
#define FLAG_I 0x04
#define FLAG_Z 0x02
#define FLAG_C 0x01
#define NEGATIVE_p (status & FLAG_N)
#define OVERFLOW_p (status & FLAG_V)
#define DECIMAL_p (status & FLAG_D)
#define ZERO_p (status & FLAG_Z)
#define CARRY_p (status & FLAG_C)
#define CARRY (CARRY_p ? 1 : 0)
#define SET_BIT(flag, x)                                                       \
  status = (status & ~flag);                                                   \
  status = (status | (!!(x) * flag))
#define SET_N(x) SET_BIT(FLAG_N, x)
#define SET_V(x) SET_BIT(FLAG_V, x)
#define SET_D(x) SET_BIT(FLAG_D, x)
#define SET_I(x) SET_BIT(FLAG_I, x)
#define SET_Z(x) SET_BIT(FLAG_Z, x)
#define SET_C(x) SET_BIT(FLAG_C, x)
#define SET_NZ(x)                                                              \
  {                                                                            \
    uint8_t v = x;                                                             \
    status = (status & ~(FLAG_N | FLAG_Z));                                    \
    status = (status | (v & FLAG_N));                                          \
    status = (status | (!v * FLAG_Z));                                         \
  }
#ifdef S6502_FAST_STACK_RAM
#define PUSH(x)                                                                \
  S6502_FAST_STACK_RAM[0x100u | sp] = (uint8_t)(x);                            \
  sp -= 1
#define POP(x) S6502_FAST_STACK_RAM[0x100u | ++sp]
#else
#define PUSH(x)                                                                \
  WRITE8((0x100 | sp), x);                                                     \
  sp -= 1
#define POP(x) READ8((0x100 | ++sp))
#endif
  {
    uint32_t executed = 0;
#if defined(S6502_AOT_DISPATCH) && !defined(S6502_NATIVE_HLE_ONLY) && \
    !defined(S6502_FIRMWARE_AOT_EXTERNAL)
    uint16_t aot_next_token = 0u;
#endif
    uint8_t dt = 0;
    uint16_t et = 0;
    uint16_t ea = 0;
    uint16_t pc = u->pc;
    uint8_t ac = u->ac;
    uint8_t ix = u->ix;
    uint8_t iy = u->iy;
    uint8_t sp = u->sp;
    uint8_t status = u->status;
#ifdef S6502_GAME_AOT_DISPATCH
#ifndef S6502_NATIVE_HLE_ONLY
    uint16_t game_aot_entry_id = 0;
    uint16_t game_aot_hash_slot = 0;
#endif
    uint32_t game_aot_physical_pc = 0;
#ifndef S6502_NATIVE_HLE_ONLY
    const s6502_game_aot_entry_t *game_aot_entry = 0;
    const uint8_t *game_aot_code = 0;
#endif
#ifdef S6502_GAME_HLE_LOCALS
    S6502_GAME_HLE_LOCALS
#endif
#endif
#ifdef S6502_INSTRUCTION_HOOK
    uint16_t instruction_pc;
    uint8_t instruction_opcode;
#define S6502_FETCH_OPCODE()                                                  \
    (instruction_pc = pc, instruction_opcode = READX8(pc++),                 \
     S6502_INSTRUCTION_HOOK(instruction_pc, instruction_opcode),             \
     instruction_opcode)
#else
#define S6502_FETCH_OPCODE() READX8(pc++)
#endif
  _exit:
#if defined(S6502_TEST_STOP_PREDICATE)
    if (S6502_TEST_STOP_PREDICATE(pc) && executed) {
#elif defined(S6502_TEST_STOP_PC)
    if (pc == (uint16_t)S6502_TEST_STOP_PC && executed) {
#endif
#if defined(S6502_TEST_STOP_PREDICATE) || defined(S6502_TEST_STOP_PC)
      u->pc = pc;
      u->ac = ac;
      u->ix = ix;
      u->iy = iy;
      u->sp = sp;
      u->status = status;
      return executed;
    }
#endif
    if ((executed >= cycles) || sys_halt_p()) {
#if (defined(S6502_AOT_DISPATCH) && !defined(S6502_NATIVE_HLE_ONLY) && \
    !defined(S6502_FIRMWARE_AOT_EXTERNAL)) || \
    defined(S6502_GAME_AOT_DISPATCH)
  _aot_return:
#endif
      u->pc = pc;
      u->ac = ac;
      u->ix = ix;
      u->iy = iy;
      u->sp = sp;
      u->status = status;
      return (executed);
    } else {
#if defined(S6502_AOT_DISPATCH) && !defined(S6502_NATIVE_HLE_ONLY) && \
    !defined(S6502_FIRMWARE_AOT_EXTERNAL)
      if (aot_next_token) {
        uint16_t aot_token_id = (uint16_t)(aot_next_token - 1u);

        aot_next_token = 0u;
        if (aot_token_id < S6502_AOT_BLOCK_COUNT &&
            s6502_aot_match(aot_token_id)) {
          ++s6502_aot_token_link_hits;
          goto *s6502_aot_token_table[aot_token_id];
        }
      }
#endif
#ifdef S6502_AOT_DISPATCH
      S6502_AOT_DISPATCH();
#endif
#ifdef S6502_GAME_AOT_DISPATCH
      S6502_GAME_AOT_DISPATCH();
#endif
      NEXT;
    };
  _next:
#if defined(S6502_TEST_STOP_PREDICATE)
    if (S6502_TEST_STOP_PREDICATE(pc) && executed) {
#elif defined(S6502_TEST_STOP_PC)
    if (pc == (uint16_t)S6502_TEST_STOP_PC && executed) {
#endif
#if defined(S6502_TEST_STOP_PREDICATE) || defined(S6502_TEST_STOP_PC)
      u->pc = pc;
      u->ac = ac;
      u->ix = ix;
      u->iy = iy;
      u->sp = sp;
      u->status = status;
      return executed;
    }
#endif
#ifdef S6502_NATIVE_CHAIN_ACTIVE
    if (S6502_NATIVE_CHAIN_ACTIVE()) {
      u->pc = pc;
      u->ac = ac;
      u->ix = ix;
      u->iy = iy;
      u->sp = sp;
      u->status = status;
      return executed;
    }
#endif
#ifdef S6502_NATIVE_CHAIN_ONLY
    /* The wrapper fastcall enters this compact copy only at a native dispatch
     * boundary.  If no HLE owns the PC, return zero immediately so the outer
     * full core can execute the real instruction/AOT block.  Re-dispatching
     * here would retry a condition-rejected HLE forever. */
    u->pc = pc;
    u->ac = ac;
    u->ix = ix;
    u->iy = iy;
    u->sp = sp;
    u->status = status;
    return executed;
#else
#ifdef S6502_IRAM_EXEC_BURST
    {
      uint32_t iram_budget = executed < cycles ? cycles - executed : 0u;
      uint32_t iram_result = S6502_IRAM_EXEC_BURST(
          &pc, &ac, &ix, &iy, &sp, &status, iram_budget);
      uint32_t iram_executed = iram_result & 0x7fffffffu;

      if (iram_executed) {
        executed += iram_executed;
        if (iram_result & 0x80000000u)
          goto _exit;
        goto _next;
      }
    }
#endif
#ifdef S6502_NO_COMPUTED_GOTO
    switch (S6502_FETCH_OPCODE()) {
    case 0x00: goto _00;
    case 0x01: goto _01;
    case 0x02: goto _02;
    case 0x03: goto _03;
    case 0x04: goto _04;
    case 0x05: goto _05;
    case 0x06: goto _06;
    case 0x07: goto _07;
    case 0x08: goto _08;
    case 0x09: goto _09;
    case 0x0a: goto _0a;
    case 0x0b: goto _0b;
    case 0x0c: goto _0c;
    case 0x0d: goto _0d;
    case 0x0e: goto _0e;
    case 0x0f: goto _0f;
    case 0x10: goto _10;
    case 0x11: goto _11;
    case 0x12: goto _12;
    case 0x13: goto _13;
    case 0x14: goto _14;
    case 0x15: goto _15;
    case 0x16: goto _16;
    case 0x17: goto _17;
    case 0x18: goto _18;
    case 0x19: goto _19;
    case 0x1a: goto _1a;
    case 0x1b: goto _1b;
    case 0x1c: goto _1c;
    case 0x1d: goto _1d;
    case 0x1e: goto _1e;
    case 0x1f: goto _1f;
    case 0x20: goto _20;
    case 0x21: goto _21;
    case 0x22: goto _22;
    case 0x23: goto _23;
    case 0x24: goto _24;
    case 0x25: goto _25;
    case 0x26: goto _26;
    case 0x27: goto _27;
    case 0x28: goto _28;
    case 0x29: goto _29;
    case 0x2a: goto _2a;
    case 0x2b: goto _2b;
    case 0x2c: goto _2c;
    case 0x2d: goto _2d;
    case 0x2e: goto _2e;
    case 0x2f: goto _2f;
    case 0x30: goto _30;
    case 0x31: goto _31;
    case 0x32: goto _32;
    case 0x33: goto _33;
    case 0x34: goto _34;
    case 0x35: goto _35;
    case 0x36: goto _36;
    case 0x37: goto _37;
    case 0x38: goto _38;
    case 0x39: goto _39;
    case 0x3a: goto _3a;
    case 0x3b: goto _3b;
    case 0x3c: goto _3c;
    case 0x3d: goto _3d;
    case 0x3e: goto _3e;
    case 0x3f: goto _3f;
    case 0x40: goto _40;
    case 0x41: goto _41;
    case 0x42: goto _42;
    case 0x43: goto _43;
    case 0x44: goto _44;
    case 0x45: goto _45;
    case 0x46: goto _46;
    case 0x47: goto _47;
    case 0x48: goto _48;
    case 0x49: goto _49;
    case 0x4a: goto _4a;
    case 0x4b: goto _4b;
    case 0x4c: goto _4c;
    case 0x4d: goto _4d;
    case 0x4e: goto _4e;
    case 0x4f: goto _4f;
    case 0x50: goto _50;
    case 0x51: goto _51;
    case 0x52: goto _52;
    case 0x53: goto _53;
    case 0x54: goto _54;
    case 0x55: goto _55;
    case 0x56: goto _56;
    case 0x57: goto _57;
    case 0x58: goto _58;
    case 0x59: goto _59;
    case 0x5a: goto _5a;
    case 0x5b: goto _5b;
    case 0x5c: goto _5c;
    case 0x5d: goto _5d;
    case 0x5e: goto _5e;
    case 0x5f: goto _5f;
    case 0x60: goto _60;
    case 0x61: goto _61;
    case 0x62: goto _62;
    case 0x63: goto _63;
    case 0x64: goto _64;
    case 0x65: goto _65;
    case 0x66: goto _66;
    case 0x67: goto _67;
    case 0x68: goto _68;
    case 0x69: goto _69;
    case 0x6a: goto _6a;
    case 0x6b: goto _6b;
    case 0x6c: goto _6c;
    case 0x6d: goto _6d;
    case 0x6e: goto _6e;
    case 0x6f: goto _6f;
    case 0x70: goto _70;
    case 0x71: goto _71;
    case 0x72: goto _72;
    case 0x73: goto _73;
    case 0x74: goto _74;
    case 0x75: goto _75;
    case 0x76: goto _76;
    case 0x77: goto _77;
    case 0x78: goto _78;
    case 0x79: goto _79;
    case 0x7a: goto _7a;
    case 0x7b: goto _7b;
    case 0x7c: goto _7c;
    case 0x7d: goto _7d;
    case 0x7e: goto _7e;
    case 0x7f: goto _7f;
    case 0x80: goto _80;
    case 0x81: goto _81;
    case 0x82: goto _82;
    case 0x83: goto _83;
    case 0x84: goto _84;
    case 0x85: goto _85;
    case 0x86: goto _86;
    case 0x87: goto _87;
    case 0x88: goto _88;
    case 0x89: goto _89;
    case 0x8a: goto _8a;
    case 0x8b: goto _8b;
    case 0x8c: goto _8c;
    case 0x8d: goto _8d;
    case 0x8e: goto _8e;
    case 0x8f: goto _8f;
    case 0x90: goto _90;
    case 0x91: goto _91;
    case 0x92: goto _92;
    case 0x93: goto _93;
    case 0x94: goto _94;
    case 0x95: goto _95;
    case 0x96: goto _96;
    case 0x97: goto _97;
    case 0x98: goto _98;
    case 0x99: goto _99;
    case 0x9a: goto _9a;
    case 0x9b: goto _9b;
    case 0x9c: goto _9c;
    case 0x9d: goto _9d;
    case 0x9e: goto _9e;
    case 0x9f: goto _9f;
    case 0xa0: goto _a0;
    case 0xa1: goto _a1;
    case 0xa2: goto _a2;
    case 0xa3: goto _a3;
    case 0xa4: goto _a4;
    case 0xa5: goto _a5;
    case 0xa6: goto _a6;
    case 0xa7: goto _a7;
    case 0xa8: goto _a8;
    case 0xa9: goto _a9;
    case 0xaa: goto _aa;
    case 0xab: goto _ab;
    case 0xac: goto _ac;
    case 0xad: goto _ad;
    case 0xae: goto _ae;
    case 0xaf: goto _af;
    case 0xb0: goto _b0;
    case 0xb1: goto _b1;
    case 0xb2: goto _b2;
    case 0xb3: goto _b3;
    case 0xb4: goto _b4;
    case 0xb5: goto _b5;
    case 0xb6: goto _b6;
    case 0xb7: goto _b7;
    case 0xb8: goto _b8;
    case 0xb9: goto _b9;
    case 0xba: goto _ba;
    case 0xbb: goto _bb;
    case 0xbc: goto _bc;
    case 0xbd: goto _bd;
    case 0xbe: goto _be;
    case 0xbf: goto _bf;
    case 0xc0: goto _c0;
    case 0xc1: goto _c1;
    case 0xc2: goto _c2;
    case 0xc3: goto _c3;
    case 0xc4: goto _c4;
    case 0xc5: goto _c5;
    case 0xc6: goto _c6;
    case 0xc7: goto _c7;
    case 0xc8: goto _c8;
    case 0xc9: goto _c9;
    case 0xca: goto _ca;
    case 0xcb: goto _cb;
    case 0xcc: goto _cc;
    case 0xcd: goto _cd;
    case 0xce: goto _ce;
    case 0xcf: goto _cf;
    case 0xd0: goto _d0;
    case 0xd1: goto _d1;
    case 0xd2: goto _d2;
    case 0xd3: goto _d3;
    case 0xd4: goto _d4;
    case 0xd5: goto _d5;
    case 0xd6: goto _d6;
    case 0xd7: goto _d7;
    case 0xd8: goto _d8;
    case 0xd9: goto _d9;
    case 0xda: goto _da;
    case 0xdb: goto _db;
    case 0xdc: goto _dc;
    case 0xdd: goto _dd;
    case 0xde: goto _de;
    case 0xdf: goto _df;
    case 0xe0: goto _e0;
    case 0xe1: goto _e1;
    case 0xe2: goto _e2;
    case 0xe3: goto _e3;
    case 0xe4: goto _e4;
    case 0xe5: goto _e5;
    case 0xe6: goto _e6;
    case 0xe7: goto _e7;
    case 0xe8: goto _e8;
    case 0xe9: goto _e9;
    case 0xea: goto _ea;
    case 0xeb: goto _eb;
    case 0xec: goto _ec;
    case 0xed: goto _ed;
    case 0xee: goto _ee;
    case 0xef: goto _ef;
    case 0xf0: goto _f0;
    case 0xf1: goto _f1;
    case 0xf2: goto _f2;
    case 0xf3: goto _f3;
    case 0xf4: goto _f4;
    case 0xf5: goto _f5;
    case 0xf6: goto _f6;
    case 0xf7: goto _f7;
    case 0xf8: goto _f8;
    case 0xf9: goto _f9;
    case 0xfa: goto _fa;
    case 0xfb: goto _fb;
    case 0xfc: goto _fc;
    case 0xfd: goto _fd;
    case 0xfe: goto _fe;
    case 0xff: goto _ff;
    }
#else
    goto *_table[S6502_FETCH_OPCODE()];
#endif
  _00:
    BRK_HOOK;
    CYCLES(7);
    EXIT;
  _01:
    ea = READ16W((0xff & (READX8(pc) + ix)));
    pc = (pc + 1);
    ac = (ac | READ8(ea));
    SET_NZ(ac);
    CYCLES(6);
    NEXT;
  _02:
    ea = pc;
    pc = (pc + 1);
    READ8(ea);
    CYCLES(2);
    NEXT;
  _03:
    CYCLES(1);
    NEXT;
  _04:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt | ac));
    SET_Z((!(dt & ac)));
    CYCLES(5);
    NEXT;
  _05:
    ea = READX8(pc);
    pc = (pc + 1);
    ac = (ac | READ8(ea));
    SET_NZ(ac);
    CYCLES(3);
    NEXT;
  _06:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    SET_C((0x80 & dt));
    dt = (dt << 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(5);
    NEXT;
  _07:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt & ~(0x01 << 0)));
    CYCLES(5);
    NEXT;
  _08:
    PUSH((status | FLAG_B | FLAG_U));
    CYCLES(3);
    NEXT;
  _09:
    ea = pc;
    pc = (pc + 1);
    ac = (ac | READ8(ea));
    SET_NZ(ac);
    CYCLES(2);
    NEXT;
  _0a:
    SET_C((0x80 & ac));
    ac = (ac << 1);
    SET_NZ(ac);
    CYCLES(2);
    NEXT;
  _0b:
    CYCLES(1);
    NEXT;
  _0c:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = READ8(ea);
    WRITE8(ea, (dt | ac));
    SET_Z((!(dt & ac)));
    CYCLES(6);
    NEXT;
  _0d:
    ea = READX16(pc);
    pc = (pc + 2);
    ac = (ac | READ8(ea));
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _0e:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = READ8(ea);
    SET_C((0x80 & dt));
    dt = (dt << 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _0f:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (!(dt & (0x01 << 0))) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _10:
    ea = (pc + 1 + ((int8_t)(READX8(pc))));
    pc = (pc + 1);
    if (!NEGATIVE_p) {
      CYCLES(1);
      CYCLES((!!(0xff00 & (pc ^ ea))));
      pc = ea;
    };
    CYCLES(2);
    EXIT;
  _11:
    et = READ16W((READX8(pc)));
    pc = (pc + 1);
    ea = (et + iy);
    CYCLES((!!(0xff00 & (et ^ ea))));
    ac = (ac | READ8(ea));
    SET_NZ(ac);
    CYCLES(5);
    NEXT;
  _12:
    ea = READ16W((READX8(pc)));
    pc = (pc + 1);
    ac = (ac | READ8(ea));
    SET_NZ(ac);
    CYCLES(5);
    NEXT;
  _13:
    CYCLES(1);
    NEXT;
  _14:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt & ~ac));
    SET_Z((!(dt & ac)));
    CYCLES(5);
    NEXT;
  _15:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    ac = (ac | READ8(ea));
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _16:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    dt = READ8(ea);
    SET_C((0x80 & dt));
    dt = (dt << 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _17:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt & ~(0x01 << 1)));
    CYCLES(5);
    NEXT;
  _18:
    SET_C(0);
    CYCLES(2);
    NEXT;
  _19:
    et = READX16(pc);
    ea = (et + iy);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    ac = (ac | READ8(ea));
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _1a:
    ac += 1;
    SET_NZ(ac);
    CYCLES(2);
    NEXT;
  _1b:
    CYCLES(1);
    NEXT;
  _1c:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = READ8(ea);
    WRITE8(ea, (dt & ~ac));
    SET_Z((!(dt & ac)));
    CYCLES(6);
    NEXT;
  _1d:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    ac = (ac | READ8(ea));
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _1e:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    SET_C((0x80 & dt));
    dt = (dt << 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _1f:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (!(dt & (0x01 << 1))) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _20:
    ea = READX16(pc);
    pc = (pc + 2);
    pc = (pc - 1);
    PUSH((pc >> 8));
    PUSH((pc & 0xff));
    pc = ea;
    CYCLES(6);
    EXIT;
  _21:
    ea = READ16W((0xff & (READX8(pc) + ix)));
    pc = (pc + 1);
    ac = (ac & READ8(ea));
    SET_NZ(ac);
    CYCLES(6);
    NEXT;
  _22:
    ea = pc;
    pc = (pc + 1);
    READ8(ea);
    CYCLES(2);
    NEXT;
  _23:
    CYCLES(1);
    NEXT;
  _24:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    SET_V((dt & 0x40));
    SET_N((dt & 0x80));
    SET_Z((!(ac & dt)));
    CYCLES(3);
    NEXT;
  _25:
    ea = READX8(pc);
    pc = (pc + 1);
    ac = (ac & READ8(ea));
    SET_NZ(ac);
    CYCLES(3);
    NEXT;
  _26:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    et = (dt & 0x80);
    dt = (CARRY | (dt << 1));
    SET_C(et);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(5);
    NEXT;
  _27:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt & ~(0x01 << 2)));
    CYCLES(5);
    NEXT;
  _28:
    status = (POP() | FLAG_U | FLAG_B);
    CYCLES(4);
    NEXT;
  _29:
    ea = pc;
    pc = (pc + 1);
    ac = (ac & READ8(ea));
    SET_NZ(ac);
    CYCLES(2);
    NEXT;
  _2a:
    dt = (ac & 0x80);
    ac = (CARRY | (ac << 1));
    SET_C(dt);
    SET_NZ(ac);
    CYCLES(2);
    NEXT;
  _2b:
    CYCLES(1);
    NEXT;
  _2c:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = READ8(ea);
    SET_V((dt & 0x40));
    SET_N((dt & 0x80));
    SET_Z((!(ac & dt)));
    CYCLES(4);
    NEXT;
  _2d:
    ea = READX16(pc);
    pc = (pc + 2);
    ac = (ac & READ8(ea));
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _2e:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = READ8(ea);
    et = (dt & 0x80);
    dt = (CARRY | (dt << 1));
    SET_C(et);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _2f:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (!(dt & (0x01 << 2))) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _30:
    ea = (pc + 1 + ((int8_t)(READX8(pc))));
    pc = (pc + 1);
    if (NEGATIVE_p) {
      CYCLES(1);
      CYCLES((!!(0xff00 & (pc ^ ea))));
      pc = ea;
    };
    CYCLES(2);
    EXIT;
  _31:
    et = READ16W((READX8(pc)));
    pc = (pc + 1);
    ea = (et + iy);
    CYCLES((!!(0xff00 & (et ^ ea))));
    ac = (ac & READ8(ea));
    SET_NZ(ac);
    CYCLES(5);
    NEXT;
  _32:
    ea = READ16W((READX8(pc)));
    pc = (pc + 1);
    ac = (ac & READ8(ea));
    SET_NZ(ac);
    CYCLES(5);
    NEXT;
  _33:
    CYCLES(1);
    NEXT;
  _34:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    dt = READ8(ea);
    SET_V((dt & 0x40));
    SET_N((dt & 0x80));
    SET_Z((!(ac & dt)));
    CYCLES(4);
    NEXT;
  _35:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    ac = (ac & READ8(ea));
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _36:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    dt = READ8(ea);
    et = (dt & 0x80);
    dt = (CARRY | (dt << 1));
    SET_C(et);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _37:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt & ~(0x01 << 3)));
    CYCLES(5);
    NEXT;
  _38:
    SET_C(1);
    CYCLES(2);
    NEXT;
  _39:
    et = READX16(pc);
    ea = (et + iy);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    ac = (ac & READ8(ea));
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _3a:
    ac -= 1;
    SET_NZ(ac);
    CYCLES(2);
    NEXT;
  _3b:
    CYCLES(1);
    NEXT;
  _3c:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    dt = READ8(ea);
    SET_V((dt & 0x40));
    SET_N((dt & 0x80));
    SET_Z((!(ac & dt)));
    CYCLES(4);
    NEXT;
  _3d:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    ac = (ac & READ8(ea));
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _3e:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    et = (dt & 0x80);
    dt = (CARRY | (dt << 1));
    SET_C(et);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _3f:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (!(dt & (0x01 << 3))) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _40:
    status = (POP() | FLAG_U | FLAG_B);
    pc = POP();
    pc = (pc | (POP() << 8));
    CYCLES(6);
    EXIT;
  _41:
    ea = READ16W((0xff & (READX8(pc) + ix)));
    pc = (pc + 1);
    dt = READ8(ea);
    ac = (ac ^ dt);
    SET_NZ(ac);
    CYCLES(6);
    NEXT;
  _42:
    ea = pc;
    pc = (pc + 1);
    READ8(ea);
    CYCLES(2);
    NEXT;
  _43:
    CYCLES(1);
    NEXT;
  _44:
    ea = READX8(pc);
    pc = (pc + 1);
    READ8(ea);
    CYCLES(3);
    NEXT;
  _45:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    ac = (ac ^ dt);
    SET_NZ(ac);
    CYCLES(3);
    NEXT;
  _46:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    SET_C((0x01 & dt));
    dt = (dt >> 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(5);
    NEXT;
  _47:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt & ~(0x01 << 4)));
    CYCLES(5);
    NEXT;
  _48:
    PUSH(ac);
    CYCLES(3);
    NEXT;
  _49:
    ea = pc;
    pc = (pc + 1);
    dt = READ8(ea);
    ac = (ac ^ dt);
    SET_NZ(ac);
    CYCLES(2);
    NEXT;
  _4a:
    SET_C((0x01 & ac));
    ac = (ac >> 1);
    SET_NZ(ac);
    CYCLES(2);
    NEXT;
  _4b:
    CYCLES(1);
    NEXT;
  _4c:
    ea = READX16(pc);
    pc = (pc + 2);
    pc = ea;
    CYCLES(3);
    EXIT;
  _4d:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = READ8(ea);
    ac = (ac ^ dt);
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _4e:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = READ8(ea);
    SET_C((0x01 & dt));
    dt = (dt >> 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _4f:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (!(dt & (0x01 << 4))) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _50:
    ea = (pc + 1 + ((int8_t)(READX8(pc))));
    pc = (pc + 1);
    if (!OVERFLOW_p) {
      CYCLES(1);
      CYCLES((!!(0xff00 & (pc ^ ea))));
      pc = ea;
    };
    CYCLES(2);
    EXIT;
  _51:
    et = READ16W((READX8(pc)));
    pc = (pc + 1);
    ea = (et + iy);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    ac = (ac ^ dt);
    SET_NZ(ac);
    CYCLES(5);
    NEXT;
  _52:
    ea = READ16W((READX8(pc)));
    pc = (pc + 1);
    dt = READ8(ea);
    ac = (ac ^ dt);
    SET_NZ(ac);
    CYCLES(5);
    NEXT;
  _53:
    CYCLES(1);
    NEXT;
  _54:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    READ8(ea);
    CYCLES(4);
    NEXT;
  _55:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    dt = READ8(ea);
    ac = (ac ^ dt);
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _56:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    dt = READ8(ea);
    SET_C((0x01 & dt));
    dt = (dt >> 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _57:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt & ~(0x01 << 5)));
    CYCLES(5);
    NEXT;
  _58:
    SET_I(0);
    CYCLES(2);
    NEXT;
  _59:
    et = READX16(pc);
    ea = (et + iy);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    ac = (ac ^ dt);
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _5a:
    PUSH(iy);
    CYCLES(3);
    NEXT;
  _5b:
    CYCLES(1);
    NEXT;
  _5c:
    ea = READX16(pc);
    pc = (pc + 2);
    READ8(ea);
    CYCLES(8);
    NEXT;
  _5d:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    ac = (ac ^ dt);
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _5e:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    SET_C((0x01 & dt));
    dt = (dt >> 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _5f:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (!(dt & (0x01 << 5))) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _60:
    pc = POP();
    pc = (pc | (POP() << 8));
    pc = (pc + 1);
    CYCLES(6);
    EXIT;
  _61:
    ea = READ16W((0xff & (READX8(pc) + ix)));
    pc = (pc + 1);
    dt = READ8(ea);
    CYCLES(6);
    goto _adc;
  _62:
    ea = pc;
    pc = (pc + 1);
    READ8(ea);
    CYCLES(2);
    NEXT;
  _63:
    CYCLES(1);
    NEXT;
  _64:
    ea = READX8(pc);
    pc = (pc + 1);
    WRITE8(ea, 0);
    CYCLES(3);
    NEXT;
  _65:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    CYCLES(3);
    goto _adc;
  _66:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    et = (dt & 0x01);
    dt = ((0x80 * CARRY) | (dt >> 1));
    SET_C(et);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(5);
    NEXT;
  _67:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt & ~(0x01 << 6)));
    CYCLES(5);
    NEXT;
  _68:
    SET_NZ((ac = POP()));
    CYCLES(4);
    NEXT;
  _69:
    ea = pc;
    pc = (pc + 1);
    dt = READ8(ea);
    CYCLES(2);
    goto _adc;
  _6a:
    dt = (ac & 0x01);
    ac = ((0x80 * CARRY) | (ac >> 1));
    SET_C(dt);
    SET_NZ(ac);
    CYCLES(2);
    NEXT;
  _6b:
    CYCLES(1);
    NEXT;
  _6c:
    ea = READ16((READX16(pc)));
    pc = (pc + 1);
    pc = ea;
    CYCLES(6);
    EXIT;
  _6d:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = READ8(ea);
    CYCLES(4);
    goto _adc;
  _6e:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = READ8(ea);
    et = (dt & 0x01);
    dt = ((0x80 * CARRY) | (dt >> 1));
    SET_C(et);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _6f:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (!(dt & (0x01 << 6))) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _70:
    ea = (pc + 1 + ((int8_t)(READX8(pc))));
    pc = (pc + 1);
    if (OVERFLOW_p) {
      CYCLES(1);
      CYCLES((!!(0xff00 & (pc ^ ea))));
      pc = ea;
    };
    CYCLES(2);
    EXIT;
  _71:
    et = READ16W((READX8(pc)));
    pc = (pc + 1);
    ea = (et + iy);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    CYCLES(5);
    goto _adc;
  _72:
    ea = READ16W((READX8(pc)));
    pc = (pc + 1);
    if (DECIMAL_p) {
      CYCLES(1);
      dt = READ8(ea);
      {
        uint8_t vu = (dt & 0x0f);
        uint8_t vt = ((dt & 0xf0) >> 4);
        uint8_t au = (ac & 0x0f);
        uint8_t at = ((ac & 0xf0) >> 4);
        uint8_t units = (vu + au + CARRY);
        uint8_t tens = (vt + at);
        uint8_t tc = 0;
        if (units > 0x09) {
          tc = 1;
          tens = (tens + 0x01);
          units = (units + 0x06);
        };
        if (tens > 0x09) {
          tens += 0x06;
        };
        if (at & 0x08) {
          at = (at | 0xf0);
        };
        if (vt & 0x08) {
          vt = (vt | 0xf0);
        };
        {
          int8_t res = ((int8_t)((at + vt + tc)));
          SET_V(((res < -8) || (res > 7)));
          SET_NZ((ac = ((tens << 4) | (units & 0x0f))));
        };
        SET_C((tens & 0xf0));
      };
    } else {
      dt = READ8(ea);
      et = (ac + dt + CARRY);
      SET_C((et > 0xff));
      SET_V(((ac ^ et) & (dt ^ et) & 0x80));
      SET_NZ((ac = ((uint8_t)(et))));
    };
    CYCLES(5);
    NEXT;
  _73:
    CYCLES(1);
    NEXT;
  _74:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    WRITE8(ea, 0);
    CYCLES(4);
    NEXT;
  _75:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    dt = READ8(ea);
    CYCLES(4);
    goto _adc;
  _76:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    dt = READ8(ea);
    et = (dt & 0x01);
    dt = ((0x80 * CARRY) | (dt >> 1));
    SET_C(et);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _77:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt & ~(0x01 << 7)));
    CYCLES(5);
    NEXT;
  _78:
    SET_I(1);
    CYCLES(2);
    NEXT;
  _79:
    et = READX16(pc);
    ea = (et + iy);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    CYCLES(4);
    goto _adc;
  _7a:
    iy = POP();
    SET_NZ(iy);
    CYCLES(4);
    NEXT;
  _7b:
    CYCLES(1);
    NEXT;
  _7c:
    ea = READ16((READX16(pc) + ix));
    pc = (pc + 1);
    pc = ea;
    CYCLES(6);
    EXIT;
  _7d:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    CYCLES(4);
    goto _adc;
  /* Share the large decimal/binary arithmetic tail across all ADC modes. */
  _adc:
    if (DECIMAL_p) {
      CYCLES(1);
      {
        uint8_t vu = (dt & 0x0f);
        uint8_t vt = ((dt & 0xf0) >> 4);
        uint8_t au = (ac & 0x0f);
        uint8_t at = ((ac & 0xf0) >> 4);
        uint8_t units = (vu + au + CARRY);
        uint8_t tens = (vt + at);
        uint8_t tc = 0;
        if (units > 0x09) {
          tc = 1;
          tens = (tens + 0x01);
          units = (units + 0x06);
        };
        if (tens > 0x09) {
          tens += 0x06;
        };
        if (at & 0x08) {
          at = (at | 0xf0);
        };
        if (vt & 0x08) {
          vt = (vt | 0xf0);
        };
        {
          int8_t res = ((int8_t)((at + vt + tc)));
          SET_V(((res < -8) || (res > 7)));
          SET_NZ((ac = ((tens << 4) | (units & 0x0f))));
        };
        SET_C((tens & 0xf0));
      };
    } else {
      et = (ac + dt + CARRY);
      SET_C((et > 0xff));
      SET_V(((ac ^ et) & (dt ^ et) & 0x80));
      SET_NZ((ac = ((uint8_t)(et))));
    };
    NEXT;
  _7e:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    et = (dt & 0x01);
    dt = ((0x80 * CARRY) | (dt >> 1));
    SET_C(et);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _7f:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (!(dt & (0x01 << 7))) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _80:
    ea = (pc + 1 + ((int8_t)(READX8(pc))));
    pc = (pc + 1);
    CYCLES(1);
    CYCLES((!!(0xff00 & (pc ^ ea))));
    pc = ea;
    CYCLES(2);
    EXIT;
  _81:
    ea = READ16W((0xff & (READX8(pc) + ix)));
    pc = (pc + 1);
    WRITE8(ea, ac);
    CYCLES(6);
    NEXT;
  _82:
    ea = pc;
    pc = (pc + 1);
    READ8(ea);
    CYCLES(2);
    NEXT;
  _83:
    CYCLES(1);
    NEXT;
  _84:
    ea = READX8(pc);
    pc = (pc + 1);
    WRITE8(ea, iy);
    CYCLES(3);
    NEXT;
  _85:
    ea = READX8(pc);
    pc = (pc + 1);
    WRITE8(ea, ac);
    CYCLES(3);
    NEXT;
  _86:
    ea = READX8(pc);
    pc = (pc + 1);
    WRITE8(ea, ix);
    CYCLES(3);
    NEXT;
  _87:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt | (0x01 << 0)));
    CYCLES(5);
    NEXT;
  _88:
    iy -= 1;
    SET_NZ(iy);
    CYCLES(2);
    NEXT;
  _89:
    ea = pc;
    pc = (pc + 1);
    dt = READ8(ea);
    SET_Z((!(ac & dt)));
    CYCLES(2);
    NEXT;
  _8a:
    SET_NZ(ac = ix);
    CYCLES(2);
    NEXT;
  _8b:
    CYCLES(1);
    NEXT;
  _8c:
    ea = READX16(pc);
    pc = (pc + 2);
    WRITE8(ea, iy);
    CYCLES(4);
    NEXT;
  _8d:
    ea = READX16(pc);
    pc = (pc + 2);
    WRITE8(ea, ac);
    CYCLES(4);
    NEXT;
  _8e:
    ea = READX16(pc);
    pc = (pc + 2);
    WRITE8(ea, ix);
    CYCLES(4);
    NEXT;
  _8f:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (dt & (0x01 << 0)) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _90:
    ea = (pc + 1 + ((int8_t)(READX8(pc))));
    pc = (pc + 1);
    if (!CARRY_p) {
      CYCLES(1);
      CYCLES((!!(0xff00 & (pc ^ ea))));
      pc = ea;
    };
    CYCLES(2);
    EXIT;
  _91:
    et = READ16W((READX8(pc)));
    pc = (pc + 1);
    ea = (et + iy);
    WRITE8(ea, ac);
    CYCLES(6);
    NEXT;
  _92:
    ea = READ16W((READX8(pc)));
    pc = (pc + 1);
    WRITE8(ea, ac);
    CYCLES(5);
    NEXT;
  _93:
    CYCLES(1);
    NEXT;
  _94:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    WRITE8(ea, iy);
    CYCLES(4);
    NEXT;
  _95:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    WRITE8(ea, ac);
    CYCLES(4);
    NEXT;
  _96:
    ea = ((iy + READX8(pc)) & 0xff);
    pc = (pc + 1);
    WRITE8(ea, ix);
    CYCLES(4);
    NEXT;
  _97:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt | (0x01 << 1)));
    CYCLES(5);
    NEXT;
  _98:
    SET_NZ(ac = iy);
    CYCLES(2);
    NEXT;
  _99:
    et = READX16(pc);
    ea = (et + iy);
    pc = (pc + 2);
    WRITE8(ea, ac);
    CYCLES(5);
    NEXT;
  _9a:
    sp = ix;
    CYCLES(2);
    NEXT;
  _9b:
    CYCLES(1);
    NEXT;
  _9c:
    ea = READX16(pc);
    pc = (pc + 2);
    WRITE8(ea, 0);
    CYCLES(4);
    NEXT;
  _9d:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    WRITE8(ea, ac);
    CYCLES(5);
    NEXT;
  _9e:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    WRITE8(ea, 0);
    CYCLES(5);
    NEXT;
  _9f:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (dt & (0x01 << 1)) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _a0:
    ea = pc;
    pc = (pc + 1);
    iy = READ8(ea);
    SET_NZ(iy);
    CYCLES(2);
    NEXT;
  _a1:
    ea = READ16W((0xff & (READX8(pc) + ix)));
    pc = (pc + 1);
    ac = READ8(ea);
    SET_NZ(ac);
    CYCLES(6);
    NEXT;
  _a2:
    ea = pc;
    pc = (pc + 1);
    ix = READ8(ea);
    SET_NZ(ix);
    CYCLES(2);
    NEXT;
  _a3:
    CYCLES(1);
    NEXT;
  _a4:
    ea = READX8(pc);
    pc = (pc + 1);
    iy = READ8(ea);
    SET_NZ(iy);
    CYCLES(3);
    NEXT;
  _a5:
    ea = READX8(pc);
    pc = (pc + 1);
    ac = READ8(ea);
    SET_NZ(ac);
    CYCLES(3);
    NEXT;
  _a6:
    ea = READX8(pc);
    pc = (pc + 1);
    ix = READ8(ea);
    SET_NZ(ix);
    CYCLES(3);
    NEXT;
  _a7:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt | (0x01 << 2)));
    CYCLES(5);
    NEXT;
  _a8:
    SET_NZ(iy = ac);
    CYCLES(2);
    NEXT;
  _a9:
    ea = pc;
    pc = (pc + 1);
    ac = READ8(ea);
    SET_NZ(ac);
    CYCLES(2);
    NEXT;
  _aa:
    SET_NZ(ix = ac);
    CYCLES(2);
    NEXT;
  _ab:
    CYCLES(1);
    NEXT;
  _ac:
    ea = READX16(pc);
    pc = (pc + 2);
    iy = READ8(ea);
    SET_NZ(iy);
    CYCLES(4);
    NEXT;
  _ad:
    ea = READX16(pc);
    pc = (pc + 2);
    ac = READ8(ea);
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _ae:
    ea = READX16(pc);
    pc = (pc + 2);
    ix = READ8(ea);
    SET_NZ(ix);
    CYCLES(4);
    NEXT;
  _af:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (dt & (0x01 << 2)) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _b0:
    ea = (pc + 1 + ((int8_t)(READX8(pc))));
    pc = (pc + 1);
    if (CARRY_p) {
      CYCLES(1);
      CYCLES((!!(0xff00 & (pc ^ ea))));
      pc = ea;
    };
    CYCLES(2);
    EXIT;
  _b1:
    et = READ16W((READX8(pc)));
    pc = (pc + 1);
    ea = (et + iy);
    CYCLES((!!(0xff00 & (et ^ ea))));
    ac = READ8(ea);
    SET_NZ(ac);
    CYCLES(5);
    NEXT;
  _b2:
    ea = READ16W((READX8(pc)));
    pc = (pc + 1);
    ac = READ8(ea);
    SET_NZ(ac);
    CYCLES(5);
    NEXT;
  _b3:
    CYCLES(1);
    NEXT;
  _b4:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    iy = READ8(ea);
    SET_NZ(iy);
    CYCLES(4);
    NEXT;
  _b5:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    ac = READ8(ea);
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _b6:
    ea = ((iy + READX8(pc)) & 0xff);
    pc = (pc + 1);
    ix = READ8(ea);
    SET_NZ(ix);
    CYCLES(4);
    NEXT;
  _b7:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt | (0x01 << 3)));
    CYCLES(5);
    NEXT;
  _b8:
    SET_V(0);
    CYCLES(2);
    NEXT;
  _b9:
    et = READX16(pc);
    ea = (et + iy);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    ac = READ8(ea);
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _ba:
    SET_NZ(ix = sp);
    CYCLES(2);
    NEXT;
  _bb:
    CYCLES(1);
    NEXT;
  _bc:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    iy = READ8(ea);
    SET_NZ(iy);
    CYCLES(4);
    NEXT;
  _bd:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    ac = READ8(ea);
    SET_NZ(ac);
    CYCLES(4);
    NEXT;
  _be:
    et = READX16(pc);
    ea = (et + iy);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    ix = READ8(ea);
    SET_NZ(ix);
    CYCLES(4);
    NEXT;
  _bf:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (dt & (0x01 << 3)) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _c0:
    ea = pc;
    pc = (pc + 1);
    dt = ~READ8(ea);
    et = (iy + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(2);
    NEXT;
  _c1:
    ea = READ16W((0xff & (READX8(pc) + ix)));
    pc = (pc + 1);
    dt = ~READ8(ea);
    et = (ac + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(6);
    NEXT;
  _c2:
    ea = pc;
    pc = (pc + 1);
    READ8(ea);
    CYCLES(2);
    NEXT;
  _c3:
    CYCLES(1);
    NEXT;
  _c4:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = ~READ8(ea);
    et = (iy + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(3);
    NEXT;
  _c5:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = ~READ8(ea);
    et = (ac + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(3);
    NEXT;
  _c6:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = (READ8(ea) - 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(5);
    NEXT;
  _c7:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt | (0x01 << 4)));
    CYCLES(5);
    NEXT;
  _c8:
    iy += 1;
    SET_NZ(iy);
    CYCLES(2);
    NEXT;
  _c9:
    ea = pc;
    pc = (pc + 1);
    dt = ~READ8(ea);
    et = (ac + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(2);
    NEXT;
  _ca:
    ix -= 1;
    SET_NZ(ix);
    CYCLES(2);
    NEXT;
  _cb:
    CYCLES(3);
    NEXT;
  _cc:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = ~READ8(ea);
    et = (iy + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(4);
    NEXT;
  _cd:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = ~READ8(ea);
    et = (ac + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(4);
    NEXT;
  _ce:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = (READ8(ea) - 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _cf:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (dt & (0x01 << 4)) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _d0:
    ea = (pc + 1 + ((int8_t)(READX8(pc))));
    pc = (pc + 1);
    if (!ZERO_p) {
      CYCLES(1);
      CYCLES((!!(0xff00 & (pc ^ ea))));
      pc = ea;
    };
    CYCLES(2);
    EXIT;
  _d1:
    et = READ16W((READX8(pc)));
    pc = (pc + 1);
    ea = (et + iy);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = ~READ8(ea);
    et = (ac + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(5);
    NEXT;
  _d2:
    ea = READ16W((READX8(pc)));
    pc = (pc + 1);
    dt = ~READ8(ea);
    et = (ac + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(5);
    NEXT;
  _d3:
    CYCLES(1);
    NEXT;
  _d4:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    READ8(ea);
    CYCLES(4);
    NEXT;
  _d5:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    dt = ~READ8(ea);
    et = (ac + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(4);
    NEXT;
  _d6:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    dt = (READ8(ea) - 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _d7:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt | (0x01 << 5)));
    CYCLES(5);
    NEXT;
  _d8:
    SET_D(0);
    CYCLES(2);
    NEXT;
  _d9:
    et = READX16(pc);
    ea = (et + iy);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = ~READ8(ea);
    et = (ac + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(4);
    NEXT;
  _da:
    PUSH(ix);
    CYCLES(3);
    NEXT;
  _db:
    CYCLES(3);
    NEXT;
  _dc:
    ea = READX16(pc);
    pc = (pc + 2);
    READ8(ea);
    CYCLES(4);
    NEXT;
  _dd:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = ~READ8(ea);
    et = (ac + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(4);
    NEXT;
  _de:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    dt = (READ8(ea) - 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(7);
    NEXT;
  _df:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (dt & (0x01 << 5)) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _e0:
    ea = pc;
    pc = (pc + 1);
    dt = ~READ8(ea);
    et = (ix + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(2);
    NEXT;
  _e1:
    ea = READ16W((0xff & (READX8(pc) + ix)));
    pc = (pc + 1);
    dt = READ8(ea);
    CYCLES(6);
    goto _sbc;
  _e2:
    ea = pc;
    pc = (pc + 1);
    READ8(ea);
    CYCLES(2);
    NEXT;
  _e3:
    CYCLES(1);
    NEXT;
  _e4:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = ~READ8(ea);
    et = (ix + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(3);
    NEXT;
  _e5:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    CYCLES(3);
    goto _sbc;
  _e6:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = (READ8(ea) + 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(5);
    NEXT;
  _e7:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt | (0x01 << 6)));
    CYCLES(5);
    NEXT;
  _e8:
    ix += 1;
    SET_NZ(ix);
    CYCLES(2);
    NEXT;
  _e9:
    ea = pc;
    pc = (pc + 1);
    dt = READ8(ea);
    CYCLES(2);
    goto _sbc;
  _ea:
    CYCLES(2);
    NEXT;
  _eb:
    CYCLES(1);
    NEXT;
  _ec:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = ~READ8(ea);
    et = (ix + dt + 1);
    SET_C((et > 0xff));
    SET_NZ(((uint8_t)(et)));
    CYCLES(4);
    NEXT;
  _ed:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = READ8(ea);
    CYCLES(4);
    goto _sbc;
  _ee:
    ea = READX16(pc);
    pc = (pc + 2);
    dt = (READ8(ea) + 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _ef:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (dt & (0x01 << 6)) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
  _f0:
    ea = (pc + 1 + ((int8_t)(READX8(pc))));
    pc = (pc + 1);
    if (ZERO_p) {
      CYCLES(1);
      CYCLES((!!(0xff00 & (pc ^ ea))));
      pc = ea;
    };
    CYCLES(2);
    EXIT;
  _f1:
    et = READ16W((READX8(pc)));
    pc = (pc + 1);
    ea = (et + iy);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    CYCLES(5);
    goto _sbc;
  _f2:
    ea = READ16W((READX8(pc)));
    pc = (pc + 1);
    if (DECIMAL_p) {
      CYCLES(1);
      dt = READ8(ea);
      et = (ac + ~dt + CARRY);
      ea = (ac - dt - !CARRY);
      if (ea & 0x8000) {
        ea -= 0x60;
      };
      if (((ac & 0x0f) - (dt & 0x0f) - !CARRY) & 0x8000) {
        ea -= 0x06;
      };
      SET_V(((ac ^ et) & (~dt ^ et) & 0x80));
      SET_NZ(((uint8_t)(ea)));
      SET_C(((ea <= ((uint16_t)(ac))) || ((ea & 0xff0) == 0xff0)));
      ac = (ea & 0xff);
    } else {
      dt = ~READ8(ea);
      et = (ac + dt + CARRY);
      SET_C((et > 0xff));
      SET_V(((ac ^ et) & (dt ^ et) & 0x80));
      ac = ((uint8_t)(et));
      SET_NZ(ac);
    };
    CYCLES(5);
    NEXT;
  _f3:
    CYCLES(1);
    NEXT;
  _f4:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    READ8(ea);
    CYCLES(4);
    NEXT;
  _f5:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    dt = READ8(ea);
    CYCLES(4);
    goto _sbc;
  _f6:
    ea = ((ix + READX8(pc)) & 0xff);
    pc = (pc + 1);
    dt = (READ8(ea) + 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(6);
    NEXT;
  _f7:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    WRITE8(ea, (dt | (0x01 << 7)));
    CYCLES(5);
    NEXT;
  _f8:
    SET_D(1);
    CYCLES(2);
    NEXT;
  _f9:
    et = READX16(pc);
    ea = (et + iy);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    CYCLES(4);
    goto _sbc;
  _fa:
    SET_NZ((ix = POP()));
    CYCLES(4);
    NEXT;
  _fb:
    CYCLES(1);
    NEXT;
  _fc:
    ea = READX16(pc);
    pc = (pc + 2);
    READ8(ea);
    CYCLES(4);
    NEXT;
  _fd:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    CYCLES((!!(0xff00 & (et ^ ea))));
    dt = READ8(ea);
    CYCLES(4);
    goto _sbc;
  /* Share the arithmetic tail to keep the direct-threaded loop compact. */
  _sbc:
    if (DECIMAL_p) {
      CYCLES(1);
      et = (ac + ~dt + CARRY);
      ea = (ac - dt - !CARRY);
      if (ea & 0x8000) {
        ea -= 0x60;
      };
      if (((ac & 0x0f) - (dt & 0x0f) - !CARRY) & 0x8000) {
        ea -= 0x06;
      };
      SET_V(((ac ^ et) & (~dt ^ et) & 0x80));
      SET_NZ(((uint8_t)(ea)));
      SET_C(((ea <= ((uint16_t)(ac))) || ((ea & 0xff0) == 0xff0)));
      ac = (ea & 0xff);
    } else {
      dt = ~dt;
      et = (ac + dt + CARRY);
      SET_C((et > 0xff));
      SET_V(((ac ^ et) & (dt ^ et) & 0x80));
      ac = ((uint8_t)(et));
      SET_NZ(ac);
    };
    NEXT;
  _fe:
    et = READX16(pc);
    ea = (et + ix);
    pc = (pc + 2);
    dt = (READ8(ea) + 1);
    SET_NZ(dt);
    WRITE8(ea, dt);
    CYCLES(7);
    NEXT;
  _ff:
    ea = READX8(pc);
    pc = (pc + 1);
    dt = READ8(ea);
    if (dt & (0x01 << 7)) {
      ea = (pc + 1 + ((int8_t)(READX8(pc))));
      pc = (pc + 1);
      pc = ea;
    } else {
      pc += 1;
    };
    CYCLES(5);
    NEXT;
#endif /* !S6502_NATIVE_CHAIN_ONLY */
#if defined(S6502_AOT_DISPATCH) && !defined(S6502_NATIVE_HLE_ONLY) && \
    !defined(S6502_FIRMWARE_AOT_EXTERNAL)
#define S6502_AOT_EMIT_BLOCKS
#include "s6502_aot_ebin_generated.h"
#undef S6502_AOT_EMIT_BLOCKS
#endif
#ifdef S6502_HLE_EMIT_BLOCKS
#include "s6502_hle_ebin.h"
#endif
#ifdef S6502_GAME_AOT_EMIT_BLOCKS
#include "s6502_game_load_aot.h"
#endif
#ifdef S6502_GAME_HLE_EMIT_BLOCKS
#include "s6502_game_hle.h"
#endif
  };
#undef CYCLES
#undef EXIT
#undef NEXT
#undef FLAG_N
#undef FLAG_V
#undef FLAG_U
#undef FLAG_B
#undef FLAG_D
#undef FLAG_I
#undef FLAG_Z
#undef FLAG_C
#undef NEGATIVE_p
#undef OVERFLOW_p
#undef DECIMAL_p
#undef ZERO_p
#undef CARRY_p
#undef CARRY
#undef SET_BIT
#undef SET_N
#undef SET_V
#undef SET_D
#undef SET_I
#undef SET_Z
#undef SET_C
#undef SET_NZ
#undef PUSH
#undef POP
#undef S6502_FETCH_OPCODE
}
#ifdef S6502_EXEC_FUNCTION_LOCAL
#undef S6502_EXEC_FUNCTION_LOCAL
#undef S6502_EXEC_FUNCTION
#endif
