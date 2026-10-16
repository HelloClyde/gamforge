#ifndef GAM4980_TYPES_H
#define GAM4980_TYPES_H

/* Freestanding fixed-width types shared by the emulator core and 9288 UI. */
#ifndef BDA_TYPES_H
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef signed short s16;
typedef signed int s32;
#endif

#if defined(__STDC_HOSTED__) && __STDC_HOSTED__
/* LP64 Unix uses unsigned long for uint64_t; reuse the host's definitions
 * instead of conflicting with stdint.h in the snapshot export program. */
#include <stdint.h>
#else
typedef unsigned char uint8_t;
typedef signed char int8_t;
typedef unsigned short uint16_t;
typedef unsigned int uint32_t;
typedef unsigned long long uint64_t;
#endif

#ifndef __cplusplus
typedef int gam4980_bool_t;
#define GAM4980_FALSE 0
#define GAM4980_TRUE 1
#endif

#endif
