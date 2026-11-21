"""Generates tasteful placeholder 'studio' imagery with Pillow (no network, no stock photos).

These are stand-ins so the demo looks designed. Replace them with real photography by uploading
images in Admin > Products / Homepage content; nothing in the application depends on these files.
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

SS = 2  # supersampling factor


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def lum(c):
    return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255


def tone(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def mirror(poly):
    return [(1000 - x, y) for x, y in poly]


def ellipse_pts(cx, cy, rx, ry, n=40, a0=0, a1=360):
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


# ---- garment geometry (logical 1000 x 1250 box) ------------------------------------------------------
def coat(o):
    ln, belt = o.get("len", 1010), o.get("belt", False)
    torso = [(352, 238), (648, 238), (686, 270), (702, ln), (298, ln), (314, 270)]
    lsl = [(352, 240), (312, 268), (205, 775), (282, 802), (352, 470)]
    lapel = [(448, 238), (500, 455), (452, 520), (372, 300), (394, 262)]
    cuff = [(205, 775), (282, 802), (274, 838), (196, 810)]
    detail = [lapel, mirror(lapel), cuff, mirror(cuff), [(420, 236), (580, 236), (560, 272), (440, 272)]]
    if belt:
        detail.append([(300, 560), (700, 560), (702, 604), (298, 604)])
    lines = [[(500, 455), (500, ln)], [(372, 730), (440, 742)], [(628, 730), (560, 742)]]
    dots = [] if belt else [(528, 600 + i * 120, 9) for i in range(3)]
    return dict(body=[torso, lsl, mirror(lsl)], detail=detail, lines=lines, dots=dots)


def sweater(o):
    ln, neck = o.get("len", 860), o.get("neck", "crew")
    body = [(360, 300), (640, 300), (672, 330), (684, ln), (316, ln), (328, 330)]
    lsl = [(360, 296), (326, 330), (214, 830), (292, 860), (346, 500)]
    cuff = [(221, 792), (302, 812), (292, 860), (214, 832)]
    detail = [[(316, ln - 54), (684, ln - 54), (684, ln), (316, ln)], cuff, mirror(cuff)]
    shape = dict(body=[body, lsl, mirror(lsl)], lines=[], dots=[], cut=[])
    if neck == "turtle":
        shape["body"].append([(446, 212), (554, 212), (566, 312), (434, 312)])
        detail.append([(440, 206), (560, 206), (566, 250), (434, 250)])
        shape["cut"].append(ellipse_pts(500, 214, 52, 9))
    else:
        detail.append(ellipse_pts(500, 296, 76, 40))
        shape["cut"].append(ellipse_pts(500, 290, 56, 28))
    if o.get("open"):
        shape["lines"].append([(500, 330), (500, ln)])
        shape["dots"] = [(522, 380 + i * 105, 10) for i in range(6)]
    shape["detail"] = detail
    return shape


def shirt(o):
    long_sleeve, collar = o.get("long", True), o.get("collar", False)
    body = [(360, 296), (640, 296), (672, 330), (686, 840), (314, 840), (328, 330)]
    if long_sleeve:
        lsl = [(360, 292), (326, 330), (214, 830), (290, 856), (346, 500)]
        cuff = [(221, 790), (300, 810), (290, 856), (214, 830)]
    else:
        lsl = [(360, 292), (324, 328), (252, 520), (318, 552), (352, 430)]
        cuff = [(258, 496), (330, 520), (318, 552), (252, 522)]
    detail = [cuff, mirror(cuff)]
    shape = dict(body=[body, lsl, mirror(lsl)], dots=[], lines=[], cut=[])
    if collar:
        c = [(442, 262), (500, 306), (468, 352), (410, 296)]
        detail += [c, mirror(c)]
        shape["lines"].append([(500, 330), (500, 840)])
        shape["dots"] = [(512, 400 + i * 95, 7) for i in range(5)]
    else:
        detail.append(ellipse_pts(500, 300, 74, 38))
        shape["cut"].append(ellipse_pts(500, 294, 55, 26))
    shape["detail"] = detail
    return shape


def dress(o):
    bodice = [(404, 262), (596, 262), (612, 312), (588, 540), (412, 540), (388, 312)]
    skirt = [(412, 534), (588, 534), (772, 1090), (228, 1090)]
    shape = dict(body=[bodice, skirt], dots=[], cut=[], lines=[])
    shape["detail"] = [[(410, 520), (590, 520), (588, 556), (412, 556)]]
    shape["lines"] = [[(500 + (i - 6) * 10, 556), (500 + (i - 6) * 46, 1088)] for i in range(13)]
    if o.get("straps", True):
        s = [(426, 264), (446, 264), (470, 176), (452, 176)]
        shape["body"] += [s, mirror(s)]
        shape["cut"].append([(430, 262), (570, 262), (500, 340)])
    else:
        sl = [(404, 266), (372, 300), (330, 470), (384, 492), (400, 400)]
        shape["body"] += [sl, mirror(sl)]
        shape["cut"].append(ellipse_pts(500, 262, 56, 30))
    return shape


def pants(o):
    wide = o.get("wide", False)
    ob = 296 if wide else 346  # outer hem x
    ib = 468 if wide else 484
    left = [(378, 300), (500, 300), (500, 650), (ib, 1130), (ob, 1130), (364, 650)]
    return dict(
        body=[left, mirror(left)],
        detail=[[(376, 300), (624, 300), (626, 348), (374, 348)]],
        lines=[[(500, 348), (500, 600)], [(430, 650), (ob + 60, 1120)], [(570, 650), (1000 - ob - 60, 1120)],
               [(392, 360), (436, 430)], [(608, 360), (564, 430)]],
        dots=[(500, 324, 8)], cut=[])


def bag(o):
    handle = [(500 + 132 * math.cos(math.radians(a)), 650 - 230 * math.sin(math.radians(a))) for a in range(0, 181, 6)]
    return dict(
        body=[[(300, 640), (700, 640), (744, 1010), (256, 1010)]], strokes=[(handle, 30)],
        detail=[[(300, 640), (700, 640), (716, 790), (284, 790)]],
        lines=[[(284, 790), (716, 790)]], dots=[(500, 800, 16)], cut=[])


def scarf(o):
    ring = ellipse_pts(500, 336, 190, 66, 48, 0, 360)
    ltail = [(372, 360), (474, 392), (528, 1050), (404, 1074)]
    rtail = [(530, 392), (628, 360), (650, 1010), (548, 1030)]
    stripes = [[(372 + i * 4, 420 + i * 70), (560 + i * 4, 440 + i * 70)] for i in range(8)]
    return dict(body=[ltail, rtail], strokes=[(ring, 84)], detail=[[(404, 1020), (528, 1050), (528, 1074), (404, 1074)]],
                lines=stripes, dots=[], cut=[])


SHAPES = {"coat": coat, "sweater": sweater, "shirt": shirt, "dress": dress, "pants": pants, "bag": bag, "scarf": scarf}
DETAIL_BOX = {"coat": (300, 238, 700, 738), "sweater": (320, 262, 680, 712), "shirt": (330, 262, 670, 700),
              "dress": (360, 240, 640, 590), "pants": (350, 290, 650, 700), "bag": (270, 420, 730, 880),
              "scarf": (330, 250, 670, 700)}


# ---- rendering ---------------------------------------------------------------------------------------
def backdrop(size, top, bottom, glow_xy=None):
    w, h = size
    img = ImageOps.colorize(Image.linear_gradient("L").resize((w, h), Image.BILINEAR), black=top, white=bottom)
    gx, gy = glow_xy or (w * 0.5, h * 0.35)
    r = int(max(w, h) * 0.55)
    m = ImageOps.invert(Image.radial_gradient("L")).resize((2 * r, 2 * r), Image.BILINEAR).point(lambda v: int(v * 0.32))
    img.paste(Image.new("RGB", (2 * r, 2 * r), (255, 250, 242)), (int(gx - r), int(gy - r)), m)
    return img


def finish(img, grain=0.22, vignette=0.22):
    w, h = img.size
    noise = Image.effect_noise((w, h), 26).convert("RGB")
    img = Image.blend(img, ImageChops.soft_light(img, noise), grain)
    vm = Image.radial_gradient("L").resize((w, h), Image.BILINEAR).point(lambda v: int(v * vignette))
    return Image.composite(Image.new("RGB", (w, h), (30, 26, 22)), img, vm)


def draw_arch(img, box, color):
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    r = (x1 - x0) / 2
    d.pieslice((x0, y0, x1, y0 + 2 * r), 180, 360, fill=color)
    d.rectangle((x0, y0 + r, x1, y1), fill=color)


def render_garment(kind, opts, color_hex, bg=("#e8e2d6", "#d2c9b8"), size=(1000, 1250), k=1.0, offset=(0, 0),
                   arch=None, seed=1, grain=0.22):
    """Returns (final_image, hi_res_image)."""
    W, H = size
    w, h = W * SS, H * SS
    rnd = random.Random(seed)
    col = rgb(color_hex)
    T = lambda pts: [(offset[0] * SS + x * k * SS, offset[1] * SS + y * k * SS) for x, y in pts]
    img = backdrop((w, h), rgb(bg[0]), rgb(bg[1]))
    if arch:
        draw_arch(img, tuple(v * SS for v in arch[:4]), mix(rgb(bg[0]), rgb(arch[4]), 0.5) if len(arch) > 4 else tone(rgb(bg[0]), 0.94))

    shape = SHAPES[kind](opts)
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    for poly in shape["body"]:
        d.polygon(T(poly), fill=255)
    for pts, wd in shape.get("strokes", []):
        d.line(T(pts), fill=255, width=int(wd * k * SS), joint="curve")
        for p in (pts[0], pts[-1]):
            (px, py), r = T([p])[0], wd * k * SS / 2
            d.ellipse((px - r, py - r, px + r, py + r), fill=255)
    for poly in shape.get("cut", []):
        d.polygon(T(poly), fill=0)
    mask = mask.filter(ImageFilter.GaussianBlur(1.1 * SS))
    bbox = mask.getbbox() or (0, 0, w, h)

    # soft contact shadow
    sh = ImageChops.offset(mask.filter(ImageFilter.GaussianBlur(26 * SS * k)), 0, int(26 * SS * k)).point(lambda v: int(v * 0.30))
    img.paste(Image.new("RGB", (w, h), (52, 40, 28)), (0, 0), sh)

    # lit fabric
    light = ImageOps.invert(Image.linear_gradient("L").rotate(90).resize((w, h), Image.BILINEAR)).point(lambda v: 200 + v * 55 // 255)
    fab = ImageChops.multiply(Image.new("RGB", (w, h), col), light.convert("RGB"))

    def overlay(layer_mask, color, strength=1.0, blur=0.8):
        nonlocal fab
        m = ImageChops.multiply(layer_mask.filter(ImageFilter.GaussianBlur(blur * SS)), mask).point(lambda v: int(v * strength))
        fab = Image.composite(Image.new("RGB", (w, h), color), fab, m)

    dm = Image.new("L", (w, h), 0)
    dd = ImageDraw.Draw(dm)
    for poly in shape.get("detail", []):
        dd.polygon(T(poly), fill=255)
    overlay(dm, tone(col, 0.80), 0.9)

    lm = Image.new("L", (w, h), 0)
    ld = ImageDraw.Draw(lm)
    for pts in shape.get("lines", []):
        ld.line(T(pts), fill=255, width=max(2, int(3.2 * k * SS)))
    overlay(lm, tone(col, 0.55), 0.55, 0.7)

    x0, y0, x1, y1 = bbox
    for tint, strength, n in ((tone(col, 0.70), 0.42, 7), (tuple(min(255, int(v * 1.14) + 8) for v in col), 0.50, 5)):
        fm = Image.new("L", (w, h), 0)
        fd = ImageDraw.Draw(fm)
        for _ in range(n):
            sx = rnd.uniform(x0, x1)
            sy = rnd.uniform(y0, y0 + (y1 - y0) * 0.35)
            amp, ph = rnd.uniform(10, 36) * SS * k, rnd.uniform(0, 6)
            pts = [(sx + amp * math.sin(ph + t / 5.0) + (t - 10) * 3 * SS * k * rnd.uniform(-0.6, 0.6), sy + t * (y1 - y0) * 0.55 / 20) for t in range(21)]
            fd.line(pts, fill=255, width=int(rnd.uniform(14, 34) * SS * k), joint="curve")
        overlay(fm, tint, strength, blur=10 * k)

    for x, y, r in shape.get("dots", []):
        (cx, cy), rr = T([(x, y)])[0], r * k * SS
        fd = ImageDraw.Draw(fab)
        fd.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=tone(col, 0.52))
        fd.ellipse((cx - rr * 0.55, cy - rr * 0.6, cx + rr * 0.1, cy + rr * 0.1), fill=tone(col, 0.82))

    img = Image.composite(fab, img, mask)
    img = finish(img, grain=grain)
    return img.resize((W, H), Image.LANCZOS), img


def detail_crop(hi, kind, size=(1000, 1250)):
    x0, y0, x1, y1 = (v * SS for v in DETAIL_BOX[kind])
    return hi.crop((x0, y0, x1, y1)).resize(size, Image.LANCZOS)


def fabric_scene(size, palette, seed=3, bands=9):
    W, H = size
    rnd = random.Random(seed)
    cols = [rgb(c) for c in palette]
    img = backdrop((W, H), tone(cols[0], 1.04), tone(cols[-1], 0.92))
    for i in range(bands):
        base = H * (0.05 + 0.95 * i / bands)
        amp, fr, ph = rnd.uniform(0.04, 0.10) * H, rnd.uniform(1.0, 2.2), rnd.uniform(0, 6)
        top = [(x, base + amp * math.sin(fr * x / W * 6.28 + ph)) for x in range(0, W + 20, 20)]
        poly = top + [(W, H), (0, H)]
        layer = Image.new("L", (W, H), 0)
        ImageDraw.Draw(layer).polygon(poly, fill=255)
        c = cols[i % len(cols)]
        grad = ImageOps.colorize(Image.linear_gradient("L").resize((W, H)), black=tone(c, 1.10), white=tone(c, 0.82))
        edge = ImageChops.subtract(layer, ImageChops.offset(layer, 0, int(0.05 * H)))
        img = Image.composite(grad, img, layer.point(lambda v: int(v * 0.92)))
        img.paste(Image.new("RGB", (W, H), (255, 248, 238)), (0, 0), edge.filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.5)))
    return finish(img.filter(ImageFilter.GaussianBlur(0.6)), grain=0.25, vignette=0.25)


def save(img, directory, name, quality=86):
    Path(directory).mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(Path(directory) / name, "JPEG", quality=quality, optimize=True, progressive=True)
    return name


# ---- named sets used by the seeder ---------------------------------------------------------------------
BACKDROPS = [("#ebe5da", "#d4cab9"), ("#e2ddd3", "#c9c0ae"), ("#dfe0da", "#c2c5be"), ("#ecdfd2", "#d3bfaa"), ("#d9d4ca", "#bfb6a4")]
DARK_BACKDROPS = [("#4a4540", "#2f2b28"), ("#5b5249", "#3a342e"), ("#3d4640", "#262c28")]


def product_images(directory, slug, kind, opts, color_hex, index):
    """Three gallery images for one product. Returns [filenames]."""
    light = lum(rgb(color_hex)) > 0.62
    bg1 = DARK_BACKDROPS[index % 3] if light else BACKDROPS[index % len(BACKDROPS)]
    bg2 = BACKDROPS[(index + 2) % len(BACKDROPS)] if light else DARK_BACKDROPS[(index + 1) % 3]
    if light and lum(rgb(bg2[0])) > 0.6 and lum(rgb(color_hex)) > 0.8:
        bg2 = DARK_BACKDROPS[(index + 2) % 3]
    a, hi = render_garment(kind, opts, color_hex, bg1, seed=index * 11 + 1)
    b, _ = render_garment(kind, opts, color_hex, bg2, k=0.92, offset=(40, 70), seed=index * 11 + 5,
                          arch=(180, 170, 820, 1250, bg2[1]))
    c = detail_crop(hi, kind)
    names = []
    for n, im in enumerate((a, b, c), 1):
        names.append(save(im, directory, f"demo-{slug}-{n}.jpg"))
    return names
