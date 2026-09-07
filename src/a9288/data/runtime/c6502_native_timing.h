/* Observation only: no sleeps, timer acknowledgements, or framebuffer writes.
   All timestamps are wrapping 256 Hz CTM ticks, NOT milliseconds. */
#ifndef C6502_NATIVE_TIMING_H
#define C6502_NATIVE_TIMING_H

enum {
    NT_OTHER, NT_PICTURE, NT_TEXT, NT_SHAPE, NT_SURFACE,
    NT_MEMORY, NT_GETMSG, NT_GETKEY, NT_DIALOG, NT_PHASES
};
#define NT_BINS 10u
#define NT_FIRST 32u
#define NT_RECENT 96u
#define NT_WINDOWS 64u
#define NT_WINDOW_TICKS 2560u

typedef struct NativeTimingMetric {
    c6502_u32 calls, ticks, max_ticks, bins[NT_BINS];
} NativeTimingMetric;
typedef struct NativeTimingFrame {
    c6502_u32 events, intervals, last, min_gap, max_gap, sum_gap, bins[NT_BINS];
    c6502_u32 phases[NT_PHASES], timer_steps, timer_delivered, timer_coalesced;
} NativeTimingFrame;
/* CSV fields are deliberately fixed and documented; first-event gap_valid=0. */
typedef struct NativeTimingSample {
    c6502_u32 seq, kind, at, gap_valid, gap, draw_ticks, reload, number;
    c6502_u32 phases[NT_PHASES];
    c6502_u32 timer_steps, timer_delivered, timer_coalesced;
} NativeTimingSample;
typedef struct NativeTimingWindow {
    c6502_u32 start, elapsed, phases[NT_PHASES], full, batches;
} NativeTimingWindow;
typedef struct NativeTiming {
    c6502_u32 active, start, last, sample_count, recent_count, recent_head;
    c6502_u32 lcd_checkpoint, window_count, window_head;
    c6502_u32 invalid_deltas, window_fast_forwards;
    NativeTimingMetric phase[NT_PHASES];
    NativeTimingFrame frame[2];
    NativeTimingSample first[NT_FIRST], recent[NT_RECENT];
    NativeTimingWindow current, windows[NT_WINDOWS];
} NativeTiming;
static NativeTiming c6502_timing;

static c6502_u32 nt_bin(c6502_u32 ticks)
{
    if (!ticks) return 0u;
    if (ticks <= 2u) return 1u;
    if (ticks <= 4u) return 2u;
    if (ticks <= 8u) return 3u;
    if (ticks <= 16u) return 4u;
    if (ticks <= 32u) return 5u;
    if (ticks <= 64u) return 6u;
    if (ticks <= 128u) return 7u;
    if (ticks <= 256u) return 8u;
    return 9u;
}

static void nt_charge(c6502_u32 phase, c6502_u32 now)
{
    NativeTiming *t = &c6502_timing;
    c6502_u32 span = now - t->last;
    t->last = now;
    if (span & 0x80000000u) { ++t->invalid_deltas; return; }
    t->phase[phase].ticks += span;
    /* Split long waits across fixed wall-time windows, not API counts.
       Work MUST be bounded by storage capacity, never by the time delta:
       a forward CTM discontinuity must not spend minutes filling windows
       which would immediately be overwritten. Keep the identical tail. */
    while (span) {
        c6502_u32 room = NT_WINDOW_TICKS - t->current.elapsed;
        c6502_u32 part;
        if (!t->current.elapsed &&
            span >= NT_WINDOW_TICKS * (NT_WINDOWS + 1u)) {
            c6502_u32 skip = span / NT_WINDOW_TICKS - NT_WINDOWS;
            c6502_u32 skipped_ticks = skip * NT_WINDOW_TICKS;
            t->current.start += skipped_ticks;
            t->current.full = t->current.batches = 0u;
            span -= skipped_ticks;
            t->window_fast_forwards += skip;
            /* Advance the ring as though the omitted windows were saved.
               The following NT_WINDOWS writes replace every old entry. */
            t->window_head = (t->window_head + skip) % NT_WINDOWS;
        }
        part = span < room ? span : room;
        t->current.phases[phase] += part;
        t->current.elapsed += part;
        span -= part;
        if (t->current.elapsed == NT_WINDOW_TICKS) {
            c6502_u32 i, next = t->current.start + NT_WINDOW_TICKS;
            /* Freestanding S1C33 has no implicit C-library memcpy import.
               Volatile stores keep this small recorder copy self-contained. */
            for (i = 0u; i < sizeof(t->current) / sizeof(c6502_u32); ++i)
                ((volatile c6502_u32 *)&t->windows[t->window_head])[i] =
                    ((c6502_u32 *)&t->current)[i];
            t->window_head = (t->window_head + 1u) % NT_WINDOWS;
            if (t->window_count < NT_WINDOWS) ++t->window_count;
            for (i = 0u; i < sizeof(t->current) / sizeof(c6502_u32); ++i)
                ((c6502_u32 *)&t->current)[i] = 0u;
            t->current.start = next;
        }
    }
}

static void nt_begin(c6502_u32 now)
{
    c6502_u32 i;
    c6502_u8 *p = (c6502_u8 *)&c6502_timing;
    for (i = 0u; i < sizeof(c6502_timing); ++i) p[i] = 0u;
    c6502_timing.start = c6502_timing.last = now;
    c6502_timing.active = 1u;
}

static c6502_u32 nt_enter(c6502_u32 now)
{
    if (c6502_timing.active) nt_charge(NT_OTHER, now);
    return now;
}

static void nt_leave(c6502_u32 phase, c6502_u32 started, c6502_u32 now)
{
    NativeTimingMetric *m = &c6502_timing.phase[phase];
    c6502_u32 span = now - started;
    if (!c6502_timing.active) return;
    nt_charge(phase, now);
    ++m->calls;
    if (span & 0x80000000u) return;
    if (span > m->max_ticks) m->max_ticks = span;
    ++m->bins[nt_bin(span)];
}

static void nt_frame(c6502_u32 kind, c6502_u32 now, c6502_u32 draw,
    c6502_u32 reload, c6502_u32 number, c6502_u32 steps,
    c6502_u32 delivered, c6502_u32 coalesced)
{
    NativeTiming *t = &c6502_timing;
    NativeTimingFrame *f = &t->frame[kind - 1u];
    NativeTimingSample *s;
    c6502_u32 i, gap = now - f->last, valid = f->events && !(gap & 0x80000000u);
    if (!t->active) return;
    if (t->sample_count < NT_FIRST) s = &t->first[t->sample_count];
    else {
        s = &t->recent[t->recent_head];
        t->recent_head = (t->recent_head + 1u) % NT_RECENT;
        if (t->recent_count < NT_RECENT) ++t->recent_count;
    }
    s->seq = ++t->sample_count; s->kind = kind; s->at = now - t->start;
    s->gap_valid = valid; s->gap = valid ? gap : 0u; s->draw_ticks = draw;
    s->reload = reload; s->number = number;
    if (valid) {
        if (!f->intervals || gap < f->min_gap) f->min_gap = gap;
        if (gap > f->max_gap) f->max_gap = gap;
        ++f->intervals; f->sum_gap += gap; ++f->bins[nt_bin(gap)];
    }
    ++f->events; f->last = now;
    for (i = 0u; i < NT_PHASES; ++i) {
        s->phases[i] = t->phase[i].ticks - f->phases[i];
        f->phases[i] = t->phase[i].ticks;
    }
    s->timer_steps = steps - f->timer_steps; f->timer_steps = steps;
    s->timer_delivered = delivered - f->timer_delivered; f->timer_delivered = delivered;
    s->timer_coalesced = coalesced - f->timer_coalesced; f->timer_coalesced = coalesced;
    if (kind == 1u) ++t->current.full; else ++t->current.batches;
}
#endif
