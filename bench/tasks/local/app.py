#!/usr/bin/env python3
"""Tiny GTK3 task windows for the local smoke suite (Xvfb + AT-SPI).

    app.py <form> <state.json> [<oracle.json>]

Every change rewrites <state.json>, which the suite's checker reads. The
optional <oracle.json> holds each named widget's screen centre; only the
scripted stub model reads it, to act in the screenshot-only configuration
without a vision model. Real models never see it.
"""

import json
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

FORM, STATE, ORACLE = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else None)


class TaskWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=f"Dove Bench – {FORM}")
        self.set_default_size(420, 320)
        self.move(40, 40)
        self.state = {"form": FORM}
        self.named: dict[str, Gtk.Widget] = {}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(16)
        self.add(box)
        getattr(self, "build_" + FORM)(box)
        self.connect("destroy", Gtk.main_quit)
        self.save()

    def name(self, widget, label):
        widget.get_accessible().set_name(label)
        self.named[label] = widget
        return widget

    def entry(self, box, label):
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label=label, xalign=0, width_chars=12), False, False, 0)
        e = self.name(Gtk.Entry(), label)
        row.pack_start(e, True, True, 0)
        box.pack_start(row, False, False, 0)
        return e

    def button(self, box, label, cb):
        b = self.name(Gtk.Button(label=label), label)
        b.connect("clicked", cb)
        box.pack_start(b, False, False, 0)
        return b

    def save(self):
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, STATE)

    # rename: type a name, press Save.
    def build_rename(self, box):
        self.name_entry = self.entry(box, "Name")
        self.status = Gtk.Label(label="saved=", xalign=0)
        self.button(box, "Save", self.on_rename_save)
        box.pack_start(self.status, False, False, 0)

    def on_rename_save(self, _):
        self.state["saved_name"] = self.name_entry.get_text()
        self.status.set_text("saved=" + self.state["saved_name"])
        self.save()

    # prefs: tick a check box, pick a combo entry, press Apply.
    def build_prefs(self, box):
        self.notify = self.name(Gtk.CheckButton(label="Enable notifications"), "Enable notifications")
        box.pack_start(self.notify, False, False, 0)
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label="Theme", xalign=0, width_chars=12), False, False, 0)
        self.theme = self.name(Gtk.ComboBoxText(), "Theme")
        for t in ("Light", "Dark", "System"):
            self.theme.append_text(t)
        self.theme.set_active(0)
        row.pack_start(self.theme, True, True, 0)
        box.pack_start(row, False, False, 0)
        self.button(box, "Apply", self.on_prefs_apply)

    def on_prefs_apply(self, _):
        self.state["applied"] = {"notifications": self.notify.get_active(), "theme": self.theme.get_active_text()}
        self.save()

    # counter: press Increment exactly three times.
    def build_counter(self, box):
        self.count = 0
        self.count_label = self.name(Gtk.Label(label="count=0", xalign=0), "count=0")
        box.pack_start(self.count_label, False, False, 0)
        self.button(box, "Increment", self.on_increment)
        self.state["count"] = 0

    def on_increment(self, _):
        self.count += 1
        self.count_label.set_text(f"count={self.count}")
        self.state["count"] = self.count
        self.save()

    # signup: fill three fields, press Submit.
    def build_signup(self, box):
        self.fields = {k: self.entry(box, k) for k in ("First name", "Last name", "Email")}
        self.button(box, "Submit", self.on_submit)

    def on_submit(self, _):
        self.state["submitted"] = {k: e.get_text() for k, e in self.fields.items()}
        self.save()


def write_oracle(win):
    if not ORACLE:
        return False
    gdk = win.get_window()
    if gdk is None:
        return True
    ox, oy = gdk.get_origin()[1:]
    out = {}
    for label, w in win.named.items():
        xy = w.translate_coordinates(win, 0, 0)  # (x, y), or None when unrealized
        a = w.get_allocation()
        if xy and len(xy) >= 2:
            x, y = xy[-2], xy[-1]
            out[label] = {"x": ox + x + a.width // 2, "y": oy + y + a.height // 2}
    with open(ORACLE, "w") as f:
        json.dump(out, f)
    return False


if __name__ == "__main__":
    w = TaskWindow()
    w.show_all()
    GLib.timeout_add(500, write_oracle, w)
    Gtk.main()
