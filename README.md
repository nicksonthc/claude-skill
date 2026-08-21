# claude-skill

Version-controlled home for my personal Claude Code skills. This repo is the
source of truth; `~/.claude/skills/` holds symlinks back into it, so editing a
skill here immediately changes the skill Claude Code loads.

## Skills

| Skill                                    | What it does                                                                                  |
| ---------------------------------------- | --------------------------------------------------------------------------------------------- |
| [`network-diagram`](skills/network-diagram/) | Renders a printable engineering-blueprint network topology as one self-contained 1920x1080 HTML file. |

## Install

Symlink a skill into the global skills directory:

```bash
ln -s "$PWD/skills/network-diagram" ~/.claude/skills/network-diagram
```

Then invoke it as `/network-diagram`, or just ask for a network diagram and
Claude will pick it up from the description.

To install every skill in this repo:

```bash
for s in skills/*/; do
  ln -sfn "$PWD/$s" "$HOME/.claude/skills/$(basename "$s")"
done
```

Verify Claude Code sees them with `/skills`.

## Layout

```
skills/<name>/
├── SKILL.md            # entry point, <100 lines, frontmatter name + description
├── REFERENCE.md        # full spec, loaded only when needed
├── INPUT-TEMPLATE.md   # fill-in form for the skill's inputs
└── examples/           # canonical reference output + provenance
```

`SKILL.md`'s `description` is the only text Claude sees when choosing a skill,
so it carries the trigger words. Keep detail in `REFERENCE.md`.

## Provenance

`network-diagram` began as a copy-paste prompt
(`skills/network-diagram/examples/original-prompt.v1.md`) that lived only in
gitignored directories in two unrelated repos. It was converted to a skill and
corrected against its own reference render — see
[skills/network-diagram/CHANGELOG.md](skills/network-diagram/CHANGELOG.md) for
what was wrong.

Because it grew out of real client work, every identifier was genericised
before this repo was made public: the bundled reference render is a fictional
project on fictional hosts, and the skill now refuses to put credentials in a
drawing at all. The `v3` entry in that changelog lists exactly what changed.
