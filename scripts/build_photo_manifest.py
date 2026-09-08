#!/usr/bin/env python3
"""Create site/photos/manifest.json from date-named photo folders.

Example:
  site/photos/2017-08-07/IMG_1234.jpg
  site/photos/2017-08-07/IMG_1235.webp
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHOTOS = ROOT / "site" / "photos"
MANIFEST = PHOTOS / "manifest.json"
SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}
SUPPORTED_VIDEOS = {".mp4", ".webm", ".mov"}


def main() -> None:
    PHOTOS.mkdir(parents=True, exist_ok=True)
    entries: dict[str, list[dict[str, str]]] = {}

    for folder in sorted(p for p in PHOTOS.iterdir() if p.is_dir()):
        date = folder.name
        items: list[dict[str, str]] = []
        for file in sorted(p for p in folder.rglob("*") if p.is_file()):
            suffix = file.suffix.lower()
            if suffix not in SUPPORTED_IMAGES | SUPPORTED_VIDEOS:
                continue
            rel = file.relative_to(PHOTOS).as_posix()
            items.append(
                {
                    "src": f"photos/{rel}",
                    "type": "video" if suffix in SUPPORTED_VIDEOS else "image",
                    "name": file.stem.replace("_", " ").replace("-", " "),
                }
            )
        if items:
            entries[date] = items

    payload = {"version": 1, "dates": entries}
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {MANIFEST} with {sum(len(v) for v in entries.values())} media items")


if __name__ == "__main__":
    main()
