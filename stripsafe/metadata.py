"""Read-only inspection of what private metadata a file currently carries."""

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageOps
from pypdf import PdfReader

from .images import IMAGE_EXTENSIONS
from .pdf import _MARKUP_ANNOTS, PDF_EXTENSIONS

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
# (tag, label) for top-level EXIF tags worth showing by name.
_SHOWN_TAGS = [
    (0x010F, "Camera make"), (0x0110, "Camera model"), (0x0131, "Software"),
    (0x013B, "Author"), (0x8298, "Copyright"), (0x0132, "Date modified"),
]
_PDF_FIELDS = [
    ("/Author", "Author"), ("/Creator", "Created with"), ("/Producer", "Producer"),
    ("/Title", "Title"), ("/Subject", "Subject"), ("/Keywords", "Keywords"),
    ("/CreationDate", "Created"), ("/ModDate", "Modified"),
]
_MAX_ANNOT_PAGES = 200


@dataclass
class MetaReport:
    fields: List[Tuple[str, str]] = field(default_factory=list)  # (label, value) shown by name
    other_count: int = 0                                          # further fields not listed
    note: Optional[str] = None                                    # e.g. "Password-protected"

    @property
    def total(self) -> int:
        return len(self.fields) + self.other_count

    @property
    def clean(self) -> bool:
        return self.total == 0 and not self.note


def _clean_text(value, limit=60) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = str(value).replace("\x00", "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _gps_to_decimal(gps) -> Optional[str]:
    try:
        def conv(parts, ref):
            deg, minutes, seconds = (float(p) for p in parts)
            value = deg + minutes / 60 + seconds / 3600
            return -value if ref in ("S", "W") else value
        lat = conv(gps[2], gps[1])
        lon = conv(gps[4], gps[3])
        return f"{lat:.4f}, {lon:.4f}"
    except Exception:
        return None


def _pdf_date(raw: str) -> str:
    text = str(raw)
    if text.startswith("D:") and len(text) >= 10 and text[2:10].isdigit():
        d = text[2:]
        out = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        if len(d) >= 12 and d[8:12].isdigit():
            out += f" {d[8:10]}:{d[10:12]}"
        return out
    return _clean_text(text)


def inspect_image(path: Path) -> MetaReport:
    report = MetaReport()
    with Image.open(path) as img:
        exif = img.getexif()
        shown_tags = set()
        taken = exif.get_ifd(_EXIF_IFD).get(0x9003)
        if taken:
            report.fields.append(("Date taken", _clean_text(taken)))
            shown_tags.add(0x9003)
        for tag, label in _SHOWN_TAGS:
            if exif.get(tag):
                report.fields.append((label, _clean_text(exif[tag])))
                shown_tags.add(tag)
        gps = exif.get_ifd(_GPS_IFD)
        if gps:
            coords = _gps_to_decimal(gps)
            report.fields.append(("GPS location", coords or "present"))
        other = max(0, len([t for t in exif if t not in (_EXIF_IFD, _GPS_IFD)]) - len(
            [t for t in shown_tags if t in exif]))
        other += len(exif.get_ifd(_EXIF_IFD)) - (1 if taken else 0)
        info = img.info
        if info.get("xmp") or info.get("XML:com.adobe.xmp"):
            other += 1
        if info.get("photoshop"):
            other += 1
        if info.get("comment"):
            other += 1
        other += len(getattr(img, "text", {}) or {})
        report.other_count = max(0, other)
    return report


def inspect_pdf(path: Path) -> MetaReport:
    report = MetaReport()
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")
        except Exception:
            ok = 0
        if not ok:
            report.note = "Password-protected: remove the password to process"
            return report
    info = reader.metadata or {}
    for key, label in _PDF_FIELDS:
        value = info.get(key)
        if value:
            text = _pdf_date(value) if "Date" in key else _clean_text(value)
            report.fields.append((label, text))
    other = 0
    if "/Metadata" in reader.trailer["/Root"]:
        other += 1
    authors = 0
    for page in reader.pages[:_MAX_ANNOT_PAGES]:
        for annot in page.get("/Annots") or []:
            annot = annot.get_object()
            if annot.get("/Subtype") in _MARKUP_ANNOTS and annot.get("/T"):
                authors += 1
    if authors:
        report.fields.append(("Comment authors", str(authors)))
    report.other_count = other
    return report


def inspect_file(path) -> MetaReport:
    path = Path(path)
    ext = path.suffix.lower()
    if ext in PDF_EXTENSIONS:
        return inspect_pdf(path)
    if ext in IMAGE_EXTENSIONS:
        return inspect_image(path)
    raise ValueError(f"Unsupported file type: {ext}")


def make_thumbnail(path, size: int = 256) -> Optional[Image.Image]:
    """A small RGB preview for images; None for PDFs and unreadable files."""
    path = Path(path)
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    try:
        with Image.open(path) as img:
            img.draft("RGB", (size * 2, size * 2))  # fast JPEG downscale on decode
            img = ImageOps.exif_transpose(img)
            img.thumbnail((size, size))
            return img.convert("RGB")
    except Exception:
        return None
