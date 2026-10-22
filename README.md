# StripSafe

A small desktop tool that strips private metadata from PDFs and images and shrinks them for email.
**Everything runs locally. The app makes no network calls and never uploads your files.**

## The app

* **Process Files:** drop in files (or use Add files / Add folder), tick the ones you want, pick a compression quality, and press Process. Select any file to see exactly what private data it carries and a preview, before you process it.
* **Settings:** switch between the dark and light theme, and set the default quality and output folder. Settings are stored in a small file in your user config folder (`~/.config/StripSafe/` on Linux, `%APPDATA%\\StripSafe` on Windows).
* **About:** what the app does and does not touch.

Quality steps: *Strip only* (pixels untouched), *High quality*, *Balanced* (default) and *Smallest*.

## What it removes

| File type | Removed |
|---|---|
| PDF | Document info (author, title, creator, producer, dates), XMP metadata, page-level metadata and `PieceInfo`, comment/annotation author names, and the file ID (replaced with a random one) |
| JPEG | EXIF (camera, GPS, timestamps, serial numbers), XMP, IPTC/Photoshop blocks, comments, embedded thumbnails, and any data hidden after the image end marker |
| PNG / WebP | EXIF, XMP and text chunks |

Colour profiles are kept so images don't change appearance. In lossless mode, JPEGs keep an orientation-only EXIF tag so photos still display upright.

## How it shrinks files

* **PDF:** embedded images are re-encoded as JPEG (and downscaled) when that is smaller, content streams are Flate-compressed, and duplicate or unused objects are dropped. Images with transparency masks or unusual colour spaces are left alone.
* **JPEG/WebP:** re-encoded at the preset's quality and downscaled to its maximum size. PNG is losslessly optimised (and downscaled for non-lossless presets).

| Preset | JPEG quality | Max image side |
|---|---|---|
| Strip only (lossless) | unchanged | unchanged |
| Light | 85 | 3000 px |
| Balanced (default) | 75 | 2000 px |
| Strong | 60 | 1400 px |

Cleaned copies are written as `name_clean.ext` (or `name_clean_2.ext`, ...). Originals are never modified or overwritten. Password-protected PDFs are skipped with a message.

## Install and run

Requires Python 3.9+ with tkinter.

### Linux Mint / Ubuntu / Debian

```
sudo apt install python3-tk python3-venv
git clone https://github.com/HyderJavaid/StripSafe.git && cd StripSafe
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-optional.txt   # optional: enables drag-and-drop
python -m stripsafe
```

Next time, just `cd StripSafe && source .venv/bin/activate && python -m stripsafe`.

### macOS / Windows

tkinter ships with the python.org installers. Then:

```
pip install -r requirements.txt
pip install -r requirements-optional.txt   # optional: enables drag-and-drop
python -m stripsafe
```

Pass files to open the window with them queued: `python -m stripsafe report.pdf photo.jpg`.

Without `tkinterdnd2` the window uses the "Add files..." / "Add folder..." buttons instead of drag-and-drop.

A headless command line is also available:

```
python -m stripsafe.cli -p balanced -o cleaned/ *.pdf *.jpg
```

## Standalone app (no Python needed)

Pre-built single-file apps for Linux and Windows are attached to each GitHub release (and as downloadable artifacts on every CI run). Download, then:

* **Linux:** `chmod +x StripSafe-linux-x86_64 && ./StripSafe-linux-x86_64` (or tick "Allow executing as program" in the file's Properties, then double-click).
* **Windows:** double-click `StripSafe-windows-x86_64.exe`. SmartScreen may warn because the file isn't code-signed; choose "More info" then "Run anyway".

Build one yourself on the OS you want to target (PyInstaller can't cross-compile):

```
pip install -r requirements-build.txt
pyinstaller packaging/stripsafe.spec
# result: dist/StripSafe  (dist\StripSafe.exe on Windows)
```

Releases are built by `.github/workflows/build.yml` whenever a tag like `v0.1.0` is pushed.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

## Limits

Metadata removal covers the standard locations listed above. Text visible on a page, text in the document body, or identifying pixels (faces, watermarks) are not touched. Review sensitive documents before sharing.
