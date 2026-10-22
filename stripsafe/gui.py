"""StripSafe desktop window: a sidebar with Process Files, Settings and About views, dark or light."""

import base64
import io
import queue
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

from PIL import ImageOps

from . import __version__, settings as settings_store
from .core import SUPPORTED_EXTENSIONS, Result, expand_paths, human_size, is_supported, process_file
from .metadata import MetaReport, inspect_file, make_thumbnail
from .presets import get_preset
from .ui.theme import PALETTES, make_fonts
from .ui.widgets import Button, Checkbox, Pill, Segmented, Slider, blend, draw_logo, round_rect

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAVE_DND = True
except Exception:  # optional dependency (or its native library) not available
    HAVE_DND = False

# (label, preset name, description) for the quality slider.
QUALITY_STEPS = [
    ("Strip only", "lossless", "Removes metadata, keeps every pixel"),
    ("High quality", "light", "Gentle compression, looks identical"),
    ("Balanced", "balanced", "Good size savings, minor quality loss"),
    ("Smallest", "strong", "Maximum savings for email"),
]
NAV = [("process", "Process Files"), ("settings", "Settings"), ("about", "About")]
COLUMNS = {0: 40, 2: 76, 3: 160, 4: 96, 5: 36}  # queue column widths; column 1 (name) stretches


@dataclass(eq=False)  # compared and hashed by identity
class Item:
    path: Path
    kind: str  # "pdf" or "image"
    size: int
    checked: bool = True
    status: str = "Ready"  # Ready, Working, Done, Failed
    report: Optional[MetaReport] = None
    inspect_error: Optional[str] = None
    thumb: object = None   # PIL image
    result: Optional[Result] = None
    photos: dict = field(default_factory=dict)  # cache of PhotoImage objects by size


class Row:
    """One line of the queue. Widgets are created once and refreshed in place."""

    def __init__(self, app, parent, item):
        self.app, self.item = app, item
        p, f = app.pal, app.fonts
        self.frame = tk.Frame(parent, bg=p.surface)
        self.frame.grid_columnconfigure(1, weight=1)
        for col, w in COLUMNS.items():
            self.frame.grid_columnconfigure(col, minsize=w)
        self.check = Checkbox(self.frame, p, item.checked, self._on_check, bg=p.surface)
        self.check.grid(row=0, column=0, padx=(12, 0), pady=11)
        self.name = tk.Label(self.frame, text=item.path.name, font=f["base"], fg=p.text, bg=p.surface,
                             anchor="w", width=1)
        self.name.grid(row=0, column=1, sticky="ew", padx=(4, 8))
        self.kind_cell = tk.Frame(self.frame, bg=p.surface)
        self.kind_cell.grid(row=0, column=2, sticky="w")
        self.size = tk.Label(self.frame, font=f["small"], fg=p.muted, bg=p.surface, anchor="w")
        self.size.grid(row=0, column=3, sticky="w")
        self.status_cell = tk.Frame(self.frame, bg=p.surface)
        self.status_cell.grid(row=0, column=4, sticky="w")
        self.remove = tk.Label(self.frame, text="✕", font=f["small"], fg=p.muted, bg=p.surface, cursor="hand2")
        self.remove.grid(row=0, column=5)
        self.remove.bind("<Button-1>", lambda e: app.remove_item(item))
        self.pill_kind = None
        self.pill_status = None
        for w in (self.frame, self.name, self.size, self.kind_cell, self.status_cell):
            w.bind("<Button-1>", lambda e: app.select(item))
        self.refresh()

    def _on_check(self, value):
        self.item.checked = value
        self.app.update_queue_chrome()

    def refresh(self):
        p, f, item = self.app.pal, self.app.fonts, self.item
        bg = p.surface2 if self.app.selected is item else p.surface
        for w in (self.frame, self.name, self.size, self.kind_cell, self.status_cell, self.remove):
            w.config(bg=bg)
        self.check.config(bg=bg)
        self.check.set(item.checked)
        self.check.draw()
        if self.pill_kind is None:
            color = p.danger if item.kind == "pdf" else p.accent
            self.pill_kind = Pill(self.kind_cell, "PDF" if item.kind == "pdf" else "Image", color, f["small"], bg)
            self.pill_kind.pack()
        else:
            self.pill_kind.config(bg=bg)
        if item.result and item.result.ok:
            self.size.config(text=f"{human_size(item.size)}  →  {human_size(item.result.new_size)}",
                             fg=p.success)
        else:
            self.size.config(text=human_size(item.size), fg=p.muted)
        if self.pill_status is not None:
            self.pill_status.destroy()
        color = {"Ready": p.muted, "Working": p.accent, "Done": p.success, "Failed": p.danger}[item.status]
        self.pill_status = Pill(self.status_cell, item.status, color, f["small"], bg)
        self.pill_status.pack()
        for w in (self.pill_kind, self.pill_status):
            w.bind("<Button-1>", lambda e: self.app.select(item))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        # Drag-and-drop needs both the package and a root window created by it.
        self.dnd = HAVE_DND and getattr(root, "TkdndVersion", None) is not None
        self.settings = settings_store.load()
        self.pal = PALETTES[self.settings.theme]
        self.fonts = make_fonts(root)
        self.files = []
        self.rows = {}
        self.selected = None
        self.view = "process"
        self.tab = "metadata"
        self.working = False
        self.summary = ""
        self.events = queue.Queue()
        root.title("StripSafe")
        root.geometry("1240x740")
        root.minsize(1120, 640)
        self.build()
        root.after(100, self._poll)

    # ------------------------------------------------------------ layout --
    def build(self):
        """(Re)build the whole window from state. Used at start and when the theme changes."""
        for child in self.root.winfo_children():
            child.destroy()
        self.pal = PALETTES[self.settings.theme]
        p = self.pal
        self.rows = {}
        self.root.config(bg=p.bg)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = tk.Frame(self.root, bg=p.bg)
        self.content.grid(row=0, column=1, sticky="nsew")
        self._show_view()

    def _build_sidebar(self):
        p, f = self.pal, self.fonts
        side = tk.Frame(self.root, bg=p.surface, width=230, highlightbackground=p.border, highlightthickness=0)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        tk.Frame(self.root, bg=p.border, width=1).grid(row=0, column=0, sticky="nse")
        brand = tk.Frame(side, bg=p.surface)
        brand.pack(fill="x", padx=20, pady=(26, 22))
        logo = tk.Canvas(brand, width=34, height=38, bg=p.surface, highlightthickness=0)
        logo.pack(side="left")
        draw_logo(logo, 2, 2, 32, p.accent, p.on_accent)
        names = tk.Frame(brand, bg=p.surface)
        names.pack(side="left", padx=10)
        tk.Label(names, text="StripSafe", font=f["logo"], fg=p.text, bg=p.surface).pack(anchor="w")
        tk.Label(names, text="Clean files. Keep privacy.", font=f["small"], fg=p.muted, bg=p.surface).pack(anchor="w")

        for key, label in NAV:
            active = key == self.view
            row = tk.Frame(side, bg=p.surface2 if active else p.surface, cursor="hand2")
            row.pack(fill="x", padx=12, pady=2)
            bar = tk.Frame(row, bg=p.accent if active else row["bg"], width=3)
            bar.pack(side="left", fill="y", pady=8)
            lbl = tk.Label(row, text=label, font=f["bold"] if active else f["base"], anchor="w",
                           fg=p.text if active else p.muted, bg=row["bg"], padx=14, pady=10)
            lbl.pack(side="left", fill="x", expand=True)
            for w in (row, lbl, bar):
                w.bind("<Button-1>", lambda e, k=key: self.switch_view(k))
            if not active:
                for w in (row, lbl):
                    w.bind("<Enter>", lambda e, r=row, l=lbl: (r.config(bg=p.surface2), l.config(bg=p.surface2)))
                    w.bind("<Leave>", lambda e, r=row, l=lbl: (r.config(bg=p.surface), l.config(bg=p.surface)))

        note = tk.Frame(side, bg=p.bg, highlightbackground=p.border, highlightthickness=1)
        note.pack(side="bottom", fill="x", padx=16, pady=20)
        tk.Label(note, text="100% local", font=f["bold"], fg=p.success, bg=p.bg, anchor="w").pack(
            fill="x", padx=14, pady=(12, 0))
        tk.Label(note, text="Your files never leave this computer. StripSafe makes no network connections.",
                 font=f["small"], fg=p.muted, bg=p.bg, anchor="w", justify="left", wraplength=160).pack(
            fill="x", padx=14, pady=(2, 12))

    def switch_view(self, key):
        if key == self.view:
            return
        self.view = key
        self.build()

    def _show_view(self):
        {"process": self._build_process, "settings": self._build_settings, "about": self._build_about}[self.view]()

    # -------------------------------------------------------- shared bits --
    def _card(self, parent, **pack):
        card = tk.Frame(parent, bg=self.pal.surface, highlightbackground=self.pal.border, highlightthickness=1)
        if pack:
            card.pack(**pack)
        return card

    def _title(self, parent, title, subtitle):
        p, f = self.pal, self.fonts
        tk.Label(parent, text=title, font=f["h1"], fg=p.text, bg=p.bg, anchor="w").pack(fill="x")
        tk.Label(parent, text=subtitle, font=f["base"], fg=p.muted, bg=p.bg, anchor="w").pack(fill="x", pady=(2, 0))

    def _quality_controls(self, parent, bg, on_change=None):
        """Slider plus its label; returns the container frame."""
        p, f = self.pal, self.fonts
        box = tk.Frame(parent, bg=bg)
        tk.Label(box, text="Compression quality", font=f["small"], fg=p.muted, bg=bg, anchor="w").pack(fill="x")
        label = tk.Label(box, font=f["bold"], fg=p.text, bg=bg, anchor="w")

        def changed(idx):
            self.settings.quality = idx
            settings_store.save(self.settings)
            label.config(text=QUALITY_STEPS[idx][0])
            if on_change:
                on_change()

        slider = Slider(box, p, len(QUALITY_STEPS), self.settings.quality, changed, width=160, bg=bg)
        slider.pack(fill="x", pady=(4, 0))
        label.pack(fill="x")
        label.config(text=QUALITY_STEPS[self.settings.quality][0])
        return box

    def _output_controls(self, parent, bg):
        p, f = self.pal, self.fonts
        box = tk.Frame(parent, bg=bg)
        tk.Label(box, text="Output folder", font=f["small"], fg=p.muted, bg=bg, anchor="w").pack(fill="x")
        row = tk.Frame(box, bg=bg)
        row.pack(fill="x", pady=(4, 0))
        self.out_label = tk.Label(row, font=f["base"], fg=p.text, bg=p.surface2, anchor="w", padx=10, pady=7, width=14)
        self.out_label.pack(side="left", fill="x", expand=True)
        Button(row, "Change", self.pick_output, p, f["base"], height=32, bg=bg).pack(side="left", padx=(8, 0))
        self._refresh_out_label()
        return box

    def _refresh_out_label(self):
        text = self.settings.output_dir or "Next to originals"
        if len(text) > 38:
            text = "…" + text[-37:]
        self.out_label.config(text=text)

    def pick_output(self):
        folder = filedialog.askdirectory(title="Save cleaned files in")
        if folder:
            self.settings.output_dir = folder
            settings_store.save(self.settings)
            self._refresh_out_label()

    # ------------------------------------------------------- process view --
    def _build_process(self):
        p, f = self.pal, self.fonts
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_columnconfigure(1, minsize=364)  # detail panel (340) plus its right margin
        self.content.grid_rowconfigure(0, weight=1)
        main = tk.Frame(self.content, bg=p.bg)
        main.grid(row=0, column=0, sticky="nsew", padx=(28, 16), pady=24)
        self.detail_host = tk.Frame(self.content, bg=p.bg, width=340)
        self.detail_host.grid(row=0, column=1, sticky="ns", padx=(0, 24), pady=24)
        self.detail_host.grid_propagate(False)

        self._title(main, "Clean your files", "Remove metadata and shrink images and PDFs, right here on this computer.")

        # Drop zone
        zone = tk.Canvas(main, height=132, bg=p.bg, highlightthickness=0)
        zone.pack(fill="x", pady=(18, 14))
        self.zone = zone
        hint = "Drag & drop files here" if self.dnd else "Add files to get started"
        sub = "Supports JPG, PNG, WebP and PDF"
        btn_add = Button(zone, "+  Add files", self.add_files, p, f["bold"], variant="primary", height=38, bg=p.surface)
        btn_dir = Button(zone, "Add folder", self.add_folder, p, f["base"], height=38, bg=p.surface)

        def draw_zone(_e=None, active=False):
            zone.delete("all")
            w = zone.winfo_width()
            round_rect(zone, 2, 2, w - 2, 130, 14, fill=p.surface, outline=p.accent if active else p.border,
                       dash=(5, 4), width=1.5)
            zone.create_text(w / 2, 30, text=hint, font=f["h2"], fill=p.text)
            zone.create_window(w / 2 - 62, 72, window=btn_add)
            zone.create_window(w / 2 + 62, 72, window=btn_dir)
            zone.create_text(w / 2, 110, text=sub, font=f["small"], fill=p.muted)

        zone.bind("<Configure>", draw_zone)
        if self.dnd:
            self._register_drop(zone, draw_zone)

        # Queue
        queue_card = self._card(main)
        queue_card.pack(fill="both", expand=True)
        head = tk.Frame(queue_card, bg=p.surface)
        head.pack(fill="x", padx=18, pady=(14, 8))
        self.queue_title = tk.Label(head, font=f["h2"], fg=p.text, bg=p.surface)
        self.queue_title.pack(side="left")
        self.summary_label = tk.Label(head, font=f["small"], fg=p.success, bg=p.surface)
        self.summary_label.pack(side="left", padx=14)
        Button(head, "Clear all", self.clear, p, f["small"], variant="ghost", height=28, bg=p.surface).pack(side="right")

        cols = tk.Frame(queue_card, bg=p.surface2)
        cols.pack(fill="x")
        cols.grid_columnconfigure(1, weight=1)
        for col, w in COLUMNS.items():
            cols.grid_columnconfigure(col, minsize=w)
        self.select_all = Checkbox(cols, p, True, self._toggle_all, bg=p.surface2)
        self.select_all.grid(row=0, column=0, padx=(12, 0), pady=8)
        for col, text in ((1, "Name"), (2, "Type"), (3, "Size"), (4, "Status")):
            tk.Label(cols, text=text, font=f["small"], fg=p.muted, bg=p.surface2, anchor="w").grid(
                row=0, column=col, sticky="w", padx=(4, 0) if col == 1 else 0)

        body = tk.Frame(queue_card, bg=p.surface)
        body.pack(fill="both", expand=True)
        self.rows_canvas = tk.Canvas(body, bg=p.surface, highlightthickness=0, height=120)
        self.rows_canvas.pack(fill="both", expand=True)
        self.rows_frame = tk.Frame(self.rows_canvas, bg=p.surface)
        win = self.rows_canvas.create_window(0, 0, window=self.rows_frame, anchor="nw")
        self.rows_canvas.bind("<Configure>", lambda e: self.rows_canvas.itemconfig(win, width=e.width))
        self.rows_frame.bind("<Configure>", lambda e: self.rows_canvas.config(
            scrollregion=self.rows_canvas.bbox("all")))
        self.empty_label = tk.Label(self.rows_canvas, text="No files yet. Add or drop some above.",
                                    font=f["base"], fg=p.muted, bg=p.surface)
        self._bind_wheel(self.rows_canvas)
        if self.dnd:
            self._register_drop(self.rows_canvas)

        # Bottom bar
        bar = self._card(main)
        bar.pack(fill="x", pady=(14, 0))
        inner = tk.Frame(bar, bg=p.surface)
        inner.pack(fill="x", padx=18, pady=14)
        self.go = Button(inner, "Process files", self.start, p, f["bold"], variant="primary", width=140, height=44,
                         bg=p.surface)
        self.go.pack(side="right", padx=(16, 0))  # packed first so it is never squeezed out
        self._quality_controls(inner, p.surface, on_change=self._refresh_detail).pack(side="left", padx=(0, 20))
        self._output_controls(inner, p.surface).pack(side="left", fill="x", expand=True)

        for item in self.files:
            self._make_row(item)
        self.update_queue_chrome()
        self._refresh_detail()

    def _bind_wheel(self, canvas):
        def on_wheel(event):
            if canvas.bbox("all") is None or self.rows_frame.winfo_height() <= canvas.winfo_height():
                return
            delta = -1 if (event.num == 4 or event.delta > 0) else 1
            canvas.yview_scroll(delta * 2, "units")

        def enter(_e):
            canvas.bind_all("<MouseWheel>", on_wheel)
            canvas.bind_all("<Button-4>", on_wheel)
            canvas.bind_all("<Button-5>", on_wheel)

        def leave(_e):
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.unbind_all(ev)

        canvas.bind("<Enter>", enter)
        canvas.bind("<Leave>", leave)

    def _make_row(self, item):
        row = Row(self, self.rows_frame, item)
        row.frame.pack(fill="x")
        tk.Frame(self.rows_frame, bg=self.pal.border, height=1).pack(fill="x")
        self.rows[item] = row
        return row

    def update_queue_chrome(self):
        """Refresh counts, empty state, select-all box and the Process button."""
        if self.view != "process":
            return
        n = len(self.files)
        self.queue_title.config(text=f"Files queue ({n})")
        self.summary_label.config(text=self.summary)
        if n:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        self.select_all.set(bool(self.files) and all(i.checked for i in self.files))
        todo = self._todo()
        self.go.set_text(f"Process files ({len(todo)})" if todo else "Process files")
        self.go.set_enabled(bool(todo) and not self.working)

    def _todo(self):
        return [i for i in self.files if i.checked and i.status in ("Ready", "Failed")]

    # ------------------------------------------------------- file actions --
    def _toggle_all(self, value):
        for item in self.files:
            item.checked = value
            if item in self.rows:
                self.rows[item].refresh()
        self.update_queue_chrome()

    def _register_drop(self, widget, redraw=None):
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            if redraw:
                widget.dnd_bind("<<DropEnter>>", lambda e: (redraw(active=True), e.action)[1])
                widget.dnd_bind("<<DropLeave>>", lambda e: (redraw(), e.action)[1])
        except tk.TclError:
            self.dnd = False  # drop support unavailable on this system; buttons still work

    def _on_drop(self, event):
        self.add_paths(self.root.tk.splitlist(event.data))
        return event.action

    def add_files(self):
        types = [("PDFs and images", " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))), ("All files", "*.*")]
        paths = filedialog.askopenfilenames(title="Choose files", filetypes=types)
        if paths:
            self.add_paths(paths)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Choose a folder")
        if folder:
            self.add_paths([folder])

    def add_paths(self, paths):
        if self.view != "process":
            self.view = "process"
            self.build()
        known = {i.path for i in self.files}
        new = []
        for path in expand_paths(paths):
            path = Path(path)
            if path in known or not is_supported(path) or not path.is_file():
                continue
            known.add(path)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            kind = "pdf" if path.suffix.lower() == ".pdf" else "image"
            item = Item(path, kind, size)
            self.files.append(item)
            self._make_row(item)
            new.append(item)
        self.summary = ""
        self.update_queue_chrome()
        if new:
            if self.selected is None:
                self.select(new[0])
            threading.Thread(target=self._inspect_worker, args=(new,), daemon=True).start()

    def _inspect_worker(self, items):
        for item in items:
            try:
                report = inspect_file(item.path)
                thumb = make_thumbnail(item.path)
                self.events.put(("meta", item, report, thumb, None))
            except Exception as exc:
                self.events.put(("meta", item, None, None, str(exc) or exc.__class__.__name__))

    def remove_item(self, item):
        if self.working and item.status == "Working":
            return
        self.files.remove(item)
        self._rebuild_rows()
        if self.selected is item:
            self.selected = self.files[0] if self.files else None
        self.update_queue_chrome()
        self._refresh_detail()

    def _rebuild_rows(self):
        for child in self.rows_frame.winfo_children():
            child.destroy()
        self.rows = {}
        for item in self.files:
            self._make_row(item)

    def clear(self):
        if self.working:
            return
        self.files.clear()
        self.selected = None
        self.summary = ""
        self._rebuild_rows()
        self.update_queue_chrome()
        self._refresh_detail()

    def select(self, item):
        previous = self.selected
        self.selected = item
        for it in (previous, item):
            if it in self.rows:
                self.rows[it].refresh()
        self._refresh_detail()

    # ------------------------------------------------------- detail panel --
    def _photo(self, item, size):
        """A Tk image of the item's thumbnail. Goes via PNG so Pillow's optional ImageTk isn't needed."""
        if item.thumb is None:
            return None
        if size not in item.photos:
            img = ImageOps.fit(item.thumb, (size, size)) if size <= 64 else item.thumb.copy()
            if size > 64:
                img.thumbnail((size, size))
            buf = io.BytesIO()
            img.save(buf, "PNG")
            item.photos[size] = tk.PhotoImage(master=self.root, data=base64.b64encode(buf.getvalue()))
        return item.photos[size]

    def _refresh_detail(self):
        if self.view != "process":
            return
        for child in self.detail_host.winfo_children():
            child.destroy()
        p, f, item = self.pal, self.fonts, self.selected
        card = self._card(self.detail_host, fill="x")
        if item is None:
            tk.Label(card, text="Select a file to see what private data it contains.", font=f["base"], fg=p.muted,
                     bg=p.surface, wraplength=280, justify="left").pack(padx=20, pady=40)
            return

        head = tk.Frame(card, bg=p.surface)
        head.pack(fill="x", padx=18, pady=(18, 10))
        photo = self._photo(item, 56)
        if photo:
            tk.Label(head, image=photo, bg=p.surface, bd=0).pack(side="left")
        else:
            icon = tk.Canvas(head, width=56, height=56, bg=p.surface, highlightthickness=0)
            round_rect(icon, 0, 0, 56, 56, 12, fill=blend(p.surface, p.danger if item.kind == "pdf" else p.accent, .15),
                       outline="")
            icon.create_text(28, 28, text="PDF" if item.kind == "pdf" else "IMG", font=f["bold"],
                             fill=p.danger if item.kind == "pdf" else p.accent)
            icon.pack(side="left")
        info = tk.Frame(head, bg=p.surface)
        info.pack(side="left", padx=12, fill="x", expand=True)
        tk.Label(info, text=item.path.name, font=f["bold"], fg=p.text, bg=p.surface, anchor="w", width=1).pack(fill="x")
        tk.Label(info, text=human_size(item.size), font=f["small"], fg=p.muted, bg=p.surface, anchor="w").pack(fill="x")

        tabs = tk.Frame(card, bg=p.surface)
        tabs.pack(fill="x", padx=18)
        for key, label in (("metadata", "Metadata found"), ("preview", "Preview")):
            active = self.tab == key
            cell = tk.Frame(tabs, bg=p.surface, cursor="hand2")
            cell.pack(side="left", padx=(0, 18))
            tk.Label(cell, text=label, font=f["bold"] if active else f["base"], bg=p.surface,
                     fg=p.text if active else p.muted).pack()
            tk.Frame(cell, bg=p.accent if active else p.surface, height=2).pack(fill="x", pady=(4, 0))
            for w in [cell] + cell.winfo_children():
                w.bind("<Button-1>", lambda e, k=key: self._set_tab(k))
        tk.Frame(card, bg=p.border, height=1).pack(fill="x")

        body = tk.Frame(card, bg=p.surface)
        body.pack(fill="x", padx=18, pady=12)
        if self.tab == "preview":
            self._detail_preview(body, item)
        else:
            self._detail_metadata(body, item)

        # Size card
        size_card = self._card(self.detail_host, fill="x", pady=(14, 0))
        tk.Label(size_card, text="Size after processing", font=f["bold"], fg=p.text, bg=p.surface, anchor="w").pack(
            fill="x", padx=18, pady=(14, 8))
        row = tk.Frame(size_card, bg=p.surface)
        row.pack(fill="x", padx=18, pady=(0, 16))
        self._size_box(row, "Original", human_size(item.size), p.text)
        tk.Label(row, text="→", font=f["h2"], fg=p.muted, bg=p.surface).pack(side="left", padx=8)
        if item.result and item.result.ok:
            saved = item.result.saved_percent
            self._size_box(row, "After", human_size(item.result.new_size), p.success,
                           f"{saved:.0f}% smaller" if saved > 0 else "no size change")
        else:
            self._size_box(row, "After", "—", p.muted, QUALITY_STEPS[self.settings.quality][0])
        if item.status == "Failed" and item.result is not None and item.result.error:
            tk.Label(size_card, text=item.result.error, font=f["small"], fg=p.danger, bg=p.surface, wraplength=290,
                     justify="left", anchor="w").pack(fill="x", padx=18, pady=(0, 14))

    def _size_box(self, parent, title, value, color, caption=None):
        p, f = self.pal, self.fonts
        box = tk.Frame(parent, bg=p.surface2)
        box.pack(side="left", fill="both", expand=True)
        tk.Label(box, text=title, font=f["small"], fg=p.muted, bg=p.surface2, anchor="w").pack(
            fill="x", padx=12, pady=(10, 0))
        tk.Label(box, text=value, font=f["h2"], fg=color, bg=p.surface2, anchor="w").pack(fill="x", padx=12)
        tk.Label(box, text=caption or " ", font=f["small"], fg=p.muted, bg=p.surface2, anchor="w").pack(
            fill="x", padx=12, pady=(0, 10))

    def _set_tab(self, key):
        self.tab = key
        self._refresh_detail()

    def _detail_metadata(self, body, item):
        p, f = self.pal, self.fonts
        if item.report is None:
            text = item.inspect_error or "Reading metadata…"
            tk.Label(body, text=text, font=f["base"], fg=p.danger if item.inspect_error else p.muted, bg=p.surface,
                     anchor="w", wraplength=290, justify="left").pack(fill="x", pady=8)
            return
        report = item.report
        if report.note:
            tk.Label(body, text=report.note, font=f["base"], fg=p.danger, bg=p.surface, anchor="w",
                     wraplength=290, justify="left").pack(fill="x", pady=8)
            return
        if report.clean:
            tk.Label(body, text="No identifying metadata found.", font=f["base"], fg=p.success, bg=p.surface,
                     anchor="w").pack(fill="x", pady=8)
            return
        for label, value in report.fields:
            line = tk.Frame(body, bg=p.surface)
            line.pack(fill="x", pady=3)
            tk.Label(line, text=label, font=f["base"], fg=p.muted, bg=p.surface, anchor="w").pack(side="left")
            tk.Label(line, text=value, font=f["base"], fg=p.text, bg=p.surface, anchor="e", justify="right",
                     wraplength=170).pack(side="right")
        if report.other_count:
            line = tk.Frame(body, bg=p.surface)
            line.pack(fill="x", pady=3)
            tk.Label(line, text="Other (EXIF, IPTC, XMP)", font=f["base"], fg=p.muted, bg=p.surface).pack(side="left")
            tk.Label(line, text=f"{report.other_count} more", font=f["base"], fg=p.text, bg=p.surface).pack(side="right")
        removed = "Removed after processing." if item.status == "Done" else "This metadata will be removed."
        tag = tk.Label(body, text=removed, font=f["small"], bg=blend(p.surface, p.success if item.status == "Done"
                                                                     else p.danger, .14),
                       fg=p.success if item.status == "Done" else p.danger, padx=10, pady=5)
        tag.pack(anchor="w", pady=(12, 0))

    def _detail_preview(self, body, item):
        p, f = self.pal, self.fonts
        photo = self._photo(item, 260)
        if photo:
            tk.Label(body, image=photo, bg=p.surface, bd=0).pack(pady=4)
        else:
            text = "PDF previews are not shown." if item.kind == "pdf" else "Preview unavailable."
            tk.Label(body, text=text, font=f["base"], fg=p.muted, bg=p.surface).pack(pady=24)

    # --------------------------------------------------------- processing --
    def start(self):
        todo = self._todo()
        if self.working or not todo:
            return
        _label, preset_name, _desc = QUALITY_STEPS[self.settings.quality]
        preset = get_preset(preset_name)
        out = self.settings.output_dir
        if out and not Path(out).exists():
            try:
                Path(out).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror("StripSafe", f"Can't use that output folder:\n{exc}")
                return
        self.working = True
        self.summary = ""
        for item in todo:
            item.status, item.result = "Ready", None
        self.update_queue_chrome()
        threading.Thread(target=self._worker, args=(todo, preset, out), daemon=True).start()

    def _worker(self, items, preset, out):
        for item in items:
            self.events.put(("start", item))
            self.events.put(("done", item, process_file(item.path, preset, out)))
        self.events.put(("finished", None))

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "meta":
                    _, item, report, thumb, error = event
                    item.report, item.thumb, item.inspect_error = report, thumb, error
                    if item is self.selected:
                        self._refresh_detail()
                elif kind == "start":
                    event[1].status = "Working"
                    self._refresh_row(event[1])
                elif kind == "done":
                    _, item, result = event
                    item.result, item.status = result, "Done" if result.ok else "Failed"
                    self._refresh_row(item)
                    if item is self.selected:
                        self._refresh_detail()
                else:
                    self._finish()
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _refresh_row(self, item):
        if self.view == "process" and item in self.rows:
            self.rows[item].refresh()

    def _finish(self):
        self.working = False
        done = [i for i in self.files if i.result and i.result.ok]
        failed = [i for i in self.files if i.status == "Failed"]
        saved = sum(i.result.original_size - i.result.new_size for i in done)
        parts = []
        if done:
            parts.append(f"{len(done)} cleaned" + (f", saved {human_size(saved)}" if saved > 0 else ""))
        if failed:
            parts.append(f"{len(failed)} failed")
        self.summary = " · ".join(parts)
        self.update_queue_chrome()

    # ------------------------------------------------------ settings view --
    def _build_settings(self):
        p, f = self.pal, self.fonts
        page = tk.Frame(self.content, bg=p.bg)
        page.pack(fill="both", expand=True, padx=32, pady=28)
        self._title(page, "Settings", "Your choices are saved on this computer only.")

        card = self._card(page, fill="x", pady=(20, 0))
        self._setting_row(card, "Appearance", "Switch between the dark and light theme.").pack(fill="x")
        row = card.winfo_children()[-1]
        Segmented(row, p, f["base"], [("dark", "Dark"), ("light", "Light")], self.settings.theme,
                  self._set_theme).pack(side="right", padx=20)

        card2 = self._card(page, fill="x", pady=(14, 0))
        row = self._setting_row(card2, "Default compression", "Used for every batch you process.")
        row.pack(fill="x")
        self._quality_controls(row, p.surface).pack(side="right", padx=20, pady=12)

        card3 = self._card(page, fill="x", pady=(14, 0))
        row = self._setting_row(card3, "Output folder", "Cleaned copies are saved here. Originals are never changed.")
        row.pack(fill="x")
        right = tk.Frame(row, bg=p.surface)
        right.pack(side="right", padx=20, pady=12)
        self._output_controls(right, p.surface).pack()
        Button(right, "Save next to originals", self._reset_output, p, f["small"], variant="ghost", height=28,
               bg=p.surface).pack(anchor="e", pady=(4, 0))

    def _setting_row(self, card, title, subtitle):
        p, f = self.pal, self.fonts
        row = tk.Frame(card, bg=p.surface)
        left = tk.Frame(row, bg=p.surface)
        left.pack(side="left", padx=20, pady=16)
        tk.Label(left, text=title, font=f["bold"], fg=p.text, bg=p.surface, anchor="w").pack(fill="x")
        tk.Label(left, text=subtitle, font=f["small"], fg=p.muted, bg=p.surface, anchor="w").pack(fill="x")
        row.pack(fill="x")
        return row

    def _set_theme(self, theme):
        self.settings.theme = theme
        settings_store.save(self.settings)
        self.build()

    def _reset_output(self):
        self.settings.output_dir = None
        settings_store.save(self.settings)
        self._refresh_out_label()

    # --------------------------------------------------------- about view --
    def _build_about(self):
        p, f = self.pal, self.fonts
        page = tk.Frame(self.content, bg=p.bg)
        page.pack(fill="both", expand=True, padx=32, pady=28)
        self._title(page, "About StripSafe", f"Version {__version__}")
        card = self._card(page, fill="x", pady=(20, 0))
        blocks = [
            ("What it does",
             "Removes hidden personal data from PDFs and images (author names, GPS location, camera details, "
             "timestamps, editing history) and compresses them so they are easy to email."),
            ("Private by design",
             "Everything happens on this computer. StripSafe never connects to the internet and never uploads "
             "your files. Cleaned copies are saved as new files, so your originals are never changed."),
            ("Supported files", "PDF, JPG, PNG and WebP."),
            ("Good to know",
             "Text and pictures you can see on the page are not altered. Password-protected PDFs need their "
             "password removed first."),
            ("License", "Free software under the GNU GPL v3."),
        ]
        for title, text in blocks:
            tk.Label(card, text=title, font=f["bold"], fg=p.text, bg=p.surface, anchor="w").pack(
                fill="x", padx=22, pady=(16, 0))
            tk.Label(card, text=text, font=f["base"], fg=p.muted, bg=p.surface, anchor="w", justify="left",
                     wraplength=640).pack(fill="x", padx=22, pady=(2, 0))
        tk.Frame(card, bg=p.surface, height=16).pack()


def main(argv=None) -> int:
    try:
        root = TkinterDnD.Tk() if HAVE_DND else tk.Tk()
    except Exception:  # tkdnd's native library failed to load: run without drag-and-drop
        root = tk.Tk()
    app = App(root)
    if argv:
        app.add_paths(argv)
    root.mainloop()
    return 0
