import io

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject, DictionaryObject, FloatObject, NameObject, StreamObject, TextStringObject,
)

GPS_IFD = 0x8825
XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description creator="Jane Secret"/></rdf:RDF></x:xmpmeta>'


def noisy_image(w=1600, h=1200, mode="RGB"):
    """A photo-like image (gradient + noise) so compression behaves realistically."""
    import random
    random.seed(1)
    img = Image.radial_gradient("L").resize((w, h))
    noise = Image.effect_noise((w, h), 40)
    base = Image.merge("RGB", (img, noise, Image.linear_gradient("L").resize((w, h))))
    return base.convert(mode)


@pytest.fixture
def jpeg_with_metadata():
    img = noisy_image(1600, 1200)
    exif = Image.Exif()
    exif[0x010F] = "SpyCam Inc"            # Make
    exif[0x0110] = "Model X"               # Model
    exif[0x013B] = "Jane Secret"           # Artist
    exif[0x0112] = 6                       # Orientation: rotate 90 CW to display
    gps = exif.get_ifd(GPS_IFD)
    gps[1] = "N"
    gps[2] = (51.0, 30.0, 12.0)
    gps[3] = "W"
    gps[4] = (0.0, 7.0, 39.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95, exif=exif, comment=b"secret comment", xmp=XMP)
    return buf.getvalue()


@pytest.fixture
def png_with_metadata():
    from PIL import PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Jane Secret")
    info.add_itxt("XML:com.adobe.xmp", XMP.decode())
    exif = Image.Exif()
    exif[0x013B] = "Jane Secret"
    buf = io.BytesIO()
    noisy_image(400, 300).save(buf, "PNG", pnginfo=info, exif=exif)
    return buf.getvalue()


@pytest.fixture
def pdf_with_metadata():
    """A PDF with Info metadata, XMP, a big uncompressed image, and an authored comment."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    img = noisy_image(2400, 1800)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pageCompression=0)
    c.setAuthor("Jane Secret")
    c.setTitle("Tax return 2025")
    c.setSubject("Private")
    c.setCreator("SecretWriter 9")
    c.drawString(72, 750, "Hello, this is a private document.")
    c.drawImage(ImageReader(img), 72, 300, width=400, height=300)
    c.showPage()
    c.drawString(72, 750, "Page two.")
    c.drawImage(ImageReader(img), 72, 300, width=400, height=300)  # same image again
    c.showPage()
    c.save()

    writer = PdfWriter(clone_from=io.BytesIO(buf.getvalue()))
    xmp = StreamObject()
    xmp._data = XMP
    xmp.update({NameObject("/Type"): NameObject("/Metadata"), NameObject("/Subtype"): NameObject("/XML")})
    writer._root_object[NameObject("/Metadata")] = writer._add_object(xmp)
    annot = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Text"),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (100, 100, 120, 120)]),
        NameObject("/T"): TextStringObject("Jane Secret"),
        NameObject("/Contents"): TextStringObject("Check this figure"),
    })
    writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(annot)])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
