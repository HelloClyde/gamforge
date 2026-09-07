"""Shared-register leaf contracts; target differential probe lives in scripts/."""

import re
import tempfile
import unittest
from pathlib import Path

from a9288.compiler.build import SUPPORTED_BRIDGES, generate_bridges
from a9288.compiler.fast_helpers import PURE, RMW, fast_helper


class NativeLeafTests(unittest.TestCase):
    def test_helpers_have_existing_reference_contracts(self):
        self.assertEqual(len(PURE | RMW), 13)
        self.assertTrue((PURE | RMW) <= set(SUPPORTED_BRIDGES))
        self.assertEqual(fast_helper("unknown", 999), ([], False))

    def test_pure_leaves_do_not_enter_c_bridge_or_spill_globals(self):
        for i, symbol in enumerate(sorted(PURE), 1):
            lines, complete = fast_helper(symbol, i)
            self.assertTrue(complete)
            text = "\n".join(lines)
            self.assertNotIn("call ", text)
            self.assertNotIn("c6502_bridge_regs", text)
            self.assertNotIn("%r15", text)
            self.assertEqual(text.count("pushn %r3"), 1)
            self.assertEqual(text.count("popn %r3"), 1)
            self.assertIn(f".size {symbol}", text)

    def test_rmw_guards_restore_scratch_before_existing_slow_path(self):
        for i, symbol in enumerate(sorted(RMW), 1):
            lines, complete = fast_helper(symbol, i)
            self.assertFalse(complete)
            self.assertEqual(lines[-2:], [f".Lalu_{i}_slow:", "    popn %r3"])
            text = "\n".join(lines)
            self.assertIn("ld.uh %r0, %r12", text)
            self.assertNotIn("%r15", text)
            # No load/store occurs before the last side-effect guard.
            self.assertLess(text.rindex(f"jreq .Lalu_{i}_slow"), text.index("ld.ub %r2, [%r1]"))

    def test_large_complement_masks_never_use_three_ext_prefixes(self):
        for i, symbol in enumerate(sorted(PURE | RMW), 1):
            text = "\n".join(fast_helper(symbol, i)[0])
            self.assertNotRegex(text, r"(?:    ext \d+\n){3}")

    def test_builder_keeps_ids_and_fallbacks_in_profile_and_normal_builds(self):
        for profile in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                header, asm = generate_bridges(sorted(PURE | RMW), Path(directory), profile)
                text = asm.read_text()
                ids = header.read_text()
                for symbol in PURE | RMW:
                    self.assertIn(f"C6502_BRIDGE_{symbol} =", ids)
                    start = text.index(symbol + ":")
                    end = text.index(f".size {symbol},", start)
                    body = text[start:end]
                    if symbol in PURE:
                        self.assertNotIn("call c6502_native_bridge", body)
                    else:
                        self.assertIn("call c6502_native_bridge", body)
                        self.assertRegex(body, r"_slow:\n    popn %r3\n    sub %sp, 4")
                    # No writes to the firmware data-pointer register.
                    self.assertFalse(
                        re.search(r"^\s+(?:ld\.\w+|add|sub|and|or|xor) %r15[, ]", body, re.M)
                    )


if __name__ == "__main__":
    unittest.main()
