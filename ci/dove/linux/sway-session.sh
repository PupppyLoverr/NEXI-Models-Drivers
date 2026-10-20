#!/usr/bin/env bash
# Run a command inside one native, headless Sway session with a private
# D-Bus session bus and an active AT-SPI registry.
#
#   ci/dove/linux/sway-session.sh <command> [args...]
#
# Ported from upstream's scripts/ci/linux/run-rust-e2e-wayland.sh (trycua/cua,
# MIT), without the cua-compositor and Secret Service parts. Needs sway,
# dbus, at-spi2-core and libglib2.0-bin (gdbus). The compositor log goes to
# $DOVE_CI_ARTIFACTS (default ./artifacts/linux-sway).
set -euo pipefail
(($#)) || { echo "usage: sway-session.sh <command> [args...]" >&2; exit 2; }

artifacts="${DOVE_CI_ARTIFACTS:-$PWD/artifacts/linux-sway}"
mkdir -p "$artifacts"
runtime_dir="$(mktemp -d)"
sway_config="$(mktemp)"
compositor_pid=""
dbus_pid=""
atspi_pid=""

cleanup() {
  [[ -n "$compositor_pid" ]] && { kill "$compositor_pid" 2>/dev/null || true; wait "$compositor_pid" 2>/dev/null || true; }
  [[ -n "$atspi_pid" ]] && { kill "$atspi_pid" 2>/dev/null || true; wait "$atspi_pid" 2>/dev/null || true; }
  [[ -n "$dbus_pid" ]] && kill "$dbus_pid" 2>/dev/null || true
  rm -f "$sway_config"
}
trap cleanup EXIT

chmod 700 "$runtime_dir"
cat > "$sway_config" <<'EOF'
xwayland disable
output HEADLESS-1 mode 1920x1080
seat seat0 fallback true
focus_follows_mouse no
default_border none
default_floating_border none
for_window [title="^CuaTestHarness"] floating enable, resize set 940 780, move position 0 0
for_window [title="CuaTestHarness Sentinel"] fullscreen enable
EOF

unset DISPLAY WAYLAND_DISPLAY
export XDG_RUNTIME_DIR="$runtime_dir"
export XDG_SESSION_TYPE=wayland XDG_CURRENT_DESKTOP=sway XDG_SESSION_DESKTOP=sway
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_RENDERER_ALLOW_SOFTWARE=1
export WLR_LIBINPUT_NO_DEVICES=1 WLR_HEADLESS_OUTPUTS=1
export CUA_DRIVER_RS_ENABLE_WAYLAND=1
export CUA_E2E_WAYLAND_SESSION=sway CUA_E2E_COMPOSITOR=sway
export CUA_E2E_INPUT_BACKENDS=atspi,wlr-virtual-pointer
export CUA_WAYLAND_RECORDING_OUTPUT=HEADLESS-1
export GDK_BACKEND=wayland QT_QPA_PLATFORM=wayland ELECTRON_OZONE_PLATFORM_HINT=wayland
export NO_AT_BRIDGE=0 ACCESSIBILITY_ENABLED=1

dbus_info="$(dbus-daemon --session --fork --print-address=1 --print-pid=1)"
export DBUS_SESSION_BUS_ADDRESS="$(sed -n '1p' <<< "$dbus_info")"
dbus_pid="$(sed -n '2p' <<< "$dbus_info")"

wait_for() {  # wait_for <seconds> <description> <command...>
  local seconds="$1" what="$2"; shift 2
  local deadline=$((SECONDS + seconds))
  until "$@" >/dev/null 2>&1; do
    ((SECONDS < deadline)) || { echo "$what did not become ready within ${seconds}s" >&2; return 1; }
    sleep 0.2
  done
}

# A private session bus does not start the accessibility stack by itself.
launcher="${CUA_AT_SPI_BUS_LAUNCHER:-}"
for candidate in "$launcher" /usr/libexec/at-spi-bus-launcher "$(command -v at-spi-bus-launcher || true)"; do
  [[ -n "$candidate" && -x "$candidate" ]] && { launcher="$candidate"; break; }
done
[[ -x "$launcher" ]] || { echo "at-spi-bus-launcher not found" >&2; exit 1; }
"$launcher" --launch-immediately > "$artifacts/at-spi-bus.log" 2>&1 &
atspi_pid=$!
wait_for 15 "org.a11y.Bus" gdbus call --session --dest org.a11y.Bus \
  --object-path /org/a11y/bus --method org.a11y.Bus.GetAddress \
  || { cat "$artifacts/at-spi-bus.log" >&2; exit 1; }
a11y_address="$(gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus \
  --method org.a11y.Bus.GetAddress | sed -e "s/^('//" -e "s/',)$//")"
export AT_SPI_BUS_ADDRESS="$a11y_address"
wait_for 15 "AT-SPI registry" gdbus call --address "$a11y_address" \
  --dest org.a11y.atspi.Registry --object-path /org/a11y/atspi/accessible/root \
  --method org.freedesktop.DBus.Properties.Get org.a11y.atspi.Accessible ChildCount
gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus \
  --method org.freedesktop.DBus.Properties.Set org.a11y.Status IsEnabled '<true>' >/dev/null

sway --unsupported-gpu --config "$sway_config" > "$artifacts/sway.log" 2>&1 &
compositor_pid=$!
deadline=$((SECONDS + 20))
while [[ -z "${WAYLAND_DISPLAY:-}" ]]; do
  kill -0 "$compositor_pid" 2>/dev/null || { echo "sway exited early" >&2; cat "$artifacts/sway.log" >&2; exit 1; }
  ((SECONDS < deadline)) || { echo "sway made no Wayland socket in 20s" >&2; cat "$artifacts/sway.log" >&2; exit 1; }
  socket="$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -type s -name 'wayland-*' -print -quit)"
  [[ -n "$socket" ]] && export WAYLAND_DISPLAY="$(basename "$socket")"
  sleep 0.2
done
SWAYSOCK="$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -type s -name 'sway-ipc.*.sock' -print -quit)"
[[ -n "$SWAYSOCK" ]] || { echo "sway exposed no IPC socket" >&2; exit 1; }
export SWAYSOCK

echo "headless Sway on $WAYLAND_DISPLAY, AT-SPI at $AT_SPI_BUS_ADDRESS"
set +e
"$@"
status=$?
set -e
((status == 0)) || swaymsg -t get_tree > "$artifacts/sway-tree.json" 2>/dev/null || true
exit "$status"
