# Anchor Release Policy

Anchor has two sources:

- Development source: `/Users/eric/Desktop/Anchor/skills/anchor/`
- Installed runtime copy: `/Users/eric/.codex/skills/anchor/`

Before publishing a package:

- Sync and verify the installed runtime copy matches the development source.
- Build with `scripts/package_skill.sh`.
- Publish only the package tree: `SKILL.md`, `references/`, and `scripts/`.
- Record user-visible changes in `references/changelog.md`.

Do not publish development project files, tests, docs, AGENTS files, `.anchor/`, `.git/`, or build output.
