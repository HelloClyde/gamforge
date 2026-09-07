/* Two bounded generations. Never truncate the latest successful session
   before its replacement has been written and closed. FAT rename is not
   claimed to be power-loss atomic; an unpromoted NATIVE.TMP is recoverable. */
#ifndef C6502_NATIVE_LOG_H
#define C6502_NATIVE_LOG_H
static int native_log_commit(void)
{
    FS_FILE *previous = fs_fopen("a:\\NATIVE.LOG", "rb");
    int had_previous = previous != 0;
    if (previous) {
        if (fs_fclose(previous)) return 0;
        /* Removing an absent backup is harmless. A failed removal of an
           existing file will make the following rename fail safely. */
        (void)fs_remove("a:\\NATIVE.BAK");
        if (fs_rename("a:\\NATIVE.LOG", "a:\\NATIVE.BAK")) return 0;
    }
    if (!fs_rename("a:\\NATIVE.TMP", "a:\\NATIVE.LOG")) return 1;
    if (had_previous) (void)fs_rename("a:\\NATIVE.BAK", "a:\\NATIVE.LOG");
    return 0;
}
#endif
