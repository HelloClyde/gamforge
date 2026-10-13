"""Explicit host profiles; GAM translation itself is independent of the host."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    name: str
    width: int
    height: int
    scale: str
    sdk_directory: str
    module: int
    executable_format: str = "KF2"
    icon_size: int = 40
    d300_magic: int = 0x12345678
    category: str = "娱乐"


TARGETS = {
    "9288": Target("9288", 320, 240, "2x", "Down_Include", 0x0008),
    # Match the program class used by the supported 9288T firmware launcher.
    # Plain SDK category 8 is insufficient for its system/program entry lookup.
    "9288t": Target("9288T", 240, 160, "1x", "include", 0x0208),
    # The S is a distinct D300/touchscreen platform, not a resized KF2 host.
    "9288s": Target("9288S", 160, 240, "1x", "Down_Include", 0, "D300", 32),
    "tsw600": Target(
        "听说王600",
        160,
        240,
        "1x",
        "Down_Include",
        0,
        "D300",
        32,
        d300_magic=0x0000D500,
        category="游戏",
    ),
}

TOUCH_TARGETS = ("9288s", "tsw600")
DISPLAY_SCALES = {
    "9288": ("2x",),
    "9288t": ("1x", "1.5x", "1.5x-linear"),
    **{t: ("1x",) for t in TOUCH_TARGETS},
}


def display_filter(scale: str) -> str:
    return "bilinear-4gray" if scale == "1.5x-linear" else "nearest"


def target_profile(name: str) -> Target:
    try:
        return TARGETS[name.lower()]
    except KeyError:
        raise ValueError(f"不支持的输出机型：{name}") from None


def display_scale(target: str, requested: str | None = None) -> str:
    """Resolve an explicit scale without silently cropping or changing hosts."""
    profile = target_profile(target)
    scale = requested or profile.scale
    if scale not in DISPLAY_SCALES[target.lower()]:
        raise ValueError(f"{profile.name} 不支持画面缩放 {scale}")
    return scale


def display_geometry(target: str, requested: str | None = None) -> tuple[int, int, int, int]:
    """Visible width, height and left/top margins; the hidden 160th bit is white."""
    scale = display_scale(target, requested)
    if target.lower() in TOUCH_TARGETS:
        # Centre in the upper 120 lines, reserving the lower 120 for keys.
        return 159, 96, 0, 12
    return {
        "1x": (159, 96, 40, 32),
        "1.5x": (239, 144, 0, 8),
        "1.5x-linear": (239, 144, 0, 8),
        "2x": (318, 192, 1, 24),
    }[scale]
