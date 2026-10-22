from pypdf import PdfReader  # noqa: F401  (ensures pypdf import path works in tests)

from stripsafe.metadata import inspect_file, make_thumbnail
from stripsafe.settings import Settings, load, save


def test_image_report(tmp_path, jpeg_with_metadata):
    p = tmp_path / "x.jpg"
    p.write_bytes(jpeg_with_metadata)
    report = inspect_file(p)
    fields = dict(report.fields)
    assert fields["Camera make"] == "SpyCam Inc"
    assert fields["Author"] == "Jane Secret"
    assert fields["GPS location"] == "51.5033, -0.1275"
    assert report.other_count >= 2  # XMP and the comment
    assert not report.clean


def test_clean_image_reports_nothing(tmp_path):
    from PIL import Image
    p = tmp_path / "c.jpg"
    Image.new("RGB", (20, 20), "red").save(p)
    assert inspect_file(p).clean


def test_pdf_report(tmp_path, pdf_with_metadata):
    p = tmp_path / "d.pdf"
    p.write_bytes(pdf_with_metadata)
    report = inspect_file(p)
    fields = dict(report.fields)
    assert fields["Author"] == "Jane Secret"
    assert fields["Title"] == "Tax return 2025"
    assert fields["Comment authors"] == "1"
    assert report.other_count >= 1  # XMP stream


def test_thumbnail(tmp_path, jpeg_with_metadata):
    p = tmp_path / "x.jpg"
    p.write_bytes(jpeg_with_metadata)
    thumb = make_thumbnail(p, 100)
    assert thumb is not None and max(thumb.size) <= 100
    assert make_thumbnail(tmp_path / "d.pdf") is None


def test_settings_roundtrip_and_bad_file(tmp_path):
    p = tmp_path / "s" / "settings.json"
    save(Settings(theme="light", quality=3, output_dir="/tmp/out"), p)
    s = load(p)
    assert (s.theme, s.quality, s.output_dir) == ("light", 3, "/tmp/out")
    p.write_text("{not json")
    assert load(p) == Settings()
    p.write_text('{"theme": "neon", "quality": 99}')
    assert (load(p).theme, load(p).quality) == ("dark", 3)
