#!/usr/bin/env bash
# Run a command in a virtual X11 desktop: Xvfb, a private D-Bus session (which
# activates AT-SPI), openbox and picom, as upstream's canonical X11 lane does.
#
#   ci/dove/linux/x11-session.sh <command> [args...]
#
# Needs xvfb, dbus-x11, at-spi2-core, openbox and picom (apt-deps.sh x11).
set -euo pipefail
(($#)) || { echo "usage: x11-session.sh <command> [args...]" >&2; exit 2; }
artifacts="${DOVE_CI_ARTIFACTS:-$PWD/artifacts/linux-x11}"
mkdir -p "$artifacts"
export DOVE_CI_X11_LOGS="$artifacts"
exec xvfb-run -a --server-args="-screen 0 1920x1080x24" \
  dbus-run-session -- bash -c '
    export NO_AT_BRIDGE=0 ACCESSIBILITY_ENABLED=1 GDK_BACKEND=x11
    openbox > "$DOVE_CI_X11_LOGS/openbox.log" 2>&1 &
    picom --backend xrender --config /dev/null > "$DOVE_CI_X11_LOGS/picom.log" 2>&1 &
    sleep 2
    exec "$@"
  ' x11-session "$@"
