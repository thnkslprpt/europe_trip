#!/usr/bin/env python3
"""Import explicitly selected Google Photos into the static trip site.

This helper uses the Google Photos Picker API. Google no longer permits an app
like this to search an existing user's entire Photos library by date. Instead,
the script creates an official Picker session, opens Google Photos in your
browser, waits for you to select media, downloads the selected photos, sanitizes
and resizes them, stores them under site/photos/YYYY-MM-DD/, and rebuilds the
site photo manifest.

One-time setup:
  1. Enable the *Google Photos Picker API* in a Google Cloud project.
  2. Create an OAuth client of type "Desktop app".
  3. Download its JSON to the repository root as:
       google-photos-oauth-client.json
  4. Install requirements:
       python3 -m pip install -r requirements-photos.txt

Example:
  python3 scripts/import_google_photos.py --date 2017-08-03

OAuth credentials/tokens are intentionally gitignored and are never copied into
site/. The downloaded public site photos contain no EXIF metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import webbrowser
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageOps
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError as exc:
    raise SystemExit(
        "Google Photos importer dependencies are missing.\n"
        "Install them with:\n"
        "  python3 -m pip install -r requirements-photos.txt"
    ) from exc

ROOT = Path(__file__).resolve().parents[1]
PHOTO_ROOT = ROOT / "site" / "photos"
DEFAULT_CLIENT_SECRETS = ROOT / "google-photos-oauth-client.json"
DEFAULT_TOKEN = ROOT / ".google-photos-token.json"
PICKER_API = "https://photospicker.googleapis.com/v1"
SCOPES = ["https://www.googleapis.com/auth/photospicker.mediaitems.readonly"]
TRIP_START = date(2017, 7, 26)
TRIP_END = date(2017, 8, 29)


def parse_duration(value: str | None, default: float) -> float:
    """Parse protobuf Duration values such as '3.5s'."""
    if not value:
        return default
    try:
        if value.endswith("s"):
            return max(0.0, float(value[:-1]))
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def parse_google_time(value: str) -> datetime:
    # Python accepts +00:00 but older versions do not accept a trailing Z.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def likely_trip_local_datetime(created: datetime, target: date) -> datetime:
    """Choose a plausible local Europe time for date checking/filename display.

    This trip was in summer time. Most visited countries were UTC+2, while the
    eastern portion used UTC+3. The Picker API returns RFC3339 timestamps,
    usually Z-normalized, so we test both offsets rather than rejecting a photo
    taken close to local midnight.
    """
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    for hours in (2, 3, 1, 0):
        candidate = created.astimezone(timezone(timedelta(hours=hours)))
        if candidate.date() == target:
            return candidate
    return created.astimezone(timezone.utc)


def target_date_matches(created: datetime, target: date) -> bool:
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    # Summer 2017 Europe route spans mainly UTC+2 / UTC+3. Include UTC itself
    # only as a defensive fallback for malformed/zone-less old metadata.
    return any(
        created.astimezone(timezone(timedelta(hours=hours))).date() == target
        for hours in (0, 1, 2, 3)
    )


def load_credentials(client_secrets: Path, token_path: Path) -> Credentials:
    creds: Credentials | None = None

    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as exc:
            print(f"Ignoring unusable cached OAuth token {token_path.name}: {exc}")

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            print(f"Cached OAuth token could not be refreshed: {exc}")
            creds = None

    if not creds or not creds.valid:
        if not client_secrets.exists():
            raise SystemExit(
                f"OAuth client file not found: {client_secrets}\n\n"
                "Download a Desktop-app OAuth client JSON from Google Cloud and save it as:\n"
                f"  {DEFAULT_CLIENT_SECRETS.name}\n\n"
                "See the 'Google Photos Picker setup' section in README.md."
            )

        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
        print("Opening Google sign-in in your browser...")
        creds = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            open_browser=True,
            authorization_prompt_message=(
                "If the browser did not open, visit this URL:\n{url}\n"
            ),
            success_message=(
                "Google Photos access granted. You can close this tab and return to the terminal."
            ),
        )
        token_path.write_text(creds.to_json(), encoding="utf-8")
        try:
            token_path.chmod(0o600)
        except OSError:
            pass
        print(f"Saved reusable OAuth token to {token_path.name} (gitignored).")

    return creds


def api_json(session: AuthorizedSession, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    response = session.request(method, url, timeout=60, **kwargs)
    if not response.ok:
        detail = response.text.strip()
        raise RuntimeError(f"Google Photos Picker API HTTP {response.status_code}: {detail}")
    if not response.content:
        return {}
    return response.json()


def create_picker_session(session: AuthorizedSession, max_items: int) -> dict[str, Any]:
    payload = {"pickingConfig": {"maxItemCount": str(max_items)}}
    return api_json(session, "POST", f"{PICKER_API}/sessions", json=payload)


def wait_for_picker(session: AuthorizedSession, picking: dict[str, Any]) -> dict[str, Any]:
    session_id = picking["id"]
    polling = picking.get("pollingConfig", {})
    interval = parse_duration(polling.get("pollInterval"), 3.0)
    timeout_in = parse_duration(polling.get("timeoutIn"), 900.0)
    # Give sane bounds even if an odd config is returned.
    interval = min(max(interval, 1.0), 30.0)
    timeout_in = min(max(timeout_in, 30.0), 3600.0)
    deadline = time.monotonic() + timeout_in

    print("Waiting for you to finish selecting photos in Google Photos...")
    while time.monotonic() < deadline:
        time.sleep(interval)
        current = api_json(session, "GET", f"{PICKER_API}/sessions/{session_id}")
        if current.get("mediaItemsSet"):
            return current
        polling = current.get("pollingConfig", {})
        interval = min(max(parse_duration(polling.get("pollInterval"), interval), 1.0), 30.0)

    raise TimeoutError(
        "The Google Photos Picker session timed out before selection was completed. "
        "Run the command again to create a new session."
    )


def list_picked_items(session: AuthorizedSession, session_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"sessionId": session_id, "pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        payload = api_json(session, "GET", f"{PICKER_API}/mediaItems", params=params)
        items.extend(payload.get("mediaItems", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return items


def public_filename(item: dict[str, Any], target: date) -> str:
    created = parse_google_time(item["createTime"])
    local = likely_trip_local_datetime(created, target)
    opaque_id = str(item.get("id", "photo"))
    digest = hashlib.sha256(opaque_id.encode("utf-8")).hexdigest()[:10]
    return f"{target.isoformat()}_{local.strftime('%H%M%S')}_{digest}.jpg"


def sanitize_photo(content: bytes, dest: Path, max_size: int, quality: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(BytesIO(content)) as image:
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
        # Deliberately do not pass exif=...: the public copy contains no EXIF
        # metadata, including no original GPS/location metadata.
        image.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)


def download_photo(
    session: AuthorizedSession,
    item: dict[str, Any],
    target: date,
    max_size: int,
    quality: int,
) -> Path:
    media = item.get("mediaFile") or {}
    base_url = media.get("baseUrl")
    if not base_url:
        raise RuntimeError(f"Selected item has no mediaFile.baseUrl: {item.get('id', 'unknown')}")

    # The Photos APIs require image base URLs to include width and height.
    # The OAuth bearer token is also required for Picker base URLs; the
    # AuthorizedSession supplies it automatically.
    url = f"{base_url}=w{max_size}-h{max_size}"
    response = session.get(url, timeout=120)
    if not response.ok:
        raise RuntimeError(
            f"Photo download HTTP {response.status_code} for {media.get('filename', 'photo')}: "
            f"{response.text[:500]}"
        )

    dest = PHOTO_ROOT / target.isoformat() / public_filename(item, target)
    sanitize_photo(response.content, dest, max_size=max_size, quality=quality)
    return dest


def rebuild_manifest() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_photo_manifest.py")],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pick photos from Google Photos and import sanitized copies into one trip day."
    )
    parser.add_argument("--date", required=True, help="Trip day to import into, YYYY-MM-DD")
    parser.add_argument(
        "--client-secrets",
        type=Path,
        default=DEFAULT_CLIENT_SECRETS,
        help=f"OAuth client JSON (default: {DEFAULT_CLIENT_SECRETS.name})",
    )
    parser.add_argument(
        "--token",
        type=Path,
        default=DEFAULT_TOKEN,
        help=f"OAuth token cache (default: {DEFAULT_TOKEN.name})",
    )
    parser.add_argument("--max-size", type=int, default=2000, help="Maximum published width/height (default 2000)")
    parser.add_argument("--quality", type=int, default=86, help="Published JPEG quality (default 86)")
    parser.add_argument("--max-items", type=int, default=500, help="Maximum items selectable in one Picker session (default 500)")
    parser.add_argument(
        "--allow-date-mismatch",
        action="store_true",
        help="Import selected photos even when Picker createTime does not plausibly match --date",
    )
    args = parser.parse_args()

    try:
        target = datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit("--date must be YYYY-MM-DD, for example 2017-08-03") from exc

    if not (TRIP_START <= target <= TRIP_END):
        raise SystemExit(f"Date must be within the trip range {TRIP_START} to {TRIP_END}")
    if not (1 <= args.max_items <= 2000):
        raise SystemExit("--max-items must be between 1 and 2000")
    if args.max_size < 320:
        raise SystemExit("--max-size must be at least 320")
    if not (40 <= args.quality <= 100):
        raise SystemExit("--quality must be between 40 and 100")

    creds = load_credentials(args.client_secrets.expanduser(), args.token.expanduser())
    session = AuthorizedSession(creds)
    picking: dict[str, Any] | None = None

    try:
        print(f"Creating Google Photos Picker session for {target.isoformat()}...")
        picking = create_picker_session(session, args.max_items)
        picker_uri = picking.get("pickerUri")
        if not picker_uri:
            raise RuntimeError("Google Photos Picker did not return a pickerUri")

        browser_uri = picker_uri.rstrip("/") + "/autoclose"
        print("\nGoogle Photos Picker URL:")
        print(browser_uri)
        print(f"\nSelect the photos for {target.strftime('%A, %d %B %Y')}, then click Done.")
        if not webbrowser.open(browser_uri, new=2):
            print("Your browser did not open automatically; copy the URL above into your browser.")

        ready = wait_for_picker(session, picking)
        items = list_picked_items(session, ready["id"])
        print(f"Google Photos returned {len(items)} selected media item(s).")

        imported = 0
        skipped_videos = 0
        skipped_date = 0
        failed = 0

        for index, item in enumerate(items, 1):
            item_type = item.get("type", "TYPE_UNSPECIFIED")
            media = item.get("mediaFile") or {}
            filename = media.get("filename") or f"item-{index}"

            if item_type != "PHOTO":
                print(f"[{index}/{len(items)}] Skip {filename}: {item_type.lower()} (photo importer currently imports still photos only)")
                skipped_videos += 1
                continue

            create_time_raw = item.get("createTime")
            if not create_time_raw:
                print(f"[{index}/{len(items)}] Skip {filename}: Picker returned no createTime")
                skipped_date += 1
                continue

            created = parse_google_time(create_time_raw)
            matches = target_date_matches(created, target)
            if not matches and not args.allow_date_mismatch:
                print(
                    f"[{index}/{len(items)}] Skip {filename}: createTime {create_time_raw} "
                    f"does not plausibly fall on {target.isoformat()} in the trip's Europe time zones"
                )
                skipped_date += 1
                continue
            if not matches:
                print(f"[{index}/{len(items)}] Warning: importing date-mismatched {filename} because --allow-date-mismatch was used")

            dest = PHOTO_ROOT / target.isoformat() / public_filename(item, target)
            if dest.exists():
                print(f"[{index}/{len(items)}] Already imported {filename} -> {dest.relative_to(ROOT)}")
                imported += 1
                continue

            try:
                dest = download_photo(session, item, target, args.max_size, args.quality)
                print(f"[{index}/{len(items)}] Imported {filename} -> {dest.relative_to(ROOT)}")
                imported += 1
            except Exception as exc:
                print(f"[{index}/{len(items)}] FAILED {filename}: {exc}", file=sys.stderr)
                failed += 1

        rebuild_manifest()
        print("\nImport complete.")
        print(f"  Imported/already present: {imported}")
        print(f"  Skipped non-photos:       {skipped_videos}")
        print(f"  Skipped date mismatches:  {skipped_date}")
        print(f"  Failed:                   {failed}")
        print(f"  Public folder:            site/photos/{target.isoformat()}/")
        print("\nPreview the site, then commit site/photos/ and push to GitHub.")

        if failed:
            raise SystemExit(2)

    finally:
        if picking and picking.get("id"):
            try:
                session.delete(f"{PICKER_API}/sessions/{picking['id']}", timeout=30)
            except Exception:
                # Cleanup is best-effort and should never hide the import result.
                pass
        try:
            session.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
