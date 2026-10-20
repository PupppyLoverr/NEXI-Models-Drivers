# Paths that exist only in the fork. Sourced by sync-upstream.sh and parity-check.sh.
# Anything else on `main` must equal the `upstream` branch after apply-dove-changes.sh.
DOVE_ONLY_FILES=(
  README.md
  NOTICE.md
  ROADMAP.md
  NEXI_CUA_COMPARISON.md
  .gitignore
  scripts/dove
  bench
)
