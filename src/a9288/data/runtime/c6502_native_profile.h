/* Bounded observational recorder. No hardware access, guest state changes,
   scheduler calls, stack walking, allocations or file I/O here.
   Gaps are boundary intervals, NOT function-exclusive CPU time. */
#ifndef C6502_NATIVE_PROFILE_H
#define C6502_NATIVE_PROFILE_H
#define NP_EDGES 256u
#define NP_SPIKES 16u
typedef struct NPBridge {
    c6502_u32 calls, samples, ticks, other, max_ticks, remaining, seed;
} NPBridge;
typedef struct NPEdge {
    c6502_u32 from_id, from_pc, to_id, to_pc, calls, other, max_other;
} NPEdge;
typedef struct NPSpike {
    c6502_u32 from_id, from_pc, to_id, to_pc, at, wall, other;
} NPSpike;
typedef struct NativeProfile {
    c6502_u32 active, start, last, last_other, from_id, from_pc;
    c6502_u32 current_id, current_pc, inside;
    c6502_u32 gaps, gap_other, bridge_other, invalid, clock_reads;
    c6502_u32 edge_overflow_calls, edge_overflow_ticks;
    c6502_u32 spike_events, key_events, key_last, key_id, key_pc, key_seen;
    NPBridge bridge[C6502_BRIDGE_COUNT];
    NPEdge edges[NP_EDGES];
    NPSpike spikes[NP_SPIKES], keys[NP_SPIKES];
} NativeProfile;
static NativeProfile c6502_profile;

static void np_begin(c6502_u32 now)
{
    c6502_u32 i;
    volatile c6502_u8 *p = (volatile c6502_u8 *)&c6502_profile;
    for (i = 0u; i < sizeof(c6502_profile); ++i) p[i] = 0u;
    c6502_profile.start = c6502_profile.last = now;
    c6502_profile.active = 1u;
}

static int np_select(c6502_u32 id, int public_api)
{
    NPBridge *b;
    if (!c6502_profile.active || !id || id >= C6502_BRIDGE_COUNT) return 0;
    b = &c6502_profile.bridge[id];
    ++b->calls;
    if (public_api) return 1;
    /* First call plus pseudo-random gaps of 1..127 calls (mean 64).
       Avoid locking onto every 64th iteration of a game loop. No claim
       of cycle-accurate sampling or exact extrapolated helper cost. */
    if (b->remaining) { --b->remaining; return 0; }
    if (!b->seed) b->seed = id * 2654435761u;
    b->seed = b->seed * 1664525u + 1013904223u;
    b->remaining = (b->seed >> 16) % 127u;
    return 1;
}

static void np_keep(NPSpike *items, c6502_u32 from_id, c6502_u32 from_pc,
    c6502_u32 to_id, c6502_u32 to_pc, c6502_u32 at,
    c6502_u32 wall, c6502_u32 other)
{
    c6502_u32 i, minimum = 0u;
    for (i = 1u; i < NP_SPIKES; ++i)
        if (items[i].wall < items[minimum].wall) minimum = i;
    if (wall <= items[minimum].wall) return;
    items[minimum].from_id = from_id; items[minimum].from_pc = from_pc;
    items[minimum].to_id = to_id; items[minimum].to_pc = to_pc;
    items[minimum].at = at; items[minimum].wall = wall;
    items[minimum].other = other;
}

static void np_gap(c6502_u32 now, c6502_u32 other_total,
    c6502_u32 id, c6502_u32 pc)
{
    NativeProfile *p = &c6502_profile;
    c6502_u32 wall = now - p->last, other = other_total - p->last_other;
    c6502_u32 hash, probe;
    if (!p->active) return;
    if ((wall | other) & 0x80000000u) { ++p->invalid; return; }
    ++p->gaps; p->gap_other += other;
    if (!other) return;
    hash = ((p->from_pc >> 1) ^ (pc >> 3) ^ (id * 17u) ^ p->from_id) & (NP_EDGES - 1u);
    for (probe = 0u; probe < 4u; ++probe) {
        NPEdge *e = &p->edges[(hash + probe) & (NP_EDGES - 1u)];
        if (!e->calls || (e->from_id == p->from_id && e->from_pc == p->from_pc &&
                e->to_id == id && e->to_pc == pc)) {
            e->from_id = p->from_id; e->from_pc = p->from_pc;
            e->to_id = id; e->to_pc = pc;
            ++e->calls; e->other += other;
            if (other > e->max_other) e->max_other = other;
            break;
        }
    }
    if (probe == 4u) { ++p->edge_overflow_calls; p->edge_overflow_ticks += other; }
    if (wall >= 32u) {
        ++p->spike_events;
        np_keep(p->spikes, p->from_id, p->from_pc, id, pc,
            now - p->start, wall, other);
    }
}

static void np_leave(c6502_u32 id, c6502_u32 pc, c6502_u32 started,
    c6502_u32 other_started, c6502_u32 now, c6502_u32 other_total)
{
    NativeProfile *p = &c6502_profile;
    NPBridge *b = &p->bridge[id];
    c6502_u32 span = now - started, other = other_total - other_started;
    if (!((span | other) & 0x80000000u)) {
        ++b->samples; b->ticks += span; b->other += other;
        if (span > b->max_ticks) b->max_ticks = span;
        p->bridge_other += other;
    } else ++p->invalid;
    p->last = now; p->last_other = other_total;
    p->from_id = id; p->from_pc = pc;
}

static void np_key(c6502_u32 now)
{
    NativeProfile *p = &c6502_profile;
    c6502_u32 gap = now - p->key_last;
    if (!p->active) return;
    if (p->key_seen && gap >= 32u && !(gap & 0x80000000u)) {
        ++p->key_events;
        np_keep(p->keys, p->key_id, p->key_pc, p->current_id,
            p->current_pc, now - p->start, gap, 0u);
    }
    p->key_seen = 1u; p->key_last = now;
    p->key_id = p->current_id; p->key_pc = p->current_pc;
}
#endif
