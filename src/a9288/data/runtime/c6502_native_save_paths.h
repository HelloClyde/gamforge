#ifndef C6502_NATIVE_SAVE_PATHS_H
#define C6502_NATIVE_SAVE_PATHS_H

#ifndef C6502_SAVE_DIRECTORY
#error The per-game compiler must provide an isolated save directory
#endif

/* Capacity includes the separator, longest filename and NUL. Never use
   the previous 20-byte root-only path buffer with a GBK game directory. */
#define C6502_SAVE_PATH_CAPACITY (sizeof(C6502_SAVE_DIRECTORY) + 15u)
#define C6502_FILE_INDEX_PATH C6502_SAVE_DIRECTORY "\\G49NIDX.BIN"
static c6502_u8 c6502_files_initialized;

static void native_save_initialize(void)
{
    /* mkdir already-existing is harmless. fopen at the full absolute path
       determines whether creation succeeded; there is NO root fallback
       and no process-wide chdir affecting resource/debug APIs. */
    (void)fs_mkdir(C6502_SAVE_PARENT_SYSTEM);
    (void)fs_mkdir(C6502_SAVE_PARENT_DATA);
    (void)fs_mkdir(C6502_SAVE_PARENT_GAMES);
    (void)fs_mkdir(C6502_SAVE_DIRECTORY);
    c6502_files_initialized = 1u;
}

#endif
