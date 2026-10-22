"""Small canvas-drawn widgets so the look is identical on Linux and Windows and follows the theme."""

import tkinter as tk


def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def blend(c1: str, c2: str, t: float) -> str:
    """Mix two #RRGGBB colours; t=0 gives c1, t=1 gives c2."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


class Button(tk.Canvas):
    """Rounded button. variant: primary (filled), secondary (outlined), ghost (text only)."""

    def __init__(self, parent, text, command, pal, font, variant="secondary", width=None, height=36, bg=None):
        self.pal, self.text, self.command, self.variant = pal, text, command, variant
        self.font, self.enabled, self.hover = font, True, False
        w = width or font.measure(text) + 36
        super().__init__(parent, width=w, height=height, bg=bg or pal.surface,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)

    def _set_hover(self, value):
        self.hover = value
        self.draw()

    def _click(self, event):
        if self.enabled and 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.command()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.config(cursor="hand2" if enabled else "arrow")
        self.draw()

    def set_text(self, text):
        self.text = text
        self.draw()

    def draw(self):
        self.delete("all")
        w, h, p = self.winfo_width(), self.winfo_height(), self.pal
        if w < 4:
            return
        if self.variant == "primary":
            fill = p.accent_hover if (self.hover and self.enabled) else p.accent
            if not self.enabled:
                fill = blend(p.surface, p.accent, 0.35)
            round_rect(self, 1, 1, w - 1, h - 1, 10, fill=fill, outline=fill)
            color = p.on_accent
        elif self.variant == "secondary":
            fill = p.surface2 if self.hover and self.enabled else p.surface
            round_rect(self, 1, 1, w - 1, h - 1, 10, fill=fill, outline=p.border)
            color = p.text if self.enabled else p.muted
        else:
            if self.hover and self.enabled:
                round_rect(self, 1, 1, w - 1, h - 1, 8, fill=p.surface2, outline=p.surface2)
            color = p.muted if not self.hover else p.text
        self.create_text(w / 2, h / 2, text=self.text, fill=color, font=self.font)


class Checkbox(tk.Canvas):
    def __init__(self, parent, pal, checked, command, bg=None, size=18):
        super().__init__(parent, width=size, height=size, bg=bg or pal.surface,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.pal, self.checked, self.command, self.size = pal, checked, command, size
        self.bind("<Button-1>", self._toggle)
        self.draw()

    def _toggle(self, _event):
        self.set(not self.checked)
        self.command(self.checked)
        return "break"

    def set(self, checked):
        self.checked = checked
        self.draw()

    def draw(self):
        self.delete("all")
        s, p = self.size, self.pal
        if self.checked:
            round_rect(self, 1, 1, s - 1, s - 1, 5, fill=p.accent, outline=p.accent)
            self.create_line(s * .27, s * .52, s * .43, s * .68, s * .74, s * .33,
                             fill=p.on_accent, width=2, capstyle="round", joinstyle="round")
        else:
            round_rect(self, 1, 1, s - 1, s - 1, 5, fill=self["bg"], outline=p.muted)


class Slider(tk.Canvas):
    """Discrete slider with `steps` positions."""

    def __init__(self, parent, pal, steps, value, command, width=190, bg=None):
        super().__init__(parent, width=width, height=26, bg=bg or pal.surface, highlightthickness=0, bd=0,
                         cursor="hand2")
        self.pal, self.steps, self.value, self.command = pal, steps, value, command
        self.pad = 10
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Configure>", lambda e: self.draw())

    def _x(self, i):
        w = self.winfo_width()
        return self.pad + (w - 2 * self.pad) * i / (self.steps - 1)

    def _drag(self, event):
        w = self.winfo_width()
        frac = min(1, max(0, (event.x - self.pad) / max(1, w - 2 * self.pad)))
        idx = round(frac * (self.steps - 1))
        if idx != self.value:
            self.value = idx
            self.draw()
            self.command(idx)

    def draw(self):
        self.delete("all")
        p, y = self.pal, 13
        if self.winfo_width() < 4:
            return
        self.create_line(self.pad, y, self.winfo_width() - self.pad, y, fill=p.border, width=4, capstyle="round")
        self.create_line(self.pad, y, self._x(self.value), y, fill=p.accent, width=4, capstyle="round")
        for i in range(self.steps):
            if i != self.value:
                self.create_oval(self._x(i) - 2, y - 2, self._x(i) + 2, y + 2,
                                 fill=p.accent if i < self.value else p.muted, outline="")
        x = self._x(self.value)
        self.create_oval(x - 8, y - 8, x + 8, y + 8, fill=p.accent, outline=p.bg, width=2)


class Pill(tk.Canvas):
    """Small rounded label, e.g. file type or status."""

    def __init__(self, parent, text, color, font, bg, tint=0.15):
        w, h = font.measure(text) + 18, font.metrics("linespace") + 8
        super().__init__(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
        round_rect(self, 0, 0, w, h, h / 2, fill=blend(bg, color, tint), outline="")
        self.create_text(w / 2, h / 2, text=text, fill=color, font=font)


class Segmented(tk.Frame):
    """Two-or-more option selector used for the theme switch."""

    def __init__(self, parent, pal, font, options, value, command, bg=None):
        super().__init__(parent, bg=bg or pal.surface)
        self.buttons = {}
        for key, label in options:
            btn = Button(self, label, lambda k=key: (self.select(k), command(k)), pal, font,
                         variant="primary" if key == value else "secondary", width=96, bg=self["bg"])
            btn.pack(side="left", padx=(0, 6))
            self.buttons[key] = btn

    def select(self, value):
        for key, btn in self.buttons.items():
            btn.variant = "primary" if key == value else "secondary"
            btn.draw()


def draw_logo(canvas, x, y, size, color, inner):
    """A shield with a check mark."""
    s = size
    pts = [x + s * .5, y, x + s * .92, y + s * .15, x + s * .92, y + s * .5,
           x + s * .5, y + s, x + s * .08, y + s * .5, x + s * .08, y + s * .15]
    canvas.create_polygon(pts, fill=color, outline=color, smooth=False, joinstyle="round", width=3)
    canvas.create_line(x + s * .3, y + s * .5, x + s * .45, y + s * .64, x + s * .72, y + s * .34,
                       fill=inner, width=max(2, s // 9), capstyle="round", joinstyle="round")
