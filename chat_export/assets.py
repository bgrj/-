"""生成示例头像和风景图，导出演示不依赖外部图片。"""

import struct
import zlib
from pathlib import Path


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path: Path, width: int, height: int, pixel) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixel(x, y))
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def _blend(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def write_avatar(path: Path, shirt) -> None:
    def pixel(x, y):
        cx, cy = 40, 30
        if (x - cx) ** 2 + (y - cy) ** 2 <= 14 ** 2:
            return (210, 210, 210)
        if y > 52 and abs(x - 40) < 22 - (y - 52) // 3:
            return shirt
        return (32, 32, 32)

    write_png(path, 80, 80, pixel)


def write_landscape(path: Path) -> None:
    def pixel(x, y):
        w, h = 640, 420
        if y < int(h * 0.62):
            color = _blend((120, 186, 230), (196, 224, 242), y / (h * 0.62))
        else:
            color = _blend((92, 158, 72), (46, 110, 48), (y - h * 0.62) / (h * 0.38))
        if (x - 470) ** 2 + (y - 90) ** 2 <= 28 ** 2:
            color = (255, 236, 170)
        if 70 <= x <= 250 and 150 <= y <= 280:
            color = (168, 176, 184) if (x // 18 + y // 16) % 2 == 0 else (186, 194, 200)
            if 90 <= x <= 120 and 180 <= y <= 230:
                color = (90, 140, 170)
        for cx, cy, radius, green in (
            (300, 230, 70, (34, 120, 52)),
            (390, 210, 86, (24, 108, 46)),
            (500, 240, 64, (40, 132, 58)),
            (180, 250, 48, (28, 112, 44)),
        ):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2 and y < 300:
                color = green
        return color

    write_png(path, 640, 420, pixel)


def ensure_demo_assets(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    landscape = directory / "landscape.png"
    other = directory / "avatar-other.png"
    self_avatar = directory / "avatar-self.png"
    if not landscape.exists():
        write_landscape(landscape)
    if not other.exists():
        write_avatar(other, (70, 110, 150))
    if not self_avatar.exists():
        write_avatar(self_avatar, (60, 140, 90))
    return {"landscape": landscape, "other": other, "self": self_avatar}
