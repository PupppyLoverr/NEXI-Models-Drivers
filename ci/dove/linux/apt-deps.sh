#!/usr/bin/env bash
# Install the Ubuntu packages one dove-driver CI job needs.
#
#   ci/dove/linux/apt-deps.sh <build|x11|sway>
#
#   build  Rust build dependencies of the driver only.
#   x11    build + Xvfb, openbox, picom, AT-SPI and the GTK3 fixture runtime.
#   sway   build + headless Sway, AT-SPI and the GTK3 fixture runtime.
# Package lists follow upstream's e2e-rust-linux*.yml (trycua/cua, MIT).
set -euo pipefail
kind="${1:?usage: apt-deps.sh <build|x11|sway>}"
build=(clang pkg-config libdbus-1-dev libpipewire-0.3-dev libspa-0.2-dev libei-dev
  libwayland-dev libxkbcommon-dev libx11-dev libxi-dev libxtst-dev libxext-dev
  libxdo-dev libssl-dev libdrm-dev libgbm-dev jq)
gtk=(python3-gi gir1.2-gtk-3.0 libgtk-3-dev at-spi2-core dbus dbus-x11 libglib2.0-bin)
case "$kind" in
  build) pkgs=("${build[@]}") ;;
  x11) pkgs=("${build[@]}" "${gtk[@]}" xvfb openbox picom x11-utils ffmpeg) ;;
  sway) pkgs=("${build[@]}" "${gtk[@]}" sway grim wtype wf-recorder ffmpeg) ;;
  *) echo "unknown kind: $kind" >&2; exit 2 ;;
esac
sudo apt-get update
sudo apt-get install -y --no-install-recommends "${pkgs[@]}"
