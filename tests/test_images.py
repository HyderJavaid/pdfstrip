import io

import pytest
from PIL import Image

from pdfstrip.images import process_image, strip_jpeg_lossless
from pdfstrip.presets import PRESETS

from .conftest import GPS_IFD

SECRETS = (b"Jane Secret", b"SpyCam", b"secret comment", b"xmpmeta", b"Model X")


def assert_no_secrets(data):
    for s in SECRETS:
        assert s not in data, s


@pytest.mark.parametrize("preset", list(PRESETS))
def test_jpeg_metadata_removed(jpeg_with_metadata, preset):
    out = process_image(jpeg_with_metadata, ".jpg", PRESETS[preset])
    assert_no_secrets(out)
    with Image.open(io.BytesIO(out)) as img:
        img.load()
        exif = img.getexif()
        assert GPS_IFD not in exif and not exif.get_ifd(GPS_IFD)
        assert 0x013B not in exif and 0x010F not in exif
        assert "comment" not in img.info and "xmp" not in img.info


def test_lossless_keeps_pixels_and_orientation(jpeg_with_metadata):
    out = process_image(jpeg_with_metadata, ".jpg", PRESETS["lossless"])
    with Image.open(io.BytesIO(jpeg_with_metadata)) as a, Image.open(io.BytesIO(out)) as b:
        assert a.tobytes() == b.tobytes()  # pixel data untouched
        assert b.getexif().get(0x0112) == 6  # still displays upright
        assert len(b.getexif()) == 1  # and orientation is the only tag left


def test_compressed_jpeg_is_smaller_and_upright(jpeg_with_metadata):
    out = process_image(jpeg_with_metadata, ".jpg", PRESETS["balanced"])
    assert len(out) < len(jpeg_with_metadata)
    with Image.open(io.BytesIO(out)) as img:
        # Orientation 6 was baked into the pixels, so the image is now portrait.
        assert img.height > img.width
        assert img.getexif().get(0x0112, 1) == 1


def test_strong_downscales(jpeg_with_metadata):
    out = process_image(jpeg_with_metadata, ".jpg", PRESETS["strong"])
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) <= 1400


def test_lossless_strip_drops_trailing_data(jpeg_with_metadata):
    out = strip_jpeg_lossless(jpeg_with_metadata + b"HIDDEN-PAYLOAD")
    assert out.endswith(b"\xff\xd9") and b"HIDDEN-PAYLOAD" not in out


def test_progressive_jpeg_lossless():
    from .conftest import noisy_image
    buf = io.BytesIO()
    noisy_image(300, 200).save(buf, "JPEG", progressive=True, comment=b"secret comment")
    out = strip_jpeg_lossless(buf.getvalue())
    assert b"secret comment" not in out
    with Image.open(io.BytesIO(buf.getvalue())) as a, Image.open(io.BytesIO(out)) as b:
        assert a.tobytes() == b.tobytes()


@pytest.mark.parametrize("preset", ["lossless", "balanced"])
def test_png_metadata_removed(png_with_metadata, preset):
    out = process_image(png_with_metadata, ".png", PRESETS[preset])
    assert_no_secrets(out)
    with Image.open(io.BytesIO(out)) as img:
        assert not img.text
        assert not img.getexif()


def test_webp_metadata_removed(jpeg_with_metadata):
    with Image.open(io.BytesIO(jpeg_with_metadata)) as img:
        buf = io.BytesIO()
        img.save(buf, "WEBP", exif=img.info["exif"], xmp=img.info["xmp"])
    out = process_image(buf.getvalue(), ".webp", PRESETS["balanced"])
    assert_no_secrets(out)
    assert b"EXIF" not in out and b"XMP " not in out
