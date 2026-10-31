"""Read-only PNG quality checks.

This module never renders or rewrites a figure. It inspects the exported native
PNG for integrity, dimensions, blank output and suspicious pixel statistics.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    chunks: list[tuple[bytes, bytes]] = []
    position = 8
    while position + 12 <= len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        chunks.append((kind, body))
        position += 12 + length
        if kind == b"IEND":
            break
    return chunks


def _unfilter(raw: bytes, width: int, height: int, channels: int) -> bytes:
    stride = width * channels
    output = bytearray(stride * height)
    previous = bytearray(stride)
    position = 0
    for row in range(height):
        if position >= len(raw):
            break
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position:position + stride])
        position += stride
        if len(line) < stride:
            line.extend(b"\x00" * (stride - len(line)))
        for index in range(stride):
            left = line[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                line[index] = (line[index] + left) & 0xFF
            elif filter_type == 2:
                line[index] = (line[index] + up) & 0xFF
            elif filter_type == 3:
                line[index] = (line[index] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                p = left + up - upper_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upper_left)
                predictor = left if pa <= pb and pa <= pc else (up if pb <= pc else upper_left)
                line[index] = (line[index] + predictor) & 0xFF
        output[row * stride:(row + 1) * stride] = line
        previous = line
    return bytes(output)


def read_png(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    result: dict[str, object] = {"path": path.name, "bytes": len(data), "valid": False}
    if not data.startswith(PNG_SIGNATURE):
        result["error"] = "not a PNG signature"
        return result
    chunks = _chunks(data)
    header = next((body for kind, body in chunks if kind == b"IHDR"), None)
    if header is None or len(header) < 13:
        result["error"] = "missing IHDR"
        return result
    width, height, depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", header[:13])
    result.update({"width": width, "height": height, "bit_depth": depth, "color_type": color_type,
                   "interlace": interlace, "valid": True})
    if compression != 0 or filtering != 0:
        result["valid"] = False
        result["error"] = "unsupported PNG compression/filter method"
        return result
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None or depth not in (8, 16):
        result["note"] = "pixel statistics skipped for this PNG variant"
        return result
    if interlace != 0:
        result["note"] = "pixel statistics skipped for interlaced PNG"
        return result
    try:
        raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    except zlib.error as exc:
        result["valid"] = False
        result["error"] = f"corrupt PNG data: {exc}"
        return result
    pixels = _unfilter(raw, width, height, channels)
    step = 2 if depth == 16 else 1
    if color_type == 3:
        palette = next((body for kind, body in chunks if kind == b"PLTE"), b"")
        indexes = pixels[::step]
        colors = Counter(indexes)
        result["unique_colors"] = len(colors)
        result["most_common_ratio"] = round(colors.most_common(1)[0][1] / max(1, len(indexes)), 6)
        result["dark_ratio"] = None
        if palette:
            samples = []
            for index in list(colors)[:2000]:
                base = index * 3
                if base + 2 < len(palette):
                    samples.append((palette[base], palette[base + 1], palette[base + 2]))
            result["mean_rgb"] = tuple(
                round(sum(sample[i] for sample in samples) / max(1, len(samples)), 2)
                for i in range(3)
            )
        return result
    pixels_per_row = width * channels
    sampled: Counter[tuple[int, ...]] = Counter()
    dark = 0
    total = 0
    for row in range(0, height, max(1, height // 400)):
        start = row * pixels_per_row
        line = pixels[start:start + pixels_per_row]
        for index in range(0, len(line) - channels + 1, channels * max(1, width // 300)):
            pixel = tuple(line[index:index + channels])
            sampled[pixel] += 1
            total += 1
            if color_type in (0, 4):
                luminance = float(pixel[0])
            else:
                luminance = sum(pixel[:3]) / 3.0
            if luminance < 245:
                dark += 1
    result["unique_colors"] = len(sampled)
    if not sampled or total == 0:
        result["most_common_ratio"] = 1.0
        result["dark_ratio"] = 0.0
        result["sampled_pixels"] = 0
        return result
    result["most_common_ratio"] = round(sampled.most_common(1)[0][1] / max(1, total), 6)
    result["dark_ratio"] = round(dark / max(1, total), 6)
    result["sampled_pixels"] = total
    return result


def validate_png(path: str | Path, *, min_width: int = 200, min_height: int = 150) -> dict[str, object]:
    target = Path(path)
    report = read_png(target)
    errors: list[str] = []
    warnings: list[str] = []
    if not report.get("valid"):
        errors.append(str(report.get("error") or "invalid PNG"))
    width = int(report.get("width") or 0)
    height = int(report.get("height") or 0)
    if width < min_width or height < min_height:
        errors.append(f"image is too small: {width}x{height}, expected at least {min_width}x{min_height}")
    dark = report.get("dark_ratio")
    if dark is not None:
        if float(dark) <= 0.0005:
            errors.append("image appears blank: almost no non-white pixels")
        elif float(dark) < 0.002:
            warnings.append("image has very little ink; inspect it visually")
        elif float(dark) > 0.98:
            warnings.append("image is almost entirely dark; inspect it visually")
    unique = report.get("unique_colors")
    if unique is not None and int(unique) <= 1:
        errors.append("image contains a single colour")
    report["errors"] = errors
    report["warnings"] = warnings
    report["ok"] = not errors
    return report
