"""Stable, game-named device save directories, independent of EXE metadata."""

import hashlib
from pathlib import Path

SAVE_ROOT = "A:\\系统\\数据\\游戏"
MAX_COMPONENT_BYTES = 60
INVALID_COMPONENT_CHARS = set('<>:"/\\|?*')


def game_save_name(game: Path) -> str:
    """Keep the source GAM stem (not its often abbreviated header title).

    Display names, icons, target machines, scaling and content hashes do not
    partition saves. Unsafe/unencodable or very long names get a short NAME
    hash to avoid collisions caused by replacement/truncation.
    """
    original = game.stem
    safe = "".join("_" if ord(c) < 32 or c in INVALID_COMPONENT_CHARS else c for c in original)
    safe = safe.strip().rstrip(". ")
    safe = safe.encode("gbk", errors="replace").decode("gbk").replace("?", "_")
    safe = safe or "GAM"
    changed = safe != original or len(safe.encode("gbk")) > MAX_COMPONENT_BYTES
    if changed:
        suffix = "_" + hashlib.sha256(original.encode("utf-8")).hexdigest()[:8].upper()
        budget = MAX_COMPONENT_BYTES - len(suffix)
        prefix = ""
        for char in safe:
            if len((prefix + char).encode("gbk")) > budget:
                break
            prefix += char
        safe = prefix.rstrip(". ") + suffix
    return safe


def game_save_directory(game: Path) -> str:
    return SAVE_ROOT + "\\" + game_save_name(game)


def c_save_config(game: Path) -> str:
    values = {
        "C6502_SAVE_PARENT_SYSTEM": "A:\\系统",
        "C6502_SAVE_PARENT_DATA": "A:\\系统\\数据",
        "C6502_SAVE_PARENT_GAMES": SAVE_ROOT,
        "C6502_SAVE_DIRECTORY": game_save_directory(game),
    }
    return "".join(
        "#define " + name + ' "' + "".join(f"\\x{b:02x}" for b in path.encode("gbk")) + '"\n'
        for name, path in values.items()
    )
