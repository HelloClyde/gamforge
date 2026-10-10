#ifndef C6502_NATIVE_HOST_H
#define C6502_NATIVE_HOST_H

/* KF2 load address, S1C33 GNU33 ABI and framebuffer base are shared.
 * The screen and late game-GUI table layout are not. */
#if defined(C6502_TARGET_9288T) || defined(C6502_TARGET_9288S)
#define C6502_HOST_PACKED_1X 1
#endif
#ifdef C6502_TARGET_9288S
#define C6502_HOST_WIDTH 160u
#define C6502_HOST_HEIGHT 240u
#define C6502_HOST_STRIDE 40u
#define C6502_HOST_VIEW_X 0u
#define C6502_HOST_VIEW_Y 12u
#define C6502_HOST_SCALE_NUMERATOR 1u
#define C6502_HOST_SCALE_DENOMINATOR 1u
/* S SDK game GUI entries already match its relocation table. */
#define C6502_HOST_GUI_GAME_OFFSET 0u
#elif defined(C6502_TARGET_9288T)
#define C6502_HOST_WIDTH 240u
#define C6502_HOST_HEIGHT 160u
#define C6502_HOST_STRIDE 60u
#ifdef C6502_T_SCALE_1_5
#define C6502_HOST_VIEW_X 0u
#define C6502_HOST_VIEW_Y 8u
#define C6502_HOST_SCALE_NUMERATOR 3u
#define C6502_HOST_SCALE_DENOMINATOR 2u
#else
#define C6502_HOST_VIEW_X 40u
#define C6502_HOST_VIEW_Y 32u
#define C6502_HOST_SCALE_NUMERATOR 1u
#define C6502_HOST_SCALE_DENOMINATOR 1u
#endif
/* Firmware SysPrintString is at GUI+0x5bc; this SDK declares +0x5a8. */
#define C6502_HOST_GUI_GAME_OFFSET 0x14u
#else
#define C6502_HOST_WIDTH 320u
#define C6502_HOST_HEIGHT 240u
#define C6502_HOST_STRIDE 80u
#define C6502_HOST_VIEW_X 1u
#define C6502_HOST_VIEW_Y 24u
#define C6502_HOST_SCALE_NUMERATOR 2u
#define C6502_HOST_SCALE_DENOMINATOR 1u
#define C6502_HOST_GUI_GAME_OFFSET 0x14u
#endif
#define C6502_HOST_FRAME_BYTES (C6502_HOST_STRIDE * C6502_HOST_HEIGHT)

#endif
