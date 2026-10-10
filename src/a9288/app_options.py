"""Shared input/metadata/icon contract for the CLI and desktop converter."""

from __future__ import annotations

import struct
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageOps

from a9288.icons import decode_icon, encode_icon
from a9288.paths import DATA
from a9288.targets import target_profile

MAX_NAME_BYTES = 15  # KF2's 16-byte field must retain its terminating NUL.


def encode_app_name(name: str) -> bytes:
    name = name.strip()
    if not name or any(ord(c) < 32 for c in name):
        raise ValueError("程序名称不能为空，也不能包含换行或控制字符。")
    try:
        encoded = name.encode("gbk")
    except UnicodeEncodeError as exc:
        raise ValueError("9288 名称仅支持 GBK 字符，请去掉表情或不支持的字符。") from exc
    if len(encoded) > MAX_NAME_BYTES:
        raise ValueError(
            f"名称为 {len(encoded)} 个 GBK 字节，最多 {MAX_NAME_BYTES} 字节（约 7 个汉字）。"
        )
    return encoded


def default_app_name(stem: str) -> str:
    result = ""
    for char in stem.strip():
        try:
            if len((result + char).encode("gbk")) > MAX_NAME_BYTES:
                break
            if ord(char) >= 32:
                result += char
        except UnicodeEncodeError:
            continue
    return result or "GAM"


def inspect_game(path: Path) -> dict:
    if path.suffix.lower() != ".gam":
        raise ValueError("请选择 .gam 游戏文件。")
    size = path.stat().st_size
    with path.open("rb") as file:
        header = file.read(0x46)
    if len(header) < 0x46 or header[:4] != b"GAM\0":
        raise ValueError("文件不是有效的 A 系列 GAM（缺少 GAM 文件头）。")
    entry, code_size = struct.unpack_from("<HI", header, 0x40)
    if not 0x5046 <= entry < 0x9000 or not 0x46 <= code_size <= size:
        raise ValueError("GAM 入口或代码段长度无效；当前编译器不支持这个文件。")
    return dict(
        path=str(path.resolve()),
        size=size,
        code_size=code_size,
        resource_size=size - code_size,
        entry=entry,
        title=header[6:0x24].split(b"\0", 1)[0].decode("gbk", errors="replace").strip(),
    )


def c_name_definition(name: str) -> str:
    encoded = encode_app_name(name)
    return '#define NATIVE_TITLE "' + "".join(f"\\x{b:02x}" for b in encoded) + '"\n'


def icon_images(
    source: Path | None = None, *, target: str = "9288"
) -> tuple[Image.Image, Image.Image]:
    """Preview KF2 resources: 9288 adds its frame; 9288T uses full-size artwork."""
    framed = target_profile(target).name == "9288"

    def four_gray(image):
        return image.point(lambda v: 0 if v < 64 else 85 if v < 128 else 170 if v < 213 else 255)

    if source is None:
        images = []
        for stem, size in (("ico1", 40), ("ico2", 16)):
            pixels = decode_icon(DATA / "icons" / (stem + ".bin"), size, size)
            image = Image.new("L", (size, size))
            image.putdata([p * 85 for p in pixels])
            images.append(image)
        if framed:
            return tuple(images)
        # The bundled default is already framed. Use only its original inner art
        # for 9288T; do not crop user-supplied images, whose borders may be artwork.
        image = four_gray(images[0].crop((5, 5, 35, 35)).resize((40, 40), Image.Resampling.LANCZOS))
        return image, four_gray(image.resize((16, 16), Image.Resampling.LANCZOS))
    with Image.open(source) as loaded:
        if loaded.width * loaded.height > 25_000_000:
            raise ValueError("图标图片过大，请使用不超过 2500 万像素的图片。")
        art = ImageOps.exif_transpose(loaded).convert("RGBA")
    box = art.getchannel("A").getbbox()
    if box is None:
        raise ValueError("图片完全透明，请选择有可见内容的图标。")
    size = 30 if framed else 40
    art = ImageOps.contain(art.crop(box), (size, size), Image.Resampling.LANCZOS)
    square = Image.new("RGBA", (size, size), "white")
    square.alpha_composite(art, ((size - art.width) // 2, (size - art.height) // 2))
    image = square.convert("L")
    if framed:
        # Preserve the established 9288 outer frame, replacing its inner artwork.
        frame = icon_images()[0]
        frame.paste(image, (5, 5))
        image = frame
    image = four_gray(image)
    return image, four_gray(image.resize((16, 16), Image.Resampling.LANCZOS))


def write_icons(destination: Path, source: Path | None = None, *, target: str = "9288") -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name, image in zip(("ico1", "ico2"), icon_images(source, target=target)):
        pixels = [v // 85 for v in image.tobytes()]
        (destination / (name + ".bin")).write_bytes(encode_icon(image.width, image.height, pixels))


@contextmanager
def compiler_lock(path: Path):
    """OS-owned lock: released on cancellation/crash, not a stale PID file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as file:
        file.seek(0, 2)
        if not file.tell():
            file.write(b"\0")
            file.flush()
        file.seek(0)
        try:
            if __import__("os").name == "nt":
                import msvcrt

                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("另一个原生转换任务正在运行，请等它结束后重试。") from exc
        try:
            yield
        finally:
            file.seek(0)
            if __import__("os").name == "nt":
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file, fcntl.LOCK_UN)
