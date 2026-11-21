"""Secure image uploads: content-sniffed with Pillow, size/pixel limited, re-encoded (strips EXIF
and any embedded payload) and stored under a random name. The original filename is never used."""
import os
import re
import secrets
from pathlib import Path

from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class UploadError(ValueError):
    pass


def save_image(file_storage, upload_dir, max_bytes, max_px=2000):
    if file_storage is None or not file_storage.filename:
        raise UploadError("No file selected.")
    if Path(file_storage.filename).suffix.lower() not in ALLOWED_EXT:
        raise UploadError("Only JPG, PNG or WebP images are allowed.")
    stream = file_storage.stream
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    if size == 0:
        raise UploadError("The file is empty.")
    if size > max_bytes:
        raise UploadError(f"Image is larger than {max_bytes // (1024 * 1024)} MB.")
    try:
        probe = Image.open(stream)
        probe.verify()
        stream.seek(0)
        img = Image.open(stream)
        if img.format not in ALLOWED_FORMATS:
            raise UploadError("Unsupported image type.")
        img = ImageOps.exif_transpose(img)
        img.thumbnail((max_px, max_px))
        alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        name = secrets.token_hex(12) + (".png" if alpha else ".jpg")
        dest = Path(upload_dir) / name
        Path(upload_dir).mkdir(parents=True, exist_ok=True)
        if alpha:
            img.convert("RGBA").save(dest, "PNG", optimize=True)
        else:
            img.convert("RGB").save(dest, "JPEG", quality=88, optimize=True, progressive=True)
        return name
    except UploadError:
        raise
    except Exception:
        raise UploadError("That file isn't a valid image.")


def delete_file(upload_dir, filename):
    if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
        return
    try:
        (Path(upload_dir) / filename).unlink()
    except OSError:
        pass
    for w in SIZES:
        try:
            (Path(upload_dir) / ".cache" / f"w{w}" / filename).unlink()
        except OSError:
            pass


# ---- responsive variants (served as /media/<file>?w=480) -----------------------------------
SIZES = (240, 320, 480, 720, 1080, 1600)  # whitelist: a visitor can never make the server render arbitrary sizes
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(?:jpg|jpeg|png|webp)", re.I)


def variant(upload_dir, filename, width):
    """Path (relative to upload_dir) of a cached copy no wider than `width`, or None to serve the original."""
    if width not in SIZES or not _SAFE_NAME.fullmatch(filename or ""):
        return None
    src = Path(upload_dir) / filename
    if not src.is_file():
        return None
    rel = f".cache/w{width}/{filename}"
    dest = Path(upload_dir) / rel
    if dest.is_file():
        return rel
    try:
        with Image.open(src) as im:
            if im.width <= width:
                return None  # already small enough
            im = ImageOps.exif_transpose(im)
            im.thumbnail((width, width * 4), Image.LANCZOS)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(f".{secrets.token_hex(4)}.tmp")
            if src.suffix.lower() == ".png":
                im.save(tmp, "PNG", optimize=True)
            else:
                im.convert("RGB").save(tmp, "JPEG", quality=80, optimize=True, progressive=True)
            os.replace(tmp, dest)  # atomic: concurrent requests never see a half-written file
    except Exception:
        return None
    return rel


def srcset(url_for_file, filename, widths=(320, 480, 720, 1080)):
    return ", ".join(f"{url_for_file(filename, w)} {w}w" for w in widths)
