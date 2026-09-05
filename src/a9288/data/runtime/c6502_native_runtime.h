#ifndef C6502_NATIVE_RUNTIME_H
#define C6502_NATIVE_RUNTIME_H

#include "Dsys.h"

typedef unsigned char c6502_u8;
typedef unsigned short c6502_u16;
typedef unsigned long c6502_u32;

typedef struct C6502_NativeState {
    c6502_u8 *ram;
    c6502_u8 *game;
    c6502_u32 game_size;
    c6502_u16 banks[16];
    c6502_u8 bank_select;
    T_GUI_HWND window;
    T_GUI_HDC hdc;
    c6502_u32 heap_next;
    c6502_u32 random_state;
    c6502_u16 keyboard_state;
    c6502_u8 keyboard_type;
    c6502_u8 input_filter;
    c6502_u8 key_sound;
    c6502_u8 running;
} C6502_NativeState;

extern volatile c6502_u32 c6502_bridge_regs[15];
extern volatile c6502_u32 c6502_bridge_target;
extern c6502_u32 c6502_entry_regs[15];
extern C6502_NativeState c6502_native_state;

void c6502_native_bridge(c6502_u32 *registers, c6502_u32 id);
void c6502_native_enter(c6502_u32 *registers);
int c6502_native_prepare(void);
void c6502_native_release(void);
void c6502_native_present(void);
void c6502_native_invalidate_screen(void);
void c6502_native_perf_begin(void);
void c6502_native_perf_end(void);

#endif
