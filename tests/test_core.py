from pdfstrip.core import expand_paths, output_path_for, process_file
from pdfstrip.presets import PRESETS


def test_writes_new_file_and_leaves_original(tmp_path, jpeg_with_metadata):
    src = tmp_path / "photo.jpg"
    src.write_bytes(jpeg_with_metadata)
    r = process_file(src, PRESETS["balanced"])
    assert r.ok and r.output == tmp_path / "photo_clean.jpg"
    assert src.read_bytes() == jpeg_with_metadata
    r2 = process_file(src, PRESETS["balanced"])
    assert r2.output == tmp_path / "photo_clean_2.jpg"  # never clobbers earlier output


def test_output_dir(tmp_path, pdf_with_metadata):
    src = tmp_path / "doc.pdf"
    src.write_bytes(pdf_with_metadata)
    r = process_file(src, PRESETS["balanced"], tmp_path / "out")
    assert r.ok and r.output == tmp_path / "out" / "doc_clean.pdf"
    assert r.new_size < r.original_size and r.saved_percent > 0


def test_errors_are_reported_not_raised(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf at all")
    assert not process_file(bad, PRESETS["balanced"]).ok
    txt = tmp_path / "notes.txt"
    txt.write_text("hi")
    assert "Unsupported" in process_file(txt, PRESETS["balanced"]).error


def test_expand_paths_skips_outputs(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    (tmp_path / "a_clean.pdf").write_bytes(b"x")
    (tmp_path / "b.txt").write_bytes(b"x")
    assert expand_paths([tmp_path]) == [tmp_path / "a.pdf"]


def test_output_path_uppercase_ext(tmp_path):
    assert output_path_for(tmp_path / "IMG_1.JPG").name == "IMG_1_clean.JPG"
