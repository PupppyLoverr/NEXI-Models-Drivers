"""A small GTK3 form for the daemon test (tests/daemon.rs): an Email
field, Save and Cancel buttons, a Remember me check box and a status
label that says what was last done. Run with the system Python that has
PyGObject (python3-gi, gir1.2-gtk-3.0) inside an AT-SPI session."""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

win = Gtk.Window(title="Grounder Demo")
win.set_default_size(420, 220)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
win.add(box)
email = Gtk.Entry()
email.get_accessible().set_name("Email")
box.pack_start(email, False, False, 0)
remember = Gtk.CheckButton(label="Remember me")
box.pack_start(remember, False, False, 0)
row = Gtk.Box(spacing=8)
save = Gtk.Button(label="Save")
cancel = Gtk.Button(label="Cancel")
row.pack_start(save, False, False, 0)
row.pack_start(cancel, False, False, 0)
box.pack_start(row, False, False, 0)
status = Gtk.Label(label="ready")
box.pack_start(status, False, False, 0)
save.connect("clicked", lambda _b: status.set_text(f"saved:{email.get_text()}"))
cancel.connect("clicked", lambda _b: status.set_text("cancelled"))
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
