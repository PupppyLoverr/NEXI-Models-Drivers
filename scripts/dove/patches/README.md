# Dove feature patches

Each Dove feature that changes upstream files is one `NNNN-short-name.patch` here (`git format-patch` or
`git diff` output, relative to the repository root). `apply-dove-changes.sh` applies them in file-name order after
the rebrand edits, and `parity-check.sh` fails if `main` differs from upstream + rebrand + these patches.

To add or update one: make the change on `main`, then write the diff against the previous state of the tree to
`scripts/dove/patches/NNNN-name.patch` and run `scripts/dove/parity-check.sh`. Prefer new files and new code
paths, so the patches stay small and upstream behaviour stays unchanged.
