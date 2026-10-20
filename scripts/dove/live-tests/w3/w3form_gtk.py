#!/usr/bin/env python3
"""Throwaway GTK3 app for the W3 run_steps live test on Linux (the twin of
w3form.ps1 on Windows).

  Main "W3 Batch Test": button "Open details", label "Result: none".
  "Open details" shows "W3 Details" after 800 ms. Its three text boxes
  (Name, Email, Phone) enable after another 1000 ms. "Submit" stays disabled
  until all three are filled, then slides in for ~600 ms. Submit writes
  "Result: Saved <name> / <email> / <phone>" and closes the dialog.
  "Close" closes the dialog.

usage: python3 w3form_gtk.py [exit-after-seconds]
"""
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

FIELDS = ("Name", "Email", "Phone")


class App:
    def __init__(self):
        self.main = Gtk.Window(title="W3 Batch Test")
        self.main.set_default_size(420, 160)
        self.main.move(40, 40)
        self.main.connect("destroy", Gtk.main_quit)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        opener = Gtk.Button(label="Open details")
        opener.connect("clicked", self.open_later)
        box.pack_start(opener, False, False, 0)
        self.result = Gtk.Label(label="Result: none", xalign=0)
        box.pack_start(self.result, False, False, 0)
        self.main.add(box)
        self.main.show_all()
        self.details = None
        self.pending = False

    def open_later(self, _button):
        if self.details is None and not self.pending:
            self.pending = True
            GLib.timeout_add(800, self.open_details)

    def open_details(self):
        self.pending = False
        win = Gtk.Window(title="W3 Details")
        win.set_default_size(420, 240)
        win.move(500, 40)
        win.set_transient_for(self.main)
        grid = Gtk.Fixed()
        self.entries = []
        for nth, name in enumerate(FIELDS):
            label = Gtk.Label(label=name)
            grid.put(label, 12, 16 + 36 * nth)
            entry = Gtk.Entry()
            entry.get_accessible().set_name(name)
            entry.set_sensitive(False)
            entry.connect("changed", self.on_changed)
            grid.put(entry, 90, 10 + 36 * nth)
            self.entries.append(entry)
        self.hint = Gtk.Label(label="Fill in all fields")
        grid.put(self.hint, 12, 124)
        self.submit = Gtk.Button(label="Submit")
        self.submit.set_sensitive(False)
        self.submit.connect("clicked", self.on_submit)
        self.submit_x = 12
        grid.put(self.submit, self.submit_x, 160)
        close = Gtk.Button(label="Close")
        close.connect("clicked", lambda _b: self.close_details())
        grid.put(close, 300, 160)
        self.fixed = grid
        win.add(grid)
        win.connect("delete-event", lambda *_: self.close_details() or True)
        win.show_all()
        self.details = win
        GLib.timeout_add(1000, self.enable_fields)
        return False

    def enable_fields(self):
        if self.details is not None:
            for entry in self.entries:
                entry.set_sensitive(True)
        return False

    def on_changed(self, _entry):
        filled = all(entry.get_text() for entry in self.entries)
        if filled and not self.submit.get_sensitive():
            self.submit.set_sensitive(True)
            self.slide_steps = 12
            self.submit_x = 12 + 15 * self.slide_steps
            self.fixed.move(self.submit, self.submit_x, 160)
            GLib.timeout_add(50, self.slide)
        elif not filled:
            self.submit.set_sensitive(False)

    def slide(self):
        if self.details is None or self.slide_steps <= 0:
            return False
        self.slide_steps -= 1
        self.submit_x = 12 + 15 * self.slide_steps
        self.fixed.move(self.submit, self.submit_x, 160)
        return self.slide_steps > 0

    def on_submit(self, _button):
        values = [entry.get_text() for entry in self.entries]
        self.result.set_text("Result: Saved " + " / ".join(values))
        self.close_details()

    def close_details(self):
        if self.details is not None:
            self.details.destroy()
            self.details = None


if __name__ == "__main__":
    App()
    if len(sys.argv) > 1:
        GLib.timeout_add_seconds(int(sys.argv[1]), Gtk.main_quit)
    Gtk.main()
