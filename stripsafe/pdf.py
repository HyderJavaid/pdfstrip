"""Strip tracking metadata from PDFs and shrink them, using pypdf."""

import io
import os
import zlib

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    StreamObject,
)

from .presets import Preset

PDF_EXTENSIONS = {".pdf"}

# Keys that carry authoring/editing history wherever they appear.
_TRACKING_KEYS = ("/Metadata", "/PieceInfo", "/LastModified")
# Annotation types whose /T is the comment author's name. Form widgets are
# excluded because there /T is the field name and removing it breaks the form.
_MARKUP_ANNOTS = {
    "/Text", "/FreeText", "/Line", "/Square", "/Circle", "/Polygon", "/PolyLine",
    "/Highlight", "/Underline", "/Squiggly", "/StrikeOut", "/Stamp", "/Caret",
    "/Ink", "/FileAttachment", "/Sound", "/Redact",
}


class PdfPasswordError(ValueError):
    pass


def _strip_metadata(writer: PdfWriter) -> None:
    writer.metadata = None  # drops the /Info dictionary (Author, Creator, Producer, dates...)
    root = writer._root_object
    for key in _TRACKING_KEYS:
        root.pop(NameObject(key), None)
    for obj in writer._objects:
        if obj is None:
            continue
        obj = obj.get_object()
        if not isinstance(obj, DictionaryObject):
            continue
        for key in _TRACKING_KEYS:
            obj.pop(NameObject(key), None)
        if "/Rect" in obj and obj.get("/Subtype") in _MARKUP_ANNOTS:
            obj.pop(NameObject("/T"), None)
    # A fresh random file ID so the output can't be matched to the original.
    writer._ID = ArrayObject([ByteStringObject(os.urandom(16)), ByteStringObject(os.urandom(16))])


def _encoded_length(xobj) -> int:
    data = getattr(xobj, "_data", None)
    return len(data) if data is not None else 0


def _recompress_image(xobj: StreamObject, pil_image: Image.Image, preset: Preset) -> bool:
    """Re-encode one image XObject as JPEG if that makes it smaller. Returns True if replaced."""
    # Masks, stencils and unusual colour setups don't survive a JPEG round trip.
    if any(k in xobj for k in ("/SMask", "/Mask", "/ImageMask", "/Decode")):
        return False
    if xobj.get("/BitsPerComponent", 8) != 8:
        return False
    if pil_image.mode not in ("RGB", "L"):
        return False
    img = pil_image
    if preset.max_dimension and max(img.size) > preset.max_dimension:
        img = img.copy()
        img.thumbnail((preset.max_dimension, preset.max_dimension), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=preset.jpeg_quality, optimize=True)
    jpeg = buf.getvalue()
    if len(jpeg) >= _encoded_length(xobj):
        return False
    for key in ("/DecodeParms", "/Filter", "/Length", "/ColorSpace", "/Intent"):
        xobj.pop(NameObject(key), None)
    xobj[NameObject("/Filter")] = NameObject("/DCTDecode")
    xobj[NameObject("/Width")] = NumberObject(img.width)
    xobj[NameObject("/Height")] = NumberObject(img.height)
    xobj[NameObject("/BitsPerComponent")] = NumberObject(8)
    xobj[NameObject("/ColorSpace")] = NameObject("/DeviceRGB" if img.mode == "RGB" else "/DeviceGray")
    xobj._data = jpeg
    if hasattr(xobj, "decoded_self"):
        xobj.decoded_self = None
    return True


def _compress_images(writer: PdfWriter, preset: Preset) -> None:
    seen = set()
    for page in writer.pages:
        try:
            images = list(page.images)
        except Exception:
            continue
        for image_file in images:
            ref = image_file.indirect_reference
            if ref is None or ref.idnum in seen:
                continue  # inline images, or already handled via another page
            seen.add(ref.idnum)
            try:
                _recompress_image(ref.get_object(), image_file.image, preset)
            except Exception:
                continue  # leave any image we can't decode untouched


def _flate_uncompressed_streams(writer: PdfWriter) -> None:
    """Losslessly Flate-compress any stream stored without a filter."""
    for obj in writer._objects:
        if obj is None:
            continue
        obj = obj.get_object()
        if isinstance(obj, StreamObject) and "/Filter" not in obj and getattr(obj, "_data", None):
            if obj.get("/Type") == "/XRef":
                continue
            compressed = zlib.compress(obj._data, 9)
            if len(compressed) < len(obj._data):
                obj._data = compressed
                obj[NameObject("/Filter")] = NameObject("/FlateDecode")


def process_pdf(data: bytes, preset: Preset) -> bytes:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")
        except Exception:
            ok = 0
        if not ok:
            raise PdfPasswordError("PDF is password-protected; remove the password first")
    writer = PdfWriter(clone_from=reader)

    _strip_metadata(writer)
    if preset.jpeg_quality is not None:
        _compress_images(writer, preset)
    for page in writer.pages:
        try:
            page.compress_content_streams(level=9)
        except Exception:
            pass
    _flate_uncompressed_streams(writer)
    writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
