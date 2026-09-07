/* Only existing full C bridges reach this checkpoint. The caller has already
   saved the guest-register ABI, so no extra native-to-C transition is added
   to the fast ALU leaves. Capture only: never consume keys or run GUI code.

   32 calls is a work-count throttle, NOT a hard real-time latency bound.
   Pure native loops and synchronous firmware calls still need measurement. */
#define C6502_KEY_CHECKPOINT_INTERVAL 32u
static c6502_u32 c6502_key_bridge_calls;
static c6502_u32 c6502_key_checkpoint_checks, c6502_key_checkpoint_scans;

static inline void native_key_checkpoint(c6502_u32 id)
{
    c6502_key_bridge_id = id;
    if (!(++c6502_key_bridge_calls & (C6502_KEY_CHECKPOINT_INTERVAL - 1u))) {
        c6502_u32 before = c6502_perf.key_scans;
        ++c6502_key_checkpoint_checks;
        native_capture_keys(); /* Existing hardware-clock gate still applies. */
        c6502_key_checkpoint_scans += c6502_perf.key_scans - before;
    }
}
