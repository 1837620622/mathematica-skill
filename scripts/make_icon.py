#!/usr/bin/env python3
"""生成项目图标：深红圆角底 + 居中的红色 3D 星形二十面体（spikey）。

几何、光照、光栅化全部自己算，不复制任何官方素材；只是视觉语言与 Mathematica
的 App 图标保持一致（暗红底、居中的红色多刺星体）。

为了让相互穿插的尖刺正确遮挡，这里用画家算法之外的 **z-buffer 光栅化**：
每个三角形逐像素比较深度，输出 assets/icon.png（1024、512、256 三档）。

可选依赖：numpy + Pillow（仅图标生成用，运行时不依赖）。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

PHI = (1 + math.sqrt(5)) / 2
VERTS = [
    (0, 1, PHI), (0, -1, PHI), (0, 1, -PHI), (0, -1, -PHI),
    (1, PHI, 0), (-1, PHI, 0), (1, -PHI, 0), (-1, -PHI, 0),
    (PHI, 0, 1), (-PHI, 0, 1), (PHI, 0, -1), (-PHI, 0, -1),
]
FACES = [
    (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
    (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
    (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
    (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
]

Vec = np.ndarray


def normalize(v: Vec) -> Vec:
    length = float(np.linalg.norm(v))
    return v / (length or 1.0)


def rotation_to_z(axis: Vec) -> np.ndarray:
    """把 axis 转到 +z 的旋转矩阵（Rodrigues）。"""
    a = normalize(axis)
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(a, z)
    c = float(np.dot(a, z))
    if c > 0.999999:
        return np.eye(3)
    if c < -0.999999:
        return np.diag([1.0, -1.0, -1.0])
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    s = float(np.linalg.norm(v))
    return np.eye(3) + k + k @ k * ((1 - c) / (s * s))


def tilt_matrix(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def spikey(spike: float) -> list[tuple[Vec, Vec, Vec]]:
    """二十面体每个面顶出一个尖，得到 60 个侧面三角形（经典 stellation）。

    沿顶点轴观察时这些面互相遮挡，正好构成实心星体；不要额外加底面，
    否则内三角会盖住尖刺，看起来发糊。
    """
    base = [normalize(np.array(v, dtype=float)) for v in VERTS]
    triangles: list[tuple[Vec, Vec, Vec]] = []
    for i, j, k in FACES:
        a, b, c = base[i], base[j], base[k]
        apex = normalize(a + b + c) * spike
        triangles += [(a, b, apex), (b, c, apex), (c, a, apex)]
    return triangles


def shade(intensity: float) -> tuple[int, int, int]:
    dark = np.array([0.26, 0.04, 0.07])
    mid = np.array([0.74, 0.19, 0.17])
    light = np.array([1.0, 0.90, 0.83])
    if intensity < 0.58:
        rgb = dark + (mid - dark) * (intensity / 0.58)
    else:
        rgb = mid + (light - mid) * ((intensity - 0.58) / 0.42)
    return tuple(int(round(float(max(0.0, min(1.0, c))) * 255)) for c in rgb)


def hex_color(intensity: float) -> str:
    r, g, b = shade(intensity)
    return f"#{r:02x}{g:02x}{b:02x}"


def render_spikey(size: int, *, spike: float = 1.85, tilt_deg: float = 0.0,
                  ssaa: int = 3) -> Image.Image:
    big = size * ssaa
    rotation = rotation_to_z(np.array(VERTS[0], dtype=float)) @ tilt_matrix(math.radians(tilt_deg))
    light_dir = normalize(np.array([-0.36, 0.46, 0.81]))

    rotated = [(rotation @ p, rotation @ q, rotation @ r) for p, q, r in spikey(spike)]
    pts = np.array([p for tri in rotated for p in tri])
    span = float(max(pts[:, 0].max() - pts[:, 0].min(), pts[:, 1].max() - pts[:, 1].min()))
    pad = big * 0.115
    factor = (big - 2 * pad) / span
    cx = big / 2
    cy = big / 2

    depth = np.full((big, big), -1e9, dtype=np.float32)
    canvas = np.zeros((big, big, 3), dtype=np.uint8)

    for tri in rotated:
        normal = normalize(np.cross(tri[1] - tri[0], tri[2] - tri[0]))
        if abs(float(normal[2])) < 1e-9:
            continue
        # 统一朝外（相对原点）
        if float(np.dot(normal, (tri[0] + tri[1] + tri[2]) / 3)) < 0:
            normal = -normal
        lambert = max(0.0, float(np.dot(normal, light_dir)))
        specular = max(0.0, float(np.dot(normal, normalize(light_dir + np.array([0.0, 0.0, 1.0]))))) ** 26
        intensity = 0.14 + 0.82 * lambert ** 0.60 + 0.10 * specular
        color = shade(min(1.0, intensity))

        screen = np.array([[cx + p[0] * factor, cy - p[1] * factor] for p in tri])
        z = np.array([p[2] for p in tri])
        x0 = max(int(math.floor(screen[:, 0].min())), 0)
        x1 = min(int(math.ceil(screen[:, 0].max())), big - 1)
        y0 = max(int(math.floor(screen[:, 1].min())), 0)
        y1 = min(int(math.ceil(screen[:, 1].max())), big - 1)
        if x1 < x0 or y1 < y0:
            continue

        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        (ax, ay), (bx, by), (cx2, cy2) = screen
        denominator = (by - cy2) * (ax - cx2) + (cx2 - bx) * (ay - cy2)
        if abs(denominator) < 1e-12:
            continue
        w0 = ((by - cy2) * (xs - cx2) + (cx2 - bx) * (ys - cy2)) / denominator
        w1 = ((cy2 - ay) * (xs - cx2) + (ax - cx2) * (ys - cy2)) / denominator
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        interp = w0 * z[0] + w1 * z[1] + w2 * z[2]
        target = depth[y0:y1 + 1, x0:x1 + 1]
        mask = inside & (interp > target)
        if not mask.any():
            continue
        target[mask] = interp[mask]
        canvas[y0:y1 + 1, x0:x1 + 1][mask] = color

    # 用深度不连续处做细边线，让相邻三角面不糊成一片
    d = np.where(depth > -1e8, depth, np.nan)
    gx = np.abs(np.diff(d, axis=1, prepend=d[:, :1]))
    gy = np.abs(np.diff(d, axis=0, prepend=d[:1, :]))
    edge = (np.nan_to_num(gx, nan=0) + np.nan_to_num(gy, nan=0)) > (span * 0.0035)
    edge = np.nan_to_num(edge, nan=False).astype(bool)
    # 柔和描边：只压暗一点，避免硬黑线
    canvas[edge] = (canvas[edge] * 0.72).astype(np.uint8)

    covered = (depth > -1e8).astype(np.uint8) * 255
    rgba = np.dstack([canvas, covered])
    image = Image.fromarray(rgba, "RGBA").resize((size, size), Image.LANCZOS)
    return image


def background(size: int) -> Image.Image:
    """暗红径向渐变 + 圆角遮罩 + 一圈细高光。"""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    cx, cy = size * 0.44, size * 0.30
    radius = float(np.hypot(x - cx, y - cy).max())
    t = np.clip(np.hypot(x - cx, y - cy) / radius, 0, 1)[..., None]
    inner = np.array([0.36, 0.09, 0.13], dtype=np.float32)
    outer = np.array([0.07, 0.015, 0.03], dtype=np.float32)
    rgb = (inner + (outer - inner) * t ** 1.15) * 255
    image = Image.fromarray(rgb.astype(np.uint8), "RGB").convert("RGBA")

    inset = max(2, round(size * 0.012))
    radius = round(size * 0.225)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [inset, inset, size - inset - 1, size - inset - 1], radius=radius, fill=255
    )
    image.putalpha(mask)
    return image


def compose(size: int) -> Image.Image:
    base = background(size)
    base.alpha_composite(render_spikey(size))
    return base


def write_svg(size: int = 1024, *, spike: float = 1.85, tilt_deg: float = 0.0) -> Path:
    """同几何、同光照的矢量版本（画家算法排序，无底面，遮挡关系与 PNG 基本一致）。"""
    rotation = rotation_to_z(np.array(VERTS[0], dtype=float)) @ tilt_matrix(math.radians(tilt_deg))
    light_dir = normalize(np.array([-0.36, 0.46, 0.81]))
    rotated = [(rotation @ p, rotation @ q, rotation @ r) for p, q, r in spikey(spike)]

    pts = np.array([p for tri in rotated for p in tri])
    span = float(max(pts[:, 0].max() - pts[:, 0].min(), pts[:, 1].max() - pts[:, 1].min()))
    pad = size * 0.115
    factor = (size - 2 * pad) / span
    cx = cy = size / 2

    faces = []
    for tri in rotated:
        normal = normalize(np.cross(tri[1] - tri[0], tri[2] - tri[0]))
        if float(normal[2]) <= 0.01:
            continue
        if float(np.dot(normal, (tri[0] + tri[1] + tri[2]) / 3)) < 0:
            normal = -normal
        lambert = max(0.0, float(np.dot(normal, light_dir)))
        intensity = 0.14 + 0.86 * lambert ** 0.60
        coords = " ".join(f"{cx + p[0] * factor:.1f},{cy - p[1] * factor:.1f}" for p in tri)
        depth = float(np.mean([p[2] for p in tri]))
        faces.append((depth, coords, hex_color(min(1.0, intensity))))

    body = "\n".join(
        f'    <polygon points="{coords}" fill="{color}" stroke="rgba(40,6,9,0.28)" stroke-width="1"/>'
        for _d, coords, color in sorted(faces)
    )
    radius = size * 0.225
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" aria-label="mathematica-skill">
  <defs>
    <radialGradient id="bg" cx="44%" cy="30%" r="82%">
      <stop offset="0%" stop-color="#5c1721"/>
      <stop offset="50%" stop-color="#330b13"/>
      <stop offset="100%" stop-color="#160408"/>
    </radialGradient>
  </defs>
  <rect x="0" y="0" width="{size}" height="{size}" rx="{radius:.0f}" fill="url(#bg)"/>
{body}
</svg>
'''
    target = Path(__file__).resolve().parent.parent / "assets" / "icon.svg"
    target.write_text(svg, encoding="utf-8")
    return target


def main() -> int:
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    master = compose(1024)
    master.save(assets / "icon.png")
    for size in (512, 256):
        master.resize((size, size), Image.LANCZOS).save(assets / f"icon-{size}.png")
    write_svg()
    print(assets / "icon.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
