# Europe Trip 2017 — interactive map

A static GitHub Pages site built from the Google Timeline export for the 2017 Europe trip.

## What is included

- Entire-Europe overview with each trip day in a different colour.
- Click any day to zoom to that day's route.
- Significant stop markers with arrival/departure time and an **Open in Google Maps** link.
- Daily movement summary and mode timeline.
- Country-aware views: each day shows the country/countries visited, playback updates the current country live, border crossings are marked on the map, and crossing days get a dedicated country timeline.
- Google `CYCLING` guesses are never displayed as bicycles: plausible on-foot segments are changed to **Walking** and the rest to **Riding**.
- Anything outside the Europe bounding region is excluded, so the Israel departure/return data is not published.
- Timeline playback slider and Play button.
- Optional raw GPS point overlay.
- Per-day Google Photos search button.
- Embedded photo/video gallery when media is placed under `site/photos/YYYY-MM-DD/`.
- Automatic removal of obvious isolated GPS spikes while preserving Europe-only raw points for the Raw GPS toggle.
- Responsive desktop/mobile UI.

## Repository structure

```text
.github/workflows/pages.yml       GitHub Pages deployment
scripts/build_trip_data.py        Timeline -> public map data
scripts/data/                     Bundled offline country boundaries
scripts/build_photo_manifest.py   Builds embedded-photo index
scripts/import_photos.py          Optional helper for downloaded Google Photos
site/                             Only this directory is published
  index.html
  app.js
  styles.css
  data/trip-data.json             Generated
  photos/manifest.json            Generated
source/
  Europe_trip_2017_timeline.json  Original Google Timeline source
```

The repository can remain private. The GitHub Pages site itself is public. The workflow publishes **only `site/`**, not the original `source/` JSON or scripts.

## 1. Put the project on your computer

If you downloaded the ZIP supplied by ChatGPT:

```bash
cd ~/Downloads
unzip europe_trip_repo.zip
cd europe_trip_repo
```

If you want the local folder to be called `europe_trip` instead:

```bash
mv ~/Downloads/europe_trip_repo ~/europe_trip
cd ~/europe_trip
```

## 2. Rebuild the processed Timeline data

Python 3 is the only dependency for the map data itself.

```bash
python3 scripts/build_trip_data.py
python3 scripts/build_photo_manifest.py
```

Expected trip-data output currently reports 35 Europe days, 16 countries, and 3,778 Europe GPS points.

## 3. Preview locally

Do **not** open `site/index.html` directly because browsers block local `fetch()` calls. Run a tiny HTTP server:

```bash
python3 -m http.server 8000 -d site
```

Then open `http://localhost:8000` in your browser.

Stop the server with `Ctrl+C`.

## 4. Push to the existing GitHub repository

Your GitHub repository is already empty, so initialise this folder and push it.

### SSH method

```bash
git init
git branch -M main
git add .
git commit -m "Initial Europe trip map"
git remote add origin git@github.com:thnkslprpt/europe_trip.git
git push -u origin main
```

If you already have an `origin` remote:

```bash
git remote -v
git remote set-url origin git@github.com:thnkslprpt/europe_trip.git
git push -u origin main
```

### HTTPS method

If SSH is not configured, copy the HTTPS repository URL from the GitHub **Quick setup** box and run:

```bash
git remote add origin PASTE_THE_HTTPS_REPOSITORY_URL_HERE
git push -u origin main
```

GitHub may ask you to sign in through its credential manager/token flow.

## 5. Enable GitHub Pages

On GitHub:

1. Open the `europe_trip` repository.
2. Open **Settings**.
3. In the left sidebar choose **Pages**.
4. Under **Build and deployment**, set **Source** to **GitHub Actions**.
5. Go to the repository's **Actions** tab.
6. Open **Deploy Europe Trip to GitHub Pages** and wait for the green checkmark.
7. Return to **Settings -> Pages**; GitHub will show the public site address.

Every later push to `main` redeploys automatically.

If GitHub says Pages is unavailable for the private repository, the personal GitHub account needs a plan that supports Pages from private repositories, or the repository must be made public. The deployed Pages site is public unless you are using GitHub Enterprise Cloud private Pages access control.

## Embedded photos

### Easy option: download a day's photos and import them

Google Photos no longer gives third-party apps broad read access to an existing personal library through the Library API. The reliable static-site approach is therefore to export/download the photos you want to publish and store web-sized copies with the site.

Install the optional photo helper dependency once:

```bash
python3 -m pip install -r requirements-photos.txt
```

For example, if you download the photos for 7 August 2017 into `~/Downloads/aug-07`:

```bash
python3 scripts/import_photos.py ~/Downloads/aug-07 --date 2017-08-07
python3 scripts/build_photo_manifest.py
```

The importer:

- rotates images correctly from EXIF orientation;
- resizes them to a maximum of 2000 px;
- converts them to efficient JPEGs;
- removes EXIF metadata from the published copy;
- stores them under `site/photos/2017-08-07/`.

Preview again:

```bash
python3 -m http.server 8000 -d site
```

Then publish:

```bash
git add .
git commit -m "Add trip photos"
git push
```

### Import a larger photo export automatically

If a folder contains JPEGs with correct EXIF capture dates, omit `--date`:

```bash
python3 scripts/import_photos.py ~/Downloads/GooglePhotosExport
python3 scripts/build_photo_manifest.py
```

Only photos dated from 2017-07-26 through 2017-08-29 are imported.

### Manual option

You can simply create a folder and copy browser-friendly images into it:

```bash
mkdir -p site/photos/2017-08-07
cp ~/Pictures/trip/*.jpg site/photos/2017-08-07/
python3 scripts/build_photo_manifest.py
```

Any media committed under `site/photos/` is publicly downloadable from the Pages site, because the Pages site is public.

## Updating the Timeline source later

Replace:

```text
source/Europe_trip_2017_timeline.json
```

and run:

```bash
python3 scripts/build_trip_data.py
python3 -m http.server 8000 -d site
```

After checking the site:

```bash
git add .
git commit -m "Update trip timeline"
git push
```

The GitHub Actions workflow also rebuilds the trip data and photo manifest on every deployment.

## Map/data notes

- The UI uses Leaflet with the standard OpenStreetMap raster tile service; no map API key is required. The normal OpenStreetMap attribution remains visible in the map corner.
- Country detection is performed while building the site using bundled offline country-boundary data; the published site does not call a reverse-geocoding service.
- Google Place IDs from the Timeline export are used only to create Google Maps links.
- The Google Photos date button is a best-effort web search/deep link for the signed-in `u/0` account.
- Exact route data published in `site/data/` is publicly accessible as part of the public Pages site.
- Third-party data notices are in `THIRD_PARTY_NOTICES.md`.

## Google Photos direct access

The published site does not currently sign in to Google Photos or read the private Google Photos library. The "Google Photos" buttons only open the selected date in Google Photos for the browser's signed-in account.

Google changed the Photos APIs in 2025: third-party apps can no longer list/search an existing user's whole Photos library. The supported Picker API lets the signed-in user explicitly choose photos, and the returned media URLs are temporary. For permanent photos on this public static site, the reliable approach is to copy selected photos into `site/photos/YYYY-MM-DD/` (manually or with the included importer) and commit those copies.

A future optional helper can use the Google Photos Picker API locally: choose a trip day, authorize Google Photos, pick the desired media, and download sanitized copies straight into that day's `site/photos/` folder before committing them.

## Sidebar scrolling/layout

The sidebar is intentionally split into a bounded day-summary pane and an independently scrollable day list. Selecting a day with the previous/next controls scrolls only the day list to keep the active day visible; it does not scroll the document, so the map toolbar remains fixed at the top of the map.
