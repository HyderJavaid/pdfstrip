"""tkinter front end. Drag-and-drop works when tkinterdnd2 is installed; otherwise use the buttons."""

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .core import SUPPORTED_EXTENSIONS, expand_paths, human_size, is_supported, process_file
from .presets import DEFAULT_PRESET, PRESETS, get_preset

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAVE_DND = True
except Exception:  # optional dependency (or its native library) not available
    HAVE_DND = False

_FILETYPES = [
    ("PDFs and images", " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))),
    ("All files", "*.*"),
]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.files = []
        self.output_dir = None
        self.events = queue.Queue()
        self.working = False
        root.title("pdfstrip - private document cleaner")
        root.minsize(640, 460)
        self._build()
        root.after(100, self._poll)

    def _build(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        hint = ("Drop PDFs or images here" if HAVE_DND else "Click Add files... to choose PDFs or images")
        self.drop = tk.Label(frame, text=f"{hint}\nEverything stays on this computer.",
                             relief="groove", bd=2, height=4, cursor="hand2")
        self.drop.pack(fill="x")
        self.drop.bind("<Button-1>", lambda e: self.add_files())
        if HAVE_DND:
            self.drop.drop_target_register(DND_FILES)
            self.drop.dnd_bind("<<Drop>>", self._on_drop)

        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=8)
        ttk.Button(bar, text="Add files...", command=self.add_files).pack(side="left")
        ttk.Button(bar, text="Add folder...", command=self.add_folder).pack(side="left", padx=4)
        ttk.Button(bar, text="Clear", command=self.clear).pack(side="left")

        opts = ttk.Frame(frame)
        opts.pack(fill="x")
        ttk.Label(opts, text="Compression:").pack(side="left")
        self.preset_var = tk.StringVar(value=PRESETS[DEFAULT_PRESET].label)
        self.preset_box = ttk.Combobox(opts, state="readonly", width=26, textvariable=self.preset_var,
                                       values=[p.label for p in PRESETS.values()])
        self.preset_box.pack(side="left", padx=6)
        self.out_label = ttk.Label(opts, text="Save next to originals")
        ttk.Button(opts, text="Output folder...", command=self.pick_output).pack(side="right")
        self.out_label.pack(side="right", padx=6)

        cols = ("file", "status", "before", "after", "saved")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        for col, text, width in (("file", "File", 280), ("status", "Status", 150),
                                 ("before", "Before", 80), ("after", "After", 80), ("saved", "Saved", 70)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w" if col in ("file", "status") else "e")
        self.tree.pack(fill="both", expand=True, pady=8)

        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.pack(fill="x")
        self.go = ttk.Button(frame, text="Strip metadata and compress", command=self.start)
        self.go.pack(pady=(8, 0))
        ttk.Label(frame, text="Originals are never modified; cleaned copies are saved as name_clean.ext",
                  foreground="gray").pack(pady=(6, 0))

    # -- file list ---------------------------------------------------------
    def _add(self, paths):
        for path in expand_paths(paths):
            path = Path(path)
            if not is_supported(path) or path in self.files:
                continue
            self.files.append(path)
            self.tree.insert("", "end", iid=str(path), values=(path.name, "Queued", "", "", ""))

    def _on_drop(self, event):
        self._add(self.root.tk.splitlist(event.data))

    def add_files(self):
        self._add(filedialog.askopenfilenames(title="Choose files", filetypes=_FILETYPES))

    def add_folder(self):
        folder = filedialog.askdirectory(title="Choose a folder")
        if folder:
            self._add([folder])

    def clear(self):
        if not self.working:
            self.files.clear()
            self.tree.delete(*self.tree.get_children())
            self.progress["value"] = 0

    def pick_output(self):
        folder = filedialog.askdirectory(title="Save cleaned files in")
        self.output_dir = folder or None
        self.out_label.config(text=f"Save to {folder}" if folder else "Save next to originals")

    # -- processing --------------------------------------------------------
    def start(self):
        if self.working:
            return
        pending = [f for f in self.files if self.tree.set(str(f), "status") in ("Queued", "Failed")]
        if not pending:
            messagebox.showinfo("pdfstrip", "Add some PDFs or images first.")
            return
        preset = next(p for p in PRESETS.values() if p.label == self.preset_var.get())
        self.working = True
        self.go.state(["disabled"])
        self.progress.config(maximum=len(pending), value=0)
        threading.Thread(target=self._worker, args=(pending, get_preset(preset.name), self.output_dir),
                         daemon=True).start()

    def _worker(self, files, preset, output_dir):
        for f in files:
            self.events.put(("start", f))
            self.events.put(("done", process_file(f, preset, output_dir)))
        self.events.put(("finished", None))

    def _poll(self):
        try:
            while True:
                kind, item = self.events.get_nowait()
                if kind == "start":
                    self.tree.set(str(item), "status", "Working...")
                elif kind == "done":
                    self._show_result(item)
                    self.progress.step(1)
                else:
                    self.working = False
                    self.go.state(["!disabled"])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _show_result(self, r):
        iid = str(r.source)
        if r.ok:
            self.tree.item(iid, values=(r.source.name, f"Saved {r.output.name}", human_size(r.original_size),
                                        human_size(r.new_size), f"{r.saved_percent:.0f}%"))
        else:
            self.tree.item(iid, values=(r.source.name, "Failed", human_size(r.original_size), "", ""))
            self.tree.set(iid, "file", f"{r.source.name}  ({r.error})")


def main(argv=None) -> int:
    root = TkinterDnD.Tk() if HAVE_DND else tk.Tk()
    app = App(root)
    if argv:
        app._add(argv)
    root.mainloop()
    return 0
