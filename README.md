# pdfstrip

A small desktop tool that strips private metadata from PDFs and images and shrinks them for email.
**Everything runs locally. The app makes no network calls and never uploads your files.**

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
git clone https://github.com/HyderJavaid/pdfstrip.git && cd pdfstrip
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-optional.txt   # optional: enables drag-and-drop
python -m pdfstrip
```

Next time, just `cd pdfstrip && source .venv/bin/activate && python -m pdfstrip`.

### macOS / Windows

tkinter ships with the python.org installers. Then:

```
pip install -r requirements.txt
pip install -r requirements-optional.txt   # optional: enables drag-and-drop
python -m pdfstrip
```

Pass files to open the window with them queued: `python -m pdfstrip report.pdf photo.jpg`.

Without `tkinterdnd2` the window uses the "Add files..." / "Add folder..." buttons instead of drag-and-drop.

A headless command line is also available:

```
python -m pdfstrip.cli -p balanced -o cleaned/ *.pdf *.jpg
```

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

## Limits

Metadata removal covers the standard locations listed above. Text visible on a page, text in the document body, or identifying pixels (faces, watermarks) are not touched. Review sensitive documents before sharing.
