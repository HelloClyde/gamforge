#ifndef GAM4980_NATIVE_MODULE_H
#define GAM4980_NATIVE_MODULE_H

/* On-disk little-endian native-code package shared by the offline packer and
 * the 9288 runtime.  Every field is 32-bit so the loader can validate tables
 * without relying on host structure packing. */
#define GAM4980_NATIVE_MAGIC              0x54414e47u /* "GNAT" */
#define GAM4980_NATIVE_FORMAT_VERSION     1u
#define GAM4980_NATIVE_GAME_FORMAT_VERSION 3u
#define GAM4980_NATIVE_ABI_VERSION        4u
#define GAM4980_NATIVE_HEADER_WORDS       16u
#define GAM4980_NATIVE_HEADER_SIZE        64u
#define GAM4980_NATIVE_GAME_HEADER_WORDS  8u
#define GAM4980_NATIVE_GAME_HEADER_SIZE   32u
#define GAM4980_NATIVE_GAME_FULL_HEADER_SIZE 96u
#define GAM4980_NATIVE_MODULE_WORDS       14u
#define GAM4980_NATIVE_MODULE_SIZE        56u
#define GAM4980_NATIVE_MATCH_WORDS        4u
#define GAM4980_NATIVE_MATCH_SIZE         16u
#define GAM4980_NATIVE_RELOC_WORDS        4u
#define GAM4980_NATIVE_RELOC_SIZE         16u
#define GAM4980_NATIVE_LINK_WORDS         4u
#define GAM4980_NATIVE_LINK_SIZE          16u

#define GAM4980_NATIVE_MAX_MODULES        192u
#define GAM4980_NATIVE_MAX_MATCHES        4096u
#define GAM4980_NATIVE_MAX_RELOCS         512u
#define GAM4980_NATIVE_MAX_LINKS          2048u
#define GAM4980_NATIVE_MANIFEST_LIMIT     0x10000u
#define GAM4980_NATIVE_CODE_SLOT_COUNT    4u

#define GAM4980_NATIVE_MODULE_PIC         0x00000001u
#define GAM4980_NATIVE_MODULE_PRELOAD     0x00000002u
#define GAM4980_NATIVE_MODULE_PINNED      0x00000004u
#define GAM4980_NATIVE_MODULE_GAME        0x00000008u

#define GAM4980_NATIVE_PACKAGE_GAME       0x00000001u

#define GAM4980_NATIVE_RELOC_ABS32_BASE   1u
#define GAM4980_NATIVE_RELOC_GAME_CODE_SPAN 2u
#define GAM4980_NATIVE_RELOC_GAME_OWNER   0xffffffffu

#define GAM4980_NATIVE_LINK_DISPATCH      0x00000001u

#ifndef __ASSEMBLER__

#include "gam4980_types.h"

typedef struct gam4980_native_header {
    u32 magic;
    u32 format_version;
    u32 abi_version;
    u32 header_size;
    u32 file_size;
    u32 module_count;
    u32 module_offset;
    u32 match_count;
    u32 match_offset;
    u32 reloc_count;
    u32 reloc_offset;
    u32 link_count;
    u32 link_offset;
    u32 payload_offset;
    u32 payload_size;
    u32 manifest_hash;
} gam4980_native_header_t;

typedef struct gam4980_native_game_header {
    u32 package_flags;
    u32 game_file_size;
    u32 game_code_size;
    u32 game_file_hash;
    u32 game_entry_pc;
    u32 game_block_count;
    u32 game_native_bytes;
    u32 game_code_span_count;
} gam4980_native_game_header_t;

typedef struct gam4980_native_module_record {
    u32 module_id;
    u32 flags;
    u32 code_offset;
    u32 code_size;
    u32 code_hash;
    u32 entry_offset;
    u32 match_first;
    u32 match_count;
    u32 reloc_first;
    u32 reloc_count;
    u32 link_first;
    u32 link_count;
    u32 working_set;
    u32 reserved;
} gam4980_native_module_record_t;

typedef struct gam4980_native_match_record {
    u32 module_index;
    u32 aot_block_id;
    u32 physical_pc;
    u32 signature_hash;
} gam4980_native_match_record_t;

typedef struct gam4980_native_reloc_record {
    u32 module_index;
    u32 code_offset;
    u32 type;
    u32 addend;
} gam4980_native_reloc_record_t;

typedef struct gam4980_native_link_record {
    u32 module_index;
    u32 guest_pc;
    u32 required_mapping; /* bank slot in bits 31:16, physical bank below */
    u32 entry_offset;
} gam4980_native_link_record_t;

_Static_assert(sizeof(gam4980_native_header_t) ==
    GAM4980_NATIVE_HEADER_SIZE, "native header layout mismatch");
_Static_assert(sizeof(gam4980_native_game_header_t) ==
    GAM4980_NATIVE_GAME_HEADER_SIZE, "native game header layout mismatch");
_Static_assert(sizeof(gam4980_native_module_record_t) ==
    GAM4980_NATIVE_MODULE_SIZE, "native module layout mismatch");
_Static_assert(sizeof(gam4980_native_match_record_t) ==
    GAM4980_NATIVE_MATCH_SIZE, "native match layout mismatch");
_Static_assert(sizeof(gam4980_native_reloc_record_t) ==
    GAM4980_NATIVE_RELOC_SIZE, "native relocation layout mismatch");
_Static_assert(sizeof(gam4980_native_link_record_t) ==
    GAM4980_NATIVE_LINK_SIZE, "native link layout mismatch");

#endif
#endif
