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
    "9288t": Target("9288T", 240, 160, "1.5x", "include", 0x0208),
}


def target_profile(name: str) -> Target:
    try:
        return TARGETS[name.lower()]
    except KeyError:
        raise ValueError(f"不支持的输出机型：{name}") from None
