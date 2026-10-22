import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    from PySide6.QtWidgets import QApplication

    from stripsafe import gui
    QApplication.instance() or QApplication([])
    win = gui.MainWindow()
    win.show()
    yield win
    win.close()  # shuts the worker pool down


def pump(cond, timeout=90):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    end = time.time() + timeout
    while time.time() < end and not cond():
        app.processEvents()
        time.sleep(0.01)
    assert cond()


def test_process_selected_files_only(window, tmp_path, jpeg_with_metadata):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    a.write_bytes(jpeg_with_metadata)
    b.write_bytes(jpeg_with_metadata)
    window.add_paths([a, b, tmp_path / "ignored.txt"])
    items = window.model.items
    assert len(items) == 2
    pump(lambda: all(i.report for i in items))
    assert dict(items[0].report.fields)["Camera make"] == "SpyCam Inc"
    window._toggle_item(items[1])  # untick b
    window.start()
    pump(lambda: not window.working)
    assert items[0].status == "Done" and items[1].status == "Ready"
    assert (tmp_path / "a_clean.jpg").exists() and not (tmp_path / "b_clean.jpg").exists()
    assert "1 cleaned" in window.summary


def test_failed_file_is_reported(window, tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    window.add_paths([bad])
    window.start()
    pump(lambda: not window.working)
    item = window.model.items[0]
    assert item.status == "Failed" and item.result.error
    assert "1 failed" in window.summary


def test_remove_clear_and_dedupe(window, tmp_path, jpeg_with_metadata):
    a = tmp_path / "a.jpg"
    a.write_bytes(jpeg_with_metadata)
    window.add_paths([a, a])
    window.add_paths([a])
    assert len(window.model.items) == 1
    window.remove_item(window.model.items[0])
    assert window.model.items == [] and window.selected is None
    window.add_paths([a])
    window.clear()
    assert window.model.items == []


def test_theme_and_settings_persist(window):
    from stripsafe import settings
    window.set_theme("light")
    window.set_quality(3)
    assert window.pal.name == "light"
    saved = settings.load()
    assert (saved.theme, saved.quality) == ("light", 3)
    assert window.quality.slider.value() == window.quality2.slider.value() == 3
    window.set_theme("dark")
    assert settings.load().theme == "dark"
    for index in range(3):
        window.stack.setCurrentIndex(index)
        window.grab()


def test_window_renders_with_files(window, tmp_path, jpeg_with_metadata, pdf_with_metadata):
    (tmp_path / "a.jpg").write_bytes(jpeg_with_metadata)
    (tmp_path / "d.pdf").write_bytes(pdf_with_metadata)
    window.add_paths([tmp_path])
    pump(lambda: all(i.report for i in window.model.items))
    for row in range(2):
        window.table.selectRow(row)
        for tab in ("preview", "metadata"):
            window.detail._set_tab(tab)
    assert not window.grab().isNull()
