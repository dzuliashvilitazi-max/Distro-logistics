"""Logo storage helpers: validated uploads, safe file paths and generated placeholders."""
import io
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

LOGO_DIR = Path(os.environ.get("LOGO_DIR") or Path(__file__).parent / "uploads" / "logos")
MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_LOGO_SIDE = 256
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
_PALETTE = [(37, 99, 235), (5, 150, 105), (217, 119, 6), (147, 51, 234), (220, 38, 38), (8, 145, 178)]


class LogoError(ValueError):
    pass


def logo_path(user_id: str) -> Path:
    safe = "".join(ch for ch in str(user_id) if ch.isalnum() or ch in "-_")
    if not safe:
        raise LogoError("Invalid user id")
    return LOGO_DIR / f"{safe}.png"


def process_upload(data: bytes) -> bytes:
    """Validate an uploaded image and return a re-encoded, size-limited PNG (drops metadata and any payload)."""
    if not data:
        raise LogoError("Empty file")
    if len(data) > MAX_LOGO_BYTES:
        raise LogoError("Logo must be 2 MB or smaller")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in ALLOWED_FORMATS:
                raise LogoError("Unsupported image type. Use PNG, JPG, WEBP or GIF")
            img.load()
            img = img.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise LogoError("The file is not a valid image")
    img.thumbnail((MAX_LOGO_SIDE, MAX_LOGO_SIDE))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def save_logo(user_id: str, png: bytes) -> None:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    logo_path(user_id).write_bytes(png)


def delete_logo(user_id: str) -> None:
    try:
        logo_path(user_id).unlink()
    except FileNotFoundError:
        pass


def placeholder_png(name: str = "", size: int = 128) -> bytes:
    """Clean default logo: coloured square with the first letter of the business name."""
    letter = (name or "?").strip()[:1].upper() or "?"
    color = _PALETTE[sum(ord(c) for c in (name or "?")) % len(_PALETTE)]
    img = Image.new("RGB", (size, size), color)
    draw = ImageDraw.Draw(img)
    font = None
    for candidate in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "NotoSansGeorgian-Bold.ttf"):
        try:
            font = ImageFont.truetype(candidate, int(size * 0.55))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default(size=int(size * 0.55))
    box = draw.textbbox((0, 0), letter, font=font)
    draw.text(((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]),
              letter, fill=(255, 255, 255), font=font)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def logo_bytes(user_id: str, name: str = "", size: int = 0) -> bytes:
    """Stored logo if present, otherwise a generated placeholder. `size` optionally downsizes for reports."""
    data = None
    try:
        path = logo_path(user_id)
        if path.is_file():
            data = path.read_bytes()
    except (LogoError, OSError):
        data = None
    if data is None:
        return placeholder_png(name, size or 128)
    if size:
        with Image.open(io.BytesIO(data)) as img:
            img = img.convert("RGBA")
            img.thumbnail((size, size))
            out = io.BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
    return data
