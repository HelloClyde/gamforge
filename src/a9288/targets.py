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


TARGETS = {
    "9288": Target("9288", 320, 240, "2x", "Down_Include", 0x0008),
    # Match the program class used by the supported 9288T firmware launcher.
    # Plain SDK category 8 is insufficient for its system/program entry lookup.
    "9288t": Target("9288T", 240, 160, "1x", "include", 0x0208),
}

DISPLAY_SCALES = {"9288": ("2x",), "9288t": ("1x", "1.5x")}


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
    return {"1x": (159, 96, 40, 32), "1.5x": (239, 144, 0, 8), "2x": (318, 192, 1, 24)}[scale]
