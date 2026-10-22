import time

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    from stripsafe import gui
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    app = gui.App(root)
    yield app
    app.pool.shutdown()
    root.destroy()


def pump(app, cond, timeout=60):
    end = time.time() + timeout
    while time.time() < end and not cond():
        app.root.update()
        time.sleep(0.02)
    assert cond()


def test_process_selected_files_and_switch_theme(app, tmp_path, jpeg_with_metadata):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    a.write_bytes(jpeg_with_metadata)
    b.write_bytes(jpeg_with_metadata)
    app.add_paths([a, b, tmp_path / "ignored.txt"])
    assert len(app.files) == 2
    pump(app, lambda: all(i.report for i in app.files))
    app.files[1].checked = False
    app.start()
    pump(app, lambda: not app.working)
    assert app.files[0].status == "Done" and app.files[1].status == "Ready"
    assert (tmp_path / "a_clean.jpg").exists() and not (tmp_path / "b_clean.jpg").exists()
    for theme in ("light", "dark"):
        app._set_theme(theme)
        app.root.update()
    for view in ("settings", "about", "process"):
        app.switch_view(view)
        app.root.update()
    assert len(app.files) == 2 and app.settings.theme == "dark"
