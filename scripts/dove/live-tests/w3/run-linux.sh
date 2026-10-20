#!/usr/bin/env bash
# Run the W3 live test on Linux in a throwaway X session: Xvfb, a private
# D-Bus session with the AT-SPI bus, and openbox (window listing needs a
# window manager). Needs xvfb, dbus, at-spi2-core, openbox, python3-gi and
# gir1.2-gtk-3.0.
#
# usage: run-linux.sh <dove-driver> <out.json>
set -euo pipefail
driver="$(realpath "$1")"
out="$(realpath -m "$2")"
here="$(cd "$(dirname "$0")" && pwd)"
home="$(mktemp -d)"
display=":${W3_DISPLAY:-77}"
# The GTK app needs a python whose version matches the installed python3-gi.
for candidate in python3 python3.12 python3.11 python3.13; do
  if "$candidate" -c 'import gi' 2>/dev/null; then export W3_PYTHON="$candidate"; break; fi
done

Xvfb "$display" -screen 0 1280x800x24 -nolisten tcp >"$home/xvfb.log" 2>&1 &
xvfb=$!
trap 'kill $xvfb 2>/dev/null || true' EXIT
for _ in $(seq 50); do [ -e "/tmp/.X11-unix/X${display#:}" ] && break; sleep 0.1; done

DISPLAY="$display" GTK_A11Y=atspi NO_AT_BRIDGE=0 dbus-run-session -- bash -c '
  set -euo pipefail
  /usr/libexec/at-spi-bus-launcher --launch-immediately >"$1/atspi.log" 2>&1 &
  openbox >"$1/openbox.log" 2>&1 &
  sleep 1
  gsettings set org.gnome.desktop.interface toolkit-accessibility true 2>/dev/null || true
  python3 -I "$2/w3live.py" "$3" "$1" "$4"
' _ "$home" "$here" "$driver" "$out"
echo "logs in $home"
