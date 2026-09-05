"""Safe packaged smoke test: generated fixtures only, no SDK/ROM/game download."""

import json
import struct

from a9288 import __version__
from a9288.app_options import encode_app_name, icon_images
from a9288.compiler import backend, cfg, frontend, kf2
from a9288.compiler.boot import bundled_helper


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
    print(
        json.dumps(
            {
                "self_test": "PASS",
                "version": __version__,
                "synthetic_blocks": len(records),
                "boot_helper": bundled_helper().is_file(),
            },
            ensure_ascii=False,
        )
    )
