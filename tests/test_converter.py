"""Converter metadata, atomic publication and desktop component contracts."""

import argparse
import json
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
from a9288 import app_options as options
from a9288 import cli as driver
from a9288 import gui as gui
from a9288.compiler import kf2 as build_9288
from a9288.compiler.boot import DEFAULT_ROM8, DEFAULT_ROME
from a9288.paths import DATA


def game_file(folder):
    path = folder / "测试 游戏.gam"
    data = bytearray(128)
    data[:4] = b"GAM\0"
    data[6:10] = "魔塔".encode("gbk")
    struct.pack_into("<HI", data, 0x40, 0x5046, 96)
    path.write_bytes(data)
    return path


class NativeConverterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_gam_inspection_and_rejection(self):
        game = game_file(self.folder)
        result = options.inspect_game(game)
        self.assertEqual(
            (result["title"], result["entry"], result["code_size"]), ("魔塔", 0x5046, 96)
        )
        game.write_bytes(b"bad")
        with self.assertRaises(ValueError):
            options.inspect_game(game)
        game = game_file(self.folder)
        data = bytearray(game.read_bytes())
        struct.pack_into("<I", data, 0x42, 1000)
        game.write_bytes(data)
        with self.assertRaises(ValueError):
            options.inspect_game(game)

    def test_gbk_name_limit_and_literal(self):
        self.assertEqual(options.encode_app_name(" 魔塔原生 "), "魔塔原生".encode("gbk"))
        self.assertEqual(options.encode_app_name("a" * 15), b"a" * 15)
        for name in ("", "\n", "a" * 16, "魔" * 8, "游戏😀", "a\0b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                options.encode_app_name(name)
        self.assertEqual(options.default_app_name("魔" * 8), "魔" * 7)
        self.assertEqual(options.c_name_definition('A"'), '#define NATIVE_TITLE "\\x41\\x22"\n')

    def test_default_icons_repack_identically(self):
        options.write_icons(self.folder)
        for name in ("ico1.bin", "ico2.bin"):
            self.assertEqual(
                (self.folder / name).read_bytes(), (DATA / "icons" / name).read_bytes()
            )

    def test_custom_icon_aspect_frame_and_exact_preview(self):
        source = self.folder / "自定义.png"
        Image.new("RGBA", (80, 20), (0, 0, 0, 255)).save(source)
        big, small = options.icon_images(source)
        default, _ = options.icon_images()
        for y in range(40):
            for x in range(40):
                if not (5 <= x < 35 and 5 <= y < 35):
                    self.assertEqual(big.getpixel((x, y)), default.getpixel((x, y)))
        self.assertEqual(big.getpixel((20, 8)), 255)  # Not stretched vertically.
        self.assertEqual(big.getpixel((20, 20)), 0)
        self.assertTrue(set(big.tobytes()) <= {0, 85, 170, 255})
        options.write_icons(self.folder / "icons", source)
        for name, image in (("ico1", big), ("ico2", small)):
            decoded = options.decode_icon(
                self.folder / "icons" / (name + ".bin"), image.width, image.height
            )
            self.assertEqual(bytes(v * 85 for v in decoded), image.tobytes())

    def test_transparent_icon_rejected(self):
        source = self.folder / "empty.png"
        Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(source)
        with self.assertRaises(ValueError):
            options.icon_images(source)

    def test_kf2_actual_metadata_and_default_compatibility(self):
        options.write_icons(self.folder)
        name = options.encode_app_name("魔塔原生")
        app = build_9288.pack_kf2(b"payload", app_name=name, icon_root=self.folder)
        header = struct.unpack_from("<IIHH16sIIIII", app)
        self.assertEqual(header[2:5], (1, 8, name.ljust(16, b"\0")))
        self.assertEqual(header[-1], len(app))
        self.assertEqual(app[header[5] :], b"payload")
        self.assertEqual(
            app[header[6] : header[6] + header[7]], (self.folder / "ico1.bin").read_bytes()
        )
        default = build_9288.pack_kf2(b"payload")
        self.assertEqual(default[12:28], b"GAM4980".ljust(16, b"\0"))

    def test_lock_rejects_concurrent_job_and_releases(self):
        lock = self.folder / "compiler.lock"
        with options.compiler_lock(lock):
            with self.assertRaises(RuntimeError):
                with options.compiler_lock(lock):
                    pass
        with options.compiler_lock(lock):
            pass

    def args(self):
        return argparse.Namespace(
            game=game_file(self.folder),
            app_name="魔塔",
            icon=None,
            sdk=self.folder,
            toolchain=self.folder,
            output=self.folder / "原生.exe",
            work_dir=self.folder / "work",
            rom8=DEFAULT_ROM8,
            rome=DEFAULT_ROME,
        )

    def test_failed_compilation_does_not_overwrite(self):
        args = self.args()
        args.output.write_bytes(b"old-valid-exe")
        with patch.object(
            driver.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["compiler"])
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                driver.convert(args)
        self.assertEqual(args.output.read_bytes(), b"old-valid-exe")

    def test_oversize_does_not_overwrite(self):
        args = self.args()
        args.output.write_bytes(b"old-valid-exe")
        stage = args.work_dir / "native-result/program.exe"
        stage.parent.mkdir(parents=True)
        stage.write_bytes(b"X" * driver.MAX_KF2_BYTES)
        with patch.object(driver.subprocess, "run"):
            with self.assertRaises(ValueError):
                driver.convert(args)
        self.assertEqual(args.output.read_bytes(), b"old-valid-exe")

    def test_success_publishes_complete_report(self):
        args = self.args()
        stage = args.work_dir / "native-result/program.exe"
        stage.parent.mkdir(parents=True)
        for suffix in (".exe", ".elf", ".map"):
            stage.with_suffix(suffix).write_bytes(b"new-valid-artifact")
        report = args.work_dir / "c6502-s1c33-direct/report.json"
        report.parent.mkdir()
        report.write_text("{}")
        with patch.object(driver.subprocess, "run"):
            driver.convert(args)
        self.assertEqual(args.output.read_bytes(), b"new-valid-artifact")
        result = json.loads(args.output.with_suffix(".report.json").read_text(encoding="utf-8"))
        self.assertEqual(result["app_name"], "魔塔")
        self.assertFalse(result["runtime_interpreter_fallback"])

    def test_atomic_copy_failure_leaves_destination(self):
        source = self.folder / "source"
        source.write_bytes(b"new")
        dest = self.folder / "target"
        dest.write_bytes(b"old")
        with patch.object(driver.shutil, "copyfile", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                driver.publish_file(source, dest)
        self.assertEqual(dest.read_bytes(), b"old")
        self.assertFalse(list(self.folder.glob("*.tmp")))

    def test_gui_command_preserves_unicode_and_spaces(self):
        config = gui.Conversion(
            self.folder / "测试 游戏.gam",
            "魔塔",
            None,
            self.folder / "我的 游戏.exe",
            self.folder,
            self.folder,
        )
        command = config.command(self.folder / "job folder")
        self.assertEqual(command[command.index("--output") + 1], str(config.output))
        self.assertEqual(command[command.index("--app-name") + 1], "魔塔")

    def test_cancel_before_spawn_does_not_start_compiler(self):
        worker = gui.ConversionWorker(queue.Queue())
        worker.cancel()
        config = gui.Conversion(
            self.folder / "a.gam", "魔塔", None, self.folder / "out.exe", self.folder, self.folder
        )
        with (
            patch.object(gui.Conversion, "validate"),
            patch.object(gui.subprocess, "Popen") as popen,
            patch.object(gui, "WORK", self.folder),
        ):
            worker.run(config)
        popen.assert_not_called()
        self.assertIn(("cancelled", None), list(worker.events.queue))

    def test_cancel_running_owned_process(self):
        worker = gui.ConversionWorker(queue.Queue())
        config = gui.Conversion(
            self.folder / "a.gam", "魔塔", None, self.folder / "out.exe", self.folder, self.folder
        )
        command = [
            sys.executable,
            "-u",
            "-c",
            'import time;print("ready",flush=True);time.sleep(30)',
        ]
        with (
            patch.object(gui.Conversion, "validate"),
            patch.object(gui.Conversion, "command", return_value=command),
            patch.object(gui, "WORK", self.folder),
        ):
            thread = threading.Thread(target=worker.run, args=(config,))
            thread.start()
            try:
                deadline = time.monotonic() + 10
                ready = False
                while time.monotonic() < deadline:
                    kind, data = worker.events.get(timeout=10)
                    if kind == "line" and data.strip() == "ready":
                        ready = True
                        break
                    if kind == "error":
                        self.fail(data)
                self.assertTrue(ready)
            finally:
                worker.cancel()
                thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertIn(("cancelled", None), list(worker.events.queue))
        self.assertFalse(config.output.exists())


if __name__ == "__main__":
    unittest.main()
