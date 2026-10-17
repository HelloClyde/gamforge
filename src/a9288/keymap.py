"""Validated physical host keys -> original 4980 raw keys, fixed at build time.

The two hosts have different input ABIs: matrix row*8+column on 9288,
firmware GUI scan codes on 9288T. Never apply these overrides to touch hosts.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from a9288.targets import target_profile

KEYMAP_TARGETS = ("9288", "9288t")


@dataclass(frozen=True)
class GuestKey:
    label: str
    code: int


@dataclass(frozen=True)
class HostKey:
    id: str
    label: str
    code: int
    default: str


GUEST_KEYS = {
    "search": GuestKey("查找", 0x2B),
    "insert": GuestKey("插入", 0x29),
    "modify": GuestKey("修改", 0x2A),
    "delete": GuestKey("删除", 0x2C),
    "help": GuestKey("帮助", 0x2D),
    "page_up": GuestKey("上翻页", 0x3A),
    "page_down": GuestKey("下翻页", 0x3B),
    "space": GuestKey("空格", 0x36),
    "shift": GuestKey("Shift / 中英", 0x28),
    "input": GuestKey("输入法", 0x20),
    "catalog": GuestKey("目录", 0x01),
    "speech": GuestKey("发音", 0x07),
    "game_power": GuestKey("4980 开关（非系统电源）", 0x00),
    "enter": GuestKey("确定", 0x2F),
    "escape": GuestKey("退出", 0x2E),
    "up": GuestKey("方向上", 0x35),
    "down": GuestKey("方向下", 0x38),
    "left": GuestKey("方向左", 0x37),
    "right": GuestKey("方向右", 0x39),
    "none": GuestKey("不映射（禁用此键的游戏输入）", 0xFF),
}
_LETTERS = {
    **dict(zip("qwertyui", range(0x10, 0x18), strict=True)),
    **dict(zip("asdfghjk", range(0x18, 0x20), strict=True)),
    **dict(zip("zxcvbnm", range(0x21, 0x28), strict=True)),
    "o": 0x32,
    "p": 0x33,
    "l": 0x34,
}
_DIGITS = {**{str(n): n + 7 for n in range(1, 9)}, "9": 0x30, "0": 0x31}
GUEST_KEYS.update({f"letter_{k}": GuestKey(k.upper(), v) for k, v in sorted(_LETTERS.items())})
GUEST_KEYS.update({f"digit_{k}": GuestKey(k, v) for k, v in sorted(_DIGITS.items())})


def _host(key: str, code: int, default: str | None = None, label: str | None = None) -> HostKey:
    return HostKey(key, label or GUEST_KEYS[key].label, code, default or key)


_T_LETTERS = {
    **{k: 16 + i for i, k in enumerate("qwertyuiop")},
    **{k: 30 + i for i, k in enumerate("asdfghjkl")},
    **{k: 44 + i for i, k in enumerate("zxcvbnm")},
}
_MATRIX_LETTERS = {
    "q": 1,
    "a": 2,
    "z": 3,
    "o": 4,
    "w": 9,
    "s": 10,
    "x": 11,
    "p": 12,
    "e": 17,
    "d": 18,
    "c": 19,
    "l": 20,
    "r": 25,
    "f": 26,
    "v": 27,
    "t": 33,
    "g": 34,
    "b": 35,
    "y": 41,
    "h": 42,
    "n": 43,
    "u": 49,
    "j": 50,
    "m": 51,
    "i": 57,
    "k": 58,
}
_MATRIX_DIGITS = {
    "0": 0,
    "1": 8,
    "2": 16,
    "3": 24,
    "4": 32,
    "5": 40,
    "6": 48,
    "7": 56,
    "8": 28,
    "9": 36,
}
HOST_KEYS = {
    "9288": (
        # Preserve the existing runtime defaults, even where the 9288 key
        # label differs from the old mapping. Users can now override them.
        _host("start", 5, "game_power", "开始"),
        _host("help", 37, "insert"),
        _host("delete", 45, "help"),
        _host("page_up", 22),
        _host("page_down", 30),
        _host("space", 53),
        _host("input", 29),
        _host("catalog", 21, label="菜单"),
        _host("speech", 13),
        *(_host(f"letter_{k}", v) for k, v in sorted(_MATRIX_LETTERS.items())),
        *(_host(f"digit_{k}", v) for k, v in sorted(_MATRIX_DIGITS.items())),
    ),
    "9288t": (
        _host("start", 59, "search", "开始"),
        _host("translate", 116, "insert", "翻译"),
        _host("longman", 117, "modify", "朗文"),
        _host("exam", 118, "delete", "考场"),
        _host("page_up", 104),
        _host("page_down", 109),
        _host("help", 87),
        _host("space", 57),
        _host("input", 120),
        _host("catalog", 63),
        _host("speech", 64),
        _host("delete", 111),
        _host("insert", 110, label="插入（扩展键）"),
        _host("modify", 65, label="修改（扩展键）"),
        _host("search", 67, label="查找（扩展键）"),
        _host("backspace", 14, "delete", "退格（扩展键）"),
        *(_host(f"letter_{k}", v) for k, v in sorted(_T_LETTERS.items())),
        *(_host(f"digit_{k}", int(k) + 1 if k != "0" else 11) for k in sorted(_DIGITS)),
    ),
}


def default_keymap(target: str) -> dict[str, str]:
    target_profile(target)
    return {key.id: key.default for key in HOST_KEYS.get(target.lower(), ())}


def normalize_keymap(target: str, overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Resolve a partial mapping and reject typos/unsupported physical keys."""
    result = default_keymap(target)
    if overrides is None:
        return result
    if not isinstance(overrides, Mapping):
        raise ValueError("按键映射必须是「实体键: 4980 按键」字典。")
    if overrides and target.lower() not in KEYMAP_TARGETS:
        raise ValueError(f"{target_profile(target).name} 使用软键盘，不支持自定义按键映射。")
    for source, destination in overrides.items():
        if not isinstance(source, str) or source not in result:
            raise ValueError(f"{target_profile(target).name} 不支持映射实体键 {source!r}。")
        if not isinstance(destination, str) or destination not in GUEST_KEYS:
            raise ValueError(f"未知的 4980 目标按键：{destination!r}。")
        result[source] = destination
    return result


def custom_keymap(target: str, mapping: Mapping[str, str] | None = None) -> dict[str, str]:
    defaults = default_keymap(target)
    return {k: v for k, v in normalize_keymap(target, mapping).items() if v != defaults[k]}


def parse_keymap(target: str, assignments: Sequence[str] | None) -> dict[str, str]:
    """CLI HOST=GUEST syntax. Duplicate source definitions are errors, not last-wins."""
    overrides = {}
    for item in assignments or ():
        if not isinstance(item, str) or item.count("=") != 1:
            raise ValueError("按键映射格式应为 HOST=GUEST，例如 start=help。")
        source, destination = (part.strip().lower() for part in item.split("="))
        if source in overrides:
            raise ValueError(f"实体键 {source!r} 被重复映射。")
        overrides[source] = destination
    normalize_keymap(target, overrides)
    return overrides


def keymap_arguments(target: str, mapping: Mapping[str, str] | None = None) -> list[str]:
    return [
        part
        for k, v in custom_keymap(target, mapping).items()
        for part in ("--key-map", f"{k}={v}")
    ]


def c_keymap_config(target: str, mapping: Mapping[str, str] | None = None) -> str:
    """Numeric-only generated C; no user labels or raw C enter the compiler."""
    overrides = custom_keymap(target, mapping)
    entries = [
        f"{{{key.code}u, {GUEST_KEYS[overrides[key.id]].code}u}}"
        for key in HOST_KEYS.get(target.lower(), ())
        if key.id in overrides
    ]
    return (
        f"#define C6502_KEYMAP_COUNT {len(entries)}u\n"
        + "#define C6502_KEYMAP_ENTRIES {"
        + ", ".join(entries)
        + "}\n"
    )


def keymap_help(target: str) -> str:
    if target.lower() not in KEYMAP_TARGETS:
        target_profile(target)
        return f"{target_profile(target).name} 使用固定软键盘，不支持按键映射。"
    lines = [f"{target_profile(target).name} 实体键（HOST）及默认 4980 按键："]
    lines += [f"  {key.id}: {key.label} -> {key.default}" for key in HOST_KEYS[target.lower()]]
    lines += ["4980 目标键（GUEST）："]
    lines += [f"  {name}: {key.label}" for name, key in GUEST_KEYS.items()]
    lines += ["电源、方向、确定、退出和实体 Shift 键保持固定，不可作为映射来源。"]
    return "\n".join(lines)
