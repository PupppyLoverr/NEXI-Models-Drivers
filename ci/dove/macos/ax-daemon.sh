#!/usr/bin/env bash
# Start (or stop) a TCC-authorized dove-driver daemon on a disposable,
# GitHub-hosted macOS runner, for the AX e2e suites.
#
#   ci/dove/macos/ax-daemon.sh start <dove-driver binary> <evidence dir>
#   ci/dove/macos/ax-daemon.sh stop  <evidence dir>
#
# macOS gives Accessibility to an app identity, and the driver keeps its own
# TCC responsibility only when it runs from .../CuaDriver.app/Contents/MacOS/.
# Until R0.3 gives dove-driver its own app identity, the release identity is
# still upstream's CuaDriver.app / com.trycua.driver, so this:
#   1. wraps the built dove-driver in /Applications/CuaDriver.app
#      (rust/scripts/CuaDriverBundle, ad hoc signed for this one build),
#   2. seeds Accessibility and Screen Recording for that identity with the
#      fork's tests/runners/macos-lume/seed-tcc-guest.sh (needs SIP disabled
#      and a VirtualMac, which GitHub's hosted macOS runners are),
#   3. records the per-app screen-capture approval macOS 15+ asks for,
#   4. launches the app through LaunchServices as an unrestricted daemon and
#      waits until it reports both grants.
# Writes DOVE_CI_MACOS_SOCKET to $GITHUB_ENV. Refuses to run anywhere but a
# GitHub-hosted runner, because it edits the system TCC database.
set -euo pipefail

APP=/Applications/CuaDriver.app
BUNDLE_ID=com.trycua.driver
action="${1:?usage: ax-daemon.sh start <binary> <evidence dir> | stop <evidence dir>}"
fork_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
socket="${HOME}/Library/Caches/dove-driver/dove-driver.sock"

fail() { echo "ax-daemon: $*" >&2; exit 2; }

if [[ "$action" == stop ]]; then
  evidence="${2:?evidence dir}"
  mkdir -p "$evidence"
  if [[ -x "$APP/Contents/MacOS/dove-driver" ]]; then
    "$APP/Contents/MacOS/dove-driver" --socket "$socket" permissions status --json \
      > "$evidence/permissions-final.json" 2>&1 || true
    "$APP/Contents/MacOS/dove-driver" --socket "$socket" stop >/dev/null 2>&1 || true
  fi
  /usr/bin/log show --last 30m --style compact \
    --predicate 'process == "dove-driver" OR process == "tccd"' \
    > "$evidence/unified-log.txt" 2>&1 || true
  exit 0
fi

[[ "$action" == start ]] || fail "unknown action: $action"
binary="${2:?dove-driver binary}"
evidence="${3:?evidence dir}"
mkdir -p "$evidence"

[[ "$(uname -s)" == Darwin ]] || fail "requires macOS"
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_ENVIRONMENT:-}" == github-hosted ]] \
  || fail "edits the system TCC database; runs only on a disposable GitHub-hosted runner"
[[ -x "$binary" ]] || fail "driver binary missing: $binary"
[[ ! -e "$APP" ]] || fail "refusing a runner with a pre-existing $APP"
sudo -n -v >/dev/null 2>&1 || fail "requires the hosted runner's non-interactive sudo"

{
  sw_vers
  echo "model=$(sysctl -n hw.model)"
  csrutil status 2>&1 || true
  echo "user=$(id -un) console=$(stat -f '%Su' /dev/console)"
} > "$evidence/environment.txt"

echo "[bundle] $APP around $binary"
stage="$(mktemp -d)/CuaDriver.app"
cp -R "$fork_root/rust/scripts/CuaDriverBundle" "$stage"
rm -f "$stage/Contents/MacOS/.gitkeep"
cp "$binary" "$stage/Contents/MacOS/dove-driver"
chmod +x "$stage/Contents/MacOS/dove-driver"
plutil -replace CFBundleExecutable -string dove-driver "$stage/Contents/Info.plist"
plutil -replace CFBundleIdentifier -string "$BUNDLE_ID" "$stage/Contents/Info.plist"
codesign --force --sign - --identifier "$BUNDLE_ID" \
  --entitlements "$fork_root/rust/scripts/CuaDriver.entitlements" "$stage"
codesign --verify --deep --strict "$stage"
mv "$stage" "$APP"
codesign -dvvv -r- "$APP" > "$evidence/codesign.txt" 2>&1

echo "[tcc] seeding Accessibility + Screen Recording for $BUNDLE_ID (ad hoc, this build only)"
bash "$fork_root/tests/runners/macos-lume/seed-tcc-guest.sh" \
  --app "$APP" --expected-client "$BUNDLE_ID" --allow-adhoc \
  2>&1 | tee "$evidence/seed-tcc.log"

approvals="${HOME}/Library/Group Containers/group.com.apple.replayd/ScreenCaptureApprovals.plist"
mkdir -p "$(dirname "$approvals")"
defaults write "$approvals" "$BUNDLE_ID" -dict \
  kScreenCaptureApprovalLastAlerted -date "3024-01-01 00:00:00 +0000" \
  kScreenCaptureApprovalLastUsed -date "3024-01-01 00:00:00 +0000"
killall -HUP replayd >/dev/null 2>&1 || true

echo "[daemon] launching $APP via LaunchServices on $socket"
mkdir -p "$(dirname "$socket")"
open -n -g "$APP" --args --socket "$socket" serve \
  --permission-mode unrestricted --dangerously-bypass-approvals

for _ in {1..60}; do
  if "$APP/Contents/MacOS/dove-driver" --socket "$socket" permissions status --json \
      > "$evidence/permissions.json" 2> "$evidence/permissions.err" \
     && python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); sys.exit(0 if p.get("accessibility") is True and p.get("screen_recording") is True else 1)' \
      "$evidence/permissions.json"; then
    echo "[daemon] ready: $(tr -d '\n' < "$evidence/permissions.json")"
    "$APP/Contents/MacOS/dove-driver" --socket "$socket" status > "$evidence/status.txt" 2>&1 || true
    [[ -n "${GITHUB_ENV:-}" ]] && echo "DOVE_CI_MACOS_SOCKET=$socket" >> "$GITHUB_ENV"
    exit 0
  fi
  sleep 1
done
cat "$evidence/permissions.json" "$evidence/permissions.err" >&2 || true
fail "daemon did not report the seeded Accessibility and Screen Recording grants"
