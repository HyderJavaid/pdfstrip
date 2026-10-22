"""Strip EXIF/GPS/XMP/IPTC metadata from images and optionally recompress them."""

import io
import struct

from PIL import Image, ImageOps

from .presets import Preset

JPEG_EXTENSIONS = {".jpg", ".jpeg", ".jpe", ".jfif"}
PNG_EXTENSIONS = {".png"}
WEBP_EXTENSIONS = {".webp"}
IMAGE_EXTENSIONS = JPEG_EXTENSIONS | PNG_EXTENSIONS | WEBP_EXTENSIONS

_SOI = b"\xff\xd8"
_EOI = 0xD9
_SOS = 0xDA
_COM = 0xFE
_APP0 = 0xE0
_APP2 = 0xE2
_APP14 = 0xEE
_ORIENTATION_TAG = 0x0112
# Markers that stand alone with no length field.
_STANDALONE = {0x01} | set(range(0xD0, 0xD8))


def _keep_jpeg_segment(marker: int, payload: bytes) -> bool:
    """Decide whether a JPEG header segment is safe (non-identifying) to keep."""
    if marker == _APP0:
        return payload.startswith(b"JFIF\x00")  # drops JFXX thumbnails
    if marker == _APP2:
        return payload.startswith(b"ICC_PROFILE\x00")  # drops MPF/FlashPix
    if marker == _APP14:
        return payload.startswith(b"Adobe")  # needed to decode CMYK/YCCK correctly
    if 0xE1 <= marker <= 0xEF or marker == _COM:
        return False  # EXIF, XMP, IPTC/Photoshop, comments, vendor blocks
    return True  # structural segments: DQT, DHT, SOFn, DRI, ...


def _orientation_segment(orientation: int) -> bytes:
    exif = Image.Exif()
    exif[_ORIENTATION_TAG] = orientation
    data = exif.tobytes()
    if not data.startswith(b"Exif\x00\x00"):
        data = b"Exif\x00\x00" + data
    return b"\xff\xe1" + struct.pack(">H", len(data) + 2) + data


def strip_jpeg_lossless(data: bytes, keep_orientation: int = 1) -> bytes:
    """Remove metadata segments from a JPEG without re-encoding the pixels.

    If ``keep_orientation`` is not 1, a minimal EXIF block holding only the
    orientation tag is written back so the photo still displays upright.
    """
    if not data.startswith(_SOI):
        raise ValueError("Not a JPEG file")
    out = bytearray(_SOI)
    if keep_orientation not in (0, 1):
        out += _orientation_segment(keep_orientation)
    pos = 2
    n = len(data)
    while pos < n:
        if data[pos] != 0xFF:
            raise ValueError("Corrupt JPEG: expected marker")
        while pos < n and data[pos] == 0xFF:  # skip fill bytes
            pos += 1
        if pos >= n:
            break
        marker = data[pos]
        pos += 1
        if marker in _STANDALONE:
            out += bytes((0xFF, marker))
            continue
        if marker == _EOI:
            out += b"\xff\xd9"
            return bytes(out)  # anything after EOI (e.g. hidden previews) is dropped
        (length,) = struct.unpack(">H", data[pos:pos + 2])
        segment = data[pos:pos + length]
        payload = segment[2:]
        if marker == _SOS:
            # Entropy-coded data runs to the EOI marker; copy it verbatim.
            out += bytes((0xFF, marker)) + segment
            end = _find_eoi(data, pos + length)
            out += data[pos + length:end] + b"\xff\xd9"
            return bytes(out)
        if _keep_jpeg_segment(marker, payload):
            out += bytes((0xFF, marker)) + segment
        pos += length
    raise ValueError("Corrupt JPEG: missing image data")


def _find_eoi(data: bytes, start: int) -> int:
    """Find the EOI marker that ends the scan data.

    Inside entropy-coded data a literal 0xFF is always followed by a stuffed 0x00,
    so the first 0xFF 0xD9 pair is the real end. Progressive JPEGs have several
    scans (and DHT segments between them); those are copied as part of the run.
    """
    end = data.find(b"\xff\xd9", start)
    return len(data) if end < 0 else end


def _downscale(img: Image.Image, max_dimension):
    if max_dimension and max(img.size) > max_dimension:
        img = img.copy()
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
    return img


def _clean_copy(img: Image.Image) -> Image.Image:
    """A copy of the pixels with every metadata field dropped (ICC profile kept)."""
    clean = img.copy()
    icc = img.info.get("icc_profile")
    clean.info = {"icc_profile": icc} if icc else {}
    return clean


def _encode_jpeg(img: Image.Image, preset: Preset) -> bytes:
    img = ImageOps.exif_transpose(img)  # bake rotation in before EXIF is dropped
    img = _downscale(img, preset.max_dimension)
    if img.mode not in ("RGB", "L", "CMYK"):
        img = img.convert("RGB")
    clean = _clean_copy(img)
    buf = io.BytesIO()
    kwargs = {"quality": preset.jpeg_quality, "optimize": True, "progressive": True}
    if clean.info.get("icc_profile"):
        kwargs["icc_profile"] = clean.info["icc_profile"]
    clean.save(buf, "JPEG", **kwargs)
    return buf.getvalue()


def process_jpeg(data: bytes, preset: Preset) -> bytes:
    with Image.open(io.BytesIO(data)) as img:
        orientation = img.getexif().get(_ORIENTATION_TAG, 1)
        lossless = strip_jpeg_lossless(data, keep_orientation=orientation)
        if preset.jpeg_quality is None:
            return lossless
        compressed = _encode_jpeg(img, preset)
    # Never hand back a bigger file than the lossless strip would.
    return compressed if len(compressed) < len(lossless) else lossless


def process_png(data: bytes, preset: Preset) -> bytes:
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        img = ImageOps.exif_transpose(img)
        if preset.max_dimension:
            img = _downscale(img, preset.max_dimension)
        clean = _clean_copy(img)
        kwargs = {"optimize": True}
        if clean.info.get("icc_profile"):
            kwargs["icc_profile"] = clean.info["icc_profile"]
        if "transparency" in img.info:
            kwargs["transparency"] = img.info["transparency"]
        buf = io.BytesIO()
        clean.save(buf, "PNG", **kwargs)
    return buf.getvalue()


def process_webp(data: bytes, preset: Preset) -> bytes:
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        img = ImageOps.exif_transpose(img)
        img = _downscale(img, preset.max_dimension)
        clean = _clean_copy(img)
        kwargs = {"exif": b"", "xmp": b""}
        if preset.jpeg_quality is None:
            kwargs["lossless"] = True
        else:
            kwargs["quality"] = preset.jpeg_quality
        if clean.info.get("icc_profile"):
            kwargs["icc_profile"] = clean.info["icc_profile"]
        buf = io.BytesIO()
        clean.save(buf, "WEBP", **kwargs)
    return buf.getvalue()


def process_image(data: bytes, ext: str, preset: Preset) -> bytes:
    ext = ext.lower()
    if ext in JPEG_EXTENSIONS:
        return process_jpeg(data, preset)
    if ext in PNG_EXTENSIONS:
        return process_png(data, preset)
    if ext in WEBP_EXTENSIONS:
        return process_webp(data, preset)
    raise ValueError(f"Unsupported image type: {ext}")
