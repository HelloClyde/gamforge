#!/usr/bin/env python3
"""Contracts for the compact statically linked game recompiler."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
from a9288.compiler import backend as direct_backend
from a9288.compiler import build as native_builder
from a9288.compiler import cfg as native
from a9288.compiler import compression as c6502_lzss
from a9288.compiler import frontend as frontend
from a9288.compiler import semantics as semantic_backend
from a9288.paths import DATA


class StaticNativeCompilerTest(unittest.TestCase):
    def test_help_bridge_accepts_both_argument_conventions(self):
        for suffix in ("", "_direct"):
            self.assertIn(
                "c6502_adapter_guidownapphelp" + suffix, native_builder.runtime_supported_bridges()
            )

    def test_builder_rejects_sp_read_in_call_delay_slot(self):
        unsafe = "ld.w %r4, %r6\nld.w %r4, %r9\ncall.d %r0\nld.w %r6, %sp\n"
        with mock.patch.object(
            native_builder.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, stdout=unsafe),
        ):
            with self.assertRaisesRegex(SystemExit, "SP-read delay-slot"):
                native_builder.verify_9288_abi("test-clang")

    def test_glyph_dc_has_no_captioned_client_origin(self):
        app = (DATA / "runtime/c6502_native_9288.c").read_text(encoding="utf-8")
        self.assertIn("fnGUI_GetDC(HWND_DESKTOP)", app)
        self.assertNotIn("fnGUI_GetClientDC(window)", app)
        self.assertIn("fnGUI_SetTimer(window, 1, 1)", app)

    def test_switch_cases_and_default_are_real_cfg_successors(self):
        game = bytearray(0x4000)
        game[0x40:0x46] = bytes.fromhex("465000400000")
        setup = bytes.fromhex("a9008526a9518527a202a000a9908520a95085214c5cdb")
        game[0x46 : 0x46 + len(setup)] = setup
        game[0x100:0x108] = bytes.fromhex("2200270080508850")
        for offset in (0x80, 0x88, 0x90):
            game[offset] = 0x60
        targets = native.game_switch_targets(bytes(game), 0x5A)
        self.assertEqual(targets, (0x90, 0x80, 0x88))
        records, _ = native.recover_game_blocks(bytes(game))
        starts = {r[2] for r in records}
        self.assertTrue({0x80, 0x88, 0x90}.issubset(starts))
        entry = next(r for r in records if r[2] == 0x46)
        self.assertEqual(frontend.block_successors(bytes(game), entry), targets)
        selected, scope = direct_backend.indirect_target_working_set(
            bytes(game), records, starts, [{"call_kinds": {"runtime_tail:switch_comparison": 1}}]
        )
        self.assertEqual(selected, set(targets))
        self.assertEqual(scope, "statically-linked-switch-targets")
        selected, _ = direct_backend.indirect_target_working_set(
            bytes(game), records, starts, [{"call_kinds": {"runtime:indirect_call": 1}}]
        )
        self.assertEqual(selected, starts)

    @staticmethod
    def decode(raw: bytes) -> list[native.aotgen.InstructionIR]:
        result: list[native.aotgen.InstructionIR] = []
        offset = 0
        pc = 0x5000
        while offset < len(raw):
            opcode = raw[offset]
            size = native.aotgen.OPCODE_LENGTHS[opcode]
            reads, writes = native.aotgen.flag_effects(opcode)
            result.append(
                native.aotgen.InstructionIR(
                    pc,
                    raw[offset : offset + size],
                    reads,
                    writes,
                )
            )
            offset += size
            pc += size
        native.aotgen.analyze_flag_liveness(result)
        return result

    def test_public_driver_enforces_sub_mib_kf2(self) -> None:
        driver = (ROOT / "src/a9288/cli.py").read_text(encoding="utf-8")
        self.assertIn("MAX_KF2_BYTES = 1024 * 1024", driver)
        self.assertIn("A9288_SDK", driver)
        self.assertNotIn("D:\\Downloads", driver)
        self.assertNotIn("--dynamic-native-all", driver)
        self.assertIn("compiler.build", driver)
        self.assertNotIn("--iram-exec-engine", driver)
        self.assertIn('"requires_original_gam": False', driver)
        self.assertIn('"runtime_interpreter_fallback": False', driver)

    def test_frontend_lifts_binary_int_expression(self) -> None:
        instructions = self.decode(
            bytes(
                (
                    0x18,
                    0xA5,
                    0x20,
                    0x65,
                    0x23,
                    0x85,
                    0x20,
                    0xA5,
                    0x21,
                    0x65,
                    0x24,
                    0x85,
                    0x21,
                )
            )
        )
        phrase = semantic_backend._semantic_peephole(instructions, 0)
        self.assertEqual(
            phrase,
            ("C6502_ADD16_REGS(0x20u, 0x23u, 0x20u);", 7),
        )

    def test_frontend_lifts_stack_slot_access(self) -> None:
        load = self.decode(bytes((0xA0, 0x0C, 0xB1, 0x28)))
        store = self.decode(bytes((0xA0, 0x04, 0x91, 0x28)))
        self.assertEqual(
            semantic_backend._semantic_peephole(load, 0),
            ("C6502_LOAD_STACK8(0x0cu);", 2),
        )
        self.assertEqual(
            semantic_backend._semantic_peephole(store, 0),
            ("C6502_STORE_STACK8(0x04u);", 2),
        )

    def test_direct_branch_uses_resident_nz_without_materialization(self) -> None:
        lines = direct_backend.condition_lines(
            0xF0,
            "probe",
            ".Lyes",
            ".Lno",
            False,
        )
        text = "\n".join(lines)
        self.assertIn("cmp %r8, 0", text)
        self.assertNotIn("%r10", text)
        self.assertNotIn("materialize", text)

    def test_direct_software_stack_is_a_register(self) -> None:
        lines = direct_backend.indexed_indirect_address(0x28)
        self.assertEqual(lines[0], "    ld.w %r12, %r10")
        self.assertFalse(any("[%r14]" in line for line in lines))

    def test_common_cross_game_opcodes_are_supported(self) -> None:
        for raw in (
            bytes((0x76, 0x20)),
            bytes((0x95, 0x20)),
            bytes((0xB5, 0x20)),
            bytes((0xB9, 0x00, 0x20)),
            bytes((0xC4, 0x20)),
        ):
            instruction = self.decode(raw)[0]
            generated, _ = native.aotgen.emit_instruction(instruction)
            self.assertTrue(generated)
            self.assertTrue(direct_backend.emit_instruction(instruction))

    def test_overlapping_cfg_tail_is_emitted_once(self) -> None:
        game = bytes((0xA9, 0x01, 0xA5, 0x20, 0x60))
        records = [
            (0xE00000, 0x5000, 0, 5, 3, 0),
            (0xE00002, 0x5002, 2, 3, 2, 0),
        ]
        canonical = frontend.canonicalize_records(game, records)
        self.assertEqual(canonical[0][3:5], (2, 1))
        self.assertEqual(frontend.block_successors(game, canonical[0]), (2,))
        self.assertEqual(sum(item[3] for item in canonical), len(game))

    def test_far_call_table_can_live_in_appended_constant_data(self) -> None:
        code_size = 0x8000
        game = bytearray(code_size + 0x100)
        table = 0x902D
        table_offset = code_size + table - 0x9000
        game[table_offset : table_offset + 3] = bytes((0x00, 0x60, 0xE1))
        self.assertEqual(
            native.game_far_table_offset(len(game), code_size, table),
            table_offset,
        )
        self.assertEqual(
            direct_backend.functions.far_game_target(
                bytes(game),
                code_size,
                table,
            ),
            0x5000,
        )

    def test_far_call_accepts_absolute_zero_page_stores(self) -> None:
        for raw in ("a28e8626a2e7862720f6d2", "a28e8e2600a2e78e270020f6d2"):
            self.assertEqual(
                direct_backend.functions.far_call_table(self.decode(bytes.fromhex(raw))), 0xE78E
            )

    def test_resource_lzss_round_trip_and_overlap_copy(self) -> None:
        source = (b"ABCD" * 4096) + bytes(range(256)) * 8
        packed = c6502_lzss.compress(source)
        self.assertLess(len(packed), len(source) // 3)
        self.assertEqual(c6502_lzss.decompress(packed, len(source)), source)

    def test_native_bridges_inline_dynamic_ram_fast_path(self) -> None:
        output = ROOT / "build" / "tests" / "native-bridge-contract"
        output.mkdir(parents=True, exist_ok=True)
        _, assembly = native_builder.generate_bridges(
            ["c6502_direct_read8", "c6502_direct_write8"],
            output,
        )
        text = assembly.read_text(encoding="utf-8")
        read = text.split("c6502_direct_read8:", 1)[1].split(".size c6502_direct_read8", 1)[0]
        write = text.split("c6502_direct_write8:", 1)[1].split(".size c6502_direct_write8", 1)[0]
        self.assertIn("ld.ub %r12, [%r11]", read)
        self.assertIn("ld.b [%r11], %r13", write)
        self.assertNotIn("%r15", read + write)
        read_id = native_builder.SUPPORTED_BRIDGES.index("c6502_direct_read8") + 1
        write_id = native_builder.SUPPORTED_BRIDGES.index("c6502_direct_write8") + 1
        self.assertIn(f".Lbridge_slow_{read_id}", read)
        self.assertIn(f".Lbridge_slow_{write_id}", write)

    def test_native_builder_rejects_unimplemented_bridge(self) -> None:
        output = ROOT / "build" / "tests" / "native-missing-bridge"
        output.mkdir(parents=True, exist_ok=True)
        with self.assertRaisesRegex(ValueError, "no explicit implementation.*missing_sdk_api"):
            native_builder.generate_bridges(
                ["c6502_adapter_missing_sdk_api"],
                output,
            )

    def test_native_bridge_ids_are_stable_across_game_subsets(self) -> None:
        output = ROOT / "build" / "tests" / "native-stable-bridge-ids"
        output.mkdir(parents=True, exist_ok=True)
        header, _ = native_builder.generate_bridges(
            ["c6502_direct_read8"],
            output,
        )
        text = header.read_text(encoding="utf-8")
        self.assertIn("C6502_BRIDGE_c6502_direct_read8", text)
        self.assertIn("C6502_BRIDGE_c6502_adapter_fileopen", text)
        self.assertEqual(
            len(native_builder.SUPPORTED_BRIDGES),
            len(set(native_builder.SUPPORTED_BRIDGES)),
        )

    def test_native_bridge_restores_9288_host_calling_convention(self) -> None:
        output = ROOT / "build" / "tests" / "native-gnu33-bridges"
        output.mkdir(parents=True, exist_ok=True)
        _, assembly = native_builder.generate_bridges(
            ["c6502_direct_read8"],
            output,
        )
        text = assembly.read_text(encoding="utf-8")
        self.assertIn("ld.w %r6, %r3", text)
        self.assertIn("ld.w %r7,", text)
        self.assertNotIn("%r15", text.split("    .globl c6502_native_enter")[0])
        self.assertIn("call c6502_native_bridge", text)
        entry = text.split("c6502_native_enter:", 1)[1]
        self.assertIn("ld.w %r0, %r6", entry)
        self.assertIn("ld.w [%r1], %r15", entry)
        self.assertIn("ld.w %r15, [%r0]", entry)

    def test_native_fillmem_uses_source_signature_argument_order(self) -> None:
        runtime = (DATA / "runtime" / "c6502_native_runtime.c").read_text(encoding="utf-8")
        case = runtime.split("case C6502_BRIDGE_c6502_adapter_fillmem_direct:", 1)[1].split(
            "case C6502_BRIDGE_c6502_adapter_sysmeminit_direct:", 1
        )[0]
        self.assertIn("i = r[1]; result = r[2];", case)
        self.assertNotIn("result = r[1]; i = r[2];", case)

    def test_native_sysgetkey_queries_matrix_without_host_messages(self) -> None:
        runtime = (DATA / "runtime" / "c6502_native_runtime.c").read_text(encoding="utf-8")
        helper = runtime.split("static void api_get_key", 1)[1].split(
            "static void api_graphics", 1
        )[0]
        self.assertIn("native_poll_key()", helper)
        poll = runtime.split("static c6502_u8 native_window_key", 1)[1].split(
            "static c6502_u8 translate_key", 1
        )[0]
        for api in (
            "GetMessage",
            "HavePendingMessage",
            "DispatchMessage",
            "TranslateMessage",
            "PostMessage",
        ):
            self.assertNotIn("fnGUI_" + api, poll)
        self.assertIn("native_capture_keys()", poll)
        self.assertIn("native_take_key()", poll)
        self.assertIn("native_window_key(0)", poll)
        self.assertIn("Real SysGetKey is non-blocking", helper)
        self.assertIn("return8(r, key);", helper)

    def test_native_graphics_uses_c6502_far_abi(self) -> None:
        runtime = (DATA / "runtime" / "c6502_native_runtime.c").read_text(encoding="utf-8")
        helper = runtime.split("static void api_graphics", 1)[1].split(
            "static c6502_u32 signed_div", 1
        )[0]
        self.assertIn("c6502_u8 x0 = (c6502_u8)r[4];", helper)
        self.assertIn("c6502_u8 y0 = stack8(r, 0u);", helper)
        self.assertIn("text[0] = stack8(r, 1u);", helper)
        self.assertIn("native_text(x0, y0, text);", helper)
        self.assertNotIn("fnGUI_bbk_SysShowPicV", runtime)
        self.assertNotIn("fnGUI_bbk_SysPrintString", runtime)
        self.assertIn("pointer = stack16(r, 1u);", helper)
        self.assertIn("pointer = stack16(r, 3u);", helper)
        self.assertIn("stack8(r, 5u)", helper)

    def test_native_gui_translate_converts_enter_and_exit(self) -> None:
        runtime = (DATA / "runtime" / "c6502_native_runtime.c").read_text(encoding="utf-8")
        helper = runtime.split("static c6502_u8 translate_key", 1)[1].split(
            "static void api_get_message", 1
        )[0]
        self.assertIn("case 0x2eu: return 0x28u;", helper)
        self.assertIn("case 0x2fu: return 0x27u;", helper)
        self.assertIn("guest_write(pointer, type);", helper)
        self.assertIn("return8(r, 1u);", helper)

    def test_semantic_helpers_use_resident_software_stack_pointer(self) -> None:
        runtime = (DATA / "runtime" / "c6502_native_runtime.c").read_text(encoding="utf-8")
        self.assertIn("return (c6502_u16)r[10];", runtime)
        self.assertIn("r[10] = value;", runtime)
        semantic = runtime.split("case C6502_BRIDGE_c6502_sem_store16_imm:", 1)[1].split(
            "case C6502_BRIDGE_c6502_sem_load16_indirect:", 1
        )[0]
        self.assertIn("semantic_get16(r, r[11])", semantic)
        self.assertIn("semantic_put16(r, r[12]", semantic)


if __name__ == "__main__":
    unittest.main()
