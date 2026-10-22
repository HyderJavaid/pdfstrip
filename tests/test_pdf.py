import io

import pytest
from pypdf import PdfReader, PdfWriter

from pdfstrip.pdf import PdfPasswordError, process_pdf
from pdfstrip.presets import PRESETS


@pytest.mark.parametrize("preset", list(PRESETS))
def test_pdf_metadata_removed(pdf_with_metadata, preset):
    before = PdfReader(io.BytesIO(pdf_with_metadata))
    assert before.metadata.author == "Jane Secret"
    assert "/Metadata" in before.trailer["/Root"]

    out = process_pdf(pdf_with_metadata, PRESETS[preset])
    reader = PdfReader(io.BytesIO(out))
    assert not reader.metadata  # Info dictionary gone
    assert "/Metadata" not in reader.trailer["/Root"]
    assert reader.trailer["/ID"] != before.trailer["/ID"]
    # Nothing identifying anywhere in the file, even in unreferenced objects.
    for secret in (b"Jane Secret", b"Tax return", b"SecretWriter", b"xmpmeta"):
        assert secret not in out
    # The document itself is intact.
    assert len(reader.pages) == 2
    assert "private document" in reader.pages[0].extract_text()
    annot = reader.pages[0]["/Annots"][0].get_object()
    assert annot["/Contents"] == "Check this figure" and "/T" not in annot


def test_pdf_shrinks(pdf_with_metadata):
    lossless = process_pdf(pdf_with_metadata, PRESETS["lossless"])
    balanced = process_pdf(pdf_with_metadata, PRESETS["balanced"])
    assert len(lossless) < len(pdf_with_metadata)
    assert len(balanced) < len(lossless)
    img = PdfReader(io.BytesIO(balanced)).pages[0].images[0]
    assert max(img.image.size) <= 2000


def test_form_field_names_kept():
    w = PdfWriter()
    w.add_blank_page(200, 200)
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject
    field = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject("/Tx"),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (10, 10, 100, 30)]),
        NameObject("/T"): TextStringObject("full_name"),
    })
    ref = w._add_object(field)
    w.pages[0][NameObject("/Annots")] = ArrayObject([ref])
    w._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): ArrayObject([ref])})
    buf = io.BytesIO()
    w.write(buf)
    out = PdfReader(io.BytesIO(process_pdf(buf.getvalue(), PRESETS["balanced"])))
    assert "full_name" in out.get_fields()


def test_password_protected_pdf_rejected(pdf_with_metadata):
    w = PdfWriter(clone_from=io.BytesIO(pdf_with_metadata))
    w.encrypt("hunter2")
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(PdfPasswordError):
        process_pdf(buf.getvalue(), PRESETS["balanced"])
