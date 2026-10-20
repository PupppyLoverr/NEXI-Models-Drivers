#!/usr/bin/env bash
# Run a command inside one Xvfb X11 session with a private D-Bus session bus,
# an active AT-SPI registry, openbox and picom.
#
#   ci/dove/linux/x11-session.sh <command> [args...]
#
# The environment of upstream's canonical Linux lanes (trycua/cua
# .github/workflows/e2e-rust-linux.yml, MIT): xvfb-run at 1920x1080x24,
# dbus-run-session, openbox as window manager and picom as compositor. Needs
# xvfb, dbus, at-spi2-core, libglib2.0-bin (gdbus), openbox and picom. Logs go
# to $DOVE_CI_ARTIFACTS (default ./artifacts/linux-x11).
set -euo pipefail
(($#)) || { echo "usage: x11-session.sh <command> [args...]" >&2; exit 2; }

if [[ "${DOVE_X11_SESSION_INNER:-}" != 1 ]]; then
  artifacts="${DOVE_CI_ARTIFACTS:-$PWD/artifacts/linux-x11}"
  mkdir -p "$artifacts"
  unset WAYLAND_DISPLAY
  export DOVE_X11_SESSION_INNER=1 DOVE_CI_ARTIFACTS="$artifacts"
  exec xvfb-run -a --server-args="-screen 0 1920x1080x24" \
    dbus-run-session -- bash "${BASH_SOURCE[0]}" "$@"
fi

wm_pid=""
compositor_pid=""
cleanup() {
  for pid in "$compositor_pid" "$wm_pid"; do
    [[ -n "$pid" ]] && { kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; }
  done
}
trap cleanup EXIT

export XDG_SESSION_TYPE=x11
export GDK_BACKEND=x11 NO_AT_BRIDGE=0 ACCESSIBILITY_ENABLED=1
export CUA_E2E_COMPOSITOR="${CUA_E2E_COMPOSITOR:-openbox-x11}"
export CUA_E2E_INPUT_BACKENDS="${CUA_E2E_INPUT_BACKENDS:-atspi,xsend-event,xtest}"

wait_for() {  # wait_for <seconds> <description> <command...>
  local seconds="$1" what="$2"; shift 2
  local deadline=$((SECONDS + seconds))
  until "$@" >/dev/null 2>&1; do
    ((SECONDS < deadline)) || { echo "$what did not become ready within ${seconds}s" >&2; return 1; }
    sleep 0.2
  done
}

# at-spi2-core makes org.a11y.Bus D-Bus activatable on the session bus.
wait_for 15 "org.a11y.Bus" gdbus call --session --dest org.a11y.Bus \
  --object-path /org/a11y/bus --method org.a11y.Bus.GetAddress
gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus \
  --method org.freedesktop.DBus.Properties.Set org.a11y.Status IsEnabled '<true>' >/dev/null
a11y_address="$(gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus \
  --method org.a11y.Bus.GetAddress | sed -e "s/^('//" -e "s/',)$//")"
wait_for 15 "AT-SPI registry" gdbus call --address "$a11y_address" \
  --dest org.a11y.atspi.Registry --object-path /org/a11y/atspi/accessible/root \
  --method org.freedesktop.DBus.Properties.Get org.a11y.atspi.Accessible ChildCount

openbox > "$DOVE_CI_ARTIFACTS/openbox.log" 2>&1 &
wm_pid=$!
picom --backend xrender --config /dev/null > "$DOVE_CI_ARTIFACTS/picom.log" 2>&1 &
compositor_pid=$!
wm_ready() { xprop -root _NET_SUPPORTING_WM_CHECK | grep -q 'window id'; }
wait_for 10 "openbox" wm_ready

echo "X11 session on $DISPLAY (openbox, picom), AT-SPI at $a11y_address"
set +e
"$@"
status=$?
set -e
exit "$status"
