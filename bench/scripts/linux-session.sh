#!/usr/bin/env bash
# Start a headless Linux desktop for the local smoke suite: Xvfb, openbox (a
# window manager, so foreground input can activate windows), a D-Bus session
# bus and the AT-SPI bus, with GTK accessibility on. Upstream's Linux e2e runs
# the same stack. Prints the env
# to `eval`:   eval "$(bash bench/scripts/linux-session.sh)"
# Stop it with: kill $DOVE_BENCH_SESSION_PIDS
set -euo pipefail

display="${DOVE_BENCH_DISPLAY:-:77}"
setsid Xvfb "$display" -screen 0 1280x800x24 -nolisten tcp >/dev/null 2>&1 < /dev/null &
xvfb_pid=$!
for _ in $(seq 50); do
  [ -e "/tmp/.X11-unix/X${display#:}" ] && break
  sleep 0.1
done

eval "$(dbus-launch --sh-syntax)"
export DISPLAY="$display" GTK_MODULES=gail:atk-bridge NO_AT_BRIDGE=0 GNOME_ACCESSIBILITY=1 QT_ACCESSIBILITY=1
launcher=""
for c in /usr/libexec/at-spi-bus-launcher /usr/lib/at-spi2-core/at-spi-bus-launcher; do
  [ -x "$c" ] && launcher="$c" && break
done
[ -n "$launcher" ] || { echo "at-spi-bus-launcher not found (install at-spi2-core)" >&2; exit 1; }
setsid "$launcher" --launch-immediately >/dev/null 2>&1 < /dev/null &
spi_pid=$!
if command -v openbox >/dev/null; then
  setsid openbox >/dev/null 2>&1 < /dev/null &
  wm_pid=$!
else
  echo "openbox not found: foreground input will be refused (no _NET_ACTIVE_WINDOW)" >&2
  wm_pid=""
fi
sleep 0.5
gsettings set org.gnome.desktop.interface toolkit-accessibility true 2>/dev/null || true

cat <<EOF
export DISPLAY=$DISPLAY
export DBUS_SESSION_BUS_ADDRESS='$DBUS_SESSION_BUS_ADDRESS'
export GTK_MODULES=gail:atk-bridge NO_AT_BRIDGE=0 GNOME_ACCESSIBILITY=1 QT_ACCESSIBILITY=1
export DOVE_BENCH_SESSION_PIDS='$xvfb_pid $DBUS_SESSION_BUS_PID $spi_pid $wm_pid'
EOF
