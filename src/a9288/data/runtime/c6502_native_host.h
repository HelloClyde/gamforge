#ifndef C6502_NATIVE_HOST_H
#define C6502_NATIVE_HOST_H

/* KF2 load address, S1C33 GNU33 ABI and framebuffer base are shared.
 * The screen and late game-GUI table layout are not. */
#ifdef C6502_TARGET_9288T
#define C6502_HOST_WIDTH 240u
#define C6502_HOST_HEIGHT 160u
#define C6502_HOST_STRIDE 60u
#define C6502_HOST_VIEW_Y 8u
/* Firmware SysPrintString is at GUI+0x5bc; this SDK declares +0x5a8. */
#define C6502_HOST_GUI_GAME_OFFSET 0x14u
#else
#define C6502_HOST_WIDTH 320u
#define C6502_HOST_HEIGHT 240u
#define C6502_HOST_STRIDE 80u
#define C6502_HOST_VIEW_Y 24u
#define C6502_HOST_GUI_GAME_OFFSET 0x14u
#endif
#define C6502_HOST_FRAME_BYTES (C6502_HOST_STRIDE * C6502_HOST_HEIGHT)

#endif
