"""Safe packaged smoke test: generated fixtures only, no SDK/ROM/game download."""

import json
import struct

from a9288 import __version__
from a9288.app_options import encode_app_name, icon_images
from a9288.cli import DEFAULT_SDK, DEFAULT_TOOLCHAIN
from a9288.compiler import backend, cfg, frontend, kf2
from a9288.compiler.boot import DEFAULT_ROM8, DEFAULT_ROME, bundled_helper
from a9288.targets import TARGETS, TOUCH_TARGETS, display_geometry


def gui_smoke_test():
    """CI-only visible Tk/Pillow startup check; no game, conversion or settings write."""
    import tkinter as tk

    from a9288.gui import ConverterApp

    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda _kind, error, _trace: errors.append(error)
    try:
        app = ConverterApp(root)
        root.update_idletasks()
        root.after(150, root.quit)
        root.mainloop()
        if errors:
            raise RuntimeError("GUI callback failed during packaged smoke test") from errors[0]
        if not root.winfo_viewable() or app.target.get() not in TARGETS:
            raise RuntimeError("Converter window was not created correctly")
        print(json.dumps({"gui_self_test": "PASS", "tk": root.tk.call("info", "patchlevel")}))
    finally:
        root.destroy()


def main():
    game = bytearray(0x100)
    game[:4] = b"GAM\0"
    struct.pack_into("<HI", game, 0x40, 0x5046, len(game))
    game[0x46:0x49] = bytes.fromhex("a90160")
    records, stats = cfg.recover_game_blocks(bytes(game))
    assert records and stats["entry_pc"] == 0x5046
    assert frontend.firmware_table_symbols(frontend.DEFAULT_MAP)
    assert backend.runtime_symbols(frontend.DEFAULT_MAP)
    assert icon_images()[0].size == (40, 40)
    packed = kf2.pack_kf2(b"\0\0", app_name=encode_app_name("测试"))
    assert packed[:4] == b"KF2\0"
    assert struct.unpack_from("<H", kf2.pack_kf2(b"\0\0", target="9288t"), 10)[0] == 0x0208
    for target in TOUCH_TARGETS:
        assert icon_images(target=target)[0].size == (32, 32)
        assert display_geometry(target) == (159, 96, 0, 12)
    print(
        json.dumps(
            {
                "self_test": "PASS",
                "version": __version__,
                "targets": list(TARGETS),
                "synthetic_blocks": len(records),
                "boot_helper": bundled_helper().is_file(),
                "dependencies": {
                    "sdk": str(DEFAULT_SDK),
                    "toolchain": str(DEFAULT_TOOLCHAIN),
                    "rom8": str(DEFAULT_ROM8),
                    "rome": str(DEFAULT_ROME),
                },
            },
            ensure_ascii=False,
        )
    )
