#!/usr/bin/env python3
"""Import exported trip photos into date folders used by the static site.

Typical use after downloading a date from Google Photos:
  python3 scripts/import_photos.py ~/Downloads/2017-08-07 --date 2017-08-07

Or scan a larger export and use EXIF DateTimeOriginal:
  python3 scripts/import_photos.py ~/Downloads/GooglePhotos

Images are auto-rotated, resized to at most 2000 px, converted to JPEG, and saved
without EXIF metadata. Videos are copied only when --date is supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from datetime import date, datetime
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError as exc:
    raise SystemExit(
        "Pillow is required. Install it with: python3 -m pip install -r requirements-photos.txt"
    ) from exc

ROOT = Path(__file__).resolve().parents[1]
PHOTO_ROOT = ROOT / "site" / "photos"
TRIP_START = date(2017, 7, 26)
TRIP_END = date(2017, 8, 29)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}


def exif_date(path: Path) -> date | None:
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            raw = exif.get(36867) or exif.get(36868) or exif.get(306)
            if not raw:
                return None
            return datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S").date()
    except Exception:
        return None


def safe_stem(path: Path) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in path.stem).strip("-")
    if not cleaned:
        cleaned = "photo"
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:7]
    return f"{cleaned}-{digest}"


def import_image(src: Path, target_dir: Path, max_size: int, quality: int) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / f"{safe_stem(src)}.jpg"
    with Image.open(src) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            background = Image.new("RGB", image.size, "white")
            if "A" in image.getbands():
                background.paste(image, mask=image.getchannel("A"))
            else:
                background.paste(image)
            image = background
        elif image.mode == "L":
            image = image.convert("RGB")
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        image.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)
    return dest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="Folder containing downloaded/exported photos")
    parser.add_argument("--date", dest="forced_date", help="Force every supported file into YYYY-MM-DD")
    parser.add_argument("--max-size", type=int, default=2000, help="Maximum width/height in pixels (default 2000)")
    parser.add_argument("--quality", type=int, default=86, help="JPEG quality (default 86)")
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input folder does not exist: {args.input}")

    forced: date | None = None
    if args.forced_date:
        forced = datetime.strptime(args.forced_date, "%Y-%m-%d").date()
        if not (TRIP_START <= forced <= TRIP_END):
            raise SystemExit(f"Date must be within {TRIP_START} to {TRIP_END}")

    imported = 0
    skipped = 0
    for src in sorted(p for p in args.input.rglob("*") if p.is_file()):
        ext = src.suffix.lower()
        if ext not in IMAGE_EXTS | VIDEO_EXTS:
            continue

        taken = forced
        if taken is None and ext in IMAGE_EXTS:
            taken = exif_date(src)
        if taken is None or not (TRIP_START <= taken <= TRIP_END):
            skipped += 1
            continue

        target_dir = PHOTO_ROOT / taken.isoformat()
        if ext in IMAGE_EXTS:
            dest = import_image(src, target_dir, args.max_size, args.quality)
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = target_dir / f"{safe_stem(src)}{ext}"
            shutil.copy2(src, dest)
        print(f"Imported {src.name} -> {dest.relative_to(ROOT)}")
        imported += 1

    print(f"Imported {imported} files; skipped {skipped} files without a usable trip date")
    print("Now run: python3 scripts/build_photo_manifest.py")


if __name__ == "__main__":
    main()
