"""Fault injection for the production CTM reader and elapsed Timer arithmetic."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_runtime import performance_globals

from a9288.paths import DATA

TYPES = """
#include <assert.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t c6502_u8;
typedef uint16_t c6502_u16;
typedef uint32_t c6502_u32;
"""


class ClockGuardTests(unittest.TestCase):
    def run_c(self, source):
        cc = shutil.which("gcc")
        if not cc:
            self.skipTest("host gcc is not installed")
        with tempfile.TemporaryDirectory(prefix="a9288-clock-") as folder:
            path = Path(folder) / "test.c"
            exe = Path(folder) / "test.exe"
            path.write_text(TYPES + source, encoding="utf-8")
            subprocess.run(
                [cc, "-O2", "-I", str(DATA / "runtime"), str(path), "-o", str(exe)],
                check=True,
                timeout=30,
            )
            subprocess.run([str(exe)], check=True, timeout=10)

    def test_clock_serial_arithmetic_and_bounded_trace(self):
        self.run_c(r"""
#include "c6502_native_clock.h"
int main(void) {
    assert(native_clock_accept(0));
    assert(native_clock_accept(1000));
    assert(native_clock_accept(1000));
    assert(!native_clock_accept(999));
    assert(c6502_clock_previous == 1000);
    assert(c6502_clock_diagnostics.backwards == 1);
    assert(c6502_clock_diagnostics.trace[0][1] == 999);
    assert(c6502_clock_diagnostics.trace[0][2] == 1000);
    assert(c6502_clock_diagnostics.trace[0][3] == 1);
    for (unsigned i = 0; i < 20; ++i) assert(!native_clock_accept(744));
    assert(c6502_clock_diagnostics.backwards == 21);
    assert(c6502_clock_diagnostics.max_backstep == 256);
    assert(c6502_clock_diagnostics.trace[20 & 7][0] == 21);
    assert(c6502_clock_previous == 1000);
    assert(native_clock_accept(1001));
    assert(!native_clock_accept(1001u + 0x80000000u));
    assert(native_clock_accept(1001u + 0x7fffffffu));
    c6502_clock_initialized = 0;
    assert(native_clock_accept(0xfffffffeu));
    assert(native_clock_accept(2));
    assert(c6502_clock_diagnostics.wraps == 1);
    assert(!native_clock_accept(0xffffffffu));
    assert(c6502_clock_previous == 2);
    assert(native_clock_accept(0x100));
    return 0;
}
""")

    def test_production_reader_retries_backward_and_torn_snapshots(self):
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        reader = (
            "static c6502_u32 native_clock(void)\n{"
            + runtime.split("static c6502_u32 native_clock(void)\n{", 1)[1].split(
                "void c6502_native_finish_input", 1
            )[0]
        )
        # MMIO-only substitution: each volatile byte read is observable so
        # a rollover can be injected between specific reads deterministically.
        for index in range(6):
            reader = reader.replace(f"ctm[{index}]", f"read_ctm({index})")
        self.run_c(
            r"""
#include "c6502_native_clock.h"
#define C6502_CTM_DIVIDER_ADDRESS 0x40153u
static uint8_t samples[4][6];
static unsigned attempts, reads, tear;
static volatile uint8_t *hardware_byte(unsigned address) {
    assert(address == C6502_CTM_DIVIDER_ADDRESS);
    assert(attempts < 4); reads = 0;
    return samples[attempts++];
}
static uint8_t read_ctm(unsigned index) {
    ++reads;
    if (tear && attempts == 1 && reads == 5) {
        /* Calendar rollover between hour and minute reads. */
        samples[0][0] = 0;
        if (tear == 1) samples[0][1] = 1;
        /* tear==2 models divider wrap before calendar changes. */
    }
    return samples[attempts - 1][index];
}
static void fill(unsigned second, unsigned divider) {
    attempts = 0; tear = 0;
    memset(samples, 0, sizeof(samples));
    for (unsigned i=0; i<4; ++i) {
        samples[i][0] = divider; samples[i][1] = second;
    }
}
"""
            + reader
            + r"""
int main(void) {
    fill(3, 232); assert(native_clock() == 1000 && attempts == 1);
    fill(3, 231); assert(native_clock() == 1000 && attempts == 4);
    assert(c6502_clock_diagnostics.backwards == 4);
    assert(c6502_clock_diagnostics.exhausted == 1);
    fill(3, 231); samples[2][0] = 233;
    assert(native_clock() == 1001 && attempts == 3);
    fill(60, 5); assert(native_clock() == 1001 && attempts == 4);
    assert(c6502_clock_diagnostics.snapshot_retries == 4);
    assert(c6502_clock_diagnostics.exhausted == 2);
    fill(4, 0); assert(native_clock() == 1024);
    for (unsigned mode=1; mode<=2; ++mode) {
        c6502_clock_initialized = 0;
        fill(0, 255); assert(native_clock() == 255);
        fill(1, 0); samples[0][0] = 255; samples[0][1] = 0; tear = mode;
        assert(native_clock() == 256 && attempts == 2);
    }
    assert(c6502_clock_diagnostics.snapshot_retries == 6);
    /* Real modulo-u32 wrap, including calendar conversion overflow. */
    c6502_clock_initialized = 0;
    fill(15, 255);
    for (unsigned i=0; i<4; ++i) {
        samples[i][2] = 20; samples[i][3] = 4; samples[i][4] = 194;
    }
    assert(native_clock() == 0xffffffffu);
    attempts = 0; samples[0][1] = 16; samples[0][0] = 0;
    assert(native_clock() == 0 && attempts == 1);
    assert(c6502_clock_diagnostics.wraps == 1);
    return 0;
}
"""
        )

    def test_timer_negative_delta_and_exact_bounded_long_advance(self):
        runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
        timer = (
            "static void native_update_timer"
            + runtime.split("static void native_update_timer", 1)[1].split(
                "static void native_timer_open", 1
            )[0]
        )
        globals_ = performance_globals(runtime).replace(
            "static c6502_u32 native_clock(void){return 0;}",
            "static c6502_u32 now; static c6502_u32 native_clock(void){return now;}",
        )
        self.run_c(
            r"""
#define C6502_TIMER_SOURCE_HZ 10000u
static uint8_t ram[32768], expected[32768];
static struct {uint8_t *ram;} c6502_native_state = {ram};
"""
            + globals_
            + timer
            + r"""
static void setup(unsigned count, unsigned number, unsigned period,
                  unsigned remaining, unsigned fraction, unsigned pending) {
    memset(ram, 0xa4, sizeof(ram)); memset(&c6502_perf, 0, sizeof(c6502_perf));
    ram[0x226] |= 1; ram[0x227] = 256 - period;
    ram[0x2018] = count; ram[0x2019] = number; ram[0x201e] |= pending;
    c6502_timer_remaining = remaining; c6502_timer_fraction = fraction;
    c6502_timer_pending = pending; c6502_timer_clock = now = 12345;
}
static void compare(unsigned elapsed, unsigned count, unsigned number,
                    unsigned period, unsigned remaining, unsigned fraction, unsigned pending) {
    uint64_t source = ((uint64_t)elapsed * 10000 + fraction) >> 8;
    uint64_t irqs = 0, messages = 0, after;
    unsigned rem = remaining;
    setup(count, number, period, remaining, fraction, pending);
    memcpy(expected, ram, sizeof(ram));
    if (source < remaining) rem -= (unsigned)source;
    else {
        source -= remaining;
        irqs = 1 + source / period;
        rem = period - source % period;
        unsigned first = count < number ? number - count :
            (count == 255 && number ? number + 1 : 1);
        if (irqs < first) expected[0x2018] = count + irqs;
        else {
            after = irqs - first;
            messages = 1 + after / (number ? number : 1);
            expected[0x2018] = after % (number ? number : 1);
            expected[0x201e] |= 1;
        }
    }
    now += elapsed; native_update_timer();
    assert(!memcmp(expected, ram, sizeof(ram)));
    assert(c6502_timer_clock == now);
    assert(c6502_timer_remaining == rem);
    assert(c6502_timer_fraction == ((elapsed * 16u + fraction) & 255));
    assert(c6502_timer_pending == (pending || messages));
    assert(c6502_perf.timer_irqs == (uint32_t)irqs);
    assert(c6502_perf.timer_steps == (uint32_t)messages);
    assert(c6502_perf.timer_coalesced == (uint32_t)(messages - (messages && !pending)));
    assert(c6502_perf.timer_update_max_gap_ticks == elapsed);
    assert(c6502_perf.timer_backward_rejected == 0);
    assert(c6502_perf.timer_advance_chunks == (elapsed + 0x03ffffffu) / 0x04000000u);
    assert(c6502_perf.timer_advance_chunks_max == c6502_perf.timer_advance_chunks);
    assert(c6502_perf.timer_advance_chunks <= 32);
}
int main(void) {
    const unsigned deltas[] = {0,1,255,256,65535,65536,65537,
        0x03ffffff,0x04000000,0x04000001,0x7fffffff};
    const unsigned periods[] = {1,90,256}, numbers[] = {0,1,5,50,255};
    const unsigned counts[] = {0,4,50,254,255}, remainders[] = {1,90,256};
    for (unsigned d=0; d<11; ++d) for (unsigned p=0; p<3; ++p)
    for (unsigned n=0; n<5; ++n) for (unsigned c=0; c<5; ++c)
    for (unsigned r=0; r<3; ++r) for (unsigned f=0; f<2; ++f)
    for (unsigned pending=0; pending<2; ++pending)
        compare(deltas[d],counts[c],numbers[n],periods[p],remainders[r], f*255,pending);
    setup(49,50,90,3,240,0);
    memcpy(expected,ram,sizeof(ram));
    now -= 1; native_update_timer(); /* the exact real-device failure */
    assert(!memcmp(expected,ram,sizeof(ram)));
    assert(c6502_timer_clock == 12345 && c6502_timer_fraction == 240);
    assert(c6502_timer_remaining == 3 && !c6502_timer_pending);
    assert(c6502_perf.timer_backward_rejected == 1);
    assert(!c6502_perf.timer_irqs && !c6502_perf.timer_steps);
    assert(!c6502_perf.timer_advance_chunks && !c6502_perf.timer_update_max_gap_ticks);
    now = 12345; native_update_timer();
    assert(!c6502_perf.timer_irqs && !c6502_perf.timer_advance_chunks);
    now = 12346; native_update_timer();
    assert(c6502_perf.timer_irqs == 1 && c6502_perf.timer_steps == 1);
    assert(c6502_timer_remaining == 53 && c6502_timer_fraction == 0);
    setup(49,50,90,3,240,0);
    c6502_timer_clock = 0xffffffff; now = 0; native_update_timer();
    assert(c6502_perf.timer_irqs == 1 && c6502_perf.timer_steps == 1);
    assert(c6502_timer_remaining == 53 && !c6502_perf.timer_backward_rejected);
    /* Disabled Timer rejects backwards time too, without moving its baseline. */
    setup(1,50,90,3,240,0); ram[0x226] &= ~1;
    now = 12344; native_update_timer(); assert(c6502_timer_clock == 12345);
    now = 12346; native_update_timer(); assert(c6502_timer_clock == 12346);
    assert(c6502_timer_remaining == 3 && c6502_timer_fraction == 240);
    assert(!c6502_perf.timer_irqs && !c6502_perf.timer_advance_chunks);
    return 0;
}
"""
        )
