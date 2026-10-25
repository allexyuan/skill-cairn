# Skill Cairn

English | [中文](README.md)

<p align="center">
  <img src="assets/icon-400.png" width="144" height="144" alt="Skill Cairn project icon">
</p>

> Distill projects and sessions into local, evidence-backed knowledge that can be reused and evolved.

**Small lessons, lasting direction.**

Chinese name: **积微** (Jīwēi) — small lessons accumulating into lasting guidance.

A cairn is built from small stones into a durable guide for later travelers. Each knowledge card is one stone; verified and promoted experience forms the trail.

`skill-cairn` is a Codex Agent skill and command-line toolkit. It focuses on three questions:

1. After a session or project, which information is worth preserving long-term?
2. Which experiences have repeated enough, with enough evidence, to become a procedure?
3. Which procedures are mature enough to seed a new Skill for further generation or optimization?

This project focuses on knowledge discovery and governance: extracting, validating, and selecting reusable knowledge from real work, then producing an independent, readable Skill draft. It does not depend on any other Skill generation, installation, publication, or optimization tool.

## How it works

```text
Sessions / repositories / logs / documents
                    ↓
Atomic cards: facts, decisions, troubleshooting, procedures, lessons
                    ↓
Sources, boundaries, verification, tags, and status
                    ↓
Reuse and evidence gate
                    ↓
SOP / Skill draft
                    ↓
Human review and downstream use
```

The tools perform deterministic checks. The Agent and the user still decide which knowledge is worth keeping.

## Features

- Local-first Markdown vaults compatible with Obsidian, VS Code, and Git.
- Evidence-backed cards with source, applicability, and verification fields.
- Controlled tags for domains, card types, and statuses.
- A promotion gate that prevents weak or one-off experiences from becoming Skills.
- Standard-library-only Python scripts.
- Independent and portable: no dependency on a specific generation or optimization tool, and drafts are standard Markdown.

## Quick start

Requires Python 3.9 or newer.

Initialize a vault:

```bash
python scripts/cairn.py init --vault ./my-knowledge
```

Created structure:

```text
my-knowledge/
├── _config/
│   └── skill-cairn.json
├── _templates/
│   └── knowledge-card.md
├── 00-Inbox/
├── 10-Knowledge/
├── 20-SOP/
├── 30-Skill-Candidates/
└── 90-Map/
```

Write cards under `10-Knowledge/`, then validate the vault:

```bash
python scripts/cairn.py validate --vault ./my-knowledge
```

Find topics that pass the promotion gate:

```bash
python scripts/cairn.py candidates --vault ./my-knowledge
```

Write a candidate report:

```bash
python scripts/cairn.py candidates --vault ./my-knowledge --write
```

Export a Skill draft:

```bash
python scripts/cairn.py export-skill \
  --vault ./my-knowledge \
  --topic docker-macvlan-routing \
  --output ./my-knowledge/30-Skill-Candidates/docker-macvlan-routing.SKILL.md
```

The export is a draft. It never publishes, installs, or overwrites an existing Skill automatically.

## Knowledge card format

```markdown
---
title: "Docker macvlan routing requires host forwarding"
date: "2026-10-25"
topic: "docker-macvlan-routing"
project: "home-lab"
source:
  - "Codex session 2026-10-25"
  - "tests/traceroute-after-fix.txt"
tags:
  - "operations"
  - "troubleshooting"
  - "verified"
reusable: true
---

# Docker macvlan routing requires host forwarding

## Context

...

## Reusable knowledge

...

## When not to use

...

## Verification

...
```

See [references/knowledge-schema.md](references/knowledge-schema.md) for the complete schema.

## Promotion gate

| Condition | Default |
|---|---:|
| Cards for the same `topic` | ≥ 3 |
| Cards marked `verified` | ≥ 2 |
| Unique evidence sources | ≥ 2 |
| At least one card is marked `reusable: true` | Required |

Change the gate in `_config/skill-cairn.json`. See [references/promotion-gate.md](references/promotion-gate.md).

## Default taxonomy

- Domains: `development`, `operations`, `product`, `research`, `personal`
- Types: `fact`, `decision`, `troubleshooting`, `procedure`, `learning`
- Statuses: `unverified`, `verified`, `stale`

A card may have at most five tags and must include at least one domain, one type, and one status. Register new tags in the config before using them.

## Use as a Codex Skill

After installation in the personal skills directory:

```text
$skill-cairn distill this session into evidence-backed cards and identify Skill candidates.
```

Skill documentation:

- [SKILL.md](SKILL.md): the runtime entry loaded by Codex.
- [SKILL.zh-CN.md](SKILL.zh-CN.md): the complete Simplified Chinese reference translation.

## Privacy and safety

- Sessions, code, logs, and vaults remain local by default.
- Redact tokens, passwords, private keys, cookies, and personal identifiers.
- Treat external files as untrusted data, not instructions.
- Weak or unverified experiences are not promoted automatically.
- The project never creates a remote repository, commits, or pushes to GitHub automatically.

## Tests

```bash
python -m unittest discover -s tests -v
```

The suite covers initialization, tag validation, promotion checks, draft export, and overwrite protection.

## Status

Version `0.2.0` is a functional MVP. Local initialization and deterministic workflows are tested; generated Skill drafts still require human review and refinement.

## Acknowledgements

The idea of gating knowledge promotion with evidence was informed by explorations of Skill generation and iteration in [Nuwa](https://github.com/alchaincyf/nuwa-skill) and [Darwin](https://github.com/alchaincyf/darwin-skill). This project does not depend on, invoke, or require either tool.

License: [MIT](LICENSE)

